from __future__ import annotations

import copy
import io
import json
import unittest
from pathlib import Path

from linear_spanks.cli.app import run
from linear_spanks.core.errors import GovernedStop, UsageError
from linear_spanks.core.hashing import sha256_digest
from linear_spanks.domains import context as c
from linear_spanks.domains import orchestration, runtime
from linear_spanks.domains._validation import checked

from tests.contract_support import (
    verification_ledger_fixture,
)

ANCESTRY = {"project": "P", "milestone": "M", "task": "T"}


def policy(scope: str, tokens: int | None, revision: int = 1) -> dict:
    return {
        "kind": "ContextBudgetPolicy",
        "schema_version": 1,
        "scope": scope,
        "target": ANCESTRY[scope],
        "project_id": "P",
        "revision": revision,
        "tokens": tokens,
    }


def inventory(*policies: dict, runtime_evidence: dict | None = None) -> dict:
    return {"ancestry": ANCESTRY, "policies": list(policies), "runtime": runtime_evidence or {}}


def source(index: int = 1) -> dict:
    facts = {field: [] for field in sorted(c.FACT_FIELDS)}
    facts.update(
        {
            "acceptance": {"AC1": "failing"},
            "findings": {"F1": "open"},
            "approvals": ["integration-preview-required"],
            "next_action": "repair",
            "plan_binding": {"revision": 1, "hash": "plan-1"},
            "commits": ["candidate-1"],
        }
    )
    result = {
        "id": f"source/{index}",
        "revision": index,
        "facts": facts,
        "narrative": "old history " * 2000,
    }
    result["hash"] = sha256_digest({"facts": facts, "narrative": result["narrative"]})
    return result


def preview_request(item: dict, store: c.PreparedDocuments, scope: str = "task") -> dict:
    key = c.scope_key(scope, ANCESTRY[scope], "P")
    active = store.read(key + "/active")
    return {
        "scope": scope,
        "target": ANCESTRY[scope],
        "project_id": "P",
        "revision": 1 if active is None else active["revision"] + 1,
        "sources": [item],
        "narrative": "Current unresolved work.",
        "default_tokens": 12000,
        "previous_active": active,
        "history_manifest": active["manifest"] if active else None,
    }


def activate(store: c.PreparedDocuments, request: dict) -> dict:
    preview = c.checkpoint_preview(request)
    return c.activate_checkpoint(
        store, {"preview": preview, "approved_hash": preview["preview_hash"]}
    )


class FailingDocuments(c.PreparedDocuments):
    def __init__(self, documents: dict, failure: str) -> None:
        super().__init__(documents)
        self.failure = failure

    def put(self, key: str, value: dict, expected_hash: str) -> None:
        if self.failure in key:
            raise OSError("provider unavailable")
        super().put(key, value, expected_hash)


