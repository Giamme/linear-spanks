"""Versioned bounded milestone-review and drift semantics."""

from __future__ import annotations

from typing import Any

from ..contracts.legacy import (
    milestone_review_contract,
    milestone_runtime_contract,
    parallel_execution_contract,
    parse_rfc3339,
)
from ..core.legacy_validation import (
    _require_exact_object_fields,
    _require_nonempty_text,
    _require_positive_revision,
)
from ._graphs_v1 import validate_execution_footprint
from ._state_v1 import _validate_hash_map, canonical_digest, validate_sha256


def _validate_review_budget(
    budget: dict[str, Any],
    *,
    finalization: bool = False,
) -> dict[str, Any]:
    contract = milestone_review_contract()
    expected = set(contract["checkpoint"]["budget_fields"])
    if not isinstance(budget, dict) or set(budget) != expected:
        raise ValueError("milestone review budget fields are incomplete")
    for field in ("model_turns", "active_context_tokens", "planned_batches"):
        value = budget[field]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"milestone review {field} must be non-negative")
    if budget["planned_batches"] <= 0:
        raise ValueError("milestone review planned_batches must be positive")
    if not isinstance(budget["telemetry_available"], bool):
        raise ValueError("milestone review telemetry_available must be boolean")
    for field in ("cumulative_input_tokens", "phase_cumulative_input_tokens"):
        value = budget[field]
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool) or value < 0
        ):
            raise ValueError(f"milestone review {field} must be non-negative or null")
        if budget["telemetry_available"] and value is None:
            raise ValueError(f"milestone review {field} requires native telemetry")
        if not budget["telemetry_available"] and value is not None:
            raise ValueError(f"milestone review {field} must be null without telemetry")
    from .context import check_capacity, effective_limits

    invocation = effective_limits(contract["invocation_budget"])
    check_capacity(budget["active_context_tokens"])
    exceeded = []
    if budget["model_turns"] > invocation["max_model_turns"]:
        exceeded.append("model_turns")
    if budget["active_context_tokens"] > invocation["max_active_context_tokens"]:
        exceeded.append("active_context_tokens")
    if (
        budget["cumulative_input_tokens"] is not None
        and budget["cumulative_input_tokens"] > invocation["max_cumulative_input_tokens"]
    ):
        exceeded.append("cumulative_input_tokens")
    phase = contract["phase_budget"]
    phase_cap = (
        phase["tokens_per_planned_batch"] * budget["planned_batches"] + phase["finalization_tokens"]
    )
    if (
        budget["phase_cumulative_input_tokens"] is not None
        and budget["phase_cumulative_input_tokens"] > phase_cap
    ):
        exceeded.append("phase_cumulative_input_tokens")
    if exceeded:
        raise ValueError("CONTEXT_OVERFLOW for milestone review: " + ", ".join(exceeded))
    threshold = (
        invocation["max_active_context_tokens"] * invocation["stop_new_reads_percent"] // 100
    )
    return {
        "phase_cap_tokens": phase_cap,
        "token_status": "verified" if budget["telemetry_available"] else "unverified",
        "new_reads_allowed": (budget["active_context_tokens"] < threshold and not finalization),
    }


def finding_is_blocking(finding: dict[str, Any]) -> bool:
    if "classification" not in finding:
        return True
    if finding["classification"] not in {"blocking", "suggestion"}:
        raise ValueError("finding classification is invalid")
    _require_nonempty_text(finding.get("evidence"), "finding evidence")
    if finding["classification"] == "blocking":
        _require_nonempty_text(finding.get("requirement"), "blocking finding requirement")
        return True
    if finding.get("requirement") is not None:
        raise ValueError("a requirement violation must be classified as blocking")
    return False


