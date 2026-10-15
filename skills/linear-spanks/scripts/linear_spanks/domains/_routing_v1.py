"""Versioned routing, assurance, and context-budget semantics."""

from __future__ import annotations

from typing import Any

from ..contracts.legacy import execution_contract, routing_contract
from ..core.hashing import sha256_digest
from ..core.legacy_constants import (
    ASSURANCE_VALUES,
    HARNESS_ALIASES,
    ORCHESTRATED_COMMANDS,
    REPOSITORY_SCAN_TIERS,
    ROUTING_HARNESSES,
)
from .execution import execution_envelope, planner_batches, validate_preflight_receipt


def task_execution_policy(payload: dict[str, Any]) -> dict[str, Any]:
    """Resolve once for standalone tasks and children of either orchestrator."""
    if set(payload) != {"assessment", "assurance"}:
        raise ValueError("task policy requires assessment and assurance")
    requested = payload["assurance"]
    if requested not in ASSURANCE_VALUES:
        raise ValueError(f"unknown assurance profile: {requested}")
    risk = tier_recommendation(payload["assessment"])
    contract = routing_contract()["assurance"]
    reasons = sorted(set(risk["active_dimensions"]) & set(contract["strict_escalation_dimensions"]))
    if payload["assessment"]["uncertainty"]:
        reasons.append("uncertainty")
    effective = requested
    if effective == "fast" and risk["executor_tier"] != "low":
        effective = "balanced"
    if reasons:
        effective = "strict"
    small = effective != "strict" and risk["executor_tier"] == "low"
    review = risk["review"]
    if effective == "strict":
        review = {
            "required": True,
            "independent": True,
            "strength": "high",
            "reason": "strict assurance requires independent high review",
        }
    body = {
        "schema_version": 1,
        "input": payload,
        "execution_path": "small-change" if small else "planned",
        "effective_assurance": effective,
        "executor_strength": risk["executor_tier"],
        "review": review,
        "planner_strength": None if small else "high",
        "reasons": reasons or risk["tier_rationale"],
    }
    return {**body, "policy_hash": sha256_digest(body)}


def validate_task_policy(policy: dict[str, Any]) -> dict[str, Any]:
    expected = task_execution_policy(policy["input"])
    if policy != expected:
        raise ValueError("TASK_POLICY_DRIFT: recompute the task execution policy")
    return expected


def _validate_decision_scope(
    name: str,
    scope: str,
    payload: dict[str, Any] | None,
    scan_tier: str | None,
    exact_required: bool,
) -> dict[str, Any] | None:
    if payload is None:
        if exact_required:
            raise ValueError(f"orchestration decision requires measured {scope} context")
        return None
    if set(payload) != {"estimated_tokens", "context_bytes", "metrics", "measured"}:
        raise ValueError(
            f"orchestration {scope} context requires estimated_tokens, context_bytes, "
            "metrics, and measured"
        )
    estimated_tokens = payload["estimated_tokens"]
    context_bytes = payload["context_bytes"]
    metrics = payload["metrics"]
    measured = payload["measured"]
    if (
        not isinstance(estimated_tokens, int)
        or isinstance(estimated_tokens, bool)
        or estimated_tokens < 0
    ):
        raise ValueError(f"orchestration {scope} estimated_tokens must be non-negative")
    if not isinstance(context_bytes, int) or isinstance(context_bytes, bool) or context_bytes < 0:
        raise ValueError(f"orchestration {scope} context_bytes must be non-negative")
    if not isinstance(metrics, dict) or not all(
        isinstance(key, str)
        and isinstance(value, int)
        and not isinstance(value, bool)
        and value >= 0
        for key, value in metrics.items()
    ):
        raise ValueError(f"orchestration {scope} metrics must be non-negative integers")
    if not isinstance(measured, bool):
        raise ValueError(f"orchestration {scope} measured must be a boolean")
    if exact_required and not measured:
        raise ValueError(f"orchestration decision requires exact measured {scope} context")
    envelope = execution_envelope(name, scan_tier)
    if scope == "command":
        limits = envelope["context"]
    elif scope == "planner":
        limits = envelope["orchestration"]["planner"]["context"]
    else:
        limits = envelope["repository_scan"]["context"]
    required_metrics = set(limits) - {"profile", "max_input_tokens"}
    if measured and set(metrics) != required_metrics:
        missing = sorted(required_metrics - set(metrics))
        extra = sorted(set(metrics) - required_metrics)
        raise ValueError(f"exact {scope} context metric mismatch; missing={missing}, extra={extra}")
    measured_estimate = (context_bytes + 3) // 4
    validation = validate_context_usage(
        name,
        max(estimated_tokens, measured_estimate),
        [f"{key}={value}" for key, value in sorted(metrics.items())],
        scope,
        scan_tier,
    )
    if measured and estimated_tokens != measured_estimate:
        raise ValueError(
            "CONTEXT_MEASUREMENT_MISMATCH: declared estimate differs from serialized context bytes"
        )
    return {**validation, "context_bytes": context_bytes, "measured": measured}


