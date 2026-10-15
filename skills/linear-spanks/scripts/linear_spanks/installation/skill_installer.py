"""Transactional installer for this repository's skill bundles."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from ..core.errors import ExitCode, FilesystemError, LinearSpanksError, UsageError
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

REPO_ROOT = Path(__file__).resolve().parents[5]
MANIFEST = REPO_ROOT / "skills-manifest.txt"
OWNERSHIP_RECORD = ".linear-spanks-managed"
COPY_MARKER = ".linear-spanks-source"
SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    name: str
    group: str


@dataclass(slots=True)
class Change:
    target: Path
    staged: Path | None
    backup: Path | None = None


@dataclass(slots=True)
class InstallPlan:
    changes: list[Change]
    record: Path
    names: set[str]
    remove_record: bool
    preview_message: str
    success_message: str
    expected_record: PathSnapshot
    expected_targets: Mapping[Path, PathSnapshot]


def _validate_skill_name(name: str, *, record: bool = False) -> str:
    if SKILL_NAME_RE.fullmatch(name) is None or name in {".", ".."}:
        code = "INVALID_OWNERSHIP_RECORD" if record else "INVALID_MANIFEST"
        source = "ownership record" if record else "manifest"
        raise UsageError(code, f"Invalid skill name in {source}: {name!r}")
    return name


def load_manifest(path: Path = MANIFEST) -> tuple[ManifestEntry, ...]:
    entries: list[ManifestEntry] = []
    for line_number, raw_line in enumerate(read_text(path).splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) != 2 or fields[1] not in {"linear", "exec", "tech"}:
            raise UsageError("INVALID_MANIFEST", f"Invalid manifest entry on line {line_number}")
        entries.append(ManifestEntry(_validate_skill_name(fields[0]), fields[1]))
    if len({entry.name for entry in entries}) != len(entries):
        raise UsageError("INVALID_MANIFEST", "Skill manifest contains duplicate names")
    return tuple(entries)


def _exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _copy_owner(path: Path) -> str | None:
    marker = path / COPY_MARKER
    if path.is_dir() and marker.is_file() and not marker.is_symlink():
        return read_text(marker).strip()
    return None


def skill_source(repo_root: Path, name: str) -> Path:
    """Core skills live in skills/<name>; the optional exec and tech skills in skills/extras/<name>."""
    core = repo_root / "skills" / name
    return core if _exists(core) else repo_root / "skills" / "extras" / name


def is_managed(path: Path, repo_root: Path = REPO_ROOT) -> bool:
    if path.is_symlink():
        target = path.readlink()
        return target.is_absolute() and repo_root / "skills" in target.parents
    return _copy_owner(path) == str(repo_root)


def _stage(source: Path, destination: Path, mode: str, repo_root: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix=".linear-spanks-stage-", dir=destination))
    target = staged / source.name
    if mode == "link":
        target.symlink_to(source)
    else:
        shutil.copytree(source, target, symlinks=True)
        (target / COPY_MARKER).write_text(str(repo_root) + "\n", encoding="utf-8")
    return target


def _record_names(record: Path) -> set[str]:
    if record.is_symlink():
        raise UsageError("INVALID_OWNERSHIP_RECORD", f"Ownership record is a symlink: {record}")
    if not record.is_file():
        return set()
    names: set[str] = set()
    for line in read_text(record).splitlines():
        name = line.strip()
        if not name:
            continue
        validated = _validate_skill_name(name, record=True)
        if validated in names:
            raise UsageError(
                "INVALID_OWNERSHIP_RECORD",
                f"Ownership record contains duplicate name: {validated}",
            )
        names.add(validated)
    return names


def _cleanup_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.exists():
        shutil.rmtree(path)


def _cleanup_staged(changes: Iterable[Change]) -> None:
    for change in changes:
        if change.staged is None or not _exists(change.staged):
            continue
        parent = change.staged.parent
        _cleanup_path(parent if parent.name.startswith(".linear-spanks-stage-") else change.staged)


def _apply_plans(plans: Sequence[InstallPlan]) -> None:
    for plan in plans:
        destination = plan.record.parent
        for name in plan.names:
            _validate_skill_name(name, record=True)
        for change in plan.changes:
            if change.target.parent != destination:
                raise UsageError(
                    "INVALID_OWNERSHIP_RECORD",
                    f"Managed skill target escapes its destination: {change.target}",
                )
            _validate_skill_name(change.target.name, record=True)
    try:
        for plan in plans:
            require_unchanged(plan.record, plan.expected_record)
            for path, expected in plan.expected_targets.items():
                require_unchanged(path, expected)
    except BaseException:
        _cleanup_staged(change for plan in plans for change in plan.changes)
        raise
    applied: list[Change] = []
    target_poststates: dict[Path, PathSnapshot] = {}
    backup_states: dict[Path, PathSnapshot] = {}
    record_poststates: dict[Path, PathSnapshot] = {}
    record_backups: dict[Path, Path | None] = {}
    record_backup_states: dict[Path, PathSnapshot] = {}
    try:
        for plan in plans:
            for change in plan.changes:
                expected_target = plan.expected_targets[change.target]
                require_unchanged(change.target, expected_target)
                if expected_target != ABSENT_PATH:
                    candidate = change.target.with_name(
                        f".{change.target.name}.backup-{os.getpid()}-{len(applied)}"
                    )
                    vacate_expected(change.target, expected_target, candidate)
                    change.backup = candidate
                    backup_states[candidate] = expected_target
                    target_poststates[change.target] = ABSENT_PATH
                    applied.append(change)
                if change.staged is not None:
                    staged_state = snapshot_path(change.staged)
                    try:
                        publish_staged_exclusive(change.staged, change.target)
                    except BaseException:
                        actual = snapshot_path(change.target)
                        if actual == staged_state:
                            target_poststates[change.target] = staged_state
                            if change not in applied:
                                applied.append(change)
                        elif actual != ABSENT_PATH and change.backup is None:
                            require_unchanged(change.target, ABSENT_PATH)
                        raise
                    target_poststates[change.target] = staged_state
                    if change not in applied:
                        applied.append(change)
                    require_unchanged(change.target, staged_state)
                    parent = change.staged.parent
                    if parent.name.startswith(".linear-spanks-stage-"):
                        parent.rmdir()
        for plan in plans:
            require_unchanged(plan.record, plan.expected_record)
            if plan.expected_record != ABSENT_PATH:
                candidate = plan.record.with_name(
                    f".{plan.record.name}.backup-{os.getpid()}-{len(record_backups)}"
                )
                vacate_expected(plan.record, plan.expected_record, candidate)
                record_backups[plan.record] = candidate
                record_backup_states[candidate] = plan.expected_record
                record_poststates[plan.record] = ABSENT_PATH
            if not plan.remove_record:
                content = "".join(f"{name}\n" for name in sorted(plan.names))
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
                    _cleanup_path(quarantine)
            except (LinearSpanksError, OSError) as rollback_error:
                rollback_failures.append(str(rollback_error))
        for change in reversed(applied):
            try:
                if change.backup is not None and not matches_snapshot(
                    change.backup, backup_states[change.backup]
                ):
                    rollback_failures.append(f"concurrent backup drift: {change.backup}")
                    continue
                quarantine = quarantine_expected(change.target, target_poststates[change.target])
                if change.backup is not None and _exists(change.backup):
                    publish_staged_exclusive(change.backup, change.target)
                if quarantine is not None:
                    _cleanup_path(quarantine)
            except (LinearSpanksError, OSError) as rollback_error:
                rollback_failures.append(str(rollback_error))
        _cleanup_staged(change for plan in plans for change in plan.changes)
        if rollback_failures:
            raise FilesystemError(
                "INSTALLATION_ROLLBACK_FAILED",
                "Skill installation rollback preserved concurrent data: "
                + "; ".join(rollback_failures),
            ) from error
        raise
    cleanup_failures: list[str] = []
    for change in applied:
        if change.backup is not None:
            try:
                require_unchanged(change.backup, backup_states[change.backup])
                _cleanup_path(change.backup)
            except (LinearSpanksError, OSError) as cleanup_error:
                cleanup_failures.append(f"{change.backup}: {cleanup_error}")
    for backup in record_backups.values():
        if backup is not None:
            try:
                require_unchanged(backup, record_backup_states[backup])
                _cleanup_path(backup)
            except (LinearSpanksError, OSError) as cleanup_error:
                cleanup_failures.append(f"{backup}: {cleanup_error}")
    if cleanup_failures:
        raise FilesystemError(
            "INSTALLATION_BACKUP_CLEANUP_FAILED",
            "Skill installation committed, but backup cleanup was incomplete: "
            + "; ".join(cleanup_failures),
        )


def _apply_changes(changes: list[Change], record: Path, names: set[str]) -> None:
    _apply_plans(
        (
            InstallPlan(
                changes=changes,
                record=record,
                names=names,
                remove_record=False,
                preview_message="",
                success_message="",
                expected_record=snapshot_path(record),
                expected_targets={
                    change.target: snapshot_path(change.target) for change in changes
                },
            ),
        )
    )


def _selected_entries(manifest: Iterable[ManifestEntry], scope: str) -> tuple[ManifestEntry, ...]:
    return tuple(entry for entry in manifest if scope == "all" or entry.group == scope)


def _prepare_install(
    client: ClientSpec,
    destination: Path,
    *,
    mode: str,
    scope: str,
    force: bool,
    prune: bool,
    prune_scope: bool,
    uninstall: bool,
    stage: bool,
    repo_root: Path = REPO_ROOT,
    manifest_path: Path = MANIFEST,
) -> InstallPlan:
    manifest = load_manifest(manifest_path)
    selected = _selected_entries(manifest, scope)
    record = destination / OWNERSHIP_RECORD
    expected_record = snapshot_path(record)
    recorded = _record_names(record)
    expected_targets: dict[Path, PathSnapshot] = {}

    def watch(name: str) -> Path:
        target = destination / name
        expected_targets.setdefault(target, snapshot_path(target))
        return target

    if uninstall:
        uninstall_changes: list[Change] = []
        for name in sorted(recorded):
            target = watch(name)
            if not _exists(target):
                continue
            if not is_managed(target, repo_root):
                raise UsageError(
                    "UNMANAGED_ENTRY",
                    f"Refusing to remove unmanaged entry: {target}",
                )
            uninstall_changes.append(Change(target=target, staged=None))
        return InstallPlan(
            changes=uninstall_changes,
            record=record,
            names=set(),
            remove_record=True,
            preview_message=(
                f"Would uninstall {len(uninstall_changes)} managed skills from {destination}"
            ),
            success_message=f"Uninstalled managed skills from {destination}",
            expected_record=expected_record,
            expected_targets=expected_targets,
        )

    desired_names = {entry.name for entry in selected}
    next_names = set(desired_names) if prune_scope else recorded | desired_names
    manifest_names = {entry.name for entry in manifest}
    if prune:
        next_names &= manifest_names
    install_sources: list[tuple[Path, Path]] = []
    for entry in selected:
        source = skill_source(repo_root, entry.name)
        if not (source / "SKILL.md").is_file():
            raise UsageError("INVALID_MANIFEST", f"Manifest entry has no SKILL.md: {entry.name}")
        target = watch(entry.name)
        if (
            entry.name in recorded
            and target.is_symlink()
            and target.readlink() == source
            and mode == "link"
        ):
            continue
        if _exists(target) and (entry.name not in recorded or not is_managed(target, repo_root)):
            message = f"Destination exists and is unmanaged: {target}"
            if force:
                message += "; --force never replaces user-owned entries"
            raise UsageError("UNMANAGED_ENTRY", message)
        install_sources.append((target, source))

    removals: list[Change] = []
    for old_name in sorted(recorded - next_names):
        target = watch(old_name)
        if not _exists(target):
            continue
        if not is_managed(target, repo_root):
            raise UsageError("UNMANAGED_ENTRY", f"Refusing to remove unmanaged entry: {target}")
        removals.append(Change(target=target, staged=None))

    changes: list[Change] = []
    try:
        for target, source in install_sources:
            staged = _stage(source, destination, mode, repo_root) if stage else None
            changes.append(Change(target=target, staged=staged))
    except BaseException:
        _cleanup_staged(changes)
        raise
    changes.extend(removals)
    return InstallPlan(
        changes=changes,
        record=record,
        names=next_names,
        remove_record=False,
        preview_message=(
            f"Would install {len(selected)} skills for {client.name} in {destination} ({mode} mode)"
        ),
        success_message=(
            f"Installed {len(selected)} skills for {client.name} in {destination} ({mode} mode)."
        ),
        expected_record=expected_record,
        expected_targets=expected_targets,
    )


def install_to(
    client: ClientSpec,
    destination: Path,
    *,
    mode: str,
    scope: str,
    force: bool,
    prune: bool,
    prune_scope: bool,
    uninstall: bool,
    dry_run: bool,
    repo_root: Path = REPO_ROOT,
    manifest_path: Path = MANIFEST,
) -> str:
    plan = _prepare_install(
        client,
        destination,
        mode=mode,
        scope=scope,
        force=force,
        prune=prune,
        prune_scope=prune_scope,
        uninstall=uninstall,
        stage=not dry_run,
        repo_root=repo_root,
        manifest_path=manifest_path,
    )
    if dry_run:
        return plan.preview_message
    _apply_plans((plan,))
    return plan.success_message


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--client", default="codex")
    parser.add_argument("--mode", choices=("link", "copy"), default="link")
    parser.add_argument("--scope", choices=("all", "linear", "exec", "tech"), default="linear")
    parser.add_argument("--dest")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--prune", action="store_true")
    parser.add_argument("--prune-scope", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--print-destinations", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--without-ripwire", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None, environment: Mapping[str, str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    selected_environment = environment or os.environ
    registry = client_registry()
    plans: list[InstallPlan] = []
    try:
        override: Path | None = None
        if args.dest is not None:
            if not args.dest or args.dest != args.dest.strip():
                raise UsageError("INVALID_DESTINATION", "--dest must be non-empty and trimmed")
            override = Path(args.dest).expanduser().absolute()
        clients = registry.expand(args.client)
        if override is not None and len(clients) != 1:
            raise UsageError(
                "INVALID_DESTINATION", "--dest requires a selector that resolves to one client"
            )
        if args.print_destinations:
            for client in clients:
                destination = override or client.skill_destination(selected_environment)
                print(f"{client.name}\t{destination}")
            return int(ExitCode.SUCCESS)
        for client in clients:
            destination = (
                override if override is not None else client.skill_destination(selected_environment)
            )
            plans.append(
                _prepare_install(
                    client,
                    destination,
                    mode=args.mode,
                    scope=args.scope,
                    force=args.force,
                    prune=args.prune,
                    prune_scope=args.prune_scope,
                    uninstall=args.uninstall,
                    stage=not args.dry_run,
                )
            )
        if args.dry_run:
            for plan in plans:
                print(plan.preview_message)
            if args.scope in {"linear", "all"} and not args.uninstall:
                print(
                    "Ripwire: offline preview; skip and save off"
                    if args.without_ripwire
                    else "Ripwire: install if user preference permits"
                )
        else:
            _apply_plans(plans)
            for plan in plans:
                print(plan.success_message)
            if args.scope in {"linear", "all"} and not args.uninstall:
                from ..extensions.ripwire_settings import configure, resolve
                from .ripwire import install

                try:
                    if args.without_ripwire:
                        configure("off", environment=selected_environment)
                    if resolve(None, environment=selected_environment)["mode"] == "on":
                        result = install(selected_environment)
                        print(f"Ripwire: {result['status']}")
                    else:
                        print("Ripwire: disabled (user preference)")
                except (LinearSpanksError, OSError, ValueError) as error:
                    print(f"Ripwire unavailable: {error}", file=sys.stderr)
    except LinearSpanksError as error:
        print(f"skill installation error: {error.message}", file=sys.stderr)
        return int(error.exit_code)
    except OSError as error:
        print(f"skill installation error: {error}", file=sys.stderr)
        return int(ExitCode.FILESYSTEM)
    finally:
        _cleanup_staged(change for plan in plans for change in plan.changes)
    return int(ExitCode.SUCCESS)
