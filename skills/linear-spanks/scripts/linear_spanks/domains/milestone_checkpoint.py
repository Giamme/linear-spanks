"""Milestone comment compaction and explicitly requested, receipt-backed task pruning."""

from __future__ import annotations

import copy
import json
import re
from typing import Any

from ..core.errors import UsageError
from ..core.hashing import sha256_digest
from . import task_checkpoint as task
from .context import _BUDGET, integer, measurement, stop

START = "<!-- linear-spanks:milestone-checkpoint:start -->"
END = "<!-- linear-spanks:milestone-checkpoint:end -->"
URL = "{{archive_url}}"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise UsageError("INVALID_MILESTONE_CHECKPOINT", message)


def identity(issue: dict[str, Any]) -> str:
    return str(issue.get("uuid", issue["id"]))


def level(invocation: dict[str, Any]) -> str:
    require(
        invocation.get("command") == "milestone checkpoint", "Bind the actual public invocation"
    )
    selected = invocation.get("options", {}).get("level", "compact")
    require(selected in {"compact", "prune"}, "level must be compact or prune")
    return str(selected)


def milestone_core(value: dict[str, Any]) -> dict[str, Any]:
    # Comment writes bump updatedAt; task deletion changes derived progress.
    return {k: v for k, v in value.items() if k not in {"description", "updatedAt", "progress"}}


def summary_description(description: str, paragraph: str, key: str) -> str:
    require(0 < len(paragraph) <= 2000 and "\n" not in paragraph, "Use one short paragraph")
    require(
        START not in paragraph and END not in paragraph and URL not in paragraph,
        "Reserved summary markers",
    )
    require(URL not in description, "Reserved link placeholder in original description")
    require(description.count(START) == description.count(END) <= 1, "Ambiguous managed summary")
    section = f"{START}\n{paragraph} [Archive](<{URL}>)\n\n`{key}`\n{END}"
    if START not in description:
        return description.rstrip() + "\n\n" + section
    before, rest = description.split(START)
    require(END in rest, "Malformed managed summary")
    _, after = rest.split(END, 1)
    return before + section + after


def _task_map(rows: list[dict[str, Any]], complete: bool) -> dict[str, dict[str, Any]]:
    require(complete is False, "Read every milestone task page")
    result = {identity(row["issue"]): row for row in rows}
    require(len(result) == len(rows), "Duplicate task identity")
    return result


def _passed_receipt(body: str, candidate: str) -> bool:
    for raw in re.findall(r"```json\n(.*?)\n```", body, re.S):
        try:
            receipt = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(receipt, dict) or receipt.get("candidate_commit") != candidate:
            continue
        if receipt.get("verification_status") == "passed":
            return True
        commands = receipt.get("verification_commands")
        review = receipt.get("independent_review", {})
        if (
            isinstance(commands, list)
            and bool(commands)
            and all(
                isinstance(c, dict) and type(c.get("exit_code")) is int and c["exit_code"] == 0
                for c in commands
            )
            and isinstance(review, dict)
            and review.get("result") == "passed"
        ):
            return True
    return False


def _outcome(record: dict[str, Any], value: dict[str, Any]) -> None:
    issue = record["issue"]
    require(
        issue.get("statusType") == "completed" and bool(issue.get("completedAt")),
        "Only completed tasks may be pruned",
    )
    require(
        "linear-spanks:human-verification-gate" not in issue["description"],
        "Managed human gates cannot be pruned",
    )
    require(
        value.get("verification_status") == "passed" and bool(value.get("summary")),
        "Require a verified terminal outcome",
    )
    require(
        bool(re.fullmatch(r"[0-9a-f]{40}", value.get("candidate_commit", ""))),
        "Bind the verified candidate",
    )
    evidence = value.get("evidence", [])
    require(isinstance(evidence, list) and bool(evidence), "Missing outcome evidence")
    sources = task._comments(record)
    # Completion/review sources may already live in the single task archive.
    if record.get("archive"):
        sources.update({c["id"] + ":" + h: c for h, c in record["archive"]["comments"].items()})
    bound_sources = []
    for ref in evidence:
        matching = [
            c for c in sources.values() if c["id"] == ref["id"] and sha256_digest(c) == ref["hash"]
        ]
        require(bool(matching), "Outcome evidence is not preserved exactly")
        bound_sources.extend(matching)
    require(
        any(_passed_receipt(c["body"], value["candidate_commit"]) for c in bound_sources),
        "Outcome requires a machine-readable passing receipt for the exact candidate",
    )


