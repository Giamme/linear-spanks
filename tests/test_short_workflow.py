from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from typing import Any

from linear_spanks.core.errors import LinearSpanksError
from linear_spanks.core.hashing import sha256_digest
from linear_spanks.domains import context, orchestration, reviews, routing, runtime
from linear_spanks.domains.artifacts import artifact_codecs

from tests import test_contract_incremental_runtime as incremental_tests
from tests import test_contract_routing_assurance as assurance_tests
from tests.contract_support import (
    assessment_fixture,
    isolation_receipt_fixture,
    role_handoff_fixture,
    run_contract,
    task_attempt_fixture,
    verification_ledger_fixture,
)


def current_verification(workflow: dict[str, Any]) -> dict[str, Any]:
    ledger = verification_ledger_fixture()
    ledger["schema_version"] = 2
    ledger["plan_revision"] = workflow["plan_drift"]["current"]["plan_revision"]
    ledger["execution_binding"] = runtime.task_next(workflow)["verification_binding"]
    for finding in ledger["findings"]:
        finding.update({"classification": "blocking", "requirement": "AC1"})
    return ledger


def workflow_fixture() -> dict[str, Any]:
    plan = incremental_tests.IncrementalMilestoneAutopilotTest().plan()
    return {
        "schema_version": 1,
        "task_id": "ENG-1",
        "roles": {"executor": "logical-task-executor", "verifier": "task-verifier-ENG-1"},
        "candidate_commit": "d" * 40,
        "decision": assurance_tests.AssuranceProfileTest().decision_payload(
            "run-task", "low", "balanced"
        ),
        "plan_drift": {"plan": plan, "current": copy.deepcopy(plan), "changed_plan_fields": []},
        "progress": {"attempts": []},
        "verification_commands": [
            item["command"] for item in verification_ledger_fixture()["verification_runs"]
        ],
        "observations": {},
        "approval_satisfied": True,
        "blockers": [],
    }


def refresh_request(workflow: dict[str, Any]) -> dict[str, Any]:
    return {
        "project_id": "P",
        "source": "source/current",
        "expected_source_hash": sha256_digest(workflow["plan_drift"]),
        "expected_receipt_hash": sha256_digest(None),
        "authorization": {
            "task_id": "ENG-1",
            "material_binding": reviews.evidence_bindings(workflow["plan_drift"]["current"])[
                "material"
            ],
        },
    }


def bound_handoff(workflow: dict[str, Any]) -> dict[str, Any]:
    decision = runtime.task_next(workflow)
    handoff = {
        **role_handoff_fixture("task-executor"),
        "schema_version": 2,
        "plan_revision": workflow["plan_drift"]["current"]["plan_revision"],
        "repository_head": workflow["candidate_commit"],
        "execution_policy": decision["execution_policy"],
        "workflow_hash": decision["workflow_hash"],
    }
    packet = context.compile_packet(
        {
            "body": {
                "instructions": "Execute the approved task and self-verify once.",
                "skills": [],
                "plan": workflow["plan_drift"]["current"],
                "evidence": [],
                "bindings": {
                    "handoff_hash": sha256_digest(
                        {key: value for key, value in handoff.items() if key != "context_tokens"}
                    ),
                    "task_workflow": sha256_digest(workflow),
                },
            },
            "default_tokens": 12000,
        }
    )
    handoff["context_tokens"] = packet["measurement"]["estimated_tokens"]
    return {"handoff": handoff, "packet": packet, "workflow": workflow}


