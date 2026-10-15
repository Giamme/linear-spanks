"""Versioned v1 state and marker semantics owned by the state domain."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

from ..contracts.legacy import (
    command_by_name,
    command_transitions,
    execution_contract,
    issue_workflow_contract,
    load_json,
    parse_rfc3339,
)
from ..core.legacy_constants import MARKER_RE, WORKFLOW_PATH


def validate_transition(
    name: str,
    current: str,
    resume_stage: str | None,
    mode: str | None = None,
) -> str:
    contract = load_json(WORKFLOW_PATH)
    transition = contract.get("transitions", {}).get(name)
    if not isinstance(transition, dict):
        raise ValueError(f"unknown transition: {name}")
    mode_self_transition = transition.get("mode_self_transition")
    if (
        isinstance(mode_self_transition, dict)
        and current == mode_self_transition.get("from")
        and mode in mode_self_transition.get("modes", [])
    ):
        mode_target = mode_self_transition.get("to")
        if not isinstance(mode_target, str):
            raise ValueError(f"transition {name} mode self-transition has no target")
        return mode_target
    allowed = transition.get("from", [])
    if current not in allowed:
        raise ValueError(
            f"transition {name} does not allow stage {current}; expected one of {allowed}"
        )
    target = transition.get("to")
    if target == "$resume_stage":
        if not resume_stage or resume_stage in {"paused", "archived", "wrapped"}:
            raise ValueError("resume requires a non-terminal --resume-stage")
        stages = contract.get("stages", [])
        if resume_stage not in stages:
            raise ValueError(f"unknown resume stage: {resume_stage}")
        pause_sources = set(contract.get("transitions", {}).get("pause", {}).get("from", []))
        if resume_stage not in pause_sources:
            raise ValueError("resume stage must be a valid stored pause destination")
        return resume_stage
    if not isinstance(target, str):
        raise ValueError(f"transition {name} has no target")
    return target


def validate_issue_transition(
    command_name: str, from_status: str, to_status: str
) -> dict[str, Any]:
    command = command_by_name(command_name)
    transition_name = command.get("issue_transition")
    if not isinstance(transition_name, str):
        raise ValueError(f"command {command_name} does not declare an issue transition")
    contract = issue_workflow_contract()
    transition = contract["transitions"].get(transition_name)
    if not isinstance(transition, dict) or command_name not in transition["commands"]:
        raise ValueError(
            f"command {command_name} is not allowed for issue transition {transition_name}"
        )
    if from_status not in transition["from"]:
        raise ValueError(
            f"issue transition {transition_name} does not allow status {from_status}; "
            f"expected one of {transition['from']}"
        )
    if to_status != transition["to"]:
        raise ValueError(
            f"issue transition {transition_name} must target status {transition['to']}"
        )
    return {
        "issue_contract_version": contract["schema_version"],
        "command": command_name,
        "transition": transition_name,
        "from_status": from_status,
        "to_status": to_status,
        "requires": transition["requires"],
        "status": "valid",
    }


def marker_payload(args: argparse.Namespace) -> dict[str, Any]:
    contract = load_json(WORKFLOW_PATH)
    stages = contract.get("stages", [])
    if args.stage not in stages:
        raise ValueError(f"unknown stage: {args.stage}")
    if args.revision < 0:
        raise ValueError("revision must be non-negative")
    command = command_by_name(args.last_command)
    validate_resume_state(args.stage, args.resume_stage, stages)
    payload = {
        "schema_version": contract["schema_version"],
        "project_id": args.project_id,
        "milestone_id": args.milestone_id,
        "stage": args.stage,
        "resume_stage": args.resume_stage,
        "revision": args.revision,
        "last_command": args.last_command,
        "run_id": args.run_id,
        "updated_at": args.updated_at or datetime.now(UTC).isoformat(),
    }
    validate_marker_semantics(payload, command)
    return payload


def canonical_digest(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def validate_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
        raise ValueError(f"{field} must be a lowercase sha256 digest")
    return value


def _validate_hash_map(value: Any, field: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    result: dict[str, str] = {}
    for key, digest in value.items():
        if not isinstance(key, str) or not key:
            raise ValueError(f"{field} keys must be non-empty text")
        result[key] = validate_sha256(digest, f"{field}.{key}")
    return result


def parse_marker(text: str) -> dict[str, Any]:
    matches = MARKER_RE.findall(text)
    if len(matches) != 1:
        raise ValueError(f"expected exactly one state marker, found {len(matches)}")
    payload = json.loads(matches[0])
    if not isinstance(payload, dict):
        raise ValueError("state marker payload must be an object")
    contract = load_json(WORKFLOW_PATH)
    if payload.get("schema_version") != contract.get("schema_version"):
        raise ValueError("unsupported state marker schema_version")
    if payload.get("stage") not in contract.get("stages", []):
        raise ValueError(f"unknown marker stage: {payload.get('stage')}")
    required_text = ("project_id", "milestone_id", "last_command", "run_id", "updated_at")
    for field in required_text:
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            raise ValueError(f"marker field {field} must be non-empty text")
    if (
        not isinstance(payload.get("revision"), int)
        or isinstance(payload.get("revision"), bool)
        or payload["revision"] < 0
    ):
        raise ValueError("marker revision must be a non-negative integer")
    validate_marker_semantics(payload)
    return payload


def validate_marker_semantics(
    payload: dict[str, Any], command: dict[str, Any] | None = None
) -> None:
    contract = load_json(WORKFLOW_PATH)
    stages = contract["stages"]
    for field in ("project_id", "milestone_id", "last_command", "run_id", "updated_at"):
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            raise ValueError(f"marker field {field} must be non-empty text")
    if (
        not isinstance(payload.get("revision"), int)
        or isinstance(payload.get("revision"), bool)
        or payload["revision"] < 0
    ):
        raise ValueError("marker revision must be a non-negative integer")
    stage = payload.get("stage")
    if not isinstance(stage, str) or stage not in stages:
        raise ValueError(f"unknown marker stage: {stage}")
    parse_rfc3339(payload["updated_at"])
    selected_command = command or command_by_name(payload["last_command"])
    transitions = command_transitions(selected_command)
    if stage != "draft" and not transitions:
        raise ValueError(f"last_command {selected_command['name']} could not produce stage {stage}")
    possible_stages = {
        transition["to"]
        for name in transitions
        if isinstance((transition := contract["transitions"].get(name)), dict)
        and isinstance(transition.get("to"), str)
        and not transition["to"].startswith("$")
    }
    possible_stages.update(
        transition["mode_self_transition"]["to"]
        for name in transitions
        if isinstance((transition := contract["transitions"].get(name)), dict)
        and isinstance(transition.get("mode_self_transition"), dict)
        and isinstance(transition["mode_self_transition"].get("to"), str)
    )
    if stage not in {"draft", "paused"} and stage not in possible_stages:
        raise ValueError(f"last_command {selected_command['name']} could not produce stage {stage}")
    if stage == "paused" and "pause" not in transitions:
        raise ValueError(f"last_command {selected_command['name']} could not produce stage paused")
    resume_stage = payload.get("resume_stage")
    if resume_stage is not None and not isinstance(resume_stage, str):
        raise ValueError("resume_stage must be text or null")
    validate_resume_state(stage, resume_stage, stages)


def validate_state_advance(
    command_name: str,
    transition_name: str,
    current: dict[str, Any],
    replacement: dict[str, Any],
    mode: str | None = None,
) -> dict[str, Any]:
    command = command_by_name(command_name)
    if transition_name not in command_transitions(command):
        raise ValueError(
            f"command {command_name} is not declared to perform transition {transition_name}"
        )
    validate_marker_semantics(current)
    validate_marker_semantics(replacement, command)
    target = validate_transition(
        transition_name, current["stage"], current.get("resume_stage"), mode
    )
    if replacement["stage"] != target:
        raise ValueError(f"replacement marker stage must be {target}")
    for field in ("project_id", "milestone_id"):
        if replacement[field] != current[field]:
            raise ValueError(f"replacement marker {field} must match the current marker")
    if replacement["revision"] != current["revision"] + 1:
        raise ValueError("replacement marker revision must increment by exactly one")
    if parse_rfc3339(replacement["updated_at"]) < parse_rfc3339(current["updated_at"]):
        raise ValueError("replacement marker updated_at must not move backwards")
    if replacement["last_command"] != command_name:
        raise ValueError("replacement marker last_command must match --command")
    return {
        "command": command_name,
        "transition": transition_name,
        "from": current["stage"],
        "to": target,
        "revision": replacement["revision"],
        "status": "valid",
    }


def validate_resume_state(stage: str, resume_stage: str | None, stages: list[str]) -> None:
    if stage == "paused":
        if resume_stage not in stages or resume_stage in {"paused", "wrapped", "archived"}:
            raise ValueError("paused state requires a valid non-terminal resume_stage")
    elif resume_stage is not None:
        raise ValueError("resume_stage must be null unless stage is paused")


def idempotency_key(
    project_id: str,
    entity_id: str,
    command: str,
    revision: int,
    operation_id: str | None = None,
    payload_hash: str | None = None,
) -> str:
    command_by_name(command)
    if revision < 0:
        raise ValueError("revision must be non-negative")
    if (operation_id is None) != (payload_hash is None):
        raise ValueError("operation-id and payload-hash must be supplied together")
    configuration = execution_contract()["commands"][command]
    if configuration.get("bulk") and operation_id is None:
        raise ValueError("bulk command requires an operation-id and payload-hash")
    if operation_id is not None:
        assert payload_hash is not None
        if not operation_id.strip() or not payload_hash.strip():
            raise ValueError("operation-id and payload-hash must be non-empty")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", payload_hash):
            raise ValueError("payload-hash must be a canonical sha256:<64 lowercase hex> value")
    version = "v2" if operation_id is not None else "v1"
    values = [version, project_id, entity_id, command, str(revision)]
    if operation_id is not None and payload_hash is not None:
        values.extend((operation_id, payload_hash))
    raw = "\0".join(values).encode()
    return "lsp-" + hashlib.sha256(raw).hexdigest()[:20]


def normalized_payload_hash(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def require_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        raise ValueError(f"{field} must be a canonical sha256 value")
    return value


def require_unique_text_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{field} must be a text list")
    if len(value) != len(set(value)):
        raise ValueError(f"{field} must not contain duplicates")
    return value
