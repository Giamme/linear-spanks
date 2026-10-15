"""Secure installer for the external Caveman skill bundle."""

from __future__ import annotations

import argparse
import bz2
import gzip
import lzma
import os
import re
import shutil
import stat
import sys
import tarfile
import tempfile
import urllib.request
import uuid
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import IO, cast

from ..core.errors import ExitCode, FilesystemError, GovernedStop, LinearSpanksError, UsageError
from ..core.jsonio import read_text
from .clients import ClientSpec, client_registry
from .snapshots import (
    ABSENT_PATH,
    PathSnapshot,
    matches_snapshot,
    publish_staged_exclusive,
    quarantine_expected,
    require_unchanged,
    snapshot_path,
    text_path_snapshot,
    vacate_expected,
    write_text_exclusive,
)

UPSTREAM_REPOSITORY = "https://github.com/JuliusBrussee/caveman"
UPSTREAM_ARCHIVE = "https://codeload.github.com/JuliusBrussee/caveman/tar.gz"
CORE_SKILLS = ("caveman",)
ALL_SKILLS = (
    "cavecrew",
    "caveman",
    "caveman-commit",
    "caveman-compress",
    "caveman-help",
    "caveman-review",
    "caveman-stats",
)
CACHE_MARKER = ".linear-spanks-caveman-cache"
COPY_MARKER = ".linear-spanks-caveman-source"
OWNERSHIP_RECORD = ".linear-spanks-caveman-managed"
REF_RE = re.compile(r"^[A-Za-z0-9._/-]+$")


@dataclass(frozen=True, slots=True)
class ArchiveLimits:
    archive_bytes: int = 64 * 1024 * 1024
    expanded_bytes: int = 256 * 1024 * 1024
    members: int = 10_000
    metadata_bytes: int = 64 * 1024
    path_bytes: int = 4 * 1024


DEFAULT_LIMITS = ArchiveLimits()


@dataclass(slots=True)
class CavemanInstallPlan:
    changes: list[tuple[Path, Path | None]]
    record: Path
    ownership: Mapping[str, str]
    remove_record: bool
    success_message: str
    expected_record: PathSnapshot
    expected_targets: Mapping[Path, PathSnapshot]


@dataclass(frozen=True, slots=True)
class StagedCaveman:
    source: Path
    temporary_root: Path
    expected_cache: PathSnapshot | None = None


@dataclass(frozen=True, slots=True)
class CavemanCachePlan:
    staged: Path
    target: Path
    expected: PathSnapshot


def _exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def validate_ref(ref: str) -> str:
    if REF_RE.fullmatch(ref) is None or ".." in ref:
        raise UsageError("INVALID_REF", f"Invalid ref: {ref}")
    return ref


class _BoundedArchiveReader:
    """Count decompressed tar bytes, including headers and extension records."""

    def __init__(self, source: IO[bytes], limit: int) -> None:
        self._source = source
        self._limit = limit
        self._read = 0

    def read(self, size: int = -1) -> bytes:
        requested = self._limit - self._read + 1
        if size >= 0:
            requested = min(requested, size)
        data = self._source.read(requested)
        self._read += len(data)
        if self._read > self._limit:
            raise UsageError(
                "ARCHIVE_EXPANDED_SIZE_LIMIT",
                f"Archive expands beyond {self._limit} bytes",
            )
        return data


@contextmanager
def _decompressed_archive(archive: Path, limits: ArchiveLimits) -> Iterator[_BoundedArchiveReader]:
    with archive.open("rb") as raw:
        signature = raw.read(6)
        raw.seek(0)
        if signature.startswith(b"\x1f\x8b"):
            with gzip.GzipFile(fileobj=raw) as gzip_stream:
                yield _BoundedArchiveReader(cast(IO[bytes], gzip_stream), limits.expanded_bytes)
            return
        if signature.startswith(b"BZh"):
            with bz2.BZ2File(raw) as bz2_stream:
                yield _BoundedArchiveReader(bz2_stream, limits.expanded_bytes)
            return
        if signature.startswith(b"\xfd7zXZ\x00"):
            with lzma.LZMAFile(raw) as xz_stream:
                yield _BoundedArchiveReader(xz_stream, limits.expanded_bytes)
            return
        yield _BoundedArchiveReader(raw, limits.expanded_bytes)


