from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "linear-spanks"
COMMANDS = json.loads((SKILL / "commands.json").read_text(encoding="utf-8"))
WORKFLOW = json.loads((SKILL / "workflow-contract.json").read_text(encoding="utf-8"))
ISSUE_WORKFLOW = json.loads((SKILL / "issue-workflow-contract.json").read_text(encoding="utf-8"))
EXECUTION = json.loads((SKILL / "execution-contract.json").read_text(encoding="utf-8"))
ROUTING = json.loads((SKILL / "routing-contract.json").read_text(encoding="utf-8"))
REPOSITORY_SCAN = json.loads((SKILL / "repository-scan-contract.json").read_text(encoding="utf-8"))
PROJECT_EPOCH = json.loads((SKILL / "project-epoch-contract.json").read_text(encoding="utf-8"))
PARALLEL_EXECUTION = json.loads(
    (SKILL / "parallel-execution-contract.json").read_text(encoding="utf-8")
)
PROJECT_ORCHESTRATION = json.loads(
    (SKILL / "project-orchestration-contract.json").read_text(encoding="utf-8")
)
MILESTONE_ORCHESTRATION = json.loads(
    (SKILL / "milestone-orchestration-contract.json").read_text(encoding="utf-8")
)
HUMAN_VERIFICATION = json.loads(
    (SKILL / "human-verification-contract.json").read_text(encoding="utf-8")
)
MILESTONE_REVIEW = json.loads(
    (SKILL / "milestone-review-contract.json").read_text(encoding="utf-8")
)
MILESTONE_RUNTIME = json.loads(
    (SKILL / "milestone-runtime-contract.json").read_text(encoding="utf-8")
)
ASSESSMENT_FIXTURES = json.loads(
    (ROOT / "tests" / "fixtures" / "routing-assessments.json").read_text(encoding="utf-8")
)
STARTUP_FIXTURE = json.loads(
    (ROOT / "tests" / "fixtures" / "assurance-startup-baseline.json").read_text(encoding="utf-8")
)
CONTRACT_SCRIPT = SKILL / "scripts" / "workflow_contract.py"
CATALOG_SCRIPT = SKILL / "scripts" / "generate_command_catalog.py"
SCRIPTS = SKILL / "scripts"
sys.path.insert(0, str(SCRIPTS))

from linear_spanks.cli import internal
from linear_spanks.compat import v1_runtime as v1_runtime
from linear_spanks.contracts.legacy import command_by_name
from linear_spanks.contracts.registry import get_contract_set
from linear_spanks.core.errors import LinearSpanksError
from linear_spanks.domains.execution import execution_brief, execution_envelope, task_runtime_card
from linear_spanks.domains.legacy_validation import validate_contracts

_LEGACY_INTERNAL_ROUTES = {
    legacy_action: (namespace, operation)
    for namespace, operations in internal.INTERNAL_OPERATIONS.items()
    for operation, legacy_action in operations.items()
}


def _namespaced_operand(name: str, *, mode_option: str) -> tuple[str, ...] | None:
    command = get_contract_set().by_legacy_name.get(name)
    if command is None:
        return None
    tokens = (command.namespace, command.name)
    if name == "run-milestone-loop":
        tokens += (mode_option, "loop")
    return tokens


def _characterization_arguments(
    route: tuple[str, str], arguments: tuple[str, ...]
) -> tuple[str, ...]:
    namespace, operation = route
    if (
        (namespace == "context" and operation in {"check", "packet"})
        or (namespace == "state" and operation == "issue-transition")
    ) and arguments:
        operand = _namespaced_operand(arguments[0], mode_option="--mode")
        return (*operand, *arguments[1:]) if operand is not None else arguments

    option = None
    if namespace == "state" and operation in {"advance", "idempotency-key"}:
        option = "--command"
    elif namespace == "state" and operation == "marker":
        option = "--last-command"
    if option is None or option not in arguments:
        return arguments
    index = arguments.index(option)
    if index + 1 >= len(arguments):
        return arguments
    operand = _namespaced_operand(arguments[index + 1], mode_option="--command-mode")
    if operand is None:
        return arguments
    return (*arguments[: index + 1], *operand, *arguments[index + 2 :])


