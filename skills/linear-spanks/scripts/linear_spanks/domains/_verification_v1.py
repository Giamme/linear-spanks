"""Versioned human-verification policies, markers, gates, and actions."""

from __future__ import annotations

import json
from typing import Any

from ..contracts.legacy import human_verification_contract, load_json, parse_rfc3339
from ..core.legacy_constants import (
    HUMAN_CHECKLIST_MARKER_RE,
    HUMAN_GATE_MARKER_RE,
    HUMAN_OVERRIDE_MARKER_RE,
    HUMAN_POLICY_MARKER_RE,
    HUMAN_REPAIR_MARKER_RE,
    WORKFLOW_PATH,
)
from ..core.legacy_validation import (
    _require_exact_object_fields,
    _require_nonempty_text,
    _require_positive_revision,
)
from ._state_v1 import canonical_digest, validate_sha256


def _validate_actor_timestamp(payload: dict[str, Any]) -> None:
    _require_nonempty_text(payload["actor"], "actor")
    parse_rfc3339(payload["updated_at"])


def validate_human_project_policy(payload: dict[str, Any]) -> dict[str, Any]:
    contract = human_verification_contract()
    schema = contract["project_policy"]
    policy = _require_exact_object_fields(
        payload, schema["required_fields"], "human verification project policy"
    )
    if policy["schema_version"] != contract["schema_version"]:
        raise ValueError("HUMAN_VERIFICATION_POLICY_MALFORMED: schema_version")
    _require_nonempty_text(policy["project_id"], "project_id")
    if policy["default"] not in schema["values"]:
        raise ValueError("HUMAN_VERIFICATION_POLICY_MALFORMED: default")
    _require_positive_revision(policy["revision"], "revision")
    _validate_actor_timestamp(policy)
    validate_sha256(policy["policy_hash"], "policy_hash")
    expected_hash = canonical_digest(
        {key: value for key, value in policy.items() if key != "policy_hash"}
    )
    if policy["policy_hash"] != expected_hash:
        raise ValueError("HUMAN_VERIFICATION_POLICY_DRIFT: project policy hash")
    return policy


def validate_human_milestone_override(payload: dict[str, Any]) -> dict[str, Any]:
    contract = human_verification_contract()
    schema = contract["milestone_override"]
    override = _require_exact_object_fields(
        payload, schema["required_fields"], "human verification milestone override"
    )
    if override["schema_version"] != contract["schema_version"]:
        raise ValueError("HUMAN_VERIFICATION_POLICY_MALFORMED: schema_version")
    for field in ("project_id", "milestone_id"):
        _require_nonempty_text(override[field], field)
    if override["override"] not in schema["values"]:
        raise ValueError("HUMAN_VERIFICATION_POLICY_MALFORMED: override")
    _require_positive_revision(override["revision"], "revision")
    _validate_actor_timestamp(override)
    validate_sha256(override["marker_hash"], "marker_hash")
    expected_hash = canonical_digest(
        {key: value for key, value in override.items() if key != "marker_hash"}
    )
    if override["marker_hash"] != expected_hash:
        raise ValueError("HUMAN_VERIFICATION_POLICY_DRIFT: milestone override hash")
    return override


def check_human_policy_document(payload: dict[str, Any]) -> dict[str, Any]:
    source = _require_exact_object_fields(
        payload,
        ["project_id", "document_capability", "for_mutation", "documents"],
        "human verification policy document lookup",
    )
    project_id = _require_nonempty_text(source["project_id"], "project_id")
    for field in ("document_capability", "for_mutation"):
        if not isinstance(source[field], bool):
            raise ValueError(f"{field} must be boolean")
    if source["for_mutation"] and not source["document_capability"]:
        raise ValueError("HUMAN_VERIFICATION_POLICY_UNAVAILABLE")
    if not isinstance(source["documents"], list):
        raise ValueError("human verification documents must be a list")
    title = human_verification_contract()["project_policy"]["document_title"]
    matches = [
        document
        for document in source["documents"]
        if isinstance(document, dict) and document.get("title") == title
    ]
    if len(matches) > 1:
        raise ValueError("HUMAN_VERIFICATION_POLICY_COLLISION")
    if not matches:
        return {
            "status": "missing",
            "project_id": project_id,
            "effective_default": "disabled",
            "source": "system-default",
            "policy": None,
        }
    document = _require_exact_object_fields(
        matches[0], ["id", "title", "body"], "human verification policy document"
    )
    _require_nonempty_text(document["id"], "document id")
    policy = parse_human_verification_marker("project-policy", document["body"])
    if policy["project_id"] != project_id:
        raise ValueError("HUMAN_VERIFICATION_POLICY_DRIFT: project binding")
    return {
        "status": "found",
        "project_id": project_id,
        "effective_default": policy["default"],
        "source": "project-default",
        "document_id": document["id"],
        "policy": policy,
    }


