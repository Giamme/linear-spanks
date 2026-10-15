from __future__ import annotations

from tests.contract_support import *


class ProjectOrchestrationContractTest(unittest.TestCase):
    def test_run_project_compiles_hierarchy_and_role_runtime_cards(self) -> None:
        envelope = run_contract("execution-envelope", "run-project")
        brief = run_contract("execution-brief", "run-project")
        controller = run_contract("runtime-card", "run-project")
        verifier = run_contract("project-role-card", "task-verifier")

        for result in (envelope, brief, controller, verifier):
            self.assertEqual(result.returncode, 0, result.stderr)
        envelope_payload = json.loads(envelope.stdout)
        brief_payload = json.loads(brief.stdout)
        self.assertEqual(envelope_payload["session_boundary"], "single-event")
        self.assertEqual(
            envelope_payload["project_orchestration"]["topology"][
                "project_orchestrators_per_project"
            ],
            1,
        )
        self.assertEqual(
            brief_payload["project_orchestration"]["roles"],
            PROJECT_ORCHESTRATION["topology"]["roles"],
        )
        self.assertIn(
            "references/parallel-execution.md",
            envelope_payload["required_references"],
        )
        self.assertIn(
            "templates/completion-handoff.md",
            envelope_payload["required_references"],
        )
        self.assertIsNotNone(brief_payload["runtime_card"])
        verifier_payload = json.loads(verifier.stdout)
        self.assertEqual(verifier_payload["policy"]["strength"], "risk-based")
        self.assertEqual(verifier_payload["policy"]["routing_role"], "reviewer")
        self.assertIn("verification_ledger", verifier_payload)

    def test_receipt_enforces_one_orchestrator_and_worker_pair_per_entity(self) -> None:
        valid = run_contract(
            "project-loop-receipt-check",
            input_text=json.dumps(project_loop_receipt_fixture()),
        )
        self.assertEqual(valid.returncode, 0, valid.stderr)

        duplicate = project_loop_receipt_fixture()
        duplicate["milestones"].append(
            {
                **duplicate["milestones"][0],
                "milestone_id": "milestone-2",
            }
        )
        rejected = run_contract("project-loop-receipt-check", input_text=json.dumps(duplicate))
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("orchestrator reused", rejected.stderr)

        duplicate_task = project_loop_receipt_fixture()
        duplicate_task["task_loops"].append(
            {
                **duplicate_task["task_loops"][0],
                "task_id": "ENG-2",
            }
        )
        rejected_task = run_contract(
            "project-loop-receipt-check", input_text=json.dumps(duplicate_task)
        )
        self.assertEqual(rejected_task.returncode, 2)
        self.assertIn("executor reused", rejected_task.stderr)

    def test_receipt_selection_resumes_one_and_rejects_ambiguity(self) -> None:
        receipt = project_loop_receipt_fixture()
        selection = {
            "project_id": "project-1",
            "project_revision": 7,
            "receipts": [receipt],
        }
        resumed = run_contract("project-loop-receipt-check", input_text=json.dumps(selection))
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertEqual(json.loads(resumed.stdout)["status"], "resume")

        second = json.loads(json.dumps(receipt))
        second["receipt_id"] = "project-loop-2"
        selection["receipts"].append(second)
        ambiguous = run_contract("project-loop-receipt-check", input_text=json.dumps(selection))
        self.assertEqual(ambiguous.returncode, 2)
        self.assertIn("PROJECT_ORCHESTRATION_RECEIPT_AMBIGUOUS", ambiguous.stderr)
        self.assertIn("project-loop-1, project-loop-2", ambiguous.stderr)

    def test_event_selection_uses_deterministic_precedence(self) -> None:
        payload = {
            "project_drift": False,
            "cross_milestone_conflict": False,
            "approval_pending": False,
            "executing_task_ids": [],
            "verifying_task_ids": ["ENG-1"],
            "verified_task_ids": ["ENG-2"],
            "ready_task_ids": ["ENG-3"],
            "milestones_ready_to_wrap": ["milestone-1"],
            "eligible_milestone_ids": ["milestone-2"],
            "project_complete": True,
        }
        verifying = run_contract("project-loop-next", input_text=json.dumps(payload))
        self.assertEqual(verifying.returncode, 0, verifying.stderr)
        self.assertEqual(json.loads(verifying.stdout)["event"], "task-verify")

        payload["project_drift"] = True
        reconcile = run_contract("project-loop-next", input_text=json.dumps(payload))
        self.assertEqual(json.loads(reconcile.stdout)["event"], "project-reconcile")

    def test_role_handoffs_are_bounded_and_exclude_raw_transcripts(self) -> None:
        for role in PROJECT_ORCHESTRATION["topology"]["roles"]:
            with self.subTest(role=role):
                result = run_contract(
                    "role-handoff-check", input_text=json.dumps(role_handoff_fixture(role))
                )
                self.assertEqual(result.returncode, 0, result.stderr)

        raw = role_handoff_fixture("task-verifier")
        raw["raw_transcript_included"] = True
        rejected = run_contract("role-handoff-check", input_text=json.dumps(raw))
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("raw transcripts are prohibited", rejected.stderr)

        overflow = role_handoff_fixture("project-orchestrator")
        overflow["context_tokens"] = profile_limit("project") + 1
        rejected_overflow = run_contract("role-handoff-check", input_text=json.dumps(overflow))
        self.assertEqual(rejected_overflow.returncode, 2)
        self.assertIn("CONTEXT_OVERFLOW", rejected_overflow.stderr)

        receipt = project_loop_receipt_fixture()
        bound = role_handoff_fixture("task-verifier")
        bound["logical_role_id"] = receipt["task_loops"][0]["verifier_id"]
        with tempfile.TemporaryDirectory() as directory:
            receipt_path = Path(directory) / "receipt.json"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            bound_result = run_contract(
                "role-handoff-check",
                "--receipt",
                str(receipt_path),
                input_text=json.dumps(bound),
            )
            self.assertEqual(bound_result.returncode, 0, bound_result.stderr)

            bound["logical_role_id"] = "task-verifier-other"
            drift = run_contract(
                "role-handoff-check",
                "--receipt",
                str(receipt_path),
                input_text=json.dumps(bound),
            )
            self.assertEqual(drift.returncode, 2)
            self.assertIn("logical role binding drift", drift.stderr)

    def test_role_capabilities_limit_source_and_linear_writes(self) -> None:
        executor = {
            "role": "task-executor",
            "operation": "edit-assigned-worktree",
            "tracked_source_write": True,
            "worktree_path": "/worktrees/ENG-1",
            "assigned_worktree": "/worktrees/ENG-1",
            "comment_marker": None,
        }
        allowed = run_contract("role-capability-check", input_text=json.dumps(executor))
        self.assertEqual(allowed.returncode, 0, allowed.stderr)

        executor["worktree_path"] = "/worktrees/ENG-2"
        wrong_worktree = run_contract("role-capability-check", input_text=json.dumps(executor))
        self.assertEqual(wrong_worktree.returncode, 2)
        self.assertIn("assigned worktree", wrong_worktree.stderr)

        verifier_write = {**executor, "role": "task-verifier"}
        verifier_write["worktree_path"] = "/worktrees/ENG-1"
        forbidden = run_contract("role-capability-check", input_text=json.dumps(verifier_write))
        self.assertEqual(forbidden.returncode, 2)
        self.assertIn("ROLE_CAPABILITY_VIOLATION", forbidden.stderr)

        verifier_comment = {
            "role": "task-verifier",
            "operation": "write-verification-result-comment",
            "tracked_source_write": False,
            "worktree_path": None,
            "assigned_worktree": None,
            "comment_marker": "linear-spanks:verification-result",
        }
        allowed_comment = run_contract(
            "role-capability-check", input_text=json.dumps(verifier_comment)
        )
        self.assertEqual(allowed_comment.returncode, 0, allowed_comment.stderr)

    def test_four_fast_rounds_then_require_user_model_selection(self) -> None:
        for index in range(4):
            with self.subTest(index=index):
                result = run_contract(
                    "task-attempt-check",
                    input_text=json.dumps(task_attempt_fixture(index, "failed")),
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                payload = json.loads(result.stdout)
                self.assertEqual(payload["attempt"]["executor_strength"], "low")
                self.assertEqual(payload["attempt"]["verifier_strength"], "high")
                self.assertEqual(
                    payload["next_action"],
                    "user-model-selection" if index == 3 else "automatic-repair",
                )

        extra = task_attempt_fixture(4, "failed")
        extra["executor_phase"] = "repair"
        rejected = run_contract("task-attempt-check", input_text=json.dumps(extra))
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("exceeds round three", rejected.stderr)

    def test_user_selected_attempt_gets_one_round_then_prompts_again(self) -> None:
        selection = {
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
        selected = run_contract("model-escalation-check", input_text=json.dumps(selection))
        self.assertEqual(selected.returncode, 0, selected.stderr)
        self.assertEqual(json.loads(selected.stdout)["next_action"], "user-selected-repair")

        selection["previous_escalated_failure"] = True
        selection["action"] = "select-another-stronger-model"
        another = run_contract("model-escalation-check", input_text=json.dumps(selection))
        self.assertEqual(another.returncode, 0, another.stderr)
        self.assertEqual(json.loads(another.stdout)["next_action"], "user-selected-repair")

        selection["selected_model"]["configured"] = False
        unconfigured = run_contract("model-escalation-check", input_text=json.dumps(selection))
        self.assertEqual(unconfigured.returncode, 2)
        self.assertIn("must be configured", unconfigured.stderr)
        selection["selected_model"]["configured"] = True

        attempt = task_attempt_fixture(4, "failed", attempt_kind="user-selected")
        failed = run_contract("task-attempt-check", input_text=json.dumps(attempt))
        self.assertEqual(failed.returncode, 0, failed.stderr)
        self.assertEqual(json.loads(failed.stdout)["next_action"], "user-model-selection")

        selection["automatic_failures"] = 3
        too_early = run_contract("model-escalation-check", input_text=json.dumps(selection))
        self.assertEqual(too_early.returncode, 2)
        self.assertIn("after four failed automatic rounds", too_early.stderr)

    def test_verification_ledger_preserves_identity_and_exact_candidate(self) -> None:
        ledger = verification_ledger_fixture()
        valid = run_contract(
            "verification-ledger-check",
            "--expected-task-id",
            "ENG-1",
            "--expected-verifier-id",
            "task-verifier-ENG-1",
            "--expected-plan-revision",
            "2",
            input_text=json.dumps(ledger),
        )
        self.assertEqual(valid.returncode, 0, valid.stderr)
        self.assertEqual(json.loads(valid.stdout)["final_result"], "passed")

        raw = verification_ledger_fixture()
        raw["raw_executor_transcript_included"] = True
        rejected_raw = run_contract("verification-ledger-check", input_text=json.dumps(raw))
        self.assertEqual(rejected_raw.returncode, 2)
        self.assertIn("raw executor transcripts", rejected_raw.stderr)

        stale = verification_ledger_fixture()
        stale["reviewed_attempts"][-1]["commit"] = "e" * 40
        rejected_stale = run_contract("verification-ledger-check", input_text=json.dumps(stale))
        self.assertEqual(rejected_stale.returncode, 2)
        self.assertIn("exact candidate commit", rejected_stale.stderr)

        stale_evidence = verification_ledger_fixture()
        stale_evidence["verification_runs"][0]["commit"] = "e" * 40
        rejected_evidence = run_contract(
            "verification-ledger-check", input_text=json.dumps(stale_evidence)
        )
        self.assertEqual(rejected_evidence.returncode, 2)
        self.assertIn("exact candidate commit", rejected_evidence.stderr)

    def test_verifier_session_refresh_is_bounded_but_failure_ledger_remains_valid(self) -> None:
        failed_ledger = verification_ledger_fixture("failed")
        failed_ledger["live_session"] = {
            "session_id": None,
            "status": "refreshed",
            "context_tokens": 1000,
        }
        valid = run_contract("verification-ledger-check", input_text=json.dumps(failed_ledger))
        self.assertEqual(valid.returncode, 0, valid.stderr)
        self.assertEqual(json.loads(valid.stdout)["final_result"], "failed")

        failed_ledger["live_session"]["context_tokens"] = profile_limit("task") + 1
        overflow = run_contract("verification-ledger-check", input_text=json.dumps(failed_ledger))
        self.assertEqual(overflow.returncode, 2)
        self.assertIn("CONTEXT_OVERFLOW for task-verifier", overflow.stderr)

    def test_project_loop_transition_refreshes_trace_source_but_rejects_bound_drift(self) -> None:
        receipt = project_loop_receipt_fixture()
        request = {
            "target_state": "project-orchestrating",
            "current_project_revision": 7,
            "current_source_hash": receipt["source_hash"],
            "current_dependency_graph_hash": receipt["dependency_graph_hash"],
            "current_milestones": receipt["milestones"],
            "current_human_verification_policies": receipt["human_verification_policies"],
            "current_task_loops": receipt["task_loops"],
            "completed_event": receipt["next_event"],
            "next_project_revision": 7,
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
        with tempfile.TemporaryDirectory() as directory:
            receipt_path = Path(directory) / "receipt.json"
            request_path = Path(directory) / "request.json"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            request_path.write_text(json.dumps(request), encoding="utf-8")
            valid = run_contract("project-loop-transition", str(receipt_path), str(request_path))
            self.assertEqual(valid.returncode, 0, valid.stderr)
            transitioned = json.loads(valid.stdout)
            self.assertEqual(transitioned["state"], "project-orchestrating")
            self.assertEqual(transitioned["budget"]["role_invocations"], 1)

            request["current_source_hash"] = "sha256:" + "f" * 64
            request["next_source_hash"] = request["current_source_hash"]
            request_path.write_text(json.dumps(request), encoding="utf-8")
            drift = run_contract("project-loop-transition", str(receipt_path), str(request_path))
            self.assertEqual(drift.returncode, 0, drift.stderr)
            self.assertEqual(
                json.loads(drift.stdout)["source_hash"],
                request["current_source_hash"],
            )

            request["current_source_hash"] = receipt["source_hash"]
            request["next_source_hash"] = receipt["source_hash"]
            request["current_task_loops"] = json.loads(json.dumps(receipt["task_loops"]))
            request["current_task_loops"][0]["plan_revision"] = 3
            request_path.write_text(json.dumps(request), encoding="utf-8")
            plan_drift = run_contract(
                "project-loop-transition", str(receipt_path), str(request_path)
            )
            self.assertEqual(plan_drift.returncode, 2)
            self.assertIn("PROJECT_ORCHESTRATION_DRIFT: task_loops", plan_drift.stderr)

            request["current_task_loops"] = receipt["task_loops"]
            request["next_task_loops"] = []
            request_path.write_text(json.dumps(request), encoding="utf-8")
            rebound = run_contract("project-loop-transition", str(receipt_path), str(request_path))
            self.assertEqual(rebound.returncode, 2)
            self.assertIn("changed task role binding", rebound.stderr)

    def test_templates_mark_worker_comments_and_verifier_memory(self) -> None:
        completion = (SKILL / "templates" / "completion-handoff.md").read_text(encoding="utf-8")
        verification = (SKILL / "templates" / "task-verification-result.md").read_text(
            encoding="utf-8"
        )
        ledger = (SKILL / "templates" / "verification-ledger.md").read_text(encoding="utf-8")
        self.assertIn("linear-spanks:completion-handoff", completion)
        self.assertIn("linear-spanks:verification-result", verification)
        self.assertIn("Authoritative Verification Ledger", verification)
        self.assertIn("Raw executor transcript included", ledger)

        router = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        project_policy = (SKILL / "references" / "project-orchestration.md").read_text(
            encoding="utf-8"
        )
        git_policy = (ROOT / "skills" / "linear-spanks-git" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for text in (router, project_policy, git_policy, readme):
            self.assertIn("project run", text)
        self.assertIn("single-event", router)
        self.assertIn("MODEL_SELECTION_REQUIRED", project_policy)
        self.assertIn("Project Orchestration Overlay", git_policy)


class MilestoneOrchestrationContractTest(unittest.TestCase):
    def test_milestone_loop_compiles_shared_task_policy_and_role_cards(self) -> None:
        envelope = run_contract(
            "execution-envelope", "run-milestone-loop", "--assurance", "balanced"
        )
        brief = run_contract("execution-brief", "run-milestone-loop")
        controller = run_contract("runtime-card", "run-milestone-loop")
        verifier = run_contract("milestone-role-card", "task-verifier")

        for result in (envelope, brief, controller, verifier):
            self.assertEqual(result.returncode, 0, result.stderr)
        envelope_payload = json.loads(envelope.stdout)
        brief_payload = json.loads(brief.stdout)
        self.assertEqual(envelope_payload["session_boundary"], "single-event")
        self.assertEqual(
            envelope_payload["milestone_orchestration"]["topology"]["roles"],
            MILESTONE_ORCHESTRATION["topology"]["roles"],
        )
        self.assertEqual(
            brief_payload["milestone_orchestration"]["automatic_rounds"],
            PROJECT_ORCHESTRATION["task_loop"]["automatic_rounds"],
        )
        self.assertEqual(brief_payload["assurance"]["status"], "milestone-role-policy-enforced")
        self.assertIsNone(brief_payload["assurance"]["escalation_reason"])
        self.assertIn(
            "references/milestone-orchestration.md", envelope_payload["required_references"]
        )
        self.assertEqual(json.loads(verifier.stdout)["policy"]["strength"], "risk-based")

    def test_milestone_receipt_selection_and_scope_fences(self) -> None:
        receipt = milestone_loop_receipt_fixture()
        selection = {
            "project_id": "project-1",
            "project_revision": 7,
            "milestone_id": "milestone-1",
            "milestone_revision": 3,
            "receipts": [receipt],
        }
        resumed = run_contract("milestone-loop-receipt-check", input_text=json.dumps(selection))
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertEqual(json.loads(resumed.stdout)["status"], "resume")

        duplicate = json.loads(json.dumps(receipt))
        duplicate["receipt_id"] = "milestone-loop-2"
        ambiguous = run_contract(
            "milestone-loop-receipt-check",
            input_text=json.dumps({**selection, "receipts": [receipt, duplicate]}),
        )
        self.assertEqual(ambiguous.returncode, 2)
        self.assertIn("MILESTONE_ORCHESTRATION_RECEIPT_AMBIGUOUS", ambiguous.stderr)

        blocked_milestone = run_contract(
            "orchestration-scope-check",
            input_text=json.dumps(
                {
                    "scope": "milestone",
                    "project_id": "project-1",
                    "project_revision": 7,
                    "project_receipts": [project_loop_receipt_fixture()],
                    "milestone_receipts": [],
                }
            ),
        )
        self.assertEqual(blocked_milestone.returncode, 2)
        self.assertIn("ORCHESTRATION_SCOPE_CONFLICT: project-loop-1", blocked_milestone.stderr)

        blocked_project = run_contract(
            "orchestration-scope-check",
            input_text=json.dumps(
                {
                    "scope": "project",
                    "project_id": "project-1",
                    "project_revision": 7,
                    "project_receipts": [],
                    "milestone_receipts": [receipt],
                }
            ),
        )
        self.assertEqual(blocked_project.returncode, 2)
        self.assertIn("ORCHESTRATION_SCOPE_CONFLICT: milestone-loop-1", blocked_project.stderr)

    def test_milestone_event_precedence_and_transition_drift(self) -> None:
        payload = {
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
        verifying = run_contract("milestone-loop-next", input_text=json.dumps(payload))
        self.assertEqual(verifying.returncode, 0, verifying.stderr)
        self.assertEqual(json.loads(verifying.stdout)["event"], "task-verify")
        payload["project_coordination_required"] = True
        coordination = run_contract("milestone-loop-next", input_text=json.dumps(payload))
        self.assertEqual(json.loads(coordination.stdout)["event"], "project-coordination-required")

        receipt = milestone_loop_receipt_fixture()
        request = {
            "target_state": "milestone-orchestrating",
            "current_project_revision": 7,
            "current_milestone_revision": 3,
            "current_source_hash": receipt["source_hash"],
            "current_dependency_graph_hash": receipt["dependency_graph_hash"],
            "current_human_verification_policy": receipt["human_verification_policy"],
            "current_task_loops": receipt["task_loops"],
            "completed_event": receipt["next_event"],
            "next_project_revision": 7,
            "next_milestone_revision": 3,
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
        with tempfile.TemporaryDirectory() as directory:
            receipt_path = Path(directory) / "receipt.json"
            request_path = Path(directory) / "request.json"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            request_path.write_text(json.dumps(request), encoding="utf-8")
            valid = run_contract("milestone-loop-transition", str(receipt_path), str(request_path))
            self.assertEqual(valid.returncode, 0, valid.stderr)
            self.assertEqual(json.loads(valid.stdout)["state"], "milestone-orchestrating")

            request["current_source_hash"] = "sha256:" + "f" * 64
            request["next_source_hash"] = request["current_source_hash"]
            request_path.write_text(json.dumps(request), encoding="utf-8")
            trace_refresh = run_contract(
                "milestone-loop-transition", str(receipt_path), str(request_path)
            )
            self.assertEqual(trace_refresh.returncode, 0, trace_refresh.stderr)
            self.assertEqual(
                json.loads(trace_refresh.stdout)["source_hash"],
                request["current_source_hash"],
            )

            request["current_source_hash"] = receipt["source_hash"]
            request["next_source_hash"] = receipt["source_hash"]
            request["current_milestone_revision"] = 4
            request_path.write_text(json.dumps(request), encoding="utf-8")
            drift = run_contract("milestone-loop-transition", str(receipt_path), str(request_path))
            self.assertEqual(drift.returncode, 2)
            self.assertIn("MILESTONE_ORCHESTRATION_DRIFT: milestone_revision", drift.stderr)

    def test_milestone_role_handoff_and_capability_are_scoped(self) -> None:
        receipt = milestone_loop_receipt_fixture()
        handoff = role_handoff_fixture("task-verifier")
        handoff["logical_role_id"] = receipt["task_loops"][0]["verifier_id"]
        with tempfile.TemporaryDirectory() as directory:
            receipt_path = Path(directory) / "receipt.json"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            bound = run_contract(
                "role-handoff-check",
                "--orchestration",
                "milestone",
                "--receipt",
                str(receipt_path),
                input_text=json.dumps(handoff),
            )
            self.assertEqual(bound.returncode, 0, bound.stderr)

        allowed = run_contract(
            "role-capability-check",
            "--orchestration",
            "milestone",
            input_text=json.dumps(
                {
                    "role": "task-verifier",
                    "operation": "write-verification-result-comment",
                    "tracked_source_write": False,
                    "worktree_path": None,
                    "assigned_worktree": None,
                    "comment_marker": "linear-spanks:verification-result",
                }
            ),
        )
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
