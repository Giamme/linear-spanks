"""Human-verification marker operations with strict v2 JSON boundaries."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from ..contracts.legacy import human_verification_contract
from ..core.jsonio import mutable_json_copy
from ..core.legacy_constants import (
    HUMAN_CHECKLIST_MARKER_RE,
    HUMAN_GATE_MARKER_RE,
    HUMAN_OVERRIDE_MARKER_RE,
    HUMAN_POLICY_MARKER_RE,
    HUMAN_REPAIR_MARKER_RE,
)
from . import _verification_v1 as legacy
from ._validation import checked
from .embedded_json import parse_embedded_object

MarkerValidator = Callable[[dict[str, Any]], dict[str, Any]]


def _definitions() -> dict[str, tuple[Any, MarkerValidator]]:
    return {
        "project-policy": (HUMAN_POLICY_MARKER_RE, legacy.validate_human_project_policy),
        "milestone-override": (
            HUMAN_OVERRIDE_MARKER_RE,
            legacy.validate_human_milestone_override,
        ),
        "gate": (HUMAN_GATE_MARKER_RE, legacy.validate_human_gate),
        "checklist": (HUMAN_CHECKLIST_MARKER_RE, legacy.validate_human_checklist),
        "repair": (HUMAN_REPAIR_MARKER_RE, legacy.validate_human_repair_task),
    }


def _parse_marker(kind: str, text: str) -> dict[str, Any]:
    definition = _definitions().get(kind)
    if definition is None:
        raise ValueError(f"unknown human verification marker kind: {kind}")
    pattern, validator = definition
    matches = pattern.findall(text)
    if len(matches) != 1:
        raise ValueError(
            f"HUMAN_VERIFICATION_POLICY_MALFORMED: expected exactly one {kind} marker, "
            f"found {len(matches)}"
        )
    payload = parse_embedded_object(matches[0], f"human verification {kind} marker")
    expected_version = human_verification_contract()["schema_version"]
    if (
        type(payload.get("schema_version")) is not int
        or payload["schema_version"] != expected_version
    ):
        raise ValueError("HUMAN_VERIFICATION_POLICY_MALFORMED: schema_version")
    return validator(payload)


def parse_marker(kind: str, text: str) -> dict[str, Any]:
    return checked(_parse_marker, kind, text)


def _check_policy_document(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized = mutable_json_copy(payload)
    documents = sanitized.get("documents")
    title = human_verification_contract()["project_policy"]["document_title"]
    matches = (
        [
            document
            for document in documents
            if isinstance(document, dict) and document.get("title") == title
        ]
        if isinstance(documents, list)
        else []
    )
    if len(matches) == 1 and isinstance(matches[0].get("body"), str):
        body = matches[0]["body"]
        policy = _parse_marker("project-policy", body)
        marker_match = next(iter(HUMAN_POLICY_MARKER_RE.finditer(body)))
        encoded = json.dumps(policy, sort_keys=True, separators=(",", ":"), allow_nan=False)
        matches[0]["body"] = body[: marker_match.start(1)] + encoded + body[marker_match.end(1) :]
    return legacy.check_human_policy_document(sanitized)


def check_policy_document(payload: dict[str, Any]) -> dict[str, Any]:
    return checked(_check_policy_document, payload)


def _filter_gates(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized = mutable_json_copy(payload)
    issues = sanitized.get("issues")
    if isinstance(issues, list):
        for issue in issues:
            if not isinstance(issue, dict) or not isinstance(issue.get("description"), str):
                continue
            description = issue["description"]
            matches = list(HUMAN_GATE_MARKER_RE.finditer(description))
            if len(matches) != 1:
                continue
            gate = _parse_marker("gate", description)
            encoded = json.dumps(gate, sort_keys=True, separators=(",", ":"), allow_nan=False)
            marker_match = matches[0]
            issue["description"] = (
                description[: marker_match.start(1)] + encoded + description[marker_match.end(1) :]
            )
    return legacy.filter_human_verification_gates(sanitized)


def filter_gates(payload: dict[str, Any]) -> dict[str, Any]:
    return checked(_filter_gates, payload)