def resolve_human_verification_policy(payload: dict[str, Any]) -> dict[str, Any]:
    source = _require_exact_object_fields(
        payload,
        ["project_id", "milestone_id", "project_policy", "milestone_override"],
        "human verification policy resolution",
    )
    project_id = _require_nonempty_text(source["project_id"], "project_id")
    milestone_id = _require_nonempty_text(source["milestone_id"], "milestone_id")
    project_policy = (
        None
        if source["project_policy"] is None
        else validate_human_project_policy(source["project_policy"])
    )
    override = (
        None
        if source["milestone_override"] is None
        else validate_human_milestone_override(source["milestone_override"])
    )
    if project_policy is not None and project_policy["project_id"] != project_id:
        raise ValueError("HUMAN_VERIFICATION_POLICY_DRIFT: project policy binding")
    if override is not None and (
        override["project_id"] != project_id or override["milestone_id"] != milestone_id
    ):
        raise ValueError("HUMAN_VERIFICATION_POLICY_DRIFT: milestone override binding")
    if override is not None and override["override"] != "inherit":
        effective = override["override"]
        policy_source = "milestone-override"
    elif project_policy is not None:
        effective = project_policy["default"]
        policy_source = "project-default"
    else:
        effective = "disabled"
        policy_source = "system-default"
    result = {
        "schema_version": human_verification_contract()["schema_version"],
        "project_id": project_id,
        "milestone_id": milestone_id,
        "effective": effective,
        "source": policy_source,
        "project_policy_revision": project_policy["revision"] if project_policy else 0,
        "milestone_override_revision": override["revision"] if override else 0,
    }
    result["policy_hash"] = canonical_digest(result)
    return result


def validate_effective_human_policy(payload: dict[str, Any]) -> dict[str, Any]:
    schema = human_verification_contract()["effective_policy"]
    effective = _require_exact_object_fields(
        payload, schema["required_fields"], "effective human verification policy"
    )
    if effective["schema_version"] != human_verification_contract()["schema_version"]:
        raise ValueError("effective human verification schema_version is invalid")
    for field in ("project_id", "milestone_id"):
        _require_nonempty_text(effective[field], field)
    if effective["effective"] not in {"enabled", "disabled"}:
        raise ValueError("effective human verification value is invalid")
    if effective["source"] not in schema["sources"]:
        raise ValueError("effective human verification source is invalid")
    for field in ("project_policy_revision", "milestone_override_revision"):
        value = effective[field]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"{field} must be a non-negative integer")
    validate_sha256(effective["policy_hash"], "policy_hash")
    expected_hash = canonical_digest(
        {key: value for key, value in effective.items() if key != "policy_hash"}
    )
    if effective["policy_hash"] != expected_hash:
        raise ValueError("HUMAN_VERIFICATION_POLICY_DRIFT: effective policy hash")
    if effective["source"] == "system-default" and (
        effective["effective"] != "disabled" or effective["project_policy_revision"] != 0
    ):
        raise ValueError("system default human verification binding is invalid")
    if effective["source"] == "project-default" and effective["project_policy_revision"] == 0:
        raise ValueError("project default human verification binding requires a revision")
    if (
        effective["source"] == "milestone-override"
        and effective["milestone_override_revision"] == 0
    ):
        raise ValueError("milestone override human verification binding requires a revision")
    return effective