def _read_exact(source: _BoundedArchiveReader, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = source.read(min(1024 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _discard_exact(source: _BoundedArchiveReader, size: int) -> None:
    remaining = size
    while remaining:
        chunk = source.read(min(1024 * 1024, remaining))
        if not chunk:
            raise UsageError("INVALID_ARCHIVE", "Archive ended inside a member payload")
        remaining -= len(chunk)


def _preflight_raw_archive(archive: Path, limits: ArchiveLimits) -> None:
    """Reject oversized tar metadata before tarfile materializes GNU/PAX values."""

    extension_types = {
        tarfile.GNUTYPE_LONGNAME,
        tarfile.GNUTYPE_LONGLINK,
        tarfile.XHDTYPE,
        tarfile.XGLTYPE,
    }
    long_value_types = {tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK}
    header_count = 0
    with _decompressed_archive(archive, limits) as source:
        while True:
            block = _read_exact(source, tarfile.BLOCKSIZE)
            if not block:
                break
            if len(block) != tarfile.BLOCKSIZE:
                raise UsageError("INVALID_ARCHIVE", "Archive has a truncated tar header")
            if block == tarfile.NUL * tarfile.BLOCKSIZE:
                break
            header_count += 1
            if header_count > limits.members:
                raise UsageError(
                    "ARCHIVE_MEMBER_LIMIT",
                    f"Archive contains more than {limits.members} members or metadata headers",
                )
            try:
                member = tarfile.TarInfo.frombuf(block, tarfile.ENCODING, "surrogateescape")
            except tarfile.HeaderError as error:
                raise UsageError("INVALID_ARCHIVE", f"Invalid tar header: {error}") from error
            if member.size < 0:
                raise UsageError("INVALID_ARCHIVE_MEMBER", "Archive member size is negative")
            if member.type in extension_types:
                metadata_limit = (
                    limits.path_bytes + 1
                    if member.type in long_value_types
                    else limits.metadata_bytes
                )
                if member.size > metadata_limit:
                    code = (
                        "ARCHIVE_PATH_LIMIT"
                        if member.type in long_value_types
                        else "ARCHIVE_METADATA_LIMIT"
                    )
                    raise UsageError(
                        code,
                        f"Archive metadata record exceeds {metadata_limit} bytes",
                    )
            payload_size = member.size + (-member.size % tarfile.BLOCKSIZE)
            _discard_exact(source, payload_size)


def _safe_member_path(name: str, *, max_bytes: int = 4 * 1024) -> PurePosixPath:
    if not name or "\x00" in name or "\\" in name:
        raise UsageError("UNSAFE_ARCHIVE_PATH", f"Unsafe archive path: {name!r}")
    if len(name.encode("utf-8", "surrogatepass")) > max_bytes:
        raise UsageError("ARCHIVE_PATH_LIMIT", f"Archive path exceeds {max_bytes} encoded bytes")
    raw_parts = name.split("/")
    if name.startswith("/") or any(part in {"", ".", ".."} for part in raw_parts):
        raise UsageError("UNSAFE_ARCHIVE_PATH", f"Unsafe archive path: {name}")
    path = PurePosixPath(name)
    if path.is_absolute():
        raise UsageError("UNSAFE_ARCHIVE_PATH", f"Unsafe archive path: {name}")
    return path


def _iter_validated_members(
    members: Iterable[tarfile.TarInfo], limits: ArchiveLimits
) -> Iterator[tuple[tarfile.TarInfo, PurePosixPath]]:
    expanded = 0
    seen: set[PurePosixPath] = set()
    for member_count, member in enumerate(members, start=1):
        if member_count > limits.members:
            raise UsageError(
                "ARCHIVE_MEMBER_LIMIT",
                f"Archive contains more than {limits.members} members",
            )
        path = _safe_member_path(member.name.rstrip("/"), max_bytes=limits.path_bytes)
        if path in seen:
            raise UsageError("DUPLICATE_ARCHIVE_MEMBER", f"Duplicate archive member: {path}")
        seen.add(path)
        if member.issym():
            raise UsageError("ARCHIVE_LINK_REJECTED", f"Archive contains symbolic link: {path}")
        if member.islnk():
            raise UsageError("ARCHIVE_LINK_REJECTED", f"Archive contains hard link: {path}")
        if member.isdev() or member.isfifo() or not (member.isdir() or member.isreg()):
            raise UsageError("ARCHIVE_SPECIAL_FILE", f"Archive contains special member: {path}")
        if member.size < 0:
            raise UsageError("INVALID_ARCHIVE_MEMBER", f"Archive member has invalid size: {path}")
        if member.isreg():
            expanded += member.size
            if expanded > limits.expanded_bytes:
                raise UsageError(
                    "ARCHIVE_EXPANDED_SIZE_LIMIT",
                    f"Archive expands beyond {limits.expanded_bytes} bytes",
                )
        yield member, path


def _validate_members(
    members: Iterable[tarfile.TarInfo], limits: ArchiveLimits
) -> list[tuple[tarfile.TarInfo, PurePosixPath]]:
    return list(_iter_validated_members(members, limits))


def _member_fingerprint(member: tarfile.TarInfo, path: PurePosixPath) -> tuple[object, ...]:
    return (
        str(path),
        member.type,
        member.size,
        member.mode,
        member.linkname,
    )


def _preflight_archive(archive: Path, limits: ArchiveLimits) -> tuple[tuple[object, ...], ...]:
    _preflight_raw_archive(archive, limits)
    try:
        with (
            _decompressed_archive(archive, limits) as source,
            tarfile.open(fileobj=cast(IO[bytes], source), mode="r|") as bundle,
        ):
            return tuple(
                _member_fingerprint(member, path)
                for member, path in _iter_validated_members(bundle, limits)
            )
    except UsageError:
        raise
    except (OSError, tarfile.TarError) as error:
        raise UsageError("INVALID_ARCHIVE", f"Unable to read archive: {error}") from error


def _copy_member(source: IO[bytes], target: Path, expected_size: int) -> None:
    written = 0
    with target.open("xb") as destination:
        while True:
            chunk = source.read(min(1024 * 1024, expected_size - written + 1))
            if not chunk:
                break
            written += len(chunk)
            if written > expected_size:
                raise UsageError(
                    "INVALID_ARCHIVE_MEMBER",
                    f"Archive member exceeded declared size: {target.name}",
                )
            destination.write(chunk)
    if written != expected_size:
        raise UsageError(
            "INVALID_ARCHIVE_MEMBER",
            f"Archive member size changed during extraction: {target.name}",
        )


def safe_extract_archive(
    archive: Path,
    destination: Path,
    *,
    limits: ArchiveLimits = DEFAULT_LIMITS,
) -> Path:
    if archive.stat().st_size > limits.archive_bytes:
        raise UsageError(
            "ARCHIVE_SIZE_LIMIT",
            f"Archive exceeds {limits.archive_bytes} bytes",
        )
    expected = _preflight_archive(archive, limits)
    destination.mkdir(parents=True, exist_ok=False)
    try:
        with (
            _decompressed_archive(archive, limits) as source,
            tarfile.open(fileobj=cast(IO[bytes], source), mode="r|") as bundle,
        ):
            actual_count = 0
            for member, relative in _iter_validated_members(bundle, limits):
                if (
                    actual_count >= len(expected)
                    or _member_fingerprint(member, relative) != expected[actual_count]
                ):
                    raise GovernedStop(
                        "ARCHIVE_SOURCE_DRIFT",
                        "Archive changed after its bounded preflight",
                    )
                actual_count += 1
                target = destination.joinpath(*relative.parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                extracted = bundle.extractfile(member)
                if extracted is None:
                    raise UsageError(
                        "INVALID_ARCHIVE_MEMBER",
                        f"Unable to read archive member: {relative}",
                    )
                with extracted:
                    _copy_member(extracted, target, member.size)
                os.chmod(target, member.mode & 0o755 or 0o644)
            if actual_count != len(expected):
                raise GovernedStop(
                    "ARCHIVE_SOURCE_DRIFT",
                    "Archive changed after its bounded preflight",
                )
        top_level = list(destination.iterdir())
        if len(top_level) != 1 or not top_level[0].is_dir() or top_level[0].is_symlink():
            raise UsageError(
                "INVALID_ARCHIVE_LAYOUT",
                "Archive must contain one top-level directory",
            )
        return top_level[0]
    except BaseException:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def download_archive(
    url: str,
    target: Path,
    *,
    limits: ArchiveLimits = DEFAULT_LIMITS,
) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "linear-spanks/1.0.0"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            content_length = response.headers.get("Content-Length")
            if content_length is not None and int(content_length) > limits.archive_bytes:
                raise UsageError(
                    "ARCHIVE_SIZE_LIMIT", f"Archive exceeds {limits.archive_bytes} bytes"
                )
            written = 0
            with target.open("xb") as stream:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > limits.archive_bytes:
                        raise UsageError(
                            "ARCHIVE_SIZE_LIMIT", f"Archive exceeds {limits.archive_bytes} bytes"
                        )
                    stream.write(chunk)
    except OSError as error:
        raise FilesystemError(
            "ARCHIVE_DOWNLOAD_FAILED", f"Unable to download Caveman: {error}"
        ) from error


def validate_skill_tree(
    root: Path,
    requested_skills: Sequence[str],
    *,
    limits: ArchiveLimits = DEFAULT_LIMITS,
) -> None:
    members = 0
    expanded = 0
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in [*directories, *files]:
            members += 1
            if members > limits.members:
                raise UsageError("ARCHIVE_MEMBER_LIMIT", "Caveman source contains too many members")
            path = current_path / name
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise UsageError(
                    "SOURCE_LINK_REJECTED",
                    f"Refusing Caveman skill containing symbolic links: {path}",
                )
            if stat.S_ISREG(metadata.st_mode):
                expanded += metadata.st_size
                if expanded > limits.expanded_bytes:
                    raise UsageError(
                        "ARCHIVE_EXPANDED_SIZE_LIMIT", "Caveman source exceeds expanded size limit"
                    )
            elif not stat.S_ISDIR(metadata.st_mode):
                raise UsageError(
                    "SOURCE_SPECIAL_FILE", f"Refusing Caveman source special file: {path}"
                )
    for name in requested_skills:
        skill_file = root / "skills" / name / "SKILL.md"
        if not skill_file.is_file() or skill_file.is_symlink():
            raise UsageError("INVALID_CAVEMAN_SOURCE", f"Caveman source is missing {name}/SKILL.md")
        content = skill_file.read_text(encoding="utf-8")
        if re.search(rf"^name:\s*{re.escape(name)}\s*$", content, re.MULTILINE) is None:
            raise UsageError("INVALID_CAVEMAN_SOURCE", f"Caveman skill name mismatch: {skill_file}")
        if re.search(r"^description:\s*.+$", content, re.MULTILINE) is None:
            raise UsageError(
                "INVALID_CAVEMAN_SOURCE", f"Caveman skill has no description: {skill_file}"
            )


def _managed_cache(cache: Path) -> bool:
    marker = cache / CACHE_MARKER
    if not (
        cache.is_dir() and not cache.is_symlink() and marker.is_file() and not marker.is_symlink()
    ):
        return False
    lines = read_text(marker).splitlines()
    return (
        len(lines) == 2
        and lines[0] == UPSTREAM_REPOSITORY
        and REF_RE.fullmatch(lines[1]) is not None
        and ".." not in lines[1]
    )


def swap_managed_cache(
    staged: Path,
    cache: Path,
    expected: PathSnapshot | None = None,
) -> None:
    cache.parent.mkdir(parents=True, exist_ok=True)
    expected_state = snapshot_path(cache) if expected is None else expected
    require_unchanged(cache, expected_state)
    if _exists(cache) and not _managed_cache(cache):
        raise UsageError("UNMANAGED_CACHE", f"Refusing to replace unmanaged cache: {cache}")
    staged_state = snapshot_path(staged)
    backup: Path | None = None
    installed_state = ABSENT_PATH
    started = False
    try:
        if expected_state != ABSENT_PATH:
            candidate = cache.with_name(f".{cache.name}.backup-{uuid.uuid4().hex}")
            vacate_expected(cache, expected_state, candidate)
            backup = candidate
            started = True
        try:
            publish_staged_exclusive(staged, cache)
        except BaseException:
            actual = snapshot_path(cache)
            if actual == staged_state:
                installed_state = staged_state
                started = True
            elif actual != ABSENT_PATH and backup is None:
                require_unchanged(cache, ABSENT_PATH)
            raise
        installed_state = staged_state
        started = True
        require_unchanged(cache, installed_state)
    except BaseException as error:
        if not started:
            raise
        rollback_failures: list[str] = []
        try:
            if backup is not None and not matches_snapshot(backup, expected_state):
                rollback_failures.append(f"concurrent cache backup drift: {backup}")
            if not rollback_failures:
                quarantine = quarantine_expected(cache, installed_state)
                if backup is not None:
                    publish_staged_exclusive(backup, cache)
                if quarantine is not None:
                    _cleanup(quarantine)
        except (LinearSpanksError, OSError) as failure:
            rollback_failures.append(str(failure))
        if rollback_failures:
            raise FilesystemError(
                "INSTALLATION_ROLLBACK_FAILED",
                "Caveman cache rollback preserved concurrent data: " + "; ".join(rollback_failures),
            ) from error
        raise
    if backup is not None:
        try:
            require_unchanged(backup, expected_state)
            _cleanup(backup)
        except (LinearSpanksError, OSError) as error:
            raise FilesystemError(
                "INSTALLATION_BACKUP_CLEANUP_FAILED",
                f"Caveman cache committed, but backup cleanup was incomplete: {backup}: {error}",
            ) from error


def stage_caveman(
    ref: str,
    cache: Path,
    *,
    archive_url: str = UPSTREAM_ARCHIVE,
    limits: ArchiveLimits = DEFAULT_LIMITS,
) -> StagedCaveman:
    validate_ref(ref)
    cache.parent.mkdir(parents=True, exist_ok=True)
    expected_cache = snapshot_path(cache)
    if _exists(cache) and not _managed_cache(cache):
        raise UsageError("UNMANAGED_CACHE", f"Refusing to replace unmanaged cache: {cache}")
    work = Path(tempfile.mkdtemp(prefix=".caveman-fetch-", dir=cache.parent))
    try:
        archive = work / "caveman.tar.gz"
        download_archive(f"{archive_url}/{ref}", archive, limits=limits)
        extracted = safe_extract_archive(archive, work / "extracted", limits=limits)
        validate_skill_tree(extracted, ALL_SKILLS, limits=limits)
        (extracted / CACHE_MARKER).write_text(f"{UPSTREAM_REPOSITORY}\n{ref}\n", encoding="utf-8")
        return StagedCaveman(
            source=extracted,
            temporary_root=work,
            expected_cache=expected_cache,
        )
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise


def fetch_caveman(
    ref: str,
    cache: Path,
    *,
    archive_url: str = UPSTREAM_ARCHIVE,
    limits: ArchiveLimits = DEFAULT_LIMITS,
) -> Path:
    staged = stage_caveman(ref, cache, archive_url=archive_url, limits=limits)
    try:
        swap_managed_cache(staged.source, cache, staged.expected_cache)
    finally:
        shutil.rmtree(staged.temporary_root, ignore_errors=True)
    return cache


def _read_record(path: Path) -> dict[str, str]:
    if path.is_symlink():
        raise UsageError("INVALID_OWNERSHIP_RECORD", f"Ownership record is a symlink: {path}")
    if not path.is_file():
        return {}
    result: dict[str, str] = {}
    for line in read_text(path).splitlines():
        fields = line.split("\t", 1)
        if len(fields) != 2 or not all(fields):
            raise UsageError("INVALID_OWNERSHIP_RECORD", f"Malformed ownership record: {path}")
        if fields[0] not in ALL_SKILLS or fields[0] in result:
            raise UsageError(
                "INVALID_OWNERSHIP_RECORD",
                f"Invalid Caveman skill in ownership record: {fields[0]!r}",
            )
        result[fields[0]] = fields[1]
    return result


def _is_managed_install(path: Path, expected_source: str) -> bool:
    if path.is_symlink():
        return str(path.readlink()) == expected_source
    marker = path / COPY_MARKER
    if path.is_dir() and marker.is_file() and not marker.is_symlink():
        lines = read_text(marker).splitlines()
        return lines == [UPSTREAM_REPOSITORY, expected_source]
    return False


def _cleanup(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.exists():
        shutil.rmtree(path)


def _stage_skill(
    source: Path,
    destination: Path,
    mode: str,
    *,
    installed_source: Path | None = None,
) -> Path:
    staged_root = Path(tempfile.mkdtemp(prefix=".caveman-stage-", dir=destination))
    staged = staged_root / source.name
    if mode == "link":
        staged.symlink_to(installed_source or source)
    else:
        shutil.copytree(source, staged)
        marker_source = installed_source or source
        (staged / COPY_MARKER).write_text(
            f"{UPSTREAM_REPOSITORY}\n{marker_source}\n",
            encoding="utf-8",
        )
    return staged


def _cleanup_staged_installs(changes: Sequence[tuple[Path, Path | None]]) -> None:
    for _, staged in changes:
        if staged is not None and _exists(staged.parent):
            _cleanup(staged.parent)


def _apply_install_plans(
    plans: Sequence[CavemanInstallPlan],
    *,
    cache_plan: CavemanCachePlan | None = None,
) -> None:
    for plan in plans:
        destination = plan.record.parent
        if not set(plan.ownership).issubset(ALL_SKILLS):
            raise UsageError(
                "INVALID_OWNERSHIP_RECORD",
                "Caveman ownership contains an undeclared skill",
            )
        for target, _ in plan.changes:
            if target.parent != destination or target.name not in ALL_SKILLS:
                raise UsageError(
                    "INVALID_OWNERSHIP_RECORD",
                    f"Managed Caveman target escapes its destination: {target}",
                )
    try:
        for plan in plans:
            require_unchanged(plan.record, plan.expected_record)
            for path, expected in plan.expected_targets.items():
                require_unchanged(path, expected)
        if cache_plan is not None:
            require_unchanged(cache_plan.target, cache_plan.expected)
    except BaseException:
        for plan in plans:
            _cleanup_staged_installs(plan.changes)
        raise
    backups: list[tuple[Path, Path | None]] = []
    cache_backup: Path | None = None
    cache_poststate = ABSENT_PATH
    cache_staged_state: PathSnapshot | None = None
    cache_started = False
    target_poststates: dict[Path, PathSnapshot] = {}
    backup_states: dict[Path, PathSnapshot] = {}
    record_poststates: dict[Path, PathSnapshot] = {}
    record_backups: dict[Path, Path | None] = {}
    record_backup_states: dict[Path, PathSnapshot] = {}
    try:
        if cache_plan is not None:
            cache_plan.target.parent.mkdir(parents=True, exist_ok=True)
            require_unchanged(cache_plan.target, cache_plan.expected)
            cache_staged_state = snapshot_path(cache_plan.staged)
            if cache_plan.expected != ABSENT_PATH:
                if not _managed_cache(cache_plan.target):
                    raise UsageError(
                        "UNMANAGED_CACHE",
                        f"Refusing to replace unmanaged cache: {cache_plan.target}",
                    )
                candidate = cache_plan.target.with_name(
                    f".{cache_plan.target.name}.backup-{uuid.uuid4().hex}"
                )
                vacate_expected(cache_plan.target, cache_plan.expected, candidate)
                cache_backup = candidate
                cache_started = True
            try:
                publish_staged_exclusive(cache_plan.staged, cache_plan.target)
            except BaseException:
                actual = snapshot_path(cache_plan.target)
                if actual == cache_staged_state:
                    cache_poststate = cache_staged_state
                    cache_started = True
                elif actual != ABSENT_PATH and cache_backup is None:
                    require_unchanged(cache_plan.target, ABSENT_PATH)
                raise
            cache_poststate = cache_staged_state
            cache_started = True
            require_unchanged(cache_plan.target, cache_staged_state)
        for plan in plans:
            for target, staged in plan.changes:
                expected_target = plan.expected_targets[target]
                require_unchanged(target, expected_target)
                backup: Path | None = None
                if expected_target != ABSENT_PATH:
                    candidate = target.with_name(f".{target.name}.backup-{uuid.uuid4().hex}")
                    vacate_expected(target, expected_target, candidate)
                    backup = candidate
                    backups.append((target, candidate))
                    backup_states[candidate] = expected_target
                    target_poststates[target] = ABSENT_PATH
                if staged is not None:
                    staged_state = snapshot_path(staged)
                    try:
                        publish_staged_exclusive(staged, target)
                    except BaseException:
                        actual = snapshot_path(target)
                        if actual == staged_state:
                            target_poststates[target] = staged_state
                            if not any(item[0] == target for item in backups):
                                backups.append((target, None))
                        elif actual != ABSENT_PATH and backup is None:
                            require_unchanged(target, ABSENT_PATH)
                        raise
                    target_poststates[target] = staged_state
                    if not any(item[0] == target for item in backups):
                        backups.append((target, None))
                    require_unchanged(target, staged_state)
                    staged.parent.rmdir()
        for plan in plans:
            require_unchanged(plan.record, plan.expected_record)
            if plan.expected_record != ABSENT_PATH:
                candidate = plan.record.with_name(f".{plan.record.name}.backup-{uuid.uuid4().hex}")
                vacate_expected(plan.record, plan.expected_record, candidate)
                record_backups[plan.record] = candidate
                record_backup_states[candidate] = plan.expected_record
                record_poststates[plan.record] = ABSENT_PATH
            if not plan.remove_record:
                content = "".join(
                    f"{name}\t{plan.ownership[name]}\n" for name in sorted(plan.ownership)
                )
                desired = text_path_snapshot(content)
                try:
                    write_text_exclusive(plan.record, content)
                except BaseException:
                    actual = snapshot_path(plan.record)
                    if actual == desired:
                        record_backups.setdefault(plan.record, None)
                        record_poststates[plan.record] = desired
                    elif actual != ABSENT_PATH and plan.record not in record_backups:
                        require_unchanged(plan.record, ABSENT_PATH)
                    raise
                record_backups.setdefault(plan.record, None)
                record_poststates[plan.record] = desired
                require_unchanged(plan.record, desired)
        for path, poststate in (*target_poststates.items(), *record_poststates.items()):
            require_unchanged(path, poststate)
        if cache_plan is not None and cache_started:
            require_unchanged(cache_plan.target, cache_poststate)
    except BaseException as error:
        rollback_failures: list[str] = []
        for record, backup in reversed(tuple(record_backups.items())):
            try:
                if backup is not None and not matches_snapshot(
                    backup, record_backup_states[backup]
                ):
                    rollback_failures.append(f"concurrent ownership-record backup drift: {backup}")
                    continue
                quarantine = quarantine_expected(record, record_poststates[record])
                if backup is not None and _exists(backup):
                    publish_staged_exclusive(backup, record)
                if quarantine is not None:
                    _cleanup(quarantine)
            except (LinearSpanksError, OSError) as failure:
                rollback_failures.append(str(failure))
        for target, backup in reversed(backups):
            try:
                if backup is not None and not matches_snapshot(backup, backup_states[backup]):
                    rollback_failures.append(f"concurrent backup drift: {backup}")
                    continue
                quarantine = quarantine_expected(target, target_poststates[target])
                if backup is not None and _exists(backup):
                    publish_staged_exclusive(backup, target)
                if quarantine is not None:
                    _cleanup(quarantine)
            except (LinearSpanksError, OSError) as failure:
                rollback_failures.append(str(failure))
        if cache_plan is not None and cache_started:
            try:
                if cache_backup is not None and not matches_snapshot(
                    cache_backup, cache_plan.expected
                ):
                    rollback_failures.append(f"concurrent cache backup drift: {cache_backup}")
                else:
                    quarantine = quarantine_expected(cache_plan.target, cache_poststate)
                    if cache_backup is not None and _exists(cache_backup):
                        publish_staged_exclusive(cache_backup, cache_plan.target)
                    if quarantine is not None:
                        _cleanup(quarantine)
            except (LinearSpanksError, OSError) as failure:
                rollback_failures.append(str(failure))
        for plan in plans:
            _cleanup_staged_installs(plan.changes)
        if rollback_failures:
            raise FilesystemError(
                "INSTALLATION_ROLLBACK_FAILED",
                "Caveman rollback preserved concurrent data: " + "; ".join(rollback_failures),
            ) from error
        raise
    cleanup_failures: list[str] = []
    for _, backup in backups:
        if backup is not None:
            try:
                require_unchanged(backup, backup_states[backup])
                _cleanup(backup)
            except (LinearSpanksError, OSError) as failure:
                cleanup_failures.append(f"{backup}: {failure}")
    for backup in record_backups.values():
        if backup is not None:
            try:
                require_unchanged(backup, record_backup_states[backup])
                _cleanup(backup)
            except (LinearSpanksError, OSError) as failure:
                cleanup_failures.append(f"{backup}: {failure}")
    if cache_backup is not None:
        try:
            assert cache_plan is not None
            require_unchanged(cache_backup, cache_plan.expected)
            _cleanup(cache_backup)
        except (LinearSpanksError, OSError) as failure:
            cleanup_failures.append(f"{cache_backup}: {failure}")
    if cleanup_failures:
        raise FilesystemError(
            "INSTALLATION_BACKUP_CLEANUP_FAILED",
            "Caveman installation committed, but backup cleanup was incomplete: "
            + "; ".join(cleanup_failures),
        )


def _apply_install_changes(
    changes: list[tuple[Path, Path | None]], record: Path, ownership: Mapping[str, str]
) -> None:
    _apply_install_plans(
        (
            CavemanInstallPlan(
                changes=changes,
                record=record,
                ownership=ownership,
                remove_record=False,
                success_message="",
                expected_record=snapshot_path(record),
                expected_targets={target: snapshot_path(target) for target, _ in changes},
            ),
        )
    )


def _prepare_install(
    client: ClientSpec,
    destination: Path,
    source_root: Path,
    requested_skills: Sequence[str],
    *,
    mode: str,
    uninstall: bool,
    stage: bool,
    installed_source_root: Path | None = None,
) -> CavemanInstallPlan:
    if any(name not in ALL_SKILLS for name in requested_skills):
        raise UsageError("INVALID_CAVEMAN_SKILL", "Requested Caveman skills are invalid")
    record = destination / OWNERSHIP_RECORD
    expected_record = snapshot_path(record)
    ownership = _read_record(record)
    changes: list[tuple[Path, Path | None]] = []
    expected_targets: dict[Path, PathSnapshot] = {}

    def watch(name: str) -> Path:
        target = destination / name
        expected_targets.setdefault(target, snapshot_path(target))
        return target

    if uninstall:
        for name, expected_source in sorted(ownership.items()):
            target = watch(name)
            if not _exists(target):
                continue
            if not _is_managed_install(target, expected_source):
                raise UsageError(
                    "UNMANAGED_ENTRY", f"Refusing to remove unmanaged Caveman entry: {target}"
                )
            changes.append((target, None))
        return CavemanInstallPlan(
            changes=changes,
            record=record,
            ownership={},
            remove_record=True,
            success_message=f"Uninstalled managed Caveman skills from {destination}",
            expected_record=expected_record,
            expected_targets=expected_targets,
        )

    next_ownership = dict(ownership)
    installed_root = installed_source_root or source_root
    install_sources: list[tuple[Path, Path, Path]] = []
    for name in requested_skills:
        source = source_root / "skills" / name
        installed_source = installed_root / "skills" / name
        target = watch(name)
        recorded_source = ownership.get(name)
        if target.is_symlink() and target.readlink() == installed_source and mode == "link":
            next_ownership[name] = str(installed_source)
            continue
        if _exists(target) and (
            recorded_source is None or not _is_managed_install(target, recorded_source)
        ):
            raise UsageError(
                "UNMANAGED_ENTRY",
                f"Destination exists and is not managed by this command: {target}",
            )
        install_sources.append((target, source, installed_source))
        next_ownership[name] = str(installed_source)
    try:
        if stage:
            destination.mkdir(parents=True, exist_ok=True)
        for target, source, installed_source in install_sources:
            changes.append(
                (
                    target,
                    _stage_skill(
                        source,
                        destination,
                        mode,
                        installed_source=installed_source,
                    )
                    if stage
                    else None,
                )
            )
    except BaseException:
        _cleanup_staged_installs(changes)
        raise
    return CavemanInstallPlan(
        changes=changes,
        record=record,
        ownership=next_ownership,
        remove_record=False,
        success_message=(
            f"Installed {len(requested_skills)} Caveman skills for {client.name} "
            f"in {destination} ({mode} mode)."
        ),
        expected_record=expected_record,
        expected_targets=expected_targets,
    )


def install_to(
    client: ClientSpec,
    destination: Path,
    source_root: Path,
    requested_skills: Sequence[str],
    *,
    mode: str,
    uninstall: bool,
) -> str:
    plan = _prepare_install(
        client,
        destination,
        source_root,
        requested_skills,
        mode=mode,
        uninstall=uninstall,
        stage=True,
    )
    _apply_install_plans((plan,))
    return plan.success_message


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--client", default="codex")
    parser.add_argument("--bundle", choices=("core", "all"), default="core")
    parser.add_argument("--mode", choices=("link", "copy"), default="link")
    parser.add_argument("--ref", default="main")
    parser.add_argument("--cache-dir")
    parser.add_argument("--source-dir")
    parser.add_argument("--dest")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--print-destinations", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None, environment: Mapping[str, str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    selected_environment = environment or os.environ
    registry = client_registry()
    plans: list[CavemanInstallPlan] = []
    staged_caveman: StagedCaveman | None = None
    cache_plan: CavemanCachePlan | None = None
    try:
        overrides: dict[str, Path | None] = {}
        for option, raw_value in (
            ("dest", args.dest),
            ("cache-dir", args.cache_dir),
            ("source-dir", args.source_dir),
        ):
            if raw_value is not None and (not raw_value or raw_value != raw_value.strip()):
                raise UsageError(
                    "INVALID_DESTINATION",
                    f"--{option} must be non-empty and trimmed",
                )
            overrides[option] = (
                Path(raw_value).expanduser().absolute() if raw_value is not None else None
            )
        destination_override = overrides["dest"]
        cache_override = overrides["cache-dir"]
        source_override = overrides["source-dir"]
        validate_ref(args.ref)
        clients = registry.expand(args.client)
        if destination_override is not None and len(clients) != 1:
            raise UsageError(
                "INVALID_DESTINATION", "--dest requires a selector that resolves to one client"
            )
        if args.print_destinations:
            for client in clients:
                destination = destination_override or client.skill_destination(selected_environment)
                print(f"{client.name}\t{destination}")
            return int(ExitCode.SUCCESS)
        requested = CORE_SKILLS if args.bundle == "core" else ALL_SKILLS
        if args.dry_run:
            print(f"Source: {source_override or f'JuliusBrussee/caveman@{args.ref}'}")
            print(f"Bundle: {args.bundle} ({' '.join(requested)})")
            print(f"Mode: {args.mode}")
            for client in clients:
                destination = (
                    destination_override
                    if destination_override is not None
                    else client.skill_destination(selected_environment)
                )
                print(f"{client.name}\t{destination}")
            return int(ExitCode.SUCCESS)
        home = Path(selected_environment.get("HOME") or Path.home())
        cache = (
            cache_override
            or (
                Path(selected_environment.get("XDG_CACHE_HOME") or home / ".cache")
                / "linear-spanks"
                / "extensions"
                / "caveman"
            )
            .expanduser()
            .absolute()
        )
        if source_override is not None:
            source_root = source_override
            if not source_root.is_dir():
                raise UsageError(
                    "INVALID_CAVEMAN_SOURCE", f"Caveman source does not exist: {source_root}"
                )
        elif args.uninstall:
            source_root = cache
        else:
            staged_caveman = stage_caveman(args.ref, cache)
            source_root = staged_caveman.source
            cache_plan = CavemanCachePlan(
                staged=source_root,
                target=cache,
                expected=staged_caveman.expected_cache or snapshot_path(cache),
            )
        if not args.uninstall:
            validate_skill_tree(source_root, requested)
        destinations = [
            (
                client,
                destination_override
                if destination_override is not None
                else client.skill_destination(selected_environment),
            )
            for client in clients
        ]
        for client, destination in destinations:
            _prepare_install(
                client,
                destination,
                source_root,
                requested,
                mode=args.mode,
                uninstall=args.uninstall,
                stage=False,
                installed_source_root=cache if cache_plan is not None else None,
            )
        for client, destination in destinations:
            plans.append(
                _prepare_install(
                    client,
                    destination,
                    source_root,
                    requested,
                    mode=args.mode,
                    uninstall=args.uninstall,
                    stage=True,
                    installed_source_root=cache if cache_plan is not None else None,
                )
            )
        _apply_install_plans(plans, cache_plan=cache_plan)
        for plan in plans:
            print(plan.success_message)
    except LinearSpanksError as error:
        print(f"Caveman installation error: {error.message}", file=sys.stderr)
        return int(error.exit_code)
    except (OSError, tarfile.TarError, UnicodeError, ValueError) as error:
        print(f"Caveman installation error: {error}", file=sys.stderr)
        return int(ExitCode.FILESYSTEM)
    finally:
        for plan in plans:
            _cleanup_staged_installs(plan.changes)
        if staged_caveman is not None:
            shutil.rmtree(staged_caveman.temporary_root, ignore_errors=True)
    return int(ExitCode.SUCCESS)
