from __future__ import annotations

import copy
import json
import tempfile
import unittest
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from linear_spanks.core.errors import LinearSpanksError
from linear_spanks.domains import _context_v1 as context
from linear_spanks.domains import _graphs_v1 as graphs
from linear_spanks.domains import _isolation_v1 as isolation
from linear_spanks.domains import _orchestration_v1 as orchestration
from linear_spanks.domains import _reviews_v1 as reviews
from linear_spanks.domains import _routing_v1 as routing
from linear_spanks.domains import _runtime_v1 as runtime
from linear_spanks.domains import _state_v1 as state
from linear_spanks.domains import _verification_v1 as verification
from linear_spanks.domains import context as context_api
from linear_spanks.domains import execution
from linear_spanks.domains import graphs as graphs_api
from linear_spanks.domains import isolation as isolation_api
from linear_spanks.domains import orchestration as orchestration_api
from linear_spanks.domains import reviews as reviews_api
from linear_spanks.domains import runtime as runtime_api
from linear_spanks.domains import state as state_api
from linear_spanks.domains._validation import checked

from tests.contract_support import (
    approved_human_preview,
    assessment_fixture,
    canonical_hash,
    dependency_graph_source_fixture,
    human_checklist,
    human_effective_policy,
    human_gate,
    human_milestone_override,
    human_policy_binding,
    human_project_policy,
    human_repair,
    isolation_preflight_fixture,
    isolation_receipt_fixture,
    milestone_loop_receipt_fixture,
    project_capsule_fixture,
    project_loop_receipt_fixture,
    role_handoff_fixture,
    rollover_receipt_fixture,
    task_attempt_fixture,
    verification_ledger_fixture,
    wave_receipt_fixture,
)

Payload = dict[str, Any]
Validator = Callable[[Payload], Any]
PathPart = str | int
_DIGEST_A = "sha256:" + "a" * 64
_DIGEST_B = "sha256:" + "b" * 64
_DIGEST_C = "sha256:" + "c" * 64


def _footprint(scopes: list[str]) -> Payload:
    return {
        "repository": "linear-spanks",
        "write_scopes": scopes,
        "exclusive_resources": [],
        "parallel_safe": True,
        "serialization_rationale": "mutation fixture scopes are explicit",
    }


def _incremental_plan() -> Payload:
    return {
        "schema_version": 2,
        "task_id": "ENG-1",
        "plan_revision": 1,
        "trace_source_head": "abc123",
        "target_file_hashes": {"src/a.py": _DIGEST_A},
        "consumed_surface_hashes": {"src/api.py#Api": _DIGEST_B},
        "dependency_receipt_hashes": {
            "ENG-0": {"receipt_hash": _DIGEST_A, "output_hash": _DIGEST_B}
        },
        "acceptance_contract_hash": _DIGEST_C,
        "execution_footprint": _footprint(["src/a.py"]),
    }


def _review_checkpoint() -> Payload:
    return {
        "schema_version": 2,
        "receipt_id": "review-receipt-1",
        "review_id": "review-1",
        "session_id": "session-1",
        "project_id": "project-1",
        "milestone_id": "milestone-1",
        "entry_command": "review-milestone",
        "mode": "incremental",
        "marker_revision": 7,
        "matrix_hash": _DIGEST_A,
        "dependency_graph_hash": _DIGEST_B,
        "coverage_hash": _DIGEST_C,
        "ordered_task_ids": ["A", "B"],
        "covered_task_ids": ["A", "B"],
        "remaining_task_ids": [],
        "changed_task_ids": ["A"],
        "adjacent_task_ids": ["B"],
        "unchanged_task_ids": [],
        "task_revisions": {"A": 2, "B": 1},
        "plan_revisions": {"A": 2, "B": 1},
        "batch_index": 1,
        "cumulative_findings": [
            {
                "finding_id": "finding-1",
                "severity": "medium",
                "summary": "Bounded mutation fixture finding",
                "task_ids": ["A"],
                "source_revisions": {"A": 2},
            }
        ],
        "previous_receipt_id": None,
        "budget": {
            "model_turns": 4,
            "active_context_tokens": 12000,
            "cumulative_input_tokens": None,
            "phase_cumulative_input_tokens": None,
            "planned_batches": 1,
            "telemetry_available": False,
        },
        "idempotency_key": "review-1:batch-1",
        "status": "ready-to-finalize",
        "timestamp": "2026-07-27T10:00:00+00:00",
        "next_command": "review-milestone milestone-1 --resume review-receipt-1",
        "checkpoint_read_back": True,
    }


def _review_coverage() -> Payload:
    return {
        "tasks": [
            {
                "id": "A",
                "dependencies": [],
                "execution_footprint": _footprint(["src/a.py"]),
                "final_sink": False,
            },
            {
                "id": "B",
                "dependencies": ["A"],
                "execution_footprint": _footprint(["src/b.py"]),
                "final_sink": False,
            },
            {
                "id": "C",
                "dependencies": [],
                "execution_footprint": _footprint(["src/a.py/sub"]),
                "final_sink": True,
            },
        ],
        "changed_task_ids": ["A"],
        "mode": "incremental",
    }


