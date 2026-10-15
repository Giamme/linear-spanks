from __future__ import annotations

import copy
import io
import json
import unittest

from linear_spanks.cli.app import run
from linear_spanks.core.errors import GovernedStop, UsageError
from linear_spanks.domains import task_checkpoint as tc


def comment(cid: str, body: str = "Original review " * 60) -> dict:
    return {
        "id": cid,
        "body": body,
        "author": {"id": "human-account"},
        "createdAt": "2026-09-07T10:00:00Z",
        "updatedAt": "2026-09-07T10:00:00Z",
        "parentId": None,
        "quotedText": None,
        "onBehalfOf": None,
    }


def request() -> dict:
    return {
        "project_id": "P",
        "task_id": "T",
        "identifier": "ENG-1",
        "issue": {"id": "T", "projectId": "P", "description": "Stable intent", "status": "Done"},
        "comments": [comment("r1"), comment("r2"), comment("human", "Unresolved human question")],
        "has_next_page": False,
        "archive": None,
        "archive_max_bytes": 100000,
        "groups": [
            {
                "type": "review",
                "source_ids": ["r1", "r2"],
                "canonical_id": "r2",
                "body": "Review: F1 fixed; F2 remains open. Static only.",
            }
        ],
        "keep_ids": ["human"],
    }


def state(r: dict, p: dict) -> dict:
    return {
        "preview": p,
        "approved_hash": p["preview_hash"],
        "comments": copy.deepcopy(r["comments"]),
        "issue": copy.deepcopy(r["issue"]),
        "has_next_page": False,
        "archive": r["archive"],
    }