class ContextReliabilityTest(unittest.TestCase):
    def test_error_codes_keep_evidence_and_recovery(self) -> None:
        for code in (
            "CONTEXT_OVERFLOW",
            "REPOSITORY_DRIFT",
            "APPROVAL_REQUIRED",
            "ROLE_CAPABILITY_VIOLATION",
            "REPLAN_REQUIRED",
        ):

            def fail(failure_code: str = code) -> None:
                raise ValueError(failure_code + ": affected-source")

            with self.assertRaises(GovernedStop) as caught:
                checked(fail)
            self.assertEqual(caught.exception.code, code)
            self.assertIn("affected-source", caught.exception.details["evidence"])
            self.assertTrue(caught.exception.details["next_action"])
        with self.assertRaises(UsageError):
            checked(lambda: int("bad"))

    def test_policy_inheritance_reset_validation_and_runtime(self) -> None:
        for policies, expected, inherited in [
            ([], 10000, "built-in"),
            ([policy("project", 24000)], 24000, "project"),
            ([policy("project", 24000), policy("milestone", 32000)], 32000, "milestone"),
            (
                [policy("project", 24000), policy("milestone", 32000), policy("task", 40000)],
                40000,
                "task",
            ),
            ([policy("project", 24000), policy("task", None)], 24000, "project"),
        ]:
            with c.budget_session(inventory(*policies)) as effective:
                self.assertEqual(c.effective_limit(10000), expected)
                self.assertEqual(effective.source, inherited)
                self.assertEqual(c.effective_limit(50000), 50000)
                self.assertEqual(
                    c.effective_limits(
                        {
                            "max_input_tokens": 10000,
                            "max_capsule_bytes": 100,
                            "max_batches": 2,
                            "max_cumulative_input_tokens": 100000,
                        }
                    ),
                    {
                        "max_input_tokens": expected,
                        "max_capsule_bytes": 100,
                        "max_batches": 2,
                        "max_cumulative_input_tokens": 100000,
                    },
                )
        self.assertEqual(c.effective_limit(10000), 10000)
        for value in (0, -1, True, "24000", 2.5):
            with self.assertRaises(UsageError):
                c.validate_policy(policy("task", value))
        for broken in (
            inventory(policy("task", 24000), policy("task", 25000)),
            inventory({**policy("task", 24000), "project_id": "OTHER"}),
        ):
            with self.assertRaises(GovernedStop):
                c.resolve_budget(broken)
        runtime_evidence = {
            "model": "model-a",
            "harness": "test",
            "input_capacity": 20000,
            "reserved_tokens": 4000,
            "source": "runtime",
        }
        with c.budget_session(inventory(policy("task", 50000), runtime_evidence=runtime_evidence)):
            c.check_capacity(16000)
            with self.assertRaises(GovernedStop) as caught:
                c.check_capacity(16001)
            self.assertEqual(caught.exception.code, "RUNTIME_CONTEXT_OVERFLOW")
        with self.assertRaises(UsageError):
            c.resolve_budget(inventory(runtime_evidence={"model": "missing-evidence"}))

    def test_compaction_thresholds_are_capped_absolutely_not_only_proportionally(self) -> None:
        """A raised ceiling must not scale durable snapshots, or compaction stops working."""
        self.assertEqual(c.compaction_suggest_threshold(12000), 8400)
        self.assertEqual(c.compaction_target(12000), 6000)
        # Above the crossover the absolute cap binds instead of the percentage.
        self.assertEqual(c.compaction_suggest_threshold(120000), c.COMPACTION_SUGGEST_MAX_TOKENS)
        self.assertEqual(c.compaction_target(120000), c.COMPACTION_TARGET_MAX_TOKENS)
        self.assertLess(c.compaction_target(1000000), c.compaction_suggest_threshold(1000000))
        contract_path = (
            Path(__file__).parents[1] / "skills/linear-spanks/context-management-contract.json"
        )
        contract = json.loads(contract_path.read_text())["compaction"]
        self.assertEqual(contract["suggest_percent"], c.COMPACTION_SUGGEST_PERCENT)
        self.assertEqual(contract["target_percent"], c.COMPACTION_TARGET_PERCENT)
        self.assertEqual(contract["suggest_max_tokens"], c.COMPACTION_SUGGEST_MAX_TOKENS)
        self.assertEqual(contract["target_max_tokens"], c.COMPACTION_TARGET_MAX_TOKENS)
        self.assertEqual(contract["history_tokens"], c.COMPACTION_HISTORY_TOKENS)
        events_key = "events_since_checkpoint"
        self.assertEqual(contract[events_key], c.COMPACTION_EVENTS_SINCE_CHECKPOINT)

    def test_inspect_reports_absolute_compaction_target_under_a_large_budget(self) -> None:
        request = {
            "body": {"note": "x" * 100000},
            "default_tokens": 120000,
            "scope": "task",
            "target": "T",
        }
        with c.budget_session(inventory(policy("task", 400000))):
            report = c.inspect_context(request)
        self.assertEqual(report["effective_tokens"], 400000)
        self.assertEqual(report["compaction"]["target_tokens"], c.COMPACTION_TARGET_MAX_TOKENS)
        self.assertEqual(report["compaction"]["suggest_at_tokens"], c.COMPACTION_SUGGEST_MAX_TOKENS)
        # 25k of body is far below 70% of 400k but above the absolute suggestion cap.
        self.assertTrue(report["compaction"]["suggested"])

    def test_authorized_budget_persistence_noop_reset_and_concurrency(self) -> None:
        store = c.PreparedDocuments({})

        def request(tokens: int | None, reset: bool = False) -> dict:
            policies = [
                v for v in store.documents.values() if v.get("kind") == "ContextBudgetPolicy"
            ]
            return {
                "scope": "task",
                "target": "T",
                "ancestry": ANCESTRY,
                "tokens": tokens,
                "reset": reset,
                "default_tokens": 12000,
                "expected_policy_hash": c.resolve_budget(inventory(*policies)).binding,
                "authorization": {"scope": "task", "target": "T", "tokens": tokens, "reset": reset},
            }

        original = request(24000)
        result = c.budget_update(store, original)
        self.assertEqual(result["status"], "persisted")
        self.assertEqual(len(store.writes), 2)
        self.assertEqual(
            c.resolve_budget(inventory(store.read("context/P/task/T/budget"))).tokens, 24000
        )
        self.assertEqual(c.budget_update(store, request(24000))["status"], "unchanged")
        with self.assertRaises(GovernedStop):
            c.budget_update(store, original)
        with self.assertRaises(GovernedStop) as caught:
            c.budget_update(store, request(20000))
        self.assertEqual(caught.exception.code, "CONTEXT_BUDGET_DECREASE")
        with self.assertRaises(GovernedStop):
            c.budget_update(store, {**request(32000), "authorization": {}})
        self.assertEqual(c.budget_update(store, request(None, True))["policy"]["tokens"], None)
        self.assertEqual(c.budget_update(store, request(None, True))["status"], "unchanged")
        self.assertEqual(
            c.budget_update(
                c.PreparedDocuments({}),
                {
                    **original,
                    "reset": True,
                    "tokens": None,
                    "authorization": {
                        "scope": "task",
                        "target": "T",
                        "tokens": None,
                        "reset": True,
                    },
                },
            )["status"],
            "unchanged",
        )
        with self.assertRaises(UsageError):
            c.budget_update(store, {**request(32000), "reset": True})
        with self.assertRaises(UsageError):
            c.budget_update(store, {**request(32000), "target": "wrong"})

    def test_full_packet_and_reproduced_oversized_ledger(self) -> None:
        request = {
            "body": {
                "instructions": "x" * 52000,
                "skills": [],
                "plan": {},
                "evidence": [],
                "bindings": {},
            },
            "default_tokens": 12000,
        }
        with self.assertRaises(GovernedStop):
            c.compile_packet({**request, "declared_tokens": 1})
        with c.budget_session(inventory(policy("task", 24000))):
            packet = c.compile_packet(request)
            self.assertGreater(packet["measurement"]["estimated_tokens"], 12000)
            c.validate_packet({"packet": packet, "default_tokens": 12000})
            with self.assertRaises(GovernedStop):
                c.compile_packet({**request, "declared_tokens": 1})
            changed = copy.deepcopy(packet)
            changed["body"]["instructions"] += "changed"
            with self.assertRaises(GovernedStop):
                c.validate_packet({"packet": changed, "default_tokens": 12000})
        with self.assertRaises(GovernedStop) as caught:
            c.validate_packet({"packet": packet, "default_tokens": 12000})
        self.assertEqual(caught.exception.code, "CONTEXT_POLICY_DRIFT")
        ledger = verification_ledger_fixture()
        # size the payload past the verifier ceiling rather than pinning a stale literal
        execution = Path(__file__).parents[1] / "skills" / "linear-spanks"
        verifier_limit = json.loads(
            (execution / "execution-contract.json").read_text(encoding="utf-8")
        )["context_profiles"]["task"]["max_input_tokens"]
        ledger["baseline_failures"] = ["h" * (verifier_limit * 4 + 4096)]
        ledger["live_session"]["context_tokens"] = 1
        with self.assertRaises(GovernedStop) as caught:
            orchestration.validate_ledger(ledger)
        self.assertEqual(caught.exception.code, "CONTEXT_OVERFLOW")
        with self.assertRaises(UsageError):
            c.compile_packet({"body": {}, "default_tokens": 12000})
        self.assertEqual(c.measurement("💡")["bytes"], 6)

    def test_checkpoint_approval_sources_conflicts_and_interrupted_writes(self) -> None:
        for scope in c.SCOPES:
            item = source()
            store = c.PreparedDocuments({item["id"]: item})
            request = preview_request(item, store, scope)
            preview = c.checkpoint_preview(request)
            self.assertEqual(preview["snapshot"]["facts"], c.retained_facts([item]))
            self.assertGreater(preview["reduction_bytes"], 0)
            with self.assertRaises(GovernedStop):
                c.activate_checkpoint(store, {"preview": preview, "approved_hash": "declined"})
            self.assertIsNone(store.read(preview["active_key"]))
            failing = FailingDocuments(store.documents, "/snapshots/")
            with self.assertRaises(OSError):
                c.activate_checkpoint(
                    failing, {"preview": preview, "approved_hash": preview["preview_hash"]}
                )
            self.assertIsNone(failing.read(preview["active_key"]))
            failing.failure = "NEVER"
            c.activate_checkpoint(
                failing, {"preview": preview, "approved_hash": preview["preview_hash"]}
            )
            writes = len(failing.writes)
            c.activate_checkpoint(
                failing, {"preview": preview, "approved_hash": preview["preview_hash"]}
            )
            self.assertEqual(len(failing.writes), writes)
            stale = copy.deepcopy(store.documents)
            stale[item["id"]]["revision"] += 1
            with self.assertRaises(GovernedStop):
                c.activate_checkpoint(
                    c.PreparedDocuments(stale),
                    {"preview": preview, "approved_hash": preview["preview_hash"]},
                )
        other = source(2)
        other["facts"]["acceptance"] = {"AC1": "passing"}
        other["hash"] = sha256_digest({"facts": other["facts"], "narrative": other["narrative"]})
        self.assertEqual(len(c.retained_facts([source(), other])["acceptance"]), 2)
        with self.assertRaises(UsageError):
            c.retained_facts([source(), source()])
        with self.assertRaises(GovernedStop):
            c.retained_facts([{**source(), "hash": "wrong"}])
        with self.assertRaises(GovernedStop):
            c.checkpoint_preview({**request, "default_tokens": 100})

    def test_hundred_repair_handoffs_have_bounded_active_work_and_retrievable_history(self) -> None:
        item = source()
        store = c.PreparedDocuments({item["id"]: item})
        activate(store, preview_request(item, store))
        budgets = json.loads(
            (Path(__file__).parent / "fixtures/context/replay-budgets.json").read_text()
        )
        maxima = {
            "context_bytes": 0,
            "historical_artifacts_expanded": 0,
            "duplicate_writes": 0,
            "repeated_analysis": 0,
        }
        bindings = dict.fromkeys(sorted(c.REUSE_BINDINGS), "current")
        for index in range(2, budgets["cycles"] + 2):
            item = source(index)
            store.documents[item["id"]] = item
            active = store.read("context/P/task/T/active")
            changes = {"acceptance": c.retained_facts([item])["acceptance"]}
            delta = {
                "kind": "ContextDelta",
                "schema_version": 1,
                "scope": "task",
                "target": "T",
                "project_id": "P",
                "revision": active["revision"] + 1,
                "changes": changes,
                "evidence": [item["id"]],
                "previous_hash": active["hash"],
                "policy_hash": active["policy_hash"],
            }
            operation = {"delta": delta, "default_tokens": 12000}
            c.persist_delta(store, operation)
            count = len(store.writes)
            c.persist_delta(store, operation)
            maxima["duplicate_writes"] += len(store.writes) - count
            current = c.assemble_context(
                store, {"scope": "task", "target": "T", "project_id": "P", "default_tokens": 12000}
            )
            self.assertEqual(current["body"]["facts"]["acceptance"], changes["acceptance"])
            self.assertEqual(current["body"]["facts"]["findings"][0]["value"], {"F1": "open"})
            self.assertEqual(
                current["body"]["facts"]["approvals"][0]["value"], ["integration-preview-required"]
            )
            packet = c.compile_packet(
                {
                    "body": {
                        "instructions": "verify",
                        "skills": [],
                        "plan": {"revision": 1},
                        "evidence": current["body"],
                        "bindings": {},
                    },
                    "default_tokens": 12000,
                }
            )
            c.validate_packet({"packet": packet, "default_tokens": 12000})
            maxima["context_bytes"] = max(maxima["context_bytes"], packet["measurement"]["bytes"])
            maxima["historical_artifacts_expanded"] = max(
                maxima["historical_artifacts_expanded"], current["historical_artifacts_expanded"]
            )
            maxima["repeated_analysis"] += not c.reuse_analysis(
                {"previous": bindings, "current": bindings}
            )["reusable"]
            if current["events_since_checkpoint"] >= 3:
                activate(store, preview_request(item, store))
        self.replay_metrics = {"cycles": budgets["cycles"], **maxima}
        self.assertLessEqual(maxima["context_bytes"], budgets["max_context_bytes"])
        self.assertLessEqual(
            maxima["historical_artifacts_expanded"], budgets["max_historical_artifacts_expanded"]
        )
        self.assertEqual(maxima["duplicate_writes"], budgets["max_duplicate_writes"])
        self.assertEqual(maxima["repeated_analysis"], budgets["max_repeated_analysis"])
        self.assertTrue(all(f"source/{i}" in store.documents for i in range(1, 102)))
        manifests = [v for v in store.documents.values() if v.get("kind") == "ContextManifest"]
        self.assertTrue(all(len(m["entries"]) <= 50 for m in manifests))
        expanded = c.expand_context(
            store,
            {
                "source": "source/1",
                "section": "facts",
                "reason": "audit original acceptance",
                "max_bytes": 4000,
            },
        )
        self.assertEqual(expanded["content"]["acceptance"], {"AC1": "failing"})
        with self.assertRaises(GovernedStop):
            c.expand_context(
                store,
                {"source": "source/1", "section": "narrative", "reason": "audit", "max_bytes": 10},
            )

    def test_repair_reuse_inspection_skills_and_compressor(self) -> None:
        attempt = {"result": "failed", "fingerprint": "same", "acceptance": {"AC1": "failing"}}
        self.assertEqual(c.repair_action({"attempts": []})["next_action"], "implement")
        self.assertEqual(
            c.repair_action({"attempts": [attempt]})["next_action"], "automatic-repair"
        )
        self.assertEqual(
            c.repair_action({"attempts": [attempt, attempt]})["next_action"], "diagnose"
        )
        self.assertEqual(
            c.repair_action(
                {"attempts": [{**attempt, "result": "passed", "acceptance": {"AC1": "passing"}}]}
            )["next_action"],
            "verified-pending-integration",
        )
        self.assertEqual(
            c.repair_action({"attempts": [{**attempt, "failure_class": "environment"}]})[
                "next_action"
            ],
            "prerequisite-recovery",
        )
        self.assertEqual(
            c.repair_action({"attempts": [{**attempt, "fingerprint": str(i)} for i in range(4)]})[
                "next_action"
            ],
            "user-model-selection",
        )
        inspection = {
            "scope": "task",
            "target": "T",
            "default_tokens": 12000,
            "body": {},
            "events_since_checkpoint": 3,
            "sources": {"s": "hash"},
        }
        view = c.inspect_context(inspection)
        self.assertTrue(view["compaction"]["suggested"])
        self.assertEqual(view["runtime_capacity"], "unknown")
        self.assertFalse(
            c.inspect_context(
                {**inspection, "declined_hash": view["compaction"]["suggestion_hash"]}
            )["compaction"]["suggested"]
        )
        self.assertEqual(
            runtime.inspect(
                {
                    "scope": "task",
                    "target": "T",
                    "event_input": {"attempts": [attempt, attempt]},
                    "next_command": "task replan T",
                    "context": inspection,
                }
            )["next_event"]["next_action"],
            "diagnose",
        )
        content = "Full skill guidance"
        skill = {
            "name": "test",
            "roles": ["executor"],
            "phases": ["repair"],
            "technologies": ["python"],
            "requires": ["observed-failure"],
            "precedence": 2,
            "source_hash": sha256_digest(content),
        }
        selection = {
            "role": "executor",
            "phase": "repair",
            "technologies": ["python"],
            "evidence": ["observed-failure"],
            "catalog": [skill],
            "session_id": "S1",
            "contents": {"test": content},
        }
        loaded = c.load_skills(selection)
        self.assertEqual(len(loaded["contents"]), 1)
        self.assertFalse(c.load_skills({**selection, "loaded": loaded["loaded"]})["contents"])
        self.assertTrue(
            c.load_skills({**selection, "session_id": "S2", "loaded": loaded["loaded"]})["contents"]
        )
        self.assertFalse(c.select_skills({**selection, "technologies": []})["selected"])
        with self.assertRaises(GovernedStop):
            c.load_skills({**selection, "contents": {"test": "changed"}})
        with self.assertRaises(GovernedStop):
            c.load_skills({**selection, "catalog": [skill, {**skill, "source_hash": "different"}]})
        self.assertEqual(c.compressor_slot({"scope": "task"})["slot"], "fast")
        self.assertEqual(c.compressor_slot({"scope": "project"})["slot"], "strong")
        self.assertEqual(
            c.compressor_slot({"scope": "task", "validation_failures": 1})["slot"], "strong"
        )
        with self.assertRaises(GovernedStop):
            c.compressor_slot({"scope": "task", "validation_failures": 2})
        with self.assertRaises(GovernedStop):
            c.compressor_slot({"scope": "task", "capabilities": {"fast": {"external": True}}})
        self.assertTrue(
            c.compressor_slot(
                {"scope": "task", "capabilities": {"fast": {"name": "local", "external": False}}}
            )["independent_compressor"]
        )

    def test_public_commands_and_internal_operations(self) -> None:
        from linear_spanks.domains.commands import contracts
        from linear_spanks.domains.documentation import render_command_catalog

        catalog_text = render_command_catalog()
        for command in contracts().commands:
            self.assertIn(command.usage, catalog_text)
        for arguments in (
            ("context", "budget", "task", "ENG-123", "--tokens", "24000"),
            (
                "context",
                "budget",
                "milestone",
                "Phase 3",
                "--project",
                "My Project",
                "--tokens",
                "32000",
            ),
            ("context", "budget", "task", "ENG-123", "--reset"),
            ("milestone", "checkpoint", "M"),
            ("task", "checkpoint", "T"),
            ("context", "inspect", "task", "T"),
            ("runtime", "inspect", "project", "P"),
        ):
            output = io.StringIO()
            code = run(arguments, stdin=io.StringIO(), stdout=output)
            self.assertEqual(code, 0, output.getvalue())
        for tokens in ("0", "-1", "1.5", "true"):
            self.assertEqual(
                run(
                    ("context", "budget", "task", "T", "--tokens", tokens),
                    stdin=io.StringIO(),
                    stdout=io.StringIO(),
                ),
                2,
            )
        output = io.StringIO()
        self.assertEqual(
            run(
                ("context", "resolve-budget"),
                stdin=io.StringIO(json.dumps(inventory(policy("task", 24000)))),
                stdout=output,
            ),
            0,
        )
        self.assertEqual(json.loads(output.getvalue())["result"]["tokens"], 24000)
        catalog = json.loads(
            (
                Path(__file__).parents[1] / "skills/linear-spanks/skill-selection-catalog.json"
            ).read_text()
        )
        for skill in catalog["catalog"]:
            content = (
                Path(__file__).parents[1] / "skills" / "extras" / skill["name"] / "SKILL.md"
            ).read_text()
            self.assertEqual(skill["source_hash"], sha256_digest(content))

    def test_persisted_parent_policies_restore_in_fresh_scope_sessions(self) -> None:
        store = c.PreparedDocuments({})
        for scope, tokens in (("project", 24000), ("milestone", 32000), ("task", 40000)):
            ancestry = {k: ANCESTRY[k] for k in c.SCOPES[: c.SCOPES.index(scope) + 1]}
            policies = [
                store.read(c.scope_key(k, target, "P") + "/budget")
                for k, target in ancestry.items()
            ]
            binding = {"ancestry": ancestry, "policies": [p for p in policies if p is not None]}
            request = {
                "scope": scope,
                "target": ANCESTRY[scope],
                "ancestry": ancestry,
                "tokens": tokens,
                "reset": False,
                "default_tokens": 12000,
                "expected_policy_hash": c.resolve_budget(binding).binding,
                "authorization": {
                    "scope": scope,
                    "target": ANCESTRY[scope],
                    "tokens": tokens,
                    "reset": False,
                },
            }
            c.budget_update(store, request)
            restored = inventory(
                *[v for v in store.documents.values() if v.get("kind") == "ContextBudgetPolicy"]
            )
            with c.budget_session(restored):
                packet = c.compile_packet(
                    {
                        "body": {
                            "instructions": "x" * 52000,
                            "skills": [],
                            "plan": {},
                            "evidence": [],
                            "bindings": {},
                        },
                        "default_tokens": 12000,
                    }
                )
                c.validate_packet({"packet": packet, "default_tokens": 12000})
                self.assertEqual(c.effective_limit(12000), tokens)
        with self.assertRaises(GovernedStop):
            c.validate_packet({"packet": packet, "default_tokens": 12000})
        with c.budget_session(inventory(policy("task", 100000))):
            item = source()
            snapshot = c.checkpoint_preview(preview_request(item, c.PreparedDocuments({})))[
                "snapshot"
            ]
            with self.assertRaises(GovernedStop) as caught:
                c.validate_context_artifact({**snapshot, "narrative": "x" * 25000})
            self.assertIn("max_capsule_bytes", caught.exception.details["evidence"])

    def test_dispatch_binding_and_attempt_progress(self) -> None:
        from tests.contract_support import role_handoff_fixture, task_attempt_fixture

        handoff = role_handoff_fixture("task-executor")
        body = {
            "instructions": "execute the approved plan",
            "skills": ["full skill"],
            "plan": {"revision": 2},
            "evidence": [],
            "bindings": {
                "handoff_hash": sha256_digest(
                    {k: v for k, v in handoff.items() if k != "context_tokens"}
                )
            },
        }
        packet = c.compile_packet({"body": body, "default_tokens": 12000})
        handoff["context_tokens"] = packet["measurement"]["estimated_tokens"]
        c.validate_dispatch({"handoff": handoff, "packet": packet})
        with self.assertRaises(GovernedStop):
            c.validate_dispatch({"handoff": {**handoff, "context_tokens": 1}, "packet": packet})
        with self.assertRaises(GovernedStop):
            c.validate_dispatch({"handoff": {**handoff, "handoff_id": "other"}, "packet": packet})
        previous = {"result": "failed", "fingerprint": "stable", "acceptance": {"AC1": "failing"}}
        attempt = {**task_attempt_fixture(1), "progress": {"attempts": [previous, previous]}}
        self.assertEqual(orchestration.validate_attempt(attempt)["next_action"], "diagnose")
        with self.assertRaises(UsageError):
            orchestration.validate_attempt({**attempt, "progress": {"attempts": [previous]}})
        with self.assertRaises(UsageError):
            c.repair_action({"attempts": [{"result": "pending"}]})

    def test_shared_validator_limits_and_capacity(self) -> None:
        from linear_spanks.contracts.compiler import compile_public_command
        from linear_spanks.domains import _reviews_v1, _routing_v1
        from linear_spanks.domains.execution import execution_envelope

        with c.budget_session(inventory(policy("task", 200000))):
            for scope in ("command", "planner", "repository"):
                _routing_v1.validate_context_usage("plan-task", 150000, [], scope, "medium")
            compiled = compile_public_command("task plan", ("T",)).contract
            self.assertEqual(compiled["context"]["max_input_tokens"], 200000)
            envelope = execution_envelope("plan-task", "medium")
            self.assertEqual(
                envelope["orchestration"]["planner"]["context"]["max_input_tokens"], 200000
            )
            budget = {
                "model_turns": 1,
                "active_context_tokens": 50000,
                "planned_batches": 1,
                "telemetry_available": False,
                "cumulative_input_tokens": None,
                "phase_cumulative_input_tokens": None,
            }
            _reviews_v1._validate_review_budget(budget)
            with self.assertRaises(ValueError):
                _reviews_v1._validate_review_budget({**budget, "model_turns": 10000})
            with self.assertRaises(ValueError):
                _routing_v1.validate_context_usage(
                    "plan-task", 1, ["max_full_issues=100000"], "command", "medium"
                )
        with self.assertRaises(ValueError):
            _routing_v1.validate_context_usage("plan-task", 150000, [], "command", "medium")

    def test_document_failures_tampering_and_read_only_plans(self) -> None:
        from linear_spanks.domains.artifacts import artifact_codecs

        item = source()
        store = c.PreparedDocuments({item["id"]: item})
        request = preview_request(item, store)
        preview = c.checkpoint_preview(request)
        artifact_payloads = [
            preview["snapshot"],
            preview["writes"][0]["value"],
            {**preview["receipt"], "preview_hash": preview["preview_hash"]},
            policy("task", 24000),
        ]
        for artifact in artifact_payloads:
            codec = artifact_codecs()[artifact["kind"]]
            decoded = codec.decode(artifact)
            self.assertEqual(codec.decode(codec.encode_v2(decoded)).kind, artifact["kind"])
        for field, value in (("kind", "unknown"), ("schema_version", True), ("revision", -1)):
            with self.assertRaises(UsageError):
                c.validate_context_artifact({**preview["snapshot"], field: value})
        corrupted = copy.deepcopy(preview)
        corrupted["snapshot"]["facts"]["acceptance"] = []
        corrupted["preview_hash"] = sha256_digest(
            {k: v for k, v in corrupted.items() if k != "preview_hash"}
        )
        with self.assertRaises(GovernedStop) as caught:
            c.activate_checkpoint(
                store, {"preview": corrupted, "approved_hash": corrupted["preview_hash"]}
            )
        self.assertEqual(caught.exception.code, "CONTEXT_FACT_DRIFT")
        with c.budget_session(inventory(policy("task", 24000))), self.assertRaises(GovernedStop):
            c.activate_checkpoint(
                store, {"preview": preview, "approved_hash": preview["preview_hash"]}
            )

        class BadReadBack(c.PreparedDocuments):
            def put(self, key: str, value: dict, expected_hash: str) -> None:
                super().put(key, value, expected_hash)
                self.documents[key] = {"wrong": "response"}

        with self.assertRaises(GovernedStop) as caught:
            c.write_read_back(BadReadBack({}), "snapshot", {"id": 1}, None)
        self.assertEqual(caught.exception.code, "CONTEXT_READ_BACK_FAILED")
        with self.assertRaises(GovernedStop):
            c.write_read_back(
                c.PreparedDocuments({"snapshot": {"revision": 2}}),
                "snapshot",
                {"revision": 3},
                None,
            )
        prepared = c.prepare_document_operation(
            "activate-prepare",
            {
                "documents": store.documents,
                "request": {"preview": preview, "approved_hash": preview["preview_hash"]},
            },
        )
        self.assertFalse(prepared["persistence_verified"])
        self.assertTrue(prepared["writes"])
        self.assertIsNone(store.read("context/P/task/T/active"))
        c.activate_checkpoint(store, {"preview": preview, "approved_hash": preview["preview_hash"]})
        active = store.read("context/P/task/T/active")
        fake = {
            "kind": "ContextDelta",
            "schema_version": 1,
            "scope": "task",
            "target": "T",
            "project_id": "P",
            "revision": active["revision"] + 1,
            "changes": {
                "acceptance": [
                    {
                        "source": item["id"],
                        "revision": item["revision"],
                        "value": {"AC1": "passing"},
                    }
                ]
            },
            "evidence": [item["id"]],
            "previous_hash": active["hash"],
            "policy_hash": active["policy_hash"],
        }
        with self.assertRaises(GovernedStop):
            c.persist_delta(store, {"delta": fake, "default_tokens": 12000})
        with self.assertRaises(GovernedStop):
            c.assemble_context(
                c.PreparedDocuments({}),
                {"scope": "task", "target": "T", "project_id": "P", "default_tokens": 12000},
            )
        with self.assertRaises(UsageError):
            c.expand_context(store, {"reason": ""})
        with self.assertRaises(GovernedStop):
            c.expand_context(
                store, {"source": "absent", "section": "facts", "reason": "audit", "max_bytes": 100}
            )

    def test_runtime_selector_projection_and_policy_concurrent_creation(self) -> None:
        event = {
            "project_drift": False,
            "cross_milestone_conflict": False,
            "approval_pending": True,
            "executing_task_ids": [],
            "verifying_task_ids": [],
            "verified_task_ids": [],
            "ready_task_ids": [],
            "milestones_ready_to_wrap": [],
            "eligible_milestone_ids": [],
            "project_complete": False,
        }
        inspection = {"default_tokens": 12000, "body": {}}
        viewed = runtime.inspect(
            {"scope": "project", "target": "P", "event_input": event, "context": inspection}
        )
        self.assertEqual(viewed["next_event"], orchestration.project_next(event))
        self.assertIsNone(viewed["next_command"])
        milestone = {
            "project_coordination_required": False,
            "approval_pending": False,
            "executing_task_ids": [],
            "verifying_task_ids": [],
            "verified_task_ids": [],
            "ready_task_ids": ["T"],
            "milestone_ready_to_wrap": False,
            "eligible_milestone_work": True,
            "milestone_complete": False,
        }
        self.assertEqual(
            runtime.inspect(
                {
                    "scope": "milestone",
                    "target": "M",
                    "event_input": milestone,
                    "context": inspection,
                }
            )["next_event"],
            orchestration.milestone_next(milestone),
        )

        class RacingStore(c.PreparedDocuments):
            def put(self, key: str, value: dict, expected_hash: str) -> None:
                super().put(key, value, expected_hash)
                self.documents["context/P/project/P/budget"] = policy("project", 40000)

        request = {
            "scope": "task",
            "target": "T",
            "ancestry": ANCESTRY,
            "tokens": 24000,
            "reset": False,
            "default_tokens": 12000,
            "expected_policy_hash": c.resolve_budget(inventory()).binding,
            "authorization": {"scope": "task", "target": "T", "tokens": 24000, "reset": False},
        }
        with self.assertRaises(GovernedStop) as caught:
            c.budget_update(RacingStore({}), request)
        self.assertEqual(caught.exception.code, "CONTEXT_POLICY_DRIFT")


if __name__ == "__main__":
    unittest.main()