def orchestration_decision(payload: dict[str, Any]) -> dict[str, Any]:
    required_fields = {
        "schema_version",
        "command",
        "requested_assurance",
        "harness",
        "scan_tier",
        "context",
        "assessment",
        "current_plan",
        "detected_drift",
        "preflight",
        "planning_tasks",
    }
    if set(payload) != required_fields:
        missing = sorted(required_fields - set(payload))
        extra = sorted(set(payload) - required_fields)
        raise ValueError(f"orchestration decision field mismatch; missing={missing}, extra={extra}")
    if payload["schema_version"] != 1:
        raise ValueError("unsupported orchestration decision schema_version")
    name = payload["command"]
    if name not in ORCHESTRATED_COMMANDS:
        raise ValueError(f"command {name} does not support orchestration decisions")
    requested = payload["requested_assurance"]
    if requested not in ASSURANCE_VALUES:
        raise ValueError(f"unknown assurance profile: {requested}")
    normalized_harness = HARNESS_ALIASES.get(payload["harness"], payload["harness"])
    if normalized_harness not in ROUTING_HARNESSES:
        raise ValueError(f"unknown routing harness: {normalized_harness}")
    scan_tier = payload["scan_tier"]
    configuration = execution_contract()["commands"][name]
    if "repository_scan" in configuration:
        if scan_tier not in REPOSITORY_SCAN_TIERS:
            raise ValueError(f"command {name} requires a repository scan tier")
    elif scan_tier is not None:
        raise ValueError(f"command {name} does not read repository code")
    detected_drift = payload["detected_drift"]
    if isinstance(detected_drift, bool):
        drift_classification = "material" if detected_drift else "valid"
    elif isinstance(detected_drift, str) and detected_drift in {
        "valid",
        "safe-refresh",
        "material",
    }:
        drift_classification = detected_drift
    else:
        raise ValueError("detected_drift must be a boolean or valid, safe-refresh, or material")
    material_drift = drift_classification == "material"
    safe_refresh_drift = drift_classification == "safe-refresh"

    risk = tier_recommendation(payload["assessment"])
    active_dimensions = set(risk["active_dimensions"])
    assurance_contract = routing_contract()["assurance"]
    strict_reasons = sorted(
        active_dimensions & set(assurance_contract["strict_escalation_dimensions"])
    )
    if payload["assessment"]["uncertainty"]:
        strict_reasons.append("uncertainty")
    if material_drift:
        strict_reasons.append("detected_drift")
    escalation_reasons: list[str] = []
    effective = requested
    if effective == "fast" and risk["executor_tier"] != "low":
        effective = "balanced"
        escalation_reasons.append("fast_requires_deterministic_low_risk")
    if effective in {"fast", "balanced"} and strict_reasons:
        if effective == "fast":
            escalation_reasons.append("fast_escalated_through_balanced")
        effective = "strict"
        escalation_reasons.extend(strict_reasons)

    current_plan = payload["current_plan"]
    if not isinstance(current_plan, dict) or set(current_plan) != {
        "present",
        "stale",
        "revision",
    }:
        raise ValueError("current_plan requires exactly present, stale, and revision")
    if not isinstance(current_plan["present"], bool) or not isinstance(current_plan["stale"], bool):
        raise ValueError("current_plan present and stale must be booleans")
    if current_plan["present"]:
        if not isinstance(current_plan["revision"], str) or not current_plan["revision"]:
            raise ValueError("a present current plan requires a revision")
    elif current_plan["revision"] is not None:
        raise ValueError("an absent current plan must have a null revision")

    planning_tasks = payload["planning_tasks"]
    if not isinstance(planning_tasks, list):
        raise ValueError("planning_tasks must be a list")
    batches = planner_batches(planning_tasks, effective) if name == "plan-tasks" else []
    if name == "plan-tasks" and not batches:
        raise ValueError("plan-tasks requires at least one planning task")
    if name != "plan-tasks" and planning_tasks:
        raise ValueError(f"command {name} does not accept planning_tasks")

    plan_needed = name in {"plan-task", "plan-tasks", "replan-task"} or (
        name in {"run-task", "implement-next"}
        and (not current_plan["present"] or current_plan["stale"])
    )
    policy = task_execution_policy(
        {
            "assessment": payload["assessment"],
            "assurance": effective if material_drift else requested,
        }
    )
    small_change = policy["execution_path"] == "small-change" and not material_drift
    if small_change:
        planner_strength = None
        planner_role = "coordinator"
        planner_runs = 0
    else:
        planner_strength = (
            "medium" if effective == "balanced" and risk["executor_tier"] == "low" else "high"
        )
        planner_role = "planner"
        planner_runs = (len(batches) if batches else 1) if plan_needed else 0

    context = payload["context"]
    if not isinstance(context, dict) or set(context) != {
        "command",
        "planner",
        "repository",
        "large_matrix",
        "near_limit",
    }:
        raise ValueError(
            "orchestration context requires command, planner, repository, large_matrix, "
            "and near_limit"
        )
    if not isinstance(context["large_matrix"], bool) or not isinstance(context["near_limit"], bool):
        raise ValueError("large_matrix and near_limit must be booleans")
    triggered_exact = context["large_matrix"] or context["near_limit"]
    execution_drift = configuration["orchestration"] == "task-execution" and (
        material_drift or safe_refresh_drift
    )
    command_exact = not (material_drift and execution_drift) and (
        effective == "strict" or (effective == "balanced" and triggered_exact)
    )
    if execution_drift:
        planner_runs = 0
    planner_exact = planner_runs > 0 and command_exact
    repository_exact = "repository_scan" in configuration
    context_results = {
        "command": _validate_decision_scope(
            name, "command", context["command"], scan_tier, command_exact
        ),
        "planner": _validate_decision_scope(
            name,
            "planner",
            context["planner"],
            scan_tier,
            planner_exact,
        )
        if planner_runs > 0
        else None,
        "repository": _validate_decision_scope(
            name,
            "repository",
            context["repository"],
            scan_tier,
            repository_exact,
        )
        if repository_exact
        else None,
    }
    if not repository_exact and context["repository"] is not None:
        raise ValueError("repository context supplied for a command without repository scan")

    preflight_payload = payload["preflight"]
    preflight_result: dict[str, Any] = {
        "reused": False,
        "status": "not-supplied",
        "invalidated_by": [],
    }
    if preflight_payload is not None:
        if name not in {"implement-next", "run-task"}:
            raise ValueError(f"command {name} does not accept a preflight receipt")
        if not isinstance(preflight_payload, dict) or set(preflight_payload) != {
            "receipt",
            "current",
        }:
            raise ValueError("preflight requires exactly receipt and current")
        preflight_result = validate_preflight_receipt(
            preflight_payload["receipt"], preflight_payload["current"]
        )
        current_preflight = preflight_payload["current"]
        expected_preflight = {
            "harness": normalized_harness,
            "requested_assurance": requested,
            "effective_assurance": effective,
            "scan_tier": scan_tier,
            "plan_revision": current_plan["revision"] or "none",
        }
        decision_mismatches = sorted(
            field
            for field, expected in expected_preflight.items()
            if (
                HARNESS_ALIASES.get(current_preflight[field], current_preflight[field])
                if field == "harness"
                else current_preflight[field]
            )
            != expected
        )
        if decision_mismatches:
            preflight_result = {
                "reused": False,
                "status": routing_contract()["preflight_receipt"]["invalid_result"],
                "invalidated_by": sorted(
                    set(preflight_result["invalidated_by"]) | set(decision_mismatches)
                ),
            }
        if material_drift:
            preflight_result = {
                "reused": False,
                "status": routing_contract()["preflight_receipt"]["invalid_result"],
                "invalidated_by": sorted(
                    set(preflight_result["invalidated_by"]) | {"detected_drift"}
                ),
            }
        elif safe_refresh_drift:
            preflight_result = {
                "reused": False,
                "status": routing_contract()["preflight_receipt"]["invalid_result"],
                "invalidated_by": sorted(
                    set(preflight_result["invalidated_by"]) | {"safe-refresh"}
                ),
            }

    routes: list[dict[str, Any]] = []
    if (
        planner_runs > 0
        and planner_strength is not None
        and not (
            (material_drift or safe_refresh_drift)
            and configuration["orchestration"] == "task-execution"
        )
    ):
        routes.append(
            routing_check(payload["harness"], "planner", planner_strength, None, effective)
        )
    orchestration_profile = configuration["orchestration"]
    stop_result = None
    if orchestration_profile == "task-execution":
        if material_drift:
            stop_result = "REPLAN_REQUIRED"
        elif safe_refresh_drift:
            stop_result = "SAFE_REFRESH_REQUIRED"
    refresh_needed = safe_refresh_drift and orchestration_profile == "task-execution"
    if refresh_needed:
        stop_result = None
    if stop_result is not None or refresh_needed:
        planner_runs = 0
    if orchestration_profile == "task-execution" and stop_result is None and not refresh_needed:
        routes.append(
            routing_check(payload["harness"], "executor", risk["executor_tier"], None, effective)
        )
    review = policy["review"]
    if effective == "fast":
        review = {
            "required": False,
            "independent": False,
            "strength": None,
            "reason": "fast is eligible only for deterministic low-risk self-verifying work",
        }
    if orchestration_profile == "task-verification" and not review["required"]:
        routes.append(
            routing_check(payload["harness"], "executor", risk["executor_tier"], None, effective)
        )
    reviewer_runs = (
        1
        if review["required"]
        and orchestration_profile in {"task-execution", "task-verification"}
        and stop_result is None
        and not refresh_needed
        else 0
    )
    if reviewer_runs:
        routes.append(
            routing_check(payload["harness"], "reviewer", review["strength"], None, effective)
        )
    delegated_roles = sorted({route["role"] for route in routes})
    context_bytes = sum(
        result["context_bytes"] for result in context_results.values() if result is not None
    )
    return {
        "execution_policy": policy,
        "execution_path": policy["execution_path"],
        "dispatch_ready": stop_result is None and not refresh_needed,
        "next_action": "refresh-evidence"
        if refresh_needed
        else "replan"
        if stop_result
        else "continue",
        "refresh_requires": ["fresh-sources", "guarded-write", "durable-read-back", "recompile"]
        if refresh_needed
        else [],
        "routing_contract_version": routing_contract()["schema_version"],
        "command": name,
        "requested_assurance": requested,
        "effective_assurance": effective,
        "assurance_escalation_reason": escalation_reasons or None,
        "assurance_profile": assurance_contract["profiles"][effective],
        "safety_invariants": assurance_contract["safety_invariants"],
        "risk": risk,
        "planner": {
            "role": planner_role,
            "strength": planner_strength,
            "runs": planner_runs,
            "batches": batches,
            "per_task_outputs": routing_contract()["planner_batching"]["per_task_outputs"],
        },
        "review": review,
        "reviewer_runs": reviewer_runs,
        "stop_result": stop_result,
        "routes": routes,
        "delegated_roles": delegated_roles,
        "context": context_results,
        "context_bytes": context_bytes,
        "linear_verification": assurance_contract["linear_verification"][
            "bulk_fast_balanced"
            if configuration.get("bulk") and effective in {"fast", "balanced"}
            else effective
        ],
        "preflight": preflight_result,
        "drift_classification": drift_classification,
        "completion_receipt_fields": routing_contract()["completion_receipt"][
            "required_routing_fields"
        ],
    }


