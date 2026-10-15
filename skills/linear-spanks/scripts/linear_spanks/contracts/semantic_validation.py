"""Exhaustive semantic validation for the indexed v1 policy documents.

These validators are the characterized v1 safety contract, evaluated against an
injectable in-memory contract collection at the v2 load boundary. They perform no
filesystem reads and define no public command surface.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextvars import ContextVar
from pathlib import Path
from typing import Any, cast

from ..core.errors import UsageError
from ..core.jsonio import mutable_json_copy
from ..core.legacy_constants import (
    APPROVAL_KINDS,
    ASSURANCE_VALUES,
    COMMANDS_PATH,
    EXECUTION_PATH,
    HUMAN_VERIFICATION_PATH,
    ISSUE_WORKFLOW_PATH,
    MILESTONE_ORCHESTRATION_PATH,
    MILESTONE_REVIEW_PATH,
    MILESTONE_RUNTIME_PATH,
    ORCHESTRATED_COMMANDS,
    PARALLEL_EXECUTION_PATH,
    PROJECT_EPOCH_PATH,
    PROJECT_ORCHESTRATION_PATH,
    REPOSITORY_SCAN_PATH,
    REPOSITORY_SCAN_TIERS,
    ROUTING_HARNESSES,
    ROUTING_PATH,
    TASK_RUNTIME_COMMANDS,
    WORKFLOW_PATH,
)

_PATH_NAMES = {
    COMMANDS_PATH: "legacy_commands",
    WORKFLOW_PATH: "workflow",
    ISSUE_WORKFLOW_PATH: "issue_workflow",
    EXECUTION_PATH: "execution",
    ROUTING_PATH: "routing",
    REPOSITORY_SCAN_PATH: "repository_scan",
    PROJECT_EPOCH_PATH: "project_epoch",
    PARALLEL_EXECUTION_PATH: "parallel_execution",
    PROJECT_ORCHESTRATION_PATH: "project_orchestration",
    MILESTONE_ORCHESTRATION_PATH: "milestone_orchestration",
    HUMAN_VERIFICATION_PATH: "human_verification",
    MILESTONE_REVIEW_PATH: "milestone_review",
    MILESTONE_RUNTIME_PATH: "milestone_runtime",
}
_ACTIVE_DOCUMENTS: ContextVar[Mapping[str, Mapping[str, Any]] | None] = ContextVar(
    "linear_spanks_semantic_contracts",
    default=None,
)


def load_json(path: Path) -> dict[str, Any]:
    documents = _ACTIVE_DOCUMENTS.get()
    name = _PATH_NAMES.get(path)
    if documents is None or name is None or name not in documents:
        raise ValueError(f"semantic contract source is unavailable: {path.name}")
    return cast(dict[str, Any], mutable_json_copy(documents[name]))


def issue_workflow_contract() -> dict[str, Any]:
    contract = load_json(ISSUE_WORKFLOW_PATH)
    if not isinstance(contract.get("schema_version"), int) or contract["schema_version"] <= 0:
        raise ValueError("issue workflow contract requires a positive schema_version")
    expected_statuses = {
        "human_draft": "Human draft",
        "unplanned": "Unplanned",
        "backlog": "Backlog",
    }
    if contract.get("statuses") != expected_statuses:
        raise ValueError("issue workflow contract has invalid readiness statuses")
    transitions = contract.get("transitions")
    if not isinstance(transitions, dict) or not transitions:
        raise ValueError("issue workflow contract requires transitions")
    for name, transition in transitions.items():
        if not isinstance(transition, dict):
            raise ValueError(f"issue transition {name} must be an object")
        commands = transition.get("commands")
        sources = transition.get("from")
        target = transition.get("to")
        requirements = transition.get("requires")
        if (
            not isinstance(commands, list)
            or not commands
            or not all(isinstance(command, str) and command for command in commands)
        ):
            raise ValueError(f"issue transition {name} requires commands")
        if (
            not isinstance(sources, list)
            or not sources
            or not all(source in expected_statuses.values() for source in sources)
        ):
            raise ValueError(f"issue transition {name} has invalid source statuses")
        if target not in expected_statuses.values():
            raise ValueError(f"issue transition {name} has invalid target status")
        if (
            not isinstance(requirements, list)
            or not requirements
            or not all(isinstance(requirement, str) and requirement for requirement in requirements)
        ):
            raise ValueError(f"issue transition {name} requires postconditions")
    return contract


def human_verification_contract() -> dict[str, Any]:
    contract = load_json(HUMAN_VERIFICATION_PATH)
    if contract.get("schema_version") != 1:
        raise ValueError("human verification contract schema_version must be one")
    if contract.get("system_default") != "disabled":
        raise ValueError("human verification system default must be disabled")
    if contract.get("precedence") != ["milestone-override", "project-default", "system-default"]:
        raise ValueError("human verification precedence is invalid")
    results = contract.get("results")
    required_results = {
        "policy_unavailable",
        "policy_collision",
        "policy_malformed",
        "policy_drift",
        "preview_required",
        "gate_drift",
        "checklist_stale",
        "confirmation_incomplete",
        "bypass_reason_required",
    }
    if not isinstance(results, dict) or set(results) != required_results:
        raise ValueError("human verification result vocabulary is incomplete")
    project = contract.get("project_policy")
    if (
        not isinstance(project, dict)
        or project.get("document_title") != "Linear Spanks Human Verification Policy"
        or project.get("values") != ["enabled", "disabled"]
        or project.get("singleton") is not True
        or project.get("missing_behavior") != "disabled"
        or project.get("persistence_required_for_project_mutation") is not True
    ):
        raise ValueError("human verification project policy is invalid")
    override = contract.get("milestone_override")
    if not isinstance(override, dict) or override.get("values") != [
        "enabled",
        "disabled",
        "inherit",
    ]:
        raise ValueError("human verification milestone override is invalid")
    gate = contract.get("gate_issue")
    if (
        not isinstance(gate, dict)
        or gate.get("disabled_action") != "cancel"
        or gate.get("history_preserved") is not True
        or not all(
            gate.get(field) is True
            for field in (
                "planner_excluded",
                "dependency_graph_excluded",
                "task_execution_excluded",
                "regular_task_totals_excluded",
            )
        )
    ):
        raise ValueError("human verification gate policy is invalid")
    lifecycle = contract.get("lifecycle")
    if lifecycle != {
        "disabled_wrap_from": "milestone-verified",
        "enabled_verify_to": "milestone-verified",
        "enabled_confirm_to": "human-verified",
        "enabled_failure_to": "implementing",
        "enabled_wrap_from": "human-verified",
        "await_event": "await-human-verification",
        "requires_linear_completion_readback": True,
        "machine_reverification_after_enable_or_failure": True,
        "confirmation_and_wrap_are_separate": True,
    }:
        raise ValueError("human verification lifecycle is invalid")
    for section in (
        "project_policy",
        "milestone_override",
        "effective_policy",
        "preview",
        "gate_issue",
        "checklist",
        "repair_task",
        "orchestration_binding",
    ):
        value = contract.get(section)
        if not isinstance(value, dict) or not isinstance(value.get("required_fields"), list):
            raise ValueError(f"human verification {section} requires fields")
    return contract


def milestone_review_contract() -> dict[str, Any]:
    contract = load_json(MILESTONE_REVIEW_PATH)
    if contract.get("schema_version") != 2:
        raise ValueError("milestone review contract requires schema_version 2")
    if set(contract.get("commands", [])) != {
        "run-milestone",
        "run-milestone-loop",
        "review-milestone",
    }:
        raise ValueError("milestone review contract command coverage is incomplete")
    if contract.get("session_boundary") != "single-review-batch":
        raise ValueError("milestone review requires a single-review-batch boundary")
    if contract.get("same_session_result") != "FRESH_CONTEXT_REQUIRED":
        raise ValueError("milestone review same-session result is invalid")
    if contract.get("overflow_result") != "CONTEXT_OVERFLOW":
        raise ValueError("milestone review overflow result is invalid")
    if contract.get("drift_result") != "MILESTONE_REVIEW_DRIFT":
        raise ValueError("milestone review drift result is invalid")
    for section_name in (
        "batching",
        "invocation_budget",
        "phase_budget",
        "coverage",
        "checkpoint",
        "finalization",
    ):
        if not isinstance(contract.get(section_name), dict):
            raise ValueError(f"milestone review {section_name} is required")
    for section, field in (
        ("batching", "max_tasks_per_batch"),
        ("batching", "max_packet_tokens"),
        ("invocation_budget", "max_model_turns"),
        ("invocation_budget", "max_active_context_tokens"),
        ("invocation_budget", "max_cumulative_input_tokens"),
        ("invocation_budget", "stop_new_reads_percent"),
        ("phase_budget", "tokens_per_planned_batch"),
        ("phase_budget", "finalization_tokens"),
    ):
        value = contract[section].get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError(f"milestone review {field} must be a positive integer")
    if contract["invocation_budget"]["stop_new_reads_percent"] >= 100:
        raise ValueError("milestone review stop_new_reads_percent must be below 100")
    if set(contract.get("modes", [])) != {"legacy", "next-wave", "incremental"}:
        raise ValueError("milestone review modes are invalid")
    coverage = contract["coverage"]
    if coverage.get("incremental") != [
        "changed-tasks",
        "material-dependency-neighbours",
        "overlapping-footprints",
        "affected-final-sinks",
    ]:
        raise ValueError("milestone review incremental coverage is invalid")
    for section_name in ("checkpoint", "finalization"):
        fields = contract[section_name].get("required_fields")
        if not isinstance(fields, list) or not fields or len(fields) != len(set(fields)):
            raise ValueError(f"milestone review {section_name} fields are invalid")
    return contract


def milestone_runtime_contract() -> dict[str, Any]:
    contract = load_json(MILESTONE_RUNTIME_PATH)
    if contract.get("schema_version") != 1:
        raise ValueError("milestone runtime contract requires schema_version 1")
    if contract.get("document_title_pattern") != (
        "Linear Spanks Milestone Runtime — <milestone-id>"
    ):
        raise ValueError("milestone runtime document title pattern is invalid")
    storage = contract.get("storage")
    if not isinstance(storage, dict) or storage.get("preferred") != "document":
        raise ValueError("milestone runtime storage policy is invalid")
    if storage.get("fallback") != "managed-comment":
        raise ValueError("milestone runtime fallback policy is invalid")
    if storage.get("conflict_result") != "MILESTONE_RUNTIME_STATE_CONFLICT":
        raise ValueError("milestone runtime conflict result is invalid")
    required = contract.get("runtime_required_fields")
    if not isinstance(required, list) or not required or len(required) != len(set(required)):
        raise ValueError("milestone runtime fields are invalid")
    reference = contract.get("description_reference")
    if (
        not isinstance(reference, dict)
        or not isinstance(reference.get("required_fields"), list)
        or reference.get("preserve_human_description") is not True
    ):
        raise ValueError("milestone runtime description reference is invalid")
    plan = contract.get("plan")
    if not isinstance(plan, dict) or plan.get("schema_version") != 2:
        raise ValueError("milestone runtime plan policy is invalid")
    if set(plan.get("drift_classes", [])) != {"valid", "safe-refresh", "material"}:
        raise ValueError("milestone runtime drift classes are invalid")
    autopilot = contract.get("autopilot")
    if (
        not isinstance(autopilot, dict)
        or autopilot.get("default_max_events") != 20
        or autopilot.get("hard_max_events") != 100
    ):
        raise ValueError("milestone runtime autopilot limits are invalid")
    if set(autopilot.get("automatic_operations", [])) & set(autopilot.get("gated_operations", [])):
        raise ValueError("milestone runtime operation policies overlap")
    return contract


def routing_contract() -> dict[str, Any]:
    contract = load_json(ROUTING_PATH)
    if not isinstance(contract.get("schema_version"), int) or contract["schema_version"] <= 0:
        raise ValueError("routing contract requires a positive schema_version")

    roles = contract.get("roles")
    strengths = contract.get("strengths")
    capabilities = contract.get("harness_capabilities")
    if roles != ["planner", "executor", "reviewer"]:
        raise ValueError("routing contract roles must be planner, executor, reviewer")
    if strengths != ["low", "medium", "high"]:
        raise ValueError("routing contract strengths must be low, medium, high")
    if capabilities != ["enforced", "inherited-model", "advisory-only"]:
        raise ValueError("routing contract has invalid harness capabilities")
    if contract.get("hierarchical_orchestration_contract") != (
        "project-orchestration-contract.json"
    ):
        raise ValueError("routing contract must link hierarchical project orchestration")
    if contract.get("detected_drift_values") != {
        "legacy": [False, True],
        "scoped": ["valid", "safe-refresh", "material"],
        "legacy_true_semantics": "material",
        "scoped_results": {
            "valid": None,
            "safe-refresh": "SAFE_REFRESH_REQUIRED",
            "material": "REPLAN_REQUIRED",
        },
    }:
        raise ValueError("routing contract detected drift values are invalid")

    assurance = contract.get("assurance")
    if not isinstance(assurance, dict):
        raise ValueError("routing contract requires assurance profiles")
    if assurance.get("schema_version") != 1:
        raise ValueError("assurance schema_version must be one")
    if assurance.get("values") != list(ASSURANCE_VALUES):
        raise ValueError("assurance values must be fast, balanced, strict")
    if assurance.get("default") != "balanced":
        raise ValueError("balanced must be the default assurance")
    if set(assurance.get("task_optimized_commands", [])) != TASK_RUNTIME_COMMANDS:
        raise ValueError("assurance task command coverage is incomplete")
    assurance_profiles = assurance.get("profiles")
    if not isinstance(assurance_profiles, dict) or set(assurance_profiles) != set(ASSURANCE_VALUES):
        raise ValueError("assurance profiles must cover every assurance value")
    for name, profile in assurance_profiles.items():
        if not isinstance(profile, dict):
            raise ValueError(f"assurance profile {name} must be an object")
        for field in (
            "eligibility",
            "planner",
            "review",
            "context_mode",
            "mutation_verification",
        ):
            if not isinstance(profile.get(field), str) or not profile[field]:
                raise ValueError(f"assurance profile {name} requires {field}")
    strict_dimensions = assurance.get("strict_escalation_dimensions")
    if not isinstance(strict_dimensions, list) or not strict_dimensions:
        raise ValueError("assurance requires strict escalation dimensions")
    safety_invariants = assurance.get("safety_invariants")
    if not isinstance(safety_invariants, list) or len(safety_invariants) < 8:
        raise ValueError("assurance safety invariants are incomplete")

    planner = contract.get("planner")
    if not isinstance(planner, dict):
        raise ValueError("routing contract requires a planner object")
    if planner.get("strength") != "high" or planner.get("access") != "read-only":
        raise ValueError("planner must be high strength and read-only")
    planner_context = planner.get("context")
    if not isinstance(planner_context, dict) or not planner_context:
        raise ValueError("planner requires a bounded context object")
    for limit, value in planner_context.items():
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError(f"planner context limit {limit} must be a positive integer")
    evidence = planner.get("required_repository_evidence")
    if (
        not isinstance(evidence, list)
        or not evidence
        or not all(isinstance(item, str) and item for item in evidence)
    ):
        raise ValueError("planner requires repository evidence fields")
    if planner.get("overflow_result") != "CONTEXT_OVERFLOW":
        raise ValueError("planner overflow result must be CONTEXT_OVERFLOW")

    assessment = contract.get("assessment")
    if not isinstance(assessment, dict):
        raise ValueError("routing contract requires an assessment object")
    if assessment.get("schema_version") != contract["schema_version"]:
        raise ValueError("routing assessment schema_version must match the routing contract")
    required_fields = assessment.get("required_fields")
    expected_fields = {
        "schema_version",
        "localized_established_pattern",
        "deterministic_focused_verification",
        "uncertainty",
        "dimensions",
    }
    if not isinstance(required_fields, list) or set(required_fields) != expected_fields:
        raise ValueError("routing assessment required_fields are incomplete")
    dimensions = assessment.get("dimensions")
    if not isinstance(dimensions, dict) or not dimensions:
        raise ValueError("routing assessment requires dimensions")
    for name, definition in dimensions.items():
        if not isinstance(definition, dict):
            raise ValueError(f"routing dimension {name} must be an object")
        if definition.get("severity") not in {"critical", "medium"}:
            raise ValueError(f"routing dimension {name} has invalid severity")
        if not isinstance(definition.get("review_trigger"), bool):
            raise ValueError(f"routing dimension {name} requires review_trigger boolean")
    if not set(strict_dimensions).issubset(dimensions):
        raise ValueError("assurance strict escalation dimensions are unknown")

    rules = contract.get("tier_rules")
    if not isinstance(rules, dict):
        raise ValueError("routing contract requires tier_rules")
    threshold = rules.get("high_on_medium_dimension_count")
    if not isinstance(threshold, int) or isinstance(threshold, bool) or threshold < 2:
        raise ValueError("high_on_medium_dimension_count must be at least two")
    if rules.get("default_tier") not in strengths:
        raise ValueError("tier_rules has an invalid default_tier")
    if rules.get("high_on_any_severity") != "critical":
        raise ValueError("tier_rules has an invalid high_on_any_severity")
    if rules.get("low_requires") != [
        "localized_established_pattern",
        "deterministic_focused_verification",
        "no_active_dimensions",
    ]:
        raise ValueError("tier_rules has invalid low requirements")
    if rules.get("uncertainty_escalates_one_tier") is not True:
        raise ValueError("uncertainty must escalate one tier")
    if rules.get("worker_may_downgrade") is not False:
        raise ValueError("workers must not be allowed to downgrade the planner tier")

    review_policy = contract.get("review_policy")
    if not isinstance(review_policy, dict) or set(review_policy) != set(strengths):
        raise ValueError("review_policy must cover every strength")
    if not all(isinstance(review_policy[strength], dict) for strength in strengths):
        raise ValueError("every review policy must be an object")
    if review_policy["high"].get("required") is not True:
        raise ValueError("high tier must require review")
    if review_policy["high"].get("strength") != "high":
        raise ValueError("high tier reviewer must use high strength")
    if review_policy["medium"].get("strength") != "medium":
        raise ValueError("medium reviewer must use medium strength")
    if review_policy["low"].get("required") is not False:
        raise ValueError("low tier must self-verify")

    for packet_name, field_name in (
        ("plan_packet", "required_fields"),
        ("worker_handoff", "required_fields"),
        ("completion_receipt", "required_routing_fields"),
    ):
        packet = contract.get(packet_name)
        if not isinstance(packet, dict):
            raise ValueError(f"routing contract requires {packet_name}")
        fields = packet.get(field_name)
        if (
            not isinstance(fields, list)
            or not fields
            or not all(isinstance(item, str) and item for item in fields)
        ):
            raise ValueError(f"{packet_name} requires a non-empty {field_name} list")
    expected_plan_fields = {
        "plan_revision",
        "planner_strength",
        "source_revision",
        "repository_evidence",
        "complexity_assessment",
        "executor_tier",
        "tier_rationale",
        "escalation_triggers",
        "reviewer_requirement",
        "implementation_steps",
        "affected_interfaces",
        "verification_commands",
        "stop_replan_conditions",
        "selected_skills",
        "execution_footprint",
    }
    expected_handoff_fields = {
        "plan_revision",
        "source_revision",
        "stable_task_contract",
        "relevant_blocker_outputs",
        "selected_skills",
        "repository_evidence_pointers",
        "acceptance_criteria",
        "required_verification",
        "executor_tier",
        "stop_replan_conditions",
    }
    expected_receipt_fields = {
        "harness",
        "worker_role",
        "configured_model_when_observable",
        "tier_enforcement_status",
        "requested_strength",
        "review_result",
        "requested_assurance",
        "effective_assurance",
        "assurance_escalation_reason",
        "planner_runs",
        "reviewer_runs",
        "delegated_roles",
        "linear_reads",
        "linear_writes",
        "linear_read_backs",
        "context_bytes",
        "preflight_reused",
    }
    if set(contract["plan_packet"]["required_fields"]) != expected_plan_fields:
        raise ValueError("plan_packet fields do not match the routing schema")
    if set(contract["worker_handoff"]["required_fields"]) != expected_handoff_fields:
        raise ValueError("worker_handoff fields do not match the routing schema")
    if set(contract["completion_receipt"]["required_routing_fields"]) != expected_receipt_fields:
        raise ValueError("completion_receipt fields do not match the routing schema")
    worker_handoff = contract["worker_handoff"]
    if worker_handoff.get("drift_result") != "REPLAN_REQUIRED":
        raise ValueError("worker handoff drift result must be REPLAN_REQUIRED")
    expected_drift_fields = {"scope", "interface", "dependency", "evidence"}
    if set(worker_handoff.get("drift_fields", [])) != expected_drift_fields:
        raise ValueError("worker handoff drift fields are incomplete")
    if worker_handoff.get("worker_may_downgrade") is not False:
        raise ValueError("worker handoff must prohibit tier downgrade")

    preflight = contract.get("preflight_receipt")
    if not isinstance(preflight, dict) or preflight.get("schema_version") != 1:
        raise ValueError("routing contract requires a versioned preflight receipt")
    preflight_fields = preflight.get("required_fields")
    drift_fields = set(preflight.get("drift_fields", []))
    trace_fields = set(preflight.get("trace_fields", []))
    if (
        not isinstance(preflight_fields, list)
        or drift_fields & trace_fields
        or set(preflight_fields) - {"schema_version"} != drift_fields | trace_fields
    ):
        raise ValueError(
            "preflight receipt drift and trace fields must partition every bound field"
        )
    if preflight.get("valid_for") != ["implement-next", "run-task"]:
        raise ValueError("preflight receipt command coverage is invalid")
    if preflight.get("invalid_result") != "PREFLIGHT_INVALIDATED":
        raise ValueError("preflight invalid result must be PREFLIGHT_INVALIDATED")
    batching = contract.get("planner_batching")
    if not isinstance(batching, dict):
        raise ValueError("routing contract requires planner batching")
    if (
        not isinstance(batching.get("balanced_max_tasks"), int)
        or batching["balanced_max_tasks"] <= 1
    ):
        raise ValueError("balanced planner batches must contain at least two tasks")
    reconciliation = contract.get("linear_reconciliation")
    if not isinstance(reconciliation, dict) or reconciliation.get("schema_version") != 1:
        raise ValueError("routing contract requires versioned Linear reconciliation")
    if reconciliation.get("operation_fields") != [
        "entity_id",
        "expected_revision",
        "write_acknowledged",
    ]:
        raise ValueError("Linear reconciliation operation fields are invalid")

    coordinator_owns = contract.get("coordinator_owns")
    if not isinstance(coordinator_owns, list) or not coordinator_owns:
        raise ValueError("routing contract requires coordinator ownership fields")
    profiles = contract.get("orchestration_profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise ValueError("routing contract requires orchestration_profiles")
    for name, profile in profiles.items():
        if not isinstance(profile, dict):
            raise ValueError(f"orchestration profile {name} must be an object")
        profile_roles = profile.get("roles")
        if not isinstance(profile_roles, dict) or set(profile_roles) != set(roles):
            raise ValueError(f"orchestration profile {name} must cover every role")
        for role, role_policy in profile_roles.items():
            if not isinstance(role_policy, dict):
                raise ValueError(f"orchestration role {name}.{role} must be an object")
            if "required" not in role_policy or "strength" not in role_policy:
                raise ValueError(f"orchestration role {name}.{role} is incomplete")
            required = role_policy["required"]
            strength = role_policy["strength"]
            if not isinstance(required, bool | str) or required == "":
                raise ValueError(f"orchestration role {name}.{role} has invalid required policy")
            if not isinstance(strength, str) or not strength:
                raise ValueError(f"orchestration role {name}.{role} has invalid strength")
            if role_policy.get("access") not in {"read-only", "workspace-write"}:
                raise ValueError(f"orchestration role {name}.{role} has invalid access")
        for field in ("delegation_policy", "fallback_behavior", "review_policy"):
            if not isinstance(profile.get(field), str) or not profile[field]:
                raise ValueError(f"orchestration profile {name} requires {field}")
        if not isinstance(profile.get("recompute_tier"), bool):
            raise ValueError(f"orchestration profile {name} requires recompute_tier boolean")

    harnesses = contract.get("harnesses")
    if not isinstance(harnesses, dict) or set(harnesses) != ROUTING_HARNESSES:
        raise ValueError("routing contract must configure every supported harness exactly once")
    for name, harness in harnesses.items():
        if not isinstance(harness, dict):
            raise ValueError(f"routing harness {name} must be an object")
        if harness.get("capability") not in capabilities:
            raise ValueError(f"routing harness {name} has an invalid capability")
        for field in ("delegation", "configuration"):
            if not isinstance(harness.get(field), str) or not harness[field]:
                raise ValueError(f"routing harness {name} requires {field}")
        if "profiles" in harness:
            profiles = harness["profiles"]
            if not isinstance(profiles, dict) or set(profiles) != set(roles):
                raise ValueError(f"routing harness {name} profiles must cover every role")
            if not all(isinstance(profile, str) and profile for profile in profiles.values()):
                raise ValueError(f"routing harness {name} profiles must be non-empty strings")
    return contract


def repository_scan_contract() -> dict[str, Any]:
    contract = load_json(REPOSITORY_SCAN_PATH)
    if not isinstance(contract.get("schema_version"), int) or contract["schema_version"] <= 0:
        raise ValueError("repository scan contract requires a positive schema_version")
    if contract.get("tiers") != list(REPOSITORY_SCAN_TIERS):
        raise ValueError("repository scan tiers must be fast, medium, heavy")
    if contract.get("default_tier") not in REPOSITORY_SCAN_TIERS:
        raise ValueError("repository scan contract has an invalid default_tier")
    if contract.get("token_estimate") != "ceil(utf8_characters / 4)":
        raise ValueError("repository scan contract has an invalid token estimate")

    measurements = contract.get("metric_measurements")
    if not isinstance(measurements, dict) or not measurements:
        raise ValueError("repository scan contract requires metric measurements")
    allowed_measurements = {"count", "utf8_bytes", "tokens"}
    if not all(measurement in allowed_measurements for measurement in measurements.values()):
        raise ValueError("repository scan contract has an invalid metric measurement")

    profiles = contract.get("profiles")
    if not isinstance(profiles, dict) or set(profiles) != set(REPOSITORY_SCAN_TIERS):
        raise ValueError("repository scan profiles must cover every tier")
    expected_limits = {"max_input_tokens", *measurements}
    previous: dict[str, int] | None = None
    for tier in REPOSITORY_SCAN_TIERS:
        profile = profiles[tier]
        if not isinstance(profile, dict) or set(profile) != expected_limits:
            raise ValueError(f"repository scan profile {tier} has incomplete limits")
        for limit, value in profile.items():
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(
                    f"repository scan profile {tier} limit {limit} must be a positive integer"
                )
            if previous is not None and value < previous[limit]:
                raise ValueError(f"repository scan limit {limit} must not decrease at tier {tier}")
        previous = profile

    stages = contract.get("stages")
    if stages != ["inventory", "shard-analysis", "synthesis", "preview", "apply", "complete"]:
        raise ValueError("repository scan contract has invalid stages")
    checkpoint = contract.get("checkpoint")
    if not isinstance(checkpoint, dict):
        raise ValueError("repository scan contract requires a checkpoint schema")
    expected_checkpoint_fields = {
        "schema_version",
        "run_id",
        "command",
        "scan_tier",
        "repository_root",
        "source_revision",
        "repository_fingerprint",
        "stage",
        "completed_batch_ids",
        "remaining_batch_ids",
        "coverage",
        "capsules",
        "completion_findings",
        "next_command",
    }
    expected_coverage_fields = {
        "eligible_files",
        "selected_files",
        "analyzed_files",
        "excluded_files",
        "selected_source_bytes",
    }
    if set(checkpoint.get("required_fields", [])) != expected_checkpoint_fields:
        raise ValueError("repository checkpoint fields are incomplete")
    if set(checkpoint.get("coverage_fields", [])) != expected_coverage_fields:
        raise ValueError("repository checkpoint coverage fields are incomplete")

    capsule = contract.get("evidence_capsule")
    if not isinstance(capsule, dict):
        raise ValueError("repository scan contract requires an evidence capsule schema")
    expected_capsule_fields = {
        "capsule_id",
        "module",
        "source_hashes",
        "responsibilities",
        "public_interfaces",
        "dependencies",
        "implemented_capabilities",
        "tests_and_verification",
        "known_gaps",
        "evidence_pointers",
        "confidence",
    }
    if set(capsule.get("required_fields", [])) != expected_capsule_fields:
        raise ValueError("repository evidence capsule fields are incomplete")
    if capsule.get("confidence_values") != ["low", "medium", "high"]:
        raise ValueError("repository evidence capsule confidence values are invalid")
    completion_finding = contract.get("completion_finding")
    expected_completion_finding_fields = {
        "outcome",
        "classification",
        "evidence_pointers",
        "verification_evidence",
        "confidence",
    }
    if (
        not isinstance(completion_finding, dict)
        or set(completion_finding.get("required_fields", [])) != expected_completion_finding_fields
    ):
        raise ValueError("repository completion finding fields are incomplete")
    if contract.get("completion_classifications") != [
        "verified-delivered",
        "implemented-unverified",
        "historical-inferred",
    ]:
        raise ValueError("repository completion classifications are invalid")

    security = contract.get("security")
    if not isinstance(security, dict):
        raise ValueError("repository scan contract requires security rules")
    if security.get("follow_symlinks") is not False:
        raise ValueError("repository scans must not follow symlinks")
    if security.get("checkpoint_within_repository") is not True:
        raise ValueError("repository checkpoints must remain inside the repository")
    for field in ("excluded_directories", "excluded_secret_patterns"):
        values = security.get(field)
        if (
            not isinstance(values, list)
            or not values
            or not all(isinstance(value, str) and value for value in values)
        ):
            raise ValueError(f"repository scan security requires {field}")
    if contract.get("overflow_result") != "CONTEXT_OVERFLOW":
        raise ValueError("repository scan overflow result must be CONTEXT_OVERFLOW")
    if contract.get("drift_result") != "REPOSITORY_DRIFT":
        raise ValueError("repository scan drift result must be REPOSITORY_DRIFT")
    return contract


def project_epoch_contract() -> dict[str, Any]:
    contract = load_json(PROJECT_EPOCH_PATH)
    if contract.get("schema_version") != 1:
        raise ValueError("project epoch contract schema_version must be one")

    capsule = contract.get("capsule")
    if not isinstance(capsule, dict):
        raise ValueError("project epoch contract requires a capsule schema")
    if capsule.get("title") != "Active Project Context":
        raise ValueError("project capsule requires the canonical title")
    if capsule.get("max_body_bytes") != 24576:
        raise ValueError("project capsule body limit must be 24 KiB")
    expected_capsule_fields = {
        "schema_version",
        "project_id",
        "project_revision",
        "label",
        "generated_at",
        "body",
        "source_snapshot_hash",
        "batches",
        "coverage",
        "next_command",
    }
    if set(capsule.get("required_fields", [])) != expected_capsule_fields:
        raise ValueError("project capsule required fields are incomplete")
    headings = capsule.get("required_headings")
    if (
        not isinstance(headings, list)
        or len(headings) != 8
        or not all(isinstance(heading, str) and heading.startswith("## ") for heading in headings)
    ):
        raise ValueError("project capsule headings are incomplete")
    inventory = capsule.get("inventory")
    expected_inventory = {
        "max_batches": 64,
        "max_compact_rows_per_batch": 30,
        "max_full_entities_per_batch": 12,
    }
    if inventory != expected_inventory:
        raise ValueError("project capsule inventory limits are invalid")
    if capsule.get("batch_fields") != [
        "batch_id",
        "compact_rows",
        "full_entities",
        "source_ids",
    ]:
        raise ValueError("project capsule batch fields are invalid")
    if capsule.get("coverage_fields") != [
        "expected_source_ids",
        "covered_source_ids",
        "excluded_sources",
    ]:
        raise ValueError("project capsule coverage fields are invalid")
    if capsule.get("exclusion_fields") != ["source_id", "reason"]:
        raise ValueError("project capsule exclusion fields are invalid")
    if capsule.get("overflow_result") != "CONTEXT_OVERFLOW":
        raise ValueError("project capsule overflow result must be CONTEXT_OVERFLOW")

    rollover = contract.get("rollover")
    if not isinstance(rollover, dict):
        raise ValueError("project epoch contract requires a rollover schema")
    phases = rollover.get("phases")
    expected_phases = [
        "inventory",
        "preview",
        "successor-created",
        "roadmap-created",
        "carryover-created",
        "source-resolved",
        "finalized",
    ]
    if phases != expected_phases:
        raise ValueError("project rollover phases are invalid")
    if rollover.get("initial_phase") != phases[0] or rollover.get("terminal_phase") != phases[-1]:
        raise ValueError("project rollover phase boundaries are invalid")
    transitions = rollover.get("transitions")
    if not isinstance(transitions, dict) or set(transitions) != set(phases):
        raise ValueError("project rollover transitions are incomplete")
    for index, phase in enumerate(phases):
        expected_targets = [phase]
        if index + 1 < len(phases):
            expected_targets.append(phases[index + 1])
        if transitions[phase] != expected_targets:
            raise ValueError(f"project rollover transition {phase} is invalid")
    if rollover.get("min_roadmap_items") != 3 or rollover.get("max_roadmap_items") != 7:
        raise ValueError("project rollover roadmap bounds are invalid")
    if rollover.get("successor_issue_status") != "Unplanned":
        raise ValueError("project rollover successor issues must start in Unplanned")
    if rollover.get("completed_project_status") != "Completed":
        raise ValueError("project rollover must complete the source project")
    if rollover.get("drift_result") != "ROLLOVER_DRIFT":
        raise ValueError("project rollover drift result must be ROLLOVER_DRIFT")
    if rollover.get("receipt_title_prefix") != "Project Rollover Receipt — ":
        raise ValueError("project rollover receipt title prefix is invalid")
    for field in (
        "required_fields",
        "project_fields",
        "capsule_fields",
        "initiative_fields",
        "roadmap_item_fields",
        "carryover_fields",
        "milestone_disposition_fields",
        "milestone_dispositions",
        "issue_disposition_fields",
        "issue_dispositions",
    ):
        values = rollover.get(field)
        if (
            not isinstance(values, list)
            or not values
            or not all(isinstance(value, str) and value for value in values)
        ):
            raise ValueError(f"project rollover requires {field}")
    expected_rollover_fields = {
        "schema_version",
        "run_id",
        "phase",
        "source_project",
        "successor_project",
        "next_release",
        "initiative",
        "source_snapshot_hash",
        "approved_plan_hash",
        "capsule",
        "roadmap_items",
        "carryovers",
        "milestone_dispositions",
        "issue_dispositions",
        "unresolved_source_items",
        "applied_operation_ids",
        "read_back_ids",
        "next_command",
        "updated_at",
    }
    exact_schemas = {
        "required_fields": expected_rollover_fields,
        "project_fields": {"project_id", "revision", "status"},
        "capsule_fields": {
            "document_id",
            "revision",
            "content_hash",
            "source_snapshot_hash",
            "status",
        },
        "initiative_fields": {
            "source_initiative_id",
            "requested_initiative_id",
            "successor_initiative_id",
            "warning",
        },
        "roadmap_item_fields": {
            "proposal_id",
            "successor_milestone_id",
            "objective",
            "read_back",
        },
        "carryover_fields": {
            "source_issue_id",
            "source_revision",
            "successor_issue_id",
            "successor_status",
            "provenance_linked",
            "read_back",
        },
        "milestone_disposition_fields": {
            "source_milestone_id",
            "disposition",
            "approved",
            "resolved",
        },
        "issue_disposition_fields": {
            "source_issue_id",
            "disposition",
            "approved",
            "resolved",
        },
    }
    for field, expected in exact_schemas.items():
        if set(rollover[field]) != expected:
            raise ValueError(f"project rollover {field} schema is invalid")
    if rollover["capsule_statuses"] != ["draft", "prepared", "finalized"]:
        raise ValueError("project rollover capsule statuses are invalid")
    if rollover["milestone_dispositions"] != ["wrapped", "archived", "canceled"]:
        raise ValueError("project rollover milestone dispositions are invalid")
    if rollover["issue_dispositions"] != ["completed", "superseded", "canceled"]:
        raise ValueError("project rollover issue dispositions are invalid")
    return contract


def parallel_execution_contract() -> dict[str, Any]:
    contract = load_json(PARALLEL_EXECUTION_PATH)
    if contract.get("schema_version") != 1:
        raise ValueError("parallel execution contract schema_version must be one")
    graph = contract.get("graph")
    footprint = contract.get("execution_footprint")
    waves = contract.get("waves")
    git = contract.get("git")
    single = contract.get("single_execution")
    isolation_receipt = contract.get("isolation_receipt")
    receipt = contract.get("wave_receipt")
    reconciliation = contract.get("reconciliation")
    if not all(
        isinstance(section, dict)
        for section in (
            graph,
            footprint,
            waves,
            git,
            single,
            isolation_receipt,
            receipt,
            reconciliation,
        )
    ):
        raise ValueError("parallel execution contract sections are incomplete")
    graph = cast(dict[str, Any], graph)
    footprint = cast(dict[str, Any], footprint)
    waves = cast(dict[str, Any], waves)
    git = cast(dict[str, Any], git)
    single = cast(dict[str, Any], single)
    isolation_receipt = cast(dict[str, Any], isolation_receipt)
    receipt = cast(dict[str, Any], receipt)
    reconciliation = cast(dict[str, Any], reconciliation)
    expected_graph_fields = {
        "schema_version",
        "project_id",
        "milestone_id",
        "graph_revision",
        "workflow_revision",
        "source_hash",
        "graph_hash",
        "review_status",
        "tasks",
        "hard_edges",
        "serialization_edges",
        "waves",
        "generated_at",
    }
    if set(graph.get("required_fields", [])) != expected_graph_fields:
        raise ValueError("dependency graph fields are incomplete")
    if graph.get("marker_name") != "linear-spanks:dependency-graph":
        raise ValueError("dependency graph marker name is invalid")
    if graph.get("drift_result") != "DEPENDENCY_GRAPH_DRIFT":
        raise ValueError("dependency graph drift result is invalid")
    if graph.get("max_write_retries") != 1:
        raise ValueError("dependency graph permits exactly one write retry")
    expected_footprint_fields = {
        "repository",
        "write_scopes",
        "exclusive_resources",
        "parallel_safe",
        "serialization_rationale",
    }
    if set(footprint.get("required_fields", [])) != expected_footprint_fields:
        raise ValueError("execution footprint fields are incomplete")
    if not all(
        footprint.get(rule) is True
        for rule in (
            "unknown_scope_serializes",
            "overlapping_scope_serializes",
            "overlapping_exclusive_resource_serializes",
            "paths_are_repository_relative",
        )
    ):
        raise ValueError("execution footprint serialization rules are incomplete")
    if waves.get("default_max_parallel") != 2:
        raise ValueError("parallel execution default must be two")
    if waves.get("hard_max_parallel") != 8:
        raise ValueError("parallel execution hard maximum must be eight")
    if waves.get("selection_input_fields") != ["graph", "live_statuses", "excluded_issue_ids"]:
        raise ValueError("parallel wave selection inputs are incomplete")
    if waves.get("incremental_selection_field") != "review_coverage_hashes":
        raise ValueError("incremental wave review coverage input is invalid")
    if waves.get("assurance") != "strict" or waves.get("fixed_frontier") is not True:
        raise ValueError("parallel waves must be strict and fixed-frontier")
    if git.get("parent_source") != "clean-current-branch-and-head":
        raise ValueError("parallel git parent must be the clean current branch")
    if git.get("worktree_policy") != "one-clean-worktree-per-task":
        raise ValueError("parallel tasks require isolated clean worktrees")
    if git.get("merge_strategy") != "merge-commit-no-ff":
        raise ValueError("parallel reconciliation requires merge commits")
    if git.get("executor_may_merge") is not False or git.get("executor_may_mark_done") is not False:
        raise ValueError("parallel executors may neither merge nor mark issues Done")
    if single.get("flag") != "--isolated-worktree":
        raise ValueError("single execution isolation flag is invalid")
    if single.get("optional_commands") != ["run-task", "implement-next"]:
        raise ValueError("single execution optional commands are invalid")
    if single.get("conditional_commands") != {"run-milestone": "start-implementation"}:
        raise ValueError("single execution conditional commands are invalid")
    if single.get("always_isolated_commands") != ["implement-wave"]:
        raise ValueError("single execution always-isolated commands are invalid")
    if single.get("not_applicable_result") != "ISOLATION_NOT_APPLICABLE":
        raise ValueError("single execution isolation result is invalid")
    if single.get("merge_strategy") != "merge-commit-no-ff":
        raise ValueError("single execution isolation requires merge commits")
    if single.get("integration_strategy") != "temporary-worktree-then-fast-forward-parent":
        raise ValueError("single execution integration strategy is invalid")
    if any(
        single.get(field) is not expected
        for field, expected in (
            ("preserve_child_branch", True),
            ("push_or_pr", False),
            ("cleanup_after_integrated_receipt", True),
            ("linear_done_after_parent_integration", True),
        )
    ):
        raise ValueError("single execution safety rules are incomplete")
    expected_isolation_fields = {
        "schema_version",
        "receipt_id",
        "run_id",
        "state",
        "command",
        "issue_id",
        "plan_revision",
        "source_hash",
        "parent_branch",
        "baseline_head",
        "repository_root",
        "worktree_root",
        "worktree_path",
        "child_branch",
        "child_commit",
        "verification",
        "integration",
        "completion",
        "failure",
        "created_at",
        "updated_at",
        "state_timestamps",
    }
    if set(isolation_receipt.get("required_fields", [])) != expected_isolation_fields:
        raise ValueError("isolation receipt fields are incomplete")
    expected_isolation_states = {
        "prepared",
        "executing",
        "verified-pending-integration",
        "integrating",
        "integrated",
        "failed",
    }
    if set(isolation_receipt.get("states", [])) != expected_isolation_states:
        raise ValueError("isolation receipt states are incomplete")
    transitions = isolation_receipt.get("transitions")
    if not isinstance(transitions, dict) or set(transitions) != expected_isolation_states:
        raise ValueError("isolation receipt transitions are incomplete")
    expected_receipt_fields = {
        "schema_version",
        "wave_id",
        "milestone_id",
        "graph_hash",
        "source_hash",
        "parent_branch",
        "baseline_head",
        "worktree_root",
        "requested_parallelism",
        "effective_parallelism",
        "state",
        "tasks",
        "created_at",
        "updated_at",
    }
    if set(receipt.get("required_fields", [])) != expected_receipt_fields:
        raise ValueError("wave receipt fields are incomplete")
    if reconciliation.get("approval") != "one-exact-wave-preview":
        raise ValueError("wave reconciliation approval is invalid")
    if reconciliation.get("linear_done_only_after_parent_integration") is not True:
        raise ValueError("issues may become Done only after parent integration")
    return contract


def project_orchestration_contract() -> dict[str, Any]:
    contract = load_json(PROJECT_ORCHESTRATION_PATH)
    if contract.get("schema_version") != 1:
        raise ValueError("project orchestration contract schema_version must be one")
    if contract.get("command") != "run-project":
        raise ValueError("project orchestration command must be run-project")
    if contract.get("session_boundary") != "single-event":
        raise ValueError("project orchestration must use the single-event boundary")
    if contract.get("results") != {
        "drift": "PROJECT_ORCHESTRATION_DRIFT",
        "ambiguous_receipt": "PROJECT_ORCHESTRATION_RECEIPT_AMBIGUOUS",
        "unauthorized_operation": "ROLE_CAPABILITY_VIOLATION",
        "invalid_handoff": "ROLE_HANDOFF_INVALID",
        "model_selection_required": "MODEL_SELECTION_REQUIRED",
        "context_overflow": "CONTEXT_OVERFLOW",
    }:
        raise ValueError("project orchestration result vocabulary is invalid")

    topology = contract.get("topology")
    roles = contract.get("roles")
    expected_roles = [
        "project-orchestrator",
        "milestone-orchestrator",
        "task-executor",
        "task-verifier",
    ]
    if not isinstance(topology, dict) or topology.get("roles") != expected_roles:
        raise ValueError("project orchestration topology roles are invalid")
    for field in (
        "project_orchestrators_per_project",
        "milestone_orchestrators_per_milestone",
        "task_executors_per_task",
        "task_verifiers_per_task",
    ):
        if topology.get(field) != 1:
            raise ValueError(f"project orchestration topology requires {field}=1")
    if topology.get("logical_identity_survives_session_refresh") is not True:
        raise ValueError("logical role identity must survive session refresh")
    if topology.get("cross_milestone_conflict_owner") != "project-orchestrator":
        raise ValueError("project orchestrator must own cross-milestone conflicts")
    if not isinstance(roles, dict) or list(roles) != expected_roles:
        raise ValueError("project orchestration role definitions are incomplete")
    expected_role_policies = {
        "project-orchestrator": (
            "high",
            "planner",
            "one-per-project",
            "none",
            "project",
            60000,
        ),
        "milestone-orchestrator": (
            "high",
            "planner",
            "one-per-milestone",
            "source-read-only-and-integration",
            "milestone",
            100000,
        ),
        "task-executor": (
            "plan-recommended",
            "executor",
            "one-per-task",
            "assigned-worktree-write",
            "task",
            120000,
        ),
        "task-verifier": (
            "risk-based",
            "reviewer",
            "when-required",
            "source-read-only-and-test-artifacts",
            "task",
            120000,
        ),
    }
    for role, expected in expected_role_policies.items():
        policy = roles[role]
        if not isinstance(policy, dict):
            raise ValueError(f"project orchestration role {role} must be an object")
        actual = (
            policy.get("strength"),
            policy.get("routing_role"),
            policy.get("cardinality"),
            policy.get("repository_access"),
            policy.get("context_profile"),
            policy.get("max_input_tokens"),
        )
        if actual != expected:
            raise ValueError(f"project orchestration role {role} policy is invalid")
        required = policy.get("required_context")
        allowed = policy.get("allowed_context")
        if not isinstance(required, list) or not required or len(required) != len(set(required)):
            raise ValueError(f"project orchestration role {role} requires unique context")
        if not isinstance(allowed, list) or not set(required).issubset(allowed):
            raise ValueError(f"project orchestration role {role} context is incomplete")

    event_selection = contract.get("event_selection")
    if not isinstance(event_selection, dict):
        raise ValueError("project orchestration requires event selection")
    events = event_selection.get("events")
    precedence = event_selection.get("precedence")
    if not isinstance(events, list) or len(events) != 11 or len(events) != len(set(events)):
        raise ValueError("project orchestration events are invalid")
    if not isinstance(precedence, list) or len(precedence) != len(events):
        raise ValueError("project orchestration event precedence is invalid")

    task_loop = contract.get("task_loop")
    if not isinstance(task_loop, dict):
        raise ValueError("project orchestration requires a task loop")
    rounds = task_loop.get("automatic_rounds")
    if not isinstance(rounds, list) or [item.get("round") for item in rounds] != [0, 1, 2, 3]:
        raise ValueError("task loop must define rounds zero through three")
    for index, round_policy in enumerate(rounds):
        expected_phase = "implementation" if index == 0 else "repair"
        if round_policy != {
            "round": index,
            "executor_phase": expected_phase,
            "executor_strength": "plan-recommended",
            "verifier_strength": "risk-based",
        }:
            raise ValueError(f"automatic task round {index} is invalid")
    if task_loop.get("max_automatic_executions") != 4:
        raise ValueError("task loop must permit four automatic executions")
    if task_loop.get("max_automatic_verifications") != 4:
        raise ValueError("task loop must permit four automatic verifications")
    if task_loop.get("max_injected_input_tokens") != 96000:
        raise ValueError("task loop automatic input ceiling must be 96000")
    if task_loop.get("automatic_failure_action") != "user-model-selection":
        raise ValueError("automatic exhaustion must require model selection")
    if task_loop.get("minimum_selected_model_strength") != "medium":
        raise ValueError("selected executor model must be medium or high")
    if task_loop.get("escalated_attempts_per_selection") != 1:
        raise ValueError("each user model selection must authorize one attempt")
    if task_loop.get("escalated_failure_action") != "user-model-selection":
        raise ValueError("escalated failures must return to model selection")
    if task_loop.get("no_automatic_stronger_model_retry") is not True:
        raise ValueError("stronger executor retries must be user-gated")
    if task_loop.get("selected_model_fields") != [
        "strength",
        "model",
        "harness",
        "capability",
        "configured",
    ]:
        raise ValueError("selected model fields are incomplete")

    ledger = contract.get("verification_ledger")
    expected_ledger_fields = {
        "schema_version",
        "ledger_id",
        "task_id",
        "verifier_id",
        "project_revision",
        "milestone_revision",
        "plan_revision",
        "source_revision",
        "candidate_commit",
        "reviewed_attempts",
        "acceptance_criteria",
        "findings",
        "verification_runs",
        "baseline_failures",
        "exclusions",
        "next_checks",
        "raw_executor_transcript_included",
        "required_verification_current",
        "final_result",
        "live_session",
        "updated_at",
    }
    if (
        not isinstance(ledger, dict)
        or set(ledger.get("required_fields", [])) != expected_ledger_fields
    ):
        raise ValueError("verification ledger fields are incomplete")
    if ledger.get("logical_identity") != "one-per-task":
        raise ValueError("verification ledger must preserve one verifier per task")
    if ledger.get("raw_executor_transcript_allowed") is not False:
        raise ValueError("verification ledger must reject raw executor transcripts")
    if ledger.get("max_raw_log_characters") != 2000:
        raise ValueError("verification ledger raw log ceiling must be 2000 characters")

    receipt = contract.get("project_loop_receipt")
    if not isinstance(receipt, dict):
        raise ValueError("project orchestration requires a project loop receipt")
    states = receipt.get("states")
    transitions = receipt.get("transitions")
    if not isinstance(states, list) or not isinstance(transitions, dict):
        raise ValueError("project loop receipt states are invalid")
    if set(transitions) != set(states):
        raise ValueError("project loop receipt transitions must cover every state")
    if not all(
        isinstance(targets, list) and set(targets).issubset(states)
        for targets in transitions.values()
    ):
        raise ValueError("project loop receipt transitions contain unknown states")
    if not set(receipt.get("active_states", [])).issubset(states):
        raise ValueError("project loop active states are invalid")
    expected_transition_fields = {
        "target_state",
        "current_project_revision",
        "current_source_hash",
        "current_dependency_graph_hash",
        "current_milestones",
        "current_task_loops",
        "current_human_verification_policies",
        "completed_event",
        "next_project_revision",
        "next_source_hash",
        "next_dependency_graph_hash",
        "next_milestones",
        "next_human_verification_policies",
        "next_task_loops",
        "next_budget",
        "next_event",
        "approval",
        "failure",
        "updated_at",
    }
    if set(receipt.get("transition_request_fields", [])) != expected_transition_fields:
        raise ValueError("project loop transition fields are incomplete")
    if receipt.get("preserve_existing_role_bindings") is not True:
        raise ValueError("project loop transitions must preserve logical role bindings")

    handoff = contract.get("role_handoff")
    if not isinstance(handoff, dict) or handoff.get("raw_transcript_allowed") is not False:
        raise ValueError("project orchestration role handoff is invalid")
    if not isinstance(handoff.get("required_fields"), list) or not handoff["required_fields"]:
        raise ValueError("project orchestration role handoff requires fields")

    capabilities = contract.get("capabilities")
    if not isinstance(capabilities, dict) or set(capabilities) != set(expected_roles):
        raise ValueError("project orchestration capabilities are incomplete")
    for role, capability in capabilities.items():
        if not isinstance(capability, dict) or not isinstance(capability.get("operations"), list):
            raise ValueError(f"project orchestration capability {role} is invalid")
        if not capability["operations"] or len(capability["operations"]) != len(
            set(capability["operations"])
        ):
            raise ValueError(f"project orchestration capability {role} operations are invalid")
        if not isinstance(capability.get("tracked_source_write"), bool):
            raise ValueError(f"project orchestration capability {role} requires source policy")

    scheduling = contract.get("scheduling")
    parallel = parallel_execution_contract()["waves"]
    if not isinstance(scheduling, dict):
        raise ValueError("project orchestration requires scheduling")
    if scheduling.get("default_max_parallel") != parallel["default_max_parallel"]:
        raise ValueError("project scheduling default must match parallel execution")
    if scheduling.get("hard_max_parallel") != parallel["hard_max_parallel"]:
        raise ValueError("project scheduling maximum must match parallel execution")
    if scheduling.get("fixed_task_frontier") is not True:
        raise ValueError("project task waves must use a fixed frontier")
    if contract.get("approval_gates") != [
        "project-scope-change",
        "milestone-create-or-material-revision",
        "task-plan-scope-change",
        "exact-git-integration-preview",
        "stronger-executor-model-selection",
        "human-verification-policy-change-or-bypass",
    ]:
        raise ValueError("project orchestration approval gates are invalid")
    return contract


def milestone_orchestration_contract() -> dict[str, Any]:
    """Load the milestone controller while sharing task-pair policy with run-project."""
    contract = load_json(MILESTONE_ORCHESTRATION_PATH)
    project = project_orchestration_contract()
    if contract.get("schema_version") != 1:
        raise ValueError("milestone orchestration contract schema_version must be one")
    if contract.get("command") != "run-milestone-loop":
        raise ValueError("milestone orchestration command must be run-milestone-loop")
    if contract.get("session_boundary") != "single-event":
        raise ValueError("milestone orchestration must use the single-event boundary")
    if contract.get("shared_task_policy") != PROJECT_ORCHESTRATION_PATH.name:
        raise ValueError("milestone orchestration must share the project task policy")
    if contract.get("results") != {
        "drift": "MILESTONE_ORCHESTRATION_DRIFT",
        "ambiguous_receipt": "MILESTONE_ORCHESTRATION_RECEIPT_AMBIGUOUS",
        "scope_conflict": "ORCHESTRATION_SCOPE_CONFLICT",
        "project_coordination_required": "PROJECT_COORDINATION_REQUIRED",
    }:
        raise ValueError("milestone orchestration result vocabulary is invalid")
    topology = contract.get("topology")
    roles = ["milestone-orchestrator", "task-executor", "task-verifier"]
    if not isinstance(topology, dict) or topology.get("roles") != roles:
        raise ValueError("milestone orchestration topology roles are invalid")
    for field in (
        "milestone_orchestrators_per_milestone",
        "task_executors_per_task",
        "task_verifiers_per_task",
    ):
        if topology.get(field) != 1:
            raise ValueError(f"milestone orchestration requires {field}=1")
    if topology.get("logical_identity_survives_session_refresh") is not True:
        raise ValueError("milestone role identity must survive session refresh")
    if topology.get("project_level_conflict_owner") != "project-orchestrator":
        raise ValueError("project orchestrator must own milestone loop conflicts")
    events = contract.get("event_selection")
    if not isinstance(events, dict) or not isinstance(events.get("events"), list):
        raise ValueError("milestone orchestration requires event selection")
    if len(events["events"]) != 11 or len(events["events"]) != len(set(events["events"])):
        raise ValueError("milestone orchestration events are invalid")
    if not isinstance(events.get("precedence"), list) or len(events["precedence"]) != 11:
        raise ValueError("milestone orchestration event precedence is invalid")
    receipt = contract.get("milestone_loop_receipt")
    if not isinstance(receipt, dict):
        raise ValueError("milestone orchestration requires a receipt schema")
    expected_receipt_fields = {
        "schema_version",
        "receipt_id",
        "state",
        "project_id",
        "project_revision",
        "milestone_id",
        "milestone_revision",
        "milestone_orchestrator_id",
        "source_hash",
        "dependency_graph_hash",
        "human_verification_policy",
        "task_loops",
        "current_event",
        "next_event",
        "approval",
        "budget",
        "created_at",
        "updated_at",
        "state_timestamps",
        "failure",
    }
    if set(receipt.get("required_fields", [])) != expected_receipt_fields:
        raise ValueError("milestone orchestration receipt fields are incomplete")
    if receipt.get("document_marker") != "linear-spanks:milestone-orchestration-receipt":
        raise ValueError("milestone orchestration receipt marker is invalid")
    states = receipt.get("states")
    transitions = receipt.get("transitions")
    if (
        not isinstance(states, list)
        or not isinstance(transitions, dict)
        or set(transitions) != set(states)
    ):
        raise ValueError("milestone orchestration receipt transitions are invalid")
    if not all(
        isinstance(targets, list) and set(targets).issubset(states)
        for targets in transitions.values()
    ):
        raise ValueError("milestone orchestration receipt transitions contain unknown states")
    if not set(receipt.get("active_states", [])).issubset(states):
        raise ValueError("milestone orchestration active states are invalid")
    if receipt.get("task_loop_fields") != project["project_loop_receipt"]["task_loop_fields"]:
        raise ValueError("milestone task loop receipt schema must match run-project")
    if receipt.get("task_loop_states") != project["project_loop_receipt"]["task_loop_states"]:
        raise ValueError("milestone task loop states must match run-project")
    if receipt.get("approval_fields") != project["project_loop_receipt"]["approval_fields"]:
        raise ValueError("milestone approval schema must match run-project")
    if receipt.get("approval_statuses") != project["project_loop_receipt"]["approval_statuses"]:
        raise ValueError("milestone approval states must match run-project")
    if receipt.get("budget_fields") != project["project_loop_receipt"]["budget_fields"]:
        raise ValueError("milestone budget schema must match run-project")
    expected_transition_fields = {
        "target_state",
        "current_project_revision",
        "current_milestone_revision",
        "current_source_hash",
        "current_dependency_graph_hash",
        "current_task_loops",
        "current_human_verification_policy",
        "completed_event",
        "next_project_revision",
        "next_milestone_revision",
        "next_source_hash",
        "next_dependency_graph_hash",
        "next_human_verification_policy",
        "next_task_loops",
        "next_budget",
        "next_event",
        "approval",
        "failure",
        "updated_at",
    }
    if set(receipt.get("transition_request_fields", [])) != expected_transition_fields:
        raise ValueError("milestone orchestration transition fields are incomplete")
    scheduling = contract.get("scheduling")
    parallel = parallel_execution_contract()["waves"]
    if not isinstance(scheduling, dict) or (
        scheduling.get("default_max_parallel"),
        scheduling.get("hard_max_parallel"),
    ) != (parallel["default_max_parallel"], parallel["hard_max_parallel"]):
        raise ValueError("milestone orchestration scheduling must match parallel execution")
    if (
        scheduling.get("fixed_task_frontier") is not True
        or scheduling.get("isolated_worktrees_required") is not True
    ):
        raise ValueError("milestone orchestration requires isolated fixed frontiers")
    if contract.get("supervisor") != {
        "legacy_single_event_without_until": True,
        "autopilot_alias": "run-milestone --autopilot",
        "default_until": ["approval-required", "blocked", "milestone-done"],
        "default_max_events": 20,
        "hard_max_events": 100,
        "fresh_session_per_event": True,
        "receipt_read_back_per_event": True,
        "repair_safe_flag": "--repair-safe",
        "isolated_worktree_assertion": "idempotent",
    }:
        raise ValueError("milestone orchestration supervisor policy is invalid")
    if contract.get("approval_gates") != [
        "milestone-material-revision",
        "task-plan-scope-change",
        "dependency-or-product-change",
        "authorization-change",
        "migration-or-schema-source-change",
        "external-irreversible-write",
        "exact-git-integration-preview",
        "stronger-executor-model-selection",
        "human-verification-policy-change-or-bypass",
        "merge-or-push",
    ]:
        raise ValueError("milestone orchestration approval gates are invalid")
    if contract.get("wrap") != {
        "allows_milestone_retrospective": True,
        "allows_project_learning_curation": False,
        "project_handoff": "candidate-learnings-only",
    }:
        raise ValueError("milestone orchestration wrap boundary is invalid")
    effective = dict(contract)
    effective["roles"] = {role: project["roles"][role] for role in roles}
    effective["task_loop"] = project["task_loop"]
    effective["verification_ledger"] = project["verification_ledger"]
    effective["role_handoff"] = project["role_handoff"]
    effective["capabilities"] = {role: project["capabilities"][role] for role in roles}
    return effective


def execution_contract() -> dict[str, Any]:
    contract = load_json(EXECUTION_PATH)
    routing = routing_contract()
    repository_scan = repository_scan_contract()
    project_epoch = project_epoch_contract()
    parallel_execution = parallel_execution_contract()
    project_orchestration = project_orchestration_contract()
    milestone_orchestration = milestone_orchestration_contract()
    commands = load_json(COMMANDS_PATH).get("commands", [])
    issue_transitions = issue_workflow_contract()["transitions"]
    command_names = {command.get("name") for command in commands}
    configured = contract.get("commands")
    contexts = contract.get("context_profiles")
    executions = contract.get("execution_profiles")
    runtime_cards = contract.get("runtime_cards")
    if not isinstance(configured, dict) or set(configured) != command_names:
        missing = sorted(command_names - set(configured or {}))
        extra = sorted(set(configured or {}) - command_names)
        raise ValueError(f"execution command coverage mismatch; missing={missing}, extra={extra}")
    if not isinstance(contexts, dict) or not isinstance(executions, dict):
        raise ValueError("execution contract requires context_profiles and execution_profiles")
    if not isinstance(runtime_cards, dict):
        raise ValueError("execution contract requires runtime_cards")
    if set(runtime_cards.get("task_commands", [])) != TASK_RUNTIME_COMMANDS:
        raise ValueError("runtime card task command coverage is incomplete")
    cards = runtime_cards.get("phases")
    if not isinstance(cards, dict) or set(cards) != TASK_RUNTIME_COMMANDS:
        raise ValueError("runtime cards must cover every optimized task command")
    if (
        not isinstance(runtime_cards.get("shared_safety_gates"), list)
        or len(runtime_cards["shared_safety_gates"]) < 8
    ):
        raise ValueError("runtime cards require the shared safety gates")
    for name, card in cards.items():
        if not isinstance(card, dict):
            raise ValueError(f"runtime card {name} must be an object")
        if not isinstance(card.get("roles"), list) or not card["roles"]:
            raise ValueError(f"runtime card {name} requires roles")
        if not isinstance(card.get("skills"), list) or not card["skills"]:
            raise ValueError(f"runtime card {name} requires skills")
        if not isinstance(card.get("verification"), str) or not card["verification"]:
            raise ValueError(f"runtime card {name} requires verification")
    orchestration_profiles = routing["orchestration_profiles"]
    configured_orchestration = {
        name for name, configuration in configured.items() if "orchestration" in configuration
    }
    if configured_orchestration != ORCHESTRATED_COMMANDS:
        missing = sorted(ORCHESTRATED_COMMANDS - configured_orchestration)
        extra = sorted(configured_orchestration - ORCHESTRATED_COMMANDS)
        raise ValueError(
            f"orchestration command coverage mismatch; missing={missing}, extra={extra}"
        )
    for name, profile in contexts.items():
        if not isinstance(profile, dict) or not profile:
            raise ValueError(f"context profile {name} must be a non-empty object")
        for limit, value in profile.items():
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"context profile {name} limit {limit} must be a positive integer")

    for name, configuration in configured.items():
        if not isinstance(configuration, dict):
            raise ValueError(f"execution configuration for {name} must be an object")
        if configuration.get("context") not in contexts:
            raise ValueError(f"unknown context profile for {name}: {configuration.get('context')}")
        if configuration.get("execution") not in executions:
            raise ValueError(
                f"unknown execution profile for {name}: {configuration.get('execution')}"
            )
        if (
            "orchestration" in configuration
            and configuration["orchestration"] not in orchestration_profiles
        ):
            raise ValueError(
                f"unknown orchestration profile for {name}: {configuration.get('orchestration')}"
            )
        if configuration.get("session_boundary") not in {
            "single-command",
            "single-stage",
            "single-task",
            "single-phase",
            "single-wave",
            "single-event",
        }:
            raise ValueError(f"invalid session boundary for {name}")
        command = next(command for command in commands if command.get("name") == name)
        issue_transition = command.get("issue_transition")
        if issue_transition is not None and issue_transition not in issue_transitions:
            raise ValueError(f"unknown issue transition for {name}: {issue_transition}")
        if "bulk" in configuration and not isinstance(configuration["bulk"], bool):
            raise ValueError(f"execution configuration for {name} has invalid bulk flag")
        scan_configuration = configuration.get("repository_scan")
        if scan_configuration is not None:
            if not isinstance(scan_configuration, dict) or set(scan_configuration) != {
                "default_tier"
            }:
                raise ValueError(f"repository scan configuration for {name} is invalid")
            if scan_configuration["default_tier"] not in repository_scan["tiers"]:
                raise ValueError(f"repository scan configuration for {name} has invalid tier")
        for field in ("reads", "writes", "postconditions"):
            if field in configuration and not isinstance(configuration[field], list):
                raise ValueError(f"execution configuration for {name} requires a {field} list")

    for name, profile in executions.items():
        if not isinstance(profile, dict):
            raise ValueError(f"execution profile {name} must be an object")
        approval = profile.get("approval")
        if not isinstance(approval, dict) or approval.get("kind") not in APPROVAL_KINDS:
            raise ValueError(f"execution profile {name} has an invalid approval policy")
        if approval.get("kind") == "staged":
            stages = approval.get("stages")
            if (
                not isinstance(stages, dict)
                or not stages
                or not all(
                    isinstance(stage, str) and stage and gate in {"invocation", "preview"}
                    for stage, gate in stages.items()
                )
            ):
                raise ValueError(f"execution profile {name} has invalid staged approval")
            if name == "staged_import" and stages != {
                "analysis_checkpoint": "invocation",
                "linear_project_and_milestones": "preview",
            }:
                raise ValueError("staged import approval phases are invalid")
            if name == "staged_rollover" and set(stages) != {
                "inventory",
                "successor_project",
                "successor_roadmap",
                "carryover_issues",
                "source_dispositions",
                "source_completion",
            }:
                raise ValueError("staged rollover approval phases are invalid")
        for field in ("reads", "writes", "postconditions"):
            if not isinstance(profile.get(field), list):
                raise ValueError(f"execution profile {name} requires a {field} list")
    compaction = contexts.get("project_compaction")
    capsule = project_epoch["capsule"]
    if compaction != {
        "max_input_tokens": 16000,
        "max_inventory_batches": capsule["inventory"]["max_batches"],
        "max_compact_rows_per_batch": capsule["inventory"]["max_compact_rows_per_batch"],
        "max_full_entities_per_batch": capsule["inventory"]["max_full_entities_per_batch"],
        "max_capsule_bytes": capsule["max_body_bytes"],
    }:
        raise ValueError("project compaction context must match the project epoch contract")
    for name in ("implement-wave", "reconcile-wave"):
        if configured[name].get("session_boundary") != "single-wave":
            raise ValueError(f"{name} must use the single-wave session boundary")
    if parallel_execution["waves"]["assurance"] != "strict":
        raise ValueError("parallel commands require strict assurance")
    if (
        configured["run-project"].get("session_boundary")
        != project_orchestration["session_boundary"]
    ):
        raise ValueError("run-project must use the project orchestration boundary")
    if (
        configured["run-milestone-loop"].get("session_boundary")
        != milestone_orchestration["session_boundary"]
    ):
        raise ValueError("run-milestone-loop must use the milestone orchestration boundary")
    for role in project_orchestration["roles"].values():
        profile = contexts[role["context_profile"]]
        if role["max_input_tokens"] != profile["max_input_tokens"]:
            raise ValueError("project orchestration role context must match execution limits")
    for role in milestone_orchestration["roles"].values():
        profile = contexts[role["context_profile"]]
        if role["max_input_tokens"] != profile["max_input_tokens"]:
            raise ValueError("milestone orchestration role context must match execution limits")
    return contract


def _validate_legacy_manifest() -> None:
    commands = load_json(COMMANDS_PATH).get("commands")
    workflow = load_json(WORKFLOW_PATH)
    if not isinstance(commands, list):
        raise ValueError("commands.json must contain a commands array")
    transitions = workflow.get("transitions")
    if not isinstance(transitions, dict):
        raise ValueError("workflow contract requires transitions")
    issue_transitions = issue_workflow_contract()["transitions"]
    names: set[str] = set()
    for command in commands:
        if not isinstance(command, dict):
            raise ValueError("every command must be an object")
        name = command.get("name")
        if not isinstance(name, str) or not name or name in names:
            raise ValueError(f"invalid or duplicated command: {name}")
        names.add(name)
        if command.get("access") not in {"read", "write", "conditional"}:
            raise ValueError(f"command {name} has invalid access")
        declared = command.get("transitions")
        if declared is not None:
            if (
                not isinstance(declared, list)
                or not declared
                or not all(isinstance(item, str) and item for item in declared)
            ):
                raise ValueError(f"command {name} has invalid transitions")
            command_transitions = set(declared)
        else:
            transition = command.get("transition")
            command_transitions = (
                {transition} if isinstance(transition, str) and transition else set()
            )
        for transition in command_transitions:
            if transition not in transitions:
                raise ValueError(f"command {name} has unknown transition: {transition}")
        issue_transition = command.get("issue_transition")
        if issue_transition is not None:
            if issue_transition not in issue_transitions:
                raise ValueError(f"command {name} has unknown issue transition: {issue_transition}")
            if name not in issue_transitions[issue_transition]["commands"]:
                raise ValueError(
                    f"command {name} is not allowed for issue transition {issue_transition}"
                )
    declared_issue_commands = {
        command for transition in issue_transitions.values() for command in transition["commands"]
    }
    configured_issue_commands = {
        command["name"] for command in commands if command.get("issue_transition")
    }
    if declared_issue_commands != configured_issue_commands:
        raise ValueError("issue transition command coverage mismatch")


def validate_contract_documents(documents: Mapping[str, Mapping[str, Any]]) -> None:
    token = _ACTIVE_DOCUMENTS.set(documents)
    try:
        for name, document in documents.items():
            schema_version = document.get("schema_version")
            if (
                not isinstance(schema_version, int)
                or isinstance(schema_version, bool)
                or schema_version <= 0
            ):
                raise ValueError(f"{name} requires a positive integer schema_version")
        _validate_legacy_manifest()
        human_verification_contract()
        milestone_review_contract()
        milestone_runtime_contract()
        routing_contract()
        repository_scan_contract()
        project_epoch_contract()
        parallel_execution_contract()
        project_orchestration_contract()
        milestone_orchestration_contract()
        execution_contract()
    except (KeyError, TypeError, ValueError) as error:
        raise UsageError("INVALID_CONTRACT_SET", str(error)) from error
    finally:
        _ACTIVE_DOCUMENTS.reset(token)