def validate_human_verification_preview(payload: dict[str, Any]) -> dict[str, Any]:
    contract = human_verification_contract()
    schema = contract["preview"]
    preview = _require_exact_object_fields(
        payload, schema["required_fields"], "human verification preview"
    )
    if preview["schema_version"] != contract["schema_version"]:
        raise ValueError("human verification preview schema_version is invalid")
    if preview["scope"] not in schema["scopes"]:
        raise ValueError("human verification preview scope is invalid")
    _require_nonempty_text(preview["project_id"], "project_id")
    if preview["scope"] == "project":
        if preview["milestone_id"] is not None:
            raise ValueError("project policy preview cannot bind one milestone")
        if preview["requested_value"] not in contract["project_policy"]["values"]:
            raise ValueError("project policy preview value is invalid")
    else:
        _require_nonempty_text(preview["milestone_id"], "milestone_id")
        if preview["requested_value"] not in contract["milestone_override"]["values"]:
            raise ValueError("milestone override preview value is invalid")
    if not isinstance(preview["reason"], str):
        raise ValueError("human verification preview reason must be text")
    active_ids = preview["active_milestone_ids"]
    if (
        not isinstance(active_ids, list)
        or not all(isinstance(value, str) and value for value in active_ids)
        or active_ids != sorted(set(active_ids))
    ):
        raise ValueError("active_milestone_ids must be sorted unique text")
    affected = preview["affected_milestones"]
    if not isinstance(affected, list):
        raise ValueError("affected_milestones must be a list")
    rows: list[dict[str, Any]] = []
    for index, raw in enumerate(affected):
        row = _require_exact_object_fields(
            raw, schema["affected_milestone_fields"], f"affected_milestones[{index}]"
        )
        milestone_id = _require_nonempty_text(row["milestone_id"], "milestone_id")
        if row["stage"] not in load_json(WORKFLOW_PATH)["stages"]:
            raise ValueError(f"affected milestone {milestone_id} has an invalid stage")
        if row["stage"] in schema["terminal_stages"]:
            raise ValueError(f"terminal milestone {milestone_id} must remain unchanged")
        for field in ("before_effective", "after_effective"):
            if row[field] not in {"enabled", "disabled"}:
                raise ValueError(f"{field} is invalid for {milestone_id}")
        if row["gate_issue_id"] is not None:
            _require_nonempty_text(row["gate_issue_id"], "gate_issue_id")
        if row["checklist_id"] is not None:
            _require_nonempty_text(row["checklist_id"], "checklist_id")
        if row["gate_action"] not in schema["gate_actions"]:
            raise ValueError(f"gate_action is invalid for {milestone_id}")
        if row["checklist_action"] not in schema["checklist_actions"]:
            raise ValueError(f"checklist_action is invalid for {milestone_id}")
        receipts = row["orchestration_receipt_ids"]
        if (
            not isinstance(receipts, list)
            or not all(isinstance(value, str) and value for value in receipts)
            or receipts != sorted(set(receipts))
        ):
            raise ValueError(f"orchestration receipts are invalid for {milestone_id}")
        if row["receipt_action"] not in schema["receipt_actions"]:
            raise ValueError(f"receipt_action is invalid for {milestone_id}")
        changed = row["before_effective"] != row["after_effective"]
        if not changed and any(
            (
                row["gate_action"] != "none",
                row["checklist_action"] != "none",
                row["receipt_action"] != "none",
            )
        ):
            raise ValueError(f"idempotent milestone {milestone_id} cannot contain operations")
        if changed and row["after_effective"] == "enabled":
            expected_gate = "reactivate" if row["gate_issue_id"] else "create"
            if row["gate_action"] != expected_gate:
                raise ValueError(f"enabling {milestone_id} requires gate {expected_gate}")
            if row["stage"] == "milestone-verified":
                expected_checklist = "supersede" if row["checklist_id"] else "none"
                if row["checklist_action"] != expected_checklist:
                    raise ValueError(f"enabling {milestone_id} requires machine re-verification")
            elif row["checklist_action"] != "none":
                raise ValueError(
                    f"enabling {milestone_id} cannot change a checklist before verification"
                )
        if changed and row["after_effective"] == "disabled":
            expected_gate = "cancel" if row["gate_issue_id"] else "none"
            if row["gate_action"] != expected_gate:
                raise ValueError(f"disabling {milestone_id} requires gate {expected_gate}")
            if row["checklist_id"] and row["stage"] in schema["pending_stages"]:
                if not preview["reason"].strip():
                    raise ValueError("HUMAN_VERIFICATION_BYPASS_REASON_REQUIRED")
                if row["checklist_action"] != "bypass":
                    raise ValueError(f"disabling {milestone_id} requires a bypass reply")
            elif row["checklist_action"] != "none":
                raise ValueError(f"disabling {milestone_id} has no pending checklist to change")
        if receipts and changed and row["receipt_action"] != "reconcile":
            raise ValueError(f"policy change for {milestone_id} requires receipt reconciliation")
        if not receipts and row["receipt_action"] != "none":
            raise ValueError(f"policy change for {milestone_id} has no receipt to reconcile")
        rows.append(row)
    if [row["milestone_id"] for row in rows] != active_ids:
        raise ValueError("preview must enumerate every affected active milestone exactly once")
    if preview["scope"] == "milestone" and active_ids != [preview["milestone_id"]]:
        raise ValueError("milestone override preview must cover exactly its milestone")
    validate_sha256(preview["preview_hash"], "preview_hash")
    expected_hash = canonical_digest(
        {
            key: value
            for key, value in preview.items()
            if key not in {"preview_hash", "approved_hash"}
        }
    )
    if preview["preview_hash"] != expected_hash:
        raise ValueError("HUMAN_VERIFICATION_POLICY_DRIFT: preview hash")
    if preview["approved_hash"] != preview["preview_hash"]:
        raise ValueError("HUMAN_VERIFICATION_PREVIEW_REQUIRED")
    return preview


