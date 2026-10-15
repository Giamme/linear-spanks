"""Pure, resumable task comment consolidation; Linear writes stay with the coordinator."""

from __future__ import annotations

import json
import re
from typing import Any

from ..core.errors import UsageError
from ..core.hashing import sha256_digest
from .context import _BUDGET, compaction_target, enforce_measurement, integer, measurement, stop

TYPES = frozenset({"plan", "review", "handoff", "execution"})
# Slots are identified by the managed marker, never by comment position: human comments and
# thread replies interleave with managed ones, so an ordinal would break the first time somebody
# commented before the plan was written.
SLOT_ORDER = ("plan", "handoff", "review", "execution")
MARKER_PATTERN = r"\s*<!-- linear-spanks:task-comment (\{[^\n]*\}) -->\s*$"
HISTORY_START = "<!-- linear-spanks:history-start -->"
HISTORY_END = "<!-- linear-spanks:history-end -->"
HISTORY_PATTERN = re.escape(HISTORY_START) + r".*?" + re.escape(HISTORY_END)
DEFAULT_HISTORY_ENTRIES = 5


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise UsageError("INVALID_TASK_CHECKPOINT", message)


def _strip_managed(body: str, task_id: str, kind: str) -> tuple[str, dict[str, Any] | None]:
    """Remove managed trailers so an edited body never accumulates markers or history blocks."""
    marker: dict[str, Any] | None = None
    while match := re.search(MARKER_PATTERN, body, re.S):
        prior = json.loads(match.group(1))
        _require(
            prior.get("task_id") == task_id and prior.get("type") == kind,
            "Canonical marker belongs to another task/type",
        )
        if marker is None:
            marker = prior
        body = body[: match.start()]
    body = re.sub(HISTORY_PATTERN, "", body, flags=re.S)
    return body.rstrip(), marker


