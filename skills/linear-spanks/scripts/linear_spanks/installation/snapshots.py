"""Deterministic filesystem snapshots for installer compare-and-swap checks."""

from __future__ import annotations

import ctypes
import errno
import hashlib
import os
import stat
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from ..core.errors import FilesystemError, GovernedStop


@dataclass(frozen=True, slots=True)
class PathSnapshot:
    kind: str
    digest: str | None


def _tree_entries(path: Path, relative: str = "") -> list[str]:
    entries: list[str] = []
    with os.scandir(path) as children:
        for entry in sorted(children, key=lambda item: item.name):
            child_relative = f"{relative}/{entry.name}" if relative else entry.name
            metadata = entry.stat(follow_symlinks=False)
            mode = stat.S_IMODE(metadata.st_mode)
            if stat.S_ISLNK(metadata.st_mode):
                entries.append(f"link\0{child_relative}\0{mode:o}\0{os.readlink(entry.path)}")
            elif stat.S_ISREG(metadata.st_mode):
                digest = hashlib.sha256(Path(entry.path).read_bytes()).hexdigest()
                entries.append(f"file\0{child_relative}\0{mode:o}\0{digest}")
            elif stat.S_ISDIR(metadata.st_mode):
                entries.append(f"dir\0{child_relative}\0{mode:o}")
                entries.extend(_tree_entries(Path(entry.path), child_relative))
            else:
                entries.append(f"special\0{child_relative}\0{metadata.st_mode:o}")
    return entries


def snapshot_path(path: Path) -> PathSnapshot:
    """Capture type, content, links, and modes without following symlink targets."""

    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return PathSnapshot("absent", None)
    except OSError as error:
        raise FilesystemError(
            "INSTALLATION_SNAPSHOT_FAILED",
            f"Unable to inspect installation target {path}: {error}",
            details={"path": str(path)},
        ) from error
    try:
        mode = stat.S_IMODE(metadata.st_mode)
        if stat.S_ISLNK(metadata.st_mode):
            value = f"{mode:o}\0{os.readlink(path)}".encode()
            return PathSnapshot("symlink", hashlib.sha256(value).hexdigest())
        if stat.S_ISREG(metadata.st_mode):
            digest = hashlib.sha256(f"{mode:o}\0".encode() + path.read_bytes()).hexdigest()
            return PathSnapshot("file", digest)
        if stat.S_ISDIR(metadata.st_mode):
            entries = [f"root\0{mode:o}", *_tree_entries(path)]
            digest = hashlib.sha256("\n".join(entries).encode("utf-8")).hexdigest()
            return PathSnapshot("directory", digest)
        return PathSnapshot("special", hashlib.sha256(str(metadata.st_mode).encode()).hexdigest())
    except OSError as error:
        raise FilesystemError(
            "INSTALLATION_SNAPSHOT_FAILED",
            f"Unable to snapshot installation target {path}: {error}",
            details={"path": str(path)},
        ) from error


def require_unchanged(path: Path, expected: PathSnapshot) -> None:
    actual = snapshot_path(path)
    if actual != expected:
        raise GovernedStop(
            "INSTALLATION_TARGET_DRIFT",
            "Installation target changed after preview; produce a new preview",
            details={
                "path": str(path),
                "expected": {"kind": expected.kind, "digest": expected.digest},
                "actual": {"kind": actual.kind, "digest": actual.digest},
            },
        )


def matches_snapshot(path: Path, expected: PathSnapshot) -> bool:
    """Return whether a path still has the exact captured state."""

    return snapshot_path(path) == expected


ABSENT_PATH = PathSnapshot("absent", None)


def text_path_snapshot(content: str, *, mode: int = 0o600) -> PathSnapshot:
    """Return the snapshot produced by ``write_text_exclusive`` for ``content``."""

    payload = f"{mode:o}\0".encode() + content.encode("utf-8")
    return PathSnapshot("file", hashlib.sha256(payload).hexdigest())


def publish_staged_exclusive(staged: Path, target: Path) -> None:
    """Publish a staged path without replacing a concurrently-created target.

    Files and links use primitives with create-if-absent semantics. Directories use
    the platform's atomic no-replace rename, with a self-rolling exclusive fallback
    for platforms or filesystems that do not implement that primitive.
    """

    metadata = staged.lstat()
    if stat.S_ISLNK(metadata.st_mode):
        target.symlink_to(os.readlink(staged))
        staged.unlink()
        return
    if stat.S_ISREG(metadata.st_mode):
        os.link(staged, target, follow_symlinks=False)
        staged.unlink()
        return
    if stat.S_ISDIR(metadata.st_mode):
        if _rename_directory_exclusive(staged, target):
            return
        _publish_directory_fallback(staged, target, stat.S_IMODE(metadata.st_mode))
        return
    raise OSError(f"refusing to publish special staged path: {staged}")