def preview(payload: dict[str, Any]) -> dict[str, Any]:
    selected = level(payload["invocation"])
    project, milestone = payload["project_id"], payload["milestone"]
    mid = milestone["id"]
    require(
        bool(project) and bool(mid) and isinstance(milestone.get("description"), str),
        "Resolve milestone and project",
    )
    require(
        payload["invocation"].get("target") in {mid, milestone.get("name")},
        "Invocation target differs from resolved milestone",
    )
    scoped_project = payload["invocation"].get("options", {}).get("project_id")
    require(scoped_project is None or scoped_project == project, "Invocation project differs")
    records = _task_map(payload["tasks"], payload["tasks_has_next_page"])
    key = f"milestone-task-archive/{project}/{mid}"
    previous = payload.get("archive")
    if previous is not None:
        require(
            previous.get("kind") == "MilestoneTaskArchive"
            and previous.get("schema_version") == 1
            and previous.get("key") == key,
            "Archive scope/version differs",
        )
        for collection in ("milestones", "operations", "consumer_sources"):
            require(
                all(sha256_digest(v) == h for h, v in previous[collection].items()),
                "Archive history changed",
            )
    archived_tasks = copy.deepcopy(previous["tasks"]) if previous else {}
    task_plans = {}
    for tid, record in records.items():
        issue = record["issue"]
        require(
            issue.get("projectId") == project
            and issue.get("projectMilestone", {}).get("id") == mid,
            "Task scope differs",
        )
        if "linear-spanks:human-verification-gate" in issue["description"]:
            require(not record["groups"], "Keep managed human gate comments intact")
        request = {
            **record,
            "project_id": project,
            "task_id": tid,
            "identifier": issue["id"],
            "archive_max_bytes": payload["archive_max_bytes"],
        }
        existing = archived_tasks.get(tid)
        if existing:
            # Merge standalone task archives without losing older originals.
            incoming = record.get("archive")
            if incoming:
                require(incoming["key"] == existing["key"], "Task archive identity differs")
                for collection in ("comments", "issues", "checkpoints"):
                    existing[collection].update(incoming[collection])
            request["archive"] = existing
        tp = task.preview(request, archive_reference=key)
        task_plans[tid] = tp
        archived_tasks[tid] = tp["archive"]
    prune = payload.get("prune_ids", [])
    require(
        isinstance(prune, list) and len(prune) == len(set(prune)) and set(prune) <= records.keys(),
        "Invalid prune selection",
    )
    require(selected == "prune" or not prune, "Task deletion requires explicit --level prune")
    outcomes = copy.deepcopy(previous["outcomes"]) if previous else {}
    for tid in prune:
        value = payload.get("outcomes", {}).get(tid)
        require(isinstance(value, dict), "Each pruned task requires a verified outcome")
        _outcome({**records[tid], "archive": archived_tasks[tid]}, value)
        outcomes[tid] = value
    aliases = {alias: tid for tid, r in records.items() for alias in {tid, r["issue"]["id"]}}
    consumers = {identity(r["issue"]): r for r in payload.get("consumers", [])}
    require(len(consumers) == len(payload.get("consumers", [])), "Duplicate consumer")
    dependents: dict[str, set[str]] = {}
    for tid in prune:
        relations = records[tid]["issue"].get("relations")
        require(isinstance(relations, dict), "Read all task relations before pruning")
        for kind in ("blocks", "blockedBy", "relatedTo"):
            require(isinstance(relations.get(kind), list), "Incomplete task relations")
            for related in relations[kind]:
                rid = aliases.get(related["id"], related["id"])
                if rid in prune:
                    continue
                # External connector rows may identify an issue by its human key.
                matches = [cid for cid, r in consumers.items() if rid in {cid, r["issue"]["id"]}]
                require(
                    len(matches) == 1,
                    "Every surviving related issue requires a fresh consumer record",
                )
                dependents.setdefault(matches[0], set()).add(tid)
    require(set(consumers) == set(dependents), "Consumer scope differs from affected relations")
    handoffs = []
    for cid, ids in sorted(dependents.items()):
        task._comments(consumers[cid])
        marker = {"schema_version": 1, "archive": key, "task_ids": sorted(ids)}
        body = (
            "Archived prerequisite results: "
            + ", ".join(records[t]["issue"]["id"] for t in sorted(ids))
            + f". Read the verified outcomes in [milestone archive](<{URL}>) before reuse; archival is not fresh verification.\n\n<!-- linear-spanks:archived-dependencies "
            + json.dumps(marker, sort_keys=True)
            + " -->"
        )
        handoffs.append({"issue_id": cid, "body": body, "task_ids": sorted(ids)})
    description = summary_description(milestone["description"], payload["summary"], key)
    history = copy.deepcopy(previous["milestones"]) if previous else {}
    history[sha256_digest(milestone)] = milestone
    consumer_history = copy.deepcopy(previous["consumer_sources"]) if previous else {}
    for r in consumers.values():
        consumer_history[sha256_digest(r)] = r
    operation = {
        "level": selected,
        "invocation": payload["invocation"],
        "prune_ids": sorted(prune),
        "summary_template": description,
        "handoffs": handoffs,
        "task_previews": {t: p["preview_hash"] for t, p in task_plans.items()},
    }
    operations = copy.deepcopy(previous["operations"]) if previous else {}
    operation_id = sha256_digest(operation)
    operations[operation_id] = operation
    archive = {
        "kind": "MilestoneTaskArchive",
        "schema_version": 1,
        "key": key,
        "project_id": project,
        "milestone_id": mid,
        "tasks": archived_tasks,
        "outcomes": outcomes,
        "milestones": history,
        "consumer_sources": consumer_history,
        "operations": operations,
    }
    capacity = integer(payload["archive_max_bytes"], "archive_max_bytes", minimum=1)
    if measurement(archive)["bytes"] + 12 > capacity:
        stop(
            "CONTEXT_ARCHIVE_TOO_LARGE",
            measurement(archive),
            "Single milestone archive exceeds provider capacity; no deletion",
        )
    result = {
        "schema_version": 1,
        "command": "milestone checkpoint",
        "level": selected,
        "invocation": payload["invocation"],
        "policy_hash": _BUDGET.get().binding,
        "project_id": project,
        "milestone": milestone,
        "description_template": description,
        "task_plans": task_plans,
        "consumers": consumers,
        "handoffs": handoffs,
        "prune_ids": sorted(prune),
        "archive": archive,
        "archive_hash": sha256_digest(archive),
        "previous_archive_hash": sha256_digest(previous),
        "operation_id": operation_id,
    }
    result["preview_hash"] = sha256_digest(result)
    return result


