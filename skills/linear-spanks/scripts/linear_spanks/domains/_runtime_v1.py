"""Versioned milestone runtime projection and guarded-loop semantics."""

from __future__ import annotations

import json
import re
from typing import Any

from ..contracts.legacy import milestone_runtime_contract, parse_rfc3339
from ..core.legacy_constants import DEPENDENCY_GRAPH_MARKER_RE, MARKER_RE, MILESTONE_RUNTIME_REF_RE
from ..core.legacy_validation import (
    _require_exact_object_fields,
    _require_nonempty_text,
    _require_positive_revision,
)
from ._state_v1 import canonical_digest, validate_sha256


def validate_guarded_autopilot_binding(payload: dict[str, Any]) -> dict[str, Any]:
    contract = milestone_runtime_contract()
    policy = _require_exact_object_fields(
        payload,
        contract["autopilot"]["policy_required_fields"],
        "guarded autopilot policy binding",
    )
    if policy["schema_version"] != contract["schema_version"]:
        raise ValueError("guarded autopilot policy schema_version is unsupported")
    for field in ("policy_id", "milestone_id", "updated_at"):
        _require_nonempty_text(policy[field], field)
    _require_positive_revision(policy["revision"], "revision")
    parse_rfc3339(policy["updated_at"])
    if policy["persisted"] is not True or policy["read_back"] is not True:
        raise ValueError("guarded autopilot policy must be persisted and read back")
    binding = policy["binding"]
    if not isinstance(binding, dict) or set(binding) != set(contract["autopilot"]["expiry_fields"]):
        raise ValueError("guarded autopilot policy binding fields are incomplete")
    for field, digest in binding.items():
        validate_sha256(digest, f"guarded autopilot binding {field}")
    validate_sha256(policy["policy_hash"], "policy_hash")
    expected_hash = canonical_digest(
        {key: value for key, value in policy.items() if key != "policy_hash"}
    )
    if policy["policy_hash"] != expected_hash:
        raise ValueError("guarded autopilot policy hash drift")
    return policy


def validate_milestone_runtime(payload: dict[str, Any]) -> dict[str, Any]:
    contract = milestone_runtime_contract()
    runtime = _require_exact_object_fields(
        payload, contract["runtime_required_fields"], "milestone runtime"
    )
    if runtime["schema_version"] != contract["schema_version"]:
        raise ValueError("milestone runtime schema_version is unsupported")
    for field in (
        "runtime_id",
        "project_id",
        "milestone_id",
        "storage_source",
        "last_event",
        "updated_at",
    ):
        _require_nonempty_text(runtime[field], field)
    if runtime["storage_source"] not in contract["storage_sources"]:
        raise ValueError("milestone runtime storage_source is invalid")
    _require_positive_revision(runtime["revision"], "revision")
    validate_sha256(runtime["projection_hash"], "projection_hash")
    parse_rfc3339(runtime["updated_at"])
    if (
        not isinstance(runtime["event_count"], int)
        or isinstance(runtime["event_count"], bool)
        or runtime["event_count"] < 0
    ):
        raise ValueError("milestone runtime event_count must be non-negative")
    for field in (
        "active_wave",
        "plan_validity",
        "review_coverage",
        "human_repair",
    ):
        if not isinstance(runtime[field], dict):
            raise ValueError(f"milestone runtime {field} must be an object")
    validate_guarded_autopilot_binding(runtime["policy_binding"])
    expected_hash = canonical_digest(
        {key: value for key, value in runtime.items() if key != "projection_hash"}
    )
    if runtime["projection_hash"] != expected_hash:
        raise ValueError("MILESTONE_RUNTIME_STATE_CONFLICT: projection hash mismatch")
    return runtime


