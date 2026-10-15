from __future__ import annotations

import copy
import io
import json
import unittest

from linear_spanks.cli.app import run
from linear_spanks.core.errors import GovernedStop, UsageError
from linear_spanks.core.hashing import sha256_digest
from linear_spanks.domains import milestone_checkpoint as m

from tests.test_task_checkpoint import comment


def task_record(tid: str, completed: bool = True) -> dict:
    issue = {
        "id": tid,
        "projectId": "P",
        "projectMilestone": {"id": "M"},
        "description": "Stable task intent",
        "statusType": "completed" if completed else "started",
        "completedAt": "2026-09-07T12:00:00Z" if completed else None,
        "relations": {"blocks": [], "blockedBy": [], "relatedTo": []},
    }
    receipt = {"candidate_commit": "a" * 40, "verification_status": "passed"}
    rows = [comment(tid + "1"), comment(tid + "2", "```json\n" + json.dumps(receipt) + "\n```")]
    return {
        "issue": issue,
        "comments": rows,
        "has_next_page": False,
        "archive": None,
        "groups": [
            {
                "type": "review",
                "source_ids": [c["id"] for c in rows],
                "canonical_id": rows[1]["id"],
                "body": "Review passed. Static evidence retained in archive.",
            }
        ],
        "keep_ids": [],
    }


def request(prune: bool = False) -> dict:
    record = task_record("T")
    result = {
        "invocation": {"command": "milestone checkpoint", "target": "M", "options": {}},
        "project_id": "P",
        "milestone": {"id": "M", "name": "Milestone", "description": "Original criteria."},
        "tasks": [record],
        "tasks_has_next_page": False,
        "archive": None,
        "archive_max_bytes": 1000000,
        "summary": "Audit completed; integrated UX checks remain open.",
        "prune_ids": [],
        "consumers": [],
    }
    if prune:
        result["invocation"]["options"]["level"] = "prune"
        result["prune_ids"] = ["T"]
        evidence = record["comments"][1]
        result["outcomes"] = {
            "T": {
                "verification_status": "passed",
                "candidate_commit": "a" * 40,
                "summary": "Static audit accepted; no runtime claim.",
                "evidence": [{"id": evidence["id"], "hash": sha256_digest(evidence)}],
            }
        }
    return result


def state(r: dict, p: dict) -> dict:
    return {
        "preview": p,
        "approved_hash": p["preview_hash"],
        "invocation": copy.deepcopy(r["invocation"]),
        "tasks": copy.deepcopy(r["tasks"]),
        "tasks_has_next_page": False,
        "milestone": copy.deepcopy(r["milestone"]),
        "archive": r["archive"],
        "consumers": copy.deepcopy(r["consumers"]),
        "delete_issue_capability": {
            "available": True,
            "provider": "test",
            "operation": "delete_issue",
        },
    }


def apply(s: dict, op: dict) -> None:
    action = op["action"]
    if action == "save-archive":
        s["archive"] = copy.deepcopy(op["value"])
        s["archive_url"] = "https://linear.app/example/document/verified-archive"
    elif action == "save-milestone-summary":
        s["milestone"]["description"] = op["description"]
    elif action in {"save-comment", "delete-comment"}:
        for r in s["tasks"]:
            for c in r["comments"][:]:
                if c["id"] == op["id"]:
                    if action == "save-comment":
                        c["body"] = op["body"]
                    else:
                        r["comments"].remove(c)
    elif action == "save-dependency-comment":
        for r in s["consumers"]:
            if m.identity(r["issue"]) == op["issue_id"]:
                r["comments"].append(comment("generated-handoff", op["body"]))
                for native in s["tasks"]:
                    if m.identity(native["issue"]) == op["issue_id"]:
                        native["comments"] = copy.deepcopy(r["comments"])
    elif action == "delete-issue":
        s.setdefault("absence_readbacks", []).append(
            {"id": op["id"], "direct_lookup": "not_found", "milestone_absent": True}
        )
        s["tasks"] = [r for r in s["tasks"] if m.identity(r["issue"]) != op["id"]]
        for r in s["tasks"] + s["consumers"]:
            for k in ("blocks", "blockedBy", "relatedTo"):
                r["issue"]["relations"][k] = [
                    edge for edge in r["issue"]["relations"][k] if edge["id"] != op["id"]
                ]
    # Internal consumer reads and task reads refer to the same native issue.
    for r in s["consumers"]:
        native = next(
            (t for t in s["tasks"] if m.identity(t["issue"]) == m.identity(r["issue"])), None
        )
        if native:
            r["issue"] = copy.deepcopy(native["issue"])
            r["comments"] = copy.deepcopy(native["comments"])


def finish(s: dict) -> list[str]:
    actions = []
    for _ in range(30):
        op = m.next_operation(s)
        actions.append(op["action"])
        if op["action"] == "complete":
            return actions
        apply(s, op)
    raise AssertionError("Checkpoint did not terminate")


