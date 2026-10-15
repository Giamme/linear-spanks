"""Lazy artifact migration coordinated by an exact approved execution preview."""

from __future__ import annotations

import json
import os
import stat
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol, cast

from ..core.errors import FilesystemError, GovernedStop, LinearSpanksError, UsageError
from ..core.hashing import sha256_bytes, sha256_digest
from ..core.jsonio import (
    StrictJsonError,
    atomic_write_text,
    dump_json,
    freeze_json,
    mutable_json_copy,
    read_text,
    strict_json_loads,
)
from ..core.types import ExecutionEnvelope, MigrationAuthorization
from .artifacts import VersionedArtifactCodec, artifact_codecs


@dataclass(frozen=True, slots=True)
class ArtifactBinding:
    """One durable artifact touched by a normal execution."""

    backend: str
    locator: str
    kind: str


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    """Backend snapshot used for optimistic compare-and-swap."""

    locator: str
    revision_token: str
    value: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ArtifactChange:
    """Exact replacement passed to an atomic backend commit."""

    locator: str
    kind: str
    expected_revision_token: str
    value: Mapping[str, Any]


class ArtifactBackend(Protocol):
    """Storage adapter with CAS, rollback, and atomic replacement per artifact.

    Backends may additionally provide multi-artifact reader isolation, but callers do not
    assume it. A migration preview always enumerates every artifact in the transaction.
    """

    name: str

    def read(self, locator: str) -> ArtifactRecord:
        """Read one artifact without mutation."""

    def commit(
        self,
        changes: Sequence[ArtifactChange],
        authorization: MigrationAuthorization,
    ) -> tuple[ArtifactRecord, ...]:
        """Compare-and-swap all changes atomically, then return fresh read-backs."""


@contextmanager
def _artifact_write_lock(path: Path) -> Iterator[None]:
    lock = path.with_name(f".{path.name}.linear-spanks.lock")
    descriptor: int | None = None
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.write(descriptor, f"pid={os.getpid()}\n".encode())
    except FileExistsError as error:
        raise GovernedStop(
            "ARTIFACT_WRITE_LOCKED",
            "Another governed artifact write owns this path",
            details={"path": str(path), "lock": str(lock)},
        ) from error
    except OSError as error:
        if descriptor is not None:
            os.close(descriptor)
            descriptor = None
            lock.unlink(missing_ok=True)
        raise FilesystemError(
            "ARTIFACT_LOCK_FAILED",
            f"Unable to lock artifact {path}: {error}",
            details={"path": str(path), "lock": str(lock)},
        ) from error
    try:
        yield
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            lock.unlink(missing_ok=True)
        except OSError as error:
            raise FilesystemError(
                "ARTIFACT_LOCK_CLEANUP_FAILED",
                f"Unable to release artifact lock {lock}: {error}",
                details={"path": str(path), "lock": str(lock)},
            ) from error