def validate_milestone_runtime_reference(payload: dict[str, Any]) -> dict[str, Any]:
    contract = milestone_runtime_contract()
    reference = _require_exact_object_fields(
        payload,
        contract["description_reference"]["required_fields"],
        "milestone runtime description reference",
    )
    if reference["schema_version"] != contract["schema_version"]:
        raise ValueError("milestone runtime reference schema_version is unsupported")
    for field in ("runtime_id", "milestone_id", "storage_source"):
        _require_nonempty_text(reference[field], field)
    _require_positive_revision(reference["revision"], "revision")
    if reference["storage_source"] not in contract["storage_sources"]:
        raise ValueError("milestone runtime reference storage_source is invalid")
    validate_sha256(reference["projection_hash"], "projection_hash")
    return reference


def upsert_milestone_runtime_reference(
    description: str,
    runtime: dict[str, Any],
) -> str:
    if not isinstance(description, str):
        raise ValueError("milestone description must be text")
    validated = validate_milestone_runtime(runtime)
    reference = validate_milestone_runtime_reference(
        {
            "schema_version": validated["schema_version"],
            "runtime_id": validated["runtime_id"],
            "milestone_id": validated["milestone_id"],
            "revision": validated["revision"],
            "storage_source": validated["storage_source"],
            "projection_hash": validated["projection_hash"],
        }
    )
    marker = (
        "<!-- linear-spanks:milestone-runtime-ref "
        + json.dumps(reference, sort_keys=True, separators=(",", ":"))
        + " -->"
    )
    matches = list(MILESTONE_RUNTIME_REF_RE.finditer(description))
    if len(matches) > 1:
        raise ValueError("MILESTONE_RUNTIME_STATE_CONFLICT: duplicate description references")
    if not matches:
        return description.rstrip() + "\n\n" + marker + "\n"
    return description[: matches[0].start()] + marker + description[matches[0].end() :]


def migrate_milestone_runtime_projection(payload: dict[str, Any]) -> dict[str, Any]:
    wrapper = _require_exact_object_fields(
        payload,
        [
            "milestone_id",
            "description",
            "documents_available",
            "documents",
            "comments",
        ],
        "milestone runtime migration input",
    )
    storage = reconcile_milestone_runtime_storage(
        {
            "milestone_id": wrapper["milestone_id"],
            "documents_available": wrapper["documents_available"],
            "documents": wrapper["documents"],
            "comments": wrapper["comments"],
        }
    )
    description = wrapper["description"]
    if not isinstance(description, str):
        raise ValueError("milestone description must be text")
    legacy = {
        "state_marker": bool(MARKER_RE.search(description)),
        "dependency_graph_marker": bool(DEPENDENCY_GRAPH_MARKER_RE.search(description)),
        "runtime_reference": bool(MILESTONE_RUNTIME_REF_RE.search(description)),
    }
    runtime = storage["runtime"]
    updated_description = (
        upsert_milestone_runtime_reference(description, runtime)
        if runtime is not None
        else description
    )
    return {
        **storage,
        "legacy_markers_detected": legacy,
        "description": updated_description,
        "description_preserved": (
            re.sub(MILESTONE_RUNTIME_REF_RE, "", description).strip()
            == re.sub(MILESTONE_RUNTIME_REF_RE, "", updated_description).strip()
        ),
    }


