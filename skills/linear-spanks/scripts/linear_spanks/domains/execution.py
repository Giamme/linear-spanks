"""Execution profiles, receipts, isolation selection, and bounded planner batches."""

from __future__ import annotations

from typing import Any

from ..contracts.legacy import (
    command_by_name,
    execution_contract,
    human_verification_contract,
    milestone_orchestration_contract,
    milestone_review_contract,
    milestone_runtime_contract,
    parallel_execution_contract,
    project_epoch_contract,
    project_orchestration_contract,
    repository_scan_contract,
    required_references,
    routing_contract,
)
from ..core.legacy_constants import (
    ASSURANCE_RANK,
    ASSURANCE_VALUES,
    HARNESS_ALIASES,
    REPOSITORY_SCAN_TIERS,
    ROUTING_HARNESSES,
    TASK_RUNTIME_COMMANDS,
)


def isolation_configuration(
    name: str,
    requested: bool = False,
    milestone_stage: str | None = None,
) -> dict[str, Any] | None:
    contract = parallel_execution_contract()
    single = contract["single_execution"]
    optional = set(single["optional_commands"])
    always = set(single["always_isolated_commands"])
    conditional = single["conditional_commands"]
    if name in always:
        return {
            "flag": single["flag"],
            "mode": "always",
            "enabled": True,
            "status": "idempotent-assertion" if requested else "always-isolated",
            "uses_existing_wave_contract": True,
        }
    elif name in optional:
        mode = "optional"
        enabled = requested
        status = "enabled" if requested else "available"
    elif name in conditional:
        if not requested:
            return {
                "flag": single["flag"],
                "mode": "conditional",
                "enabled": False,
                "status": "available-at-implementation-stage",
                "required_stage": conditional[name],
            }
        if milestone_stage is None:
            raise ValueError(
                "ISOLATION_NOT_APPLICABLE: resolve run-milestone stage before any mutation"
            )
        if milestone_stage != conditional[name]:
            raise ValueError(
                "ISOLATION_NOT_APPLICABLE: run-milestone isolation applies only to "
                f"{conditional[name]}"
            )
        mode = "conditional"
        enabled = True
        status = "enabled"
    elif requested:
        raise ValueError(f"ISOLATION_NOT_APPLICABLE: command {name} cannot use isolation")
    else:
        return None

    result = {
        "flag": single["flag"],
        "mode": mode,
        "enabled": enabled,
        "status": status,
    }
    if enabled:
        result.update(
            {
                "preflight": "isolation-preflight-check",
                "receipt_check": "isolation-receipt-check",
                "transition": "isolation-transition",
                "git": {
                    "branch_pattern": single["branch_pattern"],
                    "worktree_root_config": contract["git"]["worktree_root_config"],
                    "merge_strategy": single["merge_strategy"],
                    "integration_strategy": single["integration_strategy"],
                    "preserve_child_branch": single["preserve_child_branch"],
                    "push_or_pr": single["push_or_pr"],
                },
                "receipt": contract["isolation_receipt"],
                "receipt_template": single["receipt_template"],
                "integration_preview_fields": single["integration_preview_fields"],
                "cleanup_after_integrated_receipt": single["cleanup_after_integrated_receipt"],
                "linear_done_after_parent_integration": single[
                    "linear_done_after_parent_integration"
                ],
            }
        )
    return result