def profile_limit(name: str) -> int:
    """Read a context profile's token ceiling from the execution contract.

    Tests assert overflow behaviour, not a particular budget. Deriving the limit keeps them
    honest when a profile is deliberately re-sized.
    """

    contract = json.loads(
        (SKILL / "execution-contract.json").read_text(encoding="utf-8")
    )
    limit = contract["context_profiles"][name]["max_input_tokens"]
    assert isinstance(limit, int)
    return limit


def run_contract(*args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    """Exercise frozen v1 inputs through the owned v2 domain implementations.

    This is the v1 characterization edge. Its ``execution-brief`` / ``execution-envelope``
    results come from the legacy compiler, so assertions here do NOT cover what the shipping
    v2 command path compiles. Reference sets, postconditions and policy slices for the public
    surface are locked in ``tests/test_v2_reference_contract.py``.

    The compatibility parser remains characterization-only. Every operation body is
    dispatched through the namespaced v2 edge or called directly for the four
    contract-inspection operations that intentionally have a different public v2
    grammar.
    """

    stdout = io.StringIO()
    stderr = io.StringIO()
    return_code = 0
    try:
        if not args:
            raise ValueError("an internal operation is required")
        action, *arguments = args
        if action in {
            "command",
            "execution-envelope",
            "execution-brief",
            "runtime-card",
            "validate-contracts",
        }:
            parsed = internal.build_internal_parser().parse_args(args)
            if action == "command":
                result: Any = command_by_name(parsed.name)
            elif action == "execution-envelope":
                result = execution_envelope(
                    parsed.name,
                    parsed.scan,
                    parsed.assurance,
                    parsed.isolated_worktree,
                    parsed.milestone_stage,
                )
            elif action == "execution-brief":
                result = execution_brief(
                    parsed.name,
                    parsed.assurance,
                    parsed.scan,
                    parsed.isolated_worktree,
                    parsed.milestone_stage,
                )
            elif action == "runtime-card":
                result = task_runtime_card(
                    parsed.name,
                    parsed.isolated_worktree,
                    parsed.milestone_stage,
                )
            else:
                result = validate_contracts()
        else:
            route = _LEGACY_INTERNAL_ROUTES.get(action)
            if route is None:
                raise ValueError(f"unknown internal operation: {action}")
            translated_arguments = _characterization_arguments(route, tuple(arguments))
            result = internal.run_internal(
                route[0],
                route[1],
                translated_arguments,
                io.StringIO(input_text or ""),
            )
        if isinstance(result, str):
            stdout.write(result)
            if not result.endswith("\n"):
                stdout.write("\n")
        else:
            stdout.write(json.dumps(result, sort_keys=True))
            stdout.write("\n")
    except (
        LinearSpanksError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
    ) as error:
        message = error.message if isinstance(error, LinearSpanksError) else str(error)
        stderr.write(f"workflow contract error: {message}\n")
        return_code = 2
    return subprocess.CompletedProcess(
        [sys.executable, str(CONTRACT_SCRIPT), *args],
        return_code,
        stdout.getvalue(),
        stderr.getvalue(),
    )


def human_policy_binding(
    effective: str = "disabled",
    source: str = "system-default",
    project_revision: int = 0,
    override_revision: int = 0,
) -> dict[str, Any]:
    policy = {
        "schema_version": 1,
        "project_id": "project-1",
        "milestone_id": "milestone-1",
        "effective": effective,
        "source": source,
        "project_policy_revision": project_revision,
        "milestone_override_revision": override_revision,
    }
    encoded = json.dumps(policy, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    policy["policy_hash"] = "sha256:" + hashlib.sha256(encoded).hexdigest()
    policy.pop("schema_version")
    return policy


def canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def state_marker_fixture() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "project_id": "project-1",
        "milestone_id": "milestone-1",
        "stage": "clarified",
        "revision": 1,
        "last_command": "clarify-milestone",
        "run_id": "run-1",
        "updated_at": "2026-07-27T10:00:00+00:00",
        "resume_stage": None,
    }


def human_effective_policy(
    effective: str = "disabled",
    source: str = "system-default",
    project_revision: int = 0,
    override_revision: int = 0,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        **human_policy_binding(effective, source, project_revision, override_revision),
    }


def human_project_policy(default: str = "enabled", revision: int = 1) -> dict[str, Any]:
    policy = {
        "schema_version": 1,
        "project_id": "project-1",
        "default": default,
        "revision": revision,
        "actor": "human@example.com",
        "updated_at": "2026-07-24T10:00:00+00:00",
    }
    policy["policy_hash"] = canonical_hash(policy)
    return policy


def human_milestone_override(override: str = "inherit", revision: int = 1) -> dict[str, Any]:
    marker = {
        "schema_version": 1,
        "project_id": "project-1",
        "milestone_id": "milestone-1",
        "override": override,
        "revision": revision,
        "actor": "human@example.com",
        "updated_at": "2026-07-24T10:00:00+00:00",
    }
    marker["marker_hash"] = canonical_hash(marker)
    return marker


def human_gate(effective: dict[str, Any], state: str = "In Progress") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "project_id": "project-1",
        "milestone_id": "milestone-1",
        "issue_id": "ENG-999",
        "gate_revision": 1,
        "effective_policy_hash": effective["policy_hash"],
        "state": state,
        "updated_at": "2026-07-24T10:05:00+00:00",
    }