def validate_milestone_review_checkpoint(
    payload: dict[str, Any],
    *,
    current_session_id: str | None = None,
    expected_marker_revision: int | None = None,
    expected_matrix_hash: str | None = None,
    expected_dependency_graph_hash: str | None = None,
    expected_coverage_hash: str | None = None,
    current_source_revisions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = milestone_review_contract()
    required = set(contract["checkpoint"]["required_fields"])
    if not isinstance(payload, dict) or set(payload) != required:
        raise ValueError("milestone review checkpoint fields are incomplete")
    if payload["schema_version"] != contract["schema_version"]:
        raise ValueError("unsupported milestone review checkpoint schema_version")
    for field in (
        "receipt_id",
        "review_id",
        "session_id",
        "project_id",
        "milestone_id",
        "entry_command",
        "mode",
        "idempotency_key",
        "status",
        "timestamp",
        "next_command",
    ):
        _require_nonempty_text(payload[field], field)
    if payload["entry_command"] not in contract["commands"]:
        raise ValueError("milestone review entry_command is invalid")
    if payload["mode"] not in contract["modes"]:
        raise ValueError("milestone review mode is invalid")
    if payload["status"] not in contract["checkpoint"]["statuses"]:
        raise ValueError("milestone review status is invalid")
    parse_rfc3339(payload["timestamp"])
    for field in ("matrix_hash", "dependency_graph_hash", "coverage_hash"):
        validate_sha256(payload[field], field)
    for field in ("marker_revision", "batch_index"):
        value = payload[field]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"milestone review {field} must be non-negative")
    if payload["batch_index"] <= 0:
        raise ValueError("milestone review batch_index must be positive")
    for field in (
        "ordered_task_ids",
        "covered_task_ids",
        "remaining_task_ids",
        "changed_task_ids",
        "adjacent_task_ids",
        "unchanged_task_ids",
    ):
        values = payload[field]
        if (
            not isinstance(values, list)
            or len(values) != len(set(values))
            or not all(isinstance(value, str) and value for value in values)
        ):
            raise ValueError(f"milestone review {field} must be a unique text list")
    ordered = payload["ordered_task_ids"]
    covered = payload["covered_task_ids"]
    remaining = payload["remaining_task_ids"]
    if not ordered or set(covered) & set(remaining) or covered + remaining != ordered:
        raise ValueError("milestone review coverage must preserve the ordered partition")
    reviewed_categories = payload["changed_task_ids"] + payload["adjacent_task_ids"]
    categories = reviewed_categories + payload["unchanged_task_ids"]
    if (
        len(categories) != len(set(categories))
        or set(reviewed_categories) != set(ordered)
        or set(payload["unchanged_task_ids"]) & set(ordered)
    ):
        raise ValueError("milestone review changed/adjacent/unchanged partition is invalid")
    maximum = contract["batching"]["max_tasks_per_batch"]
    planned_batches = max(1, (len(covered) + len(remaining) + maximum - 1) // maximum)
    if payload["batch_index"] > planned_batches:
        raise ValueError("milestone review batch_index exceeds planned batches")
    if len(covered) > payload["batch_index"] * maximum:
        raise ValueError("CONTEXT_OVERFLOW: milestone review batch covers too many tasks")
    if payload["status"] == "ready-to-finalize" and remaining:
        raise ValueError("ready-to-finalize requires complete task coverage")
    for field in ("task_revisions", "plan_revisions"):
        revisions = payload[field]
        if not isinstance(revisions, dict) or set(revisions) != set(categories):
            raise ValueError(f"milestone review {field} must cover reviewed and unchanged tasks")
        if not all(
            isinstance(value, int) and not isinstance(value, bool) and value >= 0
            for value in revisions.values()
        ):
            raise ValueError(f"milestone review {field} contains invalid revisions")
    findings = payload["cumulative_findings"]
    finding_fields = set(contract["checkpoint"]["finding_fields"])
    if not isinstance(findings, list):
        raise ValueError("milestone review findings must be a list")
    finding_ids: set[str] = set()
    for finding in findings:
        if not isinstance(finding, dict) or set(finding) not in (
            finding_fields,
            finding_fields | {"classification", "requirement", "evidence"},
        ):
            raise ValueError("milestone review finding fields are incomplete")
        finding_is_blocking(finding)
        finding_id = _require_nonempty_text(finding["finding_id"], "finding_id")
        _require_nonempty_text(finding["severity"], "finding severity")
        _require_nonempty_text(finding["summary"], "finding summary")
        if finding_id in finding_ids:
            raise ValueError("milestone review finding IDs must be unique")
        finding_ids.add(finding_id)
        if (
            not isinstance(finding["task_ids"], list)
            or not finding["task_ids"]
            or not set(finding["task_ids"]) <= set(covered)
        ):
            raise ValueError("milestone review finding tasks must be covered")
        if not isinstance(finding["source_revisions"], dict) or not set(finding["task_ids"]) <= set(
            finding["source_revisions"]
        ):
            raise ValueError("milestone review finding source revisions are incomplete")
    if payload["batch_index"] == 1 and payload["previous_receipt_id"] is not None:
        raise ValueError("first milestone review batch cannot have a previous receipt")
    if payload["batch_index"] > 1 and not payload["previous_receipt_id"]:
        raise ValueError("resumed milestone review requires receipt lineage")
    if payload["checkpoint_read_back"] is not True:
        raise ValueError("milestone review checkpoint requires durable read-back")
    budget = _validate_review_budget(payload["budget"])
    if current_session_id is not None and current_session_id == payload["session_id"]:
        raise ValueError("FRESH_CONTEXT_REQUIRED: resume in a new agent context")
    drift_checks = (
        (expected_marker_revision, payload["marker_revision"], "marker revision"),
        (expected_matrix_hash, payload["matrix_hash"], "task matrix"),
        (
            expected_dependency_graph_hash,
            payload["dependency_graph_hash"],
            "dependency graph",
        ),
        (expected_coverage_hash, payload["coverage_hash"], "review coverage"),
    )
    for expected, actual, label in drift_checks:
        if expected is not None and expected != actual:
            raise ValueError(f"MILESTONE_REVIEW_DRIFT: {label} changed")
    if current_source_revisions is not None and current_source_revisions != {
        "task_revisions": payload["task_revisions"],
        "plan_revisions": payload["plan_revisions"],
    }:
        raise ValueError("MILESTONE_REVIEW_DRIFT: source revisions changed")
    return {
        "receipt_id": payload["receipt_id"],
        "review_id": payload["review_id"],
        "mode": payload["mode"],
        "batch_index": payload["batch_index"],
        "covered_tasks": len(covered),
        "remaining_tasks": len(remaining),
        "changed_tasks": len(payload["changed_task_ids"]),
        "adjacent_tasks": len(payload["adjacent_task_ids"]),
        "unchanged_tasks": len(payload["unchanged_task_ids"]),
        "status": payload["status"],
        "next_command": payload["next_command"],
        **budget,
    }


def validate_milestone_review_finalization(payload: dict[str, Any]) -> dict[str, Any]:
    contract = milestone_review_contract()
    if not isinstance(payload, dict) or set(payload) != set(
        contract["finalization"]["required_fields"]
    ):
        raise ValueError("milestone review finalization fields are incomplete")
    source_revisions = payload["current_source_revisions"]
    if not isinstance(source_revisions, dict):
        raise ValueError("current_source_revisions must be an object")
    validated = validate_milestone_review_checkpoint(
        payload["checkpoint"],
        expected_marker_revision=payload["current_marker_revision"],
        expected_matrix_hash=payload["current_matrix_hash"],
        expected_dependency_graph_hash=payload["current_dependency_graph_hash"],
        expected_coverage_hash=payload["current_coverage_hash"],
        current_source_revisions=source_revisions,
    )
    if payload["checkpoint"]["status"] != "ready-to-finalize":
        raise ValueError("milestone review finalization requires complete coverage")
    final_budget = {
        "model_turns": payload["model_turns"],
        "active_context_tokens": payload["active_context_tokens"],
        "cumulative_input_tokens": payload["cumulative_input_tokens"],
        "phase_cumulative_input_tokens": payload["phase_cumulative_input_tokens"],
        "planned_batches": payload["checkpoint"]["budget"]["planned_batches"],
        "telemetry_available": payload["telemetry_available"],
    }
    budget = _validate_review_budget(final_budget, finalization=True)
    for field in ("findings_persisted", "marker_advanced", "durable_read_back"):
        if payload[field] is not True:
            raise ValueError(f"milestone review finalization requires {field}")
    _require_nonempty_text(payload["next_command"], "next_command")
    return {
        **validated,
        "status": "finalized",
        "next_command": payload["next_command"],
        **budget,
    }


def validate_incremental_plan(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate the revisioned bindings that make task-local drift decisions possible."""
    contract = milestone_runtime_contract()["plan"]
    required = {
        "schema_version",
        "task_id",
        "plan_revision",
        "trace_source_head",
        "target_file_hashes",
        "consumed_surface_hashes",
        "dependency_receipt_hashes",
        "acceptance_contract_hash",
        "execution_footprint",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise ValueError("incremental plan fields are incomplete")
    if payload["schema_version"] != contract["schema_version"]:
        raise ValueError("incremental plan schema_version is unsupported")
    _require_nonempty_text(payload["task_id"], "task_id")
    _require_positive_revision(payload["plan_revision"], "plan_revision")
    _require_nonempty_text(payload["trace_source_head"], "trace_source_head")
    target_hashes = _validate_hash_map(payload["target_file_hashes"], "target_file_hashes")
    surfaces = _validate_hash_map(payload["consumed_surface_hashes"], "consumed_surface_hashes")
    dependencies = payload["dependency_receipt_hashes"]
    if not isinstance(dependencies, dict):
        raise ValueError("dependency_receipt_hashes must be an object")
    validated_dependencies: dict[str, dict[str, str]] = {}
    for task_id, binding in dependencies.items():
        if (
            not isinstance(task_id, str)
            or not task_id
            or not isinstance(binding, dict)
            or set(binding) != {"receipt_hash", "output_hash"}
        ):
            raise ValueError("dependency receipt bindings are invalid")
        validated_dependencies[task_id] = {
            name: validate_sha256(digest, f"dependency {task_id} {name}")
            for name, digest in binding.items()
        }
    validate_sha256(payload["acceptance_contract_hash"], "acceptance_contract_hash")
    footprint = validate_execution_footprint(payload["execution_footprint"], payload["task_id"])
    return {
        **payload,
        "target_file_hashes": target_hashes,
        "consumed_surface_hashes": surfaces,
        "dependency_receipt_hashes": validated_dependencies,
        "execution_footprint": footprint,
        "binding_hash": canonical_digest(payload),
    }


def classify_plan_drift(payload: dict[str, Any]) -> dict[str, Any]:
    wrapper = _require_exact_object_fields(
        payload,
        ["plan", "current", "changed_plan_fields"],
        "incremental plan drift input",
    )
    plan = validate_incremental_plan(wrapper["plan"])
    current = validate_incremental_plan(wrapper["current"])
    if current["task_id"] != plan["task_id"]:
        raise ValueError("incremental plan drift task_id changed")
    changed_fields = wrapper["changed_plan_fields"]
    if not isinstance(changed_fields, list) or not all(
        isinstance(field, str) and field for field in changed_fields
    ):
        raise ValueError("changed_plan_fields must be a text list")
    policy = milestone_runtime_contract()["plan"]
    material_reasons: list[str] = []
    safe_reasons: list[str] = []
    if plan["acceptance_contract_hash"] != current["acceptance_contract_hash"]:
        material_reasons.append("acceptance_contract_hash")
    if plan["consumed_surface_hashes"] != current["consumed_surface_hashes"]:
        material_reasons.append("consumed_surface_hashes")
    old_dependencies = plan["dependency_receipt_hashes"]
    new_dependencies = current["dependency_receipt_hashes"]
    if set(old_dependencies) != set(new_dependencies):
        material_reasons.append("dependencies")
    else:
        for task_id in old_dependencies:
            if old_dependencies[task_id]["output_hash"] != new_dependencies[task_id]["output_hash"]:
                material_reasons.append(f"dependency_output:{task_id}")
            elif (
                old_dependencies[task_id]["receipt_hash"]
                != new_dependencies[task_id]["receipt_hash"]
            ):
                safe_reasons.append(f"dependency_receipt:{task_id}")
    if plan["target_file_hashes"] != current["target_file_hashes"]:
        safe_reasons.append("target_file_hashes")
    if plan["execution_footprint"] != current["execution_footprint"]:
        safe_reasons.append("execution_footprint")
    material_reasons.extend(field for field in changed_fields if field in policy["material_fields"])
    safe_reasons.extend(field for field in changed_fields if field in policy["safe_refresh_fields"])
    unknown = sorted(
        set(changed_fields) - set(policy["material_fields"]) - set(policy["safe_refresh_fields"])
    )
    if unknown:
        material_reasons.extend(f"unclassified:{field}" for field in unknown)
    drift_class = "material" if material_reasons else ("safe-refresh" if safe_reasons else "valid")
    return {
        "task_id": plan["task_id"],
        "classification": drift_class,
        "material_reasons": sorted(set(material_reasons)),
        "safe_refresh_reasons": sorted(set(safe_reasons)),
        "trace_source_head_changed": (plan["trace_source_head"] != current["trace_source_head"]),
        "automatic_refresh_allowed": drift_class == "safe-refresh",
        "approval_required": drift_class == "material",
    }


def _footprints_overlap(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if left["repository"] != right["repository"]:
        return False
    left_scopes = set(left["write_scopes"])
    right_scopes = set(right["write_scopes"])
    if "*" in left_scopes or "*" in right_scopes:
        return True
    for first in left_scopes:
        for second in right_scopes:
            if first == second or first.startswith(second + "/") or second.startswith(first + "/"):
                return True
    return bool(set(left["exclusive_resources"]) & set(right["exclusive_resources"]))


def calculate_incremental_review_coverage(payload: dict[str, Any]) -> dict[str, Any]:
    changes = payload.get("plan_changes")
    payload = {key: value for key, value in payload.items() if key != "plan_changes"}
    wrapper = _require_exact_object_fields(
        payload, ["tasks", "changed_task_ids", "mode"], "review coverage input"
    )
    if wrapper["mode"] not in milestone_review_contract()["modes"]:
        raise ValueError("review coverage mode is invalid")
    tasks = wrapper["tasks"]
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("review coverage requires tasks")
    by_id: dict[str, dict[str, Any]] = {}
    dependencies: dict[str, set[str]] = {}
    for task in tasks:
        task = _require_exact_object_fields(
            task,
            ["id", "dependencies", "execution_footprint", "final_sink"],
            "review coverage task",
        )
        task_id = _require_nonempty_text(task["id"], "task id")
        if task_id in by_id:
            raise ValueError("review coverage task IDs must be unique")
        if not isinstance(task["dependencies"], list) or not all(
            isinstance(item, str) and item for item in task["dependencies"]
        ):
            raise ValueError("review coverage dependencies must be a text list")
        if not isinstance(task["final_sink"], bool):
            raise ValueError("review coverage final_sink must be boolean")
        task["execution_footprint"] = validate_execution_footprint(
            task["execution_footprint"], task_id
        )
        by_id[task_id] = task
        dependencies[task_id] = set(task["dependencies"])
    if any(not values <= set(by_id) for values in dependencies.values()):
        raise ValueError("review coverage contains an unknown dependency")
    changed = wrapper["changed_task_ids"]
    if not isinstance(changed, list) or len(changed) != len(set(changed)):
        raise ValueError("changed_task_ids must be a unique list")
    if not all(isinstance(task_id, str) and task_id in by_id for task_id in changed):
        raise ValueError("changed_task_ids contains an unknown task")
    changed_set = set(changed)
    material_set = set(changed_set)
    if changes is not None:
        if not isinstance(changes, dict) or set(changes) != changed_set:
            raise ValueError("plan_changes must bind every changed task")
        material_set = set()
        for task_id, change in changes.items():
            classification = classify_plan_drift(change)
            if classification["task_id"] != task_id:
                raise ValueError("review change binding belongs to another task")
            if classification["classification"] == "material":
                material_set.add(task_id)
    if wrapper["mode"] in {"legacy", "next-wave"}:
        coverage = set(by_id)
        adjacent = coverage - changed_set
    else:
        neighbours = (
            {
                task_id
                for task_id in by_id
                if task_id in set().union(*(dependencies[item] for item in material_set))
                or bool(dependencies[task_id] & material_set)
            }
            if material_set
            else set()
        )
        overlaps = {
            task_id
            for task_id, task in by_id.items()
            if task_id not in changed_set
            and any(
                _footprints_overlap(
                    task["execution_footprint"],
                    by_id[changed_id]["execution_footprint"],
                )
                for changed_id in changed_set
            )
        }
        affected = material_set | overlaps
        while True:
            expanded = affected | {task_id for task_id in by_id if dependencies[task_id] & affected}
            if expanded == affected:
                break
            affected = expanded
        sinks = {task_id for task_id in affected if by_id[task_id]["final_sink"]}
        coverage = changed_set | neighbours | overlaps | sinks
        adjacent = coverage - changed_set
    unchanged = set(by_id) - coverage
    ordered = list(by_id)
    result = {
        "mode": wrapper["mode"],
        "changed_task_ids": [task_id for task_id in ordered if task_id in changed_set],
        "adjacent_task_ids": [task_id for task_id in ordered if task_id in adjacent],
        "unchanged_task_ids": [task_id for task_id in ordered if task_id in unchanged],
        "covered_task_ids": [task_id for task_id in ordered if task_id in coverage],
        "counts": {
            "changed": len(changed_set),
            "adjacent": len(adjacent),
            "unchanged": len(unchanged),
        },
    }
    result["coverage_hash"] = canonical_digest(result)
    return result


def select_next_planning_wave(payload: dict[str, Any]) -> dict[str, Any]:
    wrapper = _require_exact_object_fields(
        payload, ["tasks", "max_parallel"], "next planning wave input"
    )
    maximum = wrapper["max_parallel"]
    if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum <= 0:
        raise ValueError("max_parallel must be a positive integer")
    hard_max = parallel_execution_contract()["waves"]["hard_max_parallel"]
    if maximum > hard_max:
        raise ValueError(f"max_parallel exceeds hard limit {hard_max}")
    tasks = wrapper["tasks"]
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("next planning wave requires tasks")
    by_id: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    required_fields = {
        "id",
        "status",
        "plan_revision",
        "dependencies",
        "dependency_statuses",
        "review_covered",
        "active_receipt",
    }
    for task in tasks:
        if not isinstance(task, dict) or set(task) != required_fields:
            raise ValueError("next planning wave task fields are incomplete")
        task_id = _require_nonempty_text(task["id"], "task id")
        if task_id in by_id:
            raise ValueError("next planning wave task IDs must be unique")
        if (
            not isinstance(task["plan_revision"], int)
            or isinstance(task["plan_revision"], bool)
            or task["plan_revision"] < 0
        ):
            raise ValueError("plan_revision must be a non-negative integer")
        if not isinstance(task["dependencies"], list):
            raise ValueError("dependencies must be a list")
        if not isinstance(task["dependency_statuses"], dict):
            raise ValueError("dependency_statuses must be an object")
        if set(task["dependencies"]) != set(task["dependency_statuses"]):
            raise ValueError("dependency statuses must cover dependencies exactly")
        by_id[task_id] = task
        order.append(task_id)
    frontier = [
        task_id
        for task_id in order
        if by_id[task_id]["status"] == "Unplanned"
        and by_id[task_id]["plan_revision"] == 0
        and by_id[task_id]["active_receipt"] is False
        and all(
            status in {"Done", "integrated"}
            for status in by_id[task_id]["dependency_statuses"].values()
        )
    ][:maximum]
    selected = []
    later = []
    for task_id in order:
        task = by_id[task_id]
        if task_id in frontier:
            selected.append(
                {
                    "id": task_id,
                    "from_status": "Unplanned",
                    "to_status": "Backlog",
                    "next_plan_revision": 1,
                    "review_covered": task["review_covered"],
                }
            )
        elif task["status"] == "Unplanned":
            later.append(
                {
                    "id": task_id,
                    "status": "Unplanned",
                    "plan_revision": 0,
                }
            )
    return {
        "selected": selected,
        "later": later,
        "frontier_exhausted": not frontier,
        "requires_review_after_planning": bool(frontier),
    }