def execution_envelope(
    name: str,
    scan_tier: str | None = None,
    assurance: str | None = None,
    isolated_worktree: bool = False,
    milestone_stage: str | None = None,
) -> dict[str, Any]:
    if assurance is not None and assurance not in ASSURANCE_VALUES:
        raise ValueError(f"unknown assurance profile: {assurance}")
    command = command_by_name(name)
    contract = execution_contract()
    configuration = contract["commands"][name]
    context = contract["context_profiles"][configuration["context"]]
    execution = contract["execution_profiles"][configuration["execution"]]
    approval = {**execution["approval"], "description": command["approval"]}

    def merged(field: str) -> list[str]:
        values = [*execution[field], *configuration.get(field, [])]
        return list(dict.fromkeys(values))

    reads = merged("reads")
    writes = merged("writes")
    postconditions = merged("postconditions")

    if command["access"] == "read" and (approval["kind"] != "none" or writes):
        raise ValueError(f"read-only command {name} resolved to a mutating execution profile")
    if command["access"] != "read" and approval["kind"] == "none":
        raise ValueError(f"non-read command {name} resolved without an approval policy")
    envelope = {
        "contract_version": contract["schema_version"],
        "command": command,
        "approval": approval,
        "context": {"profile": configuration["context"], **context},
        "reads": reads,
        "writes": writes,
        "postconditions": postconditions,
        "required_references": required_references(command, configuration),
        "session_boundary": configuration["session_boundary"],
        "bulk": configuration.get("bulk", False),
        "token_estimate": contract["token_estimate"],
    }
    if assurance is not None:
        optimized = name in TASK_RUNTIME_COMMANDS
        effective_assurance = (
            "strict"
            if name in {"implement-wave", "reconcile-wave"}
            else assurance
            if name in {"run-project", "run-milestone-loop"}
            else assurance
            if optimized
            else "strict"
        )
        envelope["assurance"] = {
            "requested": assurance,
            "effective": effective_assurance,
            "status": (
                "project-role-policy-enforced"
                if name == "run-project"
                else "milestone-role-policy-enforced"
                if name == "run-milestone-loop"
                else "parallel-execution-forces-strict"
                if name in {"implement-wave", "reconcile-wave"}
                else "provisional-risk-screen-required"
                if optimized
                else "family-not-yet-optimized"
            ),
        }
    scan_configuration = configuration.get("repository_scan")
    if scan_configuration is None and scan_tier is not None:
        raise ValueError(f"command {name} does not read repository code")
    if scan_configuration is not None:
        scan = repository_scan_contract()
        selected_tier = scan_tier or scan_configuration["default_tier"]
        if selected_tier not in scan["profiles"]:
            raise ValueError(f"unknown repository scan tier: {selected_tier}")
        envelope["repository_scan"] = {
            "contract_version": scan["schema_version"],
            "tier": selected_tier,
            "context": {"profile": selected_tier, **scan["profiles"][selected_tier]},
            "metric_measurements": scan["metric_measurements"],
            "stages": scan["stages"],
            "checkpoint": scan["checkpoint"],
            "evidence_capsule": scan["evidence_capsule"],
            "completion_finding": scan["completion_finding"],
            "completion_classifications": scan["completion_classifications"],
            "security": scan["security"],
            "overflow_result": scan["overflow_result"],
            "drift_result": scan["drift_result"],
        }
    if "orchestration" in configuration:
        routing = routing_contract()
        profile_name = configuration["orchestration"]
        profile = routing["orchestration_profiles"][profile_name]
        envelope["orchestration"] = {
            "contract_version": routing["schema_version"],
            "task_workflow": routing["task_workflow"],
            "profile": profile_name,
            **profile,
            "planner": routing["planner"],
            "coordinator_owns": routing["coordinator_owns"],
            "plan_packet": routing["plan_packet"],
            "worker_handoff": routing["worker_handoff"],
            "completion_receipt": routing["completion_receipt"],
        }
    if name in {"checkpoint-project", "rollover-project"}:
        epoch = project_epoch_contract()
        envelope["project_epoch"] = {
            "contract_version": epoch["schema_version"],
            "capsule": epoch["capsule"],
        }
        if name == "rollover-project":
            envelope["project_epoch"]["rollover"] = epoch["rollover"]
    if name == "run-project":
        envelope["project_orchestration"] = project_orchestration_contract()
    if name == "run-milestone-loop":
        envelope["milestone_orchestration"] = milestone_orchestration_contract()
    if name in {
        "run-milestone",
        "run-milestone-loop",
        "plan-tasks",
        "review-milestone",
        "report-milestone-findings",
        "status-milestone",
        "handoff-milestone",
    }:
        envelope["milestone_runtime"] = milestone_runtime_contract()
    if name in {"run-milestone", "run-milestone-loop", "review-milestone"}:
        envelope["milestone_review"] = milestone_review_contract()
    if name in {"implement-wave", "reconcile-wave"}:
        envelope["parallel_execution"] = parallel_execution_contract()
    if "references/human-verification.md" in envelope["required_references"]:
        envelope["human_verification"] = human_verification_contract()
    isolation = isolation_configuration(name, isolated_worktree, milestone_stage)
    if isolation is not None:
        envelope["isolation"] = isolation
        if isolation["enabled"] and isolation["mode"] != "always":
            single = parallel_execution_contract()["single_execution"]
            envelope["reads"] = list(dict.fromkeys([*envelope["reads"], *single["reads"]]))
            envelope["writes"] = list(dict.fromkeys([*envelope["writes"], *single["writes"]]))
            envelope["postconditions"] = list(
                dict.fromkeys([*envelope["postconditions"], *single["postconditions"]])
            )
            if "references/parallel-execution.md" not in envelope["required_references"]:
                envelope["required_references"].append("references/parallel-execution.md")
            if single["receipt_template"] not in envelope["required_references"]:
                envelope["required_references"].append(single["receipt_template"])
    from .context import bind_envelope

    return bind_envelope(envelope)


