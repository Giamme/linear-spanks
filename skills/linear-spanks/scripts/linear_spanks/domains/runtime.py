"""Milestone runtime projection, policy, and guarded loop domain."""

from __future__ import annotations

from typing import Any

from . import _runtime_v1 as legacy
from ._validation import checked


def task_next(payload: dict[str, Any]) -> dict[str, Any]:
    """Compile one bounded task action from authoritative evidence, without writes.

    Used by standalone dispatch, parent event projections and inspection. Model work
    starts only after this decision; refresh/plan actions remain inside the current run.
    """
    import re

    from ..core.hashing import sha256_digest
    from . import context, execution, isolation, orchestration, reviews, routing

    if payload.get("schema_version") != 1:
        raise ValueError("task workflow requires schema_version 1")
    task_id = payload["task_id"]
    candidate = payload["candidate_commit"]
    if (
        not isinstance(task_id, str)
        or not task_id
        or not isinstance(candidate, str)
        or not re.fullmatch(r"[0-9a-f]{40}", candidate)
    ):
        raise ValueError("task workflow requires task identity and exact candidate commit")
    if not isinstance(payload["approval_satisfied"], bool) or not isinstance(
        payload["blockers"], list
    ):
        raise ValueError("task workflow requires approval state and blockers")
    context.enforce_measurement(payload, 12000)
    roles = payload["roles"]
    if (
        not isinstance(roles, dict)
        or set(roles) != {"executor", "verifier"}
        or not all(isinstance(value, str) and value for value in roles.values())
    ):
        raise ValueError("task workflow requires bound executor and verifier identities")
    decision_input = dict(payload["decision"])
    if decision_input["command"] not in {"run-task", "implement-next", "verify-task"}:
        raise ValueError("TASK_COMMAND_MISMATCH: planning commands never enter task execution")
    verify_only = decision_input["command"] == "verify-task"
    integration_required = payload.get("integration_required", True)
    if not isinstance(integration_required, bool):
        raise ValueError("integration_required must come from the resolved Git strategy")
    drift_input = payload.get("plan_drift")
    bindings = None
    refresh_verified = False
    if drift_input is not None:
        drift = reviews.classify_drift(drift_input)
        current = drift_input["current"]
        if current["task_id"] != task_id:
            raise ValueError("TASK_WORKFLOW_DRIFT: plan belongs to another task")
        bindings = reviews.evidence_bindings(current)
        if reviews.evidence_bindings(drift_input["plan"])["material"] != bindings["material"]:
            drift = {**drift, "classification": "material"}
        refresh = payload.get("refresh")
        if refresh is not None:
            receipt = refresh["receipt"]
            refresh_verified = (
                refresh.get("read_back") is True
                and receipt["task_id"] == task_id
                and receipt["bindings"] == bindings
                and receipt["source_hash"] == sha256_digest(drift_input)
            )
        decision_input["detected_drift"] = (
            "valid"
            if drift["classification"] == "safe-refresh" and refresh_verified
            else drift["classification"]
        )
        decision_input["current_plan"] = {
            "present": True,
            "stale": drift["classification"] == "material",
            "revision": str(current["plan_revision"]),
        }
    else:
        decision_input["current_plan"] = {"present": False, "stale": False, "revision": None}
    decision = routing.decide(decision_input)
    if decision["review"]["required"] and roles["executor"] == roles["verifier"]:
        raise ValueError(
            "TASK_POLICY_DRIFT: independent review requires a separate reviewer identity"
        )
    progress = context.repair_action(payload["progress"])
    observations = payload["observations"]
    if not isinstance(observations, dict):
        raise ValueError("observations must be independently bound entries")
    reuse = {}
    for name, observation in observations.items():
        reuse[name] = context.reuse_analysis(observation)
    verification_commands = payload["verification_commands"]
    if (
        not isinstance(verification_commands, list)
        or not verification_commands
        or not all(
            isinstance(command, str) and command.strip() for command in verification_commands
        )
    ):
        raise ValueError("task workflow requires the current required verification commands")
    verification_binding = sha256_digest(
        {
            "task_id": task_id,
            "candidate_commit": candidate,
            "plan": bindings,
            "policy": decision["execution_policy"]["policy_hash"],
            "observations": {
                name: observation["current"] for name, observation in observations.items()
            },
            "verification_commands": verification_commands,
        }
    )
    action = (
        "verify"
        if progress["next_action"] == "verified-pending-integration"
        else progress["next_action"]
    )
    candidate_ready = payload.get("candidate_ready", False)
    if not isinstance(candidate_ready, bool):
        raise ValueError("candidate_ready must be a boolean bound to the completion handoff")
    if candidate_ready and action in {"implement", "automatic-repair"}:
        action = "verify"
    if verify_only and action in {"implement", "automatic-repair", "diagnose"}:
        action = "verify"
    selection = payload.get("model_selection")
    if action == "user-model-selection" and selection is not None:
        attempts = payload["progress"]["attempts"]
        if (
            not isinstance(selection, dict)
            or set(selection) != {"attempt_index", "request"}
            or selection["attempt_index"] != len(attempts)
            or selection["request"]["task_id"] != task_id
            or selection["request"]["previous_escalated_failure"] != (len(attempts) > 4)
            or any(attempt["result"] != "failed" for attempt in attempts)
        ):
            raise ValueError(
                "MODEL_SELECTION_DRIFT: bind new approval to the current consumed attempt count"
            )
        selected_action = orchestration.validate_escalation(selection["request"])["next_action"]
        action = (
            "blocked"
            if selected_action == "pause-task"
            else "replan"
            if selected_action == "milestone-replan"
            else selected_action
        )
    verification = payload.get("verification")
    if (
        verification is not None
        and drift_input is not None
        and decision_input["detected_drift"] == "valid"
    ):
        result = orchestration.validate_ledger(
            verification,
            expected_task_id=task_id,
            expected_plan_revision=drift_input["current"]["plan_revision"],
        )
        permitted = {roles["verifier"]} if decision["review"]["required"] else set(roles.values())
        if verification["verifier_id"] not in permitted:
            raise ValueError("TASK_POLICY_DRIFT: verification must come from the bound review role")
        if (
            verification["candidate_commit"] == candidate
            and result["final_result"] == "passed"
            and (
                verification.get("execution_binding") != verification_binding
                or not set(verification_commands)
                <= {run["command"] for run in verification["verification_runs"]}
            )
        ):
            action = "verify"
        elif verification["candidate_commit"] == candidate and result["final_result"] == "passed":
            action = "verified-pending-integration" if integration_required else "finalize-task"
            integration = payload.get("integration")
            if integration is not None:
                integrated = isolation.validate_receipt(integration)
                if (
                    integrated["issue_id"] != task_id
                    or integrated["child_commit"] != candidate
                    or integrated["plan_revision"] != verification["plan_revision"]
                ):
                    raise ValueError(
                        "TASK_WORKFLOW_DRIFT: integration does not bind the verified candidate"
                    )
                if integrated["state"] == "integrated":
                    action = "completed"
            if not integration_required and payload.get("completion") is not None:
                completed = execution.validate_completion_receipt(payload["completion"]).get(
                    "task_completion"
                )
                if (
                    completed is None
                    or completed["task_id"] != task_id
                    or completed["candidate_commit"] != candidate
                    or bindings is None
                    or completed["material_binding"] != bindings["material"]
                    or completed["policy_hash"] != decision["execution_policy"]["policy_hash"]
                ):
                    raise ValueError(
                        "TASK_WORKFLOW_DRIFT: completion does not bind the verified task"
                    )
                action = "completed"
    if not payload["approval_satisfied"]:
        action = "await-approval"
    elif payload["blockers"]:
        action = "blocked"
    elif decision["stop_result"] or (
        drift_input is not None and drift["classification"] == "material"
    ):
        action = "replan"
    elif drift_input is None:
        action = "blocked" if verify_only else "record-plan"
    elif decision["next_action"] == "refresh-evidence":
        action = "refresh-evidence"
    executable = action in {
        "implement",
        "automatic-repair",
        "user-selected-repair",
        "verify",
        "diagnose",
    }
    routes = decision["routes"] if executable else []
    if action in {"record-plan", "replan"}:
        routes = [route for route in decision["routes"] if route["role"] == "planner"]
    if action == "verify":
        role = "reviewer" if decision["review"]["required"] else "executor"
        routes = [route for route in routes if route["role"] == role]
    if action in {"implement", "automatic-repair", "diagnose"}:
        routes = [route for route in routes if route["role"] != "reviewer"]
    if action == "user-selected-repair":
        assert selection is not None
        model = selection["request"]["selected_model"]
        routes = [
            routing.check(
                model["harness"],
                "executor",
                model["strength"],
                model["model"],
                decision["effective_assurance"],
            )
        ]
    body = {
        "schema_version": 1,
        "task_id": task_id,
        "candidate_commit": candidate,
        "bindings": bindings,
        "execution_policy": decision["execution_policy"],
        "verification_binding": verification_binding,
        "roles": roles,
        "model_selection_hash": sha256_digest(selection) if selection is not None else None,
        "next_action": action,
        "dispatch_ready": executable,
        "planner_runs": decision["planner"]["runs"] if action in {"record-plan", "replan"} else 0,
        "reviewer_runs": int(action == "verify" and decision["review"]["required"]),
        "routes": routes,
        "reuse": reuse,
        "progress": progress,
        "stale_evidence": [name for name, result in reuse.items() if not result["reusable"]],
        "refresh_verified": refresh_verified,
        "review_scope": "affected-acceptance-and-changed-areas"
        if payload["progress"]["attempts"]
        else "final-task-diff",
        "required_verification": ["actual-candidate", "integrated-result"],
        "completion_steps": ["focused-checks", "final-self-review"]
        if action in {"implement", "automatic-repair", "user-selected-repair", "verify"}
        and not decision["review"]["required"]
        else ["required-independent-review"]
        if action == "verify"
        else [],
    }
    return {**body, "workflow_hash": sha256_digest(body)}