def reconcile_milestone_runtime_storage(payload: dict[str, Any]) -> dict[str, Any]:
    wrapper = _require_exact_object_fields(
        payload,
        ["milestone_id", "documents_available", "documents", "comments"],
        "milestone runtime storage input",
    )
    milestone_id = _require_nonempty_text(wrapper["milestone_id"], "milestone_id")
    if not isinstance(wrapper["documents_available"], bool):
        raise ValueError("documents_available must be boolean")
    for field in ("documents", "comments"):
        if not isinstance(wrapper[field], list):
            raise ValueError(f"{field} must be a list")
    documents = [validate_milestone_runtime(item) for item in wrapper["documents"]]
    comments = [validate_milestone_runtime(item) for item in wrapper["comments"]]
    artifacts = documents + comments
    if any(item["milestone_id"] != milestone_id for item in artifacts):
        raise ValueError("milestone runtime artifact milestone mismatch")
    if len(documents) > 1 or len(comments) > 1:
        raise ValueError("MILESTONE_RUNTIME_STATE_CONFLICT: duplicate runtime artifacts")
    if documents and comments:

        def logical_projection(runtime: dict[str, Any]) -> str:
            return canonical_digest(
                {
                    key: value
                    for key, value in runtime.items()
                    if key not in {"storage_source", "projection_hash"}
                }
            )

        if logical_projection(documents[0]) != logical_projection(comments[0]):
            raise ValueError("MILESTONE_RUNTIME_STATE_CONFLICT: document and comment differ")
        return {
            "action": "retire-matching-comment",
            "storage_source": "document",
            "runtime": documents[0],
        }
    if documents:
        return {"action": "use-document", "storage_source": "document", "runtime": documents[0]}
    if comments and wrapper["documents_available"]:
        return {
            "action": "promote-comment-to-document",
            "storage_source": "managed-comment",
            "runtime": comments[0],
        }
    if comments:
        return {
            "action": "use-managed-comment",
            "storage_source": "managed-comment",
            "runtime": comments[0],
        }
    return {
        "action": "create-document" if wrapper["documents_available"] else "create-managed-comment",
        "storage_source": "document" if wrapper["documents_available"] else "managed-comment",
        "runtime": None,
    }


def validate_autopilot_policy(payload: dict[str, Any]) -> dict[str, Any]:
    wrapper = _require_exact_object_fields(
        payload,
        ["policy_binding", "current_binding", "operation"],
        "autopilot policy input",
    )
    for field in ("policy_binding", "current_binding"):
        if not isinstance(wrapper[field], dict):
            raise ValueError(f"{field} must be an object")
        for binding_field in milestone_runtime_contract()["autopilot"]["expiry_fields"]:
            if binding_field not in wrapper[field]:
                raise ValueError(f"{field} is missing {binding_field}")
    operation = _require_nonempty_text(wrapper["operation"], "operation")
    autopilot = milestone_runtime_contract()["autopilot"]
    drift = [
        field
        for field in autopilot["expiry_fields"]
        if wrapper["policy_binding"][field] != wrapper["current_binding"][field]
    ]
    if drift:
        return {
            "status": "expired",
            "operation": operation,
            "drift_fields": drift,
            "automatic": False,
            "approval_required": True,
        }
    if operation in autopilot["gated_operations"]:
        return {
            "status": "bound",
            "operation": operation,
            "drift_fields": [],
            "automatic": False,
            "approval_required": True,
        }
    if operation not in autopilot["automatic_operations"]:
        raise ValueError("autopilot operation is not contract-bound")
    return {
        "status": "bound",
        "operation": operation,
        "drift_fields": [],
        "automatic": True,
        "approval_required": False,
    }


def resolve_milestone_run_mode(payload: dict[str, Any]) -> dict[str, Any]:
    wrapper = _require_exact_object_fields(
        payload,
        [
            "command",
            "autopilot",
            "until",
            "max_events",
            "repair_safe",
            "isolated_worktree",
        ],
        "milestone run mode input",
    )
    if wrapper["command"] not in {"run-milestone", "run-milestone-loop"}:
        raise ValueError("milestone run mode command is invalid")
    for field in ("autopilot", "repair_safe", "isolated_worktree"):
        if not isinstance(wrapper[field], bool):
            raise ValueError(f"{field} must be boolean")
    if wrapper["command"] == "run-milestone-loop" and wrapper["autopilot"]:
        raise ValueError("run-milestone-loop does not accept the autopilot alias flag")
    supervisor_requested = (
        wrapper["autopilot"]
        or wrapper["until"] is not None
        or wrapper["max_events"] is not None
        or wrapper["repair_safe"]
    )
    if not supervisor_requested:
        return {
            "mode": "legacy-single-stage"
            if wrapper["command"] == "run-milestone"
            else "legacy-single-event",
            "command": wrapper["command"],
            "until": None,
            "max_events": 1,
            "repair_safe": False,
            "isolated_worktree": wrapper["isolated_worktree"],
            "isolated_worktree_status": "legacy-applicability-rules",
        }
    contract = milestone_runtime_contract()["autopilot"]
    until = wrapper["until"] or contract["default_until"]
    maximum = wrapper["max_events"] or contract["default_max_events"]
    if (
        not isinstance(until, list)
        or not until
        or not all(isinstance(item, str) and item for item in until)
    ):
        raise ValueError("until must be a non-empty text list")
    if (
        not isinstance(maximum, int)
        or isinstance(maximum, bool)
        or maximum <= 0
        or maximum > contract["hard_max_events"]
    ):
        raise ValueError("max_events must be between 1 and 100")
    return {
        "mode": "guarded-autopilot",
        "command": "run-milestone-loop",
        "alias_source": (
            "run-milestone --autopilot" if wrapper["command"] == "run-milestone" else None
        ),
        "until": until,
        "max_events": maximum,
        "repair_safe": wrapper["repair_safe"],
        "isolated_worktree": True,
        "isolated_worktree_status": (
            "idempotent-assertion" if wrapper["isolated_worktree"] else "inherent-task-isolation"
        ),
    }