class MilestoneCheckpointTest(unittest.TestCase):
    def test_compact_retains_tasks_and_reuses_one_summary_and_archive(self) -> None:
        r = request()
        p = m.preview(r)
        s = state(r, p)
        actions = finish(s)
        self.assertEqual(
            actions,
            [
                "save-archive",
                "save-comment",
                "save-milestone-summary",
                "delete-comment",
                "complete",
            ],
        )
        self.assertEqual(len(s["tasks"]), 1)
        self.assertEqual(len(s["tasks"][0]["comments"]), 1)
        self.assertIn(p["archive"]["key"], s["tasks"][0]["comments"][0]["body"])
        self.assertTrue(s["milestone"]["description"].startswith("Original criteria."))
        r2 = copy.deepcopy(r)
        r2["archive"] = s["archive"]
        r2["milestone"] = s["milestone"]
        r2["tasks"] = s["tasks"]
        r2["tasks"][0]["groups"][0]["source_ids"] = ["T2"]
        r2["summary"] = "Updated outcome; remaining verification still open."
        p2 = m.preview(r2)
        self.assertEqual(p2["archive"]["key"], p["archive"]["key"])
        self.assertEqual(p2["description_template"].count(m.START), 1)
        self.assertTrue(
            p["archive"]["tasks"]["T"]["comments"].keys()
            <= p2["archive"]["tasks"]["T"]["comments"].keys()
        )
        self.assertEqual(m.next_operation(s)["action"], "complete")

    def test_prune_only_after_all_readbacks_and_archived_dependency_resolution(self) -> None:
        r = request(True)
        p = m.preview(r)
        s = state(r, p)
        actions = finish(s)
        self.assertEqual(actions[-3:], ["delete-comment", "delete-issue", "complete"])
        self.assertEqual(s["tasks"], [])
        resolved = m.resolve_archived_task(
            {
                "archive": s["archive"],
                "expected_archive_hash": p["archive_hash"],
                "task_id": "T",
                "native_absence_verified": True,
            }
        )
        self.assertTrue(resolved["archived"])
        self.assertEqual(resolved["status"], "Done")
        for mutation in (
            {"native_absence_verified": False},
            {"task_id": "missing"},
            {"expected_archive_hash": "wrong"},
        ):
            with self.assertRaises((UsageError, GovernedStop)):
                m.resolve_archived_task(
                    {
                        "archive": s["archive"],
                        "expected_archive_hash": p["archive_hash"],
                        "task_id": "T",
                        "native_absence_verified": True,
                        **mutation,
                    }
                )

    def test_surviving_consumer_handoff_precedes_deletion(self) -> None:
        r = request(True)
        survivor = task_record("U", completed=False)
        survivor["issue"]["relations"]["blockedBy"] = [{"id": "T"}]
        r["tasks"][0]["issue"]["relations"]["blocks"] = [{"id": "U"}]
        r["tasks"].append(survivor)
        r["consumers"] = [copy.deepcopy(survivor)]
        p = m.preview(r)
        s = state(r, p)
        actions = finish(s)
        self.assertLess(actions.index("save-dependency-comment"), actions.index("delete-issue"))
        self.assertEqual([m.identity(t["issue"]) for t in s["tasks"]], ["U"])
        self.assertEqual(s["tasks"][0]["issue"]["statusType"], "started")
        self.assertTrue(
            any("archived-dependencies" in c["body"] for c in s["tasks"][0]["comments"])
        )

    def test_no_implicit_upgrade_or_missing_delete_capability(self) -> None:
        r = request(True)
        r["invocation"]["options"] = {}
        with self.assertRaises(UsageError):
            m.preview(r)
        r = request(True)
        p = m.preview(r)
        s = state(r, p)
        s["invocation"]["options"] = {}
        with self.assertRaises(UsageError):
            m.next_operation(s)
        s = state(r, p)
        s["delete_issue_capability"] = {"available": False}
        with self.assertRaises(UsageError):
            m.next_operation(s)
        s = state(r, p)
        s["approved_hash"] = "approved generally"
        with self.assertRaises(GovernedStop):
            m.next_operation(s)

    def test_open_gate_unverified_and_unmapped_consumers_are_not_pruned(self) -> None:
        for kind in ("open", "gate", "evidence", "consumer", "scope", "inventory", "capacity"):
            with self.subTest(kind=kind):
                r = request(True)
                if kind == "open":
                    r["tasks"][0]["issue"]["statusType"] = "started"
                elif kind == "gate":
                    r["tasks"][0]["issue"]["description"] += (
                        "<!-- linear-spanks:human-verification-gate {} -->"
                    )
                elif kind == "evidence":
                    r["outcomes"]["T"]["evidence"][0]["hash"] = "wrong"
                elif kind == "consumer":
                    r["tasks"][0]["issue"]["relations"]["blocks"] = [{"id": "external"}]
                elif kind == "scope":
                    r["tasks"][0]["issue"]["projectId"] = "elsewhere"
                elif kind == "inventory":
                    r["tasks_has_next_page"] = True
                else:
                    r["archive_max_bytes"] = 10
                with self.assertRaises((UsageError, GovernedStop)):
                    m.preview(r)

    def test_partial_failure_and_source_drift_prevent_deletion(self) -> None:
        for kind in ("archive", "description", "comment", "new_task", "missing_task"):
            with self.subTest(kind=kind):
                r = request()
                p = m.preview(r)
                s = state(r, p)
                apply(s, m.next_operation(s))
                if kind == "archive":
                    s["archive"]["key"] += "changed"
                elif kind == "description":
                    s["milestone"]["description"] += "human edit"
                elif kind == "comment":
                    s["tasks"][0]["comments"][0]["body"] += "human edit"
                elif kind == "new_task":
                    s["tasks"].append(task_record("new"))
                else:
                    s["tasks"] = []
                with self.assertRaises((UsageError, GovernedStop)):
                    m.next_operation(s)

    def test_compact_cannot_resolve_a_deleted_task_as_pruned(self) -> None:
        p = m.preview(request())
        with self.assertRaises(UsageError):
            m.resolve_archived_task(
                {
                    "archive": p["archive"],
                    "expected_archive_hash": p["archive_hash"],
                    "task_id": "T",
                    "native_absence_verified": True,
                }
            )

    def test_receipt_claim_without_passing_candidate_evidence_is_rejected(self) -> None:
        r = request(True)
        c = r["tasks"][0]["comments"][1]
        c["body"] = "A user says the task is Done"
        r["outcomes"]["T"]["evidence"][0]["hash"] = sha256_digest(c)
        with self.assertRaises(UsageError):
            m.preview(r)

    def test_reusing_canonical_body_does_not_duplicate_markers(self) -> None:
        r = request()
        p = m.preview(r)
        s = state(r, p)
        finish(s)
        r["archive"] = s["archive"]
        r["tasks"] = s["tasks"]
        group = r["tasks"][0]["groups"][0]
        group["source_ids"] = ["T2"]
        group["body"] = r["tasks"][0]["comments"][0]["body"]
        p2 = m.preview(r)
        body = p2["task_plans"]["T"]["canonical"][0]["body"]
        self.assertEqual(body.count("linear-spanks:task-comment"), 1)

    def test_prune_multiple_tasks_reconciles_native_edge_removals(self) -> None:
        r = request(True)
        u = task_record("U")
        r["tasks"][0]["issue"]["relations"]["blocks"] = [{"id": "U"}]
        u["issue"]["relations"]["blockedBy"] = [{"id": "T"}]
        r["tasks"].append(u)
        r["prune_ids"].append("U")
        r["outcomes"]["U"] = {
            **r["outcomes"]["T"],
            "evidence": [{"id": "U2", "hash": sha256_digest(u["comments"][1])}],
        }
        p = m.preview(r)
        s = state(r, p)
        self.assertEqual(finish(s).count("delete-issue"), 2)
        self.assertEqual(s["tasks"], [])

    def test_external_consumer_drift_stops_before_archive_mutation(self) -> None:
        r = request(True)
        u = task_record("U", completed=False)
        u["issue"]["projectId"] = "another project"
        r["tasks"][0]["issue"]["relations"]["relatedTo"] = [{"id": "U"}]
        r["consumers"] = [u]
        p = m.preview(r)
        s = state(r, p)
        s["consumers"][0]["comments"].append(comment("human-new"))
        with self.assertRaises(UsageError):
            m.next_operation(s)
        s = state(r, p)
        actions = finish(s)
        self.assertLess(actions.index("save-dependency-comment"), actions.index("delete-issue"))

    def test_detached_task_is_not_reported_as_deleted(self) -> None:
        r = request(True)
        p = m.preview(r)
        s = state(r, p)
        while True:
            op = m.next_operation(s)
            if op["action"] == "delete-issue":
                s["tasks"] = []  # Moved/detached, without a direct native not-found readback.
                break
            apply(s, op)
        with self.assertRaises(UsageError):
            m.next_operation(s)

    def test_cli_levels_and_policy_slices(self) -> None:
        for args, deletions in (
            ([], False),
            (["--level", "compact"], False),
            (["--level=prune"], True),
        ):
            out = io.StringIO()
            code = run(
                ["contracts", "envelope", "milestone", "checkpoint", "M", *args],
                stdin=io.StringIO(),
                stdout=out,
            )
            self.assertEqual(code, 0, out.getvalue())
            result = json.loads(out.getvalue())["result"]
            self.assertEqual("approved_task_deletions" in result["writes"], deletions)
            self.assertIn("references/milestone-checkpoint.md", result["required_references"])
        for command in (
            ["milestone", "checkpoint", "M", "--level", "auto"],
            ["task", "checkpoint", "T", "--level", "prune"],
        ):
            out = io.StringIO()
            self.assertNotEqual(
                run(["contracts", "envelope", *command], stdin=io.StringIO(), stdout=out), 0
            )