def validate_human_gate(payload: dict[str, Any]) -> dict[str, Any]:
    contract = human_verification_contract()
    schema = contract["gate_issue"]
    gate = _require_exact_object_fields(
        payload, schema["required_fields"], "human verification gate"
    )
    if gate["schema_version"] != contract["schema_version"]:
        raise ValueError("human verification gate schema_version is invalid")
    for field in ("project_id", "milestone_id", "issue_id"):
        _require_nonempty_text(gate[field], field)
    _require_positive_revision(gate["gate_revision"], "gate_revision")
    validate_sha256(gate["effective_policy_hash"], "effective_policy_hash")
    if gate["state"] not in schema["states"]:
        raise ValueError("human verification gate state is invalid")
    parse_rfc3339(gate["updated_at"])
    return gate


def validate_human_checklist(payload: dict[str, Any]) -> dict[str, Any]:
    contract = human_verification_contract()
    schema = contract["checklist"]
    checklist = _require_exact_object_fields(
        payload, schema["required_fields"], "human verification checklist"
    )
    if checklist["schema_version"] != contract["schema_version"]:
        raise ValueError("human verification checklist schema_version is invalid")
    for field in ("checklist_id", "project_id", "milestone_id", "gate_issue_id"):
        _require_nonempty_text(checklist[field], field)
    for field in ("checklist_revision", "machine_verification_revision"):
        _require_positive_revision(checklist[field], field)
    validate_sha256(checklist["effective_policy_hash"], "effective_policy_hash")
    if checklist["status"] not in schema["statuses"]:
        raise ValueError("human verification checklist status is invalid")
    for field in ("instructions", "evidence"):
        values = checklist[field]
        if not isinstance(values, list) or not all(
            isinstance(value, str) and value.strip() for value in values
        ):
            raise ValueError(f"human verification checklist {field} must be non-empty text")
        if field == "instructions" and not values:
            raise ValueError("human verification checklist requires instructions")
    _validate_actor_timestamp(checklist)
    return checklist


def validate_human_repair_task(payload: dict[str, Any]) -> dict[str, Any]:
    contract = human_verification_contract()
    schema = contract["repair_task"]
    repair = _require_exact_object_fields(
        payload, schema["required_fields"], "human verification repair task"
    )
    if repair["schema_version"] != contract["schema_version"]:
        raise ValueError("human verification repair schema_version is invalid")
    for field in ("project_id", "milestone_id", "gate_issue_id", "checklist_id", "reason"):
        _require_nonempty_text(repair[field], field)
    _require_positive_revision(repair["failure_revision"], "failure_revision")
    if repair["status"] != schema["initial_status"]:
        raise ValueError("human verification repair task must start in Unplanned")
    return repair