def _rename_directory_exclusive(staged: Path, target: Path) -> bool:
    """Use a native atomic no-replace directory rename when the OS provides one."""

    library = ctypes.CDLL(None, use_errno=True)
    function: object
    arguments: tuple[object, ...]
    if sys.platform == "darwin" and hasattr(library, "renamex_np"):
        function = library.renamex_np
        arguments = (os.fsencode(staged), os.fsencode(target), 0x00000004)
    elif sys.platform.startswith("linux") and hasattr(library, "renameat2"):
        function = library.renameat2
        arguments = (-100, os.fsencode(staged), -100, os.fsencode(target), 1)
    else:
        return False
    result = function(*arguments)
    if result == 0:
        return True
    error_number = ctypes.get_errno()
    if error_number in {errno.EINVAL, errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP}:
        return False
    raise OSError(error_number, os.strerror(error_number), str(target))


def _publish_directory_fallback(staged: Path, target: Path, mode: int) -> None:
    """Portable exclusive fallback for systems without no-replace rename."""

    target.mkdir(mode=mode, exist_ok=False)
    os.chmod(target, mode)
    published: list[tuple[Path, Path, PathSnapshot]] = []
    try:
        for entry in sorted(staged.iterdir(), key=lambda item: item.name):
            destination = target / entry.name
            entry_state = snapshot_path(entry)
            publish_staged_exclusive(entry, destination)
            published.append((entry, destination, entry_state))
        staged.rmdir()
    except BaseException as publish_error:
        rollback_failures: list[str] = []
        for source, destination, entry_state in reversed(published):
            try:
                if snapshot_path(destination) != entry_state:
                    rollback_failures.append(f"concurrent published-path drift: {destination}")
                    continue
                if snapshot_path(source) != ABSENT_PATH:
                    rollback_failures.append(f"concurrent staged-path drift: {source}")
                    continue
                publish_staged_exclusive(destination, source)
            except BaseException as rollback_error:
                rollback_failures.append(f"{destination}: {rollback_error}")
        try:
            target.rmdir()
        except OSError as rollback_error:
            rollback_failures.append(f"{target}: {rollback_error}")
        if rollback_failures:
            raise FilesystemError(
                "INSTALLATION_ROLLBACK_FAILED",
                "Exclusive directory publication rollback preserved concurrent data: "
                + "; ".join(rollback_failures),
                details={"staged": str(staged), "target": str(target)},
            ) from publish_error
        raise


def write_text_exclusive(path: Path, content: str, *, mode: int = 0o600) -> None:
    """Atomically create a UTF-8 file, failing if ``path`` already exists."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        publish_staged_exclusive(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def vacate_expected(path: Path, expected: PathSnapshot, backup: Path) -> None:
    """Move the exact previewed path aside, restoring it if the move is uncertain."""

    if expected == ABSENT_PATH:
        require_unchanged(path, expected)
        return
    if snapshot_path(backup) != ABSENT_PATH:
        raise OSError(f"unexpected backup path: {backup}")
    try:
        os.replace(path, backup)
    except BaseException as move_error:
        moved_state = snapshot_path(backup)
        if moved_state != ABSENT_PATH:
            if snapshot_path(path) == ABSENT_PATH:
                try:
                    publish_staged_exclusive(backup, path)
                except BaseException as restore_error:
                    raise FilesystemError(
                        "INSTALLATION_ROLLBACK_FAILED",
                        f"Failed move left recoverable data at {backup}: {restore_error}",
                        details={"path": str(path), "backup": str(backup)},
                    ) from move_error
            else:
                raise FilesystemError(
                    "INSTALLATION_ROLLBACK_FAILED",
                    f"Failed move preserved concurrent data at {path} and backup data at {backup}",
                    details={"path": str(path), "backup": str(backup)},
                ) from move_error
        raise
    moved_state = snapshot_path(backup)
    target_state = snapshot_path(path)
    if moved_state == expected and target_state == ABSENT_PATH:
        return
    if target_state == ABSENT_PATH:
        try:
            publish_staged_exclusive(backup, path)
        except BaseException as restore_error:
            raise FilesystemError(
                "INSTALLATION_ROLLBACK_FAILED",
                f"Drifted path was preserved at {backup}, but could not be restored: {restore_error}",
                details={"path": str(path), "backup": str(backup)},
            ) from restore_error
        raise GovernedStop(
            "INSTALLATION_TARGET_DRIFT",
            "Installation target changed during its guarded backup move",
            details={"path": str(path)},
        )
    raise FilesystemError(
        "INSTALLATION_ROLLBACK_FAILED",
        f"Concurrent data was preserved at {path} and prior data at {backup}",
        details={"path": str(path), "backup": str(backup)},
    )


def quarantine_expected(path: Path, expected: PathSnapshot) -> Path | None:
    """Atomically bind an exact live post-state before rollback removes it."""

    if expected == ABSENT_PATH:
        require_unchanged(path, expected)
        return None
    quarantine = path.with_name(f".{path.name}.rollback-{uuid.uuid4().hex}")
    vacate_expected(path, expected, quarantine)
    return quarantine