def validate_context_usage(
    name: str,
    estimated_tokens: int,
    metrics: list[str],
    scope: str = "command",
    scan_tier: str | None = None,
) -> dict[str, Any]:
    if estimated_tokens < 0:
        raise ValueError("estimated tokens must be non-negative")
    envelope = execution_envelope(name, scan_tier)
    if scope == "command":
        context = envelope["context"]
        context_name = context["profile"]
    elif scope == "planner":
        orchestration = envelope.get("orchestration")
        if not isinstance(orchestration, dict):
            raise ValueError(f"command {name} has no planner context")
        context = orchestration["planner"]["context"]
        context_name = "planner"
    elif scope == "repository":
        scan = envelope.get("repository_scan")
        if not isinstance(scan, dict):
            raise ValueError(f"command {name} has no repository scan context")
        context = scan["context"]
        context_name = f"repository:{scan['tier']}"
    else:
        raise ValueError(f"unknown context scope: {scope}")
    from .context import check_capacity, effective_limits

    context = effective_limits(context)
    check_capacity(estimated_tokens)
    usage: dict[str, int] = {"max_input_tokens": estimated_tokens}
    for metric in metrics:
        key, separator, raw_value = metric.partition("=")
        if not separator or not key or not raw_value:
            raise ValueError(f"context metric must use name=value: {metric}")
        if key not in context or key in {"profile", "max_input_tokens"}:
            raise ValueError(f"unknown context metric for {name}: {key}")
        try:
            value = int(raw_value)
        except ValueError as error:
            raise ValueError(f"context metric {key} must be an integer") from error
        if value < 0:
            raise ValueError(f"context metric {key} must be non-negative")
        usage[key] = value

    exceeded = {
        key: {"used": value, "limit": context[key]}
        for key, value in usage.items()
        if value > context[key]
    }
    if exceeded:
        details = ", ".join(
            f"{key}={values['used']} > {values['limit']}" for key, values in exceeded.items()
        )
        raise ValueError(f"CONTEXT_OVERFLOW for {name}: {details}")
    return {
        "command": name,
        "context": context_name,
        "scope": scope,
        "usage": usage,
        "status": "within-budget",
    }