def _next_wave() -> Payload:
    return {
        "tasks": [
            {
                "id": "A",
                "status": "Unplanned",
                "plan_revision": 0,
                "dependencies": [],
                "dependency_statuses": {},
                "review_covered": True,
                "active_receipt": False,
            },
            {
                "id": "B",
                "status": "Unplanned",
                "plan_revision": 0,
                "dependencies": ["A"],
                "dependency_statuses": {"A": "Done"},
                "review_covered": True,
                "active_receipt": False,
            },
        ],
        "max_parallel": 2,
    }


def _project_event() -> Payload:
    return {
        "project_drift": False,
        "cross_milestone_conflict": False,
        "approval_pending": False,
        "executing_task_ids": [],
        "verifying_task_ids": ["ENG-1"],
        "verified_task_ids": ["ENG-2"],
        "ready_task_ids": ["ENG-3"],
        "milestones_ready_to_wrap": ["milestone-1"],
        "eligible_milestone_ids": ["milestone-2"],
        "project_complete": False,
    }


def _milestone_event() -> Payload:
    return {
        "project_coordination_required": False,
        "approval_pending": False,
        "executing_task_ids": [],
        "verifying_task_ids": ["ENG-1"],
        "verified_task_ids": ["ENG-2"],
        "ready_task_ids": ["ENG-3"],
        "milestone_ready_to_wrap": True,
        "eligible_milestone_work": True,
        "milestone_complete": False,
    }


def _project_transition(receipt: Payload) -> Payload:
    return {
        "target_state": "project-orchestrating",
        "current_project_revision": receipt["project_revision"],
        "current_source_hash": receipt["source_hash"],
        "current_dependency_graph_hash": receipt["dependency_graph_hash"],
        "current_milestones": receipt["milestones"],
        "current_human_verification_policies": receipt["human_verification_policies"],
        "current_task_loops": receipt["task_loops"],
        "completed_event": receipt["next_event"],
        "next_project_revision": receipt["project_revision"],
        "next_source_hash": receipt["source_hash"],
        "next_dependency_graph_hash": receipt["dependency_graph_hash"],
        "next_milestones": receipt["milestones"],
        "next_human_verification_policies": receipt["human_verification_policies"],
        "next_task_loops": receipt["task_loops"],
        "next_budget": {"role_invocations": 1, "injected_input_tokens": 1000},
        "next_event": "milestone-orchestrate",
        "approval": receipt["approval"],
        "failure": None,
        "updated_at": "2026-07-22T10:01:00+00:00",
    }


def _milestone_transition(receipt: Payload) -> Payload:
    return {
        "target_state": "milestone-orchestrating",
        "current_project_revision": receipt["project_revision"],
        "current_milestone_revision": receipt["milestone_revision"],
        "current_source_hash": receipt["source_hash"],
        "current_dependency_graph_hash": receipt["dependency_graph_hash"],
        "current_human_verification_policy": receipt["human_verification_policy"],
        "current_task_loops": receipt["task_loops"],
        "completed_event": receipt["next_event"],
        "next_project_revision": receipt["project_revision"],
        "next_milestone_revision": receipt["milestone_revision"],
        "next_source_hash": receipt["source_hash"],
        "next_dependency_graph_hash": receipt["dependency_graph_hash"],
        "next_human_verification_policy": receipt["human_verification_policy"],
        "next_task_loops": receipt["task_loops"],
        "next_budget": {"role_invocations": 1, "injected_input_tokens": 1000},
        "next_event": "milestone-orchestrate",
        "approval": receipt["approval"],
        "failure": None,
        "updated_at": "2026-07-23T10:01:00+00:00",
    }


def _model_escalation() -> Payload:
    return {
        "task_id": "ENG-1",
        "automatic_attempts_completed": 4,
        "automatic_failures": 4,
        "previous_escalated_failure": False,
        "action": "run-selected-model",
        "selected_model": {
            "strength": "high",
            "model": "provider/strong",
            "harness": "codex",
            "capability": "enforced",
            "configured": True,
        },
        "user_approved": True,
    }


def _affected_row(
    *,
    stage: str = "implementing",
    before: str = "disabled",
    after: str = "enabled",
    gate_id: str | None = None,
    gate_action: str = "create",
    checklist_id: str | None = None,
    checklist_action: str = "none",
    receipt_action: str = "reconcile",
) -> Payload:
    return {
        "milestone_id": "milestone-1",
        "stage": stage,
        "before_effective": before,
        "after_effective": after,
        "gate_issue_id": gate_id,
        "gate_action": gate_action,
        "checklist_id": checklist_id,
        "checklist_action": checklist_action,
        "orchestration_receipt_ids": ["receipt-1"],
        "receipt_action": receipt_action,
    }