def parse_human_verification_marker(kind: str, text: str) -> dict[str, Any]:
    definitions = {
        "project-policy": (HUMAN_POLICY_MARKER_RE, validate_human_project_policy),
        "milestone-override": (HUMAN_OVERRIDE_MARKER_RE, validate_human_milestone_override),
        "gate": (HUMAN_GATE_MARKER_RE, validate_human_gate),
        "checklist": (HUMAN_CHECKLIST_MARKER_RE, validate_human_checklist),
        "repair": (HUMAN_REPAIR_MARKER_RE, validate_human_repair_task),
    }
    if kind not in definitions:
        raise ValueError(f"unknown human verification marker kind: {kind}")
    pattern, validator = definitions[kind]
    matches = pattern.findall(text)
    if len(matches) != 1:
        raise ValueError(
            f"HUMAN_VERIFICATION_POLICY_MALFORMED: expected exactly one {kind} marker, "
            f"found {len(matches)}"
        )
    return validator(json.loads(matches[0]))


def filter_human_verification_gates(payload: dict[str, Any]) -> dict[str, Any]:
    source = _require_exact_object_fields(payload, ["issues"], "human verification gate filter")
    if not isinstance(source["issues"], list):
        raise ValueError("human verification gate filter requires issues")
    regular: list[dict[str, Any]] = []
    excluded: list[str] = []
    seen_gate_milestones: set[str] = set()
    for index, issue in enumerate(source["issues"]):
        if not isinstance(issue, dict):
            raise ValueError(f"issues[{index}] must be an object")
        issue_id = _require_nonempty_text(issue.get("id"), f"issues[{index}].id")
        description = issue.get("description")
        if not isinstance(description, str):
            raise ValueError(f"issues[{index}].description must be text")
        matches = HUMAN_GATE_MARKER_RE.findall(description)
        if not matches:
            regular.append(issue)
            continue
        if len(matches) != 1:
            raise ValueError(f"multiple human verification gate markers on {issue_id}")
        gate = validate_human_gate(json.loads(matches[0]))
        if gate["issue_id"] != issue_id:
            raise ValueError("HUMAN_VERIFICATION_GATE_DRIFT: issue binding")
        if gate["milestone_id"] in seen_gate_milestones:
            raise ValueError(
                f"HUMAN_VERIFICATION_GATE_DRIFT: multiple gates for {gate['milestone_id']}"
            )
        seen_gate_milestones.add(gate["milestone_id"])
        excluded.append(issue_id)
    return {
        "issues": regular,
        "excluded_gate_issue_ids": sorted(excluded),
        "regular_task_total": len(regular),
    }