def task_runtime_card(
    name: str,
    isolated_worktree: bool = False,
    milestone_stage: str | None = None,
) -> dict[str, Any]:
    contract = execution_contract()
    if name in {"run-project", "run-milestone-loop"}:
        orchestration = (
            project_orchestration_contract()
            if name == "run-project"
            else milestone_orchestration_contract()
        )
        return {
            "command": name,
            "task_workflow": routing_contract()["task_workflow"],
            "session_boundary": orchestration["session_boundary"],
            "topology": orchestration["topology"],
            "roles": orchestration["roles"],
            "task_loop": orchestration["task_loop"],
            "verification_ledger": orchestration["verification_ledger"],
            "capabilities": orchestration["capabilities"],
            "scheduling": orchestration["scheduling"],
            "approval_gates": orchestration["approval_gates"],
            "supervisor": (
                orchestration.get("supervisor") if name == "run-milestone-loop" else None
            ),
            "milestone_runtime": (
                milestone_runtime_contract() if name == "run-milestone-loop" else None
            ),
            "milestone_review": (
                milestone_review_contract() if name == "run-milestone-loop" else None
            ),
            "human_verification": {
                "precedence": human_verification_contract()["precedence"],
                "system_default": human_verification_contract()["system_default"],
                "await_event": human_verification_contract()["lifecycle"]["await_event"],
            },
        }
    if name not in TASK_RUNTIME_COMMANDS:
        raise ValueError(f"command {name} has no compact task runtime card")
    configuration = contract["commands"][name]
    execution = contract["execution_profiles"][configuration["execution"]]
    card = contract["runtime_cards"]["phases"][name]

    def merged(field: str) -> list[str]:
        return list(dict.fromkeys([*execution[field], *configuration.get(field, [])]))

    result = {
        "command": name,
        "task_workflow": routing_contract()["task_workflow"],
        "safety_gates": contract["runtime_cards"]["shared_safety_gates"],
        "reads": merged("reads"),
        "writes": merged("writes"),
        "postconditions": merged("postconditions"),
        **card,
    }
    isolation = isolation_configuration(name, isolated_worktree, milestone_stage)
    if isolation is not None:
        result["isolation"] = isolation
        if isolation["enabled"] and isolation["mode"] != "always":
            single = parallel_execution_contract()["single_execution"]
            for field in ("reads", "writes", "postconditions"):
                result[field] = list(dict.fromkeys([*result[field], *single[field]]))
    return result