def _paths(value: Any, prefix: tuple[PathPart, ...] = ()) -> Iterator[tuple[PathPart, ...]]:
    if isinstance(value, dict):
        for key, child in value.items():
            path = (*prefix, key)
            yield path
            yield from _paths(child, path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            path = (*prefix, index)
            yield path
            yield from _paths(child, path)


def _invalid_values(value: Any) -> tuple[Any, ...]:
    if isinstance(value, bool):
        return (None, "not-a-boolean", 0)
    if isinstance(value, int):
        return (None, True, -1, 0, 10**9)
    if isinstance(value, str):
        return (None, "", 123, "invalid", "../invalid")
    if value is None:
        return ("unexpected-value", 0, {}, [])
    if isinstance(value, dict):
        return (None, [], {}, {**value, "unexpected": None})
    if isinstance(value, list):
        duplicate = [*value, value[0]] if value else [None]
        return (None, {}, [], [None], duplicate, list(reversed(value)))
    return (None,)


def _mutated(payload: Payload, path: tuple[PathPart, ...], value: Any) -> Payload:
    result = copy.deepcopy(payload)
    cursor: Any = result
    for part in path[:-1]:
        cursor = cursor[part]
    final = path[-1]
    cursor[final] = value
    return result


class DomainValidationMutationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        fixture_path = Path(__file__).parent / "fixtures" / "v1" / "artifacts.json"
        cls.artifacts = json.loads(fixture_path.read_text(encoding="utf-8"))["artifacts"]

    def _exercise(self, name: str, validator: Validator, payload: Payload) -> None:
        checked(validator, copy.deepcopy(payload))

        attempted = 0
        rejected = 0
        for path in _paths(payload):
            cursor: Any = payload
            for part in path:
                cursor = cursor[part]
            for value in _invalid_values(cursor):
                if value == cursor:
                    continue
                attempted += 1
                try:
                    checked(validator, _mutated(payload, path, value))
                except LinearSpanksError as error:
                    rejected += 1
                    self.assertTrue(error.code)
                    if error.code != "PAYLOAD_VALIDATION_FAILED":
                        self.assertIn("next_action", error.details)
        self.assertGreater(attempted, 0, name)
        self.assertGreaterEqual(rejected, max(1, attempted // 10), name)

    def test_context_graph_and_isolation_payloads_fail_closed_under_deep_mutation(self) -> None:
        graph = graphs.build_dependency_graph(dependency_graph_source_fixture())
        cases: tuple[tuple[str, Validator, Payload], ...] = (
            ("project-capsule", context.validate_project_capsule, project_capsule_fixture()),
            ("graph-source", graphs.build_dependency_graph, dependency_graph_source_fixture()),
            ("dependency-graph", graphs.validate_dependency_graph, graph),
            ("wave-receipt", graphs.validate_wave_receipt, wave_receipt_fixture()),
            (
                "isolation-preflight",
                isolation.validate_isolation_preflight,
                isolation_preflight_fixture(),
            ),
            (
                "isolation-prepared",
                isolation.validate_isolation_receipt,
                isolation_receipt_fixture(),
            ),
            (
                "isolation-integrated",
                isolation.validate_isolation_receipt,
                isolation_receipt_fixture("integrated"),
            ),
        )
        for name, validator, payload in cases:
            with self.subTest(name=name):
                self._exercise(name, validator, payload)

    def test_checkpoint_rollover_and_context_packets_fail_closed_under_deep_mutation(self) -> None:
        command_context = execution.execution_envelope("run-task")["context"]
        command_packet = {
            "items": ["bounded task context"],
            "metrics": {
                key: [] for key in command_context if key not in {"max_input_tokens", "profile"}
            },
        }
        planner_context = execution.execution_envelope("run-task")["orchestration"]["planner"][
            "context"
        ]
        planner_packet = {
            "items": ["bounded planning context"],
            "metrics": {
                key: [] for key in planner_context if key not in {"max_input_tokens", "profile"}
            },
        }
        repository_scan = execution.execution_envelope("import-codebase", "medium")[
            "repository_scan"
        ]
        repository_packet = {
            "items": ["bounded repository context"],
            "metrics": {
                key: []
                for key in repository_scan["context"]
                if key not in {"max_input_tokens", "profile"}
            },
        }
        cases: tuple[tuple[str, Validator, Payload], ...] = (
            (
                "command-context-packet",
                lambda payload: context.measure_context_packet("run-task", payload),
                command_packet,
            ),
            (
                "planner-context-packet",
                lambda payload: context.measure_context_packet(
                    "run-task", payload, scope="planner"
                ),
                planner_packet,
            ),
            (
                "repository-context-packet",
                lambda payload: context.measure_context_packet(
                    "import-codebase", payload, scope="repository", scan_tier="medium"
                ),
                repository_packet,
            ),
            (
                "rollover-preview",
                context.validate_rollover_receipt,
                self.artifacts["rollover-receipt"],
            ),
            (
                "rollover-finalized",
                context.validate_rollover_receipt,
                rollover_receipt_fixture("finalized"),
            ),
        )
        for name, validator, payload in cases:
            with self.subTest(name=name):
                self._exercise(name, validator, payload)

        with tempfile.TemporaryDirectory() as directory:
            checkpoint = copy.deepcopy(self.artifacts["repository-checkpoint"])
            checkpoint["repository_root"] = directory
            self._exercise(
                "repository-checkpoint",
                context.validate_repository_checkpoint,
                checkpoint,
            )

    def test_orchestration_payloads_fail_closed_under_deep_mutation(self) -> None:
        project_receipt = project_loop_receipt_fixture()
        milestone_receipt = milestone_loop_receipt_fixture()
        executor_capability = {
            "role": "task-executor",
            "operation": "edit-assigned-worktree",
            "tracked_source_write": True,
            "worktree_path": "/worktrees/ENG-1",
            "assigned_worktree": "/worktrees/ENG-1",
            "comment_marker": None,
        }
        cases: tuple[tuple[str, Validator, Payload], ...] = (
            (
                "project-loop-prepared",
                orchestration.validate_project_loop_receipt,
                project_receipt,
            ),
            (
                "project-loop-completed",
                orchestration.validate_project_loop_receipt,
                project_loop_receipt_fixture("completed"),
            ),
            (
                "milestone-loop-prepared",
                orchestration.validate_milestone_loop_receipt,
                milestone_receipt,
            ),
            (
                "milestone-loop-completed",
                orchestration.validate_milestone_loop_receipt,
                milestone_loop_receipt_fixture("completed"),
            ),
            (
                "role-handoff",
                lambda payload: orchestration.validate_role_handoff(payload),
                role_handoff_fixture("task-executor"),
            ),
            (
                "project-role-handoff",
                lambda payload: orchestration.validate_role_handoff(payload),
                role_handoff_fixture("project-orchestrator"),
            ),
            (
                "milestone-role-handoff",
                lambda payload: orchestration.validate_role_handoff(payload),
                role_handoff_fixture("milestone-orchestrator"),
            ),
            (
                "role-capability",
                orchestration.validate_role_capability,
                executor_capability,
            ),
            (
                "automatic-task-attempt",
                orchestration.validate_task_attempt,
                task_attempt_fixture(),
            ),
            (
                "selected-task-attempt",
                orchestration.validate_task_attempt,
                task_attempt_fixture(4, attempt_kind="user-selected"),
            ),
            (
                "passing-verification-ledger",
                orchestration.validate_verification_ledger,
                verification_ledger_fixture(),
            ),
            (
                "failed-verification-ledger",
                orchestration.validate_verification_ledger,
                verification_ledger_fixture("failed"),
            ),
            (
                "project-receipt-selection",
                orchestration.check_project_loop_receipts,
                {
                    "project_id": "project-1",
                    "project_revision": 7,
                    "receipts": [project_receipt],
                },
            ),
            (
                "milestone-receipt-selection",
                orchestration.check_milestone_loop_receipts,
                {
                    "project_id": "project-1",
                    "project_revision": 7,
                    "milestone_id": "milestone-1",
                    "milestone_revision": 3,
                    "receipts": [milestone_receipt],
                },
            ),
            ("project-event", orchestration.select_project_loop_event, _project_event()),
            (
                "milestone-event",
                orchestration.select_milestone_loop_event,
                _milestone_event(),
            ),
            (
                "orchestration-scope",
                orchestration.check_orchestration_scope,
                {
                    "scope": "project",
                    "project_id": "project-1",
                    "project_revision": 7,
                    "project_receipts": [],
                    "milestone_receipts": [],
                },
            ),
            (
                "project-transition",
                lambda payload: orchestration.transition_project_loop_receipt(
                    payload["receipt"], payload["request"]
                ),
                {"receipt": project_receipt, "request": _project_transition(project_receipt)},
            ),
            (
                "milestone-transition",
                lambda payload: orchestration.transition_milestone_loop_receipt(
                    payload["receipt"], payload["request"]
                ),
                {
                    "receipt": milestone_receipt,
                    "request": _milestone_transition(milestone_receipt),
                },
            ),
            (
                "model-escalation",
                orchestration.validate_model_escalation,
                _model_escalation(),
            ),
        )
        for name, validator, payload in cases:
            with self.subTest(name=name):
                self._exercise(name, validator, payload)

    def test_review_payloads_fail_closed_under_deep_mutation(self) -> None:
        plan = _incremental_plan()
        checkpoint = _review_checkpoint()
        finalization = {
            "checkpoint": checkpoint,
            "current_marker_revision": checkpoint["marker_revision"],
            "current_matrix_hash": checkpoint["matrix_hash"],
            "current_dependency_graph_hash": checkpoint["dependency_graph_hash"],
            "current_coverage_hash": checkpoint["coverage_hash"],
            "current_source_revisions": {
                "task_revisions": checkpoint["task_revisions"],
                "plan_revisions": checkpoint["plan_revisions"],
            },
            "model_turns": 1,
            "active_context_tokens": 1000,
            "cumulative_input_tokens": None,
            "phase_cumulative_input_tokens": None,
            "telemetry_available": False,
            "findings_persisted": True,
            "marker_advanced": True,
            "durable_read_back": True,
            "next_command": "milestone run milestone-1",
        }
        cases: tuple[tuple[str, Validator, Payload], ...] = (
            ("incremental-plan", reviews.validate_incremental_plan, plan),
            (
                "plan-drift",
                reviews.classify_plan_drift,
                {"plan": plan, "current": copy.deepcopy(plan), "changed_plan_fields": []},
            ),
            (
                "review-checkpoint",
                reviews.validate_milestone_review_checkpoint,
                checkpoint,
            ),
            (
                "review-finalization",
                reviews.validate_milestone_review_finalization,
                finalization,
            ),
            ("review-coverage", reviews.calculate_incremental_review_coverage, _review_coverage()),
            ("next-wave", reviews.select_next_planning_wave, _next_wave()),
        )
        for name, validator, payload in cases:
            with self.subTest(name=name):
                self._exercise(name, validator, payload)

    def test_public_domain_facades_cover_the_owned_namespaced_surface(self) -> None:
        graph = graphs_api.build(dependency_graph_source_fixture())
        self.assertEqual(graphs_api.validate(graph), graph)
        rendered = graphs_api.render(graph)
        self.assertEqual(graphs_api.parse(rendered), graph)
        self.assertIn(
            "linear-spanks:dependency-graph",
            graphs_api.upsert("# Objective\n", graph),
        )
        selection = graphs_api.select_wave(
            {
                "graph": graph,
                "live_statuses": {task["id"]: "Backlog" for task in graph["tasks"]},
                "excluded_issue_ids": [],
            },
            2,
            2,
        )
        self.assertTrue(selection["selected"])
        self.assertEqual(
            graphs_api.validate_wave_receipt(wave_receipt_fixture())["state"],
            "awaiting-reconciliation",
        )

        self.assertEqual(
            isolation_api.preflight(isolation_preflight_fixture())["status"], "prepare"
        )
        self.assertEqual(
            isolation_api.validate_receipt(isolation_receipt_fixture())["state"], "prepared"
        )

        command_context = execution.execution_envelope("run-task")["context"]
        metrics = {key: [] for key in command_context if key not in {"profile", "max_input_tokens"}}
        self.assertEqual(context_api.validate_usage("run-task", 1, [])["status"], "within-budget")
        self.assertEqual(
            context_api.measure_packet("run-task", {"items": ["bounded"], "metrics": metrics})[
                "status"
            ],
            "within-budget",
        )
        with tempfile.TemporaryDirectory() as directory:
            checkpoint_payload = copy.deepcopy(self.artifacts["repository-checkpoint"])
            checkpoint_payload["repository_root"] = directory
            self.assertEqual(context_api.validate_checkpoint(checkpoint_payload)["status"], "valid")

        project_receipt = project_loop_receipt_fixture()
        milestone_receipt = milestone_loop_receipt_fixture()
        self.assertEqual(orchestration_api.project_next(_project_event())["event"], "task-verify")
        self.assertEqual(
            orchestration_api.milestone_next(_milestone_event())["event"], "task-verify"
        )
        self.assertEqual(
            orchestration_api.project_transition(
                project_receipt, _project_transition(project_receipt)
            )["state"],
            "project-orchestrating",
        )
        self.assertEqual(
            orchestration_api.milestone_transition(
                milestone_receipt, _milestone_transition(milestone_receipt)
            )["state"],
            "milestone-orchestrating",
        )
        self.assertEqual(
            orchestration_api.validate_scope(
                {
                    "scope": "project",
                    "project_id": "project-1",
                    "project_revision": 7,
                    "project_receipts": [],
                    "milestone_receipts": [],
                }
            )["status"],
            "clear",
        )
        self.assertEqual(
            orchestration_api.validate_handoff(role_handoff_fixture("task-executor"))["role"],
            "task-executor",
        )
        capability = {
            "role": "task-executor",
            "operation": "edit-assigned-worktree",
            "tracked_source_write": True,
            "worktree_path": "/worktrees/ENG-1",
            "assigned_worktree": "/worktrees/ENG-1",
            "comment_marker": None,
        }
        self.assertEqual(orchestration_api.validate_capability(capability)["status"], "allowed")
        self.assertEqual(
            orchestration_api.validate_attempt(task_attempt_fixture())["status"], "valid"
        )
        self.assertEqual(
            orchestration_api.validate_escalation(_model_escalation())["status"], "valid"
        )

        plan = _incremental_plan()
        checkpoint = _review_checkpoint()
        self.assertEqual(reviews_api.checkpoint(checkpoint)["status"], "ready-to-finalize")
        self.assertEqual(reviews_api.incremental_plan(plan)["task_id"], "ENG-1")
        self.assertEqual(
            reviews_api.classify_drift(
                {"plan": plan, "current": copy.deepcopy(plan), "changed_plan_fields": []}
            )["classification"],
            "valid",
        )
        self.assertTrue(reviews_api.coverage(_review_coverage())["covered_task_ids"])
        self.assertTrue(reviews_api.next_wave(_next_wave())["selected"])
        findings = {
            "milestone_id": "milestone-1",
            "session_id": "session-facade",
            "findings": ["Bounded finding"],
            "existing_session_ids": [],
            "candidate_owners": [],
            "changed_provided_surfaces": [],
            "unfinished_plans": [],
        }
        self.assertEqual(reviews_api.findings(findings)["status"], "accepted")

        projection = copy.deepcopy(self.artifacts["milestone-runtime-projection"])
        self.assertEqual(runtime_api.validate_projection(projection)["runtime_id"], "runtime-1")
        storage = {
            "milestone_id": "milestone-1",
            "documents_available": True,
            "documents": [projection],
            "comments": [],
        }
        self.assertEqual(runtime_api.validate_storage(storage)["action"], "use-document")
        migration = {**storage, "description": "# Objective\n"}
        self.assertTrue(runtime_api.migrate_projection(migration)["description_preserved"])
        binding = dict.fromkeys(
            runtime.milestone_runtime_contract()["autopilot"]["expiry_fields"], _DIGEST_A
        )
        self.assertTrue(
            runtime_api.validate_policy(
                {
                    "policy_binding": binding,
                    "current_binding": copy.deepcopy(binding),
                    "operation": "safe-plan-refresh",
                }
            )["automatic"]
        )
        self.assertEqual(
            runtime_api.validate_policy_binding(self.artifacts["autopilot-policy"])["policy_id"],
            "policy-1",
        )
        self.assertEqual(
            runtime_api.resolve_mode(
                {
                    "command": "run-milestone",
                    "autopilot": False,
                    "until": None,
                    "max_events": None,
                    "repair_safe": False,
                    "isolated_worktree": False,
                }
            )["mode"],
            "legacy-single-stage",
        )
        self.assertTrue(
            runtime_api.validate_loop(
                {
                    "max_events": 1,
                    "event_count": 0,
                    "until": ["blocked"],
                    "observed_stop": None,
                    "receipts": [],
                    "isolated_worktree": True,
                }
            )["continue"]
        )

        marker = self.artifacts["state-marker"]
        marker_text = (
            "<!-- linear-spanks:state "
            + json.dumps(marker, sort_keys=True, separators=(",", ":"))
            + " -->"
        )
        self.assertEqual(state_api.parse_marker(marker_text)["stage"], marker["stage"])
        self.assertEqual(state_api.transition("clarify", "draft"), "clarified")
        self.assertEqual(
            state_api.issue_transition("refine-task", "Human draft", "Unplanned")["to_status"],
            "Unplanned",
        )
        self.assertTrue(state_api.payload_hash({"value": 1}).startswith("sha256:"))
        self.assertTrue(
            state_api.idempotency_key("project-1", "ENG-1", "run-task", 1).startswith("lsp-")
        )

    def test_execution_receipts_and_planner_batches_fail_closed_under_deep_mutation(self) -> None:
        preflight_receipt = {
            "schema_version": 1,
            "target_id": "issue-1",
            "target_revision": "issue-r1",
            "blocker_revision": "blockers-r1",
            "plan_revision": "plan-1",
            "repository_revision": "repo-r1",
            "harness": "codex",
            "requested_assurance": "balanced",
            "effective_assurance": "balanced",
            "scan_tier": "fast",
        }
        preflight_current = {
            key: value for key, value in preflight_receipt.items() if key != "schema_version"
        }
        readback = {
            "schema_version": 1,
            "assurance": "balanced",
            "bulk": True,
            "operations": [
                {"entity_id": "A", "expected_revision": "2", "write_acknowledged": True},
                {"entity_id": "B", "expected_revision": "3", "write_acknowledged": True},
            ],
            "reconciliation": {"A": "2", "B": "3"},
        }
        completion = {
            "harness": "codex",
            "worker_role": "executor",
            "configured_model_when_observable": None,
            "tier_enforcement_status": "enforced",
            "requested_strength": "low",
            "review_result": "self-verified",
            "requested_assurance": "fast",
            "effective_assurance": "fast",
            "assurance_escalation_reason": None,
            "planner_runs": 0,
            "reviewer_runs": 0,
            "delegated_roles": ["executor"],
            "linear_reads": 3,
            "linear_writes": 2,
            "linear_read_backs": 1,
            "context_bytes": 4096,
            "preflight_reused": True,
        }
        planning = {
            "tasks": [
                {"id": "A", "blocked_by": []},
                {"id": "B", "blocked_by": ["A"]},
                {"id": "C", "blocked_by": []},
            ],
            "assurance": "balanced",
        }
        cases: tuple[tuple[str, Validator, Payload], ...] = (
            (
                "preflight-receipt",
                lambda payload: execution.validate_preflight_receipt(
                    payload["receipt"], payload["current"]
                ),
                {"receipt": preflight_receipt, "current": preflight_current},
            ),
            ("linear-readback", execution.linear_readback_plan, readback),
            ("completion-receipt", execution.validate_completion_receipt, completion),
            (
                "planner-batches",
                lambda payload: execution.planner_batches(payload["tasks"], payload["assurance"]),
                planning,
            ),
        )
        for name, validator, payload in cases:
            with self.subTest(name=name):
                self._exercise(name, validator, payload)

    def test_runtime_routing_state_and_verification_fail_closed_under_deep_mutation(self) -> None:
        effective = human_effective_policy("enabled", "project-default", 1)
        disabled = human_effective_policy()
        gate = human_gate(effective)
        checklist = human_checklist(effective)
        policy = human_project_policy()
        policy_marker = (
            "<!-- linear-spanks:human-verification-policy "
            + json.dumps(policy, sort_keys=True, separators=(",", ":"))
            + " -->"
        )
        gate_marker = (
            "<!-- linear-spanks:human-verification-gate "
            + json.dumps(gate, sort_keys=True, separators=(",", ":"))
            + " -->"
        )
        repair = human_repair()
        fail_preview = canonical_hash(
            {
                "operation": "fail",
                "project_id": "project-1",
                "milestone_id": "milestone-1",
                "checklist_id": checklist["checklist_id"],
                "gate_issue_id": gate["issue_id"],
                "reason": repair["reason"],
                "repair_task": repair,
            }
        )
        previous = human_effective_policy("enabled", "project-default", 1)
        current = human_effective_policy("disabled", "project-default", 2)
        bypass_reason = "Approved emergency release bypass"
        bypass_preview = canonical_hash(
            {
                "operation": "bypass",
                "project_id": "project-1",
                "milestone_id": "milestone-1",
                "checklist_id": "checklist-1",
                "gate_issue_id": "ENG-999",
                "reason": bypass_reason,
                "from_policy_hash": previous["policy_hash"],
                "to_policy_hash": current["policy_hash"],
            }
        )
        enabling_preview = approved_human_preview("enabled", [_affected_row()])
        disabling_preview = approved_human_preview(
            "disabled",
            [
                _affected_row(
                    stage="milestone-verified",
                    before="enabled",
                    after="disabled",
                    gate_id="ENG-999",
                    gate_action="cancel",
                    checklist_id="checklist-1",
                    checklist_action="bypass",
                )
            ],
            reason="Approved bypass",
        )
        projection = copy.deepcopy(self.artifacts["milestone-runtime-projection"])
        runtime_reference = {
            key: projection[key]
            for key in (
                "schema_version",
                "runtime_id",
                "milestone_id",
                "revision",
                "storage_source",
                "projection_hash",
            )
        }
        comment_projection = copy.deepcopy(projection)
        comment_projection["storage_source"] = "managed-comment"
        comment_projection["projection_hash"] = canonical_hash(
            {key: value for key, value in comment_projection.items() if key != "projection_hash"}
        )
        binding = dict.fromkeys(
            (
                "scope",
                "acceptance",
                "dependencies",
                "authorization",
                "migration_policy",
                "project_policy",
            ),
            _DIGEST_A,
        )
        loop_receipts = [
            {
                "event_id": "event-1",
                "session_id": "session-1",
                "persisted": True,
                "read_back": True,
            }
        ]
        findings = {
            "milestone_id": "milestone-1",
            "session_id": "test-session-1",
            "findings": ["API response changed"],
            "existing_session_ids": [],
            "candidate_owners": ["ENG-1"],
            "changed_provided_surfaces": ["api#result"],
            "unfinished_plans": [{"task_id": "ENG-2", "consumed_surfaces": ["api#result"]}],
        }
        command_limits = execution.execution_envelope("run-task")["context"]
        repository_scan = execution.execution_envelope("run-task")["repository_scan"]

        def scope(limits: Payload) -> Payload:
            return {
                "estimated_tokens": 100,
                "context_bytes": 400,
                "metrics": {key: 0 for key in limits if key not in {"profile", "max_input_tokens"}},
                "measured": True,
            }

        decision = {
            "schema_version": 1,
            "command": "run-task",
            "requested_assurance": "balanced",
            "harness": "codex",
            "scan_tier": repository_scan["tier"],
            "context": {
                "command": scope(command_limits),
                "planner": None,
                "repository": scope(repository_scan["context"]),
                "large_matrix": False,
                "near_limit": False,
            },
            "assessment": assessment_fixture("low"),
            "current_plan": {"present": True, "stale": False, "revision": "plan-1"},
            "detected_drift": False,
            "preflight": None,
            "planning_tasks": [],
        }
        cases: tuple[tuple[str, Validator, Payload], ...] = (
            ("routing-assessment", routing.tier_recommendation, assessment_fixture("low")),
            ("routing-decision", routing.orchestration_decision, decision),
            (
                "autopilot-policy",
                runtime.validate_guarded_autopilot_binding,
                self.artifacts["autopilot-policy"],
            ),
            (
                "runtime-projection",
                runtime.validate_milestone_runtime,
                self.artifacts["milestone-runtime-projection"],
            ),
            (
                "runtime-reference",
                runtime.validate_milestone_runtime_reference,
                runtime_reference,
            ),
            (
                "runtime-storage",
                runtime.reconcile_milestone_runtime_storage,
                {
                    "milestone_id": "milestone-1",
                    "documents_available": True,
                    "documents": [projection],
                    "comments": [],
                },
            ),
            (
                "runtime-migration",
                runtime.migrate_milestone_runtime_projection,
                {
                    "milestone_id": "milestone-1",
                    "documents_available": False,
                    "documents": [],
                    "comments": [comment_projection],
                    "description": "# Human milestone objective\n",
                },
            ),
            (
                "autopilot-operation",
                runtime.validate_autopilot_policy,
                {
                    "policy_binding": binding,
                    "current_binding": copy.deepcopy(binding),
                    "operation": "safe-plan-refresh",
                },
            ),
            (
                "milestone-run-mode",
                runtime.resolve_milestone_run_mode,
                {
                    "command": "run-milestone-loop",
                    "autopilot": False,
                    "until": ["blocked"],
                    "max_events": 20,
                    "repair_safe": False,
                    "isolated_worktree": True,
                },
            ),
            (
                "autopilot-loop",
                runtime.validate_autopilot_loop,
                {
                    "max_events": 20,
                    "event_count": 1,
                    "until": ["approval-required", "blocked", "milestone-done"],
                    "observed_stop": None,
                    "receipts": loop_receipts,
                    "isolated_worktree": True,
                },
            ),
            ("milestone-findings", runtime.validate_milestone_findings, findings),
            (
                "state-marker",
                lambda payload: state.validate_marker_semantics(payload),
                self.artifacts["state-marker"],
            ),
            ("human-policy", verification.validate_human_project_policy, human_project_policy()),
            (
                "human-override",
                verification.validate_human_milestone_override,
                human_milestone_override(),
            ),
            ("effective-policy", verification.validate_effective_human_policy, effective),
            ("human-gate", verification.validate_human_gate, human_gate(effective)),
            (
                "human-checklist",
                verification.validate_human_checklist,
                human_checklist(effective),
            ),
            ("human-repair", verification.validate_human_repair_task, human_repair()),
            (
                "policy-resolution",
                verification.resolve_human_verification_policy,
                {
                    "project_id": "project-1",
                    "milestone_id": "milestone-1",
                    "project_policy": policy,
                    "milestone_override": human_milestone_override(),
                },
            ),
            (
                "policy-document",
                verification.check_human_policy_document,
                {
                    "project_id": "project-1",
                    "document_capability": True,
                    "for_mutation": True,
                    "documents": [
                        {
                            "id": "document-1",
                            "title": verification.human_verification_contract()["project_policy"][
                                "document_title"
                            ],
                            "body": policy_marker,
                        }
                    ],
                },
            ),
            (
                "enabling-preview",
                verification.validate_human_verification_preview,
                enabling_preview,
            ),
            (
                "disabling-preview",
                verification.validate_human_verification_preview,
                disabling_preview,
            ),
            (
                "gate-filter",
                verification.filter_human_verification_gates,
                {
                    "issues": [
                        {"id": "ENG-1", "description": "Regular task"},
                        {"id": "ENG-999", "description": gate_marker},
                    ]
                },
            ),
            (
                "verify-action",
                verification.validate_human_verification_action,
                {
                    "operation": "verify",
                    "effective_policy": effective,
                    "milestone_stage": "implementing",
                    "machine_verification_revision": 4,
                    "gate": gate,
                    "checklist": checklist,
                },
            ),
            (
                "confirm-action",
                verification.validate_human_verification_action,
                {
                    "operation": "confirm",
                    "effective_policy": effective,
                    "milestone_stage": "milestone-verified",
                    "checklist": checklist,
                    "gate": gate,
                    "human_confirmed": True,
                    "gate_state_read_back": "Done",
                    "checklist_status_read_back": "confirmed",
                    "linear_milestone_completed": True,
                },
            ),
            (
                "fail-action",
                verification.validate_human_verification_action,
                {
                    "operation": "fail",
                    "effective_policy": effective,
                    "milestone_stage": "milestone-verified",
                    "checklist": checklist,
                    "gate": gate,
                    "reason": repair["reason"],
                    "repair_task": repair,
                    "existing_repair_tasks": [],
                    "preview_hash": fail_preview,
                    "approved_hash": fail_preview,
                    "checklist_status_read_back": "failed",
                    "gate_state_read_back": "In Progress",
                },
            ),
            (
                "bypass-action",
                verification.validate_human_verification_action,
                {
                    "operation": "bypass",
                    "effective_policy": current,
                    "previous_effective_policy": previous,
                    "milestone_stage": "milestone-verified",
                    "checklist": human_checklist(previous),
                    "gate": human_gate(previous),
                    "reason": bypass_reason,
                    "preview_hash": bypass_preview,
                    "approved_hash": bypass_preview,
                    "gate_state_read_back": "Canceled",
                    "checklist_status_read_back": "bypassed",
                    "human_confirmation_recorded": False,
                },
            ),
            (
                "disabled-wrap-action",
                verification.validate_human_verification_action,
                {
                    "operation": "wrap",
                    "effective_policy": disabled,
                    "milestone_stage": "milestone-verified",
                    "gate": None,
                    "checklist": None,
                },
            ),
            (
                "orchestration-policy-binding",
                lambda payload: verification.validate_orchestration_policy_binding(
                    payload["binding"], payload["effective"]
                ),
                {"binding": human_policy_binding(), "effective": disabled},
            ),
        )
        for name, validator, payload in cases:
            with self.subTest(name=name):
                self._exercise(name, validator, payload)


if __name__ == "__main__":
    unittest.main()
