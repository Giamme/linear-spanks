from __future__ import annotations

from tests.contract_support import *


class IncrementalMilestoneAutopilotTest(unittest.TestCase):
    digest_a = "sha256:" + "a" * 64
    digest_b = "sha256:" + "b" * 64
    digest_c = "sha256:" + "c" * 64

    def footprint(
        self,
        scopes: list[str],
        resources: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "repository": "linear-spanks",
            "write_scopes": scopes,
            "exclusive_resources": resources or [],
            "parallel_safe": True,
            "serialization_rationale": "scoped test fixture",
        }

    def plan(self) -> dict[str, Any]:
        return {
            "schema_version": 2,
            "task_id": "ENG-1",
            "plan_revision": 1,
            "trace_source_head": "abc123",
            "target_file_hashes": {"src/a.py": self.digest_a},
            "consumed_surface_hashes": {"src/api.py#Api": self.digest_b},
            "dependency_receipt_hashes": {
                "ENG-0": {
                    "receipt_hash": self.digest_a,
                    "output_hash": self.digest_b,
                }
            },
            "acceptance_contract_hash": self.digest_c,
            "execution_footprint": self.footprint(["src/a.py"]),
        }

    def runtime(self, storage: str = "document") -> dict[str, Any]:
        policy = {
            "schema_version": 1,
            "policy_id": "policy-1",
            "milestone_id": "milestone-1",
            "revision": 1,
            "binding": {
                "scope": self.digest_a,
                "acceptance": self.digest_a,
                "dependencies": self.digest_a,
                "authorization": self.digest_a,
                "migration_policy": self.digest_a,
                "project_policy": self.digest_a,
            },
            "persisted": True,
            "read_back": True,
            "updated_at": "2026-07-27T09:59:00+00:00",
        }
        policy["policy_hash"] = canonical_hash(policy)
        payload = {
            "schema_version": 1,
            "runtime_id": "runtime-1",
            "project_id": "project-1",
            "milestone_id": "milestone-1",
            "revision": 1,
            "storage_source": storage,
            "policy_binding": policy,
            "active_wave": {"task_ids": ["ENG-1"]},
            "plan_validity": {"valid": 1},
            "review_coverage": {"changed": 1, "adjacent": 1, "unchanged": 0},
            "human_repair": {"status": "none"},
            "last_event": "task-dispatch",
            "event_count": 1,
            "updated_at": "2026-07-27T10:00:00+00:00",
        }
        payload["projection_hash"] = canonical_hash(payload)
        return payload

    def test_contracts_and_public_command_surface_are_versioned(self) -> None:
        validation = run_contract("validate-contracts")
        self.assertEqual(validation.returncode, 0, validation.stderr)
        self.assertEqual(json.loads(validation.stdout)["commands"], 56)
        self.assertEqual(MILESTONE_REVIEW["schema_version"], 2)
        self.assertEqual(MILESTONE_RUNTIME["schema_version"], 1)
        command_names = {command["name"] for command in COMMANDS["commands"]}
        self.assertIn("report-milestone-findings", command_names)
        self.assertIn(
            "--next-wave",
            next(
                command["usage"]
                for command in COMMANDS["commands"]
                if command["name"] == "plan-tasks"
            ),
        )

    def test_legacy_and_mode_specific_transitions_coexist(self) -> None:
        legacy = run_contract("transition", "plan-tasks", "--from", "tasks-created")
        rolling_plan = run_contract(
            "transition",
            "plan-tasks",
            "--from",
            "implementing",
            "--mode",
            "next-wave",
        )
        rolling_review = run_contract(
            "transition",
            "review-milestone",
            "--from",
            "implementing",
            "--mode",
            "incremental",
        )
        active_fix = run_contract(
            "transition",
            "fix-review",
            "--from",
            "implementing",
            "--mode",
            "incremental",
        )
        rejected = run_contract("transition", "plan-tasks", "--from", "implementing")
        self.assertEqual(legacy.stdout.strip(), "tasks-planned")
        self.assertEqual(rolling_plan.stdout.strip(), "implementing")
        self.assertEqual(rolling_review.stdout.strip(), "implementing")
        self.assertEqual(active_fix.stdout.strip(), "implementing")
        self.assertEqual(rejected.returncode, 2)
        current = run_contract(
            "marker",
            "--project-id",
            "project-1",
            "--milestone-id",
            "milestone-1",
            "--stage",
            "implementing",
            "--revision",
            "3",
            "--last-command",
            "run-milestone",
            "--run-id",
            "run-3",
            "--updated-at",
            "2026-07-27T10:00:00+00:00",
        )
        replacement = run_contract(
            "marker",
            "--project-id",
            "project-1",
            "--milestone-id",
            "milestone-1",
            "--stage",
            "implementing",
            "--revision",
            "4",
            "--last-command",
            "plan-tasks",
            "--run-id",
            "run-4",
            "--updated-at",
            "2026-07-27T10:01:00+00:00",
        )
        with tempfile.TemporaryDirectory() as directory:
            current_path = Path(directory) / "current.md"
            replacement_path = Path(directory) / "replacement.md"
            current_path.write_text(current.stdout, encoding="utf-8")
            replacement_path.write_text(replacement.stdout, encoding="utf-8")
            advanced = run_contract(
                "advance-state",
                "--command",
                "plan-tasks",
                "--transition",
                "plan-tasks",
                "--mode",
                "next-wave",
                "--current-marker",
                str(current_path),
                "--replacement-marker",
                str(replacement_path),
            )
        self.assertEqual(advanced.returncode, 0, advanced.stderr)
        self.assertEqual(json.loads(advanced.stdout)["to"], "implementing")

    def test_plan_drift_distinguishes_trace_safe_and_material_changes(self) -> None:
        original = self.plan()
        unrelated = json.loads(json.dumps(original))
        unrelated["trace_source_head"] = "def456"
        valid = run_contract(
            "plan-drift-check",
            input_text=json.dumps(
                {
                    "plan": original,
                    "current": unrelated,
                    "changed_plan_fields": [],
                }
            ),
        )
        self.assertEqual(valid.returncode, 0, valid.stderr)
        self.assertEqual(json.loads(valid.stdout)["classification"], "valid")
        self.assertTrue(json.loads(valid.stdout)["trace_source_head_changed"])

        target = json.loads(json.dumps(original))
        target["target_file_hashes"]["src/a.py"] = self.digest_b
        safe = run_contract(
            "plan-drift-check",
            input_text=json.dumps(
                {
                    "plan": original,
                    "current": target,
                    "changed_plan_fields": ["verification_commands"],
                }
            ),
        )
        self.assertEqual(json.loads(safe.stdout)["classification"], "safe-refresh")

        interface = json.loads(json.dumps(original))
        interface["consumed_surface_hashes"]["src/api.py#Api"] = self.digest_c
        material = run_contract(
            "plan-drift-check",
            input_text=json.dumps(
                {
                    "plan": original,
                    "current": interface,
                    "changed_plan_fields": [],
                }
            ),
        )
        self.assertEqual(json.loads(material.stdout)["classification"], "material")
        self.assertTrue(json.loads(material.stdout)["approval_required"])

    def test_dependency_receipt_refresh_is_safe_but_output_change_is_material(self) -> None:
        original = self.plan()
        receipt_refresh = json.loads(json.dumps(original))
        receipt_refresh["dependency_receipt_hashes"]["ENG-0"]["receipt_hash"] = self.digest_c
        safe = run_contract(
            "plan-drift-check",
            input_text=json.dumps(
                {
                    "plan": original,
                    "current": receipt_refresh,
                    "changed_plan_fields": [],
                }
            ),
        )
        self.assertEqual(json.loads(safe.stdout)["classification"], "safe-refresh")

        output_change = json.loads(json.dumps(receipt_refresh))
        output_change["dependency_receipt_hashes"]["ENG-0"]["output_hash"] = self.digest_c
        material = run_contract(
            "plan-drift-check",
            input_text=json.dumps(
                {
                    "plan": original,
                    "current": output_change,
                    "changed_plan_fields": [],
                }
            ),
        )
        self.assertEqual(json.loads(material.stdout)["classification"], "material")

    def test_incremental_review_covers_neighbours_overlaps_and_sinks(self) -> None:
        tasks = [
            {
                "id": "A",
                "dependencies": [],
                "execution_footprint": self.footprint(["src/a.py"]),
                "final_sink": False,
            },
            {
                "id": "B",
                "dependencies": ["A"],
                "execution_footprint": self.footprint(["src/b.py"]),
                "final_sink": False,
            },
            {
                "id": "C",
                "dependencies": [],
                "execution_footprint": self.footprint(["src/a.py/sub"]),
                "final_sink": False,
            },
            {
                "id": "D",
                "dependencies": [],
                "execution_footprint": self.footprint(["src/d.py"]),
                "final_sink": True,
            },
            {
                "id": "E",
                "dependencies": [],
                "execution_footprint": self.footprint(["src/e.py"]),
                "final_sink": False,
            },
        ]
        result = run_contract(
            "review-coverage-check",
            input_text=json.dumps(
                {
                    "tasks": tasks,
                    "changed_task_ids": ["A"],
                    "mode": "incremental",
                }
            ),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        coverage = json.loads(result.stdout)
        self.assertEqual(coverage["changed_task_ids"], ["A"])
        self.assertEqual(coverage["adjacent_task_ids"], ["B", "C"])
        self.assertEqual(coverage["unchanged_task_ids"], ["D", "E"])
        self.assertTrue(coverage["coverage_hash"].startswith("sha256:"))

    def test_bounded_review_checkpoint_requires_fresh_context_and_current_hashes(self) -> None:
        checkpoint = {
            "schema_version": 2,
            "receipt_id": "review-receipt-1",
            "review_id": "review-1",
            "session_id": "session-1",
            "project_id": "project-1",
            "milestone_id": "milestone-1",
            "entry_command": "review-milestone",
            "mode": "incremental",
            "marker_revision": 7,
            "matrix_hash": self.digest_a,
            "dependency_graph_hash": self.digest_b,
            "coverage_hash": self.digest_c,
            "ordered_task_ids": ["A", "B"],
            "covered_task_ids": ["A", "B"],
            "remaining_task_ids": [],
            "changed_task_ids": ["A"],
            "adjacent_task_ids": ["B"],
            "unchanged_task_ids": [],
            "task_revisions": {"A": 2, "B": 1},
            "plan_revisions": {"A": 2, "B": 1},
            "batch_index": 1,
            "cumulative_findings": [],
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
        valid = run_contract("milestone-review-checkpoint", input_text=json.dumps(checkpoint))
        self.assertEqual(valid.returncode, 0, valid.stderr)
        self.assertEqual(json.loads(valid.stdout)["token_status"], "unverified")
        stale_session = run_contract(
            "milestone-review-checkpoint",
            "--current-session-id",
            "session-1",
            input_text=json.dumps(checkpoint),
        )
        self.assertEqual(stale_session.returncode, 2)
        self.assertIn("FRESH_CONTEXT_REQUIRED", stale_session.stderr)
        stale_graph = run_contract(
            "milestone-review-checkpoint",
            "--expected-dependency-graph-hash",
            self.digest_c,
            input_text=json.dumps(checkpoint),
        )
        self.assertEqual(stale_graph.returncode, 2)
        self.assertIn("MILESTONE_REVIEW_DRIFT", stale_graph.stderr)

    def test_next_wave_preserves_zero_revision_later_tasks(self) -> None:
        tasks = [
            {
                "id": "A",
                "status": "Unplanned",
                "plan_revision": 0,
                "dependencies": [],
                "dependency_statuses": {},
                "review_covered": False,
                "active_receipt": False,
            },
            {
                "id": "B",
                "status": "Unplanned",
                "plan_revision": 0,
                "dependencies": ["A"],
                "dependency_statuses": {"A": "Todo"},
                "review_covered": False,
                "active_receipt": False,
            },
        ]
        result = run_contract(
            "next-wave-check",
            input_text=json.dumps({"tasks": tasks, "max_parallel": 2}),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        wave = json.loads(result.stdout)
        self.assertEqual([task["id"] for task in wave["selected"]], ["A"])
        self.assertEqual(wave["later"], [{"id": "B", "status": "Unplanned", "plan_revision": 0}])

    def test_incremental_graph_keeps_zero_revision_nodes_out_of_reviewed_wave(self) -> None:
        source = dependency_graph_source_fixture()
        source["review_status"] = "incremental-reviewed"
        source["tasks"][-1]["plan_revision"] = 0
        built = run_contract("dependency-graph-build", input_text=json.dumps(source))
        self.assertEqual(built.returncode, 0, built.stderr)
        graph = json.loads(built.stdout)
        statuses = {task["id"]: "Backlog" for task in graph["tasks"]}
        missing_coverage = run_contract(
            "wave-select",
            "--max-parallel",
            "2",
            "--capacity",
            "2",
            input_text=json.dumps(
                {
                    "graph": graph,
                    "live_statuses": statuses,
                    "excluded_issue_ids": [],
                }
            ),
        )
        self.assertEqual(missing_coverage.returncode, 2)
        coverage = {"ENG-1": self.digest_a, "ENG-2": self.digest_b}
        selected = run_contract(
            "wave-select",
            "--max-parallel",
            "2",
            "--capacity",
            "2",
            input_text=json.dumps(
                {
                    "graph": graph,
                    "live_statuses": statuses,
                    "excluded_issue_ids": [],
                    "review_coverage_hashes": coverage,
                }
            ),
        )
        self.assertEqual(selected.returncode, 0, selected.stderr)
        self.assertEqual(json.loads(selected.stdout)["selected"], ["ENG-1", "ENG-2"])
        self.assertNotIn("ENG-4", json.loads(selected.stdout)["selected"])

    def test_runtime_storage_fallback_promotion_and_conflict(self) -> None:
        comment = self.runtime("managed-comment")
        fallback = run_contract(
            "milestone-runtime-storage-check",
            input_text=json.dumps(
                {
                    "milestone_id": "milestone-1",
                    "documents_available": False,
                    "documents": [],
                    "comments": [comment],
                }
            ),
        )
        self.assertEqual(json.loads(fallback.stdout)["action"], "use-managed-comment")
        promotion = run_contract(
            "milestone-runtime-storage-check",
            input_text=json.dumps(
                {
                    "milestone_id": "milestone-1",
                    "documents_available": True,
                    "documents": [],
                    "comments": [comment],
                }
            ),
        )
        self.assertEqual(json.loads(promotion.stdout)["action"], "promote-comment-to-document")

        document = self.runtime("document")
        matching = run_contract(
            "milestone-runtime-storage-check",
            input_text=json.dumps(
                {
                    "milestone_id": "milestone-1",
                    "documents_available": True,
                    "documents": [document],
                    "comments": [comment],
                }
            ),
        )
        self.assertEqual(json.loads(matching.stdout)["action"], "retire-matching-comment")

        migrated = run_contract(
            "milestone-runtime-migrate",
            input_text=json.dumps(
                {
                    "milestone_id": "milestone-1",
                    "documents_available": False,
                    "documents": [],
                    "comments": [comment],
                    "description": (
                        "# Human milestone objective\n\n"
                        '<!-- linear-spanks:state {"revision":1} -->\n'
                        '<!-- linear-spanks:dependency-graph {"graph_revision":1} -->\n'
                    ),
                }
            ),
        )
        self.assertEqual(migrated.returncode, 0, migrated.stderr)
        migration = json.loads(migrated.stdout)
        self.assertTrue(migration["description_preserved"])
        self.assertTrue(migration["legacy_markers_detected"]["state_marker"])
        self.assertIn("linear-spanks:milestone-runtime-ref", migration["description"])

        document["active_wave"] = {"task_ids": ["ENG-2"]}
        document["projection_hash"] = canonical_hash(
            {key: value for key, value in document.items() if key != "projection_hash"}
        )
        conflict = run_contract(
            "milestone-runtime-storage-check",
            input_text=json.dumps(
                {
                    "milestone_id": "milestone-1",
                    "documents_available": True,
                    "documents": [document],
                    "comments": [comment],
                }
            ),
        )
        self.assertEqual(conflict.returncode, 2)
        self.assertIn("MILESTONE_RUNTIME_STATE_CONFLICT", conflict.stderr)

    def test_guarded_policy_expires_and_always_gated_operations_stay_gated(self) -> None:
        binding = {
            "scope": self.digest_a,
            "acceptance": self.digest_a,
            "dependencies": self.digest_a,
            "authorization": self.digest_a,
            "migration_policy": self.digest_a,
            "project_policy": self.digest_a,
        }
        automatic = run_contract(
            "autopilot-policy-check",
            input_text=json.dumps(
                {
                    "policy_binding": binding,
                    "current_binding": binding,
                    "operation": "safe-plan-refresh",
                }
            ),
        )
        self.assertTrue(json.loads(automatic.stdout)["automatic"])
        gated = run_contract(
            "autopilot-policy-check",
            input_text=json.dumps(
                {
                    "policy_binding": binding,
                    "current_binding": binding,
                    "operation": "integration",
                }
            ),
        )
        self.assertTrue(json.loads(gated.stdout)["approval_required"])
        changed = dict(binding)
        changed["authorization"] = self.digest_b
        expired = run_contract(
            "autopilot-policy-check",
            input_text=json.dumps(
                {
                    "policy_binding": binding,
                    "current_binding": changed,
                    "operation": "tests",
                }
            ),
        )
        self.assertEqual(json.loads(expired.stdout)["status"], "expired")

    def test_autopilot_alias_and_no_flag_legacy_modes(self) -> None:
        base = {
            "command": "run-milestone",
            "autopilot": False,
            "until": None,
            "max_events": None,
            "repair_safe": False,
            "isolated_worktree": False,
        }
        legacy = run_contract("milestone-run-mode-check", input_text=json.dumps(base))
        self.assertEqual(json.loads(legacy.stdout)["mode"], "legacy-single-stage")
        base["autopilot"] = True
        base["isolated_worktree"] = True
        alias = run_contract("milestone-run-mode-check", input_text=json.dumps(base))
        resolved = json.loads(alias.stdout)
        self.assertEqual(resolved["command"], "run-milestone-loop")
        self.assertEqual(resolved["max_events"], 20)
        self.assertEqual(resolved["isolated_worktree_status"], "idempotent-assertion")

        loop = {**base, "command": "run-milestone-loop", "autopilot": False}
        loop["until"] = ["blocked"]
        loop["max_events"] = 100
        supervised = run_contract("milestone-run-mode-check", input_text=json.dumps(loop))
        self.assertEqual(json.loads(supervised.stdout)["mode"], "guarded-autopilot")

    def test_autopilot_enforces_fresh_receipts_and_event_ceiling(self) -> None:
        receipts = [
            {
                "event_id": f"event-{index}",
                "session_id": f"session-{index}",
                "persisted": True,
                "read_back": True,
            }
            for index in range(20)
        ]
        result = run_contract(
            "autopilot-loop-check",
            input_text=json.dumps(
                {
                    "max_events": 20,
                    "event_count": 20,
                    "until": ["approval-required", "blocked", "milestone-done"],
                    "observed_stop": None,
                    "receipts": receipts,
                    "isolated_worktree": True,
                }
            ),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["stop"], "event-ceiling")
        duplicate = json.loads(json.dumps(receipts))
        duplicate[-1]["session_id"] = duplicate[0]["session_id"]
        rejected = run_contract(
            "autopilot-loop-check",
            input_text=json.dumps(
                {
                    "max_events": 20,
                    "event_count": 20,
                    "until": ["blocked"],
                    "observed_stop": None,
                    "receipts": duplicate,
                    "isolated_worktree": False,
                }
            ),
        )
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("FRESH_CONTEXT_REQUIRED", rejected.stderr)

    def test_findings_are_idempotent_and_invalidate_only_consumers(self) -> None:
        payload = {
            "milestone_id": "milestone-1",
            "session_id": "test-session-1",
            "findings": ["API response changed", "UI state is stale"],
            "existing_session_ids": [],
            "candidate_owners": [],
            "changed_provided_surfaces": ["api#result"],
            "unfinished_plans": [
                {"task_id": "B", "consumed_surfaces": ["api#result"]},
                {"task_id": "C", "consumed_surfaces": ["cache#entry"]},
            ],
        }
        result = run_contract("milestone-findings-check", input_text=json.dumps(payload))
        self.assertEqual(result.returncode, 0, result.stderr)
        findings = json.loads(result.stdout)
        self.assertEqual(findings["repair_task_count"], 1)
        self.assertEqual(findings["invalidate_plan_ids"], ["B"])
        self.assertTrue(findings["machine_reverification_required"])
        payload["existing_session_ids"] = ["test-session-1"]
        replay = run_contract("milestone-findings-check", input_text=json.dumps(payload))
        self.assertEqual(json.loads(replay.stdout)["status"], "idempotent-replay")
        payload["existing_session_hashes"] = {"test-session-1": findings["batch_hash"]}
        payload["findings"] = ["different batch"]
        collision = run_contract("milestone-findings-check", input_text=json.dumps(payload))
        self.assertEqual(collision.returncode, 2)
        self.assertIn("MILESTONE_FINDINGS_SESSION_CONFLICT", collision.stderr)