def validate_human_verification_action(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("human verification action must be an object")
    operation = payload.get("operation")
    common = {"operation", "effective_policy", "milestone_stage"}
    fields = {
        "verify": common | {"machine_verification_revision", "gate", "checklist"},
        "confirm": common
        | {
            "checklist",
            "gate",
            "human_confirmed",
            "gate_state_read_back",
            "checklist_status_read_back",
            "linear_milestone_completed",
        },
        "fail": common
        | {
            "checklist",
            "gate",
            "reason",
            "repair_task",
            "existing_repair_tasks",
            "preview_hash",
            "approved_hash",
            "checklist_status_read_back",
            "gate_state_read_back",
        },
        "bypass": common
        | {
            "previous_effective_policy",
            "checklist",
            "gate",
            "reason",
            "preview_hash",
            "approved_hash",
            "gate_state_read_back",
            "checklist_status_read_back",
            "human_confirmation_recorded",
        },
        "wrap": common | {"gate", "checklist"},
    }
    if operation not in fields or set(payload) != fields[operation]:
        raise ValueError(f"human verification {operation} action fields are incomplete")
    effective = validate_effective_human_policy(payload["effective_policy"])
    artifact_effective = effective
    if operation == "bypass":
        artifact_effective = validate_effective_human_policy(payload["previous_effective_policy"])
        if (
            artifact_effective["project_id"] != effective["project_id"]
            or artifact_effective["milestone_id"] != effective["milestone_id"]
            or artifact_effective["effective"] != "enabled"
            or effective["effective"] != "disabled"
        ):
            raise ValueError("HUMAN_VERIFICATION_POLICY_DRIFT: bypass policy transition")
    stage = payload["milestone_stage"]
    if stage not in load_json(WORKFLOW_PATH)["stages"]:
        raise ValueError("human verification action milestone stage is invalid")
    gate = None if payload.get("gate") is None else validate_human_gate(payload["gate"])
    checklist = (
        None if payload.get("checklist") is None else validate_human_checklist(payload["checklist"])
    )
    for artifact in (gate, checklist):
        if artifact is not None and (
            artifact["project_id"] != effective["project_id"]
            or artifact["milestone_id"] != effective["milestone_id"]
        ):
            raise ValueError("HUMAN_VERIFICATION_POLICY_DRIFT: artifact binding")
    if gate is not None and gate["effective_policy_hash"] != artifact_effective["policy_hash"]:
        raise ValueError("HUMAN_VERIFICATION_POLICY_DRIFT: gate policy")
    if (
        checklist is not None
        and checklist["effective_policy_hash"] != artifact_effective["policy_hash"]
    ):
        raise ValueError("HUMAN_VERIFICATION_CHECKLIST_STALE: policy")

    if operation == "verify":
        revision = _require_positive_revision(
            payload["machine_verification_revision"], "machine_verification_revision"
        )
        if stage not in {"implementing", "milestone-verified"}:
            raise ValueError("verify human verification action requires implementing state")
        if effective["effective"] == "disabled":
            if gate is not None or checklist is not None:
                raise ValueError("disabled verification cannot create a gate or checklist")
            return {"status": "milestone-verified", "next_command": "wrap-milestone"}
        if gate is None or gate["state"] != "In Progress":
            raise ValueError("enabled verification requires an In Progress gate")
        if (
            checklist is None
            or checklist["status"] != "pending"
            or checklist["machine_verification_revision"] != revision
            or checklist["gate_issue_id"] != gate["issue_id"]
        ):
            raise ValueError("HUMAN_VERIFICATION_CHECKLIST_STALE")
        return {
            "status": "milestone-verified",
            "next_command": "confirm-milestone",
            "stop": "await-human-verification",
        }
    if effective["effective"] != "enabled" and operation not in {"bypass", "wrap"}:
        raise ValueError(f"{operation} requires enabled human verification")
    if operation in {"confirm", "fail", "bypass"}:
        if stage != "milestone-verified":
            raise ValueError(f"{operation} requires milestone-verified state")
        if checklist is None or checklist["status"] != "pending":
            raise ValueError("HUMAN_VERIFICATION_CHECKLIST_STALE")
        if gate is None or gate["state"] not in {"Todo", "In Progress"}:
            raise ValueError("HUMAN_VERIFICATION_GATE_DRIFT")
    if operation == "confirm":
        if payload["human_confirmed"] is not True:
            raise ValueError("HUMAN_VERIFICATION_CONFIRMATION_INCOMPLETE")
        if payload["checklist_status_read_back"] != "confirmed":
            raise ValueError("HUMAN_VERIFICATION_CONFIRMATION_INCOMPLETE: checklist read-back")
        if payload["gate_state_read_back"] != "Done":
            raise ValueError("HUMAN_VERIFICATION_CONFIRMATION_INCOMPLETE: gate read-back")
        if payload["linear_milestone_completed"] is not True:
            raise ValueError("HUMAN_VERIFICATION_CONFIRMATION_INCOMPLETE: Linear completion")
        return {"status": "human-verified", "next_command": "wrap-milestone"}
    if operation == "fail":
        assert checklist is not None and gate is not None
        _require_nonempty_text(payload["reason"], "reason")
        validate_sha256(payload["preview_hash"], "preview_hash")
        expected_preview = canonical_digest(
            {
                "operation": "fail",
                "project_id": effective["project_id"],
                "milestone_id": effective["milestone_id"],
                "checklist_id": checklist["checklist_id"],
                "gate_issue_id": gate["issue_id"],
                "reason": payload["reason"],
                "repair_task": payload["repair_task"],
            }
        )
        if payload["preview_hash"] != expected_preview:
            raise ValueError("HUMAN_VERIFICATION_POLICY_DRIFT: repair preview")
        if payload["approved_hash"] != payload["preview_hash"]:
            raise ValueError("HUMAN_VERIFICATION_PREVIEW_REQUIRED")
        repair = validate_human_repair_task(payload["repair_task"])
        if (
            repair["project_id"] != effective["project_id"]
            or repair["milestone_id"] != effective["milestone_id"]
            or repair["checklist_id"] != checklist["checklist_id"]
            or repair["gate_issue_id"] != gate["issue_id"]
            or repair["reason"] != payload["reason"]
        ):
            raise ValueError("HUMAN_VERIFICATION_POLICY_DRIFT: repair task binding")
        if payload["gate_state_read_back"] not in {"Todo", "In Progress"}:
            raise ValueError("failed human verification must keep the gate open")
        if payload["checklist_status_read_back"] != "failed":
            raise ValueError("failed human verification requires failure reply read-back")
        existing_raw = payload["existing_repair_tasks"]
        if not isinstance(existing_raw, list):
            raise ValueError("existing_repair_tasks must be a list")
        existing = [
            validate_human_repair_task(item)
            for item in existing_raw
            if (
                isinstance(item, dict)
                and item.get("failure_revision") == repair["failure_revision"]
                and item.get("milestone_id") == repair["milestone_id"]
            )
        ]
        if len(existing) > 1:
            raise ValueError("multiple repair tasks exist for one failure revision")
        if existing and existing[0] != repair:
            raise ValueError("HUMAN_VERIFICATION_POLICY_DRIFT: repair task revision")
        return {
            "status": "implementing",
            "next_command": "verify-milestone",
            "repair_task": repair,
            "repair_action": "reuse" if existing else "create",
        }
    if operation == "bypass":
        assert checklist is not None and gate is not None
        _require_nonempty_text(payload["reason"], "reason")
        validate_sha256(payload["preview_hash"], "preview_hash")
        expected_preview = canonical_digest(
            {
                "operation": "bypass",
                "project_id": effective["project_id"],
                "milestone_id": effective["milestone_id"],
                "checklist_id": checklist["checklist_id"],
                "gate_issue_id": gate["issue_id"],
                "reason": payload["reason"],
                "from_policy_hash": artifact_effective["policy_hash"],
                "to_policy_hash": effective["policy_hash"],
            }
        )
        if payload["preview_hash"] != expected_preview:
            raise ValueError("HUMAN_VERIFICATION_POLICY_DRIFT: bypass preview")
        if payload["approved_hash"] != payload["preview_hash"]:
            raise ValueError("HUMAN_VERIFICATION_PREVIEW_REQUIRED")
        if payload["gate_state_read_back"] != "Canceled":
            raise ValueError("bypassed human verification requires gate cancellation read-back")
        if payload["checklist_status_read_back"] != "bypassed":
            raise ValueError("bypassed human verification requires bypass reply read-back")
        if payload["human_confirmation_recorded"] is not False:
            raise ValueError("bypass must not record false human confirmation")
        return {"status": "milestone-verified", "next_command": "wrap-milestone"}
    if operation == "wrap":
        if effective["effective"] == "disabled":
            if stage not in {"milestone-verified", "wrapped"}:
                raise ValueError("disabled human verification wraps from milestone-verified")
        else:
            if stage not in {"human-verified", "wrapped"}:
                raise ValueError("enabled human verification requires human-verified")
            if gate is None or gate["state"] != "Done":
                raise ValueError("enabled wrap requires a completed gate")
            if checklist is None or checklist["status"] != "confirmed":
                raise ValueError("enabled wrap requires a confirmed checklist")
        return {"status": "wrapped", "next_command": None}
    raise AssertionError(operation)


def validate_orchestration_policy_binding(
    binding: dict[str, Any], effective: dict[str, Any]
) -> dict[str, Any]:
    schema = human_verification_contract()["orchestration_binding"]
    value = _require_exact_object_fields(
        binding, schema["required_fields"], "human verification orchestration binding"
    )
    current = validate_effective_human_policy(effective)
    comparable = {key: current[key] for key in schema["required_fields"]}
    if value != comparable:
        raise ValueError("HUMAN_VERIFICATION_POLICY_DRIFT: orchestration receipt")
    return value
