from __future__ import annotations

from tests.contract_support import *


class ParallelExecutionContractTest(unittest.TestCase):
    def build_graph(self, source: dict[str, Any] | None = None) -> dict[str, Any]:
        result = run_contract(
            "dependency-graph-build",
            input_text=json.dumps(source or dependency_graph_source_fixture()),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_parallel_commands_compile_strict_single_wave_contracts(self) -> None:
        implement = run_contract("execution-envelope", "implement-wave", "--assurance", "fast")
        reconcile = run_contract("execution-envelope", "reconcile-wave", "--assurance", "balanced")

        self.assertEqual(implement.returncode, 0, implement.stderr)
        self.assertEqual(reconcile.returncode, 0, reconcile.stderr)
        implement_envelope = json.loads(implement.stdout)
        reconcile_envelope = json.loads(reconcile.stdout)
        self.assertEqual(implement_envelope["session_boundary"], "single-wave")
        self.assertEqual(implement_envelope["assurance"]["effective"], "strict")
        self.assertEqual(reconcile_envelope["approval"]["kind"], "preview")
        self.assertEqual(reconcile_envelope["assurance"]["effective"], "strict")
        self.assertEqual(
            implement_envelope["parallel_execution"]["git"]["worktree_policy"],
            "one-clean-worktree-per-task",
        )
        self.assertIn(
            "references/parallel-execution.md",
            implement_envelope["required_references"],
        )

    def test_graph_derives_serialization_edges_waves_and_stable_hash(self) -> None:
        first = self.build_graph()
        repeat = self.build_graph()

        self.assertEqual(first["graph_hash"], repeat["graph_hash"])
        self.assertEqual(first["serialization_edges"], [{"from": "ENG-1", "to": "ENG-3"}])
        self.assertEqual(first["waves"], [["ENG-1", "ENG-2"], ["ENG-3", "ENG-4"]])
        checked = run_contract("dependency-graph-check", input_text=json.dumps(first))
        self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_graph_render_round_trips_managed_marker(self) -> None:
        graph = self.build_graph()
        rendered = run_contract("dependency-graph-render", input_text=json.dumps(graph))
        parsed = run_contract("parse-dependency-graph", input_text=rendered.stdout)

        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        self.assertIn("n0 -. serialize .-> n2", rendered.stdout)
        self.assertIn('n0["ENG-1"]', rendered.stdout)
        self.assertIn("<!-- linear-spanks:dependency-graph", rendered.stdout)
        self.assertEqual(parsed.returncode, 0, parsed.stderr)
        self.assertEqual(json.loads(parsed.stdout), graph)

    def test_graph_upsert_preserves_human_text_and_workflow_marker(self) -> None:
        graph = self.build_graph()
        state_marker = '<!-- linear-spanks:state {"stage":"tasks-planned"} -->'
        description = f"# Human objective\n\nKeep this.\n\n{state_marker}\n"
        with (
            tempfile.NamedTemporaryFile("w", suffix=".md") as description_file,
            tempfile.NamedTemporaryFile("w", suffix=".json") as graph_file,
        ):
            description_file.write(description)
            description_file.flush()
            json.dump(graph, graph_file)
            graph_file.flush()
            first = run_contract("dependency-graph-upsert", description_file.name, graph_file.name)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn("# Human objective", first.stdout)
        self.assertIn("Keep this.", first.stdout)
        self.assertIn(state_marker, first.stdout)
        self.assertEqual(first.stdout.count("linear-spanks:dependency-graph"), 1)

    def test_graph_rejects_cycles_and_tampering(self) -> None:
        cyclic = dependency_graph_source_fixture()
        cyclic["hard_edges"].append({"from": "ENG-4", "to": "ENG-1"})
        cycle_result = run_contract("dependency-graph-build", input_text=json.dumps(cyclic))
        graph = self.build_graph()
        graph["waves"] = [["ENG-1"]]
        drift_result = run_contract("dependency-graph-check", input_text=json.dumps(graph))

        self.assertEqual(cycle_result.returncode, 2)
        self.assertIn("DEPENDENCY_GRAPH_CYCLE", cycle_result.stderr)
        self.assertEqual(drift_result.returncode, 2)
        self.assertIn("DEPENDENCY_GRAPH_DRIFT", drift_result.stderr)

    def test_unknown_footprint_serializes_and_rejects_unsafe_paths(self) -> None:
        source = dependency_graph_source_fixture()
        source["tasks"][0]["execution_footprint"]["write_scopes"] = []
        graph = self.build_graph(source)
        self.assertTrue(any(edge["from"] == "ENG-1" for edge in graph["serialization_edges"]))

        source = dependency_graph_source_fixture()
        source["tasks"][0]["execution_footprint"]["write_scopes"] = ["../secret"]
        invalid = run_contract("dependency-graph-build", input_text=json.dumps(source))
        self.assertEqual(invalid.returncode, 2)
        self.assertIn("repository-relative", invalid.stderr)

    def test_partial_planning_is_conservative_but_cannot_be_reviewed(self) -> None:
        source = dependency_graph_source_fixture()
        source["review_status"] = "unreviewed"
        source["tasks"][3]["plan_revision"] = 0
        source["tasks"][3]["execution_footprint"]["write_scopes"] = []
        graph = self.build_graph(source)
        self.assertEqual(graph["review_status"], "unreviewed")

        source["review_status"] = "reviewed"
        rejected = run_contract("dependency-graph-build", input_text=json.dumps(source))
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("every task to have a current plan", rejected.stderr)

    def test_wave_selection_clamps_capacity_and_requires_parallel_frontier(self) -> None:
        graph = self.build_graph()
        selection = {
            "graph": graph,
            "live_statuses": {task["id"]: "Backlog" for task in graph["tasks"]},
            "excluded_issue_ids": [],
        }
        selected = run_contract(
            "wave-select",
            "--max-parallel",
            "8",
            "--capacity",
            "3",
            input_text=json.dumps(selection),
        )
        no_capacity = run_contract(
            "wave-select", "--capacity", "1", input_text=json.dumps(selection)
        )
        selection["live_statuses"]["ENG-2"] = "Done"
        no_wave = run_contract("wave-select", "--capacity", "2", input_text=json.dumps(selection))

        self.assertEqual(selected.returncode, 0, selected.stderr)
        self.assertEqual(json.loads(selected.stdout)["selected"], ["ENG-1", "ENG-2"])
        self.assertEqual(no_capacity.returncode, 2)
        self.assertIn("PARALLEL_CAPACITY_UNAVAILABLE", no_capacity.stderr)
        self.assertEqual(no_wave.returncode, 2)
        self.assertIn("NO_PARALLEL_WAVE", no_wave.stderr)

    def test_wave_receipt_requires_unique_isolated_worktrees(self) -> None:
        receipt = wave_receipt_fixture()
        valid = run_contract("wave-receipt-check", input_text=json.dumps(receipt))
        receipt["tasks"][1]["worktree"] = receipt["tasks"][0]["worktree"]
        duplicate = run_contract("wave-receipt-check", input_text=json.dumps(receipt))
        outside = wave_receipt_fixture()
        outside["tasks"][0]["worktree"] = "/outside/ENG-1"
        outside_result = run_contract("wave-receipt-check", input_text=json.dumps(outside))

        self.assertEqual(valid.returncode, 0, valid.stderr)
        self.assertEqual(duplicate.returncode, 2)
        self.assertIn("must be unique", duplicate.stderr)
        self.assertEqual(outside_result.returncode, 2)
        self.assertIn("below worktree_root", outside_result.stderr)


class IsolatedWorktreeContractTest(unittest.TestCase):
    def transition(
        self,
        receipt: dict[str, Any],
        target: str,
        event: str,
        current: dict[str, Any] | None = None,
        updates: dict[str, Any] | None = None,
        updated_at: str = "2026-07-21T10:10:00+00:00",
    ) -> subprocess.CompletedProcess[str]:
        request = {
            "target_state": target,
            "event": event,
            "updated_at": updated_at,
            "current": current or isolation_current_fixture(receipt),
            "updates": updates or {},
        }
        with tempfile.TemporaryDirectory() as directory:
            receipt_path = Path(directory) / "receipt.json"
            request_path = Path(directory) / "request.json"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            request_path.write_text(json.dumps(request), encoding="utf-8")
            return run_contract("isolation-transition", str(receipt_path), str(request_path))

    def test_flag_applicability_and_runtime_compilation(self) -> None:
        for command in ("run-task", "implement-next"):
            with self.subTest(command=command):
                envelope = run_contract("execution-envelope", command, "--isolated-worktree")
                brief = run_contract("execution-brief", command, "--isolated-worktree")
                card = run_contract("runtime-card", command, "--isolated-worktree")
                self.assertEqual(envelope.returncode, 0, envelope.stderr)
                self.assertEqual(brief.returncode, 0, brief.stderr)
                self.assertEqual(card.returncode, 0, card.stderr)
                self.assertTrue(json.loads(envelope.stdout)["isolation"]["enabled"])
                self.assertTrue(json.loads(brief.stdout)["runtime_card"]["isolation"]["enabled"])
                self.assertIn(
                    "failed_integration_preserves_parent_and_linear_state",
                    json.loads(card.stdout)["postconditions"],
                )

        wave = run_contract("execution-envelope", "implement-wave", "--isolated-worktree")
        rejected = run_contract("execution-envelope", "reconcile-wave", "--isolated-worktree")
        planning = run_contract("execution-envelope", "plan-task", "--isolated-worktree")
        self.assertEqual(wave.returncode, 0, wave.stderr)
        self.assertEqual(json.loads(wave.stdout)["isolation"]["status"], "idempotent-assertion")
        self.assertTrue(json.loads(wave.stdout)["isolation"]["uses_existing_wave_contract"])
        self.assertNotIn("receipt", json.loads(wave.stdout)["isolation"])
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("ISOLATION_NOT_APPLICABLE", rejected.stderr)
        self.assertEqual(planning.returncode, 2)
        self.assertIn("ISOLATION_NOT_APPLICABLE", planning.stderr)

    def test_run_milestone_rejects_isolation_before_nonimplementation_mutation(self) -> None:
        unresolved = run_contract("execution-envelope", "run-milestone", "--isolated-worktree")
        review = run_contract(
            "execution-envelope",
            "run-milestone",
            "--isolated-worktree",
            "--milestone-stage",
            "review-milestone",
        )
        implementation = run_contract(
            "execution-envelope",
            "run-milestone",
            "--isolated-worktree",
            "--milestone-stage",
            "start-implementation",
        )
        self.assertEqual(unresolved.returncode, 2)
        self.assertIn("before any mutation", unresolved.stderr)
        self.assertEqual(review.returncode, 2)
        self.assertIn("only to start-implementation", review.stderr)
        self.assertEqual(implementation.returncode, 0, implementation.stderr)
        self.assertTrue(json.loads(implementation.stdout)["isolation"]["enabled"])

    def test_preflight_rejects_git_and_path_hazards(self) -> None:
        cases = {
            "git_strategy_present": (False, ".linear-spanks-git.yml"),
            "parent_attached": (False, "attached"),
            "parent_clean": (False, "clean"),
            "plan_current": (False, "plan must be current"),
            "branch_exists": (True, "branch already exists"),
            "worktree_path_exists": (True, "path already exists"),
            "worktree_root": ("relative/worktrees", "safe absolute path"),
        }
        for field, (value, message) in cases.items():
            with self.subTest(field=field):
                preflight = isolation_preflight_fixture()
                preflight[field] = value
                result = run_contract("isolation-preflight-check", input_text=json.dumps(preflight))
                self.assertEqual(result.returncode, 2)
                self.assertIn(message, result.stderr)

        nested = isolation_preflight_fixture()
        nested["worktree_root"] = "/repo/worktrees"
        nested["worktree_path"] = "/repo/worktrees/ENG-1"
        nested_result = run_contract("isolation-preflight-check", input_text=json.dumps(nested))
        self.assertEqual(nested_result.returncode, 2)
        self.assertIn("outside the repository tree", nested_result.stderr)

    def test_preflight_resumes_one_receipt_and_rejects_ambiguity(self) -> None:
        summary = {
            "receipt_id": "isolation-1",
            "command": "run-task",
            "issue_id": "ENG-1",
            "plan_revision": 3,
            "state": "verified-pending-integration",
        }
        preflight = isolation_preflight_fixture()
        preflight["active_receipts"] = [summary]
        preflight["branch_exists"] = True
        preflight["worktree_path_exists"] = True
        resumed = run_contract("isolation-preflight-check", input_text=json.dumps(preflight))
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertEqual(json.loads(resumed.stdout)["status"], "resume")

        preflight["active_receipts"].append({**summary, "receipt_id": "isolation-2"})
        ambiguous = run_contract("isolation-preflight-check", input_text=json.dumps(preflight))
        self.assertEqual(ambiguous.returncode, 2)
        self.assertIn("ISOLATION_RECEIPT_AMBIGUOUS", ambiguous.stderr)
        self.assertIn("isolation-1, isolation-2", ambiguous.stderr)

    def test_receipt_schema_and_failure_transitions(self) -> None:
        prepared = isolation_receipt_fixture()
        valid = run_contract("isolation-receipt-check", input_text=json.dumps(prepared))
        self.assertEqual(valid.returncode, 0, valid.stderr)

        failure = {
            "code": "EXECUTOR_FAILED",
            "message": "executor stopped",
            "at": "2026-07-21T10:10:00+00:00",
        }
        executor_failed = self.transition(
            prepared, "failed", "executor-failed", updates={"failure": failure}
        )
        verification_failed = self.transition(
            isolation_receipt_fixture("executing"),
            "failed",
            "verification-failed",
            updates={"failure": {**failure, "code": "VERIFICATION_FAILED"}},
        )
        self.assertEqual(executor_failed.returncode, 0, executor_failed.stderr)
        self.assertEqual(verification_failed.returncode, 0, verification_failed.stderr)
        self.assertEqual(json.loads(executor_failed.stdout)["state"], "failed")
        self.assertFalse(
            json.loads(verification_failed.stdout)["completion"]["issue_done_read_back"]
        )

    def test_trace_source_change_does_not_invalidate_current_isolated_plan(self) -> None:
        receipt = isolation_receipt_fixture()
        current = isolation_current_fixture(receipt)
        current["source_hash"] = "sha256:" + "f" * 64

        transitioned = self.transition(
            receipt,
            "executing",
            "start-executor",
            current=current,
        )

        self.assertEqual(transitioned.returncode, 0, transitioned.stderr)
        self.assertEqual(json.loads(transitioned.stdout)["state"], "executing")

    def test_verified_transition_binds_exact_preview_and_approval(self) -> None:
        receipt = isolation_receipt_fixture("executing")
        current = isolation_current_fixture(receipt)
        child_commit = "c" * 40
        preview = {
            "parent_branch": "main",
            "parent_head": "b" * 40,
            "child_commit": child_commit,
            "merge_command": f"git merge --no-ff {child_commit}",
            "verification_commands": ["python3 -m unittest"],
            "cleanup_commands": ["git worktree remove /worktrees/run-1-ENG-1"],
            "linear_completion_writes": ["persist completion receipt", "mark ENG-1 Done"],
        }
        verified = self.transition(
            receipt,
            "verified-pending-integration",
            "verification-passed",
            current=current,
            updates={
                "child_commit": child_commit,
                "verification": {
                    "status": "passed",
                    "commands": ["python3 -m unittest"],
                    "completed_at": "2026-07-21T10:10:00+00:00",
                },
                "integration_preview": preview,
            },
        )
        self.assertEqual(verified.returncode, 0, verified.stderr)
        pending = json.loads(verified.stdout)
        self.assertTrue(pending["integration"]["preview_hash"].startswith("sha256:"))
        approved = self.transition(
            pending,
            "verified-pending-integration",
            "approve-preview",
            current=isolation_current_fixture(pending),
            updates={
                "approve_preview": {
                    "preview_hash": pending["integration"]["preview_hash"],
                    "parent_head": "b" * 40,
                }
            },
            updated_at="2026-07-21T10:11:00+00:00",
        )
        self.assertEqual(approved.returncode, 0, approved.stderr)
        self.assertEqual(
            json.loads(approved.stdout)["integration"]["approved_preview_hash"],
            pending["integration"]["preview_hash"],
        )

    def test_declined_approval_preserves_pending_worktree_and_linear_state(self) -> None:
        receipt = isolation_receipt_fixture("verified-pending-integration")
        declined = self.transition(
            receipt,
            "verified-pending-integration",
            "approval-declined",
        )
        self.assertEqual(declined.returncode, 0, declined.stderr)
        result = json.loads(declined.stdout)
        self.assertEqual(result["child_branch"], receipt["child_branch"])
        self.assertEqual(result["worktree_path"], receipt["worktree_path"])
        self.assertEqual(result["completion"], receipt["completion"])
        self.assertEqual(result["state"], "verified-pending-integration")

    def test_parent_drift_invalidates_approval_before_integration(self) -> None:
        receipt = isolation_receipt_fixture("verified-pending-integration")
        receipt["integration"]["approved_preview_hash"] = receipt["integration"]["preview_hash"]
        receipt["integration"]["approved_parent_head"] = "b" * 40
        current = isolation_current_fixture(receipt)
        current["parent_head"] = "f" * 40
        drift = self.transition(receipt, "integrating", "begin-integration", current=current)
        self.assertEqual(drift.returncode, 2)
        self.assertIn("ISOLATION_APPROVAL_INVALIDATED", drift.stderr)
        self.assertIn("fresh preview", drift.stderr)

        current = isolation_current_fixture(receipt)
        current["source_hash"] = "sha256:" + "f" * 64
        source_drift = self.transition(receipt, "integrating", "begin-integration", current=current)
        self.assertEqual(source_drift.returncode, 0, source_drift.stderr)
        self.assertEqual(json.loads(source_drift.stdout)["state"], "integrating")

    def test_merge_conflict_returns_to_pending_without_completion(self) -> None:
        receipt = isolation_receipt_fixture("integrating")
        conflicted = self.transition(receipt, "verified-pending-integration", "merge-conflict")
        self.assertEqual(conflicted.returncode, 0, conflicted.stderr)
        result = json.loads(conflicted.stdout)
        self.assertIsNone(result["integration"]["approved_preview_hash"])
        self.assertFalse(result["completion"]["receipt_persisted"])
        self.assertFalse(result["completion"]["issue_done_read_back"])
        self.assertEqual(result["completion"]["worktree_cleanup"], "pending")

        mutated = isolation_current_fixture(receipt)
        mutated["parent_fast_forwarded"] = True
        mutated["issue_done_read_back"] = True
        rejected = self.transition(
            receipt,
            "verified-pending-integration",
            "merge-conflict",
            current=mutated,
        )
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("ISOLATION_INTEGRATION_ATOMICITY_FAILED", rejected.stderr)

    def test_external_integration_recovery_requires_ancestry_and_fresh_verification(self) -> None:
        receipt = isolation_receipt_fixture("verified-pending-integration")
        receipt["integration"]["approved_preview_hash"] = receipt["integration"]["preview_hash"]
        receipt["integration"]["approved_parent_head"] = "b" * 40
        current = isolation_current_fixture(receipt)
        current.update(
            {
                "parent_head": "e" * 40,
                "child_is_ancestor_of_parent": True,
                "integration_verification_passed": True,
                "completion_receipt_persisted": True,
                "issue_done_read_back": True,
                "newly_unblocked_read_back": True,
            }
        )
        recovered = self.transition(
            receipt,
            "integrated",
            "recover-external-integration",
            current=current,
            updates={
                "integrated_head": "e" * 40,
                "completion_receipt_id": "completion-1",
            },
        )
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertEqual(json.loads(recovered.stdout)["state"], "integrated")

        current["child_is_ancestor_of_parent"] = False
        rejected = self.transition(
            receipt,
            "integrated",
            "recover-external-integration",
            current=current,
            updates={
                "integrated_head": "e" * 40,
                "completion_receipt_id": "completion-1",
            },
        )
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("verified ancestry", rejected.stderr)

    def test_successful_integration_requires_readback_then_allows_cleanup(self) -> None:
        receipt = isolation_receipt_fixture("integrating")
        current = isolation_current_fixture(receipt)
        current.update(
            {
                "parent_head": "e" * 40,
                "integration_verification_passed": True,
                "parent_fast_forwarded": True,
                "completion_receipt_persisted": True,
                "issue_done_read_back": True,
                "newly_unblocked_read_back": True,
            }
        )
        integrated = self.transition(
            receipt,
            "integrated",
            "integration-passed",
            current=current,
            updates={
                "integrated_head": "e" * 40,
                "completion_receipt_id": "completion-1",
            },
        )
        self.assertEqual(integrated.returncode, 0, integrated.stderr)
        integrated_receipt = json.loads(integrated.stdout)
        self.assertEqual(integrated_receipt["completion"]["worktree_cleanup"], "pending")
        self.assertEqual(integrated_receipt["child_branch"], receipt["child_branch"])

        cleaned = self.transition(
            integrated_receipt,
            "integrated",
            "cleanup-completed",
            current=isolation_current_fixture(integrated_receipt),
            updates={"worktree_cleanup": "removed"},
            updated_at="2026-07-21T10:11:00+00:00",
        )
        self.assertEqual(cleaned.returncode, 0, cleaned.stderr)
        self.assertEqual(json.loads(cleaned.stdout)["completion"]["worktree_cleanup"], "removed")