def human_checklist(
    effective: dict[str, Any],
    status: str = "pending",
    machine_revision: int = 4,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "checklist_id": "checklist-1",
        "project_id": "project-1",
        "milestone_id": "milestone-1",
        "gate_issue_id": "ENG-999",
        "checklist_revision": 1,
        "machine_verification_revision": machine_revision,
        "effective_policy_hash": effective["policy_hash"],
        "status": status,
        "instructions": ["Exercise the primary workflow"],
        "evidence": [],
        "actor": "linear-spanks",
        "updated_at": "2026-07-24T10:05:00+00:00",
    }


def human_repair(reason: str = "The primary workflow regressed") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "project_id": "project-1",
        "milestone_id": "milestone-1",
        "gate_issue_id": "ENG-999",
        "checklist_id": "checklist-1",
        "failure_revision": 1,
        "reason": reason,
        "status": "Unplanned",
    }


def approved_human_preview(
    requested_value: str,
    rows: list[dict[str, Any]],
    *,
    scope: str = "project",
    reason: str = "",
) -> dict[str, Any]:
    preview = {
        "schema_version": 1,
        "scope": scope,
        "project_id": "project-1",
        "milestone_id": "milestone-1" if scope == "milestone" else None,
        "requested_value": requested_value,
        "reason": reason,
        "active_milestone_ids": sorted(row["milestone_id"] for row in rows),
        "affected_milestones": sorted(rows, key=lambda row: row["milestone_id"]),
    }
    preview["preview_hash"] = canonical_hash(preview)
    preview["approved_hash"] = preview["preview_hash"]
    return preview


def assessment_fixture(name: str) -> dict[str, Any]:
    assessment = json.loads(json.dumps(ASSESSMENT_FIXTURES["base"]))
    override = ASSESSMENT_FIXTURES["cases"][name]
    for key, value in override.items():
        if key == "dimensions":
            assessment["dimensions"].update(value)
        else:
            assessment[key] = value
    return assessment


