"""Versioned v1 readers and authorized lazy v2 artifact migration."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

from ..core.errors import UsageError
from ..core.hashing import sha256_digest
from ..core.jsonio import (
    StrictJsonError,
    freeze_json,
    mutable_json_copy,
    read_text,
    strict_json_loads,
)
from ..core.types import DecodedArtifact, JsonObject
from . import _context_v1 as context_v1
from . import _graphs_v1 as graphs_v1
from . import _isolation_v1 as isolation_v1
from . import _orchestration_v1 as orchestration_v1
from . import _runtime_v1 as runtime_v1
from . import _state_v1 as state_v1
from . import _verification_v1 as verification_v1
from .context import validate_context_artifact

Validator = Callable[[dict[str, Any]], Any]
CONTEXT_KINDS = {
    "ContextSnapshot",
    "ContextDelta",
    "ContextManifest",
    "CompactionReceipt",
    "ContextBudgetPolicy",
}


@dataclass(frozen=True, slots=True)
class ArtifactKindSpec:
    kind: str
    source_schema_versions: tuple[int, ...]
    revision_fields: tuple[str, ...]
    validator: Validator


def _validate_state_marker(payload: dict[str, Any]) -> None:
    state_v1.validate_marker_semantics(payload)


def _validator(function: Callable[..., Any]) -> Validator:
    def validate(payload: dict[str, Any]) -> Any:
        return function(payload)

    return validate


ARTIFACT_SPECS = (
    *(
        ArtifactKindSpec(kind, (1,), ("revision",), validate_context_artifact)
        for kind in (
            "ContextSnapshot",
            "ContextDelta",
            "ContextManifest",
            "CompactionReceipt",
            "ContextBudgetPolicy",
        )
    ),
    ArtifactKindSpec("state-marker", (1,), ("revision",), _validate_state_marker),
    ArtifactKindSpec(
        "dependency-graph",
        (1,),
        ("graph_revision",),
        _validator(graphs_v1.validate_dependency_graph),
    ),
    ArtifactKindSpec(
        "human-verification-policy",
        (1,),
        ("revision",),
        _validator(verification_v1.validate_human_project_policy),
    ),
    ArtifactKindSpec(
        "human-verification-override",
        (1,),
        ("revision",),
        _validator(verification_v1.validate_human_milestone_override),
    ),
    ArtifactKindSpec(
        "human-verification-gate",
        (1,),
        ("gate_revision",),
        _validator(verification_v1.validate_human_gate),
    ),
    ArtifactKindSpec(
        "human-verification-checklist",
        (1,),
        ("checklist_revision",),
        _validator(verification_v1.validate_human_checklist),
    ),
    ArtifactKindSpec(
        "human-verification-repair",
        (1,),
        ("failure_revision",),
        _validator(verification_v1.validate_human_repair_task),
    ),
    ArtifactKindSpec(
        "milestone-runtime-projection",
        (1,),
        ("revision", "event_count"),
        _validator(runtime_v1.validate_milestone_runtime),
    ),
    ArtifactKindSpec(
        "autopilot-policy",
        (1,),
        ("revision",),
        _validator(runtime_v1.validate_guarded_autopilot_binding),
    ),
    ArtifactKindSpec(
        "repository-checkpoint",
        (1,),
        (),
        _validator(context_v1.validate_repository_checkpoint),
    ),
    ArtifactKindSpec(
        "project-context-capsule",
        (1,),
        ("project_revision",),
        _validator(context_v1.validate_project_capsule),
    ),
    ArtifactKindSpec(
        "verification-ledger",
        (1, 2),
        ("plan_revision",),
        _validator(orchestration_v1.validate_verification_ledger),
    ),
    ArtifactKindSpec(
        "project-loop-receipt",
        (1,),
        ("project_revision",),
        _validator(orchestration_v1.validate_project_loop_receipt),
    ),
    ArtifactKindSpec(
        "milestone-loop-receipt",
        (1,),
        ("milestone_revision",),
        _validator(orchestration_v1.validate_milestone_loop_receipt),
    ),
    ArtifactKindSpec(
        "isolation-receipt",
        (1,),
        ("plan_revision",),
        _validator(isolation_v1.validate_isolation_receipt),
    ),
    ArtifactKindSpec("wave-receipt", (1,), (), _validator(graphs_v1.validate_wave_receipt)),
    ArtifactKindSpec(
        "rollover-receipt", (1,), (), _validator(context_v1.validate_rollover_receipt)
    ),
)


class VersionedArtifactCodec:
    """Decode one durable kind and emit a deterministic v2 wrapper."""

    def __init__(self, spec: ArtifactKindSpec) -> None:
        self.spec = spec
        self.kind = spec.kind

    def _revision(self, value: Mapping[str, Any]) -> int:
        for field in self.spec.revision_fields:
            revision = value.get(field)
            if isinstance(revision, int) and not isinstance(revision, bool) and revision >= 0:
                return revision
        return 1

    def _decode_v2(self, value: Mapping[str, Any]) -> DecodedArtifact:
        required = {"kind", "schema_version", "revision", "provenance", "payload", "integrity"}
        if set(value) != required:
            raise UsageError("MALFORMED_ARTIFACT", f"{self.kind} v2 fields are incomplete")
        if value.get("kind") != self.kind:
            raise UsageError(
                "ARTIFACT_KIND_MISMATCH",
                f"Expected {self.kind}, found {value.get('kind')}",
            )
        revision = value.get("revision")
        provenance = value.get("provenance")
        payload = value.get("payload")
        integrity = value.get("integrity")
        if (
            not isinstance(revision, int)
            or isinstance(revision, bool)
            or revision < 0
            or not isinstance(provenance, Mapping)
            or not isinstance(payload, Mapping)
            or not isinstance(integrity, Mapping)
        ):
            raise UsageError("MALFORMED_ARTIFACT", f"{self.kind} v2 metadata is invalid")
        if set(integrity) != {"algorithm", "digest"}:
            raise UsageError("MALFORMED_ARTIFACT", f"{self.kind} integrity fields are invalid")
        if integrity.get("algorithm") != "sha256" or not isinstance(integrity.get("digest"), str):
            raise UsageError("MALFORMED_ARTIFACT", f"{self.kind} integrity policy is invalid")
        body = {
            "kind": self.kind,
            "schema_version": 2,
            "revision": revision,
            "provenance": provenance,
            "payload": payload,
        }
        expected = sha256_digest(body)
        if integrity["digest"] != expected:
            raise UsageError(
                "ARTIFACT_HASH_DRIFT",
                f"{self.kind} integrity digest does not match its content",
                details={"expected": expected, "actual": integrity["digest"]},
            )
        try:
            self.spec.validator(cast(dict[str, Any], mutable_json_copy(payload)))
        except (KeyError, TypeError, ValueError) as error:
            raise UsageError("MALFORMED_ARTIFACT", str(error)) from error
        if set(provenance) != {
            "source_product_version",
            "source_schema_version",
            "source_hash",
        }:
            raise UsageError("MALFORMED_ARTIFACT", "Artifact provenance fields are invalid")
        source_product_version = provenance.get("source_product_version")
        source_schema_version = provenance.get("source_schema_version")
        source_hash = provenance.get("source_hash")
        expected_source_hash = sha256_digest(payload)
        if (
            source_product_version
            != (
                "2.x" if self.kind in CONTEXT_KINDS or payload.get("schema_version") == 2 else "1.x"
            )
            or not isinstance(source_schema_version, int)
            or isinstance(source_schema_version, bool)
            or source_schema_version not in self.spec.source_schema_versions
            or source_hash != expected_source_hash
        ):
            raise UsageError("MALFORMED_ARTIFACT", "Artifact provenance is invalid")
        if revision != self._revision(payload):
            raise UsageError(
                "MALFORMED_ARTIFACT",
                f"{self.kind} revision does not match its source payload",
            )
        return DecodedArtifact(
            kind=self.kind,
            schema_version=2,
            revision=revision,
            provenance=cast(Mapping[str, Any], freeze_json(provenance)),
            payload=cast(Mapping[str, Any], freeze_json(payload)),
            integrity=cast(Mapping[str, Any], freeze_json(integrity)),
            needs_migration=False,
            source_hash=expected_source_hash,
        )

    def decode(self, value: Mapping[str, Any]) -> DecodedArtifact:
        schema_version = value.get("schema_version")
        native_source = (
            self.kind in CONTEXT_KINDS and value.get("kind") == self.kind and schema_version == 1
        )
        if (
            (value.get("kind") is not None and not native_source)
            or "integrity" in value
            or "payload" in value
        ):
            if not isinstance(schema_version, int) or isinstance(schema_version, bool):
                raise UsageError("MALFORMED_ARTIFACT", "Artifact schema_version is invalid")
            if schema_version > 2:
                raise UsageError(
                    "FUTURE_ARTIFACT_VERSION",
                    f"Artifact schema_version {schema_version} is newer than supported version 2",
                )
            if schema_version != 2:
                raise UsageError("MALFORMED_ARTIFACT", "Versioned artifact wrapper is malformed")
            return self._decode_v2(value)
        if not isinstance(schema_version, int) or isinstance(schema_version, bool):
            raise UsageError("MALFORMED_ARTIFACT", "v1 artifact requires schema_version")
        if schema_version not in self.spec.source_schema_versions:
            if schema_version > max(self.spec.source_schema_versions):
                raise UsageError(
                    "FUTURE_ARTIFACT_VERSION",
                    f"Unsupported {self.kind} source schema_version {schema_version}",
                )
            raise UsageError("MALFORMED_ARTIFACT", f"Unsupported {self.kind} source schema_version")
        raw = cast(dict[str, Any], mutable_json_copy(value))
        try:
            self.spec.validator(raw)
        except (KeyError, TypeError, ValueError) as error:
            code = "ARTIFACT_HASH_DRIFT" if "DRIFT" in str(error).upper() else "MALFORMED_ARTIFACT"
            raise UsageError(code, str(error)) from error
        source_hash = sha256_digest(raw)
        provenance = {
            "source_product_version": "2.x"
            if self.kind in CONTEXT_KINDS or schema_version == 2
            else "1.x",
            "source_schema_version": schema_version,
            "source_hash": source_hash,
        }
        return DecodedArtifact(
            kind=self.kind,
            schema_version=schema_version,
            revision=self._revision(raw),
            provenance=cast(Mapping[str, Any], freeze_json(provenance)),
            payload=cast(Mapping[str, Any], freeze_json(raw)),
            integrity=cast(
                Mapping[str, Any],
                freeze_json(
                    {
                        "algorithm": "sha256",
                        "digest": source_hash,
                        "policy": "source-snapshot",
                    }
                ),
            ),
            needs_migration=True,
            source_hash=source_hash,
        )

    def encode_v2(self, artifact: DecodedArtifact) -> JsonObject:
        if artifact.kind != self.kind:
            raise UsageError(
                "ARTIFACT_KIND_MISMATCH", f"Cannot encode {artifact.kind} as {self.kind}"
            )
        body: JsonObject = {
            "kind": self.kind,
            "schema_version": 2,
            "revision": artifact.revision,
            "provenance": mutable_json_copy(artifact.provenance),
            "payload": mutable_json_copy(artifact.payload),
        }
        body["integrity"] = {"algorithm": "sha256", "digest": sha256_digest(body)}
        return body

    def migration_preview(self, artifact: DecodedArtifact, source: str) -> Mapping[str, Any]:
        return {
            "kind": self.kind,
            "locator": source,
            "from_schema_version": artifact.schema_version,
            "to_schema_version": 2,
            "revision": artifact.revision,
            "source_hash": artifact.source_hash,
            "action": "rewrite-on-authorized-write" if artifact.needs_migration else "none",
        }


def artifact_codecs() -> Mapping[str, VersionedArtifactCodec]:
    return MappingProxyType({spec.kind: VersionedArtifactCodec(spec) for spec in ARTIFACT_SPECS})


class ArtifactStore:
    """Filesystem adapter enforcing preview, refresh, authorization, and read-back."""

    def __init__(self, codecs: Mapping[str, VersionedArtifactCodec] | None = None) -> None:
        selected = artifact_codecs() if codecs is None else codecs
        self._codecs = MappingProxyType(dict(selected))

    def _codec(self, kind: str) -> VersionedArtifactCodec:
        codec = self._codecs.get(kind)
        if codec is None:
            raise UsageError(
                "UNKNOWN_ARTIFACT_KIND",
                f"Unknown artifact kind: {kind}",
                details={"known_kinds": sorted(self._codecs)},
            )
        return codec

    def read(self, path: Path, kind: str) -> DecodedArtifact:
        text = read_text(path)
        return self._decode_text(text, path, kind)

    def _decode_text(self, text: str, path: Path, kind: str) -> DecodedArtifact:
        try:
            value = strict_json_loads(text)
        except (json.JSONDecodeError, StrictJsonError) as error:
            message = error.msg if isinstance(error, json.JSONDecodeError) else str(error)
            raise UsageError(
                "INVALID_JSON",
                f"Artifact is not valid JSON: {message}",
                details={"path": str(path)},
            ) from error
        if not isinstance(value, dict):
            raise UsageError("MALFORMED_ARTIFACT", "Artifact must contain a JSON object")
        return self._codec(kind).decode(value)

    def inspect(self, path: Path, kind: str) -> Mapping[str, Any]:
        artifact = self.read(path, kind)
        return {
            "kind": artifact.kind,
            "schema_version": artifact.schema_version,
            "revision": artifact.revision,
            "source_hash": artifact.source_hash,
            "needs_migration": artifact.needs_migration,
            "migration": self._codec(kind).migration_preview(artifact, str(path)),
        }