class FilesystemArtifactBackend:
    """Atomic filesystem backend with exact-source rollback and read-back."""

    name = "filesystem"

    @staticmethod
    def _path(locator: str) -> Path:
        path = Path(locator)
        if not path.name:
            raise UsageError("INVALID_ARTIFACT_LOCATOR", "Artifact path must name a file")
        return path

    @classmethod
    def _record_from_text(cls, locator: str, text: str) -> ArtifactRecord:
        try:
            value = strict_json_loads(text)
        except (json.JSONDecodeError, StrictJsonError) as error:
            message = error.msg if isinstance(error, json.JSONDecodeError) else str(error)
            raise UsageError(
                "INVALID_JSON",
                f"Artifact is not valid JSON: {message}",
                details={"locator": locator},
            ) from error
        if not isinstance(value, dict):
            raise UsageError("MALFORMED_ARTIFACT", "Artifact must contain a JSON object")
        return ArtifactRecord(
            locator=locator,
            revision_token=sha256_bytes(text.encode("utf-8")),
            value=cast(Mapping[str, Any], freeze_json(value)),
        )

    def read(self, locator: str) -> ArtifactRecord:
        return self._record_from_text(locator, read_text(self._path(locator)))

    def commit(
        self,
        changes: Sequence[ArtifactChange],
        authorization: MigrationAuthorization,
    ) -> tuple[ArtifactRecord, ...]:
        del authorization
        if not changes:
            return ()
        if len({change.locator for change in changes}) != len(changes):
            raise UsageError("DUPLICATE_ARTIFACT", "A migration batch contains duplicate paths")
        ordered = tuple(sorted(changes, key=lambda change: change.locator))
        originals: dict[str, str] = {}
        encoded: dict[str, str] = {}
        staged: dict[str, Path] = {}
        backups: dict[str, Path] = {}
        poststates: dict[str, str | None] = {}
        moved: list[str] = []

        def is_absent(path: Path) -> bool:
            try:
                path.lstat()
            except FileNotFoundError:
                return True
            return False

        def matches_text(path: Path, expected: str) -> bool:
            try:
                metadata = path.lstat()
            except FileNotFoundError:
                return False
            return stat.S_ISREG(metadata.st_mode) and read_text(path) == expected

        def restore_backup(locator: str, backup: Path) -> None:
            path = self._path(locator)
            os.link(backup, path, follow_symlinks=False)
            backup.unlink()

        with ExitStack() as locks:
            for change in ordered:
                locks.enter_context(_artifact_write_lock(self._path(change.locator)))
            for change in ordered:
                original = read_text(self._path(change.locator))
                record = self._record_from_text(change.locator, original)
                if record.revision_token != change.expected_revision_token:
                    raise GovernedStop(
                        "ARTIFACT_SOURCE_DRIFT",
                        "Artifact changed after preview; produce a new write preview",
                        details={
                            "locator": change.locator,
                            "expected_revision_token": change.expected_revision_token,
                            "current_revision_token": record.revision_token,
                        },
                    )
                originals[change.locator] = original
                encoded[change.locator] = dump_json(change.value, pretty=True)
            try:
                for change in ordered:
                    current = read_text(self._path(change.locator))
                    if current != originals[change.locator]:
                        raise GovernedStop(
                            "ARTIFACT_SOURCE_DRIFT",
                            "Artifact changed while preparing migration",
                            details={"locator": change.locator},
                        )
                for change in ordered:
                    path = self._path(change.locator)
                    stage = path.with_name(f".{path.name}.migration-{uuid.uuid4().hex}.tmp")
                    atomic_write_text(stage, encoded[change.locator])
                    staged[change.locator] = stage
                for change in ordered:
                    locator = change.locator
                    path = self._path(locator)
                    backup = path.with_name(f".{path.name}.backup-{uuid.uuid4().hex}")
                    try:
                        os.replace(path, backup)
                    except BaseException as move_error:
                        if not is_absent(backup):
                            if is_absent(path):
                                try:
                                    restore_backup(locator, backup)
                                except BaseException:
                                    raise FilesystemError(
                                        "ARTIFACT_ROLLBACK_FAILED",
                                        "Failed artifact move left the original in its backup",
                                        details={"locator": locator, "backup": str(backup)},
                                    ) from move_error
                            else:
                                raise FilesystemError(
                                    "ARTIFACT_ROLLBACK_FAILED",
                                    "Failed artifact move preserved concurrent and backup data",
                                    details={"locator": locator, "backup": str(backup)},
                                ) from move_error
                        raise
                    if not matches_text(backup, originals[locator]):
                        if is_absent(path):
                            restore_backup(locator, backup)
                            raise GovernedStop(
                                "ARTIFACT_SOURCE_DRIFT",
                                "Artifact changed during its guarded backup move",
                                details={"locator": locator},
                            )
                        raise FilesystemError(
                            "ARTIFACT_ROLLBACK_FAILED",
                            "Concurrent artifact and recoverable backup data were preserved",
                            details={"locator": locator, "backup": str(backup)},
                        )
                    backups[locator] = backup
                    poststates[locator] = None
                    moved.append(locator)
                    if not is_absent(path):
                        raise GovernedStop(
                            "ARTIFACT_SOURCE_DRIFT",
                            "Artifact target was recreated during migration",
                            details={"locator": locator},
                        )
                    try:
                        os.link(staged[locator], path, follow_symlinks=False)
                    except BaseException:
                        if matches_text(path, encoded[locator]):
                            poststates[locator] = encoded[locator]
                        raise
                    poststates[locator] = encoded[locator]
                read_backs = tuple(self.read(change.locator) for change in ordered)
                for change, record in zip(ordered, read_backs, strict=True):
                    if mutable_json_copy(record.value) != mutable_json_copy(change.value):
                        raise UsageError(
                            "ARTIFACT_READBACK_MISMATCH",
                            f"Artifact read-back differs from the committed value: {change.locator}",
                        )
            except BaseException as error:
                restored: list[str] = []
                drifted: list[str] = []
                recoverable: list[dict[str, str]] = []
                rollback_failures: list[dict[str, str]] = []
                for locator in reversed(moved):
                    path = self._path(locator)
                    expected_poststate = poststates[locator]
                    quarantine: Path | None = None
                    try:
                        if expected_poststate is None:
                            target_safe = is_absent(path)
                        else:
                            quarantine = path.with_name(f".{path.name}.rollback-{uuid.uuid4().hex}")
                            try:
                                os.replace(path, quarantine)
                            except OSError:
                                target_safe = False
                            else:
                                target_safe = matches_text(quarantine, expected_poststate)
                                if not target_safe and is_absent(path):
                                    try:
                                        os.link(quarantine, path, follow_symlinks=False)
                                        quarantine.unlink()
                                        quarantine = None
                                    except OSError:
                                        pass
                        backup_safe = matches_text(backups[locator], originals[locator])
                    except Exception as rollback_error:
                        rollback_failures.append({"locator": locator, "error": str(rollback_error)})
                        continue
                    if not target_safe or not backup_safe:
                        drifted.append(locator)
                        preserved = {
                            "locator": locator,
                            "backup": str(backups[locator]),
                        }
                        if quarantine is not None:
                            preserved["quarantine"] = str(quarantine)
                        recoverable.append(preserved)
                        continue
                    try:
                        restore_backup(locator, backups[locator])
                        if quarantine is not None:
                            quarantine.unlink()
                        restored.append(locator)
                    except Exception as rollback_error:
                        rollback_failures.append(
                            {
                                "locator": locator,
                                "error": str(rollback_error),
                            }
                        )
                rollback_details = {
                    "restored": restored,
                    "preserved_drift": drifted,
                    "recoverable": recoverable,
                    "failures": rollback_failures,
                }
                if rollback_failures:
                    raise FilesystemError(
                        "ARTIFACT_ROLLBACK_FAILED",
                        "Artifact rollback was incomplete after checking every written path",
                        details=rollback_details,
                    ) from error
                if drifted:
                    raise GovernedStop(
                        "ARTIFACT_ROLLBACK_INCOMPLETE",
                        "Concurrent artifact edits were preserved; unaffected paths were restored",
                        details=rollback_details,
                    ) from error
                if isinstance(error, LinearSpanksError):
                    raise
                raise FilesystemError(
                    "ARTIFACT_WRITE_FAILED",
                    f"Artifact migration failed and was rolled back: {error}",
                ) from error
            finally:
                for stage in staged.values():
                    stage.unlink(missing_ok=True)
            cleanup_failures: list[dict[str, str]] = []
            for locator, backup in backups.items():
                try:
                    if not matches_text(backup, originals[locator]):
                        raise OSError("backup changed after commit")
                    backup.unlink()
                except Exception as cleanup_error:
                    cleanup_failures.append(
                        {"locator": locator, "backup": str(backup), "error": str(cleanup_error)}
                    )
            if cleanup_failures:
                raise FilesystemError(
                    "ARTIFACT_BACKUP_CLEANUP_FAILED",
                    "Artifacts committed, but backup cleanup was incomplete",
                    details={"failures": cleanup_failures},
                )
            return read_backs


