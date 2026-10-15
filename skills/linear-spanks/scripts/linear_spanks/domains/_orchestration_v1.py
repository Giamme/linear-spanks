"""Versioned project and milestone orchestration semantics."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..contracts.legacy import (
    human_verification_contract,
    milestone_orchestration_contract,
    parse_rfc3339,
    project_orchestration_contract,
    routing_contract,
)
from ..core.legacy_constants import ROUTING_HARNESSES
from ..core.legacy_validation import (
    _require_commit,
    _require_exact_object_fields,
    _require_nonempty_text,
    _require_positive_revision,
)
from ._state_v1 import validate_sha256
from ._verification_v1 import validate_effective_human_policy


def _validate_selected_model(value: Any) -> dict[str, Any]:
    loop = project_orchestration_contract()["task_loop"]
    selected = _require_exact_object_fields(value, loop["selected_model_fields"], "selected model")
    if selected["strength"] not in {"medium", "high"}:
        raise ValueError("selected executor model must be medium or high")
    _require_nonempty_text(selected["model"], "selected model")
    if selected["harness"] not in ROUTING_HARNESSES:
        raise ValueError("selected model harness is unsupported")
    if selected["capability"] not in routing_contract()["harness_capabilities"]:
        raise ValueError("selected model capability is invalid")
    if selected["configured"] is not True:
        raise ValueError("selected executor model must be configured")
    return selected


def validate_project_loop_receipt(payload: dict[str, Any]) -> dict[str, Any]:
    contract = project_orchestration_contract()
    schema = contract["project_loop_receipt"]
    receipt = _require_exact_object_fields(
        payload, schema["required_fields"], "project loop receipt"
    )
    if receipt["schema_version"] != contract["schema_version"]:
        raise ValueError("project loop receipt schema_version is invalid")
    for field in ("receipt_id", "project_id", "project_orchestrator_id"):
        _require_nonempty_text(receipt[field], field)
    _require_positive_revision(receipt["project_revision"], "project_revision")
    validate_sha256(receipt["source_hash"], "source_hash")
    validate_sha256(receipt["dependency_graph_hash"], "dependency_graph_hash")
    state = receipt["state"]
    if state not in schema["states"]:
        raise ValueError(f"unknown project loop receipt state: {state}")

    created = parse_rfc3339(receipt["created_at"])
    updated = parse_rfc3339(receipt["updated_at"])
    if updated < created:
        raise ValueError("project loop receipt updated_at predates created_at")
    timestamps = receipt["state_timestamps"]
    if not isinstance(timestamps, dict) or state not in timestamps:
        raise ValueError("project loop receipt must timestamp its current state")
    if not set(timestamps).issubset(schema["states"]):
        raise ValueError("project loop receipt has unknown state timestamps")
    for name, timestamp in timestamps.items():
        parsed = parse_rfc3339(timestamp)
        if parsed < created or parsed > updated:
            raise ValueError(f"project loop receipt timestamp {name} is out of bounds")

    milestones = receipt["milestones"]
    if not isinstance(milestones, list):
        raise ValueError("project loop milestones must be a list")
    milestone_ids: set[str] = set()
    milestone_orchestrators: set[str] = set()
    for index, milestone in enumerate(milestones):
        item = _require_exact_object_fields(
            milestone, schema["milestone_fields"], f"milestones[{index}]"
        )
        milestone_id = _require_nonempty_text(item["milestone_id"], "milestone_id")
        orchestrator_id = _require_nonempty_text(item["orchestrator_id"], "orchestrator_id")
        if milestone_id in milestone_ids:
            raise ValueError(f"duplicate milestone orchestrator binding: {milestone_id}")
        if orchestrator_id in milestone_orchestrators:
            raise ValueError(f"milestone orchestrator reused across milestones: {orchestrator_id}")
        milestone_ids.add(milestone_id)
        milestone_orchestrators.add(orchestrator_id)
        _require_positive_revision(item["milestone_revision"], "milestone_revision")
        if item["state"] not in schema["milestone_states"]:
            raise ValueError(f"unknown milestone orchestrator state: {item['state']}")

    policies = receipt["human_verification_policies"]
    if not isinstance(policies, list):
        raise ValueError("project human verification policies must be a list")
    policy_ids: set[str] = set()
    for index, binding in enumerate(policies):
        if not isinstance(binding, dict):
            raise ValueError(f"human_verification_policies[{index}] must be an object")
        effective = {"schema_version": human_verification_contract()["schema_version"], **binding}
        validated = validate_effective_human_policy(effective)
        if validated["project_id"] != receipt["project_id"]:
            raise ValueError("HUMAN_VERIFICATION_POLICY_DRIFT: project receipt binding")
        if validated["milestone_id"] in policy_ids:
            raise ValueError("duplicate project human verification milestone binding")
        policy_ids.add(validated["milestone_id"])
    if policy_ids != milestone_ids:
        raise ValueError("project receipt must bind human verification for every milestone")

    task_loops = receipt["task_loops"]
    if not isinstance(task_loops, list):
        raise ValueError("project task loops must be a list")
    task_ids: set[str] = set()
    executor_ids: set[str] = set()
    verifier_ids: set[str] = set()
    for index, task_loop in enumerate(task_loops):
        item = _require_exact_object_fields(
            task_loop, schema["task_loop_fields"], f"task_loops[{index}]"
        )
        task_id = _require_nonempty_text(item["task_id"], "task_id")
        milestone_id = _require_nonempty_text(item["milestone_id"], "milestone_id")
        executor_id = _require_nonempty_text(item["executor_id"], "executor_id")
        verifier_id = _require_nonempty_text(item["verifier_id"], "verifier_id")
        if milestone_id not in milestone_ids:
            raise ValueError(f"task loop {task_id} references an unknown milestone")
        if task_id in task_ids:
            raise ValueError(f"duplicate task loop binding: {task_id}")
        if executor_id in executor_ids:
            raise ValueError(f"task executor reused across tasks: {executor_id}")
        if verifier_id in verifier_ids:
            raise ValueError(f"task verifier reused across tasks: {verifier_id}")
        task_ids.add(task_id)
        executor_ids.add(executor_id)
        verifier_ids.add(verifier_id)
        _require_positive_revision(item["plan_revision"], "plan_revision")
        attempt = item["attempt_index"]
        if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 0:
            raise ValueError("task loop attempt_index must be a non-negative integer")
        if item["state"] not in schema["task_loop_states"]:
            raise ValueError(f"unknown task loop state: {item['state']}")
        if item["state"] == "prepared" and attempt != 0:
            raise ValueError("prepared task loop must start at attempt zero")
        if item["state"] == "awaiting-model-selection" and attempt < 3:
            raise ValueError("model selection requires four automatic attempts")

    events = contract["event_selection"]["events"]
    for field in ("current_event", "next_event"):
        value = receipt[field]
        if value is not None and value not in events:
            raise ValueError(f"unknown {field}: {value}")

    approval = _require_exact_object_fields(
        receipt["approval"], schema["approval_fields"], "project loop approval"
    )
    if approval["status"] not in schema["approval_statuses"]:
        raise ValueError("project loop approval status is invalid")
    for field in ("preview_hash", "approved_hash"):
        if approval[field] is not None:
            validate_sha256(approval[field], field)
    if approval["status"] == "approved" and (
        approval["preview_hash"] is None or approval["approved_hash"] != approval["preview_hash"]
    ):
        raise ValueError("approved project loop preview hash must match")
    if approval["status"] == "pending" and approval["preview_hash"] is None:
        raise ValueError("pending project loop approval requires a preview hash")
    if approval["status"] == "not-required" and any(
        approval[field] is not None for field in ("preview_hash", "approved_hash")
    ):
        raise ValueError("not-required project loop approval cannot bind hashes")
    if state == "awaiting-approval" and approval["status"] != "pending":
        raise ValueError("awaiting-approval receipt requires a pending preview")
    if state == "milestone-integrating" and approval["status"] != "approved":
        raise ValueError("milestone-integrating receipt requires approved preview")

    budget = _require_exact_object_fields(
        receipt["budget"], schema["budget_fields"], "project loop budget"
    )
    for field, value in budget.items():
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"project loop budget {field} must be a non-negative integer")

    if state == "completed":
        if any(item["state"] != "completed" for item in milestones):
            raise ValueError("completed project loop requires every milestone completed")
        if any(item["state"] != "integrated" for item in task_loops):
            raise ValueError("completed project loop requires every task loop integrated")
    if state == "failed":
        if not isinstance(receipt["failure"], dict) or not receipt["failure"]:
            raise ValueError("failed project loop receipt requires failure evidence")
    elif receipt["failure"] is not None:
        raise ValueError("non-failed project loop receipt cannot contain failure evidence")
    return receipt


def check_project_loop_receipts(payload: dict[str, Any]) -> dict[str, Any]:
    if "receipts" not in payload:
        receipt = validate_project_loop_receipt(payload)
        return {"status": "valid", "receipt": receipt}
    wrapper = _require_exact_object_fields(
        payload,
        ["project_id", "project_revision", "receipts"],
        "project loop receipt selection",
    )
    project_id = _require_nonempty_text(wrapper["project_id"], "project_id")
    project_revision = _require_positive_revision(wrapper["project_revision"], "project_revision")
    if not isinstance(wrapper["receipts"], list):
        raise ValueError("project loop receipt selection requires a receipts list")
    active_states = set(project_orchestration_contract()["project_loop_receipt"]["active_states"])
    active: list[dict[str, Any]] = []
    for raw in wrapper["receipts"]:
        receipt = validate_project_loop_receipt(raw)
        if (
            receipt["project_id"] == project_id
            and receipt["project_revision"] == project_revision
            and receipt["state"] in active_states
        ):
            active.append(receipt)
    if len(active) > 1:
        receipt_ids = sorted(receipt["receipt_id"] for receipt in active)
        raise ValueError("PROJECT_ORCHESTRATION_RECEIPT_AMBIGUOUS: " + ", ".join(receipt_ids))
    return {
        "status": "resume" if active else "new",
        "receipt_id": active[0]["receipt_id"] if active else None,
    }


def _task_workflow_projection(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from .runtime import task_next

    source = dict(payload)
    workflows = source.pop("task_workflows", None)
    if workflows is None:
        return source, []
    if not isinstance(workflows, list):
        raise ValueError("task_workflows must be a list")
    if any(workflow.get("integration_required", True) is not True for workflow in workflows):
        raise ValueError("TASK_WORKFLOW_DRIFT: orchestrated tasks require isolated integration")
    actions = [task_next(workflow) for workflow in workflows]
    ids = {action["task_id"] for action in actions}
    if len(ids) != len(actions):
        raise ValueError("task_workflows must have unique task identities")
    for field in (
        "executing_task_ids",
        "verifying_task_ids",
        "verified_task_ids",
        "ready_task_ids",
    ):
        source[field] = [task for task in source[field] if task not in ids]
    for action in actions:
        if action["next_action"] in {
            "implement",
            "automatic-repair",
            "user-selected-repair",
            "diagnose",
            "record-plan",
            "refresh-evidence",
            "replan",
        }:
            source["executing_task_ids"].append(action["task_id"])
        elif action["next_action"] == "verify":
            source["verifying_task_ids"].append(action["task_id"])
        elif action["next_action"] == "verified-pending-integration":
            source["verified_task_ids"].append(action["task_id"])
        elif action["next_action"] in {"await-approval", "user-model-selection"}:
            source["approval_pending"] = True
    return source, actions


def select_project_loop_event(payload: dict[str, Any]) -> dict[str, Any]:
    payload, task_actions = _task_workflow_projection(payload)
    payload.setdefault("awaiting_human_verification_milestone_ids", [])
    fields = [
        "project_drift",
        "cross_milestone_conflict",
        "approval_pending",
        "executing_task_ids",
        "verifying_task_ids",
        "verified_task_ids",
        "ready_task_ids",
        "awaiting_human_verification_milestone_ids",
        "milestones_ready_to_wrap",
        "eligible_milestone_ids",
        "project_complete",
    ]
    source = _require_exact_object_fields(payload, fields, "project loop event input")
    for field in (
        "project_drift",
        "cross_milestone_conflict",
        "approval_pending",
        "project_complete",
    ):
        if not isinstance(source[field], bool):
            raise ValueError(f"{field} must be boolean")
    for field in fields[3:10]:
        values = source[field]
        if not isinstance(values, list) or not all(
            isinstance(value, str) and value for value in values
        ):
            raise ValueError(f"{field} must be a text list")
        if len(values) != len(set(values)):
            raise ValueError(f"{field} must not contain duplicates")

    if source["project_drift"] or source["cross_milestone_conflict"]:
        event, state = "project-reconcile", "project-reconciling"
    elif source["approval_pending"]:
        event, state = "await-approval", "awaiting-approval"
    elif source["executing_task_ids"]:
        event, state = "task-execute", "task-wave-executing"
    elif source["verifying_task_ids"]:
        event, state = "task-verify", "task-wave-verifying"
    elif source["verified_task_ids"]:
        event, state = "milestone-integrate", "milestone-integrating"
    elif source["awaiting_human_verification_milestone_ids"]:
        event, state = "await-human-verification", "milestone-orchestrating"
    elif source["ready_task_ids"]:
        event, state = "task-dispatch", "milestone-orchestrating"
    elif task_actions and any(
        action["next_action"] in {"blocked", "prerequisite-recovery"} for action in task_actions
    ):
        event, state = "blocked", "project-orchestrating"
    elif source["milestones_ready_to_wrap"]:
        event, state = "milestone-wrap", "milestone-orchestrating"
    elif source["eligible_milestone_ids"]:
        event, state = "milestone-orchestrate", "milestone-orchestrating"
    elif source["project_complete"]:
        event, state = "project-complete", "completed"
    else:
        event, state = "blocked", "project-orchestrating"
    return {
        "event": event,
        "target_state": state,
        **({"task_actions": task_actions} if task_actions else {}),
    }


def validate_milestone_loop_receipt(payload: dict[str, Any]) -> dict[str, Any]:
    contract = milestone_orchestration_contract()
    schema = contract["milestone_loop_receipt"]
    receipt = _require_exact_object_fields(
        payload, schema["required_fields"], "milestone loop receipt"
    )
    if receipt["schema_version"] != contract["schema_version"]:
        raise ValueError("milestone loop receipt schema_version is invalid")
    for field in ("receipt_id", "project_id", "milestone_id", "milestone_orchestrator_id"):
        _require_nonempty_text(receipt[field], field)
    for field in ("project_revision", "milestone_revision"):
        _require_positive_revision(receipt[field], field)
    for field in ("source_hash", "dependency_graph_hash"):
        validate_sha256(receipt[field], field)
    binding = receipt["human_verification_policy"]
    if not isinstance(binding, dict):
        raise ValueError("milestone receipt human verification policy must be an object")
    effective = validate_effective_human_policy(
        {"schema_version": human_verification_contract()["schema_version"], **binding}
    )
    if (
        effective["project_id"] != receipt["project_id"]
        or effective["milestone_id"] != receipt["milestone_id"]
    ):
        raise ValueError("HUMAN_VERIFICATION_POLICY_DRIFT: milestone receipt binding")
    if receipt["state"] not in schema["states"]:
        raise ValueError(f"unknown milestone loop receipt state: {receipt['state']}")
    created = parse_rfc3339(receipt["created_at"])
    updated = parse_rfc3339(receipt["updated_at"])
    if updated < created:
        raise ValueError("milestone loop receipt updated_at predates created_at")
    timestamps = receipt["state_timestamps"]
    if not isinstance(timestamps, dict) or receipt["state"] not in timestamps:
        raise ValueError("milestone loop receipt must timestamp its current state")
    if not set(timestamps).issubset(schema["states"]):
        raise ValueError("milestone loop receipt has unknown state timestamps")
    for state, timestamp in timestamps.items():
        parsed = parse_rfc3339(timestamp)
        if parsed < created or parsed > updated:
            raise ValueError(f"milestone loop receipt timestamp {state} is out of bounds")

    task_ids: set[str] = set()
    executor_ids: set[str] = set()
    verifier_ids: set[str] = set()
    task_loops = receipt["task_loops"]
    if not isinstance(task_loops, list):
        raise ValueError("milestone task loops must be a list")
    for index, task_loop in enumerate(task_loops):
        item = _require_exact_object_fields(
            task_loop, schema["task_loop_fields"], f"task_loops[{index}]"
        )
        task_id = _require_nonempty_text(item["task_id"], "task_id")
        if item["milestone_id"] != receipt["milestone_id"]:
            raise ValueError(f"task loop {task_id} references another milestone")
        executor_id = _require_nonempty_text(item["executor_id"], "executor_id")
        verifier_id = _require_nonempty_text(item["verifier_id"], "verifier_id")
        if task_id in task_ids:
            raise ValueError(f"duplicate task loop binding: {task_id}")
        if executor_id in executor_ids:
            raise ValueError(f"task executor reused across tasks: {executor_id}")
        if verifier_id in verifier_ids:
            raise ValueError(f"task verifier reused across tasks: {verifier_id}")
        task_ids.add(task_id)
        executor_ids.add(executor_id)
        verifier_ids.add(verifier_id)
        _require_positive_revision(item["plan_revision"], "plan_revision")
        if (
            not isinstance(item["attempt_index"], int)
            or isinstance(item["attempt_index"], bool)
            or item["attempt_index"] < 0
        ):
            raise ValueError("task loop attempt_index must be a non-negative integer")
        if item["state"] not in schema["task_loop_states"]:
            raise ValueError(f"unknown task loop state: {item['state']}")
        if item["state"] == "prepared" and item["attempt_index"] != 0:
            raise ValueError("prepared task loop must start at attempt zero")
        if item["state"] == "awaiting-model-selection" and item["attempt_index"] < 3:
            raise ValueError("model selection requires four automatic attempts")

    for field in ("current_event", "next_event"):
        value = receipt[field]
        if value is not None and value not in contract["event_selection"]["events"]:
            raise ValueError(f"unknown {field}: {value}")
    approval = _require_exact_object_fields(
        receipt["approval"], schema["approval_fields"], "milestone loop approval"
    )
    if approval["status"] not in schema["approval_statuses"]:
        raise ValueError("milestone loop approval status is invalid")
    for field in ("preview_hash", "approved_hash"):
        if approval[field] is not None:
            validate_sha256(approval[field], field)
    if approval["status"] == "approved" and (
        approval["preview_hash"] is None or approval["approved_hash"] != approval["preview_hash"]
    ):
        raise ValueError("approved milestone loop preview hash must match")
    if approval["status"] == "pending" and approval["preview_hash"] is None:
        raise ValueError("pending milestone loop approval requires a preview hash")
    if approval["status"] == "not-required" and any(
        approval[field] is not None for field in ("preview_hash", "approved_hash")
    ):
        raise ValueError("not-required milestone loop approval cannot bind hashes")
    if receipt["state"] == "awaiting-approval" and approval["status"] != "pending":
        raise ValueError("awaiting-approval receipt requires a pending preview")
    if receipt["state"] == "milestone-integrating" and approval["status"] != "approved":
        raise ValueError("milestone-integrating receipt requires approved preview")
    budget = _require_exact_object_fields(
        receipt["budget"], schema["budget_fields"], "milestone loop budget"
    )
    for field, value in budget.items():
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"milestone loop budget {field} must be a non-negative integer")
    if receipt["state"] == "completed" and any(
        item["state"] != "integrated" for item in task_loops
    ):
        raise ValueError("completed milestone loop requires every task loop integrated")
    if receipt["state"] == "failed":
        if not isinstance(receipt["failure"], dict) or not receipt["failure"]:
            raise ValueError("failed milestone loop receipt requires failure evidence")
    elif receipt["failure"] is not None:
        raise ValueError("non-failed milestone loop receipt cannot contain failure evidence")
    return receipt


def check_milestone_loop_receipts(payload: dict[str, Any]) -> dict[str, Any]:
    if "receipts" not in payload:
        receipt = validate_milestone_loop_receipt(payload)
        return {"status": "valid", "receipt": receipt}
    wrapper = _require_exact_object_fields(
        payload,
        ["project_id", "project_revision", "milestone_id", "milestone_revision", "receipts"],
        "milestone loop receipt selection",
    )
    for field in ("project_id", "milestone_id"):
        _require_nonempty_text(wrapper[field], field)
    for field in ("project_revision", "milestone_revision"):
        _require_positive_revision(wrapper[field], field)
    if not isinstance(wrapper["receipts"], list):
        raise ValueError("milestone loop receipt selection requires a receipts list")
    active_states = set(
        milestone_orchestration_contract()["milestone_loop_receipt"]["active_states"]
    )
    active = [
        receipt
        for receipt in (validate_milestone_loop_receipt(raw) for raw in wrapper["receipts"])
        if receipt["project_id"] == wrapper["project_id"]
        and receipt["project_revision"] == wrapper["project_revision"]
        and receipt["milestone_id"] == wrapper["milestone_id"]
        and receipt["milestone_revision"] == wrapper["milestone_revision"]
        and receipt["state"] in active_states
    ]
    if len(active) > 1:
        raise ValueError(
            "MILESTONE_ORCHESTRATION_RECEIPT_AMBIGUOUS: "
            + ", ".join(sorted(receipt["receipt_id"] for receipt in active))
        )
    return {
        "status": "resume" if active else "new",
        "receipt_id": active[0]["receipt_id"] if active else None,
    }


def select_milestone_loop_event(payload: dict[str, Any]) -> dict[str, Any]:
    payload, task_actions = _task_workflow_projection(payload)
    payload.setdefault("awaiting_human_verification", False)
    fields = [
        "project_coordination_required",
        "approval_pending",
        "executing_task_ids",
        "verifying_task_ids",
        "verified_task_ids",
        "ready_task_ids",
        "awaiting_human_verification",
        "milestone_ready_to_wrap",
        "eligible_milestone_work",
        "milestone_complete",
    ]
    source = _require_exact_object_fields(payload, fields, "milestone loop event input")
    for field in (
        "project_coordination_required",
        "approval_pending",
        "awaiting_human_verification",
        "milestone_ready_to_wrap",
        "eligible_milestone_work",
        "milestone_complete",
    ):
        if not isinstance(source[field], bool):
            raise ValueError(f"{field} must be boolean")
    for field in (
        "executing_task_ids",
        "verifying_task_ids",
        "verified_task_ids",
        "ready_task_ids",
    ):
        values = source[field]
        if not isinstance(values, list) or not all(
            isinstance(value, str) and value for value in values
        ):
            raise ValueError(f"{field} must be a text list")
        if len(values) != len(set(values)):
            raise ValueError(f"{field} must not contain duplicates")
    if source["project_coordination_required"]:
        event, state = "project-coordination-required", "milestone-orchestrating"
    elif source["approval_pending"]:
        event, state = "await-approval", "awaiting-approval"
    elif source["executing_task_ids"]:
        event, state = "task-execute", "task-wave-executing"
    elif source["verifying_task_ids"]:
        event, state = "task-verify", "task-wave-verifying"
    elif source["verified_task_ids"]:
        event, state = "milestone-integrate", "milestone-integrating"
    elif source["awaiting_human_verification"]:
        event, state = "await-human-verification", "milestone-orchestrating"
    elif source["ready_task_ids"]:
        event, state = "task-dispatch", "milestone-orchestrating"
    elif task_actions and any(
        action["next_action"] in {"blocked", "prerequisite-recovery"} for action in task_actions
    ):
        event, state = "blocked", "milestone-orchestrating"
    elif source["milestone_ready_to_wrap"]:
        event, state = "milestone-wrap", "milestone-orchestrating"
    elif source["eligible_milestone_work"]:
        event, state = "milestone-orchestrate", "milestone-orchestrating"
    elif source["milestone_complete"]:
        event, state = "milestone-complete", "completed"
    else:
        event, state = "blocked", "milestone-orchestrating"
    return {
        "event": event,
        "target_state": state,
        **({"task_actions": task_actions} if task_actions else {}),
    }


def check_orchestration_scope(payload: dict[str, Any]) -> dict[str, Any]:
    source = _require_exact_object_fields(
        payload,
        ["scope", "project_id", "project_revision", "project_receipts", "milestone_receipts"],
        "orchestration scope check",
    )
    if source["scope"] not in {"project", "milestone"}:
        raise ValueError("orchestration scope must be project or milestone")
    _require_nonempty_text(source["project_id"], "project_id")
    _require_positive_revision(source["project_revision"], "project_revision")
    if not isinstance(source["project_receipts"], list) or not isinstance(
        source["milestone_receipts"], list
    ):
        raise ValueError("orchestration scope receipts must be lists")
    active_project = [
        receipt
        for receipt in (validate_project_loop_receipt(raw) for raw in source["project_receipts"])
        if receipt["project_id"] == source["project_id"]
        and receipt["project_revision"] == source["project_revision"]
        and receipt["state"]
        in project_orchestration_contract()["project_loop_receipt"]["active_states"]
    ]
    active_milestone = [
        receipt
        for receipt in (
            validate_milestone_loop_receipt(raw) for raw in source["milestone_receipts"]
        )
        if receipt["project_id"] == source["project_id"]
        and receipt["project_revision"] == source["project_revision"]
        and receipt["state"]
        in milestone_orchestration_contract()["milestone_loop_receipt"]["active_states"]
    ]
    blocking = active_project if source["scope"] == "milestone" else active_milestone
    if blocking:
        raise ValueError(
            "ORCHESTRATION_SCOPE_CONFLICT: "
            + ", ".join(sorted(receipt["receipt_id"] for receipt in blocking))
        )
    return {"status": "clear", "scope": source["scope"]}


def transition_milestone_loop_receipt(
    receipt: dict[str, Any], request: dict[str, Any]
) -> dict[str, Any]:
    current = validate_milestone_loop_receipt(receipt)
    schema = milestone_orchestration_contract()["milestone_loop_receipt"]
    transition = _require_exact_object_fields(
        request, schema["transition_request_fields"], "milestone loop transition request"
    )
    for field, current_field in (
        ("current_project_revision", "project_revision"),
        ("current_milestone_revision", "milestone_revision"),
    ):
        if transition[field] != current[current_field]:
            raise ValueError(f"MILESTONE_ORCHESTRATION_DRIFT: {current_field}")
    for field, current_field in (
        ("current_source_hash", "source_hash"),
        ("current_dependency_graph_hash", "dependency_graph_hash"),
    ):
        validate_sha256(transition[field], field)
        if current_field != "source_hash" and transition[field] != current[current_field]:
            raise ValueError(f"MILESTONE_ORCHESTRATION_DRIFT: {current_field}")
    if transition["current_task_loops"] != current["task_loops"]:
        raise ValueError("MILESTONE_ORCHESTRATION_DRIFT: task_loops")
    if transition["current_human_verification_policy"] != current["human_verification_policy"]:
        raise ValueError("HUMAN_VERIFICATION_POLICY_DRIFT: milestone receipt")
    if transition["completed_event"] != current["next_event"]:
        raise ValueError("MILESTONE_ORCHESTRATION_DRIFT: next_event")
    for field, current_field in (
        ("next_project_revision", "project_revision"),
        ("next_milestone_revision", "milestone_revision"),
    ):
        _require_positive_revision(transition[field], field)
        if transition[field] < current[current_field]:
            raise ValueError(f"milestone loop {field} moves backwards")
    for field in ("next_source_hash", "next_dependency_graph_hash"):
        validate_sha256(transition[field], field)
    target = transition["target_state"]
    if target not in schema["transitions"][current["state"]]:
        raise ValueError(f"invalid milestone loop transition: {current['state']} -> {target}")
    if (
        transition["next_event"] is not None
        and transition["next_event"]
        not in milestone_orchestration_contract()["event_selection"]["events"]
    ):
        raise ValueError("milestone loop transition next_event is invalid")
    if parse_rfc3339(transition["updated_at"]) < parse_rfc3339(current["updated_at"]):
        raise ValueError("milestone loop transition updated_at moves backwards")
    result = json.loads(json.dumps(current))
    result.update(
        {
            "state": target,
            "project_revision": transition["next_project_revision"],
            "milestone_revision": transition["next_milestone_revision"],
            "source_hash": transition["next_source_hash"],
            "dependency_graph_hash": transition["next_dependency_graph_hash"],
            "human_verification_policy": transition["next_human_verification_policy"],
            "task_loops": transition["next_task_loops"],
            "current_event": transition["completed_event"],
            "next_event": transition["next_event"],
            "approval": transition["approval"],
            "budget": transition["next_budget"],
            "failure": transition["failure"],
            "updated_at": transition["updated_at"],
        }
    )
    result["state_timestamps"][target] = transition["updated_at"]
    result = validate_milestone_loop_receipt(result)
    old_tasks = {
        item["task_id"]: (item["executor_id"], item["verifier_id"])
        for item in current["task_loops"]
    }
    new_tasks = {
        item["task_id"]: (item["executor_id"], item["verifier_id"]) for item in result["task_loops"]
    }
    for task_id, role_ids in old_tasks.items():
        if new_tasks.get(task_id) != role_ids:
            raise ValueError(f"milestone loop transition changed task role binding: {task_id}")
    for field in schema["budget_fields"]:
        if result["budget"][field] < current["budget"][field]:
            raise ValueError(f"milestone loop transition budget {field} moves backwards")
    binding_changed = any(
        result[field] != current[field]
        for field in (
            "project_revision",
            "milestone_revision",
            "dependency_graph_hash",
            "human_verification_policy",
        )
    ) or set(old_tasks) != set(new_tasks)
    if binding_changed and result["approval"]["status"] != "approved":
        raise ValueError("milestone loop binding changes require approved preview")
    if target == "awaiting-approval" and result["approval"]["status"] != "pending":
        raise ValueError("awaiting-approval requires a pending preview")
    if target == "milestone-integrating" and result["approval"]["status"] != "approved":
        raise ValueError("milestone integration requires an approved exact preview")
    return result


def validate_role_handoff(
    payload: dict[str, Any],
    receipt_payload: dict[str, Any] | None = None,
    orchestration: str = "project",
) -> dict[str, Any]:
    if orchestration not in {"project", "milestone"}:
        raise ValueError("orchestration must be project or milestone")
    contract = (
        project_orchestration_contract()
        if orchestration == "project"
        else milestone_orchestration_contract()
    )
    policy_fields = (
        ["execution_policy", "workflow_hash"] if payload.get("schema_version") == 2 else []
    )
    handoff = _require_exact_object_fields(
        payload, [*contract["role_handoff"]["required_fields"], *policy_fields], "role handoff"
    )
    if handoff["schema_version"] not in {1, 2}:
        raise ValueError("role handoff schema_version is invalid")
    role = handoff["role"]
    if role not in contract["roles"]:
        raise ValueError(f"unknown {orchestration} orchestration role: {role}")
    if policy_fields:
        from ._routing_v1 import validate_task_policy

        if role not in {"task-executor", "task-verifier"}:
            raise ValueError("v2 task policy handoffs require a task role")
        task_policy = validate_task_policy(handoff["execution_policy"])
        validate_sha256(handoff["workflow_hash"], "workflow_hash")
        if role == "task-verifier" and not task_policy["review"]["required"]:
            raise ValueError(
                "TASK_POLICY_DRIFT: self-verifying work must not dispatch an independent verifier"
            )
    for field in ("handoff_id", "logical_role_id", "project_id"):
        _require_nonempty_text(handoff[field], field)
    _require_positive_revision(handoff["project_revision"], "project_revision")
    validate_sha256(handoff["source_hash"], "source_hash")
    validate_sha256(handoff["dependency_graph_hash"], "dependency_graph_hash")
    if handoff["previous_handoff_hash"] is not None:
        validate_sha256(handoff["previous_handoff_hash"], "previous_handoff_hash")
    parse_rfc3339(handoff["created_at"])
    if handoff["raw_transcript_included"] is not False:
        raise ValueError("ROLE_HANDOFF_INVALID: raw transcripts are prohibited")
    sections = handoff["context_sections"]
    role_policy = contract["roles"][role]
    if not isinstance(sections, list) or len(sections) != len(set(sections)):
        raise ValueError("role handoff context_sections must be a unique list")
    if not set(role_policy["required_context"]).issubset(sections):
        raise ValueError(f"role handoff for {role} is missing required context")
    if not set(sections).issubset(role_policy["allowed_context"]):
        raise ValueError(f"role handoff for {role} includes forbidden context")
    tokens = handoff["context_tokens"]
    if not isinstance(tokens, int) or isinstance(tokens, bool) or tokens < 0:
        raise ValueError("role handoff context_tokens must be a non-negative integer")
    from .context import check_capacity, effective_limit, enforce_measurement

    enforce_measurement(handoff, role_policy["max_input_tokens"])
    check_capacity(tokens)
    if tokens > effective_limit(role_policy["max_input_tokens"]):
        raise ValueError(
            f"CONTEXT_OVERFLOW for {role}: max_input_tokens={tokens} > "
            f"{role_policy['max_input_tokens']}"
        )

    if role == "project-orchestrator":
        for field in (
            "milestone_id",
            "milestone_revision",
            "task_id",
            "plan_revision",
            "source_revision",
            "repository_head",
            "attempt_id",
        ):
            if handoff[field] is not None:
                raise ValueError(f"project orchestrator handoff forbids {field}")
    elif role == "milestone-orchestrator":
        _require_nonempty_text(handoff["milestone_id"], "milestone_id")
        _require_positive_revision(handoff["milestone_revision"], "milestone_revision")
        for field in ("task_id", "plan_revision", "attempt_id"):
            if handoff[field] is not None:
                raise ValueError(f"milestone orchestrator handoff forbids {field}")
        _require_commit(handoff["repository_head"], "repository_head", allow_none=True)
    else:
        _require_nonempty_text(handoff["milestone_id"], "milestone_id")
        _require_positive_revision(handoff["milestone_revision"], "milestone_revision")
        _require_nonempty_text(handoff["task_id"], "task_id")
        _require_positive_revision(handoff["plan_revision"], "plan_revision")
        _require_positive_revision(handoff["source_revision"], "source_revision")
        _require_commit(handoff["repository_head"], "repository_head")
        _require_nonempty_text(handoff["attempt_id"], "attempt_id")
    if receipt_payload is not None:
        receipt = (
            validate_project_loop_receipt(receipt_payload)
            if orchestration == "project"
            else validate_milestone_loop_receipt(receipt_payload)
        )
        for handoff_field, receipt_field in (
            ("project_id", "project_id"),
            ("project_revision", "project_revision"),
            ("source_hash", "source_hash"),
            ("dependency_graph_hash", "dependency_graph_hash"),
        ):
            if handoff[handoff_field] != receipt[receipt_field]:
                raise ValueError(f"ROLE_HANDOFF_INVALID: {handoff_field} drift")
        if role == "project-orchestrator":
            expected_role_id = receipt["project_orchestrator_id"]
        elif role == "milestone-orchestrator":
            milestone: dict[str, Any] | None
            if orchestration == "milestone":
                milestone = {
                    "milestone_id": receipt["milestone_id"],
                    "milestone_revision": receipt["milestone_revision"],
                    "orchestrator_id": receipt["milestone_orchestrator_id"],
                }
            else:
                milestone = None
                for item in receipt["milestones"]:
                    if item["milestone_id"] == handoff["milestone_id"]:
                        milestone = item
                        break
            if milestone is None or milestone["milestone_id"] != handoff["milestone_id"]:
                raise ValueError("ROLE_HANDOFF_INVALID: unknown milestone binding")
            if handoff["milestone_revision"] != milestone["milestone_revision"]:
                raise ValueError("ROLE_HANDOFF_INVALID: milestone_revision drift")
            expected_role_id = milestone["orchestrator_id"]
        else:
            task = next(
                (item for item in receipt["task_loops"] if item["task_id"] == handoff["task_id"]),
                None,
            )
            if task is None:
                raise ValueError("ROLE_HANDOFF_INVALID: unknown task binding")
            if (
                handoff["milestone_id"] != task["milestone_id"]
                or handoff["plan_revision"] != task["plan_revision"]
            ):
                raise ValueError("ROLE_HANDOFF_INVALID: task binding drift")
            expected_role_id = (
                task["executor_id"] if role == "task-executor" else task["verifier_id"]
            )
        if handoff["logical_role_id"] != expected_role_id:
            raise ValueError("ROLE_HANDOFF_INVALID: logical role binding drift")
    return handoff


def validate_role_capability(
    payload: dict[str, Any], orchestration: str = "project"
) -> dict[str, Any]:
    execution_policy = payload.get("execution_policy")
    workflow_input = payload.get("workflow")
    payload = {
        key: value for key, value in payload.items() if key not in {"execution_policy", "workflow"}
    }
    request = _require_exact_object_fields(
        payload,
        [
            "role",
            "operation",
            "tracked_source_write",
            "worktree_path",
            "assigned_worktree",
            "comment_marker",
        ],
        "role capability request",
    )
    if orchestration not in {"project", "milestone"}:
        raise ValueError("orchestration must be project or milestone")
    contract = (
        project_orchestration_contract()
        if orchestration == "project"
        else milestone_orchestration_contract()
    )
    role = request["role"]
    if role not in contract["capabilities"]:
        raise ValueError(f"unknown {orchestration} orchestration role: {role}")
    capability = contract["capabilities"][role]
    operation = request["operation"]
    if (
        role == "task-executor"
        and operation == "write-verification-result-comment"
        and execution_policy is not None
    ):
        from ._routing_v1 import validate_task_policy

        policy = validate_task_policy(execution_policy)
        if policy["review"]["required"]:
            raise ValueError("ROLE_CAPABILITY_VIOLATION: this task requires independent review")
        capability = {
            **capability,
            "operations": [*capability["operations"], operation],
            "comment_marker": "linear-spanks:verification-result",
        }
    if operation not in capability["operations"]:
        raise ValueError(f"ROLE_CAPABILITY_VIOLATION: {role} cannot perform {operation}")
    if not isinstance(request["tracked_source_write"], bool):
        raise ValueError("tracked_source_write must be boolean")

    source_operations = {"edit-assigned-worktree", "commit-assigned-worktree"}
    if workflow_input is not None:
        from .runtime import task_next

        workflow = task_next(workflow_input)
        if execution_policy is not None and execution_policy != workflow["execution_policy"]:
            raise ValueError(
                "TASK_POLICY_DRIFT: capability policy must match current task workflow"
            )
        if operation in source_operations and workflow["next_action"] not in {
            "implement",
            "automatic-repair",
        }:
            raise ValueError(
                "ROLE_CAPABILITY_VIOLATION: diagnosis, refresh, review and blocked work cannot write source"
            )
    comment_operations = {"write-completion-handoff-comment", "write-verification-result-comment"}
    if operation in source_operations:
        if role != "task-executor" or request["tracked_source_write"] is not True:
            raise ValueError("ROLE_CAPABILITY_VIOLATION: source writes require task executor")
        worktree = Path(_require_nonempty_text(request["worktree_path"], "worktree_path"))
        assigned = Path(_require_nonempty_text(request["assigned_worktree"], "assigned_worktree"))
        if not worktree.is_absolute() or not assigned.is_absolute() or worktree != assigned:
            raise ValueError("ROLE_CAPABILITY_VIOLATION: executor must use assigned worktree")
        if request["comment_marker"] is not None:
            raise ValueError("source operation cannot include a comment marker")
    else:
        if request["tracked_source_write"] is not False:
            raise ValueError("ROLE_CAPABILITY_VIOLATION: operation forbids tracked source writes")
        if request["worktree_path"] is not None or request["assigned_worktree"] is not None:
            raise ValueError("non-source operation cannot claim a worktree write")
    if operation in comment_operations:
        if request["comment_marker"] != capability["comment_marker"]:
            raise ValueError("ROLE_CAPABILITY_VIOLATION: comment marker is invalid")
    elif request["comment_marker"] is not None:
        raise ValueError("non-comment operation cannot include a comment marker")
    return {"status": "allowed", "role": role, "operation": operation}


def validate_task_attempt(payload: dict[str, Any]) -> dict[str, Any]:
    progress = payload.get("progress")
    execution_policy = payload.get("execution_policy")
    verification = payload.get("verification")
    payload = {
        k: v
        for k, v in payload.items()
        if k not in {"progress", "execution_policy", "verification"}
    }
    contract = project_orchestration_contract()
    loop = contract["task_loop"]
    attempt = _require_exact_object_fields(payload, loop["attempt_fields"], "task attempt")
    if attempt["schema_version"] not in {1, 2}:
        raise ValueError("task attempt schema_version is invalid")
    policy = None
    if attempt["schema_version"] == 2:
        from ._routing_v1 import validate_task_policy

        if execution_policy is None or progress is None:
            raise ValueError("task attempt v2 requires execution policy and durable progress")
        policy = validate_task_policy(execution_policy)
    elif execution_policy is not None:
        raise ValueError("task policy requires a v2 attempt")
    for field in ("task_id", "task_loop_id", "attempt_id"):
        _require_nonempty_text(attempt[field], field)
    index = attempt["attempt_index"]
    if not isinstance(index, int) or isinstance(index, bool) or index < 0:
        raise ValueError("attempt_index must be a non-negative integer")
    if attempt["attempt_kind"] not in loop["attempt_kinds"]:
        raise ValueError("task attempt kind is invalid")
    if attempt["verification_result"] not in loop["verification_results"]:
        raise ValueError("task attempt verification result is invalid")
    _require_commit(attempt["candidate_commit"], "candidate_commit")
    expected_verifier = policy["review"]["strength"] if policy else "high"
    if attempt["verifier_strength"] != expected_verifier:
        raise ValueError(
            "task attempt verifier must match its execution policy (legacy: high verifier)"
        )

    if attempt["attempt_kind"] == "automatic":
        if index not in range(loop["max_automatic_executions"]):
            raise ValueError("automatic task attempt exceeds round three")
        round_policy = loop["automatic_rounds"][index]
        if attempt["executor_phase"] != round_policy["executor_phase"]:
            raise ValueError("automatic task attempt phase is invalid")
        expected_executor = policy["executor_strength"] if policy else "low"
        if attempt["executor_strength"] != expected_executor:
            raise ValueError("automatic task attempts must use the planned executor")
        if attempt["selected_model"] is not None or attempt["user_approved"] is not False:
            raise ValueError("automatic task attempts cannot bind user model selection")
        if index == 0 and attempt["previous_verification"] is not None:
            raise ValueError("initial implementation cannot have previous verification")
        if index > 0 and attempt["previous_verification"] != "failed":
            raise ValueError("automatic repair requires a failed previous verification")
    else:
        if index < loop["max_automatic_executions"]:
            raise ValueError("user-selected attempts start after automatic round three")
        if attempt["executor_phase"] != "repair":
            raise ValueError("user-selected executor attempt must be a repair")
        if attempt["previous_verification"] != "failed":
            raise ValueError("user-selected repair requires a failed verification")
        if attempt["user_approved"] is not True:
            raise ValueError("user-selected executor attempt requires approval")
        selected = _validate_selected_model(attempt["selected_model"])
        if attempt["executor_strength"] != selected["strength"]:
            raise ValueError("executor strength must match the selected model")

    result = attempt["verification_result"]
    if policy:
        assert progress is not None
        for item in progress["attempts"]:
            if item.get("executor_strength") not in {"low", "medium", "high"}:
                raise ValueError("v2 progress must retain executor strengths")
        if attempt["attempt_kind"] == "automatic" and any(
            item["executor_strength"] != attempt["executor_strength"]
            for item in progress["attempts"]
        ):
            raise ValueError(
                "MODEL_SELECTION_REQUIRED: automatic repair cannot change executor strength"
            )
        if result == "pending" and len(progress["attempts"]) != index:
            raise ValueError("pending task progress must preserve all consumed attempts")
        if result == "passed":
            if verification is None:
                raise ValueError("passing v2 attempt requires candidate verification evidence")
            validated = validate_verification_ledger(
                verification, expected_task_id=attempt["task_id"]
            )
            if (
                validated["final_result"] != "passed"
                or verification["candidate_commit"] != attempt["candidate_commit"]
            ):
                raise ValueError("passing task attempt must bind exact verified candidate")
    if result == "pending":
        next_action = "task-verify"
    elif result == "passed":
        next_action = "verified-pending-integration"
    elif attempt["attempt_kind"] == "automatic" and index < 3:
        next_action = "automatic-repair"
    else:
        next_action = "user-model-selection"
    if progress is not None and result != "pending":
        from .context import repair_action

        if len(progress["attempts"]) != index + 1 or progress["attempts"][-1]["result"] != result:
            raise ValueError("task progress must bind the current attempt and result")
        next_action = repair_action(progress)["next_action"]
    return {
        "status": "valid",
        "attempt": {
            **attempt,
            **(
                {"execution_policy": policy, "progress": progress, "verification": verification}
                if policy
                else {}
            ),
        },
        "next_action": next_action,
    }


def validate_model_escalation(payload: dict[str, Any]) -> dict[str, Any]:
    request = _require_exact_object_fields(
        payload,
        [
            "task_id",
            "automatic_attempts_completed",
            "automatic_failures",
            "previous_escalated_failure",
            "action",
            "selected_model",
            "user_approved",
        ],
        "model escalation request",
    )
    _require_nonempty_text(request["task_id"], "task_id")
    if request["automatic_attempts_completed"] != 4 or request["automatic_failures"] != 4:
        raise ValueError("MODEL_SELECTION_REQUIRED only after four failed automatic rounds")
    if not isinstance(request["previous_escalated_failure"], bool):
        raise ValueError("previous_escalated_failure must be boolean")
    if not isinstance(request["user_approved"], bool):
        raise ValueError("user_approved must be boolean")
    actions = project_orchestration_contract()["task_loop"]["user_actions"]
    if request["action"] not in actions:
        raise ValueError("model escalation action is invalid")

    first_run_actions = {"run-selected-model"}
    retry_actions = {"retry-selected-model", "select-another-stronger-model"}
    run_actions = first_run_actions | retry_actions
    if request["action"] in run_actions:
        if request["user_approved"] is not True:
            raise ValueError("selected model execution requires user approval")
        _validate_selected_model(request["selected_model"])
        if request["action"] in first_run_actions and request["previous_escalated_failure"] is True:
            raise ValueError("failed escalated repair requires retry or another model selection")
        if request["action"] in retry_actions and request["previous_escalated_failure"] is not True:
            raise ValueError("retry or another model selection requires an escalated failure")
        next_action = "user-selected-repair"
    elif request["action"] == "request-milestone-replan":
        if request["selected_model"] is not None or request["user_approved"] is not True:
            raise ValueError("milestone replan selection is invalid")
        next_action = "milestone-replan"
    elif request["action"] == "pause-task":
        if request["selected_model"] is not None or request["user_approved"] is not True:
            raise ValueError("pause task selection is invalid")
        next_action = "pause-task"
    else:
        if request["selected_model"] is not None or request["user_approved"] is not False:
            raise ValueError("model selection prompt cannot pre-approve a model")
        next_action = "user-model-selection"
    return {"status": "valid", "next_action": next_action}


def validate_verification_ledger(
    payload: dict[str, Any],
    expected_task_id: str | None = None,
    expected_verifier_id: str | None = None,
    expected_plan_revision: int | None = None,
) -> dict[str, Any]:
    contract = project_orchestration_contract()
    schema = contract["verification_ledger"]
    binding_fields = ["execution_binding"] if payload.get("schema_version") == 2 else []
    ledger = _require_exact_object_fields(
        payload, [*schema["required_fields"], *binding_fields], "verification ledger"
    )
    if ledger["schema_version"] not in {1, 2}:
        raise ValueError("verification ledger schema_version is invalid")
    if binding_fields:
        validate_sha256(ledger["execution_binding"], "execution_binding")
    for field in ("ledger_id", "task_id", "verifier_id"):
        _require_nonempty_text(ledger[field], field)
    for field in ("project_revision", "milestone_revision", "plan_revision", "source_revision"):
        _require_positive_revision(ledger[field], field)
    if expected_task_id is not None and ledger["task_id"] != expected_task_id:
        raise ValueError("verification ledger task drift")
    if expected_verifier_id is not None and ledger["verifier_id"] != expected_verifier_id:
        raise ValueError("verification ledger verifier drift")
    if expected_plan_revision is not None and ledger["plan_revision"] != expected_plan_revision:
        raise ValueError("verification ledger plan drift")
    candidate_commit = _require_commit(ledger["candidate_commit"], "candidate_commit")
    if ledger["raw_executor_transcript_included"] is not False:
        raise ValueError("verification ledger cannot contain raw executor transcripts")
    if not isinstance(ledger["required_verification_current"], bool):
        raise ValueError("required_verification_current must be boolean")
    if ledger["final_result"] not in schema["final_results"]:
        raise ValueError("verification ledger final_result is invalid")
    parse_rfc3339(ledger["updated_at"])

    attempts = ledger["reviewed_attempts"]
    if not isinstance(attempts, list) or not attempts:
        raise ValueError("verification ledger requires reviewed attempts")
    attempt_ids: set[str] = set()
    attempt_indexes: set[int] = set()
    for index, raw in enumerate(attempts):
        attempt = _require_exact_object_fields(
            raw,
            ["attempt_id", "attempt_index", "commit", "result", "reviewed_at"],
            f"reviewed_attempts[{index}]",
        )
        attempt_id = _require_nonempty_text(attempt["attempt_id"], "attempt_id")
        attempt_index = attempt["attempt_index"]
        if (
            not isinstance(attempt_index, int)
            or isinstance(attempt_index, bool)
            or attempt_index < 0
        ):
            raise ValueError("reviewed attempt index must be non-negative")
        if attempt_id in attempt_ids or attempt_index in attempt_indexes:
            raise ValueError("verification ledger reviewed attempts must be unique")
        attempt_ids.add(attempt_id)
        attempt_indexes.add(attempt_index)
        _require_commit(attempt["commit"], "reviewed attempt commit")
        if attempt["result"] not in schema["verification_statuses"]:
            raise ValueError("reviewed attempt result is invalid")
        parse_rfc3339(attempt["reviewed_at"])
    if [attempt["attempt_index"] for attempt in attempts] != sorted(attempt_indexes):
        raise ValueError("verification ledger reviewed attempts must be ordered")

    criteria = ledger["acceptance_criteria"]
    if not isinstance(criteria, list) or not criteria:
        raise ValueError("verification ledger requires acceptance criteria")
    criterion_ids: set[str] = set()
    for index, raw in enumerate(criteria):
        criterion = _require_exact_object_fields(
            raw,
            ["criterion_id", "status", "evidence", "last_checked_commit"],
            f"acceptance_criteria[{index}]",
        )
        criterion_id = _require_nonempty_text(criterion["criterion_id"], "criterion_id")
        if criterion_id in criterion_ids:
            raise ValueError(f"duplicate acceptance criterion: {criterion_id}")
        criterion_ids.add(criterion_id)
        if criterion["status"] not in schema["acceptance_states"]:
            raise ValueError("acceptance criterion state is invalid")
        if not isinstance(criterion["evidence"], str):
            raise ValueError("acceptance criterion evidence must be text")
        _require_commit(criterion["last_checked_commit"], "last_checked_commit", allow_none=True)

    findings = ledger["findings"]
    if not isinstance(findings, list):
        raise ValueError("verification ledger findings must be a list")
    finding_ids: set[str] = set()
    for index, raw in enumerate(findings):
        classification_fields = (
            ["classification", "requirement"] if ledger["schema_version"] == 2 else []
        )
        finding = _require_exact_object_fields(
            raw,
            [
                "finding_id",
                "status",
                "summary",
                "introduced_commit",
                "resolved_commit",
                "evidence",
                *classification_fields,
            ],
            f"findings[{index}]",
        )
        finding_id = _require_nonempty_text(finding["finding_id"], "finding_id")
        if finding_id in finding_ids:
            raise ValueError(f"duplicate verification finding: {finding_id}")
        finding_ids.add(finding_id)
        if finding["status"] not in schema["finding_states"]:
            raise ValueError("verification finding state is invalid")
        if classification_fields:
            if finding["classification"] not in {"blocking", "suggestion"}:
                raise ValueError("verification finding classification is invalid")
            _require_nonempty_text(finding["evidence"], "finding evidence")
            if finding["classification"] == "blocking":
                _require_nonempty_text(finding["requirement"], "blocking finding requirement")
            elif finding["requirement"] is not None:
                raise ValueError("a requirement violation must be classified as blocking")
        _require_nonempty_text(finding["summary"], "finding summary")
        _require_commit(finding["introduced_commit"], "introduced_commit")
        _require_commit(finding["resolved_commit"], "resolved_commit", allow_none=True)
        if not isinstance(finding["evidence"], str):
            raise ValueError("verification finding evidence must be text")
        if finding["status"] == "resolved" and finding["resolved_commit"] is None:
            raise ValueError("resolved finding requires resolved_commit")
        if finding["status"] != "resolved" and finding["resolved_commit"] is not None:
            raise ValueError("open or regressed finding cannot have resolved_commit")

    runs = ledger["verification_runs"]
    if not isinstance(runs, list) or not runs:
        raise ValueError("verification ledger requires verification runs")
    for index, raw in enumerate(runs):
        run = _require_exact_object_fields(
            raw,
            ["command", "status", "summary", "artifact", "commit"],
            f"verification_runs[{index}]",
        )
        _require_nonempty_text(run["command"], "verification command")
        if run["status"] not in schema["verification_statuses"]:
            raise ValueError("verification run status is invalid")
        if (
            not isinstance(run["summary"], str)
            or len(run["summary"]) > schema["max_raw_log_characters"]
        ):
            raise ValueError("verification run summary exceeds the raw log ceiling")
        if run["artifact"] is not None and not isinstance(run["artifact"], str):
            raise ValueError("verification run artifact must be text or null")
        _require_commit(run["commit"], "verification run commit")

    for field in ("baseline_failures", "exclusions", "next_checks"):
        values = ledger[field]
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise ValueError(f"verification ledger {field} must be a text list")
    live = _require_exact_object_fields(
        ledger["live_session"],
        ["session_id", "status", "context_tokens"],
        "verification live session",
    )
    if live["status"] not in schema["live_session_states"]:
        raise ValueError("verification live session state is invalid")
    if live["session_id"] is not None and not isinstance(live["session_id"], str):
        raise ValueError("verification live session id must be text or null")
    if live["status"] == "active" and not live["session_id"]:
        raise ValueError("active verification session requires a session id")
    if live["status"] == "unavailable" and live["session_id"] is not None:
        raise ValueError("unavailable verification session cannot retain a session id")
    if (
        not isinstance(live["context_tokens"], int)
        or isinstance(live["context_tokens"], bool)
        or live["context_tokens"] < 0
    ):
        raise ValueError("verification live session context_tokens must be non-negative")
    from .context import check_capacity, effective_limit, enforce_measurement

    verifier_limit = effective_limit(contract["roles"]["task-verifier"]["max_input_tokens"])
    enforce_measurement(ledger, verifier_limit)
    check_capacity(live["context_tokens"])
    if live["context_tokens"] > verifier_limit:
        raise ValueError(
            f"CONTEXT_OVERFLOW for task-verifier: max_input_tokens="
            f"{live['context_tokens']} > {verifier_limit}"
        )

    if ledger["final_result"] == "passed":
        if any(criterion["status"] != "passing" for criterion in criteria):
            raise ValueError("passing verification requires all acceptance criteria passing")
        if any(
            finding.get("classification", "blocking") == "blocking"
            and finding["status"] in {"open", "regressed"}
            for finding in findings
        ):
            raise ValueError("passing verification cannot retain open findings")
        if attempts[-1]["commit"] != candidate_commit or attempts[-1]["result"] != "passed":
            raise ValueError("passing verification must review the exact candidate commit")
        if any(criterion["last_checked_commit"] != candidate_commit for criterion in criteria):
            raise ValueError("passing acceptance criteria must check the exact candidate commit")
        if any(run["commit"] != candidate_commit or run["status"] != "passed" for run in runs):
            raise ValueError("passing verification runs must pass on the exact candidate commit")
        if ledger["required_verification_current"] is not True:
            raise ValueError("passing verification requires current required verification")
    if ledger["final_result"] == "failed" and not (
        any(criterion["status"] in {"failing", "regressed"} for criterion in criteria)
        or any(
            finding.get("classification", "blocking") == "blocking"
            and finding["status"] in {"open", "regressed"}
            for finding in findings
        )
        or any(run["status"] == "failed" for run in runs)
    ):
        raise ValueError("failed verification requires failing evidence")
    return {
        "status": "valid",
        "task_id": ledger["task_id"],
        "verifier_id": ledger["verifier_id"],
        "final_result": ledger["final_result"],
        "reviewed_attempts": len(attempts),
    }


def transition_project_loop_receipt(
    receipt: dict[str, Any], request: dict[str, Any]
) -> dict[str, Any]:
    current = validate_project_loop_receipt(receipt)
    schema = project_orchestration_contract()["project_loop_receipt"]
    transition = _require_exact_object_fields(
        request,
        schema["transition_request_fields"],
        "project loop transition request",
    )
    if transition["current_project_revision"] != current["project_revision"]:
        raise ValueError("PROJECT_ORCHESTRATION_DRIFT: project_revision")
    for field, current_field in (
        ("current_source_hash", "source_hash"),
        ("current_dependency_graph_hash", "dependency_graph_hash"),
    ):
        validate_sha256(transition[field], field)
        if current_field != "source_hash" and transition[field] != current[current_field]:
            raise ValueError(f"PROJECT_ORCHESTRATION_DRIFT: {current_field}")
    for field, current_field in (
        ("current_milestones", "milestones"),
        ("current_human_verification_policies", "human_verification_policies"),
        ("current_task_loops", "task_loops"),
    ):
        if transition[field] != current[current_field]:
            raise ValueError(f"PROJECT_ORCHESTRATION_DRIFT: {current_field}")
    if transition["completed_event"] != current["next_event"]:
        raise ValueError("PROJECT_ORCHESTRATION_DRIFT: next_event")
    next_project_revision = _require_positive_revision(
        transition["next_project_revision"], "next_project_revision"
    )
    if next_project_revision < current["project_revision"]:
        raise ValueError("project loop next_project_revision moves backwards")
    for field in ("next_source_hash", "next_dependency_graph_hash"):
        validate_sha256(transition[field], field)
    target = transition["target_state"]
    allowed = project_orchestration_contract()["project_loop_receipt"]["transitions"][
        current["state"]
    ]
    if target not in allowed:
        raise ValueError(f"invalid project loop transition: {current['state']} -> {target}")
    events = project_orchestration_contract()["event_selection"]["events"]
    if transition["next_event"] is not None and transition["next_event"] not in events:
        raise ValueError("project loop transition next_event is invalid")
    updated_at = parse_rfc3339(transition["updated_at"])
    if updated_at < parse_rfc3339(current["updated_at"]):
        raise ValueError("project loop transition updated_at moves backwards")
    result = json.loads(json.dumps(current))
    result["project_revision"] = next_project_revision
    result["source_hash"] = transition["next_source_hash"]
    result["dependency_graph_hash"] = transition["next_dependency_graph_hash"]
    result["milestones"] = transition["next_milestones"]
    result["human_verification_policies"] = transition["next_human_verification_policies"]
    result["task_loops"] = transition["next_task_loops"]
    result["budget"] = transition["next_budget"]
    result["state"] = target
    result["current_event"] = transition["completed_event"]
    result["next_event"] = transition["next_event"]
    result["approval"] = transition["approval"]
    result["failure"] = transition["failure"]
    result["updated_at"] = transition["updated_at"]
    result["state_timestamps"][target] = transition["updated_at"]
    result = validate_project_loop_receipt(result)

    old_milestones = {
        item["milestone_id"]: item["orchestrator_id"] for item in current["milestones"]
    }
    new_milestones = {
        item["milestone_id"]: item["orchestrator_id"] for item in result["milestones"]
    }
    for milestone_id, orchestrator_id in old_milestones.items():
        if new_milestones.get(milestone_id) != orchestrator_id:
            raise ValueError(
                f"project loop transition changed milestone orchestrator: {milestone_id}"
            )
    old_tasks = {
        item["task_id"]: (item["executor_id"], item["verifier_id"])
        for item in current["task_loops"]
    }
    new_tasks = {
        item["task_id"]: (item["executor_id"], item["verifier_id"]) for item in result["task_loops"]
    }
    for task_id, role_ids in old_tasks.items():
        if new_tasks.get(task_id) != role_ids:
            raise ValueError(f"project loop transition changed task role binding: {task_id}")
    for field in schema["budget_fields"]:
        if result["budget"][field] < current["budget"][field]:
            raise ValueError(f"project loop transition budget {field} moves backwards")

    binding_changed = (
        result["project_revision"] != current["project_revision"]
        or result["dependency_graph_hash"] != current["dependency_graph_hash"]
        or result["human_verification_policies"] != current["human_verification_policies"]
        or set(new_milestones) != set(old_milestones)
        or set(new_tasks) != set(old_tasks)
    )
    if binding_changed and result["approval"]["status"] != "approved":
        raise ValueError("project loop binding changes require approved preview")
    if target == "awaiting-approval" and result["approval"]["status"] != "pending":
        raise ValueError("awaiting-approval requires a pending preview")
    if target == "milestone-integrating" and result["approval"]["status"] != "approved":
        raise ValueError("milestone integration requires an approved exact preview")
    return result


def project_role_card(role: str) -> dict[str, Any]:
    contract = project_orchestration_contract()
    if role not in contract["roles"]:
        raise ValueError(f"unknown project orchestration role: {role}")
    card = {
        "role": role,
        "topology": contract["topology"],
        "policy": contract["roles"][role],
        "capabilities": contract["capabilities"][role],
        "handoff": contract["role_handoff"],
        "session_boundary": contract["session_boundary"],
    }
    if role == "task-executor":
        card["task_loop"] = contract["task_loop"]
    if role == "task-verifier":
        card["verification_ledger"] = contract["verification_ledger"]
    return card


def milestone_role_card(role: str) -> dict[str, Any]:
    contract = milestone_orchestration_contract()
    if role not in contract["roles"]:
        raise ValueError(f"unknown milestone orchestration role: {role}")
    card = {
        "role": role,
        "topology": contract["topology"],
        "policy": contract["roles"][role],
        "capabilities": contract["capabilities"][role],
        "handoff": contract["role_handoff"],
        "session_boundary": contract["session_boundary"],
    }
    if role == "task-executor":
        card["task_loop"] = contract["task_loop"]
    if role == "task-verifier":
        card["verification_ledger"] = contract["verification_ledger"]
    return card