def validate_autopilot_loop(payload: dict[str, Any]) -> dict[str, Any]:
    wrapper = _require_exact_object_fields(
        payload,
        ["max_events", "event_count", "until", "observed_stop", "receipts", "isolated_worktree"],
        "autopilot loop input",
    )
    contract = milestone_runtime_contract()["autopilot"]
    maximum = wrapper["max_events"]
    event_count = wrapper["event_count"]
    if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum <= 0:
        raise ValueError("max_events must be positive")
    if maximum > contract["hard_max_events"]:
        raise ValueError("max_events exceeds the hard limit of 100")
    if not isinstance(event_count, int) or isinstance(event_count, bool) or event_count < 0:
        raise ValueError("event_count must be non-negative")
    if not isinstance(wrapper["until"], list) or not wrapper["until"]:
        raise ValueError("until must contain stop conditions")
    allowed_stops = {
        "approval-required",
        "blocked",
        "human-verification",
        "milestone-done",
        "event-ceiling",
    }
    if not set(wrapper["until"]) <= allowed_stops:
        raise ValueError("until contains an unknown stop condition")
    receipts = wrapper["receipts"]
    if not isinstance(receipts, list) or len(receipts) != event_count:
        raise ValueError("every autopilot event requires one receipt")
    session_ids: list[str] = []
    for receipt in receipts:
        if not isinstance(receipt, dict) or set(receipt) != {
            "event_id",
            "session_id",
            "persisted",
            "read_back",
        }:
            raise ValueError("autopilot receipt fields are incomplete")
        session_ids.append(_require_nonempty_text(receipt["session_id"], "session_id"))
        if receipt["persisted"] is not True or receipt["read_back"] is not True:
            raise ValueError("autopilot receipts must be persisted and read back")
    if len(session_ids) != len(set(session_ids)):
        raise ValueError("FRESH_CONTEXT_REQUIRED: each event needs a fresh session")
    if not isinstance(wrapper["isolated_worktree"], bool):
        raise ValueError("isolated_worktree must be boolean")
    observed = wrapper["observed_stop"]
    if observed is not None and observed not in allowed_stops:
        raise ValueError("observed_stop is invalid")
    stop = observed if (observed in wrapper["until"] or observed == "human-verification") else None
    if event_count >= maximum:
        stop = "event-ceiling"
    return {
        "event_count": event_count,
        "max_events": maximum,
        "stop": stop,
        "continue": stop is None,
        "next_event_requires_fresh_session": stop is None,
        "isolated_worktree_asserted": wrapper["isolated_worktree"],
    }


