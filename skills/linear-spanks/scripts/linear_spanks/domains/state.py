"""Workflow state, issue transition, hashing, and idempotency operations."""

from __future__ import annotations

from typing import Any

from ..contracts.legacy import load_json
from ..core.hashing import sha256_digest
from ..core.legacy_constants import MARKER_RE, WORKFLOW_PATH
from . import _state_v1 as legacy
from ._validation import checked
from .embedded_json import parse_embedded_object


def _parse_marker(text: str) -> dict[str, Any]:
    matches = MARKER_RE.findall(text)
    if len(matches) != 1:
        raise ValueError(f"expected exactly one state marker, found {len(matches)}")
    payload = parse_embedded_object(matches[0], "state marker")
    schema_version = payload.get("schema_version")
    expected_version = load_json(WORKFLOW_PATH).get("schema_version")
    if type(schema_version) is not int or schema_version != expected_version:
        raise ValueError("unsupported state marker schema_version")
    legacy.validate_marker_semantics(payload)
    return payload


def parse_marker(text: str) -> dict[str, Any]:
    return checked(_parse_marker, text)


def advance(
    command: str,
    transition: str,
    current: dict[str, Any],
    replacement: dict[str, Any],
    mode: str | None = None,
) -> dict[str, Any]:
    return checked(
        legacy.validate_state_advance,
        command,
        transition,
        current,
        replacement,
        mode,
    )


def transition(
    name: str, current: str, resume_stage: str | None = None, mode: str | None = None
) -> str:
    return checked(legacy.validate_transition, name, current, resume_stage, mode)


def issue_transition(command: str, source: str, target: str) -> dict[str, Any]:
    return checked(legacy.validate_issue_transition, command, source, target)


def payload_hash(payload: Any) -> str:
    return sha256_digest(payload)


def idempotency_key(
    project_id: str,
    entity_id: str,
    command: str,
    revision: int,
    operation_id: str | None = None,
    payload_digest: str | None = None,
) -> str:
    return checked(
        legacy.idempotency_key,
        project_id,
        entity_id,
        command,
        revision,
        operation_id,
        payload_digest,
    )