class TaskCheckpointTest(unittest.TestCase):
    def test_archive_first_then_all_summaries_then_deletions_and_resume(self) -> None:
        r = request()
        r["comments"] += [comment("p1"), comment("p2")]
        r["groups"].append(
            {
                "type": "plan",
                "source_ids": ["p1", "p2"],
                "canonical_id": "p2",
                "body": "Current plan revision 2; exact binding retained.",
            }
        )
        p = tc.preview(r)
        s = state(r, p)
        self.assertLess(p["after"]["bytes"], p["before"]["bytes"])
        actions = []
        while True:
            op = tc.next_operation(s)
            actions.append(op["action"])
            if op["action"] == "save-archive":
                self.assertEqual(list(op["value"]["comments"].values()), r["comments"])
                s["archive"] = copy.deepcopy(op["value"])
            elif op["action"] == "save-comment":
                row = next(c for c in s["comments"] if c["id"] == op["id"])
                row["body"] = op["body"]
                row["updatedAt"] = "2026-09-07T11:00:00Z"
                s["issue"]["updatedAt"] = "comment mutation timestamp"
            elif op["action"] == "delete-comment":
                s["comments"] = [c for c in s["comments"] if c["id"] != op["id"]]
            else:
                break
            # Simulate a new coordinator restored only from durable observations.
            s = json.loads(json.dumps(s))
        self.assertEqual(
            actions,
            [
                "save-archive",
                "save-comment",
                "save-comment",
                "delete-comment",
                "delete-comment",
                "complete",
            ],
        )
        self.assertEqual(tc.next_operation(s)["action"], "complete")
        self.assertEqual({c["id"] for c in s["comments"]}, {"r2", "p2", "human"})
        self.assertEqual(s["issue"]["description"], "Stable intent")

    def test_approval_and_failed_archive_readback_block_deletion(self) -> None:
        r = request()
        p = tc.preview(r)
        s = state(r, p)
        s["approved_hash"] = "wrong"
        with self.assertRaises(GovernedStop):
            tc.next_operation(s)
        s["approved_hash"] = p["preview_hash"]
        s["comments"][1]["body"] = p["canonical"][0]["body"]
        with self.assertRaises(GovernedStop) as caught:
            tc.next_operation(s)
        self.assertEqual(caught.exception.code, "CONTEXT_ARCHIVE_UNVERIFIED")

    def test_fresh_drift_stops_before_deleting(self) -> None:
        for change in (
            "new",
            "edited",
            "description",
            "archive",
            "author",
            "missing",
            "incomplete",
        ):
            with self.subTest(change=change):
                r = request()
                p = tc.preview(r)
                s = state(r, p)
                s["archive"] = copy.deepcopy(p["archive"])
                if change == "new":
                    s["comments"].append(comment("new"))
                elif change == "edited":
                    s["comments"][0]["body"] += "changed"
                elif change == "description":
                    s["issue"]["description"] += "changed"
                elif change == "archive":
                    s["archive"]["identifier"] = "wrong"
                elif change == "author":
                    s["comments"][1]["body"] = p["canonical"][0]["body"]
                    s["comments"][1]["author"] = {"id": "someone else"}
                elif change == "missing":
                    s["comments"] = s["comments"][:2]
                else:
                    s["has_next_page"] = True
                with self.assertRaises((GovernedStop, UsageError)):
                    tc.next_operation(s)

    def test_threads_and_incomplete_classification_not_deleted(self) -> None:
        for change in (
            "thread",
            "reply",
            "unknown",
            "overlap",
            "duplicate",
            "missing_keep",
            "capacity",
            "active_budget",
        ):
            with self.subTest(change=change):
                r = request()
                if change == "thread":
                    r["comments"][2]["parentId"] = "r1"
                elif change == "reply":
                    r["comments"][0]["parentId"] = "human"
                elif change == "unknown":
                    r["groups"][0]["source_ids"].append("absent")
                elif change == "overlap":
                    r["groups"].append({**r["groups"][0], "type": "plan"})
                elif change == "duplicate":
                    r["groups"].append(r["groups"][0])
                elif change == "missing_keep":
                    r["keep_ids"] = []
                elif change == "capacity":
                    r["archive_max_bytes"] = 100
                else:
                    r["default_tokens"] = 10
                with self.assertRaises((GovernedStop, UsageError)):
                    tc.preview(r)

    def test_repeated_checkpoint_updates_one_archive_without_losing_originals(self) -> None:
        r = request()
        p = tc.preview(r)
        originals = copy.deepcopy(p["archive"]["comments"])
        r["archive"] = p["archive"]
        r["comments"] = [
            comment("r2", p["canonical"][0]["body"]),
            comment("human", "Unresolved human question"),
            comment("r3"),
        ]
        r["groups"][0]["source_ids"] = ["r2", "r3"]
        r["groups"][0]["body"] = "F1 fixed; F2 now fixed by later evidence."
        p2 = tc.preview(r)
        self.assertEqual(p2["archive_key"], p["archive_key"])
        self.assertTrue(all(p2["archive"]["comments"].get(k) == v for k, v in originals.items()))
        self.assertEqual(len(p2["archive"]["checkpoints"]), 2)
        self.assertEqual(p2["delete_ids"], ["r3"])
        self.assertEqual(tc.preview(r), p2)

    def test_policy_drift_and_corrupt_archive_fail_closed(self) -> None:
        from linear_spanks.domains.context import budget_session

        r = request()
        p = tc.preview(r)
        with budget_session({"ancestry": {"project": "P", "task": "T"}, "policies": []}):
            with self.assertRaises(GovernedStop) as caught:
                tc.next_operation(state(r, p))
            self.assertEqual(caught.exception.code, "CONTEXT_POLICY_DRIFT")
        r["archive"] = copy.deepcopy(p["archive"])
        original = next(iter(r["archive"]["comments"].values()))
        original["body"] = "corrupted original"
        with self.assertRaises(UsageError):
            tc.preview(r)

    def test_slot_update_edits_in_place_instead_of_appending(self) -> None:
        """Each managed type owns one comment; a new revision edits it rather than appending."""
        human = {
            "id": "h",
            "body": "Any update?",
            "createdAt": "t0",
            "updatedAt": "t0",
            "author": {},
            "parentId": None,
        }
        created = tc.slot_plan(
            {
                "task_id": "T",
                "has_next_page": False,
                "comments": [human],
                "type": "plan",
                "body": "Step 1",
                "revised_at": "t1",
            }
        )
        self.assertEqual(created["action"], "create-comment")
        self.assertIsNone(created["comment_id"])
        self.assertEqual(created["revision"], 1)
        self.assertEqual(created["slot_index"], 0)
        # The read-back projection from the mutation protocol only needs the edited field.
        self.assertEqual(created["written_fields"], ["body"])

        row = {
            "id": "c1",
            "body": created["body"],
            "createdAt": "t1",
            "updatedAt": "t1",
            "author": {},
            "parentId": None,
        }
        updated = tc.slot_plan(
            {
                "task_id": "T",
                "has_next_page": False,
                "comments": [human, row],
                "type": "plan",
                "body": "Step 1 revised",
                "revised_at": "t2",
            }
        )
        self.assertEqual(updated["action"], "update-comment")
        self.assertEqual(updated["comment_id"], "c1")
        self.assertEqual(updated["revision"], 2)
        self.assertEqual(updated["previous"]["revision"], 1)
        # The superseded state stays visible without keeping the whole prior body.
        self.assertIn("Superseded revisions", updated["body"])
        self.assertIn("Step 1", updated["body"])

    def test_repeated_slot_edits_do_not_accumulate_markers_or_history(self) -> None:
        """Editing in place is only a win if the body stays bounded across many revisions."""
        human = {
            "id": "h",
            "body": "note",
            "createdAt": "t0",
            "updatedAt": "t0",
            "author": {},
            "parentId": None,
        }
        plan = tc.slot_plan(
            {
                "task_id": "T",
                "has_next_page": False,
                "comments": [human],
                "type": "handoff",
                "body": "Handoff v1",
                "revised_at": "t1",
            }
        )
        row = {
            "id": "c1",
            "body": plan["body"],
            "createdAt": "t1",
            "updatedAt": "t1",
            "author": {},
            "parentId": None,
        }
        for revision in range(2, 10):
            plan = tc.slot_plan(
                {
                    "task_id": "T",
                    "has_next_page": False,
                    "comments": [human, row],
                    "type": "handoff",
                    "body": f"Handoff v{revision}",
                    "revised_at": f"t{revision}",
                    "max_history_entries": 3,
                }
            )
            row = {**row, "body": plan["body"], "updatedAt": f"t{revision}"}
        self.assertEqual(plan["revision"], 9)
        self.assertEqual(plan["body"].count("linear-spanks:task-comment"), 1)
        self.assertEqual(plan["body"].count(tc.HISTORY_START), 1)
        marker = json.loads(
            plan["body"].rsplit("<!-- linear-spanks:task-comment ", 1)[1].rsplit(" -->", 1)[0]
        )
        self.assertEqual([entry["revision"] for entry in marker["history"]], [6, 7, 8])
        self.assertLess(len(plan["body"]), 1200)

    def test_slot_resolution_ignores_position_and_refuses_duplicates(self) -> None:
        """Slots key off the managed marker; ordinal position is not stable in a real task."""
        human = {
            "id": "h",
            "body": "posted first",
            "createdAt": "t0",
            "updatedAt": "t0",
            "author": {},
            "parentId": None,
        }
        plan = tc.slot_plan(
            {
                "task_id": "T",
                "has_next_page": False,
                "comments": [human],
                "type": "review",
                "body": "Review v1",
                "revised_at": "t1",
            }
        )
        managed = {
            "id": "c1",
            "body": plan["body"],
            "createdAt": "t1",
            "updatedAt": "t1",
            "author": {},
            "parentId": None,
        }
        # A human comment occupies the first position; the review slot still resolves.
        layout = tc.read_slots(
            {"task_id": "T", "has_next_page": False, "comments": [human, managed]}
        )
        self.assertEqual(layout["slots"]["review"]["comment_id"], "c1")
        self.assertEqual(layout["slots"]["review"]["slot_index"], 2)
        self.assertEqual(layout["unmanaged_comment_ids"], ["h"])
        # A marker for another task never claims this task's slot.
        foreign = {**managed, "id": "c2", "body": managed["body"].replace('"T"', '"OTHER"')}
        other = tc.read_slots(
            {"task_id": "T", "has_next_page": False, "comments": [managed, foreign]}
        )
        self.assertEqual(sorted(other["slots"]), ["review"])
        duplicate = {**managed, "id": "c3"}
        with self.assertRaises(GovernedStop) as caught:
            tc.slot_plan(
                {
                    "task_id": "T",
                    "has_next_page": False,
                    "comments": [managed, duplicate],
                    "type": "review",
                    "body": "Review v2",
                    "revised_at": "t2",
                }
            )
        self.assertEqual(caught.exception.code, "TASK_SLOT_AMBIGUOUS")

    def test_checkpoint_consolidation_strips_slot_history_and_markers(self) -> None:
        """task checkpoint must not re-wrap a body that already carries slot trailers."""
        plan = tc.slot_plan(
            {
                "task_id": "T",
                "has_next_page": False,
                "comments": [
                    {
                        "id": "c1",
                        "body": "Plan v1\n\n<!-- linear-spanks:task-comment "
                        + '{"schema_version": 1, "task_id": "T", "type": "plan"} -->',
                        "createdAt": "t0",
                        "updatedAt": "t0",
                        "author": {},
                        "parentId": None,
                    }
                ],
                "type": "plan",
                "body": "Plan v2",
                "revised_at": "t1",
            }
        )
        stripped, marker = tc._strip_managed(plan["body"], "T", "plan")
        self.assertEqual(stripped, "Plan v2")
        self.assertEqual(marker["revision"], 2)
        self.assertNotIn(tc.HISTORY_START, stripped)

    def test_cli_compiles_new_public_contract_and_internal_preview(self) -> None:
        stdout = io.StringIO()
        code = run(
            ["contracts", "envelope", "task", "checkpoint", "ENG-1"],
            stdin=io.StringIO(),
            stdout=stdout,
        )
        self.assertEqual(code, 0, stdout.getvalue())
        envelope = json.loads(stdout.getvalue())["result"]
        self.assertIn("approved_redundant_comment_deletions", envelope["writes"])
        self.assertIn("references/task-checkpoint.md", envelope["required_references"])
        stdout = io.StringIO()
        code = run(
            ["context", "task-checkpoint-preview"],
            stdin=io.StringIO(json.dumps(request())),
            stdout=stdout,
        )
        self.assertEqual(code, 0, stdout.getvalue())
        self.assertEqual(json.loads(stdout.getvalue())["result"]["delete_ids"], ["r1"])