def dependency_graph_source_fixture() -> dict[str, Any]:
    footprint = lambda scopes, resources=None: {
        "repository": "linear-spanks",
        "write_scopes": scopes,
        "exclusive_resources": resources or [],
        "parallel_safe": True,
        "serialization_rationale": "scopes are explicit",
    }
    return {
        "project_id": "project-1",
        "milestone_id": "milestone-1",
        "graph_revision": 3,
        "workflow_revision": 7,
        "source_hash": "sha256:" + "a" * 64,
        "review_status": "reviewed",
        "tasks": [
            {"id": "ENG-1", "plan_revision": 1, "execution_footprint": footprint(["src/a.py"])},
            {"id": "ENG-2", "plan_revision": 2, "execution_footprint": footprint(["src/b.py"])},
            {"id": "ENG-3", "plan_revision": 1, "execution_footprint": footprint(["src/a.py"])},
            {"id": "ENG-4", "plan_revision": 1, "execution_footprint": footprint(["src/c.py"])},
        ],
        "hard_edges": [
            {"from": "ENG-1", "to": "ENG-4"},
            {"from": "ENG-2", "to": "ENG-4"},
        ],
        "generated_at": "2026-07-21T10:00:00+00:00",
    }


def wave_receipt_fixture() -> dict[str, Any]:
    task = lambda issue, suffix: {
        "issue_id": issue,
        "plan_revision": 1,
        "branch": f"linear-spanks/wave-wave-1/{issue}",
        "worktree": f"/worktrees/{suffix}",
        "claim_status": "claimed",
        "execution_status": "verified",
        "commit_sha": suffix * 40,
        "verification_status": "passed",
        "integration_status": "pending",
    }
    return {
        "schema_version": 1,
        "wave_id": "wave-1",
        "milestone_id": "milestone-1",
        "graph_hash": "sha256:" + "b" * 64,
        "source_hash": "sha256:" + "a" * 64,
        "parent_branch": "main",
        "baseline_head": "c" * 40,
        "worktree_root": "/worktrees",
        "requested_parallelism": 2,
        "effective_parallelism": 2,
        "state": "awaiting-reconciliation",
        "tasks": [task("ENG-1", "d"), task("ENG-2", "e")],
        "created_at": "2026-07-21T10:00:00+00:00",
        "updated_at": "2026-07-21T10:05:00+00:00",
    }


def isolation_preflight_fixture(command: str = "run-task") -> dict[str, Any]:
    return {
        "command": command,
        "isolated_worktree": True,
        "milestone_stage": "start-implementation" if command == "run-milestone" else None,
        "issue_id": "ENG-1",
        "plan_revision": 3,
        "source_hash": "sha256:" + "a" * 64,
        "run_id": "run-1",
        "receipt_id": "isolation-1",
        "repository_root": "/repo",
        "git_strategy_present": True,
        "worktree_root": "/worktrees",
        "parent_branch": "main",
        "parent_head": "b" * 40,
        "parent_attached": True,
        "parent_clean": True,
        "plan_current": True,
        "child_branch": "linear-spanks/run-run-1/ENG-1",
        "branch_exists": False,
        "worktree_path": "/worktrees/run-1-ENG-1",
        "worktree_path_exists": False,
        "active_receipts": [],
    }