def validate_projection(payload: dict[str, Any]) -> dict[str, Any]:
    return checked(legacy.validate_milestone_runtime, payload)


def validate_storage(payload: dict[str, Any]) -> dict[str, Any]:
    return checked(legacy.reconcile_milestone_runtime_storage, payload)


def migrate_projection(payload: dict[str, Any]) -> dict[str, Any]:
    return checked(legacy.migrate_milestone_runtime_projection, payload)


def validate_policy(payload: dict[str, Any]) -> dict[str, Any]:
    return checked(legacy.validate_autopilot_policy, payload)


def validate_policy_binding(payload: dict[str, Any]) -> dict[str, Any]:
    return checked(legacy.validate_guarded_autopilot_binding, payload)


def resolve_mode(payload: dict[str, Any]) -> dict[str, Any]:
    return checked(legacy.resolve_milestone_run_mode, payload)


def validate_loop(payload: dict[str, Any]) -> dict[str, Any]:
    return checked(legacy.validate_autopilot_loop, payload)


def inspect(payload: dict[str, Any]) -> dict[str, Any]:
    """Read-only projection using the same selectors that drive execution."""
    from . import context, orchestration

    scope = payload["scope"]
    if scope == "project":
        event = orchestration.project_next(payload["event_input"])
    elif scope == "milestone":
        event = orchestration.milestone_next(payload["event_input"])
    elif scope == "task":
        event = (
            task_next(payload["event_input"])
            if "decision" in payload["event_input"]
            else context.repair_action(payload["event_input"])
        )
    else:
        raise ValueError("runtime inspect scope must be project, milestone or task")
    action = event.get("next_action", event.get("event"))
    next_command: str | None = f"{scope} run {payload['target']}"
    if action == "replan":
        next_command = f"task replan {payload['target']}"
    elif action in {
        "await-approval",
        "await-human-verification",
        "blocked",
        "project-complete",
        "milestone-complete",
        "user-model-selection",
        "prerequisite-recovery",
        "verified-pending-integration",
        "completed",
    }:
        next_command = None
    return {
        "active_scope": scope,
        "target": payload["target"],
        "next_event": event,
        "next_command": next_command,
        "blockers": payload["event_input"].get("blockers", payload.get("blockers", [])),
        "approval_state": (
            "satisfied" if payload["event_input"]["approval_satisfied"] else "required"
        )
        if "approval_satisfied" in payload["event_input"]
        else payload.get("approval_state", "unknown"),
        "execution_path": event.get("execution_policy", {}).get("execution_path"),
        "review_requirement": event.get("execution_policy", {}).get("review"),
        "analysis_reuse": event.get("reuse", {}),
        "stale_evidence": event.get("stale_evidence", payload.get("stale_evidence", [])),
        "context": context.inspect_context(payload["context"]),
        "unavailable_capabilities": payload.get("unavailable_capabilities", []),
    }