def _render(body: str, archive_url: str) -> str:
    require(
        bool(re.fullmatch(r"https://linear\.app/[^\s<>\"{}]+", archive_url)),
        "Use the URL from the exact archive readback",
    )
    return body.replace(URL, archive_url)


def _adjust_issue(
    original: dict[str, Any], current: dict[str, Any], removed: set[str]
) -> dict[str, Any]:
    adjusted = copy.deepcopy(current)
    expected = copy.deepcopy(original)
    for value in (adjusted, expected):
        for kind in ("blocks", "blockedBy", "relatedTo"):
            if isinstance(value.get("relations", {}).get(kind), list):
                value["relations"][kind] = [
                    r for r in value["relations"][kind] if r["id"] not in removed
                ]
    require(
        task._issue_hash(adjusted) == task._issue_hash(expected),
        "Issue changed outside approved relation removals",
    )
    # Reuse task selector against the original material binding; only generated edge removals differ.
    return (
        {**original, "updatedAt": current.get("updatedAt", original.get("updatedAt"))}
        if "updatedAt" in original
        else original
    )


def next_operation(payload: dict[str, Any]) -> dict[str, Any]:
    plan = payload["preview"]
    digest = sha256_digest({k: v for k, v in plan.items() if k != "preview_hash"})
    if plan["preview_hash"] != digest or payload.get("approved_hash") != digest:
        stop("APPROVAL_REQUIRED", digest, "Approve this exact milestone checkpoint")
    require(
        level(payload["invocation"]) == plan["level"]
        and payload["invocation"] == plan["invocation"],
        "Restore the exact invocation; prune cannot be inferred from approval",
    )
    if plan["policy_hash"] != _BUDGET.get().binding:
        stop("CONTEXT_POLICY_DRIFT", plan["policy_hash"], "Refresh policies and reapprove")
    if plan["prune_ids"]:
        capability = payload.get("delete_issue_capability", {})
        require(
            capability.get("available") is True
            and bool(capability.get("provider"))
            and bool(capability.get("operation")),
            "No confirmed issue-delete capability; stop before mutations",
        )
    records = _task_map(payload["tasks"], payload["tasks_has_next_page"])
    originals = plan["task_plans"]
    require(not (set(records) - originals.keys()), "New task membership requires a fresh preview")
    missing = set(originals) - records.keys()
    require(missing <= set(plan["prune_ids"]), "Unselected task disappeared")
    absence = payload.get("absence_readbacks", [])
    require(isinstance(absence, list), "Provide native deletion readbacks")
    verified_absence = {
        r["id"]
        for r in absence
        if r.get("direct_lookup") == "not_found" and r.get("milestone_absent") is True
    }
    require(
        len(verified_absence) == len(absence) and verified_absence <= set(plan["prune_ids"]),
        "Invalid or duplicated native deletion readbacks",
    )
    require(
        missing <= verified_absence,
        "Milestone absence alone is not task deletion; verify direct native lookup",
    )
    removed = missing | {p["archive"]["identifier"] for t, p in originals.items() if t in missing}
    original_issues = {
        t: next(
            v for v in p["archive"]["issues"].values() if task._issue_hash(v) == p["issue_hash"]
        )
        for t, p in originals.items()
    }
    current_milestone = payload["milestone"]
    require(
        milestone_core(current_milestone) == milestone_core(plan["milestone"]),
        "Milestone contract changed",
    )
    archive = payload.get("archive")
    ready = sha256_digest(archive) == plan["archive_hash"]
    url = payload.get("archive_url", "")
    expected_description = _render(plan["description_template"], url) if ready else None
    require(
        current_milestone["description"]
        in {plan["milestone"]["description"], expected_description},
        "Milestone description drift",
    )
    if missing:
        require(
            ready and current_milestone["description"] == expected_description,
            "Deleted tasks lack a verified archive/summary",
        )
    if not ready:
        require(sha256_digest(archive) == plan["previous_archive_hash"], "Archive changed")
        for tid, record in records.items():
            require(
                task._issue_hash(record["issue"]) == originals[tid]["issue_hash"],
                "Task changed before archival",
            )
            require(
                task._comments(record) == originals[tid]["source_comments"],
                "Comments changed before archival",
            )
        fresh_consumers = {identity(r["issue"]): r for r in payload.get("consumers", [])}
        require(
            set(fresh_consumers) == set(plan["consumers"]),
            "Missing consumer sources before archive",
        )
        for cid, original in plan["consumers"].items():
            current = fresh_consumers[cid]
            require(
                task._issue_hash(current["issue"]) == task._issue_hash(original["issue"])
                and task._comments(current) == task._comments(original),
                "Consumer changed before archive",
            )
        return {
            "action": "save-archive",
            "key": plan["archive"]["key"],
            "value": plan["archive"],
            "expected_hash": plan["previous_archive_hash"],
        }
    if archive is None:
        raise UsageError("CONTEXT_ARCHIVE_UNVERIFIED", "Fresh archive readback required")
    consumers = {identity(r["issue"]): r for r in payload.get("consumers", [])}
    require(set(consumers) == set(plan["consumers"]), "Missing consumer readbacks")
    for cid, consumer in consumers.items():
        if cid in records:
            require(
                task._issue_hash(consumer["issue"]) == task._issue_hash(records[cid]["issue"])
                and task._comments(consumer) == task._comments(records[cid]),
                "Refresh inconsistent task/consumer reads",
            )
    handoff_ops = []
    generated = {}
    for handoff in plan["handoffs"]:
        cid = handoff["issue_id"]
        current, original = consumers[cid], plan["consumers"][cid]
        _adjust_issue(original["issue"], current["issue"], removed)
        body = _render(handoff["body"], url)
        generated[cid] = body
        rows = task._comments(current)
        matches = [c for c in rows.values() if c["body"] == body]
        require(len(matches) <= 1, "Duplicate dependency handoff")
        retained = {i: c for i, c in rows.items() if c["body"] != body}
        if cid not in originals:
            require(retained == task._comments(original), "Consumer discussion changed")
        if not matches:
            require(not missing, "Restore dependency handoffs before further pruning")
            handoff_ops.append({"action": "save-dependency-comment", "issue_id": cid, "body": body})
    task_ops = []
    for tid, record in records.items():
        normalized = _adjust_issue(original_issues[tid], record["issue"], removed)
        filtered = [c for c in record["comments"] if c["body"] != generated.get(tid)]
        tp = originals[tid]
        op = task.next_operation(
            {
                "preview": tp,
                "approved_hash": tp["preview_hash"],
                "issue": normalized,
                "comments": filtered,
                "has_next_page": record["has_next_page"],
                "archive": archive["tasks"][tid],
            }
        )
        if op["action"] != "complete":
            require(
                op["action"] in {"save-comment", "delete-comment"}, "Archive/task plan mismatch"
            )
            task_ops.append({**op, "task_id": tid})
    for op in task_ops:
        if op["action"] == "save-comment":
            return op
    if handoff_ops:
        return handoff_ops[0]
    if current_milestone["description"] != expected_description:
        return {
            "action": "save-milestone-summary",
            "id": plan["milestone"]["id"],
            "description": expected_description,
            "expected_description_hash": sha256_digest(current_milestone["description"]),
        }
    if task_ops:
        return task_ops[0]
    for tid in plan["prune_ids"]:
        if tid in records:
            _outcome({**records[tid], "archive": archive["tasks"][tid]}, archive["outcomes"][tid])
            return {
                "action": "delete-issue",
                "id": tid,
                "expected_hash": sha256_digest(records[tid]["issue"]),
                "outcome": archive["outcomes"][tid],
            }
    return {
        "action": "complete",
        "level": plan["level"],
        "archive": plan["archive"]["key"],
        "archive_url": url,
        "pruned_ids": plan["prune_ids"],
        "remaining_ids": sorted(records),
        "operation_id": plan["operation_id"],
    }


def resolve_archived_task(payload: dict[str, Any]) -> dict[str, Any]:
    """Resolve a missing prerequisite only from a verified archive and an explicit prune record."""
    archive, tid = payload["archive"], payload["task_id"]
    require(
        sha256_digest(archive) == payload["expected_archive_hash"], "Archive readback hash differs"
    )
    require(
        payload.get("native_absence_verified") is True,
        "Freshly resolve native issue identity first",
    )
    require(
        any(
            tid in op["prune_ids"] and op["level"] == "prune"
            for op in archive["operations"].values()
        ),
        "Task was not selected for pruning",
    )
    preserved = archive["tasks"][tid]
    outcome = archive["outcomes"][tid]
    issues = list(preserved["issues"].values())
    matching = [i for i in issues if i.get("statusType") == "completed" and i.get("completedAt")]
    require(bool(matching), "No archived terminal task")
    _outcome(
        {"issue": matching[-1], "comments": [], "has_next_page": False, "archive": preserved},
        outcome,
    )
    return {
        "id": tid,
        "identifier": preserved["identifier"],
        "archived": True,
        "status": "Done",
        "outcome": outcome,
        "archive": archive["key"],
        "verification": "historical terminal evidence; revalidate consumed outputs for current execution",
    }
