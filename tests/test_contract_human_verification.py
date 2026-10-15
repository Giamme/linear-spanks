from __future__ import annotations

from tests.contract_support import *


class HumanVerificationContractTest(unittest.TestCase):
    def affected_row(
        self,
        *,
        stage: str = "implementing",
        before: str = "disabled",
        after: str = "enabled",
        gate_id: str | None = None,
        gate_action: str = "create",
        checklist_id: str | None = None,
        checklist_action: str = "none",
        receipt_ids: list[str] | None = None,
        receipt_action: str = "reconcile",
    ) -> dict[str, Any]:
        return {
            "milestone_id": "milestone-1",
            "stage": stage,
            "before_effective": before,
            "after_effective": after,
            "gate_issue_id": gate_id,
            "gate_action": gate_action,
            "checklist_id": checklist_id,
            "checklist_action": checklist_action,
            "orchestration_receipt_ids": (["receipt-1"] if receipt_ids is None else receipt_ids),
            "receipt_action": receipt_action,
        }

    def test_public_commands_compile_human_contract_and_read_only_status(self) -> None:
        for name in (
            "set-human-verification-policy",
            "status-human-verification",
            "confirm-milestone",
            "fail-milestone-verification",
        ):
            with self.subTest(command=name):
                envelope = run_contract("execution-envelope", name)
                self.assertEqual(envelope.returncode, 0, envelope.stderr)
                payload = json.loads(envelope.stdout)
                self.assertEqual(payload["human_verification"]["system_default"], "disabled")
                self.assertIn(
                    "references/human-verification.md",
                    payload["required_references"],
                )
        status = json.loads(run_contract("execution-envelope", "status-human-verification").stdout)
        self.assertEqual(status["writes"], [])
        self.assertEqual(status["approval"]["kind"], "none")
        run_milestone = next(
            command for command in COMMANDS["commands"] if command["name"] == "run-milestone"
        )
        self.assertNotIn("confirm-milestone", run_milestone["transitions"])

    def test_missing_policy_is_disabled_and_precedence_is_override_project_system(self) -> None:
        missing = run_contract(
            "human-verification-effective",
            input_text=json.dumps(
                {
                    "project_id": "project-1",
                    "milestone_id": "milestone-1",
                    "project_policy": None,
                    "milestone_override": None,
                }
            ),
        )
        self.assertEqual(missing.returncode, 0, missing.stderr)
        self.assertEqual(json.loads(missing.stdout)["effective"], "disabled")
        self.assertEqual(json.loads(missing.stdout)["source"], "system-default")

        inherited_system = run_contract(
            "human-verification-effective",
            input_text=json.dumps(
                {
                    "project_id": "project-1",
                    "milestone_id": "milestone-1",
                    "project_policy": None,
                    "milestone_override": human_milestone_override("inherit", 2),
                }
            ),
        )
        self.assertEqual(inherited_system.returncode, 0, inherited_system.stderr)
        inherited_system_payload = json.loads(inherited_system.stdout)
        self.assertEqual(inherited_system_payload["effective"], "disabled")
        self.assertEqual(inherited_system_payload["milestone_override_revision"], 2)

        project = human_project_policy("enabled", 2)
        inherited = run_contract(
            "human-verification-effective",
            input_text=json.dumps(
                {
                    "project_id": "project-1",
                    "milestone_id": "milestone-1",
                    "project_policy": project,
                    "milestone_override": human_milestone_override("inherit", 3),
                }
            ),
        )
        self.assertEqual(inherited.returncode, 0, inherited.stderr)
        self.assertEqual(json.loads(inherited.stdout)["source"], "project-default")
        self.assertEqual(json.loads(inherited.stdout)["effective"], "enabled")

        disabled_override = run_contract(
            "human-verification-effective",
            input_text=json.dumps(
                {
                    "project_id": "project-1",
                    "milestone_id": "milestone-1",
                    "project_policy": project,
                    "milestone_override": human_milestone_override("disabled", 4),
                }
            ),
        )
        self.assertEqual(disabled_override.returncode, 0, disabled_override.stderr)
        self.assertEqual(json.loads(disabled_override.stdout)["source"], "milestone-override")
        self.assertEqual(json.loads(disabled_override.stdout)["effective"], "disabled")

    def test_project_policy_document_requires_capability_and_is_singleton(self) -> None:
        missing_read = run_contract(
            "human-verification-policy-document-check",
            input_text=json.dumps(
                {
                    "project_id": "project-1",
                    "document_capability": False,
                    "for_mutation": False,
                    "documents": [],
                }
            ),
        )
        self.assertEqual(missing_read.returncode, 0, missing_read.stderr)
        self.assertEqual(json.loads(missing_read.stdout)["effective_default"], "disabled")

        unavailable = run_contract(
            "human-verification-policy-document-check",
            input_text=json.dumps(
                {
                    "project_id": "project-1",
                    "document_capability": False,
                    "for_mutation": True,
                    "documents": [],
                }
            ),
        )
        self.assertEqual(unavailable.returncode, 2)
        self.assertIn("HUMAN_VERIFICATION_POLICY_UNAVAILABLE", unavailable.stderr)

        policy = human_project_policy()
        body = (
            "<!-- linear-spanks:human-verification-policy "
            + json.dumps(policy, sort_keys=True, separators=(",", ":"))
            + " -->"
        )
        document = {
            "id": "document-1",
            "title": HUMAN_VERIFICATION["project_policy"]["document_title"],
            "body": body,
        }
        found = run_contract(
            "human-verification-policy-document-check",
            input_text=json.dumps(
                {
                    "project_id": "project-1",
                    "document_capability": True,
                    "for_mutation": True,
                    "documents": [document],
                }
            ),
        )
        self.assertEqual(found.returncode, 0, found.stderr)
        self.assertEqual(json.loads(found.stdout)["document_id"], "document-1")

        collision = run_contract(
            "human-verification-policy-document-check",
            input_text=json.dumps(
                {
                    "project_id": "project-1",
                    "document_capability": True,
                    "for_mutation": True,
                    "documents": [document, {**document, "id": "document-2"}],
                }
            ),
        )
        self.assertEqual(collision.returncode, 2)
        self.assertIn("HUMAN_VERIFICATION_POLICY_COLLISION", collision.stderr)

    def test_policy_and_override_markers_reject_malformed_or_drifted_content(self) -> None:
        override = human_milestone_override("enabled")
        marker = (
            "<!-- linear-spanks:human-verification-override "
            + json.dumps(override, sort_keys=True, separators=(",", ":"))
            + " -->"
        )
        valid = run_contract(
            "human-verification-marker-check", "milestone-override", input_text=marker
        )
        self.assertEqual(valid.returncode, 0, valid.stderr)

        malformed = run_contract(
            "human-verification-marker-check",
            "milestone-override",
            input_text=marker + "\n" + marker,
        )
        self.assertEqual(malformed.returncode, 2)
        self.assertIn("expected exactly one", malformed.stderr)

        override["override"] = "disabled"
        drifted = run_contract("human-verification-override-check", input_text=json.dumps(override))
        self.assertEqual(drifted.returncode, 2)
        self.assertIn("HUMAN_VERIFICATION_POLICY_DRIFT", drifted.stderr)

    def test_policy_preview_is_exact_complete_idempotent_and_terminal_safe(self) -> None:
        enabling = approved_human_preview("enabled", [self.affected_row()])
        valid = run_contract("human-verification-preview-check", input_text=json.dumps(enabling))
        self.assertEqual(valid.returncode, 0, valid.stderr)

        reactivation = self.affected_row(
            gate_id="ENG-999",
            gate_action="reactivate",
            receipt_ids=[],
            receipt_action="none",
        )
        milestone_override = run_contract(
            "human-verification-preview-check",
            input_text=json.dumps(
                approved_human_preview("enabled", [reactivation], scope="milestone")
            ),
        )
        self.assertEqual(milestone_override.returncode, 0, milestone_override.stderr)

        stale = json.loads(json.dumps(enabling))
        stale["approved_hash"] = "sha256:" + "f" * 64
        rejected = run_contract("human-verification-preview-check", input_text=json.dumps(stale))
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("HUMAN_VERIFICATION_PREVIEW_REQUIRED", rejected.stderr)

        no_change = self.affected_row(
            before="enabled",
            after="enabled",
            gate_id="ENG-999",
            gate_action="none",
            receipt_ids=[],
            receipt_action="none",
        )
        idempotent = run_contract(
            "human-verification-preview-check",
            input_text=json.dumps(approved_human_preview("enabled", [no_change])),
        )
        self.assertEqual(idempotent.returncode, 0, idempotent.stderr)

        terminal = self.affected_row(stage="wrapped")
        terminal_preview = run_contract(
            "human-verification-preview-check",
            input_text=json.dumps(approved_human_preview("enabled", [terminal])),
        )
        self.assertEqual(terminal_preview.returncode, 2)
        self.assertIn("terminal milestone", terminal_preview.stderr)

    def test_pending_disable_requires_reason_bypass_gate_cancel_and_receipt_reconcile(self) -> None:
        row = self.affected_row(
            stage="milestone-verified",
            before="enabled",
            after="disabled",
            gate_id="ENG-999",
            gate_action="cancel",
            checklist_id="checklist-1",
            checklist_action="bypass",
        )
        missing_reason = run_contract(
            "human-verification-preview-check",
            input_text=json.dumps(approved_human_preview("disabled", [row])),
        )
        self.assertEqual(missing_reason.returncode, 2)
        self.assertIn("HUMAN_VERIFICATION_BYPASS_REASON_REQUIRED", missing_reason.stderr)

        approved = run_contract(
            "human-verification-preview-check",
            input_text=json.dumps(
                approved_human_preview("disabled", [row], reason="Product owner approved bypass")
            ),
        )
        self.assertEqual(approved.returncode, 0, approved.stderr)

        incomplete = json.loads(json.dumps(row))
        incomplete["receipt_action"] = "none"
        invalid = run_contract(
            "human-verification-preview-check",
            input_text=json.dumps(
                approved_human_preview(
                    "disabled", [incomplete], reason="Product owner approved bypass"
                )
            ),
        )
        self.assertEqual(invalid.returncode, 2)
        self.assertIn("receipt reconciliation", invalid.stderr)

    def test_managed_gate_is_excluded_and_duplicate_gate_fails_closed(self) -> None:
        effective = human_effective_policy("enabled", "project-default", project_revision=1)
        gate = human_gate(effective, "Todo")
        marker = (
            "<!-- linear-spanks:human-verification-gate "
            + json.dumps(gate, sort_keys=True, separators=(",", ":"))
            + " -->"
        )
        issues = [
            {"id": "ENG-1", "description": "Regular task"},
            {"id": "ENG-999", "description": marker},
        ]
        filtered = run_contract(
            "filter-human-verification-gates",
            input_text=json.dumps({"issues": issues}),
        )
        self.assertEqual(filtered.returncode, 0, filtered.stderr)
        payload = json.loads(filtered.stdout)
        self.assertEqual(payload["regular_task_total"], 1)
        self.assertEqual(payload["excluded_gate_issue_ids"], ["ENG-999"])

        duplicate_gate = json.loads(json.dumps(gate))
        duplicate_gate["issue_id"] = "ENG-998"
        duplicate_marker = (
            "<!-- linear-spanks:human-verification-gate "
            + json.dumps(duplicate_gate, sort_keys=True, separators=(",", ":"))
            + " -->"
        )
        duplicated = run_contract(
            "filter-human-verification-gates",
            input_text=json.dumps(
                {"issues": [*issues, {"id": "ENG-998", "description": duplicate_marker}]}
            ),
        )
        self.assertEqual(duplicated.returncode, 2)
        self.assertIn("multiple gates", duplicated.stderr)

    def test_disabled_verification_preserves_legacy_wrap_path(self) -> None:
        action = {
            "operation": "verify",
            "effective_policy": human_effective_policy(),
            "milestone_stage": "implementing",
            "machine_verification_revision": 4,
            "gate": None,
            "checklist": None,
        }
        verified = run_contract("human-verification-action-check", input_text=json.dumps(action))
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertEqual(
            json.loads(verified.stdout),
            {"next_command": "wrap-milestone", "status": "milestone-verified"},
        )
        transition = run_contract("transition", "wrap-milestone", "--from", "milestone-verified")
        self.assertEqual(transition.returncode, 0, transition.stderr)
        self.assertEqual(transition.stdout.strip(), "wrapped")
        wrapped_marker = run_contract(
            "marker",
            "--project-id",
            "project-1",
            "--milestone-id",
            "milestone-1",
            "--stage",
            "wrapped",
            "--revision",
            "9",
            "--last-command",
            "wrap-milestone",
            "--run-id",
            "legacy-run",
            "--updated-at",
            "2026-07-24T10:00:00+00:00",
        )
        self.assertEqual(wrapped_marker.returncode, 0, wrapped_marker.stderr)
        parsed = run_contract("parse-marker", input_text=wrapped_marker.stdout)
        self.assertEqual(parsed.returncode, 0, parsed.stderr)
        self.assertEqual(json.loads(parsed.stdout)["stage"], "wrapped")

    def test_enabled_verify_stops_confirm_requires_native_completion(self) -> None:
        effective = human_effective_policy("enabled", "project-default", project_revision=1)
        gate = human_gate(effective)
        checklist = human_checklist(effective)
        verified = run_contract(
            "human-verification-action-check",
            input_text=json.dumps(
                {
                    "operation": "verify",
                    "effective_policy": effective,
                    "milestone_stage": "implementing",
                    "machine_verification_revision": 4,
                    "gate": gate,
                    "checklist": checklist,
                }
            ),
        )
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertEqual(json.loads(verified.stdout)["stop"], "await-human-verification")

        stale_checklist = human_checklist(effective, machine_revision=3)
        stale_verify = run_contract(
            "human-verification-action-check",
            input_text=json.dumps(
                {
                    "operation": "verify",
                    "effective_policy": effective,
                    "milestone_stage": "implementing",
                    "machine_verification_revision": 4,
                    "gate": gate,
                    "checklist": stale_checklist,
                }
            ),
        )
        self.assertEqual(stale_verify.returncode, 2)
        self.assertIn("HUMAN_VERIFICATION_CHECKLIST_STALE", stale_verify.stderr)

        confirmation = {
            "operation": "confirm",
            "effective_policy": effective,
            "milestone_stage": "milestone-verified",
            "checklist": checklist,
            "gate": gate,
            "human_confirmed": True,
            "gate_state_read_back": "Done",
            "checklist_status_read_back": "confirmed",
            "linear_milestone_completed": False,
        }
        incomplete = run_contract(
            "human-verification-action-check", input_text=json.dumps(confirmation)
        )
        self.assertEqual(incomplete.returncode, 2)
        self.assertIn("Linear completion", incomplete.stderr)
        confirmation["linear_milestone_completed"] = True
        confirmed = run_contract(
            "human-verification-action-check", input_text=json.dumps(confirmation)
        )
        self.assertEqual(confirmed.returncode, 0, confirmed.stderr)
        self.assertEqual(json.loads(confirmed.stdout)["status"], "human-verified")

    def test_failure_creates_one_bound_repair_and_requires_reverification(self) -> None:
        effective = human_effective_policy("enabled", "milestone-override", override_revision=2)
        reason = "The primary workflow regressed"
        repair = human_repair(reason)
        preview_hash = canonical_hash(
            {
                "operation": "fail",
                "project_id": "project-1",
                "milestone_id": "milestone-1",
                "checklist_id": "checklist-1",
                "gate_issue_id": "ENG-999",
                "reason": reason,
                "repair_task": repair,
            }
        )
        action = {
            "operation": "fail",
            "effective_policy": effective,
            "milestone_stage": "milestone-verified",
            "checklist": human_checklist(effective),
            "gate": human_gate(effective),
            "reason": reason,
            "repair_task": repair,
            "existing_repair_tasks": [],
            "preview_hash": preview_hash,
            "approved_hash": preview_hash,
            "checklist_status_read_back": "failed",
            "gate_state_read_back": "In Progress",
        }
        failed = run_contract("human-verification-action-check", input_text=json.dumps(action))
        self.assertEqual(failed.returncode, 0, failed.stderr)
        payload = json.loads(failed.stdout)
        self.assertEqual(payload["status"], "implementing")
        self.assertEqual(payload["next_command"], "verify-milestone")
        self.assertEqual(payload["repair_task"]["status"], "Unplanned")
        self.assertEqual(payload["repair_action"], "create")

        action["existing_repair_tasks"] = [human_repair(reason)]
        retried = run_contract("human-verification-action-check", input_text=json.dumps(action))
        self.assertEqual(retried.returncode, 0, retried.stderr)
        self.assertEqual(json.loads(retried.stdout)["repair_action"], "reuse")

        action["reason"] = ""
        no_reason = run_contract("human-verification-action-check", input_text=json.dumps(action))
        self.assertEqual(no_reason.returncode, 2)
        self.assertIn("reason must be non-empty", no_reason.stderr)

    def test_approved_bypass_cancels_without_false_confirmation(self) -> None:
        previous = human_effective_policy("enabled", "project-default", project_revision=1)
        current = human_effective_policy("disabled", "project-default", project_revision=2)
        reason = "Approved emergency release bypass"
        preview_hash = canonical_hash(
            {
                "operation": "bypass",
                "project_id": "project-1",
                "milestone_id": "milestone-1",
                "checklist_id": "checklist-1",
                "gate_issue_id": "ENG-999",
                "reason": reason,
                "from_policy_hash": previous["policy_hash"],
                "to_policy_hash": current["policy_hash"],
            }
        )
        action = {
            "operation": "bypass",
            "effective_policy": current,
            "previous_effective_policy": previous,
            "milestone_stage": "milestone-verified",
            "checklist": human_checklist(previous),
            "gate": human_gate(previous),
            "reason": reason,
            "preview_hash": preview_hash,
            "approved_hash": preview_hash,
            "gate_state_read_back": "Canceled",
            "checklist_status_read_back": "bypassed",
            "human_confirmation_recorded": False,
        }
        bypassed = run_contract("human-verification-action-check", input_text=json.dumps(action))
        self.assertEqual(bypassed.returncode, 0, bypassed.stderr)
        self.assertEqual(json.loads(bypassed.stdout)["next_command"], "wrap-milestone")
        action["human_confirmation_recorded"] = True
        false_confirmation = run_contract(
            "human-verification-action-check", input_text=json.dumps(action)
        )
        self.assertEqual(false_confirmation.returncode, 2)
        self.assertIn("false human confirmation", false_confirmation.stderr)

    def test_enabled_wrap_requires_human_verified_done_gate_and_confirmed_checklist(self) -> None:
        effective = human_effective_policy("enabled", "project-default", project_revision=1)
        pending = {
            "operation": "wrap",
            "effective_policy": effective,
            "milestone_stage": "milestone-verified",
            "gate": human_gate(effective),
            "checklist": human_checklist(effective),
        }
        rejected = run_contract("human-verification-action-check", input_text=json.dumps(pending))
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("requires human-verified", rejected.stderr)

        pending["milestone_stage"] = "human-verified"
        pending["gate"] = human_gate(effective, "Done")
        pending["checklist"] = human_checklist(effective, "confirmed")
        wrapped = run_contract("human-verification-action-check", input_text=json.dumps(pending))
        self.assertEqual(wrapped.returncode, 0, wrapped.stderr)
        self.assertEqual(json.loads(wrapped.stdout)["status"], "wrapped")

    def test_orchestration_waits_and_policy_drift_invalidates_receipts(self) -> None:
        project_event = {
            "project_drift": False,
            "cross_milestone_conflict": False,
            "approval_pending": False,
            "executing_task_ids": [],
            "verifying_task_ids": [],
            "verified_task_ids": [],
            "ready_task_ids": ["ENG-2"],
            "awaiting_human_verification_milestone_ids": ["milestone-1"],
            "milestones_ready_to_wrap": ["milestone-1"],
            "eligible_milestone_ids": ["milestone-2"],
            "project_complete": False,
        }
        waiting = run_contract("project-loop-next", input_text=json.dumps(project_event))
        self.assertEqual(waiting.returncode, 0, waiting.stderr)
        self.assertEqual(json.loads(waiting.stdout)["event"], "await-human-verification")

        milestone_event = {
            "project_coordination_required": False,
            "approval_pending": False,
            "executing_task_ids": [],
            "verifying_task_ids": [],
            "verified_task_ids": [],
            "ready_task_ids": ["ENG-2"],
            "awaiting_human_verification": True,
            "milestone_ready_to_wrap": True,
            "eligible_milestone_work": True,
            "milestone_complete": False,
        }
        milestone_waiting = run_contract(
            "milestone-loop-next", input_text=json.dumps(milestone_event)
        )
        self.assertEqual(milestone_waiting.returncode, 0, milestone_waiting.stderr)
        self.assertEqual(
            json.loads(milestone_waiting.stdout)["event"],
            "await-human-verification",
        )

        effective = human_effective_policy()
        binding = human_policy_binding()
        valid = run_contract(
            "orchestration-policy-binding-check",
            input_text=json.dumps(
                {
                    "binding": binding,
                    "effective_policy": effective,
                }
            ),
        )
        self.assertEqual(valid.returncode, 0, valid.stderr)
        changed = human_effective_policy("enabled", "project-default", project_revision=1)
        drift = run_contract(
            "orchestration-policy-binding-check",
            input_text=json.dumps(
                {
                    "binding": binding,
                    "effective_policy": changed,
                }
            ),
        )
        self.assertEqual(drift.returncode, 2)
        self.assertIn("HUMAN_VERIFICATION_POLICY_DRIFT", drift.stderr)

        receipt = milestone_loop_receipt_fixture()
        receipt["human_verification_policy"]["policy_hash"] = "sha256:" + "f" * 64
        receipt_drift = run_contract("milestone-loop-receipt-check", input_text=json.dumps(receipt))
        self.assertEqual(receipt_drift.returncode, 2)
        self.assertIn("HUMAN_VERIFICATION_POLICY_DRIFT", receipt_drift.stderr)
