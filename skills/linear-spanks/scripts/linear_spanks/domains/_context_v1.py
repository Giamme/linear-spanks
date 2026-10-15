"""Versioned project capsule, rollover, context, and scan checkpoint semantics."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..contracts.legacy import (
    command_by_name,
    execution_contract,
    parse_rfc3339,
    project_epoch_contract,
    repository_scan_contract,
)
from ._routing_v1 import validate_context_usage
from ._state_v1 import require_sha256, require_unique_text_list
from .execution import execution_envelope


def validate_project_capsule(payload: dict[str, Any]) -> dict[str, Any]:
    contract = project_epoch_contract()
    capsule = contract["capsule"]
    required = set(capsule["required_fields"])
    if set(payload) != required:
        raise ValueError("project capsule fields are incomplete")
    if payload["schema_version"] != contract["schema_version"]:
        raise ValueError("project capsule schema_version is invalid")
    for field in ("project_id", "label", "body", "next_command"):
        if not isinstance(payload[field], str) or not payload[field].strip():
            raise ValueError(f"project capsule {field} must be non-empty text")
    if (
        not isinstance(payload["project_revision"], int)
        or isinstance(payload["project_revision"], bool)
        or payload["project_revision"] < 0
    ):
        raise ValueError("project capsule project_revision must be non-negative")
    parse_rfc3339(payload["generated_at"])
    require_sha256(payload["source_snapshot_hash"], "project capsule source_snapshot_hash")

    body_bytes = len(payload["body"].encode("utf-8"))
    if body_bytes > capsule["max_body_bytes"]:
        raise ValueError(
            "CONTEXT_OVERFLOW: project capsule "
            f"max_capsule_bytes={body_bytes} > {capsule['max_body_bytes']}"
        )
    positions = [payload["body"].find(heading) for heading in capsule["required_headings"]]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise ValueError("project capsule required headings are missing or out of order")

    batches = payload["batches"]
    inventory = capsule["inventory"]
    if not isinstance(batches, list):
        raise ValueError("project capsule batches must be a list")
    if len(batches) > inventory["max_batches"]:
        raise ValueError(
            "CONTEXT_OVERFLOW: project capsule "
            f"max_inventory_batches={len(batches)} > {inventory['max_batches']}"
        )
    batch_ids: set[str] = set()
    batched_sources: list[str] = []
    for batch in batches:
        if not isinstance(batch, dict) or set(batch) != set(capsule["batch_fields"]):
            raise ValueError("project capsule batch fields are incomplete")
        batch_id = batch["batch_id"]
        if not isinstance(batch_id, str) or not batch_id or batch_id in batch_ids:
            raise ValueError("project capsule batch_id must be unique non-empty text")
        batch_ids.add(batch_id)
        for field, limit in (
            ("compact_rows", "max_compact_rows_per_batch"),
            ("full_entities", "max_full_entities_per_batch"),
        ):
            value = batch[field]
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"project capsule batch {field} must be non-negative")
            if value > inventory[limit]:
                raise ValueError(
                    f"CONTEXT_OVERFLOW: project capsule {limit}={value} > {inventory[limit]}"
                )
        sources = require_unique_text_list(batch["source_ids"], "batch source_ids")
        batched_sources.extend(sources)
    if len(batched_sources) != len(set(batched_sources)):
        raise ValueError("project capsule source IDs must appear in exactly one batch")

    coverage = payload["coverage"]
    if not isinstance(coverage, dict) or set(coverage) != set(capsule["coverage_fields"]):
        raise ValueError("project capsule coverage fields are incomplete")
    expected = set(
        require_unique_text_list(coverage["expected_source_ids"], "coverage expected_source_ids")
    )
    covered = set(
        require_unique_text_list(coverage["covered_source_ids"], "coverage covered_source_ids")
    )
    exclusions = coverage["excluded_sources"]
    if not isinstance(exclusions, list):
        raise ValueError("coverage excluded_sources must be a list")
    excluded: set[str] = set()
    for exclusion in exclusions:
        if not isinstance(exclusion, dict) or set(exclusion) != set(capsule["exclusion_fields"]):
            raise ValueError("project capsule exclusion fields are incomplete")
        source_id = exclusion["source_id"]
        reason = exclusion["reason"]
        if (
            not isinstance(source_id, str)
            or not source_id
            or source_id in excluded
            or not isinstance(reason, str)
            or not reason.strip()
        ):
            raise ValueError("project capsule exclusions require unique IDs and reasons")
        excluded.add(source_id)
    if covered != set(batched_sources):
        raise ValueError("project capsule covered sources do not reconcile with batches")
    if covered & excluded or expected != covered | excluded:
        raise ValueError("project capsule coverage does not reconcile with expected sources")
    return {
        "project_id": payload["project_id"],
        "project_revision": payload["project_revision"],
        "body_bytes": body_bytes,
        "batches": len(batches),
        "covered_sources": len(covered),
        "excluded_sources": len(excluded),
        "status": "valid",
    }


def validate_rollover_transition(current: str, target: str) -> str:
    transitions = project_epoch_contract()["rollover"]["transitions"]
    if current not in transitions:
        raise ValueError(f"unknown project rollover phase: {current}")
    if target not in transitions[current]:
        raise ValueError(f"project rollover phase {current} does not allow {target}")
    return target


def validate_rollover_receipt(
    payload: dict[str, Any],
    expected_source_revision: int | None = None,
    expected_source_snapshot_hash: str | None = None,
    expected_approved_plan_hash: str | None = None,
) -> dict[str, Any]:
    contract = project_epoch_contract()
    rollover = contract["rollover"]
    if set(payload) != set(rollover["required_fields"]):
        raise ValueError("project rollover receipt fields are incomplete")
    if payload["schema_version"] != contract["schema_version"]:
        raise ValueError("project rollover receipt schema_version is invalid")
    for field in ("run_id", "next_release", "next_command"):
        if not isinstance(payload[field], str) or not payload[field].strip():
            raise ValueError(f"project rollover {field} must be non-empty text")
    phase = payload["phase"]
    if phase not in rollover["phases"]:
        raise ValueError(f"unknown project rollover phase: {phase}")
    phase_index = rollover["phases"].index(phase)
    parse_rfc3339(payload["updated_at"])
    source_hash = require_sha256(
        payload["source_snapshot_hash"], "project rollover source_snapshot_hash"
    )

    def validate_project(value: Any, field: str) -> dict[str, Any]:
        if not isinstance(value, dict) or set(value) != set(rollover["project_fields"]):
            raise ValueError(f"project rollover {field} fields are incomplete")
        if not isinstance(value["project_id"], str) or not value["project_id"]:
            raise ValueError(f"project rollover {field} project_id is invalid")
        if (
            not isinstance(value["revision"], int)
            or isinstance(value["revision"], bool)
            or value["revision"] < 0
        ):
            raise ValueError(f"project rollover {field} revision is invalid")
        if not isinstance(value["status"], str) or not value["status"]:
            raise ValueError(f"project rollover {field} status is invalid")
        return value

    source = validate_project(payload["source_project"], "source_project")
    if expected_source_revision is not None and source["revision"] != expected_source_revision:
        raise ValueError("ROLLOVER_DRIFT: source project revision changed")
    if expected_source_snapshot_hash is not None and source_hash != expected_source_snapshot_hash:
        raise ValueError("ROLLOVER_DRIFT: source snapshot changed")

    plan_hash = payload["approved_plan_hash"]
    if plan_hash is not None:
        require_sha256(plan_hash, "project rollover approved_plan_hash")
    if phase_index >= rollover["phases"].index("preview") and plan_hash is None:
        raise ValueError("project rollover approved_plan_hash is required for preview")
    if expected_approved_plan_hash is not None and plan_hash != expected_approved_plan_hash:
        raise ValueError("ROLLOVER_DRIFT: approved rollover plan changed")

    initiative = payload["initiative"]
    if not isinstance(initiative, dict) or set(initiative) != set(rollover["initiative_fields"]):
        raise ValueError("project rollover initiative fields are incomplete")
    for field in (
        "source_initiative_id",
        "requested_initiative_id",
        "successor_initiative_id",
        "warning",
    ):
        value = initiative[field]
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError(f"project rollover initiative {field} is invalid")
    desired_initiative = initiative["requested_initiative_id"] or initiative["source_initiative_id"]
    read_backs = require_unique_text_list(payload["read_back_ids"], "read_back_ids")
    require_unique_text_list(payload["applied_operation_ids"], "applied_operation_ids")
    unresolved = require_unique_text_list(
        payload["unresolved_source_items"], "unresolved_source_items"
    )

    successor = payload["successor_project"]
    successor_required = phase_index >= rollover["phases"].index("successor-created")
    if successor_required:
        successor = validate_project(successor, "successor_project")
        if successor["project_id"] == source["project_id"]:
            raise ValueError("project rollover successor must differ from the source project")
        if successor["project_id"] not in read_backs:
            raise ValueError("project rollover successor project was not read back")
        if initiative["successor_initiative_id"] != desired_initiative:
            raise ValueError(
                "project rollover successor Initiative does not match the resolved target"
            )
        if desired_initiative is None and not initiative["warning"]:
            raise ValueError("project rollover without an Initiative requires a warning")
    elif successor is not None:
        raise ValueError("project rollover successor_project must be null before creation")
    elif initiative["successor_initiative_id"] is not None:
        raise ValueError("project rollover cannot claim Initiative inheritance before creation")

    capsule = payload["capsule"]
    if phase_index >= rollover["phases"].index("preview"):
        if not isinstance(capsule, dict) or set(capsule) != set(rollover["capsule_fields"]):
            raise ValueError("project rollover capsule fields are incomplete")
        document_id = capsule["document_id"]
        if document_id is not None and (not isinstance(document_id, str) or not document_id):
            raise ValueError("project rollover capsule document_id is invalid")
        if (
            not isinstance(capsule["revision"], int)
            or isinstance(capsule["revision"], bool)
            or capsule["revision"] < 0
        ):
            raise ValueError("project rollover capsule revision is invalid")
        require_sha256(capsule["content_hash"], "project rollover capsule content_hash")
        if (
            require_sha256(
                capsule["source_snapshot_hash"],
                "project rollover capsule source_snapshot_hash",
            )
            != source_hash
        ):
            raise ValueError("ROLLOVER_DRIFT: capsule source snapshot changed")
        if capsule["status"] not in rollover["capsule_statuses"]:
            raise ValueError("project rollover capsule status is invalid")
        if successor_required and (document_id is None or document_id not in read_backs):
            raise ValueError("project rollover capsule was not persisted and read back")
    elif capsule is not None:
        raise ValueError("project rollover capsule must be null during inventory")

    roadmap = payload["roadmap_items"]
    if not isinstance(roadmap, list):
        raise ValueError("project rollover roadmap_items must be a list")
    if phase_index >= rollover["phases"].index("preview") and not (
        rollover["min_roadmap_items"] <= len(roadmap) <= rollover["max_roadmap_items"]
    ):
        raise ValueError("project rollover roadmap must contain three to seven items")
    roadmap_created = phase_index >= rollover["phases"].index("roadmap-created")
    proposal_ids: set[str] = set()
    milestone_ids: set[str] = set()
    for item in roadmap:
        if not isinstance(item, dict) or set(item) != set(rollover["roadmap_item_fields"]):
            raise ValueError("project rollover roadmap item fields are incomplete")
        if (
            not isinstance(item["proposal_id"], str)
            or not item["proposal_id"]
            or item["proposal_id"] in proposal_ids
        ):
            raise ValueError("project rollover roadmap proposal_id is invalid")
        proposal_ids.add(item["proposal_id"])
        if not isinstance(item["objective"], str) or not item["objective"].strip():
            raise ValueError("project rollover roadmap objective is invalid")
        milestone_id = item["successor_milestone_id"]
        if roadmap_created:
            if (
                not isinstance(milestone_id, str)
                or not milestone_id
                or milestone_id in milestone_ids
                or item["read_back"] is not True
                or milestone_id not in read_backs
            ):
                raise ValueError("project rollover roadmap item was not created and read back")
            milestone_ids.add(milestone_id)
        elif milestone_id is not None or item["read_back"] is not False:
            raise ValueError("project rollover preview cannot claim roadmap persistence")

    carryovers = payload["carryovers"]
    if not isinstance(carryovers, list):
        raise ValueError("project rollover carryovers must be a list")
    carryovers_created = phase_index >= rollover["phases"].index("carryover-created")
    carryover_sources: set[str] = set()
    carryover_successors: set[str] = set()
    for item in carryovers:
        if not isinstance(item, dict) or set(item) != set(rollover["carryover_fields"]):
            raise ValueError("project rollover carryover fields are incomplete")
        if (
            not isinstance(item["source_issue_id"], str)
            or not item["source_issue_id"]
            or not isinstance(item["source_revision"], int)
            or isinstance(item["source_revision"], bool)
            or item["source_revision"] < 0
            or item["source_issue_id"] in carryover_sources
        ):
            raise ValueError("project rollover carryover source identity is invalid")
        carryover_sources.add(item["source_issue_id"])
        successor_issue_id = item["successor_issue_id"]
        if carryovers_created:
            if (
                not isinstance(successor_issue_id, str)
                or not successor_issue_id
                or successor_issue_id in carryover_successors
                or item["successor_status"] != rollover["successor_issue_status"]
                or item["provenance_linked"] is not True
                or item["read_back"] is not True
                or successor_issue_id not in read_backs
            ):
                raise ValueError("project rollover carryover was not recreated safely")
            carryover_successors.add(successor_issue_id)
        elif any(
            value is not None and value is not False
            for value in (
                successor_issue_id,
                item["successor_status"],
                item["provenance_linked"],
                item["read_back"],
            )
        ):
            raise ValueError("project rollover preview cannot claim carryover persistence")

    def validate_dispositions(
        values: Any, fields_key: str, allowed_key: str, identity: str
    ) -> dict[str, dict[str, Any]]:
        if not isinstance(values, list):
            raise ValueError(f"project rollover {identity} dispositions must be a list")
        source_resolved = phase_index >= rollover["phases"].index("source-resolved")
        by_id: dict[str, dict[str, Any]] = {}
        for item in values:
            if not isinstance(item, dict) or set(item) != set(rollover[fields_key]):
                raise ValueError(f"project rollover {identity} disposition fields are incomplete")
            source_id = item[identity]
            if not isinstance(source_id, str) or not source_id or source_id in by_id:
                raise ValueError(f"project rollover {identity} disposition ID is invalid")
            by_id[source_id] = item
            if item["disposition"] not in rollover[allowed_key]:
                raise ValueError(f"project rollover {identity} disposition is invalid")
            if not isinstance(item["approved"], bool) or not isinstance(item["resolved"], bool):
                raise ValueError(f"project rollover {identity} disposition flags are invalid")
            if source_resolved and (
                item["approved"] is not True
                or item["resolved"] is not True
                or source_id not in read_backs
            ):
                raise ValueError(f"project rollover {identity} disposition is unresolved")
        return by_id

    milestone_dispositions = validate_dispositions(
        payload["milestone_dispositions"],
        "milestone_disposition_fields",
        "milestone_dispositions",
        "source_milestone_id",
    )
    issue_dispositions = validate_dispositions(
        payload["issue_dispositions"],
        "issue_disposition_fields",
        "issue_dispositions",
        "source_issue_id",
    )

    if not carryover_sources.issubset(issue_dispositions):
        raise ValueError("project rollover carryovers are missing source dispositions")
    unresolved_dispositions = {
        source_id
        for dispositions in (milestone_dispositions, issue_dispositions)
        for source_id, item in dispositions.items()
        if not item["approved"] or not item["resolved"]
    }
    if set(unresolved) != unresolved_dispositions:
        raise ValueError("project rollover unresolved items do not reconcile with dispositions")

    if phase_index >= rollover["phases"].index("source-resolved") and unresolved:
        raise ValueError("project rollover cannot resolve the source with unresolved items")
    if phase == rollover["terminal_phase"]:
        if source["status"] != rollover["completed_project_status"]:
            raise ValueError("project rollover final source project must be Completed")
        if source["project_id"] not in read_backs:
            raise ValueError("project rollover final source project was not read back")
        if capsule["status"] != "finalized":
            raise ValueError("project rollover final capsule must be finalized")
    elif source["status"] == rollover["completed_project_status"]:
        raise ValueError("project rollover cannot complete the source before finalization")

    return {
        "run_id": payload["run_id"],
        "phase": phase,
        "source_project_id": source["project_id"],
        "successor_project_id": (successor["project_id"] if isinstance(successor, dict) else None),
        "roadmap_items": len(roadmap),
        "carryovers": len(carryovers),
        "unresolved_source_items": len(unresolved),
        "status": "valid",
    }


def measure_context_packet(
    name: str,
    payload: dict[str, Any],
    scope: str = "command",
    scan_tier: str | None = None,
) -> dict[str, Any]:
    if set(payload) != {"items", "metrics"}:
        raise ValueError("context packet requires exactly items and metrics")
    items = payload["items"]
    metrics = payload["metrics"]
    if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
        raise ValueError("context packet items must be text")
    if not isinstance(metrics, dict) or not all(
        isinstance(key, str)
        and isinstance(value, list)
        and all(isinstance(item, str) for item in value)
        for key, value in metrics.items()
    ):
        raise ValueError("context packet metrics must map names to measured text items")
    from .context import measurement

    measured = measurement(payload)
    estimated_tokens = measured["estimated_tokens"]
    envelope = execution_envelope(name, scan_tier)
    if scope == "command":
        context = envelope["context"]
        measurements = {
            key: (
                "utf8_bytes" if key in {"max_raw_log_characters", "max_capsule_bytes"} else "count"
            )
            for key in context
            if key not in {"max_input_tokens", "profile"}
        }
    elif scope == "planner":
        context = envelope.get("orchestration", {}).get("planner", {}).get("context")
        measurements = {
            key: "utf8_bytes" if key == "max_raw_log_characters" else "count"
            for key in context or {}
            if key != "max_input_tokens"
        }
    elif scope == "repository":
        scan = envelope.get("repository_scan", {})
        context = scan.get("context")
        measurements = scan.get("metric_measurements", {})
    else:
        raise ValueError(f"unknown context scope: {scope}")
    if not isinstance(context, dict):
        raise ValueError(f"command {name} has no planner context")
    required_metrics = set(context) - {"max_input_tokens", "profile"}
    if set(metrics) != required_metrics:
        missing = sorted(required_metrics - set(metrics))
        extra = sorted(set(metrics) - required_metrics)
        raise ValueError(f"context packet metric mismatch; missing={missing}, extra={extra}")

    def measure(metric_items: list[str], measurement: str) -> int:
        if measurement == "count":
            return len(metric_items)
        if measurement == "utf8_bytes":
            return sum(len(item.encode("utf-8")) for item in metric_items)
        if measurement == "tokens":
            return sum((len(item.encode("utf-8")) + 3) // 4 for item in metric_items)
        raise ValueError(f"unknown metric measurement: {measurement}")

    measured_metrics = {
        key: measure(metric_items, measurements[key]) for key, metric_items in metrics.items()
    }
    result = validate_context_usage(
        name,
        estimated_tokens,
        [f"{key}={value}" for key, value in sorted(measured_metrics.items())],
        scope,
        scan_tier,
    )
    return {**result, "measurement": measured}


def validate_repository_checkpoint(
    payload: dict[str, Any],
    expected_source_revision: str | None = None,
    checkpoint_path: Path | None = None,
    drift_classification: str | None = None,
) -> dict[str, Any]:
    contract = repository_scan_contract()
    required_fields = set(contract["checkpoint"]["required_fields"])
    if set(payload) != required_fields:
        missing = sorted(required_fields - set(payload))
        extra = sorted(set(payload) - required_fields)
        raise ValueError(f"repository checkpoint field mismatch; missing={missing}, extra={extra}")
    if payload["schema_version"] != contract["schema_version"]:
        raise ValueError("unsupported repository checkpoint schema_version")
    for field in ("run_id", "repository_root", "source_revision", "next_command"):
        if not isinstance(payload[field], str) or not payload[field].strip():
            raise ValueError(f"repository checkpoint {field} must be non-empty text")
    repository_root = Path(payload["repository_root"])
    if not repository_root.is_absolute():
        raise ValueError("repository checkpoint repository_root must be absolute")
    if repository_root.is_symlink() or not repository_root.is_dir():
        raise ValueError(
            "repository checkpoint repository_root must be an existing non-symlink directory"
        )
    if checkpoint_path is not None:
        if checkpoint_path.is_symlink():
            raise ValueError("repository checkpoint path must not be a symlink")
        resolved_root = repository_root.resolve()
        resolved_checkpoint = checkpoint_path.resolve()
        if not resolved_checkpoint.is_relative_to(resolved_root):
            raise ValueError("repository checkpoint must remain inside the repository")
    command = command_by_name(payload["command"])
    configuration = execution_contract()["commands"][command["name"]]
    if "repository_scan" not in configuration:
        raise ValueError(f"command {command['name']} does not support repository checkpoints")
    tier = payload["scan_tier"]
    if tier not in contract["profiles"]:
        raise ValueError(f"unknown repository scan tier: {tier}")
    if payload["stage"] not in contract["stages"]:
        raise ValueError(f"unknown repository checkpoint stage: {payload['stage']}")
    fingerprint = payload["repository_fingerprint"]
    if not isinstance(fingerprint, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", fingerprint):
        raise ValueError("repository_fingerprint must be a canonical sha256 value")
    if drift_classification is not None and drift_classification not in {
        "valid",
        "safe-refresh",
        "material",
    }:
        raise ValueError("repository checkpoint drift classification is invalid")
    trace_source_revision_changed = (
        expected_source_revision is not None
        and payload["source_revision"] != expected_source_revision
    )
    if trace_source_revision_changed and drift_classification != "valid":
        raise ValueError(
            f"REPOSITORY_DRIFT: checkpoint revision {payload['source_revision']} "
            f"!= current revision {expected_source_revision}"
        )

    batch_fields = ("completed_batch_ids", "remaining_batch_ids")
    for field in batch_fields:
        values = payload[field]
        if not isinstance(values, list) or not all(
            isinstance(value, str) and value for value in values
        ):
            raise ValueError(f"repository checkpoint {field} must contain batch IDs")
        if len(values) != len(set(values)):
            raise ValueError(f"repository checkpoint {field} contains duplicate batch IDs")
    completed = set(payload["completed_batch_ids"])
    remaining = set(payload["remaining_batch_ids"])
    if completed & remaining:
        raise ValueError("repository checkpoint batch IDs cannot be completed and remaining")
    if len(completed | remaining) > contract["profiles"][tier]["max_batches"]:
        raise ValueError("CONTEXT_OVERFLOW: repository checkpoint exceeds max_batches")

    coverage = payload["coverage"]
    coverage_fields = set(contract["checkpoint"]["coverage_fields"])
    if not isinstance(coverage, dict) or set(coverage) != coverage_fields:
        raise ValueError("repository checkpoint coverage fields are incomplete")
    if not all(
        isinstance(value, int) and not isinstance(value, bool) and value >= 0
        for value in coverage.values()
    ):
        raise ValueError("repository checkpoint coverage values must be non-negative integers")
    if not coverage["analyzed_files"] <= coverage["selected_files"] <= coverage["eligible_files"]:
        raise ValueError("repository checkpoint file coverage is inconsistent")
    from .context import effective_limits

    profile = effective_limits(contract["profiles"][tier])
    if coverage["selected_files"] > profile["max_repository_files"]:
        raise ValueError("CONTEXT_OVERFLOW: selected files exceed the repository scan tier")
    if coverage["selected_source_bytes"] > profile["max_source_bytes"]:
        raise ValueError("CONTEXT_OVERFLOW: selected bytes exceed the repository scan tier")

    capsules = payload["capsules"]
    if not isinstance(capsules, list):
        raise ValueError("repository checkpoint capsules must be a list")
    capsule_fields = set(contract["evidence_capsule"]["required_fields"])
    confidence_values = set(contract["evidence_capsule"]["confidence_values"])
    capsule_ids: set[str] = set()
    for capsule in capsules:
        if not isinstance(capsule, dict) or set(capsule) != capsule_fields:
            raise ValueError("repository evidence capsule fields are incomplete")
        for field in ("capsule_id", "module"):
            if not isinstance(capsule[field], str) or not capsule[field].strip():
                raise ValueError(f"repository evidence capsule {field} must be non-empty text")
        if capsule["capsule_id"] in capsule_ids:
            raise ValueError("repository checkpoint has duplicate capsule IDs")
        capsule_ids.add(capsule["capsule_id"])
        if capsule["confidence"] not in confidence_values:
            raise ValueError("repository evidence capsule has invalid confidence")
        hashes = capsule["source_hashes"]
        if (
            not isinstance(hashes, list)
            or not hashes
            or not all(
                isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value)
                for value in hashes
            )
        ):
            raise ValueError("repository evidence capsule source_hashes are invalid")
        for field in capsule_fields - {"capsule_id", "module", "confidence", "source_hashes"}:
            values = capsule[field]
            if not isinstance(values, list) or not all(
                isinstance(value, str) and value for value in values
            ):
                raise ValueError(f"repository evidence capsule {field} must be a text list")
    capsule_tokens = sum(
        (len(json.dumps(capsule, sort_keys=True).encode("utf-8")) + 3) // 4 for capsule in capsules
    )
    if capsule_tokens > profile["max_capsule_tokens"]:
        raise ValueError("CONTEXT_OVERFLOW: evidence capsules exceed the repository scan tier")

    completion_findings = payload["completion_findings"]
    if not isinstance(completion_findings, list):
        raise ValueError("repository checkpoint completion_findings must be a list")
    completion_fields = set(contract["completion_finding"]["required_fields"])
    classifications = set(contract["completion_classifications"])
    for finding in completion_findings:
        if not isinstance(finding, dict) or set(finding) != completion_fields:
            raise ValueError("repository completion finding fields are incomplete")
        if not isinstance(finding["outcome"], str) or not finding["outcome"].strip():
            raise ValueError("repository completion finding outcome must be non-empty text")
        if finding["classification"] not in classifications:
            raise ValueError("repository completion finding has invalid classification")
        if finding["confidence"] not in confidence_values:
            raise ValueError("repository completion finding has invalid confidence")
        for field in ("evidence_pointers", "verification_evidence"):
            values = finding[field]
            if not isinstance(values, list) or not all(
                isinstance(value, str) and value for value in values
            ):
                raise ValueError(f"repository completion finding {field} must be a text list")
    return {
        "command": command["name"],
        "run_id": payload["run_id"],
        "scan_tier": tier,
        "stage": payload["stage"],
        "source_revision": payload["source_revision"],
        "trace_source_revision_changed": trace_source_revision_changed,
        "completed_batches": len(completed),
        "remaining_batches": len(remaining),
        "capsules": len(capsules),
        "completion_findings": len(completion_findings),
        "coverage": coverage,
        "status": "valid",
    }