def tier_recommendation(assessment_payload: dict[str, Any]) -> dict[str, Any]:
    contract = routing_contract()
    assessment_contract = contract["assessment"]
    required_fields = set(assessment_contract["required_fields"])
    supplied_fields = set(assessment_payload)
    if supplied_fields != required_fields:
        missing = sorted(required_fields - supplied_fields)
        extra = sorted(supplied_fields - required_fields)
        raise ValueError(f"assessment field mismatch; missing={missing}, extra={extra}")
    if assessment_payload.get("schema_version") != assessment_contract["schema_version"]:
        raise ValueError("unsupported assessment schema_version")
    for field in (
        "localized_established_pattern",
        "deterministic_focused_verification",
        "uncertainty",
    ):
        if not isinstance(assessment_payload.get(field), bool):
            raise ValueError(f"assessment field {field} must be a boolean")

    dimensions = assessment_payload.get("dimensions")
    definitions = assessment_contract["dimensions"]
    if not isinstance(dimensions, dict):
        raise ValueError("assessment dimensions must be an object")
    if set(dimensions) != set(definitions):
        missing = sorted(set(definitions) - set(dimensions))
        extra = sorted(set(dimensions) - set(definitions))
        raise ValueError(f"assessment dimension mismatch; missing={missing}, extra={extra}")
    for name, value in dimensions.items():
        if not isinstance(value, bool):
            raise ValueError(f"assessment dimension {name} must be a boolean")

    active_dimensions = sorted(name for name, active in dimensions.items() if active)
    high_severity = contract["tier_rules"]["high_on_any_severity"]
    critical_dimensions = [
        name for name in active_dimensions if definitions[name]["severity"] == high_severity
    ]
    medium_dimensions = [
        name for name in active_dimensions if definitions[name]["severity"] == "medium"
    ]
    medium_threshold = contract["tier_rules"]["high_on_medium_dimension_count"]

    if critical_dimensions:
        base_tier = "high"
        rationale = [f"critical dimensions active: {', '.join(critical_dimensions)}"]
    elif len(medium_dimensions) >= medium_threshold:
        base_tier = "high"
        rationale = [
            f"{len(medium_dimensions)} medium dimensions meet the high-tier threshold: "
            f"{', '.join(medium_dimensions)}"
        ]
    elif (
        assessment_payload["localized_established_pattern"]
        and assessment_payload["deterministic_focused_verification"]
        and not active_dimensions
    ):
        base_tier = "low"
        rationale = [
            "localized established pattern with no active risk dimensions and focused "
            "deterministic verification"
        ]
    else:
        base_tier = contract["tier_rules"]["default_tier"]
        rationale = ["task falls between the low and high tier boundaries"]

    tier = base_tier
    uncertainty_escalated = False
    if assessment_payload["uncertainty"] and base_tier != "high":
        tier = "medium" if base_tier == "low" else "high"
        uncertainty_escalated = True
        rationale.append(f"uncertainty escalated the tier from {base_tier} to {tier}")

    review_triggers = [name for name in active_dimensions if definitions[name]["review_trigger"]]
    if tier == "high":
        review = {
            "required": True,
            "independent": True,
            "strength": "high",
            "reason": "high-tier tasks always require independent high review",
        }
    elif tier == "medium" and review_triggers:
        review = {
            "required": True,
            "independent": True,
            "strength": "medium",
            "reason": f"medium-tier review triggers active: {', '.join(review_triggers)}",
        }
    else:
        review = {
            "required": False,
            "independent": False,
            "strength": None,
            "reason": "executor self-verification is sufficient under the routing policy",
        }

    escalation_triggers = [
        "scope, interface, dependency, or evidence drift returns REPLAN_REQUIRED",
        "any newly discovered critical dimension requires high tier",
        f"{medium_threshold} active medium dimensions require high tier",
        "uncertainty escalates one tier",
    ]
    return {
        "routing_contract_version": contract["schema_version"],
        "assessment": assessment_payload,
        "base_tier": base_tier,
        "executor_tier": tier,
        "uncertainty_escalated": uncertainty_escalated,
        "active_dimensions": active_dimensions,
        "tier_rationale": rationale,
        "escalation_triggers": escalation_triggers,
        "review": review,
        "worker_may_downgrade": contract["tier_rules"]["worker_may_downgrade"],
    }


