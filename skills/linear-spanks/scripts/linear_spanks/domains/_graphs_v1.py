"""Versioned dependency-graph, footprint, and wave semantics."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..contracts.legacy import parallel_execution_contract, parse_rfc3339
from ..core.legacy_constants import DEPENDENCY_GRAPH_MARKER_RE
from ._state_v1 import canonical_digest, validate_sha256


def validate_execution_footprint(payload: Any, task_id: str) -> dict[str, Any]:
    contract = parallel_execution_contract()["execution_footprint"]
    required = set(contract["required_fields"])
    if not isinstance(payload, dict) or set(payload) != required:
        raise ValueError(f"task {task_id} execution footprint fields are incomplete")
    repository = payload["repository"]
    scopes = payload["write_scopes"]
    resources = payload["exclusive_resources"]
    if not isinstance(repository, str) or not repository:
        raise ValueError(f"task {task_id} footprint repository must be non-empty text")
    if not isinstance(scopes, list) or not all(isinstance(path, str) and path for path in scopes):
        raise ValueError(f"task {task_id} write_scopes must be a text list")
    if scopes != sorted(set(scopes)):
        raise ValueError(f"task {task_id} write_scopes must be sorted and unique")
    for path in scopes:
        normalized = Path(path)
        if path != "*" and (normalized.is_absolute() or ".." in normalized.parts):
            raise ValueError(f"task {task_id} write scope must be repository-relative: {path}")
        if path != "*" and (path in {".", ""} or normalized.as_posix() != path):
            raise ValueError(f"task {task_id} write scope must be canonical: {path}")
    if not isinstance(resources, list) or not all(
        isinstance(resource, str) and resource for resource in resources
    ):
        raise ValueError(f"task {task_id} exclusive_resources must be a text list")
    if resources != sorted(set(resources)):
        raise ValueError(f"task {task_id} exclusive_resources must be sorted and unique")
    if not isinstance(payload["parallel_safe"], bool):
        raise ValueError(f"task {task_id} parallel_safe must be a boolean")
    if (
        not isinstance(payload["serialization_rationale"], str)
        or not payload["serialization_rationale"].strip()
    ):
        raise ValueError(f"task {task_id} serialization_rationale must be non-empty text")
    return payload


def paths_overlap(left: str, right: str) -> bool:
    if "*" in {left, right}:
        return True
    left_path = left.rstrip("/")
    right_path = right.rstrip("/")
    return (
        left_path == right_path
        or left_path.startswith(right_path + "/")
        or right_path.startswith(left_path + "/")
    )


def footprints_conflict(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if left["repository"] != right["repository"]:
        return True
    if not left["parallel_safe"] or not right["parallel_safe"]:
        return True
    if not left["write_scopes"] or not right["write_scopes"]:
        return True
    if set(left["exclusive_resources"]) & set(right["exclusive_resources"]):
        return True
    return any(
        paths_overlap(left_scope, right_scope)
        for left_scope in left["write_scopes"]
        for right_scope in right["write_scopes"]
    )


def normalized_edges(edges: Any, task_ids: set[str], field: str) -> list[dict[str, str]]:
    if not isinstance(edges, list):
        raise ValueError(f"{field} must be a list")
    normalized: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for edge in edges:
        if not isinstance(edge, dict) or set(edge) != {"from", "to"}:
            raise ValueError(f"{field} edges require exactly from and to")
        source, target = edge["from"], edge["to"]
        if source not in task_ids or target not in task_ids:
            raise ValueError(f"{field} edge references an unknown task")
        if source == target:
            raise ValueError(f"{field} cannot contain self-edges")
        pair = (source, target)
        if pair in seen:
            raise ValueError(f"{field} contains duplicate edge {source}->{target}")
        seen.add(pair)
        normalized.append({"from": source, "to": target})
    return sorted(normalized, key=lambda item: (item["from"], item["to"]))


def derive_serialization_edges(tasks: list[dict[str, Any]]) -> list[dict[str, str]]:
    edges: list[dict[str, str]] = []
    for index, left in enumerate(tasks):
        for right in tasks[index + 1 :]:
            if footprints_conflict(left["execution_footprint"], right["execution_footprint"]):
                edges.append({"from": left["id"], "to": right["id"]})
    return edges


def derive_waves(task_ids: list[str], edges: list[dict[str, str]]) -> list[list[str]]:
    order = {task_id: index for index, task_id in enumerate(task_ids)}
    incoming = dict.fromkeys(task_ids, 0)
    outgoing: dict[str, list[str]] = {task_id: [] for task_id in task_ids}
    for edge in edges:
        incoming[edge["to"]] += 1
        outgoing[edge["from"]].append(edge["to"])
    remaining = set(task_ids)
    waves: list[list[str]] = []
    while remaining:
        wave = sorted(
            (task_id for task_id in remaining if incoming[task_id] == 0),
            key=order.__getitem__,
        )
        if not wave:
            raise ValueError("DEPENDENCY_GRAPH_CYCLE: graph contains a dependency cycle")
        waves.append(wave)
        for task_id in wave:
            remaining.remove(task_id)
            for target in outgoing[task_id]:
                incoming[target] -= 1
    return waves


def build_dependency_graph(payload: dict[str, Any]) -> dict[str, Any]:
    required = {
        "project_id",
        "milestone_id",
        "graph_revision",
        "workflow_revision",
        "source_hash",
        "review_status",
        "tasks",
        "hard_edges",
        "generated_at",
    }
    if set(payload) != required:
        raise ValueError("dependency graph build input fields are incomplete")
    for field in ("project_id", "milestone_id"):
        if not isinstance(payload[field], str) or not payload[field]:
            raise ValueError(f"dependency graph {field} must be non-empty text")
    for field in ("graph_revision", "workflow_revision"):
        if (
            not isinstance(payload[field], int)
            or isinstance(payload[field], bool)
            or payload[field] < 0
        ):
            raise ValueError(f"dependency graph {field} must be a non-negative integer")
    validate_sha256(payload["source_hash"], "dependency graph source_hash")
    parse_rfc3339(payload["generated_at"])
    contract = parallel_execution_contract()["graph"]
    if payload["review_status"] not in contract["review_statuses"]:
        raise ValueError("dependency graph review_status is invalid")
    tasks = payload["tasks"]
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("dependency graph requires at least one task")
    expected_task_fields = set(contract["task_fields"])
    task_ids: list[str] = []
    normalized_tasks: list[dict[str, Any]] = []
    for task in tasks:
        if not isinstance(task, dict) or set(task) != expected_task_fields:
            raise ValueError("dependency graph task fields are incomplete")
        task_id = task["id"]
        if (
            not isinstance(task_id, str)
            or re.fullmatch(r"[A-Za-z0-9._-]+", task_id) is None
            or task_id in task_ids
        ):
            raise ValueError(f"invalid or duplicated dependency graph task: {task_id}")
        if (
            not isinstance(task["plan_revision"], int)
            or isinstance(task["plan_revision"], bool)
            or task["plan_revision"] < 0
        ):
            raise ValueError(f"task {task_id} plan_revision must be non-negative")
        validate_execution_footprint(task["execution_footprint"], task_id)
        task_ids.append(task_id)
        normalized_tasks.append(task)
    if payload["review_status"] == "reviewed" and any(
        task["plan_revision"] == 0 for task in normalized_tasks
    ):
        raise ValueError("reviewed dependency graph requires every task to have a current plan")
    hard_edges = normalized_edges(payload["hard_edges"], set(task_ids), "hard_edges")
    serialization_edges = normalized_edges(
        derive_serialization_edges(normalized_tasks), set(task_ids), "serialization_edges"
    )
    edge_pairs = {(edge["from"], edge["to"]) for edge in hard_edges}
    serialization_edges = [
        edge for edge in serialization_edges if (edge["from"], edge["to"]) not in edge_pairs
    ]
    waves = derive_waves(task_ids, [*hard_edges, *serialization_edges])
    graph = {
        "schema_version": 1,
        **payload,
        "serialization_edges": serialization_edges,
        "waves": waves,
    }
    graph["graph_hash"] = canonical_digest(
        {key: value for key, value in graph.items() if key not in {"graph_hash", "generated_at"}}
    )
    return graph


def validate_dependency_graph(payload: dict[str, Any]) -> dict[str, Any]:
    contract = parallel_execution_contract()["graph"]
    if set(payload) != set(contract["required_fields"]):
        raise ValueError("dependency graph marker fields are incomplete")
    build_input = {
        key: payload[key]
        for key in (
            "project_id",
            "milestone_id",
            "graph_revision",
            "workflow_revision",
            "source_hash",
            "review_status",
            "tasks",
            "hard_edges",
            "generated_at",
        )
    }
    rebuilt = build_dependency_graph(build_input)
    validate_sha256(payload["graph_hash"], "dependency graph graph_hash")
    if payload != rebuilt:
        raise ValueError("DEPENDENCY_GRAPH_DRIFT: stored graph does not match its sources")
    return payload


def render_dependency_graph(payload: dict[str, Any]) -> str:
    graph = validate_dependency_graph(payload)
    lines = ["## Dependency graph", "", "```mermaid", "graph TD"]
    aliases = {task["id"]: f"n{index}" for index, task in enumerate(graph["tasks"])}
    for task in graph["tasks"]:
        lines.append(f'  {aliases[task["id"]]}["{task["id"]}"]')
    for edge in graph["hard_edges"]:
        lines.append(f"  {aliases[edge['from']]} --> {aliases[edge['to']]}")
    for edge in graph["serialization_edges"]:
        lines.append(f"  {aliases[edge['from']]} -. serialize .-> {aliases[edge['to']]}")
    lines.extend(["```", "", "Candidate waves:"])
    for index, wave in enumerate(graph["waves"], start=1):
        lines.append(f"{index}. {', '.join(wave)}")
    marker = json.dumps(graph, sort_keys=True, separators=(",", ":"))
    lines.extend(["", f"<!-- linear-spanks:dependency-graph {marker} -->"])
    return "\n".join(lines) + "\n"


def parse_dependency_graph(text: str) -> dict[str, Any]:
    matches = DEPENDENCY_GRAPH_MARKER_RE.findall(text)
    if len(matches) != 1:
        raise ValueError(f"expected exactly one dependency graph marker, found {len(matches)}")
    return validate_dependency_graph(json.loads(matches[0]))


def upsert_dependency_graph(description: str, graph: dict[str, Any]) -> str:
    rendered = render_dependency_graph(graph).rstrip("\n")
    matches = list(DEPENDENCY_GRAPH_MARKER_RE.finditer(description))
    if len(matches) > 1:
        raise ValueError(f"expected at most one dependency graph marker, found {len(matches)}")
    if not matches:
        return description.rstrip() + "\n\n" + rendered + "\n"
    marker = matches[0]
    heading_start = description.rfind("## Dependency graph", 0, marker.start())
    if heading_start < 0:
        raise ValueError("dependency graph marker is missing its managed heading")
    suffix_start = marker.end()
    if suffix_start < len(description) and description[suffix_start] == "\n":
        suffix_start += 1
    prefix = description[:heading_start].rstrip()
    suffix = description[suffix_start:].lstrip("\n")
    updated = prefix + "\n\n" + rendered + "\n"
    if suffix:
        updated += "\n" + suffix
    return updated


def select_parallel_wave(
    payload: dict[str, Any], max_parallel: int, capacity: int
) -> dict[str, Any]:
    legacy_fields = {"graph", "live_statuses", "excluded_issue_ids"}
    incremental_fields = {*legacy_fields, "review_coverage_hashes"}
    if frozenset(payload) not in {frozenset(legacy_fields), frozenset(incremental_fields)}:
        raise ValueError(
            "wave selection requires graph, live_statuses, excluded_issue_ids, "
            "and optional review_coverage_hashes"
        )
    graph = payload["graph"]
    if not isinstance(graph, dict):
        raise ValueError("wave selection graph must be an object")
    validate_dependency_graph(graph)
    if graph["review_status"] not in {"reviewed", "incremental-reviewed"}:
        raise ValueError("implement-wave requires a reviewed dependency graph")
    if graph["review_status"] == "incremental-reviewed":
        coverage = payload.get("review_coverage_hashes")
        if not isinstance(coverage, dict):
            raise ValueError("incremental-reviewed wave requires current task review coverage")
        unknown = set(coverage) - {task["id"] for task in graph["tasks"]}
        if unknown:
            raise ValueError("review coverage contains unknown graph tasks")
        for task_id, digest in coverage.items():
            validate_sha256(digest, f"review coverage {task_id}")
    limits = parallel_execution_contract()["waves"]
    if (
        max_parallel < limits["minimum_parallel_tasks"]
        or max_parallel > limits["hard_max_parallel"]
    ):
        raise ValueError("max_parallel must be between 2 and 8")
    if capacity < limits["minimum_parallel_tasks"]:
        raise ValueError("PARALLEL_CAPACITY_UNAVAILABLE: harness capacity is below two")
    task_ids = {task["id"] for task in graph["tasks"]}
    status_by_id = payload["live_statuses"]
    if (
        not isinstance(status_by_id, dict)
        or set(status_by_id) != task_ids
        or not all(isinstance(status, str) and status for status in status_by_id.values())
    ):
        raise ValueError("wave selection live_statuses must cover every graph task")
    excluded = payload["excluded_issue_ids"]
    if not isinstance(excluded, list) or not all(
        isinstance(task_id, str) and task_id in task_ids for task_id in excluded
    ):
        raise ValueError("wave selection excluded_issue_ids are invalid")
    excluded_ids = set(excluded)
    plan_revision_by_id = {task["id"]: task["plan_revision"] for task in graph["tasks"]}
    predecessors: dict[str, set[str]] = {task_id: set() for task_id in status_by_id}
    for edge in [*graph["hard_edges"], *graph["serialization_edges"]]:
        predecessors[edge["to"]].add(edge["from"])
    active = {
        task_id
        for task_id, status in status_by_id.items()
        if status in {"Backlog", "In Progress"}
        and plan_revision_by_id[task_id] > 0
        and task_id not in excluded_ids
        and all(status_by_id[predecessor] == "Done" for predecessor in predecessors[task_id])
    }
    for wave_number, wave in enumerate(graph["waves"], start=1):
        eligible = [task_id for task_id in wave if task_id in active]
        selected = eligible[: min(max_parallel, capacity)]
        if len(selected) >= limits["minimum_parallel_tasks"]:
            if graph["review_status"] == "incremental-reviewed" and not set(selected) <= set(
                payload["review_coverage_hashes"]
            ):
                raise ValueError(
                    "MILESTONE_REVIEW_DRIFT: selected wave lacks current review coverage"
                )
            return {
                "wave_number": wave_number,
                "selected": selected,
                "requested_parallelism": max_parallel,
                "effective_parallelism": len(selected),
                "assurance": limits["assurance"],
                "fixed_frontier": True,
            }
    raise ValueError("NO_PARALLEL_WAVE: use implement-next for a single ready task")


def validate_wave_receipt(payload: dict[str, Any]) -> dict[str, Any]:
    contract = parallel_execution_contract()["wave_receipt"]
    if set(payload) != set(contract["required_fields"]):
        raise ValueError("wave receipt fields are incomplete")
    for field in ("wave_id", "milestone_id", "parent_branch", "baseline_head", "worktree_root"):
        if not isinstance(payload[field], str) or not payload[field]:
            raise ValueError(f"wave receipt {field} must be non-empty text")
    if re.fullmatch(r"[A-Za-z0-9._-]+", payload["wave_id"]) is None:
        raise ValueError("wave receipt wave_id must be a branch-safe slug")
    worktree_root = Path(payload["worktree_root"])
    if (
        not worktree_root.is_absolute()
        or worktree_root == Path("/")
        or ".." in worktree_root.parts
        or worktree_root.as_posix() != payload["worktree_root"]
    ):
        raise ValueError("wave receipt worktree_root must be a safe absolute path")
    if re.fullmatch(r"[0-9a-f]{40,64}", payload["baseline_head"]) is None:
        raise ValueError("wave receipt baseline_head must be a commit SHA")
    validate_sha256(payload["graph_hash"], "wave receipt graph_hash")
    validate_sha256(payload["source_hash"], "wave receipt source_hash")
    for field in ("created_at", "updated_at"):
        parse_rfc3339(payload[field])
    if parse_rfc3339(payload["updated_at"]) < parse_rfc3339(payload["created_at"]):
        raise ValueError("wave receipt updated_at cannot precede created_at")
    if payload["state"] not in contract["states"]:
        raise ValueError("wave receipt state is invalid")
    requested, effective = payload["requested_parallelism"], payload["effective_parallelism"]
    if not isinstance(requested, int) or isinstance(requested, bool) or not 2 <= requested <= 8:
        raise ValueError("wave receipt requested_parallelism must be between 2 and 8")
    if (
        not isinstance(effective, int)
        or isinstance(effective, bool)
        or not 2 <= effective <= requested
    ):
        raise ValueError("wave receipt effective_parallelism is invalid")
    tasks = payload["tasks"]
    if not isinstance(tasks, list) or len(tasks) != effective:
        raise ValueError("wave receipt tasks must match effective_parallelism")
    expected_task_fields = set(contract["task_fields"])
    branches: set[str] = set()
    worktrees: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict) or set(task) != expected_task_fields:
            raise ValueError("wave receipt task fields are incomplete")
        for field in ("issue_id", "branch", "worktree", "claim_status", "verification_status"):
            if not isinstance(task[field], str) or not task[field]:
                raise ValueError(f"wave receipt task {field} must be non-empty text")
        if re.fullmatch(r"[A-Za-z0-9._-]+", task["issue_id"]) is None:
            raise ValueError("wave receipt task issue_id must be a branch-safe slug")
        if task["branch"] in branches or task["worktree"] in worktrees:
            raise ValueError("wave receipt branches and worktrees must be unique")
        branches.add(task["branch"])
        worktrees.add(task["worktree"])
        expected_branch = f"linear-spanks/wave-{payload['wave_id']}/{task['issue_id']}"
        if task["branch"] != expected_branch:
            raise ValueError("wave receipt task branch does not match the wave branch pattern")
        worktree_path = Path(task["worktree"])
        if (
            not worktree_path.is_absolute()
            or worktree_path == Path("/")
            or ".." in worktree_path.parts
            or worktree_path.as_posix() != task["worktree"]
        ):
            raise ValueError("wave receipt task worktree must be a safe absolute path")
        if worktree_root not in worktree_path.parents:
            raise ValueError("wave receipt task worktree must be below worktree_root")
        if (
            not isinstance(task["plan_revision"], int)
            or isinstance(task["plan_revision"], bool)
            or task["plan_revision"] < 1
        ):
            raise ValueError("wave receipt task plan_revision must be positive")
        if task["execution_status"] not in contract["execution_statuses"]:
            raise ValueError("wave receipt task execution_status is invalid")
        if task["integration_status"] not in contract["integration_statuses"]:
            raise ValueError("wave receipt task integration_status is invalid")
        if task["commit_sha"] is not None and (
            not isinstance(task["commit_sha"], str)
            or re.fullmatch(r"[0-9a-f]{40,64}", task["commit_sha"]) is None
        ):
            raise ValueError("wave receipt task commit_sha is invalid")
        if task["execution_status"] == "verified" and (
            task["commit_sha"] is None or task["verification_status"] != "passed"
        ):
            raise ValueError("verified wave task requires a commit and passed verification")
    if payload["state"] == "integrated" and any(
        task["integration_status"] != "integrated" for task in tasks
    ):
        raise ValueError("integrated wave receipt requires every task to be integrated")
    return payload