class ShortWorkflowTest(unittest.TestCase):
    def test_default_small_edit_has_no_separate_planner_or_reviewer(self) -> None:
        request = assurance_tests.AssuranceProfileTest().decision_payload(
            "run-task", "low", "balanced"
        )
        result = routing.decide(request)
        self.assertEqual(result["planner"]["runs"], 0)
        self.assertEqual(result["reviewer_runs"], 0)
        self.assertEqual(result["execution_path"], "small-change")

    def test_safe_refresh_is_an_action_in_the_current_run(self) -> None:
        request = assurance_tests.AssuranceProfileTest().decision_payload(
            "run-task", "low", "balanced", detected_drift="safe-refresh"
        )
        result = routing.decide(request)
        self.assertIsNone(result["stop_result"])
        self.assertEqual(result["next_action"], "refresh-evidence")
        self.assertFalse(result["dispatch_ready"])

    def test_unchanged_failures_diagnose_without_replanning(self) -> None:
        attempt = {"result": "failed", "fingerprint": "same", "acceptance": {"AC1": "failing"}}
        result = context.repair_action({"attempts": [attempt, attempt]})
        self.assertEqual(result["next_action"], "diagnose")
        self.assertNotEqual(result.get("code"), "REPLAN_REQUIRED")

    def test_risk_policy_is_shared_by_loop_attempts(self) -> None:
        policy = routing.task_policy(
            {"assessment": assessment_fixture("low"), "assurance": "balanced"}
        )
        attempt = {
            **task_attempt_fixture(0, "passed"),
            "schema_version": 2,
            "execution_policy": policy,
            "verifier_strength": None,
            "verification": json.loads(
                json.dumps(verification_ledger_fixture()).replace("d" * 40, "1" * 40)
            ),
            "progress": {
                "attempts": [
                    {
                        "result": "passed",
                        "fingerprint": "passed",
                        "acceptance": {"AC1": "passing"},
                        "executor_strength": "low",
                    }
                ]
            },
        }
        self.assertEqual(
            orchestration.validate_attempt(attempt)["next_action"], "verified-pending-integration"
        )

    def test_legacy_findings_block_and_new_suggestions_do_not(self) -> None:
        ledger = verification_ledger_fixture()
        suggestion = {
            "finding_id": "style-1",
            "status": "open",
            "summary": "Optional naming preference",
            "introduced_commit": ledger["candidate_commit"],
            "resolved_commit": None,
            "evidence": "Existing name satisfies the repository conventions.",
            "classification": "suggestion",
            "requirement": None,
        }
        ledger["schema_version"] = 2
        ledger["execution_binding"] = sha256_digest({})
        ledger["findings"] = [suggestion]
        self.assertEqual(orchestration.validate_ledger(ledger)["final_result"], "passed")
        legacy = copy.deepcopy(ledger)
        legacy["schema_version"] = 1
        del legacy["execution_binding"]
        for field in ("classification", "requirement"):
            del legacy["findings"][0][field]
        with self.assertRaises(LinearSpanksError):
            orchestration.validate_ledger(legacy)

    def test_risky_unknown_and_explicit_strict_do_not_use_short_path(self) -> None:
        for fixture, assurance in [
            ("high-critical", "balanced"),
            ("low", "strict"),
            ("uncertain-low", "balanced"),
        ]:
            with self.subTest(fixture=fixture, assurance=assurance):
                result = routing.task_policy(
                    {"assessment": assessment_fixture(fixture), "assurance": assurance}
                )
                self.assertEqual(result["execution_path"], "planned")
                self.assertTrue(result["review"]["required"])
        malformed = assessment_fixture("low")
        del malformed["uncertainty"]
        with self.assertRaises(LinearSpanksError):
            routing.task_policy({"assessment": malformed, "assurance": "balanced"})

    def test_refresh_persists_once_and_resumes_without_plan_revision_change(self) -> None:
        workflow = workflow_fixture()
        workflow["plan_drift"]["current"]["target_file_hashes"]["src/a.py"] = "sha256:" + "f" * 64
        self.assertEqual(runtime.task_next(workflow)["next_action"], "refresh-evidence")
        store = context.PreparedDocuments({"source/current": workflow["plan_drift"]})
        request = refresh_request(workflow)
        first = reviews.refresh_evidence(store, request)
        second = reviews.refresh_evidence(store, request)
        self.assertEqual(first["receipt"], second["receipt"])
        self.assertEqual(len(store.writes), 1)
        self.assertEqual(first["receipt"]["plan_revision"], 1)
        workflow["refresh"] = first
        decision = runtime.task_next(workflow)
        self.assertEqual(decision["next_action"], "implement")
        self.assertTrue(decision["refresh_verified"])
        context.validate_dispatch(bound_handoff(workflow))
        workflow["refresh"]["read_back"] = False
        self.assertEqual(runtime.task_next(workflow)["next_action"], "refresh-evidence")

    def test_refresh_rejects_concurrent_changes_and_material_drift(self) -> None:
        workflow = workflow_fixture()
        request = refresh_request(workflow)
        store = context.PreparedDocuments({"source/current": workflow["plan_drift"]})
        request["expected_source_hash"] = sha256_digest("old")
        with self.assertRaises(LinearSpanksError):
            reviews.refresh_evidence(store, request)
        request = refresh_request(workflow)
        workflow["plan_drift"]["current"]["acceptance_contract_hash"] = "sha256:" + "e" * 64
        store = context.PreparedDocuments({"source/current": workflow["plan_drift"]})
        request = refresh_request(workflow)
        with self.assertRaises(LinearSpanksError) as error:
            reviews.refresh_evidence(store, request)
        self.assertEqual(error.exception.code, "REPLAN_REQUIRED")
        self.assertFalse(store.writes)
        self.assertEqual(runtime.task_next(workflow)["next_action"], "replan")

    def test_diagnosis_is_once_per_evidence_state_and_attempts_are_not_reset(self) -> None:
        failed = {"result": "failed", "fingerprint": "bug", "acceptance": {"AC1": "failing"}}
        progress = {"attempts": [failed, failed]}
        result = context.repair_action(progress)
        progress["diagnosis"] = {
            "failure_binding": result["diagnosis_binding"],
            "after_attempt": 2,
            "new_approach": "",
            "new_evidence": [],
        }
        self.assertEqual(context.repair_action(progress)["code"], "REPAIR_STALLED")
        progress["diagnosis"]["new_approach"] = "Use the reproduced boundary failure"
        self.assertEqual(context.repair_action(progress)["next_action"], "automatic-repair")
        progress["attempts"].append(failed)
        self.assertEqual(context.repair_action(progress)["code"], "REPAIR_STALLED")
        progress["attempts"].append(failed)
        self.assertEqual(context.repair_action(progress)["next_action"], "user-model-selection")
        environment = {**failed, "failure_class": "environment"}
        self.assertEqual(
            context.repair_action({"attempts": [environment]})["next_action"],
            "prerequisite-recovery",
        )

    def test_dispatch_recompiles_after_policy_or_approval_drift(self) -> None:
        workflow = workflow_fixture()
        dispatch = bound_handoff(workflow)
        context.validate_dispatch(dispatch)
        workflow["approval_satisfied"] = False
        with self.assertRaises(LinearSpanksError):
            context.validate_dispatch(dispatch)
        workflow["approval_satisfied"] = True
        dispatch["handoff"]["execution_policy"]["executor_strength"] = "high"
        with self.assertRaises(ValueError):
            context.validate_dispatch(dispatch)

    def test_observations_reuse_independently_and_inspection_matches_execution(self) -> None:
        workflow = workflow_fixture()
        binding = dict.fromkeys(context.REUSE_BINDINGS, "same")
        workflow["observations"] = {
            "toolchain": {"previous": binding, "current": binding},
            "target": {"previous": binding, "current": {**binding, "source_hashes": "changed"}},
        }
        decision = runtime.task_next(workflow)
        self.assertEqual(decision["stale_evidence"], ["target"])
        self.assertTrue(decision["reuse"]["toolchain"]["reusable"])
        inspection = runtime.inspect(
            {
                "scope": "task",
                "target": "ENG-1",
                "event_input": workflow,
                "context": {
                    "scope": "task",
                    "target": "ENG-1",
                    "default_tokens": 12000,
                    "body": {},
                    "events_since_checkpoint": 0,
                    "sources": {},
                },
            }
        )
        self.assertEqual(inspection["next_event"], decision)

    def test_unchanged_completed_candidate_schedules_no_model_work(self) -> None:
        workflow = workflow_fixture()
        ledger = verification_ledger_fixture()
        ledger["plan_revision"] = 1
        ledger["execution_binding"] = runtime.task_next(workflow)["verification_binding"]
        ledger["schema_version"] = 2
        for finding in ledger["findings"]:
            finding.update({"classification": "blocking", "requirement": "AC1"})
        integration = isolation_receipt_fixture("integrated")
        integration.update({"plan_revision": 1, "child_commit": ledger["candidate_commit"]})
        workflow.update({"verification": ledger, "integration": integration})
        first = runtime.task_next(workflow)
        self.assertEqual(first["next_action"], "completed")
        self.assertFalse(first["dispatch_ready"])
        self.assertEqual(first["routes"], [])
        self.assertEqual(runtime.task_next(workflow), first)
        workflow["candidate_commit"] = "e" * 40
        self.assertEqual(runtime.task_next(workflow)["next_action"], "implement")

    def test_suggestions_roundtrip_without_weakening_acceptance_or_requirements(self) -> None:
        ledger = verification_ledger_fixture()
        ledger["schema_version"] = 2
        ledger["execution_binding"] = sha256_digest({})
        codec = artifact_codecs()["verification-ledger"]
        decoded = codec.decode(ledger)
        self.assertEqual(codec.decode(codec.encode_v2(decoded)).payload["schema_version"], 2)
        ledger["acceptance_criteria"][0]["status"] = "failing"
        with self.assertRaises(LinearSpanksError):
            orchestration.validate_ledger(ledger)

    def test_incremental_evidence_refresh_does_not_review_unrelated_sinks(self) -> None:
        factory = incremental_tests.IncrementalMilestoneAutopilotTest()
        tasks = [
            {
                "id": "ENG-1",
                "dependencies": [],
                "execution_footprint": factory.footprint(["src/a.py"]),
                "final_sink": False,
            },
            {
                "id": "ENG-2",
                "dependencies": ["ENG-1"],
                "execution_footprint": factory.footprint(["src/b.py"]),
                "final_sink": True,
            },
            {
                "id": "ENG-3",
                "dependencies": [],
                "execution_footprint": factory.footprint(["src/c.py"]),
                "final_sink": True,
            },
        ]
        change = workflow_fixture()["plan_drift"]
        change["current"]["target_file_hashes"]["src/a.py"] = factory.digest_c
        request = {
            "tasks": tasks,
            "mode": "incremental",
            "changed_task_ids": ["ENG-1"],
            "plan_changes": {"ENG-1": change},
        }
        self.assertEqual(reviews.coverage(request)["covered_task_ids"], ["ENG-1"])
        change["current"]["acceptance_contract_hash"] = factory.digest_b
        self.assertEqual(reviews.coverage(request)["covered_task_ids"], ["ENG-1", "ENG-2"])
        self.assertEqual(
            reviews.coverage({"tasks": tasks, "mode": "incremental", "changed_task_ids": []})[
                "covered_task_ids"
            ],
            [],
        )

    def test_hundred_workflow_cycles_have_bounded_dispatch_and_analysis(self) -> None:
        budgets = json.loads(
            (Path(__file__).parent / "fixtures" / "workflow-replay-budgets.json").read_text()
        )
        metrics = {
            "cycles": budgets["cycles"],
            "planner_runs": 0,
            "reviewer_runs": 0,
            "executor_dispatches": 0,
            "duplicate_writes": 0,
            "context_bytes": 0,
            "repeated_analysis": 0,
            "repair_dispatches": 0,
            "completion_replays": 0,
        }
        binding = dict.fromkeys(context.REUSE_BINDINGS, "stable")
        for index in range(metrics["cycles"]):
            workflow = workflow_fixture()
            workflow["candidate_commit"] = f"{index + 1:040x}"
            workflow["observations"] = {"toolchain": {"previous": binding, "current": binding}}
            decision = runtime.task_next(workflow)
            dispatch = bound_handoff(workflow)
            measured = context.validate_dispatch(dispatch)
            metrics["planner_runs"] += decision["planner_runs"]
            metrics["reviewer_runs"] += decision["reviewer_runs"]
            metrics["executor_dispatches"] += int(decision["dispatch_ready"])
            metrics["context_bytes"] = max(
                metrics["context_bytes"], measured["measurement"]["bytes"]
            )
            metrics["repeated_analysis"] += int(not decision["reuse"]["toolchain"]["reusable"])
            store = context.PreparedDocuments({"source/current": workflow["plan_drift"]})
            request = refresh_request(workflow)
            reviews.refresh_evidence(store, request)
            writes = len(store.writes)
            reviews.refresh_evidence(store, request)
            metrics["duplicate_writes"] += len(store.writes) - writes
            ledger = json.loads(
                json.dumps(verification_ledger_fixture()).replace(
                    "d" * 40, workflow["candidate_commit"]
                )
            )
            ledger["plan_revision"] = 1
            ledger["execution_binding"] = runtime.task_next(workflow)["verification_binding"]
            ledger["schema_version"] = 2
            for finding in ledger["findings"]:
                finding.update({"classification": "blocking", "requirement": "AC1"})
            integration = isolation_receipt_fixture("integrated")
            integration.update({"plan_revision": 1, "child_commit": workflow["candidate_commit"]})
            workflow.update({"verification": ledger, "integration": integration})
            finished = runtime.task_next(workflow)
            self.assertEqual(finished["next_action"], "completed")
            self.assertEqual(finished, runtime.task_next(workflow))
            self.assertEqual(finished["routes"], [])
            metrics["completion_replays"] += 1

            repair = workflow_fixture()
            failure = {
                "result": "failed",
                "fingerprint": f"failure-{index}",
                "acceptance": {"AC1": "failing"},
                "executor_strength": "low",
            }
            repair["progress"]["attempts"] = [failure]
            repair_decision = runtime.task_next(repair)
            attempted = {
                **task_attempt_fixture(0),
                "schema_version": 2,
                "execution_policy": repair_decision["execution_policy"],
                "verifier_strength": None,
                "progress": repair["progress"],
            }
            self.assertEqual(
                orchestration.validate_attempt(attempted)["next_action"], "automatic-repair"
            )
            self.assertEqual(repair_decision["next_action"], "automatic-repair")
            self.assertEqual(
                repair_decision["review_scope"], "affected-acceptance-and-changed-areas"
            )
            context.validate_dispatch(bound_handoff(repair))
            metrics["repair_dispatches"] += 1
        self.assertEqual(metrics["planner_runs"], 0)
        self.assertEqual(metrics["reviewer_runs"], 0)
        self.assertEqual(metrics["executor_dispatches"], 100)
        self.assertEqual(metrics["duplicate_writes"], 0)
        self.assertEqual(metrics["repeated_analysis"], 0)
        self.assertEqual(metrics["repair_dispatches"], budgets["cycles"])
        self.assertEqual(metrics["completion_replays"], budgets["cycles"])
        for metric, ceiling in budgets["ceilings"].items():
            self.assertLessEqual(metrics[metric], ceiling, metric)
        self.replay_metrics = metrics

    def test_parent_selectors_use_task_decisions_and_do_not_loop_on_blocked_tasks(self) -> None:
        workflow = workflow_fixture()
        milestone = {
            "project_coordination_required": False,
            "approval_pending": False,
            "executing_task_ids": [],
            "verifying_task_ids": [],
            "verified_task_ids": [],
            "ready_task_ids": ["ENG-1"],
            "milestone_ready_to_wrap": False,
            "eligible_milestone_work": True,
            "milestone_complete": False,
            "task_workflows": [workflow],
        }
        project = {
            "project_drift": False,
            "cross_milestone_conflict": False,
            "approval_pending": False,
            "executing_task_ids": [],
            "verifying_task_ids": [],
            "verified_task_ids": [],
            "ready_task_ids": ["ENG-1"],
            "milestones_ready_to_wrap": [],
            "eligible_milestone_ids": ["M"],
            "project_complete": False,
            "task_workflows": [workflow],
        }
        for selector, request in [
            (orchestration.milestone_next, milestone),
            (orchestration.project_next, project),
        ]:
            self.assertEqual(selector(request)["event"], "task-execute")
            workflow["blockers"] = ["unavailable prerequisite"]
            self.assertEqual(selector(request)["event"], "blocked")
            workflow["blockers"] = []
            workflow["approval_satisfied"] = False
            self.assertEqual(selector(request)["event"], "await-approval")
            workflow["approval_satisfied"] = True

    def test_diagnosis_cannot_mutate_source_and_environment_recovery_only_reverifies(self) -> None:
        workflow = workflow_fixture()
        failure = {"result": "failed", "fingerprint": "same", "acceptance": {"AC1": "failing"}}
        workflow["progress"]["attempts"] = [failure, failure]
        self.assertEqual(runtime.task_next(workflow)["next_action"], "diagnose")
        capability = {
            "role": "task-executor",
            "operation": "edit-assigned-worktree",
            "tracked_source_write": True,
            "worktree_path": "/worktrees/task",
            "assigned_worktree": "/worktrees/task",
            "comment_marker": None,
            "workflow": workflow,
        }
        with self.assertRaises(LinearSpanksError):
            orchestration.validate_capability(capability)
        environment = {**failure, "failure_class": "environment"}
        workflow["progress"] = {
            "attempts": [environment] * 4,
            "prerequisite_recovery": {"fingerprint": "same", "evidence": ["toolchain-restored"]},
        }
        self.assertEqual(runtime.task_next(workflow)["next_action"], "verify")
        workflow["progress"]["prerequisite_recovery"]["evidence"] = []
        with self.assertRaises(LinearSpanksError):
            runtime.task_next(workflow)

    def test_suggestions_do_not_create_milestone_repair_tasks(self) -> None:
        finding = {
            "summary": "Optional rename",
            "classification": "suggestion",
            "requirement": None,
            "evidence": "Current name follows conventions",
        }
        request = {
            "milestone_id": "M",
            "session_id": "S",
            "findings": [finding],
            "existing_session_ids": [],
            "candidate_owners": ["ENG-1"],
            "changed_provided_surfaces": [],
            "unfinished_plans": [],
        }
        result = reviews.findings(request)
        self.assertEqual(result["action"], "none")
        self.assertEqual(result["repair_task_count"], 0)
        finding.update(
            {"classification": "blocking", "requirement": "AC1", "evidence": "Focused check fails"}
        )
        self.assertEqual(reviews.findings(request)["action"], "reopen-owner")

    def test_failed_refresh_readback_is_retryable_without_duplicate_writes(self) -> None:
        class Interrupted(context.PreparedDocuments):
            def put(self, key: str, value: dict[str, Any], expected_hash: str) -> None:
                super().put(key, value, expected_hash)
                raise OSError("interrupted after provider accepted the write")

        workflow = workflow_fixture()
        store = Interrupted({"source/current": workflow["plan_drift"]})
        request = refresh_request(workflow)
        with self.assertRaises(OSError):
            reviews.refresh_evidence(store, request)
        self.assertEqual(reviews.refresh_evidence(store, request)["status"], "unchanged")
        self.assertEqual(len(store.writes), 1)

        class FailedReadback(context.PreparedDocuments):
            def read(self, key: str) -> dict[str, Any] | None:
                if self.writes and key.endswith("/execution-evidence"):
                    return None
                return super().read(key)

        failing = FailedReadback({"source/current": workflow["plan_drift"]})
        with self.assertRaises(LinearSpanksError) as error:
            reviews.refresh_evidence(failing, request)
        self.assertEqual(error.exception.code, "CONTEXT_READ_BACK_FAILED")
        prepared = reviews.prepare_refresh(
            {"documents": {"source/current": workflow["plan_drift"]}, "request": request}
        )
        self.assertFalse(prepared["persistence_verified"])
        self.assertFalse(prepared["result"]["read_back"])

    def test_no_plan_records_compact_plan_and_regressions_are_not_progress(self) -> None:
        workflow = workflow_fixture()
        workflow["plan_drift"] = None
        result = runtime.task_next(workflow)
        self.assertEqual(result["next_action"], "record-plan")
        self.assertEqual(result["planner_runs"], 0)
        self.assertFalse(result["dispatch_ready"])
        before = {
            "result": "failed",
            "fingerprint": "same",
            "acceptance": {"AC1": "passing", "AC2": "failing"},
        }
        after = {**before, "acceptance": {"AC1": "regressed", "AC2": "failing"}}
        self.assertEqual(
            context.repair_action({"attempts": [before, after]})["next_action"], "diagnose"
        )

    def test_new_attempts_reject_missing_verification_and_unapproved_model_changes(self) -> None:
        policy = routing.task_policy(
            {"assessment": assessment_fixture("high-critical"), "assurance": "balanced"}
        )
        failed = {
            "result": "failed",
            "fingerprint": "same",
            "acceptance": {"AC1": "failing"},
            "executor_strength": "low",
        }
        attempt = {
            **task_attempt_fixture(1),
            "schema_version": 2,
            "execution_policy": policy,
            "executor_strength": "high",
            "progress": {"attempts": [failed, {**failed, "executor_strength": "high"}]},
        }
        with self.assertRaises(LinearSpanksError) as error:
            orchestration.validate_attempt(attempt)
        self.assertEqual(error.exception.code, "MODEL_SELECTION_REQUIRED")
        attempt = {
            **task_attempt_fixture(0, "passed"),
            "schema_version": 2,
            "execution_policy": policy,
            "executor_strength": "high",
            "progress": {
                "attempts": [
                    {
                        **failed,
                        "result": "passed",
                        "executor_strength": "high",
                        "acceptance": {"AC1": "passing"},
                    }
                ]
            },
        }
        with self.assertRaises(LinearSpanksError):
            orchestration.validate_attempt(attempt)

    def test_explicit_planning_and_verification_never_enter_implementation(self) -> None:
        workflow = workflow_fixture()
        workflow["decision"] = assurance_tests.AssuranceProfileTest().decision_payload(
            "plan-task", "low", "balanced"
        )
        with self.assertRaises(ValueError):
            runtime.task_next(workflow)
        replan = assurance_tests.AssuranceProfileTest().decision_payload(
            "replan-task", "low", "balanced", strict_context=True, detected_drift="material"
        )
        self.assertEqual(routing.decide(replan)["planner"]["runs"], 1)
        workflow["decision"] = assurance_tests.AssuranceProfileTest().decision_payload(
            "verify-task", "low", "balanced"
        )
        result = runtime.task_next(workflow)
        self.assertEqual(result["next_action"], "verify")
        self.assertEqual([route["role"] for route in result["routes"]], ["executor"])
        workflow["plan_drift"] = None
        self.assertEqual(runtime.task_next(workflow)["next_action"], "blocked")

    def test_required_review_dispatches_once_after_candidate_is_ready(self) -> None:
        workflow = workflow_fixture()
        workflow["decision"] = assurance_tests.AssuranceProfileTest().decision_payload(
            "run-task", "medium-interface", "balanced"
        )
        self.assertEqual(runtime.task_next(workflow)["reviewer_runs"], 0)
        workflow["candidate_ready"] = True
        result = runtime.task_next(workflow)
        self.assertEqual(result["reviewer_runs"], 1)
        self.assertEqual([route["role"] for route in result["routes"]], ["reviewer"])
        workflow["roles"]["verifier"] = workflow["roles"]["executor"]
        with self.assertRaises(ValueError):
            runtime.task_next(workflow)

    def test_changed_checks_and_toolchain_invalidate_verification_but_trace_does_not(self) -> None:
        workflow = workflow_fixture()
        binding = dict.fromkeys(context.REUSE_BINDINGS, "same")
        workflow["observations"] = {"toolchain": {"previous": binding, "current": dict(binding)}}
        workflow["verification"] = current_verification(workflow)
        self.assertEqual(runtime.task_next(workflow)["next_action"], "verified-pending-integration")
        workflow["plan_drift"]["current"]["trace_source_head"] = "another-unrelated-head"
        self.assertEqual(runtime.task_next(workflow)["next_action"], "verified-pending-integration")
        workflow["verification_commands"].append("new required check")
        self.assertEqual(runtime.task_next(workflow)["next_action"], "verify")
        workflow["verification_commands"].pop()
        workflow["observations"]["toolchain"]["current"]["toolchain"] = "new-version"
        self.assertEqual(runtime.task_next(workflow)["next_action"], "verify")

    def test_nonisolated_completion_uses_existing_readback_receipt(self) -> None:
        workflow = workflow_fixture()
        workflow["integration_required"] = False
        workflow["verification"] = current_verification(workflow)
        decision = runtime.task_next(workflow)
        self.assertEqual(decision["next_action"], "finalize-task")
        completion = {
            "harness": "codex",
            "worker_role": "executor",
            "configured_model_when_observable": None,
            "tier_enforcement_status": "enforced",
            "requested_strength": "low",
            "review_result": "self-verified",
            "requested_assurance": "balanced",
            "effective_assurance": "balanced",
            "assurance_escalation_reason": None,
            "planner_runs": 0,
            "reviewer_runs": 0,
            "delegated_roles": ["executor"],
            "linear_reads": 2,
            "linear_writes": 1,
            "linear_read_backs": 1,
            "context_bytes": 1000,
            "preflight_reused": True,
            "task_completion": {
                "schema_version": 1,
                "task_id": "ENG-1",
                "candidate_commit": workflow["candidate_commit"],
                "material_binding": decision["bindings"]["material"],
                "policy_hash": decision["execution_policy"]["policy_hash"],
                "issue_status": "Done",
                "issue_revision": "fresh-1",
                "completion_ref": "comment-1",
                "read_back": True,
            },
        }
        workflow["completion"] = completion
        self.assertEqual(runtime.task_next(workflow)["next_action"], "completed")
        completion["task_completion"]["read_back"] = False
        with self.assertRaises(ValueError):
            runtime.task_next(workflow)

    def test_authorized_model_selection_allows_one_repair_without_reset(self) -> None:
        workflow = workflow_fixture()
        failed = {
            "result": "failed",
            "fingerprint": "bug",
            "acceptance": {"AC1": "failing"},
            "executor_strength": "low",
        }
        workflow["progress"]["attempts"] = [failed] * 4
        self.assertEqual(runtime.task_next(workflow)["next_action"], "user-model-selection")
        request = {
            "task_id": "ENG-1",
            "automatic_attempts_completed": 4,
            "automatic_failures": 4,
            "previous_escalated_failure": False,
            "action": "run-selected-model",
            "user_approved": True,
            "selected_model": {
                "strength": "high",
                "model": "provider/strong",
                "harness": "codex",
                "capability": "enforced",
                "configured": True,
            },
        }
        workflow["model_selection"] = {"attempt_index": 4, "request": request}
        result = runtime.task_next(workflow)
        self.assertEqual(result["next_action"], "user-selected-repair")
        self.assertEqual(result["routes"][0]["requested_strength"], "high")
        context.validate_dispatch(bound_handoff(workflow))
        workflow["progress"]["attempts"].append({**failed, "executor_strength": "high"})
        with self.assertRaises(ValueError):
            runtime.task_next(workflow)

    def test_new_internal_operations_execute_through_the_json_cli(self) -> None:
        workflow = workflow_fixture()
        for command, payload in [
            ("task-next", workflow),
            ("task-policy", {"assessment": assessment_fixture("low"), "assurance": "balanced"}),
            (
                "refresh-prepare",
                {
                    "documents": {"source/current": workflow["plan_drift"]},
                    "request": refresh_request(workflow),
                },
            ),
        ]:
            result = run_contract(command, input_text=json.dumps(payload))
            self.assertEqual(result.returncode, 0, result.stderr)
            value = json.loads(result.stdout)
            if command == "task-next":
                self.assertEqual(value["next_action"], "implement")
            elif command == "task-policy":
                self.assertEqual(value["execution_path"], "small-change")
            else:
                self.assertFalse(value["persistence_verified"])