def parse_migration_authorization(value: Mapping[str, Any]) -> MigrationAuthorization:
    required = {
        "kind",
        "schema_version",
        "command",
        "target",
        "preview_hash",
        "receipt_id",
        "decision",
    }
    if set(value) != required:
        raise UsageError(
            "INVALID_MIGRATION_AUTHORIZATION",
            "Migration authorization fields are incomplete or unknown",
            details={"required": sorted(required), "actual": sorted(value)},
        )
    if value.get("kind") != "migration-authorization" or value.get("schema_version") != 2:
        raise UsageError(
            "INVALID_MIGRATION_AUTHORIZATION",
            "Migration authorization kind and schema_version must identify v2",
        )
    fields = ("command", "target", "preview_hash", "receipt_id", "decision")
    if not all(isinstance(value.get(field), str) and value[field] for field in fields):
        raise UsageError(
            "INVALID_MIGRATION_AUTHORIZATION",
            "Migration authorization text fields must be non-empty",
        )
    if any(value[field] != value[field].strip() for field in fields):
        raise UsageError(
            "INVALID_MIGRATION_AUTHORIZATION",
            "Migration authorization text fields must be trimmed",
        )
    if value["receipt_id"].startswith("<"):
        raise UsageError(
            "INVALID_MIGRATION_AUTHORIZATION",
            "Migration authorization requires a completed approved-write receipt",
        )
    return MigrationAuthorization(
        command=cast(str, value["command"]),
        target=cast(str, value["target"]),
        preview_hash=cast(str, value["preview_hash"]),
        receipt_id=cast(str, value["receipt_id"]),
        decision=cast(str, value["decision"]),
    )