def routing_check(
    harness_name: str,
    role: str,
    strength: str,
    configured_model: str | None,
    assurance: str = "strict",
) -> dict[str, Any]:
    contract = routing_contract()
    harness_name = HARNESS_ALIASES.get(harness_name, harness_name)
    if harness_name not in contract["harnesses"]:
        raise ValueError(f"unknown routing harness: {harness_name}")
    if role not in contract["roles"]:
        raise ValueError(f"unknown routing role: {role}")
    if strength not in contract["strengths"]:
        raise ValueError(f"unknown routing strength: {strength}")
    if assurance not in ASSURANCE_VALUES:
        raise ValueError(f"unknown assurance profile: {assurance}")
    if (
        role == "planner"
        and strength != "high"
        and not (assurance == "balanced" and strength == "medium")
    ):
        raise ValueError("planner strength must be high, or medium for balanced low-risk work")
    if role == "reviewer" and strength == "low":
        raise ValueError("low-tier tasks self-verify and do not use a low reviewer")
    if configured_model is not None and (
        not configured_model
        or configured_model != configured_model.strip()
        or any(character.isspace() or ord(character) < 32 for character in configured_model)
    ):
        raise ValueError(
            "configured model must be non-empty and contain no whitespace or control characters"
        )

    harness = contract["harnesses"][harness_name]
    capability = harness["capability"]
    fallback: dict[str, Any]
    if capability == "enforced":
        enforced = True
        status = "enforced"
        effective_strength = strength
        fallback = {"used": False, "reason": None}
    elif capability == "inherited-model":
        enforced = False
        status = "advisory"
        effective_strength = "inherited"
        fallback = {
            "used": True,
            "reason": "the delegated subagent inherits the parent model",
        }
    else:
        enforced = False
        status = "advisory"
        effective_strength = "profile-only"
        fallback = {
            "used": True,
            "reason": "the harness selects a role profile but cannot pin a per-worker model",
        }

    result = {
        "routing_contract_version": contract["schema_version"],
        "harness": harness_name,
        "role": role,
        "assurance": assurance,
        "requested_strength": strength,
        "configured_model_when_observable": configured_model,
        "capability": capability,
        "delegation": harness["delegation"],
        "tier_enforcement_status": status,
        "enforced": enforced,
        "effective_strength": effective_strength,
        "fallback": fallback,
    }
    profiles = harness.get("profiles")
    if isinstance(profiles, dict):
        result["native_profile"] = profiles[role]
    return result