def execution_brief(
    name: str,
    assurance: str = "balanced",
    scan_tier: str | None = None,
    isolated_worktree: bool = False,
    milestone_stage: str | None = None,
) -> dict[str, Any]:
    if assurance not in ASSURANCE_VALUES:
        raise ValueError(f"unknown assurance profile: {assurance}")
    envelope = execution_envelope(
        name,
        scan_tier,
        isolated_worktree=isolated_worktree,
        milestone_stage=milestone_stage,
    )
    command = envelope["command"]
    optimized = name in TASK_RUNTIME_COMMANDS
    effective_assurance = (
        "strict"
        if name in {"implement-wave", "reconcile-wave"}
        else assurance
        if name in {"run-project", "run-milestone-loop"}
        else assurance
        if optimized
        else "strict"
    )
    result: dict[str, Any] = {
        "contract_version": envelope["contract_version"],
        "command": {
            "name": name,
            "family": command["family"],
            "access": command["access"],
            "template": command.get("template"),
            "transition": command.get("transition"),
            "issue_transition": command.get("issue_transition"),
        },
        "assurance": {
            "requested": assurance,
            "effective": effective_assurance,
            "status": (
                "project-role-policy-enforced"
                if name == "run-project"
                else "milestone-role-policy-enforced"
                if name == "run-milestone-loop"
                else "provisional-risk-screen-required"
                if optimized
                else "family-not-yet-optimized"
            ),
            "escalation_reason": (
                None
                if optimized
                or name in {"run-project", "run-milestone-loop"}
                or assurance == "strict"
                else "family-not-yet-optimized"
            ),
        },
        "approval": envelope["approval"],
        "context": envelope["context"],
        "session_boundary": envelope["session_boundary"],
        "bulk": envelope["bulk"],
        "required_references": (
            []
            if optimized and assurance in {"fast", "balanced"}
            else envelope["required_references"]
        ),
        "runtime_card": (
            task_runtime_card(name, isolated_worktree, milestone_stage)
            if optimized or name in {"run-project", "run-milestone-loop"}
            else None
        ),
    }
    if "isolation" in envelope:
        result["isolation"] = envelope["isolation"]
    if "repository_scan" in envelope:
        repository_scan = envelope["repository_scan"]
        result["repository_scan"] = {
            "tier": repository_scan["tier"],
            "context": repository_scan["context"],
            "metric_measurements": repository_scan["metric_measurements"],
            "exact_measurement_required": True,
            "overflow_result": repository_scan["overflow_result"],
            "drift_result": repository_scan["drift_result"],
        }
    if "orchestration" in envelope:
        orchestration = envelope["orchestration"]
        result["orchestration"] = {
            "profile": orchestration["profile"],
            "decision_command": "orchestration-decision",
            "plan_packet_fields": orchestration["plan_packet"]["required_fields"],
            "worker_handoff_fields": orchestration["worker_handoff"]["required_fields"],
            "completion_receipt_fields": orchestration["completion_receipt"][
                "required_routing_fields"
            ],
        }
    if "project_orchestration" in envelope:
        project = envelope["project_orchestration"]
        result["project_orchestration"] = {
            "roles": project["topology"]["roles"],
            "receipt_fields": project["project_loop_receipt"]["required_fields"],
            "handoff_fields": project["role_handoff"]["required_fields"],
            "automatic_rounds": project["task_loop"]["automatic_rounds"],
            "validator_commands": [
                "project-loop-next",
                "project-loop-receipt-check",
                "project-loop-transition",
                "role-handoff-check",
                "role-capability-check",
                "task-attempt-check",
                "model-escalation-check",
                "verification-ledger-check",
            ],
        }
    if "milestone_orchestration" in envelope:
        milestone = envelope["milestone_orchestration"]
        result["milestone_orchestration"] = {
            "roles": milestone["topology"]["roles"],
            "receipt_fields": milestone["milestone_loop_receipt"]["required_fields"],
            "handoff_fields": milestone["role_handoff"]["required_fields"],
            "automatic_rounds": milestone["task_loop"]["automatic_rounds"],
            "validator_commands": [
                "milestone-loop-next",
                "milestone-loop-receipt-check",
                "milestone-loop-transition",
                "orchestration-scope-check",
                "milestone-role-card",
                "role-handoff-check",
                "role-capability-check",
                "task-attempt-check",
                "model-escalation-check",
                "verification-ledger-check",
            ],
        }
    if "human_verification" in envelope:
        human = envelope["human_verification"]
        result["human_verification"] = {
            "system_default": human["system_default"],
            "precedence": human["precedence"],
            "await_event": human["lifecycle"]["await_event"],
            "validator_commands": [
                "human-verification-policy-document-check",
                "human-verification-effective",
                "human-verification-preview-check",
                "human-verification-action-check",
                "filter-human-verification-gates",
                "orchestration-policy-binding-check",
            ],
        }
    return result


