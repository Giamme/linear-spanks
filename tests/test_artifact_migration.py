from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

from tests.contract_support import (
    canonical_hash,
)

from linear_spanks.contracts.compiler import compile_public_command
from linear_spanks.core.errors import FilesystemError, GovernedStop, UsageError
from linear_spanks.core.hashing import sha256_digest
from linear_spanks.core.types import MigrationAuthorization
from linear_spanks.domains.artifacts import ARTIFACT_SPECS, ArtifactStore, artifact_codecs
from linear_spanks.domains import migrations as migrations_module
from linear_spanks.domains.migrations import (
    ArtifactBinding,
    ArtifactChange,
    ArtifactRecord,
    FilesystemArtifactBackend,
    MigrationCoordinator,
    parse_migration_authorization,
)


def _authorization(envelope: Any, *, decision: str = "approved") -> MigrationAuthorization:
    return MigrationAuthorization(
        command="task run",
        target="ENG-1",
        preview_hash=str(envelope.contract["migration_preview_hash"]),
        receipt_id="approval-receipt-1",
        decision=decision,
    )


def _prepared(path: Path, kind: str, *, command: str = "task run") -> tuple[Any, Any]:
    target = "ENG-1" if command.startswith("task ") else "project-1"
    compiled = compile_public_command(command, (target,))
    coordinator = MigrationCoordinator({"filesystem": FilesystemArtifactBackend()})
    prepared = coordinator.prepare(
        compiled,
        (ArtifactBinding("filesystem", str(path), kind),),
    )
    return coordinator, prepared