class MigrationCoordinator:
    """Prepare in memory, then commit only from a matching approval receipt."""

    def __init__(
        self,
        backends: Mapping[str, ArtifactBackend],
        codecs: Mapping[str, VersionedArtifactCodec] | None = None,
    ) -> None:
        self._backends = MappingProxyType(dict(backends))
        selected = artifact_codecs() if codecs is None else codecs
        self._codecs = MappingProxyType(dict(selected))

    @staticmethod
    def _invocation(envelope: ExecutionEnvelope) -> tuple[str, str]:
        invocation = envelope.contract.get("invocation")
        if not isinstance(invocation, Mapping):
            raise UsageError("INVALID_EXECUTION_ENVELOPE", "Execution invocation is missing")
        command = invocation.get("command")
        target = invocation.get("target")
        if (
            not isinstance(command, str)
            or not command
            or command != command.strip()
            or command != envelope.command.path
            or not isinstance(target, str)
            or not target
            or target != target.strip()
        ):
            raise UsageError("INVALID_EXECUTION_ENVELOPE", "Execution identity is invalid")
        return command, target

    @staticmethod
    def _hash(envelope: ExecutionEnvelope, migrations: Sequence[Mapping[str, Any]]) -> str:
        execution = mutable_json_copy(envelope.contract)
        execution.pop("migrations", None)
        execution.pop("migration_preview_hash", None)
        return sha256_digest(
            {
                "schema_version": 2,
                "execution": execution,
                "migrations": [mutable_json_copy(item) for item in migrations],
            }
        )

    def _backend(self, name: str) -> ArtifactBackend:
        backend = self._backends.get(name)
        if backend is None:
            raise UsageError(
                "ARTIFACT_BACKEND_NOT_FOUND",
                f"Unknown artifact backend: {name}",
                details={"known_backends": sorted(self._backends)},
            )
        return backend

    def _codec(self, kind: str) -> VersionedArtifactCodec:
        codec = self._codecs.get(kind)
        if codec is None:
            raise UsageError(
                "UNKNOWN_ARTIFACT_KIND",
                f"Unknown artifact kind: {kind}",
                details={"known_kinds": sorted(self._codecs)},
            )
        return codec

    def prepare(
        self,
        envelope: ExecutionEnvelope,
        bindings: Sequence[ArtifactBinding],
    ) -> ExecutionEnvelope:
        if len({(item.backend, item.locator) for item in bindings}) != len(bindings):
            raise UsageError("DUPLICATE_ARTIFACT", "Execution contains duplicate artifacts")
        migrations: list[Mapping[str, Any]] = []
        for binding in sorted(bindings, key=lambda item: (item.backend, item.locator, item.kind)):
            backend = self._backend(binding.backend)
            record = backend.read(binding.locator)
            decoded = self._codec(binding.kind).decode(record.value)
            if not decoded.needs_migration:
                continue
            item = dict(self._codec(binding.kind).migration_preview(decoded, binding.locator))
            item.update(
                {
                    "backend": binding.backend,
                    "source_revision_token": record.revision_token,
                    "action": (
                        "in-memory-only"
                        if envelope.command.access == "read"
                        else "rewrite-on-authorized-write"
                    ),
                }
            )
            migrations.append(cast(Mapping[str, Any], freeze_json(item)))
        preview_hash = self._hash(envelope, migrations)
        contract = mutable_json_copy(envelope.contract)
        contract["migrations"] = [mutable_json_copy(item) for item in migrations]
        contract["migration_preview_hash"] = preview_hash
        frozen_contract = cast(Mapping[str, Any], freeze_json(contract))
        return ExecutionEnvelope(
            command=envelope.command,
            assurance=envelope.assurance,
            arguments=envelope.arguments,
            contract=frozen_contract,
            migrations=tuple(migrations),
        )

    def authorization_template(self, envelope: ExecutionEnvelope) -> Mapping[str, Any]:
        command, target = self._invocation(envelope)
        return {
            "kind": "migration-authorization",
            "schema_version": 2,
            "command": command,
            "target": target,
            "preview_hash": envelope.contract.get("migration_preview_hash"),
            "receipt_id": "",
            "decision": "pending",
        }

    def commit(
        self,
        envelope: ExecutionEnvelope,
        authorization: MigrationAuthorization,
    ) -> Mapping[str, Any]:
        if not envelope.migrations:
            return {"status": "already-v2", "migrations": [], "read_back": True}
        if envelope.command.access == "read":
            raise GovernedStop(
                "MIGRATION_WRITE_NOT_ALLOWED",
                "Read-only execution may decode v1 artifacts only in memory",
            )
        command, target = self._invocation(envelope)
        expected_hash = self._hash(envelope, envelope.migrations)
        if envelope.contract.get("migration_preview_hash") != expected_hash:
            raise GovernedStop(
                "MIGRATION_PREVIEW_DRIFT",
                "Execution migrations changed after preview",
            )
        if (
            authorization.schema_version != 2
            or authorization.decision != "approved"
            or authorization.command != command
            or authorization.target != target
            or authorization.preview_hash != expected_hash
            or not authorization.receipt_id
            or authorization.receipt_id != authorization.receipt_id.strip()
            or authorization.receipt_id.startswith("<")
        ):
            raise GovernedStop(
                "MIGRATION_APPROVAL_INVALID",
                "Migration authorization does not match the exact execution preview",
                details={
                    "command": command,
                    "target": target,
                    "preview_hash": expected_hash,
                },
            )
        backend_names = {cast(str, item["backend"]) for item in envelope.migrations}
        if len(backend_names) != 1:
            raise GovernedStop(
                "MIGRATION_MULTI_BACKEND_NOT_ATOMIC",
                "One authorized migration commit must use exactly one atomic backend",
            )
        backend_name = next(iter(backend_names))
        backend = self._backend(backend_name)
        changes: list[ArtifactChange] = []
        for item in envelope.migrations:
            locator = cast(str, item["locator"])
            kind = cast(str, item["kind"])
            record = backend.read(locator)
            if record.revision_token != item.get("source_revision_token"):
                raise GovernedStop(
                    "ARTIFACT_SOURCE_DRIFT",
                    "Artifact changed after preview; produce a new write preview",
                    details={"backend": backend_name, "locator": locator},
                )
            decoded = self._codec(kind).decode(record.value)
            if decoded.source_hash != item.get("source_hash") or not decoded.needs_migration:
                raise GovernedStop(
                    "ARTIFACT_SOURCE_DRIFT",
                    "Artifact changed after preview; produce a new write preview",
                    details={"backend": backend_name, "locator": locator},
                )
            encoded = self._codec(kind).encode_v2(decoded)
            validated = self._codec(kind).decode(encoded)
            if validated.needs_migration:
                raise UsageError("MALFORMED_ARTIFACT", "Encoded artifact remained at v1")
            changes.append(
                ArtifactChange(
                    locator=locator,
                    kind=kind,
                    expected_revision_token=record.revision_token,
                    value=encoded,
                )
            )
        read_backs = backend.commit(changes, authorization)
        if len(read_backs) != len(changes):
            raise FilesystemError(
                "ARTIFACT_READBACK_FAILED",
                "Artifact backend returned an incomplete read-back",
            )
        receipts: list[dict[str, Any]] = []
        by_locator = {record.locator: record for record in read_backs}
        for change in changes:
            read_back = by_locator.get(change.locator)
            if read_back is None:
                raise FilesystemError(
                    "ARTIFACT_READBACK_FAILED",
                    f"Artifact backend omitted read-back: {change.locator}",
                )
            decoded = self._codec(change.kind).decode(read_back.value)
            if decoded.needs_migration or decoded.schema_version != 2:
                raise FilesystemError(
                    "ARTIFACT_READBACK_FAILED",
                    f"Artifact remained at v1 after commit: {change.locator}",
                )
            receipts.append(
                {
                    "backend": backend_name,
                    "locator": change.locator,
                    "kind": change.kind,
                    "schema_version": 2,
                    "revision_token": read_back.revision_token,
                    "receipt_id": authorization.receipt_id,
                    "read_back": True,
                }
            )
        return {
            "status": "migrated",
            "preview_hash": expected_hash,
            "receipt_id": authorization.receipt_id,
            "migrations": receipts,
            "read_back": True,
        }