def isolation_receipt_fixture(state: str = "prepared") -> dict[str, Any]:
    created = "2026-07-21T10:00:00+00:00"
    receipt = {
        "schema_version": 1,
        "receipt_id": "isolation-1",
        "run_id": "run-1",
        "state": "prepared",
        "command": "run-task",
        "issue_id": "ENG-1",
        "plan_revision": 3,
        "source_hash": "sha256:" + "a" * 64,
        "parent_branch": "main",
        "baseline_head": "b" * 40,
        "repository_root": "/repo",
        "worktree_root": "/worktrees",
        "worktree_path": "/worktrees/run-1-ENG-1",
        "child_branch": "linear-spanks/run-run-1/ENG-1",
        "child_commit": None,
        "verification": {"status": "pending", "commands": [], "completed_at": None},
        "integration": {
            "preview_hash": None,
            "preview_parent_head": None,
            "approved_preview_hash": None,
            "approved_parent_head": None,
            "integrated_head": None,
            "verification_status": "pending",
        },
        "completion": {
            "receipt_id": None,
            "receipt_persisted": False,
            "issue_done_read_back": False,
            "newly_unblocked_read_back": False,
            "worktree_cleanup": "pending",
        },
        "failure": None,
        "created_at": created,
        "updated_at": created,
        "state_timestamps": {"prepared": created},
    }
    if state in {"executing", "verified-pending-integration", "integrating", "integrated"}:
        receipt["state"] = "executing"
        receipt["updated_at"] = "2026-07-21T10:01:00+00:00"
        receipt["state_timestamps"]["executing"] = receipt["updated_at"]
    if state in {"verified-pending-integration", "integrating", "integrated"}:
        receipt["state"] = "verified-pending-integration"
        receipt["updated_at"] = "2026-07-21T10:02:00+00:00"
        receipt["state_timestamps"]["verified-pending-integration"] = receipt["updated_at"]
        receipt["child_commit"] = "c" * 40
        receipt["verification"] = {
            "status": "passed",
            "commands": ["python3 -m unittest"],
            "completed_at": receipt["updated_at"],
        }
        receipt["integration"]["preview_hash"] = "sha256:" + "d" * 64
        receipt["integration"]["preview_parent_head"] = "b" * 40
    if state in {"integrating", "integrated"}:
        receipt["state"] = "integrating"
        receipt["updated_at"] = "2026-07-21T10:03:00+00:00"
        receipt["state_timestamps"]["integrating"] = receipt["updated_at"]
        receipt["integration"]["approved_preview_hash"] = receipt["integration"]["preview_hash"]
        receipt["integration"]["approved_parent_head"] = "b" * 40
    if state == "integrated":
        receipt["state"] = "integrated"
        receipt["updated_at"] = "2026-07-21T10:04:00+00:00"
        receipt["state_timestamps"]["integrated"] = receipt["updated_at"]
        receipt["integration"]["integrated_head"] = "e" * 40
        receipt["integration"]["verification_status"] = "passed"
        receipt["completion"].update(
            {
                "receipt_id": "completion-1",
                "receipt_persisted": True,
                "issue_done_read_back": True,
                "newly_unblocked_read_back": True,
            }
        )
    return receipt


def isolation_current_fixture(receipt: dict[str, Any]) -> dict[str, Any]:
    return {
        "command": receipt["command"],
        "issue_id": receipt["issue_id"],
        "plan_revision": receipt["plan_revision"],
        "source_hash": receipt["source_hash"],
        "parent_branch": receipt["parent_branch"],
        "parent_head": receipt["integration"]["integrated_head"] or "b" * 40,
        "child_commit": receipt["child_commit"],
        "child_is_ancestor_of_parent": False,
        "parent_clean": True,
        "integration_verification_passed": False,
        "parent_fast_forwarded": False,
        "completion_receipt_persisted": False,
        "issue_done_read_back": False,
        "newly_unblocked_read_back": False,
    }


