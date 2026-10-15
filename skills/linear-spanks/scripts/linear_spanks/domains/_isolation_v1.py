"""Versioned isolated-worktree preflight, receipt, and transition semantics."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..contracts.legacy import parallel_execution_contract, parse_rfc3339
from ._state_v1 import canonical_digest, validate_sha256
from .execution import isolation_configuration


def validate_safe_isolation_paths(
    repository_root_value: Any,
    worktree_root_value: Any,
    worktree_path_value: Any,
) -> tuple[Path, Path, Path]:
    values = {
        "repository_root": repository_root_value,
        "worktree_root": worktree_root_value,
        "worktree_path": worktree_path_value,
    }
    paths: dict[str, Path] = {}
    for field, value in values.items():
        if not isinstance(value, str) or not value:
            raise ValueError(f"ISOLATION_PREFLIGHT_FAILED: {field} is missing")
        path = Path(value)
        if (
            not path.is_absolute()
            or path == Path("/")
            or ".." in path.parts
            or path.as_posix() != value
        ):
            raise ValueError(f"ISOLATION_PREFLIGHT_FAILED: {field} must be a safe absolute path")
        paths[field] = path
    repository_root = paths["repository_root"]
    worktree_root = paths["worktree_root"]
    worktree_path = paths["worktree_path"]
    if (
        repository_root == worktree_root
        or repository_root in worktree_root.parents
        or worktree_root in repository_root.parents
    ):
        raise ValueError(
            "ISOLATION_PREFLIGHT_FAILED: worktree_root must be outside the repository tree"
        )
    if worktree_root not in worktree_path.parents:
        raise ValueError("ISOLATION_PREFLIGHT_FAILED: worktree_path must be below worktree_root")
    return repository_root, worktree_root, worktree_path


def validate_isolation_preflight(payload: dict[str, Any]) -> dict[str, Any]:
    required = {
        "command",
        "isolated_worktree",
        "milestone_stage",
        "issue_id",
        "plan_revision",
        "source_hash",
        "run_id",
        "receipt_id",
        "repository_root",
        "git_strategy_present",
        "worktree_root",
        "parent_branch",
        "parent_head",
        "parent_attached",
        "parent_clean",
        "plan_current",
        "child_branch",
        "branch_exists",
        "worktree_path",
        "worktree_path_exists",
        "active_receipts",
    }
    if set(payload) != required:
        raise ValueError("ISOLATION_PREFLIGHT_FAILED: preflight fields are incomplete")
    for field in (
        "isolated_worktree",
        "git_strategy_present",
        "parent_attached",
        "parent_clean",
        "plan_current",
        "branch_exists",
        "worktree_path_exists",
    ):
        if not isinstance(payload[field], bool):
            raise ValueError(f"ISOLATION_PREFLIGHT_FAILED: {field} must be boolean")
    configuration = isolation_configuration(
        payload["command"], payload["isolated_worktree"], payload["milestone_stage"]
    )
    if configuration is None or not configuration["enabled"] or configuration["mode"] == "always":
        raise ValueError(
            f"ISOLATION_NOT_APPLICABLE: command {payload['command']} did not enable isolation"
        )
    for field in ("issue_id", "run_id", "receipt_id", "parent_branch"):
        value = payload[field]
        if not isinstance(value, str) or not value:
            raise ValueError(f"ISOLATION_PREFLIGHT_FAILED: {field} must be non-empty text")
    for field in ("issue_id", "run_id", "receipt_id"):
        if re.fullmatch(r"[A-Za-z0-9._-]+", payload[field]) is None:
            raise ValueError(f"ISOLATION_PREFLIGHT_FAILED: {field} must be branch-safe")
    if (
        not isinstance(payload["plan_revision"], int)
        or isinstance(payload["plan_revision"], bool)
        or payload["plan_revision"] < 1
    ):
        raise ValueError("ISOLATION_PREFLIGHT_FAILED: plan_revision must be positive")
    validate_sha256(payload["source_hash"], "isolation preflight source_hash")
    if re.fullmatch(r"[0-9a-f]{40,64}", str(payload["parent_head"])) is None:
        raise ValueError("ISOLATION_PREFLIGHT_FAILED: parent_head must be a commit SHA")
    validate_safe_isolation_paths(
        payload["repository_root"], payload["worktree_root"], payload["worktree_path"]
    )
    for field, message in (
        ("git_strategy_present", ".linear-spanks-git.yml is required"),
        ("parent_attached", "parent branch must be attached"),
        ("parent_clean", "parent worktree must be clean"),
        ("plan_current", "authoritative plan must be current"),
    ):
        if payload[field] is not True:
            raise ValueError(f"ISOLATION_PREFLIGHT_FAILED: {message}")
    expected_branch = f"linear-spanks/run-{payload['run_id']}/{payload['issue_id']}"
    if payload["child_branch"] != expected_branch:
        raise ValueError(
            "ISOLATION_PREFLIGHT_FAILED: child_branch does not match the run branch pattern"
        )
    active = payload["active_receipts"]
    if not isinstance(active, list):
        raise ValueError("ISOLATION_PREFLIGHT_FAILED: active_receipts must be a list")
    matching: list[dict[str, Any]] = []
    active_states = set(parallel_execution_contract()["isolation_receipt"]["active_states"])
    for receipt in active:
        fields = {"receipt_id", "command", "issue_id", "plan_revision", "state"}
        if not isinstance(receipt, dict) or set(receipt) != fields:
            raise ValueError("ISOLATION_PREFLIGHT_FAILED: active receipt summary is invalid")
        if (
            receipt["issue_id"] == payload["issue_id"]
            and receipt["plan_revision"] == payload["plan_revision"]
            and receipt["state"] in active_states
        ):
            matching.append(receipt)
    if len(matching) > 1:
        ids = ", ".join(sorted(str(receipt["receipt_id"]) for receipt in matching))
        raise ValueError(f"ISOLATION_RECEIPT_AMBIGUOUS: {ids}")
    if matching:
        receipt = matching[0]
        if receipt["command"] != payload["command"]:
            raise ValueError(
                "ISOLATION_PREFLIGHT_FAILED: active receipt belongs to another command: "
                f"{receipt['receipt_id']}"
            )
        return {
            "status": "resume",
            "receipt_id": receipt["receipt_id"],
            "command": payload["command"],
            "issue_id": payload["issue_id"],
            "plan_revision": payload["plan_revision"],
        }
    if payload["branch_exists"] is True:
        raise ValueError("ISOLATION_PREFLIGHT_FAILED: child branch already exists")
    if payload["worktree_path_exists"] is True:
        raise ValueError("ISOLATION_PREFLIGHT_FAILED: worktree path already exists")
    return {
        "status": "prepare",
        "receipt_id": payload["receipt_id"],
        "command": payload["command"],
        "issue_id": payload["issue_id"],
        "plan_revision": payload["plan_revision"],
        "parent_branch": payload["parent_branch"],
        "baseline_head": payload["parent_head"],
        "child_branch": payload["child_branch"],
        "worktree_path": payload["worktree_path"],
    }


def validate_integration_preview(payload: Any) -> dict[str, Any]:
    fields = set(parallel_execution_contract()["single_execution"]["integration_preview_fields"])
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ValueError("isolation integration preview fields are incomplete")
    for field in ("parent_branch", "parent_head", "child_commit", "merge_command"):
        if not isinstance(payload[field], str) or not payload[field]:
            raise ValueError(f"isolation integration preview {field} must be non-empty text")
    for field in ("parent_head", "child_commit"):
        if re.fullmatch(r"[0-9a-f]{40,64}", payload[field]) is None:
            raise ValueError(f"isolation integration preview {field} must be a commit SHA")
    if "--no-ff" not in payload["merge_command"]:
        raise ValueError("isolation integration preview merge_command must use --no-ff")
    for field in ("verification_commands", "cleanup_commands", "linear_completion_writes"):
        values = payload[field]
        if (
            not isinstance(values, list)
            or not values
            or not all(isinstance(value, str) and value for value in values)
        ):
            raise ValueError(f"isolation integration preview {field} must be a text list")
    return payload


def validate_isolation_receipt(payload: dict[str, Any]) -> dict[str, Any]:
    contract = parallel_execution_contract()["isolation_receipt"]
    if set(payload) != set(contract["required_fields"]):
        raise ValueError("isolation receipt fields are incomplete")
    for field in (
        "receipt_id",
        "run_id",
        "command",
        "issue_id",
        "parent_branch",
        "repository_root",
        "worktree_root",
        "worktree_path",
        "child_branch",
    ):
        if not isinstance(payload[field], str) or not payload[field]:
            raise ValueError(f"isolation receipt {field} must be non-empty text")
    for field in ("receipt_id", "run_id", "issue_id"):
        if re.fullmatch(r"[A-Za-z0-9._-]+", payload[field]) is None:
            raise ValueError(f"isolation receipt {field} must be branch-safe")
    configuration = isolation_configuration(payload["command"], True, "start-implementation")
    if configuration is None or not configuration["enabled"] or configuration["mode"] == "always":
        raise ValueError("isolation receipt command is not isolation-capable")
    if payload["state"] not in contract["states"]:
        raise ValueError("isolation receipt state is invalid")
    if (
        not isinstance(payload["plan_revision"], int)
        or isinstance(payload["plan_revision"], bool)
        or payload["plan_revision"] < 1
    ):
        raise ValueError("isolation receipt plan_revision must be positive")
    validate_sha256(payload["source_hash"], "isolation receipt source_hash")
    if re.fullmatch(r"[0-9a-f]{40,64}", payload["baseline_head"]) is None:
        raise ValueError("isolation receipt baseline_head must be a commit SHA")
    validate_safe_isolation_paths(
        payload["repository_root"], payload["worktree_root"], payload["worktree_path"]
    )
    expected_branch = f"linear-spanks/run-{payload['run_id']}/{payload['issue_id']}"
    if payload["child_branch"] != expected_branch:
        raise ValueError("isolation receipt child_branch does not match the run branch pattern")
    if payload["child_commit"] is not None and (
        not isinstance(payload["child_commit"], str)
        or re.fullmatch(r"[0-9a-f]{40,64}", payload["child_commit"]) is None
    ):
        raise ValueError("isolation receipt child_commit must be null or a commit SHA")

    verification = payload["verification"]
    if not isinstance(verification, dict) or set(verification) != set(
        contract["verification_fields"]
    ):
        raise ValueError("isolation receipt verification fields are incomplete")
    if verification["status"] not in {"pending", "passed", "failed"}:
        raise ValueError("isolation receipt verification status is invalid")
    if not isinstance(verification["commands"], list) or not all(
        isinstance(command, str) and command for command in verification["commands"]
    ):
        raise ValueError("isolation receipt verification commands must be a text list")
    if verification["completed_at"] is not None:
        parse_rfc3339(verification["completed_at"])
    if verification["status"] == "passed" and (
        not verification["commands"] or verification["completed_at"] is None
    ):
        raise ValueError("passed isolation verification requires commands and completed_at")

    integration = payload["integration"]
    if not isinstance(integration, dict) or set(integration) != set(contract["integration_fields"]):
        raise ValueError("isolation receipt integration fields are incomplete")
    for field in ("preview_hash", "approved_preview_hash"):
        if integration[field] is not None:
            validate_sha256(integration[field], f"isolation receipt integration {field}")
    for field in ("preview_parent_head", "approved_parent_head", "integrated_head"):
        if integration[field] is not None and (
            not isinstance(integration[field], str)
            or re.fullmatch(r"[0-9a-f]{40,64}", integration[field]) is None
        ):
            raise ValueError(f"isolation receipt integration {field} is invalid")
    if integration["verification_status"] not in {"pending", "passed", "failed"}:
        raise ValueError("isolation receipt integration verification_status is invalid")

    completion = payload["completion"]
    if not isinstance(completion, dict) or set(completion) != set(contract["completion_fields"]):
        raise ValueError("isolation receipt completion fields are incomplete")
    if completion["receipt_id"] is not None and (
        not isinstance(completion["receipt_id"], str) or not completion["receipt_id"]
    ):
        raise ValueError("isolation receipt completion receipt_id is invalid")
    for field in ("receipt_persisted", "issue_done_read_back", "newly_unblocked_read_back"):
        if not isinstance(completion[field], bool):
            raise ValueError(f"isolation receipt completion {field} must be boolean")
    if completion["worktree_cleanup"] not in {"pending", "removed", "retained"}:
        raise ValueError("isolation receipt worktree_cleanup is invalid")

    failure = payload["failure"]
    if failure is not None:
        if not isinstance(failure, dict) or set(failure) != set(contract["failure_fields"]):
            raise ValueError("isolation receipt failure fields are incomplete")
        if not all(isinstance(failure[field], str) and failure[field] for field in failure):
            raise ValueError("isolation receipt failure fields must be non-empty text")
        parse_rfc3339(failure["at"])
    for field in ("created_at", "updated_at"):
        parse_rfc3339(payload[field])
    if parse_rfc3339(payload["updated_at"]) < parse_rfc3339(payload["created_at"]):
        raise ValueError("isolation receipt updated_at cannot precede created_at")
    timestamps = payload["state_timestamps"]
    if (
        not isinstance(timestamps, dict)
        or not timestamps
        or not set(timestamps).issubset(set(contract["states"]))
    ):
        raise ValueError("isolation receipt state_timestamps are invalid")
    for timestamp in timestamps.values():
        parse_rfc3339(timestamp)
    if "prepared" not in timestamps or payload["state"] not in timestamps:
        raise ValueError("isolation receipt must timestamp prepared and current states")

    committed_states = {"verified-pending-integration", "integrating", "integrated"}
    if payload["state"] in committed_states and (
        payload["child_commit"] is None or verification["status"] != "passed"
    ):
        raise ValueError("verified isolation states require a commit and passed verification")
    if payload["state"] in {"integrating", "integrated"} and (
        integration["preview_hash"] is None
        or integration["approved_preview_hash"] != integration["preview_hash"]
        or integration["approved_parent_head"] != integration["preview_parent_head"]
    ):
        raise ValueError("integrating isolation receipt requires exact preview approval")
    if payload["state"] == "integrated" and (
        integration["integrated_head"] is None
        or integration["verification_status"] != "passed"
        or completion["receipt_id"] is None
        or not completion["receipt_persisted"]
        or not completion["issue_done_read_back"]
        or not completion["newly_unblocked_read_back"]
    ):
        raise ValueError("integrated isolation receipt requires durable completion read-back")
    if payload["state"] == "failed" and failure is None:
        raise ValueError("failed isolation receipt requires failure evidence")
    if payload["state"] != "failed" and failure is not None:
        raise ValueError("non-failed isolation receipt cannot carry terminal failure evidence")
    return payload


def transition_isolation_receipt(
    receipt: dict[str, Any], request: dict[str, Any]
) -> dict[str, Any]:
    validate_isolation_receipt(receipt)
    if set(request) != {"target_state", "event", "updated_at", "current", "updates"}:
        raise ValueError("isolation transition fields are incomplete")
    target = request["target_state"]
    event = request["event"]
    if not isinstance(target, str) or not isinstance(event, str) or not event:
        raise ValueError("isolation transition target_state and event must be text")
    contract = parallel_execution_contract()["isolation_receipt"]
    if target not in contract["transitions"][receipt["state"]]:
        raise ValueError(f"invalid isolation transition: {receipt['state']} -> {target}")
    updated_at = request["updated_at"]
    parse_rfc3339(updated_at)
    if parse_rfc3339(updated_at) < parse_rfc3339(receipt["updated_at"]):
        raise ValueError("isolation transition updated_at cannot move backwards")
    current = request["current"]
    required_current = {
        "command",
        "issue_id",
        "plan_revision",
        "source_hash",
        "parent_branch",
        "parent_head",
        "child_commit",
        "child_is_ancestor_of_parent",
        "parent_clean",
        "integration_verification_passed",
        "parent_fast_forwarded",
        "completion_receipt_persisted",
        "issue_done_read_back",
        "newly_unblocked_read_back",
    }
    if not isinstance(current, dict) or set(current) != required_current:
        raise ValueError("isolation transition current fields are incomplete")
    for field in ("command", "issue_id"):
        if current[field] != receipt[field]:
            raise ValueError(f"ISOLATION_RECEIPT_DRIFT: {field} changed")
    if current["plan_revision"] != receipt["plan_revision"]:
        raise ValueError("REPLAN_REQUIRED: plan revision changed")
    validate_sha256(current["source_hash"], "isolation transition source_hash")
    if current["parent_branch"] != receipt["parent_branch"]:
        raise ValueError("ISOLATION_RECEIPT_DRIFT: parent branch changed")
    if re.fullmatch(r"[0-9a-f]{40,64}", str(current["parent_head"])) is None:
        raise ValueError("isolation transition parent_head must be a commit SHA")
    for field in (
        "child_is_ancestor_of_parent",
        "parent_clean",
        "integration_verification_passed",
        "parent_fast_forwarded",
        "completion_receipt_persisted",
        "issue_done_read_back",
        "newly_unblocked_read_back",
    ):
        if not isinstance(current[field], bool):
            raise ValueError(f"isolation transition {field} must be boolean")
    if current["child_commit"] is not None and (
        not isinstance(current["child_commit"], str)
        or re.fullmatch(r"[0-9a-f]{40,64}", current["child_commit"]) is None
    ):
        raise ValueError("isolation transition child_commit is invalid")
    if receipt["child_commit"] is not None and current["child_commit"] != receipt["child_commit"]:
        raise ValueError("ISOLATION_RECEIPT_DRIFT: child commit changed")
    updates = request["updates"]
    if not isinstance(updates, dict):
        raise ValueError("isolation transition updates must be an object")
    allowed_updates = {
        "child_commit",
        "verification",
        "integration_preview",
        "approve_preview",
        "integrated_head",
        "completion_receipt_id",
        "failure",
        "worktree_cleanup",
    }
    if not set(updates).issubset(allowed_updates):
        raise ValueError("isolation transition updates contain unsupported fields")

    result: dict[str, Any] = json.loads(json.dumps(receipt))
    if "child_commit" in updates:
        result["child_commit"] = updates["child_commit"]
    if "verification" in updates:
        result["verification"] = updates["verification"]
    if "integration_preview" in updates:
        preview = validate_integration_preview(updates["integration_preview"])
        if preview["parent_branch"] != receipt["parent_branch"]:
            raise ValueError("ISOLATION_RECEIPT_DRIFT: preview parent branch changed")
        if preview["parent_head"] != current["parent_head"]:
            raise ValueError("ISOLATION_APPROVAL_INVALIDATED: preview parent is stale")
        expected_child = updates.get("child_commit", receipt["child_commit"])
        if preview["child_commit"] != expected_child:
            raise ValueError("ISOLATION_RECEIPT_DRIFT: preview child commit changed")
        result["integration"]["preview_hash"] = canonical_digest(preview)
        result["integration"]["preview_parent_head"] = preview["parent_head"]
        result["integration"]["approved_preview_hash"] = None
        result["integration"]["approved_parent_head"] = None
    if "approve_preview" in updates:
        approved = updates["approve_preview"]
        if not isinstance(approved, dict) or set(approved) != {"preview_hash", "parent_head"}:
            raise ValueError("isolation preview approval fields are incomplete")
        if (
            approved["preview_hash"] != result["integration"]["preview_hash"]
            or approved["parent_head"] != result["integration"]["preview_parent_head"]
            or approved["parent_head"] != current["parent_head"]
        ):
            raise ValueError("ISOLATION_APPROVAL_INVALIDATED: approval does not match preview")
        result["integration"]["approved_preview_hash"] = approved["preview_hash"]
        result["integration"]["approved_parent_head"] = approved["parent_head"]
    if "failure" in updates:
        result["failure"] = updates["failure"]
    if "worktree_cleanup" in updates:
        result["completion"]["worktree_cleanup"] = updates["worktree_cleanup"]

    if target == "executing" and event != "start-executor":
        raise ValueError("prepared isolation receipt may only start-executor")
    if (
        receipt["state"] == "executing"
        and target == "verified-pending-integration"
        and (
            event != "verification-passed"
            or not {
                "child_commit",
                "verification",
                "integration_preview",
            }.issubset(updates)
        )
    ):
        raise ValueError(
            "verified-pending-integration requires commit, verification, and exact preview"
        )
    if target == "failed":
        if event not in {"executor-failed", "verification-failed", "terminal-failure"}:
            raise ValueError("failed isolation transition requires a failure event")
        if "failure" not in updates:
            raise ValueError("failed isolation transition requires failure evidence")
    if target == "verified-pending-integration" and receipt["state"] == target:
        if event not in {"refresh-preview", "approve-preview", "approval-declined"}:
            raise ValueError("pending isolation transition event is invalid")
        if event == "refresh-preview" and "integration_preview" not in updates:
            raise ValueError("refresh-preview requires an exact integration preview")
        if event == "approve-preview" and "approve_preview" not in updates:
            raise ValueError("approve-preview requires matching approval data")
        if event == "approval-declined" and updates:
            raise ValueError("declined approval must preserve the pending receipt unchanged")
    if receipt["state"] == "integrating" and target == "verified-pending-integration":
        if event not in {"parent-drift", "merge-conflict", "integration-verification-failed"}:
            raise ValueError("integration recovery event is invalid")
        if (
            current["parent_head"] != receipt["integration"]["approved_parent_head"]
            or current["parent_clean"] is not True
            or current["parent_fast_forwarded"] is not False
            or current["completion_receipt_persisted"] is not False
            or current["issue_done_read_back"] is not False
            or current["newly_unblocked_read_back"] is not False
        ):
            raise ValueError(
                "ISOLATION_INTEGRATION_ATOMICITY_FAILED: parent and Linear state must be unchanged"
            )
        result["integration"]["approved_preview_hash"] = None
        result["integration"]["approved_parent_head"] = None
        result["integration"]["verification_status"] = (
            "failed" if event == "integration-verification-failed" else "pending"
        )
    if target == "integrating":
        integration = result["integration"]
        if event != "begin-integration":
            raise ValueError("pending isolation receipt may only begin-integration")
        if current["parent_clean"] is not True:
            raise ValueError("ISOLATION_APPROVAL_INVALIDATED: parent is dirty")
        if current["parent_head"] != integration["approved_parent_head"]:
            raise ValueError(
                "ISOLATION_APPROVAL_INVALIDATED: parent advanced; render a fresh preview"
            )
        if integration["approved_preview_hash"] != integration["preview_hash"]:
            raise ValueError("ISOLATION_APPROVAL_INVALIDATED: preview is not approved")
    if target == "integrated" and receipt["state"] != "integrated":
        external = event == "recover-external-integration"
        if external and receipt["state"] != "verified-pending-integration":
            raise ValueError("external integration recovery requires a pending receipt")
        if not external and (receipt["state"] != "integrating" or event != "integration-passed"):
            raise ValueError("integrated transition requires successful integration")
        if external and current["child_is_ancestor_of_parent"] is not True:
            raise ValueError("external integration recovery requires verified ancestry")
        if not all(
            current[field]
            for field in (
                "parent_clean",
                "integration_verification_passed",
                "completion_receipt_persisted",
                "issue_done_read_back",
                "newly_unblocked_read_back",
            )
        ):
            raise ValueError(
                "integrated isolation transition requires verification and Linear read-back"
            )
        if not external and current["parent_fast_forwarded"] is not True:
            raise ValueError("integrated isolation transition requires parent fast-forward")
        if "integrated_head" not in updates or "completion_receipt_id" not in updates:
            raise ValueError("integrated isolation transition requires integration evidence")
        integrated_head = updates["integrated_head"]
        if (
            not isinstance(integrated_head, str)
            or re.fullmatch(r"[0-9a-f]{40,64}", integrated_head) is None
            or integrated_head != current["parent_head"]
        ):
            raise ValueError("integrated_head must equal the verified current parent")
        result["integration"]["integrated_head"] = integrated_head
        result["integration"]["verification_status"] = "passed"
        result["completion"].update(
            {
                "receipt_id": updates["completion_receipt_id"],
                "receipt_persisted": True,
                "issue_done_read_back": True,
                "newly_unblocked_read_back": True,
                "worktree_cleanup": "pending",
            }
        )
    if (
        receipt["state"] == "integrated"
        and target == "integrated"
        and (event != "cleanup-completed" or updates != {"worktree_cleanup": "removed"})
    ):
        raise ValueError("integrated receipt only permits cleanup-completed")

    result["state"] = target
    result["updated_at"] = updated_at
    result["state_timestamps"][target] = updated_at
    validate_isolation_receipt(result)
    return result