def _comments(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    _require(payload.get("has_next_page") is False, "Read every comment page before checkpointing")
    rows = payload["comments"]
    _require(isinstance(rows, list), "comments must be a complete list")
    result = {}
    for row in rows:
        _require(isinstance(row, dict), "Comment must be the exact connector object")
        for field in ("id", "body", "createdAt", "updatedAt"):
            _require(isinstance(row.get(field), str), f"Comment requires {field}")
        _require(bool(row["id"]) and row["id"] not in result, "Duplicate/empty comment ID")
        _require("author" in row and "parentId" in row, "Preserve author and thread metadata")
        result[row["id"]] = row
    return result


def _issue_hash(issue: dict[str, Any]) -> str:
    # Linear may bump the issue timestamp when its comments change.
    return sha256_digest({k: v for k, v in issue.items() if k != "updatedAt"})


def preview(payload: dict[str, Any], *, archive_reference: str | None = None) -> dict[str, Any]:
    """Bind one archive write, one canonical update per type, and exact redundant deletions."""
    comments = _comments(payload)
    for field in ("project_id", "task_id", "identifier"):
        _require(isinstance(payload.get(field), str) and bool(payload[field]), f"Missing {field}")
    issue = payload["issue"]
    _require(
        isinstance(issue, dict) and isinstance(issue.get("description"), str),
        "Archive exact issue description and metadata",
    )
    _require(issue.get("uuid", issue.get("id")) == payload["task_id"], "Issue identity differs")
    _require(issue.get("projectId") == payload["project_id"], "Issue project differs")
    key = f"task-comment-archive/{payload['project_id']}/{payload['task_id']}"
    previous = payload.get("archive")
    if previous is not None:
        _require(
            previous.get("kind") == "TaskCommentArchive" and previous.get("schema_version") == 1,
            "Unsupported archive",
        )
        _require(previous.get("key") == key, "Archive scope differs")
        _require(
            previous.get("task_id") == payload["task_id"]
            and previous.get("project_id") == payload["project_id"],
            "Archive identity differs",
        )
        for collection in ("comments", "issues", "checkpoints"):
            rows = previous.get(collection)
            _require(isinstance(rows, dict), "Archive collection missing")
            _require(
                all(sha256_digest(value) == digest for digest, value in rows.items()),
                "Archived originals or operation hashes changed",
            )
    groups = payload["groups"]
    _require(isinstance(groups, list), "groups must be a list")
    seen: set[str] = set()
    kinds: set[str] = set()
    canonical = []
    deletions: list[str] = []
    for group in groups:
        kind, ids, body = group["type"], group["source_ids"], group["body"]
        _require(kind in TYPES and kind not in kinds, "One group per supported type")
        _require(
            isinstance(ids, list) and bool(ids) and all(isinstance(i, str) for i in ids),
            "Group requires source IDs",
        )
        _require(len(ids) == len(set(ids)) and not seen.intersection(ids), "Sources overlap")
        _require(set(ids) <= comments.keys(), "Unknown source comment")
        _require(isinstance(body, str) and bool(body.strip()), "Canonical body cannot be empty")
        _require(
            all(comments[i]["parentId"] is None for i in ids),
            "Thread replies cannot be consolidated",
        )
        # Do not orphan replies, even when the thread root itself is managed.
        _require(
            not any(c["parentId"] in ids for c in comments.values()),
            "Keep threads with replies intact",
        )
        keep = group["canonical_id"]
        _require(keep in ids, "Canonical comment must be one of the archived sources")
        # Reusing a canonical body must not accumulate old archive-reference markers.
        body, _ = _strip_managed(body, payload["task_id"], kind)
        _require(bool(body.strip()), "Canonical body cannot contain only a marker")
        marker = {
            "schema_version": 1,
            "task_id": payload["task_id"],
            "type": kind,
            "archive": archive_reference or key,
        }
        content = (
            body.rstrip()
            + "\n\n<!-- linear-spanks:task-comment "
            + json.dumps(marker, sort_keys=True)
            + " -->"
        )
        canonical.append({"id": keep, "type": kind, "body": content, "source_ids": sorted(ids)})
        deletions.extend(i for i in ids if i != keep)
        seen.update(ids)
        kinds.add(kind)
    kept = sorted(set(comments) - seen)
    _require(sorted(payload["keep_ids"]) == kept, "Classify every comment as consolidated or kept")
    # Retain each original version, including unknown/human comments and prior summaries.
    versions = dict(previous["comments"]) if previous else {}
    for row in comments.values():
        digest = sha256_digest(row)
        versions[digest] = row
    issues = dict(previous["issues"]) if previous else {}
    issues[sha256_digest(issue)] = issue
    source_hash = sha256_digest(comments)
    archive = {
        "kind": "TaskCommentArchive",
        "schema_version": 1,
        "key": key,
        "project_id": payload["project_id"],
        "task_id": payload["task_id"],
        "identifier": payload["identifier"],
        "comments": versions,
        "issues": issues,
        "checkpoints": dict(previous["checkpoints"]) if previous else {},
    }
    operation = {
        "source_hash": source_hash,
        "canonical": canonical,
        "delete_ids": sorted(deletions),
        "keep_ids": kept,
    }
    operation_id = sha256_digest(operation)
    archive["checkpoints"][operation_id] = operation
    size_limit = integer(payload["archive_max_bytes"], "archive_max_bytes", minimum=1)
    if measurement(archive)["bytes"] + 12 > size_limit:
        stop(
            "CONTEXT_ARCHIVE_TOO_LARGE",
            measurement(archive),
            "Single archive exceeds confirmed document capacity; do not split or delete",
        )
    active = [c["body"] for c in canonical] + [comments[i]["body"] for i in kept]
    active_measurement = enforce_measurement(active, payload.get("default_tokens", 12000))
    if active_measurement["estimated_tokens"] > compaction_target(
        payload.get("default_tokens", 12000)
    ):
        stop(
            "CONTEXT_COMPACTION_TARGET_OVERFLOW",
            active_measurement,
            "Shorten summaries without dropping required bindings; do not delete",
        )
    result = {
        "schema_version": 1,
        "command": "task checkpoint",
        "policy_hash": _BUDGET.get().binding,
        "project_id": payload["project_id"],
        "task_id": payload["task_id"],
        "issue_hash": _issue_hash(issue),
        "source_comments": comments,
        "source_hash": source_hash,
        "archive_key": key,
        "previous_archive_hash": sha256_digest(previous),
        "archive": archive,
        "archive_hash": sha256_digest(archive),
        "canonical": canonical,
        "delete_ids": sorted(deletions),
        "keep_ids": kept,
        "operation_id": operation_id,
        "before": measurement([c["body"] for c in comments.values()]),
        "after": active_measurement,
    }
    result["preview_hash"] = sha256_digest(result)
    return result


def next_operation(payload: dict[str, Any]) -> dict[str, Any]:
    """Return one safe operation from fresh readbacks, never simulated success/persistence."""
    plan = payload["preview"]
    digest = sha256_digest({k: v for k, v in plan.items() if k != "preview_hash"})
    if plan["preview_hash"] != digest or payload.get("approved_hash") != digest:
        stop(
            "APPROVAL_REQUIRED", digest, "Approve the exact archive, canonical bodies and deletions"
        )
    if plan["policy_hash"] != _BUDGET.get().binding:
        stop("CONTEXT_POLICY_DRIFT", plan["policy_hash"], "Refresh policy and reapprove")
    live = _comments(payload)
    originals = plan["source_comments"]
    if _issue_hash(payload["issue"]) != plan["issue_hash"]:
        stop("CONTEXT_SOURCE_DRIFT", plan["task_id"], "Refresh task and approve a new preview")
    if set(live) - originals.keys():
        stop(
            "CONTEXT_SOURCE_DRIFT",
            sorted(set(live) - originals.keys()),
            "New comments require a new archive preview",
        )
    canonical = {c["id"]: c for c in plan["canonical"]}
    updated = set()
    for cid, original in originals.items():
        current = live.get(cid)
        if current is None:
            if cid not in plan["delete_ids"]:
                stop("CONTEXT_SOURCE_DRIFT", cid, "A retained comment disappeared")
        elif current == original:
            continue
        elif cid in canonical and current["body"] == canonical[cid]["body"]:
            # Updating a body may change updatedAt, but never authorship/thread provenance.
            immutable = set(original) - {"body", "updatedAt"}
            if any(current.get(k) != original[k] for k in immutable):
                stop("CONTEXT_SOURCE_DRIFT", cid, "Canonical metadata changed")
            updated.add(cid)
        else:
            stop("CONTEXT_SOURCE_DRIFT", cid, "An original changed; rearchive and reapprove")
    archive = payload.get("archive")
    if sha256_digest(archive) != plan["archive_hash"]:
        if updated or set(originals) - live.keys():
            stop(
                "CONTEXT_ARCHIVE_UNVERIFIED",
                plan["archive_key"],
                "Recover the exact archive before any further mutation",
            )
        if sha256_digest(archive) != plan["previous_archive_hash"]:
            stop("CONTEXT_SOURCE_DRIFT", plan["archive_key"], "Archive changed; reapprove")
        return {
            "action": "save-archive",
            "key": plan["archive_key"],
            "value": plan["archive"],
            "expected_hash": plan["previous_archive_hash"],
        }
    for cid, summary in canonical.items():
        if cid not in live:
            stop("CONTEXT_SOURCE_DRIFT", cid, "Canonical comment disappeared")
        if live[cid]["body"] != summary["body"]:
            return {
                "action": "save-comment",
                "id": cid,
                "body": summary["body"],
                "expected_hash": sha256_digest(live[cid]),
            }
    for cid in plan["delete_ids"]:
        if cid in live:
            return {
                "action": "delete-comment",
                "id": cid,
                "expected_hash": sha256_digest(live[cid]),
            }
    return {
        "action": "complete",
        "operation_id": plan["operation_id"],
        "archive_hash": plan["archive_hash"],
        "remaining_ids": sorted(live),
        "verification": "fresh inventory matches archive and one canonical comment per selected type",
    }


def _slot_index(kind: str) -> int:
    return SLOT_ORDER.index(kind)


def read_slots(payload: dict[str, Any]) -> dict[str, Any]:
    """Project the managed comment layout so a coordinator can locate a slot without guessing."""
    task_id = payload["task_id"]
    _require(isinstance(task_id, str) and bool(task_id), "Missing task_id")
    comments = _comments(payload)
    slots: dict[str, dict[str, Any]] = {}
    duplicates: dict[str, list[str]] = {}
    for cid, row in comments.items():
        match = re.search(MARKER_PATTERN, row["body"], re.S)
        if match is None:
            continue
        marker = json.loads(match.group(1))
        if marker.get("task_id") != task_id or marker.get("type") not in TYPES:
            continue
        kind = marker["type"]
        if kind in slots:
            duplicates.setdefault(kind, [slots[kind]["comment_id"]]).append(cid)
            continue
        slots[kind] = {
            "comment_id": cid,
            "revision": marker.get("revision", 1),
            "body_hash": sha256_digest(row["body"]),
            "slot_index": _slot_index(kind),
            "updated_at": row["updatedAt"],
        }
    managed_ids = {slot["comment_id"] for slot in slots.values()}
    unmanaged = sorted(cid for cid in comments if cid not in managed_ids)
    return {
        "schema_version": 1,
        "task_id": task_id,
        "slot_order": list(SLOT_ORDER),
        "slots": {kind: slots[kind] for kind in SLOT_ORDER if kind in slots},
        "unmanaged_comment_ids": unmanaged,
        "duplicate_slots": {k: sorted(v) for k, v in duplicates.items()},
    }


def slot_plan(payload: dict[str, Any]) -> dict[str, Any]:
    """Bind one in-place slot update, or the first create, instead of appending a new comment."""
    task_id = payload["task_id"]
    kind = payload["type"]
    _require(kind in TYPES, f"type must be one of {sorted(TYPES)}")
    _require(
        isinstance(payload.get("revised_at"), str) and bool(payload["revised_at"]),
        "revised_at must be a caller-supplied timestamp",
    )
    body = payload["body"]
    _require(isinstance(body, str) and bool(body.strip()), "Slot body cannot be empty")
    layout = read_slots(payload)
    if kind in layout["duplicate_slots"]:
        stop(
            "TASK_SLOT_AMBIGUOUS",
            layout["duplicate_slots"][kind],
            "Run task checkpoint to consolidate this type before updating its slot",
        )
    limit = integer(
        payload.get("max_history_entries", DEFAULT_HISTORY_ENTRIES),
        "max_history_entries",
        minimum=1,
    )
    comments = _comments(payload)
    body, _ = _strip_managed(body, task_id, kind)
    _require(bool(body.strip()), "Slot body cannot contain only managed trailers")

    current = layout["slots"].get(kind)
    history: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    revision = 1
    if current is not None:
        row = comments[current["comment_id"]]
        prior_body, prior_marker = _strip_managed(row["body"], task_id, kind)
        prior_history = list((prior_marker or {}).get("history", []))
        revision = int((prior_marker or {}).get("revision", 1)) + 1
        first_line = next((ln.strip() for ln in prior_body.splitlines() if ln.strip()), "")
        # Keep the superseded state legible without letting the comment grow without bound; the
        # exact prior bodies stay recoverable from the task archive.
        prior_history.append(
            {
                "revision": revision - 1,
                "revised_at": row["updatedAt"],
                "body_hash": sha256_digest(prior_body),
                "summary": first_line[:200],
            }
        )
        history = prior_history[-limit:]
        previous = {
            "comment_id": current["comment_id"],
            "revision": revision - 1,
            "body_hash": current["body_hash"],
            "expected_hash": sha256_digest(row),
        }

    marker = {
        "schema_version": 2,
        "task_id": task_id,
        "type": kind,
        "slot_index": _slot_index(kind),
        "revision": revision,
        "history": history,
    }
    if payload.get("archive") is not None:
        marker["archive"] = payload["archive"]
    rendered = body.rstrip()
    if history:
        lines = [
            f"- r{entry['revision']} · {entry['revised_at']} · {entry['summary']}"
            for entry in reversed(history)
        ]
        rendered += (
            "\n\n"
            + HISTORY_START
            + "\n_Superseded revisions_\n"
            + "\n".join(lines)
            + "\n"
            + HISTORY_END
        )
    content = (
        rendered
        + "\n\n<!-- linear-spanks:task-comment "
        + json.dumps(marker, sort_keys=True)
        + " -->"
    )
    enforce_measurement(content, payload.get("default_tokens", 12000))
    result = {
        "schema_version": 1,
        "command": "task comment-slot",
        "policy_hash": _BUDGET.get().binding,
        "task_id": task_id,
        "type": kind,
        "slot_index": _slot_index(kind),
        "action": "update-comment" if current is not None else "create-comment",
        "comment_id": current["comment_id"] if current is not None else None,
        "body": content,
        "revision": revision,
        "previous": previous,
        "written_fields": ["body"],
        "slots": layout["slots"],
        "measurement": measurement(content),
    }
    result["plan_hash"] = sha256_digest(result)
    return result