def validate_milestone_findings(payload: dict[str, Any]) -> dict[str, Any]:
    required = {
        "milestone_id",
        "session_id",
        "findings",
        "existing_session_ids",
        "candidate_owners",
        "changed_provided_surfaces",
        "unfinished_plans",
    }
    allowed = {*required, "existing_session_hashes"}
    if not isinstance(payload, dict) or not required <= set(payload) or not set(payload) <= allowed:
        raise ValueError("milestone findings input fields are incomplete")
    wrapper = payload
    _require_nonempty_text(wrapper["milestone_id"], "milestone_id")
    session_id = _require_nonempty_text(wrapper["session_id"], "session_id")
    findings = wrapper["findings"]
    if not isinstance(findings, list) or not findings:
        raise ValueError("at least one non-empty finding is required")
    blockers: list[Any] = []
    suggestions: list[Any] = []
    from ._reviews_v1 import finding_is_blocking

    for finding in findings:
        if isinstance(finding, str) and finding.strip():
            blockers.append(finding)
        elif isinstance(finding, dict) and set(finding) == {
            "summary",
            "classification",
            "requirement",
            "evidence",
        }:
            _require_nonempty_text(finding["summary"], "finding summary")
            (blockers if finding_is_blocking(finding) else suggestions).append(finding)
        else:
            raise ValueError(
                "findings require text or classified summary, requirement and evidence"
            )
    if not isinstance(wrapper["existing_session_ids"], list):
        raise ValueError("existing_session_ids must be a list")
    batch_hash = canonical_digest(
        {
            "milestone_id": wrapper["milestone_id"],
            "session_id": session_id,
            "findings": findings,
        }
    )
    if session_id in wrapper["existing_session_ids"]:
        hashes = wrapper.get("existing_session_hashes")
        if hashes is not None:
            if not isinstance(hashes, dict) or not set(hashes) <= set(
                wrapper["existing_session_ids"]
            ):
                raise ValueError("existing_session_hashes are invalid")
            for existing_id, digest in hashes.items():
                validate_sha256(digest, f"existing session {existing_id}")
            if hashes.get(session_id) != batch_hash:
                raise ValueError(
                    "MILESTONE_FINDINGS_SESSION_CONFLICT: repeated session batch differs"
                )
        return {
            "status": "idempotent-replay",
            "session_id": session_id,
            "batch_hash": batch_hash,
            "action": "none",
            "invalidate_plan_ids": [],
        }
    owners = wrapper["candidate_owners"]
    if not blockers:
        return {
            "status": "suggestions-only",
            "session_id": session_id,
            "batch_hash": batch_hash,
            "action": "none",
            "repair_task_count": 0,
            "invalidate_plan_ids": [],
            "suggestions": suggestions,
        }
    if not isinstance(owners, list) or not all(
        isinstance(owner, str) and owner for owner in owners
    ):
        raise ValueError("candidate_owners must be a text list")
    unique_owners = list(dict.fromkeys(owners))
    action = "reopen-owner" if len(unique_owners) == 1 else "preview-managed-repair-task"
    changed_surfaces = wrapper["changed_provided_surfaces"]
    if not isinstance(changed_surfaces, list) or not all(
        isinstance(surface, str) and surface for surface in changed_surfaces
    ):
        raise ValueError("changed_provided_surfaces must be a text list")
    plans = wrapper["unfinished_plans"]
    if not isinstance(plans, list):
        raise ValueError("unfinished_plans must be a list")
    invalidated: list[str] = []
    for plan in plans:
        if not isinstance(plan, dict) or set(plan) != {"task_id", "consumed_surfaces"}:
            raise ValueError("unfinished plan surface fields are incomplete")
        if set(plan["consumed_surfaces"]) & set(changed_surfaces):
            invalidated.append(plan["task_id"])
    return {
        "status": "accepted",
        "blocking_findings": blockers,
        "suggestions": suggestions,
        "session_id": session_id,
        "batch_hash": batch_hash,
        "action": action,
        "owner_task_id": unique_owners[0] if len(unique_owners) == 1 else None,
        "repair_task_count": 0 if len(unique_owners) == 1 else 1,
        "return_stage": "implementing",
        "preserve_gate_history": True,
        "preserve_checklist_history": True,
        "machine_reverification_required": True,
        "fresh_human_checklist_required": True,
        "invalidate_plan_ids": invalidated,
    }
