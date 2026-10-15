from __future__ import annotations

from tests.contract_support import *


class RoutingContractTest(unittest.TestCase):
    def recommend(self, fixture: str) -> dict[str, Any]:
        result = run_contract(
            "tier-recommend",
            input_text=json.dumps(assessment_fixture(fixture)),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_routing_contract_has_versioned_portable_vocabulary(self) -> None:
        self.assertEqual(ROUTING["schema_version"], 1)
        self.assertEqual(ROUTING["roles"], ["planner", "executor", "reviewer"])
        self.assertEqual(ROUTING["strengths"], ["low", "medium", "high"])
        self.assertEqual(
            ROUTING["harness_capabilities"],
            ["enforced", "inherited-model", "advisory-only"],
        )
        self.assertEqual(ROUTING["planner"]["strength"], "high")
        self.assertEqual(ROUTING["planner"]["access"], "read-only")
        self.assertGreater(ROUTING["planner"]["context"]["max_repository_files"], 0)

    def test_orchestration_envelopes_preserve_execution_contracts(self) -> None:
        expected = {
            "plan-task": "planning",
            "plan-tasks": "planning",
            "replan-task": "planning",
            "run-task": "task-execution",
            "implement-next": "task-execution",
            "verify-task": "task-verification",
        }
        for name, orchestration_profile in expected.items():
            with self.subTest(command=name):
                result = run_contract("execution-envelope", name)
                self.assertEqual(result.returncode, 0, result.stderr)
                envelope = json.loads(result.stdout)
                configuration = EXECUTION["commands"][name]
                execution = EXECUTION["execution_profiles"][configuration["execution"]]
                context = EXECUTION["context_profiles"][configuration["context"]]

                self.assertEqual(envelope["orchestration"]["profile"], orchestration_profile)
                self.assertEqual(envelope["approval"]["kind"], execution["approval"]["kind"])
                self.assertEqual(
                    envelope["context"]["max_input_tokens"],
                    context["max_input_tokens"],
                )
                self.assertEqual(envelope["session_boundary"], configuration["session_boundary"])
                self.assertTrue(set(execution["reads"]).issubset(envelope["reads"]))
                self.assertTrue(set(execution["writes"]).issubset(envelope["writes"]))
                self.assertTrue(
                    set(execution["postconditions"]).issubset(envelope["postconditions"])
                )
                # legacy-compiler characterization; the v2 path is locked in
                # tests/test_v2_reference_contract.py
                self.assertIn("references/model-routing.md", envelope["required_references"])
                self.assertEqual(
                    envelope["orchestration"]["worker_handoff"]["drift_result"],
                    "REPLAN_REQUIRED",
                )
                self.assertEqual(
                    envelope["orchestration"]["coordinator_owns"],
                    ROUTING["coordinator_owns"],
                )

    def test_planner_context_has_an_independent_hard_budget(self) -> None:
        accepted = run_contract(
            "context-check",
            "run-task",
            "--scope",
            "planner",
            "--estimated-tokens",
            "10000",
            "--metric",
            "max_repository_files=24",
        )
        overflow = run_contract(
            "context-check",
            "run-task",
            "--scope",
            "planner",
            "--estimated-tokens",
            "10001",
            "--metric",
            "max_repository_files=25",
        )

        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertEqual(json.loads(accepted.stdout)["context"], "planner")
        self.assertEqual(overflow.returncode, 2)
        self.assertIn("CONTEXT_OVERFLOW", overflow.stderr)
        self.assertIn("max_repository_files=25 > 24", overflow.stderr)

    def test_low_tier_is_deterministic_and_self_verifies(self) -> None:
        recommendation = self.recommend("low")

        self.assertEqual(recommendation["base_tier"], "low")
        self.assertEqual(recommendation["executor_tier"], "low")
        self.assertFalse(recommendation["review"]["required"])
        self.assertFalse(recommendation["worker_may_downgrade"])

    def test_uncertainty_escalates_low_to_medium(self) -> None:
        recommendation = self.recommend("uncertain-low")

        self.assertEqual(recommendation["base_tier"], "low")
        self.assertEqual(recommendation["executor_tier"], "medium")
        self.assertTrue(recommendation["uncertainty_escalated"])

    def test_two_medium_dimensions_escalate_to_high(self) -> None:
        recommendation = self.recommend("high-two-medium")

        self.assertEqual(recommendation["executor_tier"], "high")
        self.assertEqual(recommendation["review"]["strength"], "high")
        self.assertTrue(recommendation["review"]["independent"])

    def test_critical_risk_requires_high_tier_and_high_review(self) -> None:
        recommendation = self.recommend("high-critical")

        self.assertEqual(recommendation["executor_tier"], "high")
        self.assertIn("security_privacy_or_auth", recommendation["active_dimensions"])
        self.assertEqual(recommendation["review"]["strength"], "high")

    def test_medium_interface_risk_requires_independent_medium_review(self) -> None:
        recommendation = self.recommend("medium-interface")

        self.assertEqual(recommendation["executor_tier"], "medium")
        self.assertTrue(recommendation["review"]["required"])
        self.assertEqual(recommendation["review"]["strength"], "medium")

    def test_malformed_assessment_fails_instead_of_defaulting_low(self) -> None:
        result = run_contract(
            "tier-recommend",
            input_text=json.dumps(ASSESSMENT_FIXTURES["malformed"]),
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("assessment field mismatch", result.stderr)

    def test_enforced_and_advisory_routing_are_reported_explicitly(self) -> None:
        enforced = run_contract(
            "routing-check",
            "--harness",
            "codex",
            "--role",
            "executor",
            "--strength",
            "low",
            "--configured-model",
            "user/low",
        )
        advisory = run_contract(
            "routing-check",
            "--harness",
            "antigravity",
            "--role",
            "executor",
            "--strength",
            "low",
        )

        self.assertEqual(enforced.returncode, 0, enforced.stderr)
        enforced_payload = json.loads(enforced.stdout)
        self.assertTrue(enforced_payload["enforced"])
        self.assertEqual(enforced_payload["tier_enforcement_status"], "enforced")
        self.assertEqual(enforced_payload["configured_model_when_observable"], "user/low")
        self.assertEqual(advisory.returncode, 0, advisory.stderr)
        advisory_payload = json.loads(advisory.stdout)
        self.assertFalse(advisory_payload["enforced"])
        self.assertTrue(advisory_payload["fallback"]["used"])
        self.assertEqual(advisory_payload["capability"], "inherited-model")

    def test_kimi_profile_route_is_advisory(self) -> None:
        result = run_contract(
            "routing-check",
            "--harness",
            "kimi",
            "--role",
            "planner",
            "--strength",
            "high",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["native_profile"], "plan")
        self.assertEqual(payload["capability"], "advisory-only")
        self.assertFalse(payload["enforced"])

    def test_replan_recomputes_tier_and_worker_drift_is_terminal(self) -> None:
        replan = json.loads(run_contract("execution-envelope", "replan-task").stdout)
        run_task = json.loads(run_contract("execution-envelope", "run-task").stdout)
        template = (SKILL / "templates" / "replan-task.md").read_text(encoding="utf-8")

        self.assertTrue(replan["orchestration"]["recompute_tier"])
        self.assertEqual(
            run_task["orchestration"]["worker_handoff"]["drift_result"],
            "REPLAN_REQUIRED",
        )
        self.assertIn("Recomputed executor tier", template)

    def test_implementation_plan_covers_every_plan_packet_field(self) -> None:
        template = (SKILL / "templates" / "implementation-plan.md").read_text(encoding="utf-8")
        field_phrases = {
            "plan_revision": "Plan revision",
            "planner_strength": "Planner strength",
            "source_revision": "Source revision",
            "repository_evidence": "Repository Evidence Inspected",
            "complexity_assessment": "Complexity and Routing",
            "executor_tier": "Executor tier",
            "tier_rationale": "Tier rationale",
            "escalation_triggers": "Escalation triggers",
            "reviewer_requirement": "Reviewer",
            "implementation_steps": "Exact Implementation Steps",
            "affected_interfaces": "Affected Interfaces",
            "verification_commands": "Verification Commands",
            "stop_replan_conditions": "Stop / Replan Conditions",
            "selected_skills": "Selected Skills",
            "execution_footprint": "Execution Footprint",
        }

        self.assertEqual(
            set(field_phrases),
            set(ROUTING["plan_packet"]["required_fields"]),
        )
        for field, phrase in field_phrases.items():
            with self.subTest(field=field):
                self.assertIn(phrase, template)

    def test_verification_failure_and_completion_routing_receipt_are_preserved(self) -> None:
        verification = json.loads(run_contract("execution-envelope", "verify-task").stdout)
        template = (SKILL / "templates" / "completion-handoff.md").read_text(encoding="utf-8")

        self.assertIn("failed_verification_remains_in_progress", verification["postconditions"])
        for field in (
            "Harness",
            "Worker role",
            "Requested strength",
            "Configured model when observable",
            "Tier enforcement",
            "Review result",
        ):
            self.assertIn(field, template)


class AssuranceProfileTest(unittest.TestCase):
    def scope_payload(self, limits: dict[str, Any], measured: bool) -> dict[str, Any]:
        metrics = {key: 0 for key in limits if key not in {"profile", "max_input_tokens"}}
        return {
            "estimated_tokens": 100,
            "context_bytes": 400,
            "metrics": metrics if measured else {},
            "measured": measured,
        }

    def decision_payload(
        self,
        command: str,
        fixture: str,
        assurance: str,
        *,
        strict_context: bool = False,
        current_plan: dict[str, Any] | None = None,
        tasks: list[dict[str, Any]] | None = None,
        harness: str = "codex",
        detected_drift: bool | str = False,
    ) -> dict[str, Any]:
        configuration = EXECUTION["commands"][command]
        command_limits = EXECUTION["context_profiles"][configuration["context"]]
        planning = command in {"plan-task", "plan-tasks", "replan-task"}
        plan = current_plan or {"present": False, "stale": False, "revision": None}
        plan_needed = planning or (
            command in {"run-task", "implement-next"} and (not plan["present"] or plan["stale"])
        )
        planner_context = (
            self.scope_payload(ROUTING["planner"]["context"], strict_context)
            if plan_needed
            else None
        )
        scan_tier = configuration.get("repository_scan", {}).get("default_tier")
        repository_context = (
            self.scope_payload(REPOSITORY_SCAN["profiles"][scan_tier], True) if scan_tier else None
        )
        return {
            "schema_version": 1,
            "command": command,
            "requested_assurance": assurance,
            "harness": harness,
            "scan_tier": scan_tier,
            "context": {
                "command": self.scope_payload(command_limits, strict_context),
                "planner": planner_context,
                "repository": repository_context,
                "large_matrix": False,
                "near_limit": False,
            },
            "assessment": assessment_fixture(fixture),
            "current_plan": plan,
            "detected_drift": detected_drift,
            "preflight": None,
            "planning_tasks": tasks or [],
        }

    def decide(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = run_contract("orchestration-decision", input_text=json.dumps(payload))
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_balanced_is_default_and_other_families_retain_strict_behavior(self) -> None:
        self.assertEqual(ROUTING["assurance"]["default"], "balanced")
        task = run_contract("execution-brief", "run-task")
        project = run_contract("execution-brief", "review-project", "--assurance", "fast")

        self.assertEqual(task.returncode, 0, task.stderr)
        self.assertEqual(json.loads(task.stdout)["assurance"]["effective"], "balanced")
        self.assertEqual(project.returncode, 0, project.stderr)
        project_brief = json.loads(project.stdout)
        self.assertEqual(project_brief["assurance"]["requested"], "fast")
        self.assertEqual(project_brief["assurance"]["effective"], "strict")

    def test_fast_and_balanced_low_risk_use_coordinator(self) -> None:
        fast = self.decide(self.decision_payload("plan-task", "low", "fast"))
        balanced = self.decide(self.decision_payload("plan-task", "low", "balanced"))

        self.assertEqual(fast["effective_assurance"], "fast")
        self.assertEqual(fast["planner"]["role"], "coordinator")
        self.assertEqual(fast["planner"]["runs"], 0)
        self.assertFalse(fast["review"]["required"])
        self.assertEqual(balanced["effective_assurance"], "balanced")
        self.assertIsNone(balanced["planner"]["strength"])
        self.assertEqual(balanced["planner"]["runs"], 0)

    def test_refine_task_uses_the_same_assurance_screen_without_delegation(self) -> None:
        fast = self.decide(self.decision_payload("refine-task", "low", "fast"))
        strict = self.decide(
            self.decision_payload("refine-task", "high-critical", "balanced", strict_context=True)
        )

        self.assertEqual(fast["effective_assurance"], "fast")
        self.assertEqual(fast["delegated_roles"], [])
        self.assertEqual(strict["effective_assurance"], "strict")
        self.assertEqual(strict["reviewer_runs"], 0)

    def test_assurance_resolution_escalates_risk_uncertainty_and_drift(self) -> None:
        fast_medium = self.decide(self.decision_payload("plan-task", "medium-interface", "fast"))
        fast_critical = self.decide(
            self.decision_payload("plan-task", "high-critical", "fast", strict_context=True)
        )
        uncertain = self.decide(
            self.decision_payload("plan-task", "uncertain-low", "balanced", strict_context=True)
        )
        drift = self.decide(
            self.decision_payload(
                "plan-task",
                "low",
                "balanced",
                strict_context=True,
                detected_drift=True,
            )
        )

        self.assertEqual(fast_medium["effective_assurance"], "balanced")
        self.assertEqual(fast_critical["effective_assurance"], "strict")
        self.assertEqual(uncertain["effective_assurance"], "strict")
        self.assertEqual(drift["effective_assurance"], "strict")
        self.assertIn("detected_drift", drift["assurance_escalation_reason"])

    def test_explicit_strict_uses_high_planner_and_exact_context(self) -> None:
        decision = self.decide(
            self.decision_payload("plan-task", "low", "strict", strict_context=True)
        )
        strict_brief = json.loads(
            run_contract("execution-brief", "plan-task", "--assurance", "strict").stdout
        )

        self.assertEqual(decision["effective_assurance"], "strict")
        self.assertEqual(decision["planner"]["strength"], "high")
        self.assertTrue(decision["context"]["command"]["measured"])
        self.assertTrue(decision["context"]["planner"]["measured"])
        self.assertTrue(decision["context"]["repository"]["measured"])
        # legacy-compiler characterization; see tests/test_v2_reference_contract.py for v2
        self.assertIn("references/model-routing.md", strict_brief["required_references"])

    def test_cross_harness_fallback_is_preserved_for_planned_work(self) -> None:
        decision = self.decide(
            self.decision_payload("plan-task", "medium-interface", "balanced", harness="kimi")
        )

        route = decision["routes"][0]
        self.assertEqual(route["role"], "planner")
        self.assertEqual(route["requested_strength"], "high")
        self.assertEqual(route["capability"], "advisory-only")
        self.assertEqual(route["native_profile"], "plan")

    def test_safety_invariants_cannot_be_disabled_by_assurance(self) -> None:
        invariant_sets = []
        for assurance in ("fast", "balanced", "strict"):
            invariant_sets.append(
                set(
                    self.decide(
                        self.decision_payload(
                            "run-task",
                            "low",
                            assurance,
                            strict_context=assurance == "strict",
                            current_plan={
                                "present": True,
                                "stale": False,
                                "revision": "plan-1",
                            },
                        )
                    )["safety_invariants"]
                )
            )
        self.assertEqual(invariant_sets[0], invariant_sets[1])
        self.assertEqual(invariant_sets[1], invariant_sets[2])
        self.assertIn("fresh_verification_before_done", invariant_sets[0])
        self.assertIn("final_durable_read_back", invariant_sets[0])

    def test_compact_briefs_reduce_task_startup_material_by_at_least_sixty_percent(self) -> None:
        for name in STARTUP_FIXTURE["commands"]:
            with self.subTest(command=name):
                envelope_result = run_contract("execution-envelope", name)
                brief_result = run_contract("execution-brief", name)
                self.assertEqual(envelope_result.returncode, 0, envelope_result.stderr)
                self.assertEqual(brief_result.returncode, 0, brief_result.stderr)
                envelope = json.loads(envelope_result.stdout)
                baseline_bytes = len(envelope_result.stdout.encode("utf-8")) + sum(
                    len((SKILL / reference).read_bytes())
                    for reference in envelope["required_references"]
                )
                compact_bytes = len(brief_result.stdout.encode("utf-8"))
                reduction = 100 * (baseline_bytes - compact_bytes) / baseline_bytes
                self.assertGreaterEqual(reduction, STARTUP_FIXTURE["minimum_reduction_percent"])
                self.assertEqual(json.loads(brief_result.stdout)["required_references"], [])

    def test_plan_task_fast_scan_and_repository_overflow_are_enforced(self) -> None:
        brief = run_contract("execution-brief", "plan-task", "--scan", "fast")
        payload = self.decision_payload("plan-task", "low", "balanced")
        payload["context"]["repository"]["estimated_tokens"] = 8001
        overflow = run_contract("orchestration-decision", input_text=json.dumps(payload))

        self.assertEqual(brief.returncode, 0, brief.stderr)
        self.assertEqual(json.loads(brief.stdout)["repository_scan"]["tier"], "fast")
        self.assertEqual(overflow.returncode, 2)
        self.assertIn("CONTEXT_OVERFLOW", overflow.stderr)

    def test_balanced_planner_batches_preserve_per_task_outputs_and_strict_isolated_runs(
        self,
    ) -> None:
        tasks = [
            {"id": "A", "blocked_by": []},
            {"id": "B", "blocked_by": ["A"]},
            {"id": "C", "blocked_by": ["B"]},
            {"id": "D", "blocked_by": ["C"]},
            {"id": "E", "blocked_by": ["D"]},
        ]
        balanced = self.decide(self.decision_payload("plan-tasks", "low", "balanced", tasks=tasks))
        strict = self.decide(
            self.decision_payload(
                "plan-tasks",
                "low",
                "strict",
                strict_context=True,
                tasks=tasks,
            )
        )

        self.assertEqual(balanced["planner"]["batches"], [["A", "B", "C", "D"], ["E"]])
        self.assertEqual(balanced["planner"]["runs"], 0)
        self.assertEqual(
            set(balanced["planner"]["per_task_outputs"]),
            {"plan_packet", "executor_tier", "plan_revision", "acceptance_mapping"},
        )
        self.assertEqual(strict["planner"]["runs"], 5)
        self.assertTrue(all(len(batch) == 1 for batch in strict["planner"]["batches"]))

    def test_preflight_receipt_reuse_and_every_bound_field_invalidation(self) -> None:
        fields = ROUTING["preflight_receipt"]["required_fields"]
        receipt = {
            "schema_version": 1,
            **{
                field: "fast"
                if field in {"requested_assurance", "effective_assurance", "scan_tier"}
                else "codex"
                if field == "harness"
                else f"{field}-1"
                for field in fields
                if field != "schema_version"
            },
        }
        current = {key: value for key, value in receipt.items() if key != "schema_version"}
        with tempfile.TemporaryDirectory() as temporary:
            receipt_path = Path(temporary) / "receipt.json"
            current_path = Path(temporary) / "current.json"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            current_path.write_text(json.dumps(current), encoding="utf-8")
            reused = run_contract("preflight-check", str(receipt_path), str(current_path))
            self.assertEqual(reused.returncode, 0, reused.stderr)
            self.assertTrue(json.loads(reused.stdout)["reused"])

            changed_repository = dict(current)
            changed_repository["repository_revision"] = "repo-r2"
            current_path.write_text(json.dumps(changed_repository), encoding="utf-8")
            trace_refresh = run_contract("preflight-check", str(receipt_path), str(current_path))
            self.assertEqual(trace_refresh.returncode, 0, trace_refresh.stderr)
            self.assertTrue(json.loads(trace_refresh.stdout)["reused"])
            self.assertEqual(
                json.loads(trace_refresh.stdout)["trace_changed"],
                ["repository_revision"],
            )

            for field in ROUTING["preflight_receipt"]["drift_fields"]:
                with self.subTest(field=field):
                    changed = dict(current)
                    if field == "requested_assurance":
                        changed[field] = "balanced"
                        changed["effective_assurance"] = "balanced"
                    elif field == "effective_assurance":
                        changed[field] = "balanced"
                    elif field == "scan_tier":
                        changed[field] = "medium"
                    elif field == "harness":
                        changed[field] = "kimi"
                    else:
                        changed[field] = changed[field] + "-changed"
                    current_path.write_text(json.dumps(changed), encoding="utf-8")
                    invalid = run_contract("preflight-check", str(receipt_path), str(current_path))
                    self.assertEqual(invalid.returncode, 0, invalid.stderr)
                    invalid_payload = json.loads(invalid.stdout)
                    self.assertFalse(invalid_payload["reused"])
                    self.assertIn(field, invalid_payload["invalidated_by"])

    def test_implement_next_preflight_reuses_in_run_task_and_assurance_change_invalidates(
        self,
    ) -> None:
        plan = {"present": True, "stale": False, "revision": "plan-1"}
        payload = self.decision_payload("run-task", "low", "balanced", current_plan=plan)
        bound = {
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
        payload["preflight"] = {
            "receipt": {"schema_version": 1, **bound},
            "current": dict(bound),
        }
        reused = self.decide(payload)
        payload["requested_assurance"] = "fast"
        invalidated = self.decide(payload)

        self.assertTrue(reused["preflight"]["reused"])
        self.assertFalse(invalidated["preflight"]["reused"])
        self.assertIn("requested_assurance", invalidated["preflight"]["invalidated_by"])

    def test_detected_execution_drift_stops_before_delegation(self) -> None:
        decision = self.decide(
            self.decision_payload(
                "run-task",
                "low",
                "balanced",
                strict_context=True,
                current_plan={
                    "present": True,
                    "stale": False,
                    "revision": "plan-1",
                },
                detected_drift=True,
            )
        )

        self.assertEqual(decision["effective_assurance"], "strict")
        self.assertEqual(decision["stop_result"], "REPLAN_REQUIRED")
        self.assertEqual(decision["routes"], [])
        self.assertEqual(decision["delegated_roles"], [])

    def test_scoped_trace_drift_does_not_stop_execution_or_escalate_assurance(self) -> None:
        decision = self.decide(
            self.decision_payload(
                "run-task",
                "low",
                "balanced",
                current_plan={
                    "present": True,
                    "stale": False,
                    "revision": "plan-1",
                },
                detected_drift="valid",
            )
        )

        self.assertEqual(decision["effective_assurance"], "balanced")
        self.assertEqual(decision["drift_classification"], "valid")
        self.assertIsNone(decision["stop_result"])
        self.assertIn("executor", decision["delegated_roles"])

        safe_refresh = self.decide(
            {
                **self.decision_payload(
                    "run-task",
                    "low",
                    "balanced",
                    current_plan={
                        "present": True,
                        "stale": False,
                        "revision": "plan-1",
                    },
                ),
                "detected_drift": "safe-refresh",
            }
        )
        self.assertEqual(safe_refresh["effective_assurance"], "balanced")
        self.assertEqual(safe_refresh["drift_classification"], "safe-refresh")
        self.assertIsNone(safe_refresh["stop_result"])
        self.assertEqual(safe_refresh["next_action"], "refresh-evidence")
        self.assertFalse(safe_refresh["dispatch_ready"])
        self.assertEqual(safe_refresh["delegated_roles"], [])

    def test_coalesced_readback_handles_success_partial_failure_stale_and_strict(self) -> None:
        base = {
            "schema_version": 1,
            "assurance": "balanced",
            "bulk": True,
            "operations": [
                {"entity_id": "A", "expected_revision": "2", "write_acknowledged": True},
                {"entity_id": "B", "expected_revision": "3", "write_acknowledged": True},
            ],
            "reconciliation": {"A": "2", "B": "3"},
        }
        success = run_contract("linear-readback-plan", input_text=json.dumps(base))
        partial = json.loads(json.dumps(base))
        partial["operations"][1]["write_acknowledged"] = False
        partial["reconciliation"]["B"] = None
        partial_result = run_contract("linear-readback-plan", input_text=json.dumps(partial))
        stale = json.loads(json.dumps(base))
        stale["reconciliation"]["B"] = "2"
        stale_result = run_contract("linear-readback-plan", input_text=json.dumps(stale))
        strict = json.loads(json.dumps(base))
        strict["assurance"] = "strict"
        strict_result = run_contract("linear-readback-plan", input_text=json.dumps(strict))

        self.assertEqual(success.returncode, 0, success.stderr)
        self.assertEqual(json.loads(success.stdout)["targeted_recovery_read_ids"], [])
        self.assertEqual(json.loads(partial_result.stdout)["targeted_recovery_read_ids"], ["B"])
        self.assertEqual(json.loads(stale_result.stdout)["targeted_recovery_read_ids"], ["B"])
        self.assertEqual(json.loads(strict_result.stdout)["final_read_ids"], ["A", "B"])

    def test_readback_projects_to_written_fields_and_defaults_to_a_full_read(self) -> None:
        """A read-back must prove the write landed, not pull whole entities into context."""
        payload = {
            "schema_version": 1,
            "assurance": "balanced",
            "bulk": False,
            "operations": [
                {
                    "entity_id": "A",
                    "expected_revision": "2",
                    "write_acknowledged": True,
                    "written_fields": ["state", "description"],
                },
                {"entity_id": "B", "expected_revision": "3", "write_acknowledged": True},
            ],
            "reconciliation": None,
        }
        result = run_contract("linear-readback-plan", input_text=json.dumps(payload))
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        # Declared writes project; identity and revision are always included for verification.
        self.assertEqual(plan["readback_fields"]["A"], ["description", "id", "revision", "state"])
        # An undeclared operation keeps the previous full-entity read rather than silently
        # narrowing what gets verified.
        self.assertIsNone(plan["readback_fields"]["B"])
        self.assertEqual(plan["mode"], "final-entity-read-back")

        strict = json.loads(json.dumps(payload))
        strict["assurance"] = "strict"
        strict_plan = json.loads(
            run_contract("linear-readback-plan", input_text=json.dumps(strict)).stdout
        )
        self.assertEqual(strict_plan["mode"], "per-write-read-back")
        expected_fields = ["description", "id", "revision", "state"]
        self.assertEqual(strict_plan["readback_fields"]["A"], expected_fields)

        invalid = json.loads(json.dumps(payload))
        invalid["operations"][0]["written_fields"] = []
        self.assertNotEqual(
            run_contract("linear-readback-plan", input_text=json.dumps(invalid)).returncode, 0
        )
        unknown = json.loads(json.dumps(payload))
        unknown["operations"][0]["unexpected"] = "x"
        self.assertNotEqual(
            run_contract("linear-readback-plan", input_text=json.dumps(unknown)).returncode, 0
        )

    def test_completion_receipt_metrics_and_verify_task_recovery_semantics(self) -> None:
        receipt = {
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
        result = run_contract("completion-receipt-check", input_text=json.dumps(receipt))
        verify_card = json.loads(run_contract("runtime-card", "verify-task").stdout)
        run_card = json.loads(run_contract("runtime-card", "run-task").stdout)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("resolved_target", run_card["reads"])
        self.assertIn("invocation_scoped_operations", run_card["writes"])
        self.assertIn("required_links_reported", run_card["postconditions"])
        self.assertEqual(
            verify_card["verification"],
            "explicit-recovery-or-independent-verification",
        )
        self.assertEqual(
            run_card["verification"],
            "fresh-in-command-verification-and-final-entity-read-back",
        )