def project_loop_receipt_fixture(state: str = "prepared") -> dict[str, Any]:
    timestamp = "2026-07-22T10:00:00+00:00"
    milestone_state = "completed" if state == "completed" else "active"
    task_state = "integrated" if state == "completed" else "prepared"
    return {
        "schema_version": 1,
        "receipt_id": "project-loop-1",
        "state": state,
        "project_id": "project-1",
        "project_revision": 7,
        "project_orchestrator_id": "project-orchestrator-project-1",
        "source_hash": "sha256:" + "a" * 64,
        "dependency_graph_hash": "sha256:" + "b" * 64,
        "milestones": [
            {
                "milestone_id": "milestone-1",
                "milestone_revision": 3,
                "orchestrator_id": "milestone-orchestrator-milestone-1",
                "state": milestone_state,
            }
        ],
        "human_verification_policies": [human_policy_binding()],
        "task_loops": [
            {
                "task_id": "ENG-1",
                "milestone_id": "milestone-1",
                "plan_revision": 2,
                "executor_id": "task-executor-ENG-1",
                "verifier_id": "task-verifier-ENG-1",
                "state": task_state,
                "attempt_index": 0,
            }
        ],
        "current_event": None,
        "next_event": "milestone-orchestrate" if state != "completed" else None,
        "approval": {
            "status": "not-required",
            "preview_hash": None,
            "approved_hash": None,
        },
        "budget": {"role_invocations": 0, "injected_input_tokens": 0},
        "created_at": timestamp,
        "updated_at": timestamp,
        "state_timestamps": {state: timestamp},
        "failure": (
            {"code": "PROJECT_FAILED", "message": "terminal test failure"}
            if state == "failed"
            else None
        ),
    }


def milestone_loop_receipt_fixture(state: str = "prepared") -> dict[str, Any]:
    timestamp = "2026-07-23T10:00:00+00:00"
    task_state = "integrated" if state == "completed" else "prepared"
    return {
        "schema_version": 1,
        "receipt_id": "milestone-loop-1",
        "state": state,
        "project_id": "project-1",
        "project_revision": 7,
        "milestone_id": "milestone-1",
        "milestone_revision": 3,
        "milestone_orchestrator_id": "milestone-orchestrator-milestone-1",
        "source_hash": "sha256:" + "a" * 64,
        "dependency_graph_hash": "sha256:" + "b" * 64,
        "human_verification_policy": human_policy_binding(),
        "task_loops": [
            {
                "task_id": "ENG-1",
                "milestone_id": "milestone-1",
                "plan_revision": 2,
                "executor_id": "task-executor-ENG-1",
                "verifier_id": "task-verifier-ENG-1",
                "state": task_state,
                "attempt_index": 0,
            }
        ],
        "current_event": None,
        "next_event": "milestone-orchestrate" if state != "completed" else None,
        "approval": {
            "status": "not-required",
            "preview_hash": None,
            "approved_hash": None,
        },
        "budget": {"role_invocations": 0, "injected_input_tokens": 0},
        "created_at": timestamp,
        "updated_at": timestamp,
        "state_timestamps": {state: timestamp},
        "failure": (
            {"code": "MILESTONE_FAILED", "message": "terminal test failure"}
            if state == "failed"
            else None
        ),
    }


def role_handoff_fixture(role: str) -> dict[str, Any]:
    policy = PROJECT_ORCHESTRATION["roles"][role]
    task_role = role in {"task-executor", "task-verifier"}
    milestone_role = role != "project-orchestrator"
    return {
        "schema_version": 1,
        "handoff_id": f"handoff-{role}",
        "role": role,
        "logical_role_id": f"logical-{role}",
        "project_id": "project-1",
        "project_revision": 7,
        "milestone_id": "milestone-1" if milestone_role else None,
        "milestone_revision": 3 if milestone_role else None,
        "task_id": "ENG-1" if task_role else None,
        "plan_revision": 2 if task_role else None,
        "source_revision": 11 if task_role else None,
        "source_hash": "sha256:" + "a" * 64,
        "dependency_graph_hash": "sha256:" + "b" * 64,
        "repository_head": "c" * 40 if task_role else None,
        "attempt_id": "attempt-0" if task_role else None,
        "context_sections": policy["required_context"],
        "context_tokens": 1000,
        "raw_transcript_included": False,
        "previous_handoff_hash": None,
        "created_at": "2026-07-22T10:00:00+00:00",
    }


