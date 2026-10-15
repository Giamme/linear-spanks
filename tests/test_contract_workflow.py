from __future__ import annotations

from tests.contract_support import *


class CommandManifestTest(unittest.TestCase):
    def test_registry_contains_unique_complete_commands(self) -> None:
        commands = COMMANDS["commands"]
        names = [command["name"] for command in commands]

        self.assertEqual(len(names), 56)
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(
            {
                "create-project",
                "analyze-codebase",
                "import-codebase",
                "update-project",
                "onboard-project",
                "audit-project",
                "normalize-project",
                "onboard-milestone",
                "onboard-task",
                "backfill-completion",
                "verify-task",
                "verify-milestone",
                "refine-task",
                "plan-task",
                "organize-unplanned",
                "checkpoint-project",
                "rollover-project",
                "run-project",
                "run-milestone-loop",
                "set-human-verification-policy",
                "status-human-verification",
                "confirm-milestone",
                "fail-milestone-verification",
            }.issubset(names)
        )

    def test_commands_reference_existing_templates_and_transitions(self) -> None:
        transitions = WORKFLOW["transitions"]
        for command in COMMANDS["commands"]:
            with self.subTest(command=command["name"]):
                self.assertIn(
                    command["family"], {"project", "milestone", "task", "lifecycle", "learning"}
                )
                self.assertIn(command["access"], {"read", "write", "conditional"})
                if command["access"] == "read":
                    self.assertEqual(command["approval"], "none")
                    self.assertIsNone(command["transition"])
                if command["template"]:
                    self.assertTrue((SKILL / "templates" / command["template"]).is_file())
                if command["transition"]:
                    self.assertIn(command["transition"], transitions)

    def test_execution_contract_covers_every_command(self) -> None:
        command_names = {command["name"] for command in COMMANDS["commands"]}

        self.assertEqual(set(EXECUTION["commands"]), command_names)
        for name in sorted(command_names):
            with self.subTest(command=name):
                result = run_contract("execution-envelope", name)
                self.assertEqual(result.returncode, 0, result.stderr)
                envelope = json.loads(result.stdout)
                self.assertEqual(envelope["command"]["name"], name)
                self.assertGreater(envelope["context"]["max_input_tokens"], 0)
                self.assertIn(
                    envelope["session_boundary"],
                    {
                        "single-command",
                        "single-stage",
                        "single-task",
                        "single-phase",
                        "single-wave",
                        "single-event",
                    },
                )

    def test_generated_catalog_is_current(self) -> None:
        result = subprocess.run(
            [sys.executable, str(CATALOG_SCRIPT), "--check"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_router_references_every_command_family(self) -> None:
        router = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("contracts envelope", router)
        self.assertIn("<namespace> <command>", router)
        self.assertIn("required_references", router)
        self.assertNotIn("Read `commands.json`", router)
        self.assertLess(len(router.split()), 1000)


class WorkflowContractTest(unittest.TestCase):
    def test_run_task_envelope_is_bounded_and_single_task(self) -> None:
        result = run_contract("execution-envelope", "run-task")

        self.assertEqual(result.returncode, 0, result.stderr)
        envelope = json.loads(result.stdout)
        self.assertEqual(envelope["approval"]["kind"], "invocation")
        self.assertEqual(envelope["context"]["max_input_tokens"], profile_limit("task"))
        self.assertEqual(envelope["context"]["max_siblings"], 6)
        self.assertEqual(envelope["session_boundary"], "single-task")
        self.assertIn("blocker_status_matrix", envelope["reads"])
        self.assertIn("planned_issue_readiness", envelope["reads"])
        self.assertIn("authoritative_current_plan", envelope["reads"])
        self.assertIn("verification_passed", envelope["postconditions"])
        self.assertIn("references/context-management.md", envelope["required_references"])

    def test_issue_intake_commands_compile_expected_contracts(self) -> None:
        expected = {
            "refine-task": ("preview", "task", "refine"),
            "plan-task": ("invocation", "task", "plan"),
            "organize-unplanned": ("conditional", "intake", None),
        }
        for name, (approval, context, issue_transition) in expected.items():
            with self.subTest(command=name):
                result = run_contract("execution-envelope", name)
                self.assertEqual(result.returncode, 0, result.stderr)
                envelope = json.loads(result.stdout)
                self.assertEqual(envelope["approval"]["kind"], approval)
                self.assertEqual(envelope["context"]["profile"], context)
                self.assertEqual(envelope["command"].get("issue_transition"), issue_transition)
                self.assertIn("references/issue-intake.md", envelope["required_references"])
                self.assertIn("team_issue_status_catalog", envelope["reads"])
                self.assertIn("required_statuses_resolved", envelope["postconditions"])
                if name == "organize-unplanned":
                    self.assertTrue(envelope["bulk"])
                if name == "plan-task":
                    self.assertEqual(envelope["orchestration"]["profile"], "planning")

        milestone_plan = run_contract("execution-envelope", "plan-tasks")
        self.assertEqual(milestone_plan.returncode, 0, milestone_plan.stderr)
        milestone_envelope = json.loads(milestone_plan.stdout)
        self.assertEqual(milestone_envelope["command"]["issue_transition"], "plan")
        self.assertIn("references/issue-intake.md", milestone_envelope["required_references"])
        self.assertIn("backlog_status_after_plan_read_back", milestone_envelope["writes"])

        task_creation = run_contract("execution-envelope", "create-tasks")
        self.assertEqual(task_creation.returncode, 0, task_creation.stderr)
        self.assertIn("created_task_unplanned_status", json.loads(task_creation.stdout)["writes"])

    def test_issue_status_transitions_are_command_bound(self) -> None:
        refined = run_contract(
            "issue-transition",
            "refine-task",
            "--from-status",
            "Human draft",
            "--to-status",
            "Unplanned",
        )
        planned = run_contract(
            "issue-transition",
            "plan-task",
            "--from-status",
            "Unplanned",
            "--to-status",
            "Backlog",
        )
        skipped_refinement = run_contract(
            "issue-transition",
            "plan-task",
            "--from-status",
            "Human draft",
            "--to-status",
            "Backlog",
        )
        wrong_target = run_contract(
            "issue-transition",
            "refine-task",
            "--from-status",
            "Human draft",
            "--to-status",
            "Backlog",
        )
        unrelated_command = run_contract(
            "issue-transition",
            "run-task",
            "--from-status",
            "Backlog",
            "--to-status",
            "In Progress",
        )

        self.assertEqual(refined.returncode, 0, refined.stderr)
        self.assertEqual(json.loads(refined.stdout)["to_status"], "Unplanned")
        self.assertEqual(planned.returncode, 0, planned.stderr)
        self.assertEqual(json.loads(planned.stdout)["to_status"], "Backlog")
        self.assertEqual(skipped_refinement.returncode, 2)
        self.assertIn("does not allow status Human draft", skipped_refinement.stderr)
        self.assertEqual(wrong_target.returncode, 2)
        self.assertIn("must target status Unplanned", wrong_target.stderr)
        self.assertEqual(unrelated_command.returncode, 2)
        self.assertIn("does not declare an issue transition", unrelated_command.stderr)

    def test_issue_workflow_uses_exact_human_readiness_statuses(self) -> None:
        self.assertEqual(
            ISSUE_WORKFLOW["statuses"],
            {
                "human_draft": "Human draft",
                "unplanned": "Unplanned",
                "backlog": "Backlog",
            },
        )
        intake_policy = (SKILL / "references" / "issue-intake.md").read_text(encoding="utf-8")
        task_policy = (SKILL / "references" / "task-commands.md").read_text(encoding="utf-8")
        lifecycle = (
            ROOT / "skills" / "linear-workflow" / "references" / "task-lifecycle.md"
        ).read_text(encoding="utf-8")
        self.assertIn("A title, label, component, or technology match alone is", intake_policy)
        self.assertIn("AI-created complementary tasks start in `Unplanned`", intake_policy)
        self.assertIn("Stop if the issue is `Human draft` or `Unplanned`", task_policy)
        self.assertIn("Human draft", lifecycle)
        self.assertIn("Unplanned", lifecycle)
        self.assertIn("Backlog", lifecycle)

    def test_help_envelope_loads_only_the_generated_catalog(self) -> None:
        result = run_contract("execution-envelope", "help")

        self.assertEqual(result.returncode, 0, result.stderr)
        envelope = json.loads(result.stdout)
        self.assertEqual(envelope["required_references"], ["references/command-catalog.md"])

    def test_run_milestone_envelope_stops_after_one_stage(self) -> None:
        result = run_contract("execution-envelope", "run-milestone")

        self.assertEqual(result.returncode, 0, result.stderr)
        envelope = json.loads(result.stdout)
        self.assertEqual(envelope["approval"]["kind"], "per_operation")
        self.assertEqual(envelope["session_boundary"], "single-stage")

    def test_context_check_accepts_usage_within_budget(self) -> None:
        result = run_contract(
            "context-check",
            "run-task",
            "--estimated-tokens",
            "11000",
            "--metric",
            "max_siblings=6",
            "--metric",
            "max_blocker_nodes=20",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "within-budget")

    def test_context_check_rejects_overflow(self) -> None:
        result = run_contract(
            "context-check",
            "run-task",
            "--estimated-tokens",
            str(profile_limit("task") + 1),
            "--metric",
            "max_siblings=7",
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("CONTEXT_OVERFLOW", result.stderr)
        limit = profile_limit("task")
        self.assertIn(f"max_input_tokens={limit + 1} > {limit}", result.stderr)
        self.assertIn("max_siblings=7 > 6", result.stderr)

    def test_context_check_rejects_unknown_metrics(self) -> None:
        result = run_contract(
            "context-check",
            "run-task",
            "--estimated-tokens",
            "1000",
            "--metric",
            "unbounded_comments=1",
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown context metric", result.stderr)

    def test_context_packet_measures_text_and_requires_every_limit(self) -> None:
        packet = {
            "items": ["small bounded evidence"],
            "metrics": {
                "max_blocker_depth": ["depth-1"],
                "max_blocker_nodes": ["blocker-1"],
                "max_full_blockers": ["blocker-1"],
                "max_siblings": ["sibling-1"],
                "max_learning_entries": ["learning-1"],
                "max_raw_log_characters": ["short log"],
            },
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json") as source:
            json.dump(packet, source)
            source.flush()
            result = run_contract("context-packet", "run-task", source.name)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "within-budget")

    def test_repository_scan_tiers_are_compiled_and_command_scoped(self) -> None:
        default = run_contract("execution-envelope", "import-codebase")
        heavy = run_contract("execution-envelope", "import-codebase", "--scan", "heavy")
        existing = run_contract("execution-envelope", "run-task")
        unsupported = run_contract("execution-envelope", "help", "--scan", "fast")

        self.assertEqual(default.returncode, 0, default.stderr)
        self.assertEqual(json.loads(default.stdout)["repository_scan"]["tier"], "medium")
        self.assertEqual(heavy.returncode, 0, heavy.stderr)
        heavy_scan = json.loads(heavy.stdout)["repository_scan"]
        self.assertEqual(heavy_scan["tier"], "heavy")
        self.assertEqual(heavy_scan["context"]["max_repository_files"], 1000)
        self.assertEqual(json.loads(existing.stdout)["repository_scan"]["tier"], "fast")
        self.assertEqual(unsupported.returncode, 2)
        self.assertIn("does not read repository code", unsupported.stderr)

    def test_repository_context_packet_measures_total_and_batch_budgets(self) -> None:
        packet = {
            "items": ["bounded raw source batch"],
            "metrics": {
                "max_repository_files": ["src/a.py", "src/b.py"],
                "max_source_bytes": ["def a(): pass", "def b(): pass"],
                "max_batches": ["batch-1"],
                "max_files_per_batch": ["src/a.py", "src/b.py"],
                "max_git_commits": ["abc123"],
                "max_manifest_files": ["pyproject.toml"],
                "max_test_files": ["tests/test_a.py"],
                "max_capsule_tokens": ["small evidence capsule"],
            },
        }
        overflow_packet = json.loads(json.dumps(packet))
        overflow_packet["metrics"]["max_source_bytes"] = ["x" * 50001]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            valid_path = root / "valid.json"
            overflow_path = root / "overflow.json"
            valid_path.write_text(json.dumps(packet), encoding="utf-8")
            overflow_path.write_text(json.dumps(overflow_packet), encoding="utf-8")
            valid = run_contract(
                "context-packet",
                "analyze-codebase",
                str(valid_path),
                "--scope",
                "repository",
                "--scan",
                "fast",
            )
            overflow = run_contract(
                "context-packet",
                "analyze-codebase",
                str(overflow_path),
                "--scope",
                "repository",
                "--scan",
                "fast",
            )

        self.assertEqual(valid.returncode, 0, valid.stderr)
        self.assertEqual(json.loads(valid.stdout)["context"], "repository:fast")
        self.assertEqual(overflow.returncode, 2)
        self.assertIn("CONTEXT_OVERFLOW", overflow.stderr)
        self.assertIn("max_source_bytes=50001 > 50000", overflow.stderr)

    def test_repository_checkpoint_validates_lineage_capsules_and_drift(self) -> None:
        digest = "sha256:" + "a" * 64
        checkpoint = {
            "schema_version": 1,
            "run_id": "scan-1",
            "command": "analyze-codebase",
            "scan_tier": "medium",
            "repository_root": "/repo",
            "source_revision": "abc123",
            "repository_fingerprint": digest,
            "stage": "shard-analysis",
            "completed_batch_ids": ["batch-1"],
            "remaining_batch_ids": ["batch-2"],
            "coverage": {
                "eligible_files": 20,
                "selected_files": 16,
                "analyzed_files": 8,
                "excluded_files": 4,
                "selected_source_bytes": 120000,
            },
            "capsules": [
                {
                    "capsule_id": "auth",
                    "module": "authentication",
                    "source_hashes": [digest],
                    "responsibilities": ["authenticate users"],
                    "public_interfaces": ["login"],
                    "dependencies": ["database"],
                    "implemented_capabilities": ["password login"],
                    "tests_and_verification": ["tests/test_auth.py"],
                    "known_gaps": [],
                    "evidence_pointers": ["src/auth.py:login"],
                    "confidence": "high",
                }
            ],
            "completion_findings": [
                {
                    "outcome": "Password authentication delivered",
                    "classification": "verified-delivered",
                    "evidence_pointers": ["src/auth.py:login"],
                    "verification_evidence": ["tests/test_auth.py passed"],
                    "confidence": "high",
                }
            ],
            "next_command": "analyze-codebase --resume scan-1",
        }
        malformed = json.loads(json.dumps(checkpoint))
        malformed["capsules"][0]["raw_source"] = "secret"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkpoint["repository_root"] = str(root)
            malformed["repository_root"] = str(root)
            valid_path = root / "valid.json"
            malformed_path = root / "malformed.json"
            valid_path.write_text(json.dumps(checkpoint), encoding="utf-8")
            malformed_path.write_text(json.dumps(malformed), encoding="utf-8")
            valid = run_contract("scan-checkpoint", str(valid_path))
            drift = run_contract(
                "scan-checkpoint",
                str(valid_path),
                "--expected-source-revision",
                "def456",
            )
            trace_refresh = run_contract(
                "scan-checkpoint",
                str(valid_path),
                "--expected-source-revision",
                "def456",
                "--drift-classification",
                "valid",
            )
            rejected = run_contract("scan-checkpoint", str(malformed_path))

        self.assertEqual(valid.returncode, 0, valid.stderr)
        self.assertEqual(json.loads(valid.stdout)["status"], "valid")
        self.assertEqual(drift.returncode, 2)
        self.assertIn("REPOSITORY_DRIFT", drift.stderr)
        self.assertEqual(trace_refresh.returncode, 0, trace_refresh.stderr)
        self.assertTrue(json.loads(trace_refresh.stdout)["trace_source_revision_changed"])
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("capsule fields are incomplete", rejected.stderr)

    def test_repository_checkpoint_must_remain_inside_repository(self) -> None:
        digest = "sha256:" + "a" * 64
        with tempfile.TemporaryDirectory() as repository, tempfile.TemporaryDirectory() as outside:
            checkpoint = {
                "schema_version": 1,
                "run_id": "scan-1",
                "command": "analyze-codebase",
                "scan_tier": "fast",
                "repository_root": repository,
                "source_revision": "abc123",
                "repository_fingerprint": digest,
                "stage": "inventory",
                "completed_batch_ids": [],
                "remaining_batch_ids": ["batch-1"],
                "coverage": {
                    "eligible_files": 1,
                    "selected_files": 1,
                    "analyzed_files": 0,
                    "excluded_files": 0,
                    "selected_source_bytes": 10,
                },
                "capsules": [],
                "completion_findings": [],
                "next_command": "analyze-codebase --resume scan-1",
            }
            path = Path(outside) / "checkpoint.json"
            path.write_text(json.dumps(checkpoint), encoding="utf-8")
            result = run_contract("scan-checkpoint", str(path))

        self.assertEqual(result.returncode, 2)
        self.assertIn("must remain inside the repository", result.stderr)

    def test_repository_scan_tier_limits_are_monotonic(self) -> None:
        profiles = REPOSITORY_SCAN["profiles"]
        for metric in profiles["fast"]:
            with self.subTest(metric=metric):
                self.assertLessEqual(profiles["fast"][metric], profiles["medium"][metric])
                self.assertLessEqual(profiles["medium"][metric], profiles["heavy"][metric])
        for tier, profile in profiles.items():
            with self.subTest(tier=tier):
                self.assertLessEqual(
                    profile["max_repository_files"],
                    profile["max_batches"] * profile["max_files_per_batch"],
                )
                self.assertLessEqual(
                    profile["max_source_bytes"],
                    profile["max_batches"] * profile["max_input_tokens"] * 4,
                )

    def test_import_uses_staged_approval_and_completion_classifications(self) -> None:
        envelope = json.loads(run_contract("execution-envelope", "import-codebase").stdout)
        template = (SKILL / "templates" / "codebase-import-proposal.md").read_text(encoding="utf-8")

        self.assertEqual(envelope["approval"]["kind"], "staged")
        self.assertEqual(envelope["approval"]["stages"]["analysis_checkpoint"], "invocation")
        self.assertEqual(
            envelope["approval"]["stages"]["linear_project_and_milestones"],
            "preview",
        )
        for classification in REPOSITORY_SCAN["completion_classifications"]:
            self.assertIn(classification, template)

    def test_advance_state_binds_command_transition_and_marker_lineage(self) -> None:
        current = (
            '<!-- linear-spanks:state {"last_command":"create-tasks","milestone_id":"m",'
            '"project_id":"p","resume_stage":null,"revision":4,"run_id":"r",'
            '"schema_version":1,"stage":"tasks-created",'
            '"updated_at":"2026-07-13T10:00:00+00:00"} -->'
        )
        replacement = (
            '<!-- linear-spanks:state {"last_command":"plan-tasks","milestone_id":"m",'
            '"project_id":"p","resume_stage":null,"revision":5,"run_id":"r",'
            '"schema_version":1,"stage":"tasks-planned",'
            '"updated_at":"2026-07-13T10:01:00+00:00"} -->'
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            current_path = root / "current.md"
            replacement_path = root / "replacement.md"
            current_path.write_text(current, encoding="utf-8")
            replacement_path.write_text(replacement, encoding="utf-8")
            result = run_contract(
                "advance-state",
                "--command",
                "plan-tasks",
                "--transition",
                "plan-tasks",
                "--current-marker",
                str(current_path),
                "--replacement-marker",
                str(replacement_path),
            )
            wrong_command = run_contract(
                "advance-state",
                "--command",
                "wrap-milestone",
                "--transition",
                "plan-tasks",
                "--current-marker",
                str(current_path),
                "--replacement-marker",
                str(replacement_path),
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["to"], "tasks-planned")
        self.assertEqual(wrong_command.returncode, 2)
        self.assertIn("not declared", wrong_command.stderr)

    def test_valid_transition_returns_target(self) -> None:
        result = run_contract("transition", "plan-tasks", "--from", "tasks-created")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "tasks-planned")

    def test_invalid_transition_is_rejected(self) -> None:
        result = run_contract("transition", "wrap-milestone", "--from", "draft")

        self.assertEqual(result.returncode, 2)
        self.assertIn("does not allow stage draft", result.stderr)

    def test_resume_requires_non_terminal_destination(self) -> None:
        result = run_contract(
            "transition", "resume", "--from", "paused", "--resume-stage", "archived"
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("non-terminal", result.stderr)

    def test_resume_requires_the_stored_pause_destination(self) -> None:
        result = run_contract("transition", "resume", "--from", "paused", "--resume-stage", "draft")

        self.assertEqual(result.returncode, 2)
        self.assertIn("stored pause destination", result.stderr)

    def test_paused_marker_requires_resume_stage(self) -> None:
        marker = run_contract(
            "marker",
            "--project-id",
            "project-1",
            "--milestone-id",
            "milestone-1",
            "--stage",
            "paused",
            "--revision",
            "4",
            "--last-command",
            "pause-milestone",
            "--run-id",
            "run-1",
        )

        self.assertEqual(marker.returncode, 2)
        self.assertIn("requires a valid non-terminal resume_stage", marker.stderr)

    def test_marker_round_trip(self) -> None:
        marker = run_contract(
            "marker",
            "--project-id",
            "project-1",
            "--milestone-id",
            "milestone-1",
            "--stage",
            "tasks-planned",
            "--revision",
            "4",
            "--last-command",
            "plan-tasks",
            "--run-id",
            "run-1",
            "--updated-at",
            "2026-07-13T10:00:00+00:00",
        )
        self.assertEqual(marker.returncode, 0, marker.stderr)

        parsed = run_contract("parse-marker", input_text=f"Description\n{marker.stdout}")
        self.assertEqual(parsed.returncode, 0, parsed.stderr)
        payload = json.loads(parsed.stdout)
        self.assertEqual(payload["stage"], "tasks-planned")
        self.assertEqual(payload["revision"], 4)

    def test_marker_rejects_invalid_timestamp(self) -> None:
        result = run_contract(
            "marker",
            "--project-id",
            "project-1",
            "--milestone-id",
            "milestone-1",
            "--stage",
            "tasks-planned",
            "--revision",
            "4",
            "--last-command",
            "plan-tasks",
            "--run-id",
            "run-1",
            "--updated-at",
            "not-a-timestamp",
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("RFC 3339", result.stderr)

    def test_marker_rejects_command_that_could_not_produce_stage(self) -> None:
        result = run_contract(
            "marker",
            "--project-id",
            "project-1",
            "--milestone-id",
            "milestone-1",
            "--stage",
            "tasks-planned",
            "--revision",
            "4",
            "--last-command",
            "wrap-milestone",
            "--run-id",
            "run-1",
            "--updated-at",
            "2026-07-13T10:00:00+00:00",
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("could not produce stage", result.stderr)

    def test_idempotency_key_is_stable_and_revision_sensitive(self) -> None:
        base = (
            "idempotency-key",
            "--project-id",
            "project-1",
            "--entity-id",
            "milestone-1",
            "--command",
            "verify-milestone",
        )
        first = run_contract(*base, "--revision", "4")
        repeat = run_contract(*base, "--revision", "4")
        changed = run_contract(*base, "--revision", "5")

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout, repeat.stdout)
        self.assertNotEqual(first.stdout, changed.stdout)

    def test_operation_idempotency_key_includes_payload_identity(self) -> None:
        base = (
            "idempotency-key",
            "--project-id",
            "project-1",
            "--entity-id",
            "milestone-1",
            "--command",
            "create-tasks",
            "--revision",
            "4",
            "--operation-id",
            "create-task-ENG-42",
        )
        first_hash = "sha256:" + "a" * 64
        changed_hash = "sha256:" + "b" * 64
        first = run_contract(*base, "--payload-hash", first_hash)
        repeat = run_contract(*base, "--payload-hash", first_hash)
        changed = run_contract(*base, "--payload-hash", changed_hash)

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout, repeat.stdout)
        self.assertNotEqual(first.stdout, changed.stdout)

    def test_operation_idempotency_requires_operation_and_payload_together(self) -> None:
        result = run_contract(
            "idempotency-key",
            "--project-id",
            "project-1",
            "--entity-id",
            "milestone-1",
            "--command",
            "create-tasks",
            "--revision",
            "4",
            "--operation-id",
            "create-task-ENG-42",
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("must be supplied together", result.stderr)

    def test_bulk_idempotency_requires_operation_identity(self) -> None:
        result = run_contract(
            "idempotency-key",
            "--project-id",
            "project-1",
            "--entity-id",
            "milestone-1",
            "--command",
            "create-tasks",
            "--revision",
            "4",
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("bulk command", result.stderr)

    def test_project_epoch_commands_compile_staged_bounded_contracts(self) -> None:
        checkpoint = json.loads(
            run_contract("execution-envelope", "checkpoint-project", "--assurance", "fast").stdout
        )
        rollover = json.loads(
            run_contract("execution-envelope", "rollover-project", "--assurance", "fast").stdout
        )

        self.assertEqual(checkpoint["context"]["max_capsule_bytes"], 24576)
        self.assertEqual(checkpoint["session_boundary"], "single-command")
        self.assertEqual(checkpoint["assurance"]["effective"], "strict")
        self.assertIn("references/project-epoch.md", checkpoint["required_references"])
        self.assertEqual(rollover["approval"]["kind"], "staged")
        self.assertEqual(rollover["approval"]["stages"]["inventory"], "invocation")
        self.assertEqual(rollover["approval"]["stages"]["source_completion"], "preview")
        self.assertEqual(rollover["session_boundary"], "single-phase")
        self.assertTrue(rollover["bulk"])
        self.assertIn("--resume <receipt>", rollover["command"]["usage"])
        self.assertEqual(rollover["assurance"]["effective"], "strict")
        self.assertEqual(
            rollover["project_epoch"]["rollover"]["drift_result"],
            "ROLLOVER_DRIFT",
        )

    def test_project_capsule_validates_body_batches_and_complete_coverage(self) -> None:
        result = run_contract(
            "project-capsule-check", input_text=json.dumps(project_capsule_fixture())
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        validated = json.loads(result.stdout)
        self.assertEqual(validated["covered_sources"], 2)
        self.assertEqual(validated["excluded_sources"], 1)
        self.assertEqual(validated["status"], "valid")

    def test_project_capsule_rejects_overflow_and_coverage_gaps(self) -> None:
        overflow = project_capsule_fixture()
        overflow["body"] += "x" * 24576
        gap = project_capsule_fixture()
        gap["coverage"]["expected_source_ids"].append("issue-missing")

        overflow_result = run_contract("project-capsule-check", input_text=json.dumps(overflow))
        gap_result = run_contract("project-capsule-check", input_text=json.dumps(gap))

        self.assertEqual(overflow_result.returncode, 2)
        self.assertIn("CONTEXT_OVERFLOW", overflow_result.stderr)
        self.assertEqual(gap_result.returncode, 2)
        self.assertIn("does not reconcile", gap_result.stderr)

    def test_project_compaction_packet_measures_capsule_bytes(self) -> None:
        limits = EXECUTION["context_profiles"]["project_compaction"]
        payload = {
            "items": ["small context"],
            "metrics": {
                "max_inventory_batches": [],
                "max_compact_rows_per_batch": [],
                "max_full_entities_per_batch": [],
                "max_capsule_bytes": ["x" * (limits["max_capsule_bytes"] + 1)],
            },
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json") as source:
            json.dump(payload, source)
            source.flush()
            result = run_contract("context-packet", "checkpoint-project", source.name)

        self.assertEqual(result.returncode, 2)
        self.assertIn("max_capsule_bytes=24577 > 24576", result.stderr)

    def test_rollover_transition_allows_only_same_or_next_phase(self) -> None:
        valid = run_contract(
            "rollover-transition", "--from", "preview", "--to", "successor-created"
        )
        skipped = run_contract(
            "rollover-transition", "--from", "preview", "--to", "roadmap-created"
        )

        self.assertEqual(valid.returncode, 0, valid.stderr)
        self.assertEqual(valid.stdout.strip(), "successor-created")
        self.assertEqual(skipped.returncode, 2)
        self.assertIn("does not allow", skipped.stderr)

    def test_final_rollover_receipt_requires_durable_readback_and_empty_frontier(self) -> None:
        receipt = rollover_receipt_fixture("finalized")
        result = run_contract(
            "rollover-receipt-check",
            input_text=json.dumps(receipt),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        validated = json.loads(result.stdout)
        self.assertEqual(validated["phase"], "finalized")
        self.assertEqual(validated["successor_project_id"], "project-2")
        self.assertEqual(validated["unresolved_source_items"], 0)

    def test_rollover_rejects_drift_unsafe_carryover_and_early_completion(self) -> None:
        receipt = rollover_receipt_fixture("carryover-created")
        unsafe = json.loads(json.dumps(receipt))
        unsafe["carryovers"][0]["successor_status"] = "Backlog"
        early_completion = rollover_receipt_fixture("roadmap-created")
        early_completion["source_project"]["status"] = "Completed"

        drift = run_contract(
            "rollover-receipt-check",
            "--expected-source-revision",
            "43",
            input_text=json.dumps(receipt),
        )
        unsafe_result = run_contract("rollover-receipt-check", input_text=json.dumps(unsafe))
        early_result = run_contract(
            "rollover-receipt-check", input_text=json.dumps(early_completion)
        )

        self.assertEqual(drift.returncode, 2)
        self.assertIn("ROLLOVER_DRIFT", drift.stderr)
        self.assertEqual(unsafe_result.returncode, 2)
        self.assertIn("carryover was not recreated safely", unsafe_result.stderr)
        self.assertEqual(early_result.returncode, 2)
        self.assertIn("cannot complete the source before finalization", early_result.stderr)

    def test_rollover_binds_capsule_initiative_and_carryovers_to_source(self) -> None:
        capsule_drift = rollover_receipt_fixture("successor-created")
        capsule_drift["capsule"]["source_snapshot_hash"] = "sha256:" + "c" * 64
        wrong_initiative = rollover_receipt_fixture("successor-created")
        wrong_initiative["initiative"]["successor_initiative_id"] = "initiative-2"
        missing_disposition = rollover_receipt_fixture("carryover-created")
        missing_disposition["issue_dispositions"] = []
        missing_disposition["unresolved_source_items"] = ["milestone-1"]

        capsule_result = run_contract(
            "rollover-receipt-check", input_text=json.dumps(capsule_drift)
        )
        initiative_result = run_contract(
            "rollover-receipt-check", input_text=json.dumps(wrong_initiative)
        )
        disposition_result = run_contract(
            "rollover-receipt-check", input_text=json.dumps(missing_disposition)
        )

        self.assertEqual(capsule_result.returncode, 2)
        self.assertIn("ROLLOVER_DRIFT", capsule_result.stderr)
        self.assertEqual(initiative_result.returncode, 2)
        self.assertIn("Initiative does not match", initiative_result.stderr)
        self.assertEqual(disposition_result.returncode, 2)
        self.assertIn("missing source dispositions", disposition_result.stderr)

    def test_source_resolution_rejects_partial_dispositions(self) -> None:
        receipt = rollover_receipt_fixture("source-resolved")
        receipt["issue_dispositions"][0]["resolved"] = False
        receipt["unresolved_source_items"] = ["issue-1"]

        result = run_contract("rollover-receipt-check", input_text=json.dumps(receipt))

        self.assertEqual(result.returncode, 2)
        self.assertIn("disposition is unresolved", result.stderr)

    def test_rollover_bulk_idempotency_requires_operation_identity(self) -> None:
        result = run_contract(
            "idempotency-key",
            "--project-id",
            "project-1",
            "--entity-id",
            "project-1",
            "--command",
            "rollover-project",
            "--revision",
            "42",
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("bulk command", result.stderr)