def validate_preflight_receipt(receipt: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    contract = routing_contract()["preflight_receipt"]
    required = set(contract["required_fields"])
    if set(receipt) != required:
        missing = sorted(required - set(receipt))
        extra = sorted(set(receipt) - required)
        raise ValueError(f"preflight receipt field mismatch; missing={missing}, extra={extra}")
    current_fields = required - {"schema_version"}
    if set(current) != current_fields:
        missing = sorted(current_fields - set(current))
        extra = sorted(set(current) - current_fields)
        raise ValueError(f"preflight current field mismatch; missing={missing}, extra={extra}")
    if receipt["schema_version"] != contract["schema_version"]:
        raise ValueError("unsupported preflight receipt schema_version")
    for field in current_fields:
        if not isinstance(receipt[field], str) or not receipt[field]:
            raise ValueError(f"preflight receipt {field} must be non-empty text")
        if not isinstance(current[field], str) or not current[field]:
            raise ValueError(f"preflight current {field} must be non-empty text")
    for field in ("requested_assurance", "effective_assurance"):
        if receipt[field] not in ASSURANCE_VALUES or current[field] not in ASSURANCE_VALUES:
            raise ValueError(f"preflight {field} has an invalid assurance value")
    if (
        ASSURANCE_RANK[receipt["effective_assurance"]]
        < ASSURANCE_RANK[receipt["requested_assurance"]]
        or ASSURANCE_RANK[current["effective_assurance"]]
        < ASSURANCE_RANK[current["requested_assurance"]]
    ):
        raise ValueError("preflight effective assurance cannot downgrade the request")
    for source_name, source in (("receipt", receipt), ("current", current)):
        harness = HARNESS_ALIASES.get(source["harness"], source["harness"])
        if harness not in ROUTING_HARNESSES:
            raise ValueError(f"preflight {source_name} has an unknown harness")
    if (
        receipt["scan_tier"] not in REPOSITORY_SCAN_TIERS
        or current["scan_tier"] not in REPOSITORY_SCAN_TIERS
    ):
        raise ValueError("preflight scan_tier is invalid")
    mismatches = []
    for field in contract["drift_fields"]:
        receipt_value = receipt[field]
        current_value = current[field]
        if field == "harness":
            receipt_value = HARNESS_ALIASES.get(receipt_value, receipt_value)
            current_value = HARNESS_ALIASES.get(current_value, current_value)
        if receipt_value != current_value:
            mismatches.append(field)
    trace_changed = [
        field for field in contract["trace_fields"] if receipt[field] != current[field]
    ]
    return {
        "reused": not mismatches,
        "status": "reused" if not mismatches else contract["invalid_result"],
        "invalidated_by": mismatches,
        "trace_changed": trace_changed,
    }


def linear_readback_plan(payload: dict[str, Any]) -> dict[str, Any]:
    required = {"schema_version", "assurance", "bulk", "operations", "reconciliation"}
    if set(payload) != required:
        missing = sorted(required - set(payload))
        extra = sorted(set(payload) - required)
        raise ValueError(f"Linear read-back field mismatch; missing={missing}, extra={extra}")
    if payload["schema_version"] != 1:
        raise ValueError("unsupported Linear read-back schema_version")
    assurance = payload["assurance"]
    if assurance not in ASSURANCE_VALUES:
        raise ValueError(f"unknown assurance profile: {assurance}")
    if not isinstance(payload["bulk"], bool):
        raise ValueError("Linear read-back bulk must be a boolean")
    operations = payload["operations"]
    reconciliation_policy = routing_contract()["linear_reconciliation"]
    operation_fields = set(reconciliation_policy["operation_fields"])
    optional_fields = set(reconciliation_policy["optional_operation_fields"])
    identity_fields = list(reconciliation_policy["readback_identity_fields"])
    if not isinstance(operations, list) or not operations:
        raise ValueError("Linear read-back requires at least one operation")
    identifiers: list[str] = []
    expected: dict[str, str] = {}
    acknowledged: dict[str, bool] = {}
    # A read-back must prove the intended fields landed, not haul the whole entity back into
    # context. When the caller declares what it wrote, the plan projects the read to those fields
    # plus identity and revision; omitting written_fields keeps the previous full-entity read.
    projection: dict[str, list[str] | None] = {}
    for operation in operations:
        if not isinstance(operation, dict) or not operation_fields <= set(operation):
            raise ValueError("Linear read-back operations have invalid fields")
        if set(operation) - operation_fields - optional_fields:
            raise ValueError("Linear read-back operations have invalid fields")
        entity_id = operation["entity_id"]
        revision = operation["expected_revision"]
        ack = operation["write_acknowledged"]
        written = operation.get("written_fields")
        if written is not None and (
            not isinstance(written, list)
            or not written
            or not all(isinstance(field, str) and field for field in written)
        ):
            raise ValueError("Linear read-back written_fields must be a non-empty string list")
        projection[entity_id] = (
            None if written is None else sorted(set(identity_fields) | set(written))
        )
        if (
            not isinstance(entity_id, str)
            or not entity_id
            or entity_id in expected
            or not isinstance(revision, str)
            or not revision
            or not isinstance(ack, bool)
        ):
            raise ValueError("Linear read-back operation values are invalid")
        identifiers.append(entity_id)
        expected[entity_id] = revision
        acknowledged[entity_id] = ack
    reconciliation = payload["reconciliation"]
    if reconciliation is not None and (
        not isinstance(reconciliation, dict)
        or not all(
            isinstance(key, str) and key and (value is None or isinstance(value, str))
            for key, value in reconciliation.items()
        )
    ):
        raise ValueError("Linear reconciliation must map entity IDs to revisions or null")
    if assurance == "strict":
        return {
            "mode": "per-write-read-back",
            "trust_mutation_acknowledgement": False,
            "reconciliation_query": False,
            "final_read_ids": identifiers,
            "targeted_recovery_read_ids": [
                entity_id for entity_id in identifiers if not acknowledged[entity_id]
            ],
            "readback_fields": projection,
        }
    if payload["bulk"]:
        if reconciliation is None:
            raise ValueError("bulk fast/balanced read-back requires a reconciliation result")
        unknown = sorted(set(reconciliation) - set(identifiers))
        if unknown:
            raise ValueError(f"Linear reconciliation contains unknown entities: {unknown}")
        recovery = [
            entity_id
            for entity_id in identifiers
            if not acknowledged[entity_id] or reconciliation.get(entity_id) != expected[entity_id]
        ]
        return {
            "mode": "coalesced-bulk-read-back",
            "trust_mutation_acknowledgement": True,
            "reconciliation_query": True,
            "final_read_ids": [],
            "targeted_recovery_read_ids": recovery,
            "readback_fields": projection,
        }
    if reconciliation is not None:
        raise ValueError("single-entity fast/balanced read-back does not use reconciliation")
    return {
        "mode": "final-entity-read-back",
        "trust_mutation_acknowledgement": True,
        "reconciliation_query": False,
        "final_read_ids": identifiers,
        "targeted_recovery_read_ids": [
            entity_id for entity_id in identifiers if not acknowledged[entity_id]
        ],
        "readback_fields": projection,
    }


def validate_completion_receipt(payload: dict[str, Any]) -> dict[str, Any]:
    completion = payload.get("task_completion")
    payload = {key: value for key, value in payload.items() if key != "task_completion"}
    if completion is not None:
        from ..core.legacy_validation import _require_commit, _require_nonempty_text
        from ._state_v1 import validate_sha256

        if (
            not isinstance(completion, dict)
            or set(completion)
            != {
                "schema_version",
                "task_id",
                "candidate_commit",
                "material_binding",
                "policy_hash",
                "issue_status",
                "issue_revision",
                "completion_ref",
                "read_back",
            }
            or completion["schema_version"] != 1
        ):
            raise ValueError("task completion binding fields are invalid")
        for field in ("task_id", "issue_revision", "completion_ref"):
            _require_nonempty_text(completion[field], field)
        _require_commit(completion["candidate_commit"], "candidate_commit")
        for field in ("material_binding", "policy_hash"):
            validate_sha256(completion[field], field)
        if completion["issue_status"] != "Done" or completion["read_back"] is not True:
            raise ValueError("task completion requires durable Done and completion read-back")
    required = set(routing_contract()["completion_receipt"]["required_routing_fields"])
    if set(payload) != required:
        missing = sorted(required - set(payload))
        extra = sorted(set(payload) - required)
        raise ValueError(f"completion receipt field mismatch; missing={missing}, extra={extra}")
    for field in (
        "harness",
        "worker_role",
        "tier_enforcement_status",
        "requested_strength",
        "review_result",
        "requested_assurance",
        "effective_assurance",
    ):
        if not isinstance(payload[field], str) or not payload[field]:
            raise ValueError(f"completion receipt {field} must be non-empty text")
    harness = HARNESS_ALIASES.get(payload["harness"], payload["harness"])
    if harness not in ROUTING_HARNESSES:
        raise ValueError("completion receipt harness is unknown")
    if payload["worker_role"] not in {*routing_contract()["roles"], "coordinator"}:
        raise ValueError("completion receipt worker_role is invalid")
    if payload["requested_strength"] not in {*routing_contract()["strengths"], "none"}:
        raise ValueError("completion receipt requested_strength is invalid")
    if (
        payload["requested_assurance"] not in ASSURANCE_VALUES
        or payload["effective_assurance"] not in ASSURANCE_VALUES
    ):
        raise ValueError("completion receipt assurance values are invalid")
    if (
        ASSURANCE_RANK[payload["effective_assurance"]]
        < ASSURANCE_RANK[payload["requested_assurance"]]
    ):
        raise ValueError("completion receipt effective assurance cannot downgrade the request")
    escalation_reason = payload["assurance_escalation_reason"]
    if escalation_reason is not None and not (
        isinstance(escalation_reason, list)
        and escalation_reason
        and all(isinstance(reason, str) and reason for reason in escalation_reason)
    ):
        raise ValueError(
            "completion receipt assurance_escalation_reason must be a non-empty text list or null"
        )
    if payload["configured_model_when_observable"] is not None and not isinstance(
        payload["configured_model_when_observable"], str
    ):
        raise ValueError("completion receipt configured model must be text or null")
    for field in (
        "planner_runs",
        "reviewer_runs",
        "linear_reads",
        "linear_writes",
        "linear_read_backs",
        "context_bytes",
    ):
        if (
            not isinstance(payload[field], int)
            or isinstance(payload[field], bool)
            or payload[field] < 0
        ):
            raise ValueError(f"completion receipt {field} must be a non-negative integer")
    if not isinstance(payload["delegated_roles"], list) or not all(
        isinstance(role, str) and role for role in payload["delegated_roles"]
    ):
        raise ValueError("completion receipt delegated_roles must be a text list")
    if not isinstance(payload["preflight_reused"], bool):
        raise ValueError("completion receipt preflight_reused must be a boolean")
    return {
        "status": "valid",
        **payload,
        **({"task_completion": completion} if completion is not None else {}),
    }


def planner_batches(tasks: list[dict[str, Any]], assurance: str) -> list[list[str]]:
    if assurance not in ASSURANCE_VALUES:
        raise ValueError(f"unknown assurance profile: {assurance}")
    ids: list[str] = []
    blockers_by_id: dict[str, list[str]] = {}
    for task in tasks:
        if not isinstance(task, dict) or set(task) != {"id", "blocked_by"}:
            raise ValueError("planning tasks require exactly id and blocked_by")
        task_id = task["id"]
        blocked_by = task["blocked_by"]
        if not isinstance(task_id, str) or not task_id or task_id in blockers_by_id:
            raise ValueError("planning task IDs must be unique non-empty text")
        if not isinstance(blocked_by, list) or not all(
            isinstance(blocker, str) and blocker for blocker in blocked_by
        ):
            raise ValueError(f"planning task {task_id} blocked_by must be a text list")
        ids.append(task_id)
        blockers_by_id[task_id] = blocked_by
    if assurance == "strict":
        return [[task_id] for task_id in ids]
    index = {task_id: position for position, task_id in enumerate(ids)}
    neighbors: dict[str, set[str]] = {task_id: set() for task_id in ids}
    for task_id, blockers in blockers_by_id.items():
        for blocker in blockers:
            if blocker in neighbors:
                neighbors[task_id].add(blocker)
                neighbors[blocker].add(task_id)
    components: list[list[str]] = []
    unseen = set(ids)
    for task_id in ids:
        if task_id not in unseen:
            continue
        stack = [task_id]
        component: list[str] = []
        unseen.remove(task_id)
        while stack:
            current = stack.pop()
            component.append(current)
            adjacent = sorted(neighbors[current] & unseen, key=index.__getitem__, reverse=True)
            for neighbor in adjacent:
                unseen.remove(neighbor)
                stack.append(neighbor)
        components.append(sorted(component, key=index.__getitem__))
    limit = routing_contract()["planner_batching"]["balanced_max_tasks"]
    return [
        component[offset : offset + limit]
        for component in components
        for offset in range(0, len(component), limit)
    ]