def task_attempt_fixture(
    index: int = 0,
    result: str = "failed",
    *,
    attempt_kind: str = "automatic",
) -> dict[str, Any]:
    selected = None
    strength = "low"
    approved = False
    if attempt_kind == "user-selected":
        selected = {
            "strength": "high",
            "model": "provider/strong",
            "harness": "codex",
            "capability": "enforced",
            "configured": True,
        }
        strength = "high"
        approved = True
    return {
        "schema_version": 1,
        "task_id": "ENG-1",
        "task_loop_id": "task-loop-1",
        "attempt_id": f"attempt-{index}",
        "attempt_index": index,
        "attempt_kind": attempt_kind,
        "executor_phase": "implementation" if index == 0 else "repair",
        "executor_strength": strength,
        "verifier_strength": "high",
        "selected_model": selected,
        "user_approved": approved,
        "previous_verification": None if index == 0 else "failed",
        "verification_result": result,
        "candidate_commit": f"{index + 1:x}" * 40,
    }


def verification_ledger_fixture(result: str = "passed") -> dict[str, Any]:
    commit = "d" * 40
    passing = result == "passed"
    return {
        "schema_version": 1,
        "ledger_id": "ledger-ENG-1",
        "task_id": "ENG-1",
        "verifier_id": "task-verifier-ENG-1",
        "project_revision": 7,
        "milestone_revision": 3,
        "plan_revision": 2,
        "source_revision": 11,
        "candidate_commit": commit,
        "reviewed_attempts": [
            {
                "attempt_id": "attempt-0",
                "attempt_index": 0,
                "commit": commit,
                "result": "passed" if passing else "failed",
                "reviewed_at": "2026-07-22T10:05:00+00:00",
            }
        ],
        "acceptance_criteria": [
            {
                "criterion_id": "acceptance-1",
                "status": "passing" if passing else "failing",
                "evidence": "focused test passed" if passing else "focused test failed",
                "last_checked_commit": commit,
            }
        ],
        "findings": (
            []
            if passing
            else [
                {
                    "finding_id": "finding-1",
                    "status": "open",
                    "summary": "focused test still fails",
                    "introduced_commit": commit,
                    "resolved_commit": None,
                    "evidence": "test output summary",
                }
            ]
        ),
        "verification_runs": [
            {
                "command": "python3 -m unittest tests.test_target",
                "status": "passed" if passing else "failed",
                "summary": "focused verification result",
                "artifact": None,
                "commit": commit,
            }
        ],
        "baseline_failures": [],
        "exclusions": [],
        "next_checks": [] if passing else ["rerun focused verification"],
        "raw_executor_transcript_included": False,
        "required_verification_current": passing,
        "final_result": result,
        "live_session": {
            "session_id": "verifier-session-1",
            "status": "active",
            "context_tokens": 2000,
        },
        "updated_at": "2026-07-22T10:05:00+00:00",
    }


def project_capsule_fixture() -> dict[str, Any]:
    body = "\n\n".join(
        f"{heading}\n\nContent for {heading[3:]}"
        for heading in PROJECT_EPOCH["capsule"]["required_headings"]
    )
    digest = "sha256:" + "a" * 64
    return {
        "schema_version": 1,
        "project_id": "project-1",
        "project_revision": 42,
        "label": "Post-v1 baseline",
        "generated_at": "2026-07-16T10:00:00+00:00",
        "body": body,
        "source_snapshot_hash": digest,
        "batches": [
            {
                "batch_id": "batch-1",
                "compact_rows": 2,
                "full_entities": 1,
                "source_ids": ["milestone-1", "issue-1"],
            }
        ],
        "coverage": {
            "expected_source_ids": ["milestone-1", "issue-1", "document-old"],
            "covered_source_ids": ["milestone-1", "issue-1"],
            "excluded_sources": [
                {"source_id": "document-old", "reason": "superseded historical draft"}
            ],
        },
        "next_command": "run-milestone milestone-2 --project-id project-1",
    }


