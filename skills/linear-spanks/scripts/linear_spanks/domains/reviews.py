"""Incremental and bounded milestone review domain."""

from __future__ import annotations

from typing import Any

from . import _reviews_v1 as legacy
from ._validation import checked


def evidence_bindings(plan: dict[str, Any]) -> dict[str, str]:
    """Material identity excludes trace HEAD and mutable execution evidence."""
    from ..core.hashing import sha256_digest

    current = incremental_plan(plan)
    return {
        "material": sha256_digest(
            {
                "task_id": current["task_id"],
                "plan_revision": current["plan_revision"],
                "acceptance": current["acceptance_contract_hash"],
                "surfaces": current["consumed_surface_hashes"],
                "dependencies": {
                    key: value["output_hash"]
                    for key, value in current["dependency_receipt_hashes"].items()
                },
            }
        ),
        "evidence": sha256_digest(
            {
                "target_file_hashes": current["target_file_hashes"],
                "execution_footprint": current["execution_footprint"],
            }
        ),
    }


def refresh_evidence(store: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """Persist a guarded evidence receipt; never rewrite the material plan."""
    from ..core.hashing import sha256_digest
    from .context import scope_key, stop, write_read_back

    source = store.read(payload["source"])
    if source is None or sha256_digest(source) != payload["expected_source_hash"]:
        stop(
            "PLAN_EVIDENCE_DRIFT",
            payload["source"],
            "Refresh source evidence within the current task",
        )
    drift = classify_drift(source)
    current = source["current"]
    binding = evidence_bindings(current)
    if (
        drift["classification"] == "material"
        or evidence_bindings(source["plan"])["material"] != binding["material"]
    ):
        stop("REPLAN_REQUIRED", drift, "Replan only the materially affected task scope")
    if payload["authorization"] != {
        "task_id": current["task_id"],
        "material_binding": binding["material"],
    }:
        stop("APPROVAL_REQUIRED", binding, "Restore authorization for the existing task scope")
    key = scope_key("task", current["task_id"], payload["project_id"]) + "/execution-evidence"
    previous = store.read(key)
    receipt = {
        "schema_version": 1,
        "task_id": current["task_id"],
        "plan_revision": current["plan_revision"],
        "bindings": binding,
        "source": payload["source"],
        "source_hash": payload["expected_source_hash"],
    }
    if previous != receipt and sha256_digest(previous) != payload["expected_receipt_hash"]:
        stop("PLAN_EVIDENCE_DRIFT", key, "Restore the current execution evidence receipt")
    if store.read(payload["source"]) != source:
        stop("PLAN_EVIDENCE_DRIFT", payload["source"], "Refresh changed sources before writing")
    write_read_back(store, key, receipt, previous)
    if store.read(payload["source"]) != source:
        stop("PLAN_EVIDENCE_DRIFT", payload["source"], "Revalidate sources before dispatch")
    return {
        "receipt": receipt,
        "read_back": True,
        "status": "unchanged" if previous == receipt else "refreshed",
    }


def prepare_refresh(payload: dict[str, Any]) -> dict[str, Any]:
    from .context import PreparedDocuments

    store = PreparedDocuments(payload["documents"])
    result = refresh_evidence(store, payload["request"])
    return {
        "result": {**result, "read_back": False},
        "writes": store.writes,
        "persistence_verified": False,
    }


def checkpoint(payload: dict[str, Any], **expected: Any) -> dict[str, Any]:
    return checked(legacy.validate_milestone_review_checkpoint, payload, **expected)


def finalize(payload: dict[str, Any]) -> dict[str, Any]:
    return checked(legacy.validate_milestone_review_finalization, payload)


def incremental_plan(payload: dict[str, Any]) -> dict[str, Any]:
    return checked(legacy.validate_incremental_plan, payload)


def classify_drift(payload: dict[str, Any]) -> dict[str, Any]:
    return checked(legacy.classify_plan_drift, payload)


def coverage(payload: dict[str, Any]) -> dict[str, Any]:
    return checked(legacy.calculate_incremental_review_coverage, payload)


def next_wave(payload: dict[str, Any]) -> dict[str, Any]:
    return checked(legacy.select_next_planning_wave, payload)


def findings(payload: dict[str, Any]) -> dict[str, Any]:
    from ._runtime_v1 import validate_milestone_findings

    return checked(validate_milestone_findings, payload)