def v1_artifacts() -> dict[str, dict[str, Any]]:
    fixture_path = Path(__file__).parent / "fixtures" / "v1" / "artifacts.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    artifacts = fixture["artifacts"]
    canonical = json.dumps(
        artifacts, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    actual = "sha256:" + hashlib.sha256(canonical).hexdigest()
    if actual != fixture["artifacts_sha256"]:
        raise AssertionError("frozen v1 artifact fixture digest drifted")
    return artifacts


class ArtifactCodecMigrationTest(unittest.TestCase):
    def test_explicit_empty_codec_registries_remain_empty_and_defensively_copied(self) -> None:
        injected: dict[str, Any] = {}
        store = ArtifactStore(injected)
        coordinator = MigrationCoordinator({}, injected)
        injected.update(artifact_codecs())
        for lookup in (
            lambda: store._codec("state-marker"),
            lambda: coordinator._codec("state-marker"),
        ):
            with self.assertRaises(UsageError) as caught:
                lookup()
            self.assertEqual(caught.exception.code, "UNKNOWN_ARTIFACT_KIND")

    def test_decoded_artifacts_are_deeply_immutable_and_round_trip_cleanly(self) -> None:
        source = v1_artifacts()["dependency-graph"]
        codec = artifact_codecs()["dependency-graph"]
        decoded = codec.decode(source)

        with self.assertRaises(AttributeError):
            decoded.payload["hard_edges"].append({"from": "ENG-X", "to": "ENG-Y"})
        with self.assertRaises(TypeError):
            decoded.payload["hard_edges"][0]["from"] = "ENG-X"

        source["hard_edges"][0]["from"] = "caller-mutation"
        self.assertEqual(decoded.payload["hard_edges"][0]["from"], "ENG-1")
        encoded = codec.encode_v2(decoded)
        self.assertEqual(encoded["payload"], v1_artifacts()["dependency-graph"])
        round_trip = codec.decode(encoded)
        self.assertEqual(codec.encode_v2(round_trip), encoded)
        with self.assertRaises(TypeError):
            round_trip.provenance["source_hash"] = "changed"

    def test_registry_has_an_exhaustive_valid_v1_decoder(self) -> None:
        payloads = v1_artifacts()
        codecs = artifact_codecs()
        self.assertEqual(set(codecs), {spec.kind for spec in ARTIFACT_SPECS})
        self.assertEqual(
            set(codecs)
            - {
                "ContextSnapshot",
                "ContextDelta",
                "ContextManifest",
                "CompactionReceipt",
                "ContextBudgetPolicy",
            },
            set(payloads),
        )
        for kind, payload in payloads.items():
            with self.subTest(kind=kind):
                decoded = codecs[kind].decode(payload)
                self.assertEqual(decoded.kind, kind)
                self.assertEqual(decoded.schema_version, 1)
                self.assertTrue(decoded.needs_migration)
                self.assertEqual(decoded.provenance["source_schema_version"], 1)
                self.assertEqual(decoded.provenance["source_hash"], decoded.source_hash)

    def test_every_kind_rejects_malformed_future_and_drifted_artifacts(self) -> None:
        codecs = artifact_codecs()
        for kind, payload in v1_artifacts().items():
            codec = codecs[kind]
            with self.subTest(kind=kind, case="malformed"):
                malformed = json.loads(json.dumps(payload))
                malformed.pop("schema_version")
                with self.assertRaisesRegex(UsageError, "schema_version"):
                    codec.decode(malformed)

            with self.subTest(kind=kind, case="future"):
                future = {
                    "schema_version": 99,
                    **{k: v for k, v in payload.items() if k != "schema_version"},
                }
                with self.assertRaises(UsageError) as caught:
                    codec.decode(future)
                self.assertEqual(caught.exception.code, "FUTURE_ARTIFACT_VERSION")

            with self.subTest(kind=kind, case="v2-hash-drift"):
                encoded = codec.encode_v2(codec.decode(payload))
                encoded["revision"] = int(encoded["revision"]) + 1
                with self.assertRaises(UsageError) as caught:
                    codec.decode(encoded)
                self.assertEqual(caught.exception.code, "ARTIFACT_HASH_DRIFT")

            with self.subTest(kind=kind, case="boolean-schema-version"):
                boolean_version = {**payload, "schema_version": True}
                with self.assertRaises(UsageError) as caught:
                    codec.decode(boolean_version)
                self.assertEqual(caught.exception.code, "MALFORMED_ARTIFACT")

    def test_native_v1_hash_drift_is_classified_consistently(self) -> None:
        payload = v1_artifacts()["human-verification-policy"]
        payload["default"] = "disabled"
        with self.assertRaises(UsageError) as caught:
            artifact_codecs()["human-verification-policy"].decode(payload)
        self.assertEqual(caught.exception.code, "ARTIFACT_HASH_DRIFT")

    def test_native_revision_fields_reject_booleans(self) -> None:
        mutations = (
            ("state-marker", ("revision",)),
            ("isolation-receipt", ("plan_revision",)),
            ("wave-receipt", ("tasks", 0, "plan_revision")),
            ("wave-receipt", ("tasks", 1, "plan_revision")),
        )
        for kind, path in mutations:
            with self.subTest(kind=kind, path=path):
                payload = json.loads(json.dumps(v1_artifacts()[kind]))
                target: Any = payload
                for field in path[:-1]:
                    target = target[field]
                target[path[-1]] = True
                with self.assertRaises(UsageError) as caught:
                    artifact_codecs()[kind].decode(payload)
                self.assertEqual(caught.exception.code, "MALFORMED_ARTIFACT")

    def test_owned_validator_type_and_key_failures_are_malformed_artifacts(self) -> None:
        for mutation in (
            {"baseline_head": None},
            {"baseline_head": []},
        ):
            with self.subTest(mutation=mutation):
                payload = {**v1_artifacts()["isolation-receipt"], **mutation}
                with self.assertRaises(UsageError) as caught:
                    artifact_codecs()["isolation-receipt"].decode(payload)
                self.assertEqual(caught.exception.code, "MALFORMED_ARTIFACT")

    def test_v2_wrapper_metadata_and_provenance_fail_closed(self) -> None:
        codec = artifact_codecs()["state-marker"]
        decoded = codec.decode(v1_artifacts()["state-marker"])
        encoded = codec.encode_v2(decoded)

        def rehash(value: dict[str, Any]) -> dict[str, Any]:
            body = {key: item for key, item in value.items() if key != "integrity"}
            value["integrity"] = {"algorithm": "sha256", "digest": sha256_digest(body)}
            return value

        malformed = (
            {key: value for key, value in encoded.items() if key != "integrity"},
            {**encoded, "kind": "dependency-graph"},
            {**encoded, "revision": True},
            {**encoded, "integrity": {"algorithm": "md5", "digest": "bad"}},
            {**encoded, "integrity": {**encoded["integrity"], "unbound": "injected"}},
            rehash({**encoded, "payload": {}}),
            rehash({**encoded, "provenance": {}}),
            rehash({**encoded, "revision": 999}),
            rehash(
                {
                    **encoded,
                    "provenance": {**encoded["provenance"], "source_hash": "not-a-sha256"},
                }
            ),
            rehash(
                {
                    **encoded,
                    "provenance": {
                        **encoded["provenance"],
                        "source_product_version": "2.x",
                    },
                }
            ),
            rehash(
                {
                    **encoded,
                    "provenance": {**encoded["provenance"], "source_schema_version": 2},
                }
            ),
            rehash(
                {
                    **encoded,
                    "provenance": {**encoded["provenance"], "source_schema_version": 1.0},
                }
            ),
            rehash(
                {
                    **encoded,
                    "provenance": {**encoded["provenance"], "unexpected": "field"},
                }
            ),
            {**encoded, "schema_version": True},
            {**encoded, "schema_version": 1},
            {**encoded, "schema_version": 99},
        )
        for payload in malformed:
            with self.subTest(payload=payload), self.assertRaises(UsageError):
                codec.decode(payload)

        unsupported_source = {**v1_artifacts()["state-marker"], "schema_version": 0}
        with self.assertRaises(UsageError) as source_version:
            codec.decode(unsupported_source)
        self.assertEqual(source_version.exception.code, "MALFORMED_ARTIFACT")

        with self.assertRaises(UsageError) as wrong_kind:
            codec.encode_v2(replace(decoded, kind="dependency-graph"))
        self.assertEqual(wrong_kind.exception.code, "ARTIFACT_KIND_MISMATCH")

        with self.assertRaises(UsageError) as non_object:
            ArtifactStore()._decode_text("[]", Path("artifact.json"), "state-marker")
        self.assertEqual(non_object.exception.code, "MALFORMED_ARTIFACT")

    def test_read_only_inspection_never_mutates_and_write_migration_is_idempotent(self) -> None:
        store = ArtifactStore()
        for kind, payload in v1_artifacts().items():
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "artifact.json"
                path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
                original = path.read_bytes()

                preview = store.inspect(path, kind)
                self.assertTrue(preview["needs_migration"])
                self.assertEqual(path.read_bytes(), original)
                coordinator, prepared = _prepared(path, kind)
                self.assertEqual(len(prepared.migrations), 1)
                self.assertEqual(prepared.contract["migrations"][0]["kind"], kind)
                with self.assertRaises(GovernedStop) as unauthorized:
                    coordinator.commit(prepared, _authorization(prepared, decision="pending"))
                self.assertEqual(unauthorized.exception.code, "MIGRATION_APPROVAL_INVALID")
                self.assertEqual(path.read_bytes(), original)

                result = coordinator.commit(prepared, _authorization(prepared))
                self.assertEqual(result["status"], "migrated")
                persisted = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(persisted["schema_version"], 2)
                self.assertEqual(persisted["kind"], kind)
                self.assertEqual(persisted["payload"], payload)
                self.assertEqual(persisted["provenance"]["source_hash"], preview["source_hash"])

                second_coordinator, second_prepared = _prepared(path, kind)
                self.assertEqual(second_prepared.migrations, ())
                second = second_coordinator.commit(
                    second_prepared,
                    MigrationAuthorization(
                        command="task run",
                        target="ENG-1",
                        preview_hash=str(second_prepared.contract["migration_preview_hash"]),
                        receipt_id="not-required-for-noop",
                    ),
                )
                self.assertEqual(second["status"], "already-v2")
                self.assertTrue(second["read_back"])

    def test_authorized_write_rejects_stale_preview_and_source_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_text(
                json.dumps(v1_artifacts()["human-verification-policy"]),
                encoding="utf-8",
            )
            coordinator, prepared = _prepared(path, "human-verification-policy")
            with self.assertRaises(GovernedStop) as caught:
                coordinator.commit(
                    prepared,
                    MigrationAuthorization(
                        command="task run",
                        target="ENG-1",
                        preview_hash="sha256:" + "0" * 64,
                        receipt_id="approval-receipt-1",
                    ),
                )
            self.assertEqual(caught.exception.code, "MIGRATION_APPROVAL_INVALID")
            changed = v1_artifacts()["human-verification-policy"]
            changed["revision"] += 1
            changed.pop("policy_hash")
            changed["policy_hash"] = canonical_hash(changed)
            path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaises(GovernedStop) as drift:
                coordinator.commit(prepared, _authorization(prepared))
            self.assertEqual(drift.exception.code, "ARTIFACT_SOURCE_DRIFT")

    def test_concurrent_write_during_encode_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            source = v1_artifacts()["state-marker"]
            path.write_text(json.dumps(source), encoding="utf-8")
            codec = artifact_codecs()["state-marker"]
            original_encode = codec.encode_v2

            def concurrent_encode(artifact: Any) -> dict[str, Any]:
                concurrent = dict(source)
                concurrent["run_id"] = "concurrent-write"
                path.write_text(json.dumps(concurrent), encoding="utf-8")
                return original_encode(artifact)

            codec.encode_v2 = concurrent_encode  # type: ignore[method-assign]
            coordinator = MigrationCoordinator(
                {"filesystem": FilesystemArtifactBackend()}, {"state-marker": codec}
            )
            prepared = coordinator.prepare(
                compile_public_command("task run", ("ENG-1",)),
                (ArtifactBinding("filesystem", str(path), "state-marker"),),
            )
            with self.assertRaises(GovernedStop) as caught:
                coordinator.commit(prepared, _authorization(prepared))
            self.assertEqual(caught.exception.code, "ARTIFACT_SOURCE_DRIFT")
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8"))["run_id"], "concurrent-write"
            )

    def test_failed_v2_readback_restores_exact_v1_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            source_text = json.dumps(v1_artifacts()["state-marker"], indent=1) + "\n"
            path.write_text(source_text, encoding="utf-8")

            class CorruptingReadbackBackend(FilesystemArtifactBackend):
                def __init__(self) -> None:
                    self.corrupt = False

                def read(self, locator: str) -> ArtifactRecord:
                    record = super().read(locator)
                    if self.corrupt and record.value.get("kind") == "state-marker":
                        corrupted = dict(record.value)
                        corrupted["revision"] = int(corrupted["revision"]) + 1
                        return ArtifactRecord(locator, record.revision_token, corrupted)
                    return record

                def commit(
                    self,
                    changes: Any,
                    authorization: MigrationAuthorization,
                ) -> tuple[ArtifactRecord, ...]:
                    self.corrupt = True
                    return super().commit(changes, authorization)

            backend = CorruptingReadbackBackend()
            coordinator = MigrationCoordinator({"filesystem": backend})
            prepared = coordinator.prepare(
                compile_public_command("task run", ("ENG-1",)),
                (ArtifactBinding("filesystem", str(path), "state-marker"),),
            )
            with self.assertRaises(UsageError) as caught:
                coordinator.commit(prepared, _authorization(prepared))
            self.assertEqual(caught.exception.code, "ARTIFACT_READBACK_MISMATCH")
            self.assertEqual(path.read_text(encoding="utf-8"), source_text)

    def test_batch_rollback_restores_every_safe_path_while_preserving_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = tuple(root / name for name in ("a.json", "b.json", "c.json"))
            originals = {path: json.dumps({"original": path.stem}) + "\n" for path in paths}
            for path, content in originals.items():
                path.write_text(content, encoding="utf-8")

            backend = FilesystemArtifactBackend()
            changes = tuple(
                ArtifactChange(
                    locator=str(path),
                    kind="state-marker",
                    expected_revision_token=backend.read(str(path)).revision_token,
                    value={"replacement": path.stem},
                )
                for path in paths
            )
            authorization = MigrationAuthorization(
                command="task run",
                target="ENG-1",
                preview_hash="sha256:" + "a" * 64,
                receipt_id="receipt-1",
            )
            concurrent = json.dumps({"concurrent": True}) + "\n"
            real_link = os.link

            def fail_third_write(
                source: Path, target: Path, *, follow_symlinks: bool = True
            ) -> None:
                if Path(target) == paths[2] and ".migration-" in Path(source).name:
                    paths[1].write_text(concurrent, encoding="utf-8")
                    raise FilesystemError("FILE_WRITE_FAILED", "injected third-write failure")
                real_link(source, target, follow_symlinks=follow_symlinks)

            with (
                patch.object(
                    migrations_module.os,
                    "link",
                    side_effect=fail_third_write,
                ),
                self.assertRaises(GovernedStop) as caught,
            ):
                backend.commit(changes, authorization)

            self.assertEqual(caught.exception.code, "ARTIFACT_ROLLBACK_INCOMPLETE")
            self.assertEqual(paths[0].read_text(encoding="utf-8"), originals[paths[0]])
            self.assertEqual(paths[1].read_text(encoding="utf-8"), concurrent)
            self.assertEqual(paths[2].read_text(encoding="utf-8"), originals[paths[2]])
            self.assertEqual(
                caught.exception.details["restored"],
                [str(paths[2]), str(paths[0])],
            )
            self.assertEqual(caught.exception.details["preserved_drift"], [str(paths[1])])
            self.assertEqual(
                caught.exception.details["recoverable"][0]["backup"],
                str(next(root.glob(".b.json.backup-*"))),
            )

    def test_artifact_publication_race_preserves_live_and_backup_versions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "state.json"
            original = json.dumps({"old": 1}) + "\n"
            concurrent = json.dumps({"user": 2}) + "\n"
            path.write_text(original, encoding="utf-8")
            backend = FilesystemArtifactBackend()
            change = ArtifactChange(
                locator=str(path),
                kind="state-marker",
                expected_revision_token=backend.read(str(path)).revision_token,
                value={"replacement": True},
            )
            authorization = MigrationAuthorization(
                command="task run",
                target="ENG-1",
                preview_hash="sha256:" + "a" * 64,
                receipt_id="receipt-1",
            )
            real_link = os.link

            def race_publication(
                source: Path, target: Path, *, follow_symlinks: bool = True
            ) -> None:
                if Path(target) == path and ".migration-" in Path(source).name:
                    path.write_text(concurrent, encoding="utf-8")
                real_link(source, target, follow_symlinks=follow_symlinks)

            with (
                patch.object(migrations_module.os, "link", side_effect=race_publication),
                self.assertRaises(GovernedStop) as caught,
            ):
                backend.commit((change,), authorization)
            self.assertEqual(caught.exception.code, "ARTIFACT_ROLLBACK_INCOMPLETE")
            self.assertEqual(path.read_text(encoding="utf-8"), concurrent)
            backup = Path(caught.exception.details["recoverable"][0]["backup"])
            self.assertEqual(backup.read_text(encoding="utf-8"), original)

    def test_artifact_rollback_quarantines_before_touching_live_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = (root / "a.json", root / "b.json")
            originals = {path: json.dumps({"old": path.stem}) + "\n" for path in paths}
            for path, content in originals.items():
                path.write_text(content, encoding="utf-8")
            concurrent = json.dumps({"user": True}) + "\n"
            backend = FilesystemArtifactBackend()
            changes = tuple(
                ArtifactChange(
                    locator=str(path),
                    kind="state-marker",
                    expected_revision_token=backend.read(str(path)).revision_token,
                    value={"replacement": path.stem},
                )
                for path in paths
            )
            authorization = MigrationAuthorization(
                command="task run",
                target="ENG-1",
                preview_hash="sha256:" + "a" * 64,
                receipt_id="receipt-1",
            )
            real_link = os.link
            real_replace = os.replace

            def fail_second_publication(
                source: Path, target: Path, *, follow_symlinks: bool = True
            ) -> None:
                if Path(target) == paths[1] and ".migration-" in Path(source).name:
                    raise OSError("later publication failed")
                real_link(source, target, follow_symlinks=follow_symlinks)

            def race_quarantine(source: Path, target: Path) -> None:
                if Path(source) == paths[0] and ".rollback-" in Path(target).name:
                    paths[0].write_text(concurrent, encoding="utf-8")
                real_replace(source, target)

            with (
                patch.object(migrations_module.os, "link", side_effect=fail_second_publication),
                patch.object(migrations_module.os, "replace", side_effect=race_quarantine),
                self.assertRaises(GovernedStop) as caught,
            ):
                backend.commit(changes, authorization)
            self.assertEqual(caught.exception.code, "ARTIFACT_ROLLBACK_INCOMPLETE")
            self.assertEqual(paths[0].read_text(encoding="utf-8"), concurrent)
            self.assertEqual(paths[1].read_text(encoding="utf-8"), originals[paths[1]])

    def test_artifact_source_move_drift_names_every_recoverable_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "state.json"
            path.write_text(json.dumps({"old": 1}) + "\n", encoding="utf-8")
            backend = FilesystemArtifactBackend()
            change = ArtifactChange(
                locator=str(path),
                kind="state-marker",
                expected_revision_token=backend.read(str(path)).revision_token,
                value={"replacement": True},
            )
            authorization = MigrationAuthorization(
                command="task run",
                target="ENG-1",
                preview_hash="sha256:" + "a" * 64,
                receipt_id="receipt-1",
            )
            real_replace = os.replace

            def replace_with_drift(source: Path, target: Path) -> None:
                if Path(source) == path and ".backup-" in Path(target).name:
                    path.write_text(json.dumps({"moved": "user"}) + "\n", encoding="utf-8")
                    real_replace(source, target)
                    path.write_text(json.dumps({"live": "user"}) + "\n", encoding="utf-8")
                    return
                real_replace(source, target)

            with (
                patch.object(migrations_module.os, "replace", side_effect=replace_with_drift),
                self.assertRaises(FilesystemError) as caught,
            ):
                backend.commit((change,), authorization)
            self.assertEqual(caught.exception.code, "ARTIFACT_ROLLBACK_FAILED")
            backup = Path(caught.exception.details["backup"])
            self.assertEqual(json.loads(path.read_text()), {"live": "user"})
            self.assertEqual(json.loads(backup.read_text()), {"moved": "user"})

    def test_existing_artifact_lock_stops_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            source_text = json.dumps(v1_artifacts()["state-marker"])
            path.write_text(source_text, encoding="utf-8")
            lock = path.with_name(f".{path.name}.linear-spanks.lock")
            lock.write_text("owned\n", encoding="utf-8")
            coordinator, prepared = _prepared(path, "state-marker")
            with self.assertRaises(GovernedStop) as caught:
                coordinator.commit(prepared, _authorization(prepared))
            self.assertEqual(caught.exception.code, "ARTIFACT_WRITE_LOCKED")
            self.assertEqual(path.read_text(encoding="utf-8"), source_text)

    def test_read_only_preparation_is_in_memory_and_cannot_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            source = json.dumps(v1_artifacts()["state-marker"], sort_keys=True)
            path.write_text(source, encoding="utf-8")
            coordinator, prepared = _prepared(path, "state-marker", command="project review")
            self.assertEqual(prepared.migrations[0]["action"], "in-memory-only")
            self.assertEqual(path.read_text(encoding="utf-8"), source)
            authorization = MigrationAuthorization(
                command="project review",
                target="project-1",
                preview_hash=str(prepared.contract["migration_preview_hash"]),
                receipt_id="approval-receipt-1",
            )
            with self.assertRaises(GovernedStop) as caught:
                coordinator.commit(prepared, authorization)
            self.assertEqual(caught.exception.code, "MIGRATION_WRITE_NOT_ALLOWED")
            self.assertEqual(path.read_text(encoding="utf-8"), source)

    def test_injected_linear_hosted_backend_uses_the_same_authorization_contract(self) -> None:
        class LinearArtifactBackend:
            name = "linear"

            def __init__(self, value: dict[str, Any]) -> None:
                self.value = value
                self.revision = 1

            def read(self, locator: str) -> ArtifactRecord:
                return ArtifactRecord(
                    locator,
                    f"linear-revision:{self.revision}",
                    json.loads(json.dumps(self.value)),
                )

            def commit(
                self,
                changes: Any,
                authorization: MigrationAuthorization,
            ) -> tuple[ArtifactRecord, ...]:
                self.assert_authorization = authorization
                change: ArtifactChange = changes[0]
                if change.expected_revision_token != f"linear-revision:{self.revision}":
                    raise GovernedStop("ARTIFACT_SOURCE_DRIFT", "Linear revision changed")
                self.value = dict(change.value)
                self.revision += 1
                return (self.read(change.locator),)

        backend = LinearArtifactBackend(v1_artifacts()["state-marker"])
        coordinator = MigrationCoordinator({"linear": backend})
        prepared = coordinator.prepare(
            compile_public_command("task run", ("ENG-1",)),
            (ArtifactBinding("linear", "comment:artifact-1", "state-marker"),),
        )
        self.assertEqual(prepared.migrations[0]["backend"], "linear")
        result = coordinator.commit(prepared, _authorization(prepared))
        self.assertEqual(result["status"], "migrated")
        self.assertEqual(backend.value["schema_version"], 2)

    def test_store_rejects_invalid_json_and_unknown_kinds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "artifact.json"
            path.write_text("{", encoding="utf-8")
            with self.assertRaises(UsageError) as invalid:
                ArtifactStore().read(path, "state-marker")
            self.assertEqual(invalid.exception.code, "INVALID_JSON")
            path.write_text(json.dumps(v1_artifacts()["state-marker"]), encoding="utf-8")
            with self.assertRaises(UsageError) as unknown:
                ArtifactStore().read(path, "not-a-kind")
            self.assertEqual(unknown.exception.code, "UNKNOWN_ARTIFACT_KIND")

    def test_authorization_payload_parser_is_exact_and_typed(self) -> None:
        valid = {
            "kind": "migration-authorization",
            "schema_version": 2,
            "command": "task run",
            "target": "ENG-1",
            "preview_hash": "sha256:" + "a" * 64,
            "receipt_id": "receipt-1",
            "decision": "approved",
        }
        parsed = parse_migration_authorization(valid)
        self.assertEqual(parsed.command, "task run")
        self.assertEqual(parsed.target, "ENG-1")
        self.assertEqual(parsed.receipt_id, "receipt-1")

        malformed = (
            {key: value for key, value in valid.items() if key != "decision"},
            {**valid, "kind": "approval"},
            {**valid, "schema_version": 1},
            {**valid, "receipt_id": ""},
            {**valid, "receipt_id": "   "},
            {**valid, "receipt_id": " receipt-1"},
            {**valid, "receipt_id": "<approved-write-receipt-id>"},
            {**valid, "receipt_id": " <approved-write-receipt-id>"},
            {**valid, "target": 7},
        )
        for payload in malformed:
            with self.subTest(payload=payload), self.assertRaises(UsageError) as caught:
                parse_migration_authorization(payload)
            self.assertEqual(caught.exception.code, "INVALID_MIGRATION_AUTHORIZATION")

    def test_filesystem_backend_rejects_invalid_locators_objects_and_batches(self) -> None:
        backend = FilesystemArtifactBackend()
        authorization = MigrationAuthorization(
            command="task run",
            target="ENG-1",
            preview_hash="sha256:" + "a" * 64,
            receipt_id="receipt-1",
        )
        with self.assertRaises(UsageError) as locator:
            backend.read("")
        self.assertEqual(locator.exception.code, "INVALID_ARTIFACT_LOCATOR")
        with self.assertRaises(UsageError) as malformed:
            backend._record_from_text("artifact.json", "[]")
        self.assertEqual(malformed.exception.code, "MALFORMED_ARTIFACT")
        immutable = backend._record_from_text(
            "artifact.json",
            '{"nested":{"items":[1]}}',
        )
        with self.assertRaises(TypeError):
            immutable.value["nested"]["items"][0] = 2
        self.assertEqual(backend.commit((), authorization), ())

        change = ArtifactChange(
            locator="artifact.json",
            kind="state-marker",
            expected_revision_token="sha256:" + "0" * 64,
            value={},
        )
        with self.assertRaises(UsageError) as duplicate:
            backend.commit((change, change), authorization)
        self.assertEqual(duplicate.exception.code, "DUPLICATE_ARTIFACT")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "artifact.json"
            path.write_text(json.dumps(v1_artifacts()["state-marker"]), encoding="utf-8")
            stale = replace(change, locator=str(path))
            with self.assertRaises(GovernedStop) as drift:
                backend.commit((stale,), authorization)
            self.assertEqual(drift.exception.code, "ARTIFACT_SOURCE_DRIFT")

    def test_coordinator_rejects_invalid_identity_registry_and_duplicate_bindings(self) -> None:
        source = v1_artifacts()["state-marker"]

        class MemoryBackend:
            name = "memory"

            def read(self, locator: str) -> ArtifactRecord:
                return ArtifactRecord(locator, "revision:1", source)

            def commit(
                self,
                changes: Any,
                authorization: MigrationAuthorization,
            ) -> tuple[ArtifactRecord, ...]:
                raise AssertionError("commit must not be reached")

        compiled = compile_public_command("task run", ("ENG-1",))
        coordinator = MigrationCoordinator({"memory": MemoryBackend()})
        with self.assertRaises(UsageError) as missing_invocation:
            coordinator.authorization_template(replace(compiled, contract={}))
        self.assertEqual(missing_invocation.exception.code, "INVALID_EXECUTION_ENVELOPE")
        with self.assertRaises(UsageError) as invalid_identity:
            coordinator.authorization_template(
                replace(compiled, contract={"invocation": {"command": 7, "target": "ENG-1"}})
            )
        self.assertEqual(invalid_identity.exception.code, "INVALID_EXECUTION_ENVELOPE")
        for field, value in (
            ("command", ""),
            ("command", " "),
            ("command", " task run"),
            ("command", "project run"),
            ("target", ""),
            ("target", " "),
            ("target", " ENG-1"),
        ):
            with self.subTest(field=field, value=value):
                invocation = {"command": "task run", "target": "ENG-1", field: value}
                invalid = replace(compiled, contract={"invocation": invocation})
                with self.assertRaises(UsageError) as identity:
                    coordinator.authorization_template(invalid)
                self.assertEqual(identity.exception.code, "INVALID_EXECUTION_ENVELOPE")

        binding = ArtifactBinding("memory", "state:1", "state-marker")
        with self.assertRaises(UsageError) as duplicate:
            coordinator.prepare(compiled, (binding, binding))
        self.assertEqual(duplicate.exception.code, "DUPLICATE_ARTIFACT")
        with self.assertRaises(UsageError) as backend:
            coordinator.prepare(
                compiled,
                (ArtifactBinding("missing", "state:1", "state-marker"),),
            )
        self.assertEqual(backend.exception.code, "ARTIFACT_BACKEND_NOT_FOUND")
        with self.assertRaises(UsageError) as codec:
            coordinator.prepare(
                compiled,
                (ArtifactBinding("memory", "state:1", "unknown-kind"),),
            )
        self.assertEqual(codec.exception.code, "UNKNOWN_ARTIFACT_KIND")

        prepared = coordinator.prepare(compiled, (binding,))
        invalid_contract = dict(prepared.contract)
        invalid_contract["invocation"] = {"command": "task run", "target": " "}
        invalid_prepared = replace(prepared, contract=invalid_contract)
        with self.assertRaises(UsageError) as invalid_commit:
            coordinator.commit(
                invalid_prepared,
                MigrationAuthorization(
                    command="task run",
                    target=" ",
                    preview_hash=str(prepared.contract["migration_preview_hash"]),
                    receipt_id="receipt-1",
                ),
            )
        self.assertEqual(invalid_commit.exception.code, "INVALID_EXECUTION_ENVELOPE")
        template = coordinator.authorization_template(prepared)
        self.assertEqual(template["command"], "task run")
        self.assertEqual(template["target"], "ENG-1")
        self.assertEqual(template["receipt_id"], "")
        self.assertEqual(template["decision"], "pending")
        with self.assertRaises(UsageError) as incomplete:
            parse_migration_authorization(template)
        self.assertEqual(incomplete.exception.code, "INVALID_MIGRATION_AUTHORIZATION")
        with self.assertRaises(GovernedStop) as placeholder:
            coordinator.commit(
                prepared,
                MigrationAuthorization(
                    command="task run",
                    target="ENG-1",
                    preview_hash=prepared.contract["migration_preview_hash"],
                    receipt_id="<approved-write-receipt-id>",
                ),
            )
        self.assertEqual(placeholder.exception.code, "MIGRATION_APPROVAL_INVALID")
        with self.assertRaises(GovernedStop) as prefixed_placeholder:
            coordinator.commit(
                prepared,
                MigrationAuthorization(
                    command="task run",
                    target="ENG-1",
                    preview_hash=prepared.contract["migration_preview_hash"],
                    receipt_id=" <approved-write-receipt-id>",
                ),
            )
        self.assertEqual(prefixed_placeholder.exception.code, "MIGRATION_APPROVAL_INVALID")

    def test_coordinator_rejects_preview_drift_and_multi_backend_writes(self) -> None:
        source = v1_artifacts()["state-marker"]

        class MemoryBackend:
            def __init__(self, name: str) -> None:
                self.name = name

            def read(self, locator: str) -> ArtifactRecord:
                return ArtifactRecord(locator, f"{self.name}:revision:1", source)

            def commit(
                self,
                changes: Any,
                authorization: MigrationAuthorization,
            ) -> tuple[ArtifactRecord, ...]:
                raise AssertionError("commit must not be reached")

        compiled = compile_public_command("task run", ("ENG-1",))
        coordinator = MigrationCoordinator(
            {"first": MemoryBackend("first"), "second": MemoryBackend("second")}
        )
        one = coordinator.prepare(
            compiled,
            (ArtifactBinding("first", "state:1", "state-marker"),),
        )
        drifted_contract = dict(one.contract)
        drifted_contract["migration_preview_hash"] = "sha256:" + "0" * 64
        drifted = replace(one, contract=drifted_contract)
        with self.assertRaises(GovernedStop) as preview_drift:
            coordinator.commit(drifted, _authorization(one))
        self.assertEqual(preview_drift.exception.code, "MIGRATION_PREVIEW_DRIFT")

        both = coordinator.prepare(
            compiled,
            (
                ArtifactBinding("first", "state:1", "state-marker"),
                ArtifactBinding("second", "state:2", "state-marker"),
            ),
        )
        with self.assertRaises(GovernedStop) as multi_backend:
            coordinator.commit(both, _authorization(both))
        self.assertEqual(multi_backend.exception.code, "MIGRATION_MULTI_BACKEND_NOT_ATOMIC")

    def test_coordinator_requires_complete_fresh_v2_readback(self) -> None:
        source = v1_artifacts()["state-marker"]

        class OutcomeBackend:
            name = "memory"

            def __init__(self, outcome: str) -> None:
                self.outcome = outcome

            def read(self, locator: str) -> ArtifactRecord:
                return ArtifactRecord(locator, "revision:1", source)

            def commit(
                self,
                changes: Any,
                authorization: MigrationAuthorization,
            ) -> tuple[ArtifactRecord, ...]:
                del authorization
                change: ArtifactChange = changes[0]
                if self.outcome == "empty":
                    return ()
                if self.outcome == "wrong-locator":
                    return (ArtifactRecord("other", "revision:2", change.value),)
                return (ArtifactRecord(change.locator, "revision:2", source),)

        compiled = compile_public_command("task run", ("ENG-1",))
        expected = {
            "empty": "Artifact backend returned an incomplete read-back",
            "wrong-locator": "Artifact backend omitted read-back",
            "v1": "Artifact remained at v1 after commit",
        }
        for outcome, message in expected.items():
            with self.subTest(outcome=outcome):
                coordinator = MigrationCoordinator({"memory": OutcomeBackend(outcome)})
                prepared = coordinator.prepare(
                    compiled,
                    (ArtifactBinding("memory", "state:1", "state-marker"),),
                )
                with self.assertRaisesRegex(Exception, message):
                    coordinator.commit(prepared, _authorization(prepared))


if __name__ == "__main__":
    unittest.main()