def rollover_receipt_fixture(phase: str = "preview") -> dict[str, Any]:
    phases = PROJECT_EPOCH["rollover"]["phases"]
    phase_index = phases.index(phase)
    at_least = lambda target: phase_index >= phases.index(target)
    digest_a = "sha256:" + "a" * 64
    digest_b = "sha256:" + "b" * 64
    successor_created = at_least("successor-created")
    roadmap_created = at_least("roadmap-created")
    carryover_created = at_least("carryover-created")
    source_resolved = at_least("source-resolved")
    finalized = phase == "finalized"

    read_back_ids: list[str] = []
    successor = None
    if successor_created:
        successor = {"project_id": "project-2", "revision": 1, "status": "Planned"}
        read_back_ids.extend(["project-2", "capsule-1"])
    roadmap = []
    if at_least("preview"):
        for index in range(1, 4):
            milestone_id = f"milestone-new-{index}" if roadmap_created else None
            roadmap.append(
                {
                    "proposal_id": f"roadmap-{index}",
                    "successor_milestone_id": milestone_id,
                    "objective": f"Outcome {index}",
                    "read_back": roadmap_created,
                }
            )
            if milestone_id:
                read_back_ids.append(milestone_id)
    carryovers = []
    if at_least("preview"):
        successor_issue_id = "issue-new-1" if carryover_created else None
        carryovers.append(
            {
                "source_issue_id": "issue-1",
                "source_revision": 7,
                "successor_issue_id": successor_issue_id,
                "successor_status": "Unplanned" if carryover_created else None,
                "provenance_linked": carryover_created,
                "read_back": carryover_created,
            }
        )
        if successor_issue_id:
            read_back_ids.append(successor_issue_id)
    milestone_dispositions = [
        {
            "source_milestone_id": "milestone-1",
            "disposition": "wrapped",
            "approved": source_resolved,
            "resolved": source_resolved,
        }
    ]
    issue_dispositions = [
        {
            "source_issue_id": "issue-1",
            "disposition": "superseded",
            "approved": source_resolved,
            "resolved": source_resolved,
        }
    ]
    if source_resolved:
        read_back_ids.extend(["milestone-1", "issue-1"])
    if finalized:
        read_back_ids.append("project-1")
    return {
        "schema_version": 1,
        "run_id": "rollover-1",
        "phase": phase,
        "source_project": {
            "project_id": "project-1",
            "revision": 42,
            "status": "Completed" if finalized else "In Progress",
        },
        "successor_project": successor,
        "next_release": "v2",
        "initiative": {
            "source_initiative_id": "initiative-1",
            "requested_initiative_id": None,
            "successor_initiative_id": "initiative-1" if successor_created else None,
            "warning": None,
        },
        "source_snapshot_hash": digest_a,
        "approved_plan_hash": digest_b if at_least("preview") else None,
        "capsule": (
            {
                "document_id": "capsule-1" if successor_created else None,
                "revision": 2 if successor_created else 0,
                "content_hash": digest_a,
                "source_snapshot_hash": digest_a,
                "status": "finalized"
                if finalized
                else ("prepared" if successor_created else "draft"),
            }
            if at_least("preview")
            else None
        ),
        "roadmap_items": roadmap,
        "carryovers": carryovers,
        "milestone_dispositions": milestone_dispositions,
        "issue_dispositions": issue_dispositions,
        "unresolved_source_items": [] if source_resolved else ["milestone-1", "issue-1"],
        "applied_operation_ids": [],
        "read_back_ids": read_back_ids,
        "next_command": (
            "run-milestone milestone-new-1 --project-id project-2"
            if finalized
            else f"rollover-project project-1 --next-release v2 --resume {phase}"
        ),
        "updated_at": "2026-07-16T10:00:00+00:00",
    }
