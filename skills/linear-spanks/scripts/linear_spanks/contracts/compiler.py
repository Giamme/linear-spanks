"""Compile canonical namespaced commands without exposing v1 runtime identity."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from ..core.errors import FilesystemError, UsageError
from ..core.hashing import sha256_digest
from ..core.jsonio import mutable_json_copy
from ..core.types import CommandModeSpec, CommandSpec, ContractSet, ExecutionEnvelope
from .arguments import ParsedPublicArguments, parse_public_arguments
from .registry import get_contract_set, validate_contract_set

ASSURANCE_VALUES = {"fast", "balanced", "strict"}
LOOP_ONLY_FLAGS = {
    "--max-parallel",
    "--resume",
    "--until",
    "--max-events",
    "--repair-safe",
}
TASK_RUNTIME_COMMANDS = {
    "task refine",
    "task plan",
    "milestone plan",
    "task run",
    "task replan",
    "task verify",
    "task next",
    "wave implement",
    "wave reconcile",
}
SKILL_COMPOSITION_COMMANDS = {
    "milestone plan",
    "task plan",
    "task run",
    "task replan",
    "task verify",
    "task next",
    "wave implement",
    "wave reconcile",
}
LEARNING_ARTIFACT_COMMANDS = {
    "milestone wrap",
    "learning organize",
    "learning review",
}
ISSUE_INTAKE_COMMANDS = {
    "milestone plan",
    "task plan",
    "task refine",
    "task organize",
}
LIFECYCLE_COMMANDS = {
    "milestone archive",
    "milestone blockers",
    "milestone diff",
    "milestone handoff",
    "milestone onboard",
    "milestone pause",
    "milestone resume",
    "milestone status",
    "milestone sync",
    "task next",
    "task onboard",
    "wave implement",
    "wave reconcile",
}


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise UsageError("INVALID_CONTRACT_SET", f"{field} must be an object")
    return value


def _text_list(value: Any, field: str) -> list[str]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, str | bytes)
        or not all(isinstance(item, str) for item in value)
    ):
        raise UsageError("INVALID_CONTRACT_SET", f"{field} must be a text array")
    return list(value)


def _runtime_command(path: str, parsed: ParsedPublicArguments, default: str) -> tuple[str, str]:
    if path != "milestone run":
        return default, "step"
    mode = parsed.value("--mode") or "step"
    present_loop_flags = sorted(flag for flag in LOOP_ONLY_FLAGS if flag in parsed.options)
    if mode == "step" and present_loop_flags:
        raise UsageError(
            "LOOP_OPTION_REQUIRES_LOOP_MODE",
            "Loop-only options require milestone run --mode loop",
            details={"options": present_loop_flags},
        )
    return ("run-milestone-loop" if mode == "loop" else "run-milestone"), mode


def _mode_spec(command: CommandSpec, mode: str) -> CommandModeSpec | None:
    return command.modes.get(mode)


def _public_command(command: CommandSpec, mode: str) -> dict[str, object]:
    variant = _mode_spec(command, mode)
    return {
        "path": command.path,
        "tier": command.tier,
        "access": command.access,
        "approval": variant.approval if variant else command.approval,
        "profiles": list(variant.profiles if variant else command.profiles),
        "template": variant.template if variant else command.template,
        "transitions": list(variant.transitions if variant else command.transitions),
        "summary": variant.summary if variant else command.summary,
        "usage": variant.usage if variant else command.usage,
    }


def _merge_policy_values(
    profile: Mapping[str, Any], configuration: Mapping[str, Any], field: str
) -> list[str]:
    values = [
        *_text_list(profile.get(field), f"execution profile {field}"),
        *_text_list(configuration.get(field, ()), f"command configuration {field}"),
    ]
    translated = {
        "autopilot_policy_when_requested": "loop_policy_when_mode_loop",
        "autopilot_aliases_guarded_loop_when_requested": ("mode_loop_uses_guarded_orchestration"),
    }
    return list(dict.fromkeys(translated.get(value, value) for value in values))


def _native_references(command: CommandSpec) -> list[str]:
    """References for the natively-defined v2 commands that bypass the legacy configuration."""

    references = ["references/context-management.md"]
    if command.path == "task checkpoint":
        references.append("references/task-checkpoint.md")
    if command.path == "milestone checkpoint":
        references.extend(("references/milestone-checkpoint.md", "references/task-checkpoint.md"))
    return references


def _required_references(
    command: CommandSpec,
    configuration: Mapping[str, Any],
    *,
    mode: str,
    template: str | None,
    contract_set: ContractSet,
) -> list[str]:
    namespace_reference = {
        "codebase": "references/codebase-analysis.md",
        "project": "references/project-commands.md",
        "milestone": "references/milestone-commands.md",
        "task": "references/task-commands.md",
        "wave": "references/parallel-execution.md",
        "verification": "references/human-verification.md",
        "learning": "references/learning-commands.md",
    }
    references = [namespace_reference[command.namespace], "references/context-runtime.md"]
    if configuration.get("orchestration") is not None:
        references.append("references/model-routing.md")
        references.append("references/task-workflow.md")
    if command.transitions:
        references.append("references/workflow-state.md")
    if command.path in SKILL_COMPOSITION_COMMANDS:
        references.append("references/skill-composition.md")
    if configuration.get("repository_scan") is not None:
        # Staged scans and import synthesis are codebase-namespace concerns; every other
        # command that reads a working tree needs only resolution, tiers and capsules.
        references.append(
            "references/codebase-analysis.md"
            if command.namespace == "codebase"
            else "references/repository-scan.md"
        )
    if command.path in LIFECYCLE_COMMANDS:
        references.append("references/lifecycle-commands.md")
    if command.namespace == "codebase" or command.path in {
        "verification policy-set",
        "verification status",
    }:
        references.append("references/project-commands.md")
    if command.path in {"verification confirm", "verification fail"}:
        references.append("references/milestone-commands.md")
    if command.path in {"project checkpoint", "project rollover"}:
        references.append("references/project-epoch.md")
    if command.path == "project run":
        references = [
            reference
            for reference in references
            if reference != namespace_reference[command.namespace]
        ]
        references.extend(
            (
                "references/project-orchestration.md",
                "references/parallel-execution.md",
                "templates/completion-handoff.md",
                "templates/verification-ledger.md",
                "templates/task-verification-result.md",
            )
        )
    if command.path == "milestone run" and mode == "loop":
        references = [
            reference
            for reference in references
            if reference != namespace_reference[command.namespace]
        ]
        references.extend(
            (
                "references/milestone-orchestration.md",
                "references/parallel-execution.md",
                "templates/completion-handoff.md",
                "templates/verification-ledger.md",
                "templates/task-verification-result.md",
                "templates/milestone-orchestration-receipt.md",
            )
        )
    if command.namespace == "verification" or command.path in {
        "project run",
        "milestone run",
        "milestone verify",
        "milestone wrap",
        "milestone status",
        "milestone handoff",
        "milestone report-findings",
    }:
        references.append("references/human-verification.md")
    if command.path in ISSUE_INTAKE_COMMANDS:
        references.append("references/issue-intake.md")
    if command.path in LEARNING_ARTIFACT_COMMANDS:
        references.extend(
            ("templates/learning-entry.md", "templates/milestone-learning-index.md")
        )
    if command.path == "milestone run" and mode == "loop":
        references.append("templates/milestone-runtime.md")
    if template is not None:
        references.append(f"templates/{template}")
    result = list(dict.fromkeys(references))
    for reference in result:
        if not (contract_set.root / reference).is_file():
            raise FilesystemError(
                "REFERENCE_NOT_FOUND",
                f"Required command reference does not exist: {reference}",
                details={"command": command.path, "reference": reference},
            )
    return result


ORCHESTRATION_REFERENCES = frozenset(
    {"references/project-orchestration.md", "references/milestone-orchestration.md"}
)


def _resolves_repository(compiled: Mapping[str, Any]) -> bool:
    """Report whether a compiled command actually reaches a working tree.

    Ripwire is optional repository discovery, so its reference only governs commands that
    resolve a repository themselves or forward ``ripwire.child_arguments`` to children that
    do. Purely Linear-scoped commands never reach a working tree.
    """

    if compiled.get("repository_scan") is not None or compiled.get("orchestration") is not None:
        return True
    references = compiled.get("required_references")
    if not isinstance(references, list):
        return False
    return any(reference in ORCHESTRATION_REFERENCES for reference in references)


def _policy_reference(contract_set: ContractSet, name: str) -> dict[str, object]:
    contract = contract_set.contract(name)
    version = contract.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise UsageError("INVALID_CONTRACT_SET", f"{name} has an invalid schema version")
    source = contract_set.sources.get(name)
    if source is None:
        raise UsageError("INVALID_CONTRACT_SET", f"{name} has no indexed source metadata")
    return {
        "name": name,
        "path": source.path,
        "sha256": source.sha256,
        "contract_schema_version": version,
        "contract_set_revision": contract_set.revision,
    }


def _copy_policy_fields(contract: Mapping[str, Any], fields: Sequence[str]) -> dict[str, object]:
    return {field: mutable_json_copy(contract[field]) for field in fields if field in contract}


def _policy_slice(
    contract_set: ContractSet,
    name: str,
    *,
    command: CommandSpec,
    runtime_name: str,
    configuration: Mapping[str, Any],
    context_name: str,
    execution_name: str,
    assurance: str,
    parsed: ParsedPublicArguments,
    transitions: Sequence[str],
    writes: Sequence[str],
    postconditions: Sequence[str],
) -> dict[str, object]:
    """Compile the bounded, command-specific portion of one indexed policy."""

    contract = contract_set.contract(name)
    if name == "core_policy":
        return _core_policy_slice(contract, writes=writes, postconditions=postconditions)
    if name == "workflow":
        available = _mapping(contract.get("transitions"), "workflow transitions")
        return {
            **_copy_policy_fields(contract, ("schema_version", "marker_prefix", "stages")),
            "transitions": {
                transition: mutable_json_copy(available[transition])
                for transition in transitions
                if transition in available
            },
        }
    if name == "issue_workflow":
        available = _mapping(contract.get("transitions"), "issue transitions")
        transition_names = (
            ("refine",)
            if runtime_name == "refine-task"
            else ("plan",)
            if runtime_name in {"plan-task", "plan-tasks"}
            else ()
        )
        return {
            **_copy_policy_fields(contract, ("schema_version", "statuses")),
            "transitions": {
                transition: mutable_json_copy(available[transition])
                for transition in transition_names
                if transition in available
            },
        }
    if name == "execution":
        return {
            **_copy_policy_fields(contract, ("schema_version", "token_estimate")),
            "context_profiles": {
                context_name: mutable_json_copy(
                    _mapping(contract.get("context_profiles"), "context profiles")[context_name]
                )
            },
            "execution_profiles": {
                execution_name: mutable_json_copy(
                    _mapping(contract.get("execution_profiles"), "execution profiles")[
                        execution_name
                    ]
                )
            },
            "commands": {runtime_name: mutable_json_copy(configuration)},
        }
    if name == "routing":
        raw_assurance = _mapping(contract.get("assurance"), "routing assurance")
        assurance_profiles = _mapping(raw_assurance.get("profiles"), "routing assurance profiles")
        assurance_slice = _copy_policy_fields(
            raw_assurance,
            (
                "schema_version",
                "values",
                "default",
                "task_optimized_commands",
                "strict_escalation_dimensions",
                "strict_escalation_conditions",
                "exact_context_triggers",
                "safety_invariants",
                "linear_verification",
            ),
        )
        assurance_slice["profiles"] = {assurance: mutable_json_copy(assurance_profiles[assurance])}
        routing_slice = _copy_policy_fields(
            contract,
            (
                "schema_version",
                "roles",
                "strengths",
                "harness_capabilities",
                "hierarchical_orchestration_contract",
                "detected_drift_values",
                "task_workflow",
                "planner",
                "assessment",
                "tier_rules",
                "review_policy",
                "plan_packet",
                "worker_handoff",
                "completion_receipt",
                "preflight_receipt",
                "planner_batching",
                "linear_reconciliation",
                "coordinator_owns",
                "harnesses",
            ),
        )
        routing_slice["assurance"] = assurance_slice
        orchestration_name = configuration.get("orchestration")
        if isinstance(orchestration_name, str):
            orchestration_profiles = _mapping(
                contract.get("orchestration_profiles"), "routing orchestration profiles"
            )
            routing_slice["orchestration_profiles"] = {
                orchestration_name: mutable_json_copy(orchestration_profiles[orchestration_name])
            }
        return routing_slice
    if name == "repository_scan":
        tier = parsed.value("--scan") or configuration.get("repository_scan", {}).get(
            "default_tier"
        )
        profiles = _mapping(contract.get("profiles"), "repository scan profiles")
        scan_slice = _copy_policy_fields(
            contract,
            (
                "schema_version",
                "source_revision_semantics",
                "default_tier",
                "token_estimate",
                "metric_measurements",
                "stages",
                "checkpoint",
                "evidence_capsule",
                "completion_finding",
                "completion_classifications",
                "security",
                "overflow_result",
                "drift_result",
            ),
        )
        if isinstance(tier, str) and tier in profiles:
            scan_slice["profiles"] = {tier: mutable_json_copy(profiles[tier])}
        return scan_slice
    if name == "project_epoch":
        section = "rollover" if command.path == "project rollover" else "capsule"
        return _copy_policy_fields(contract, ("schema_version", section))
    if name == "parallel_execution":
        parallel_fields = (
            (
                "schema_version",
                "source_hash_semantics",
                "graph",
                "execution_footprint",
                "waves",
                "git",
                "wave_receipt",
                "reconciliation",
            )
            if command.namespace == "wave"
            else (
                "schema_version",
                "source_hash_semantics",
                "git",
                "single_execution",
                "isolation_receipt",
            )
        )
        return _copy_policy_fields(contract, parallel_fields)
    if name == "milestone_runtime":
        runtime_fields = [
            "schema_version",
            "title_prefix",
            "document_title_pattern",
            "document_marker",
            "fallback_comment_marker",
            "description_marker",
            "description_reference",
            "singleton",
            "sources_of_truth",
            "storage",
            "runtime_required_fields",
            "storage_sources",
        ]
        if runtime_name == "run-milestone-loop":
            runtime_fields.append("autopilot")
        elif runtime_name in {"plan-tasks", "review-milestone"}:
            runtime_fields.extend(("plan", "next_wave"))
        elif runtime_name == "report-milestone-findings":
            runtime_fields.append("findings")
        return _copy_policy_fields(contract, runtime_fields)
    return cast(dict[str, object], mutable_json_copy(contract))


def _core_policy_slice(
    contract: Mapping[str, Any],
    *,
    writes: Sequence[str],
    postconditions: Sequence[str],
) -> dict[str, object]:
    """Bound core policy to what this command actually declares.

    Project resolution and recovery govern every command. The mutation protocol and naming
    rule only matter where the command writes. Postcondition definitions are filtered to the
    tokens this command emits, so the slice stays proportional instead of shipping the whole
    policy into every envelope.
    """

    selected: dict[str, object] = {
        "schema_version": contract["schema_version"],
        "project_resolution": mutable_json_copy(contract["project_resolution"]),
        "recovery": mutable_json_copy(contract["recovery"]),
    }
    if writes:
        selected["mutation_protocol"] = mutable_json_copy(contract["mutation_protocol"])
        selected["naming"] = contract["naming"]
    definitions = contract["postcondition_definitions"]
    defined = {name: definitions[name] for name in postconditions if name in definitions}
    if defined:
        selected["postcondition_definitions"] = defined
    return selected


def _policy_contract(
    contract_set: ContractSet,
    name: str,
    **slice_arguments: Any,
) -> dict[str, object]:
    policy_slice = _policy_slice(contract_set, name, **slice_arguments)
    return {
        **_policy_reference(contract_set, name),
        "policy_slice": policy_slice,
        "policy_slice_sha256": sha256_digest(policy_slice),
    }


def _policy_names(
    command: CommandSpec,
    runtime_name: str,
    configuration: Mapping[str, Any],
    references: Sequence[str],
    *,
    isolated: bool,
) -> list[str]:
    names = ["core_policy", "workflow", "execution"]
    if command.path in ISSUE_INTAKE_COMMANDS:
        names.append("issue_workflow")
    if configuration.get("repository_scan") is not None:
        names.append("repository_scan")
    if configuration.get("orchestration") is not None:
        names.append("routing")
    if command.path in {"project checkpoint", "project rollover"}:
        names.append("project_epoch")
    if command.path == "project run":
        names.append("project_orchestration")
    if runtime_name == "run-milestone-loop":
        names.append("milestone_orchestration")
    if command.path in {
        "milestone run",
        "milestone plan",
        "milestone review",
        "milestone report-findings",
        "milestone status",
        "milestone handoff",
    }:
        names.append("milestone_runtime")
    if command.path in {"milestone run", "milestone review"}:
        names.append("milestone_review")
    if command.namespace == "wave" or isolated:
        names.append("parallel_execution")
    if "references/human-verification.md" in references:
        names.append("human_verification")
    return list(dict.fromkeys(names))


def _assurance(path: str, requested: str, *, mode: str) -> dict[str, str]:
    effective = requested
    if path in {"wave implement", "wave reconcile"}:
        effective = "strict"
        status = "parallel-execution-forces-strict"
    elif path == "project run":
        status = "project-role-policy-enforced"
    elif path == "milestone run" and mode == "loop":
        status = "milestone-role-policy-enforced"
    elif path in TASK_RUNTIME_COMMANDS:
        status = "provisional-risk-screen-required"
    else:
        effective = "strict"
        status = "family-not-yet-optimized"
    return {"requested": requested, "effective": effective, "status": status}


def _isolation(
    contract_set: ContractSet,
    runtime_name: str,
    *,
    requested: bool,
    milestone_stage: str | None,
) -> dict[str, object] | None:
    parallel = contract_set.contract("parallel_execution")
    single = _mapping(parallel.get("single_execution"), "parallel single execution")
    optional = set(_text_list(single.get("optional_commands"), "optional isolation commands"))
    always = set(_text_list(single.get("always_isolated_commands"), "always-isolated commands"))
    conditional = _mapping(single.get("conditional_commands"), "conditional isolation commands")
    governance_fields = (
        "preflight_result",
        "ambiguous_receipt_result",
        "approval_drift_result",
        "plan_drift_result",
        "branch_pattern",
        "receipt_template",
        "integration_preview_fields",
        "integration_strategy",
        "merge_strategy",
        "preserve_child_branch",
        "push_or_pr",
        "cleanup_after_integrated_receipt",
        "linear_done_after_parent_integration",
    )
    governance = {
        field: mutable_json_copy(single[field]) for field in governance_fields if field in single
    }
    if runtime_name == "run-milestone-loop":
        return {
            "mode": "always",
            "enabled": True,
            "status": "idempotent-assertion" if requested else "loop-task-isolation",
            "policy": _policy_reference(contract_set, "parallel_execution"),
            "orchestration_policy": _policy_reference(contract_set, "milestone_orchestration"),
            "governance": governance,
        }
    if runtime_name in always:
        return {
            "mode": "always",
            "enabled": True,
            "status": "idempotent-assertion" if requested else "always-isolated",
            "policy": _policy_reference(contract_set, "parallel_execution"),
            "governance": governance,
        }
    if runtime_name in optional:
        return {
            "mode": "optional",
            "enabled": requested,
            "status": "enabled" if requested else "available",
            "policy": _policy_reference(contract_set, "parallel_execution"),
            "governance": governance,
        }
    if runtime_name in conditional:
        required_stage = conditional[runtime_name]
        if requested and milestone_stage is not None and milestone_stage != required_stage:
            raise UsageError(
                "ISOLATION_NOT_APPLICABLE",
                f"Isolation applies only at {required_stage}",
                details={"required_stage": required_stage, "actual_stage": milestone_stage},
            )
        return {
            "mode": "conditional",
            "enabled": requested and milestone_stage == required_stage,
            "status": (
                "enabled"
                if requested and milestone_stage == required_stage
                else "requires-stage-resolution"
                if requested
                else "available-at-implementation-stage"
            ),
            "required_stage": required_stage,
            "policy": _policy_reference(contract_set, "parallel_execution"),
            "governance": governance,
        }
    if requested:
        raise UsageError(
            "ISOLATION_NOT_APPLICABLE", "This command does not support --isolated-worktree"
        )
    return None


def _compile_contract(
    command: CommandSpec,
    parsed: ParsedPublicArguments,
    *,
    runtime_name: str,
    mode: str,
    assurance: str,
    contract_set: ContractSet,
) -> dict[str, object]:
    if not command.legacy_names:
        native = mutable_json_copy(
            contract_set.contract("context_management")["commands"][command.path]
        )
        checkpoint_level = parsed.value("--level") or "compact"
        if command.path == "milestone checkpoint" and checkpoint_level == "compact":
            native["writes"] = [
                w
                for w in native["writes"]
                if w not in {"approved_task_deletions", "archived_dependency_handoff_comments"}
            ]
            native["postconditions"] = [
                p
                for p in native["postconditions"]
                if p
                not in {
                    "deleted_tasks_absent_on_fresh_inventory",
                    "surviving_consumers_have_verified_archive_references",
                }
            ]
            native["postconditions"].append("all_task_entities_retained")
        return {
            "schema_version": 2,
            "contract_set_revision": contract_set.revision,
            "command": _public_command(command, mode),
            "invocation": {"command": command.path, **parsed.as_dict()},
            "approval": {
                "kind": native["approval_kind"],
                "description": native["approval"],
                "regate_on": ["source_hash_changed", "policy_hash_changed"],
            },
            "context": {"profile": "context_management", "max_input_tokens": 12000},
            "reads": native["reads"],
            "writes": native["writes"],
            "postconditions": native["postconditions"],
            "required_references": _native_references(command),
            "policy_contracts": [
                _policy_contract(
                    contract_set,
                    "core_policy",
                    command=command,
                    runtime_name=runtime_name,
                    configuration={},
                    context_name="context_management",
                    execution_name="context_management",
                    assurance=assurance,
                    parsed=parsed,
                    transitions=list(_public_command(command, mode)["transitions"]),
                    writes=native["writes"],
                    postconditions=native["postconditions"],
                ),
                {**_policy_reference(contract_set, "context_management"), "policy_slice": native},
            ],
            "session_boundary": "single-command",
            "bulk": False,
            "migrations": [],
            "migration_preview_hash": None,
        }
    execution_contract = contract_set.contract("execution")
    configurations = _mapping(execution_contract.get("commands"), "execution commands")
    configuration = _mapping(configurations.get(runtime_name), f"execution command {runtime_name}")
    context_name = configuration.get("context")
    execution_name = configuration.get("execution")
    if not isinstance(context_name, str) or not isinstance(execution_name, str):
        raise UsageError("INVALID_CONTRACT_SET", "Execution profiles are invalid")
    contexts = _mapping(execution_contract.get("context_profiles"), "context profiles")
    profiles = _mapping(execution_contract.get("execution_profiles"), "execution profiles")
    context = _mapping(contexts.get(context_name), f"context profile {context_name}")
    profile = _mapping(profiles.get(execution_name), f"execution profile {execution_name}")
    public_command = _public_command(command, mode)
    public_template = public_command["template"]
    public_transitions = public_command["transitions"]
    if public_template is not None and not isinstance(public_template, str):
        raise UsageError("INVALID_CONTRACT_SET", "Command template is invalid")
    if not isinstance(public_transitions, list) or not all(
        isinstance(transition, str) for transition in public_transitions
    ):
        raise UsageError("INVALID_CONTRACT_SET", "Command transitions are invalid")
    approval = mutable_json_copy(_mapping(profile.get("approval"), "approval policy"))
    approval["description"] = public_command["approval"]
    reads = _merge_policy_values(profile, configuration, "reads")
    writes = _merge_policy_values(profile, configuration, "writes")
    postconditions = _merge_policy_values(profile, configuration, "postconditions")
    if command.access == "read" and (approval.get("kind") != "none" or writes):
        raise UsageError(
            "INVALID_CONTRACT_SET", f"Read-only command {command.path} resolves to writes"
        )
    if command.access != "read" and approval.get("kind") == "none":
        raise UsageError(
            "INVALID_CONTRACT_SET",
            f"Non-read command {command.path} must resolve to governed approval",
        )
    isolated = "--isolated-worktree" in parsed.options
    milestone_stage = parsed.value("--milestone-stage")
    isolation = _isolation(
        contract_set,
        runtime_name,
        requested=isolated,
        milestone_stage=milestone_stage,
    )
    references = _required_references(
        command,
        configuration,
        mode=mode,
        template=public_template,
        contract_set=contract_set,
    )
    if isolation is not None and isolation.get("enabled") and isolation.get("mode") != "always":
        parallel = contract_set.contract("parallel_execution")
        single = _mapping(parallel.get("single_execution"), "parallel single execution")
        reads = list(
            dict.fromkeys([*reads, *_text_list(single.get("reads"), "single isolation reads")])
        )
        writes = list(
            dict.fromkeys([*writes, *_text_list(single.get("writes"), "single isolation writes")])
        )
        postconditions = list(
            dict.fromkeys(
                [
                    *postconditions,
                    *_text_list(single.get("postconditions"), "single isolation postconditions"),
                ]
            )
        )
        receipt_template = single.get("receipt_template")
        if not isinstance(receipt_template, str):
            raise UsageError("INVALID_CONTRACT_SET", "Single isolation receipt template is invalid")
        references = list(
            dict.fromkeys(
                [
                    *references,
                    "references/parallel-execution.md",
                    receipt_template,
                ]
            )
        )
    policy_names = _policy_names(
        command,
        runtime_name,
        configuration,
        references,
        isolated=bool(isolation is not None and isolation.get("enabled")),
    )
    slice_arguments = {
        "command": command,
        "runtime_name": runtime_name,
        "configuration": configuration,
        "context_name": context_name,
        "execution_name": execution_name,
        "assurance": assurance,
        "parsed": parsed,
        "transitions": public_transitions,
        "writes": writes,
        "postconditions": postconditions,
    }
    policy_contracts = [
        _policy_contract(contract_set, name, **slice_arguments) for name in policy_names
    ]
    result: dict[str, object] = {
        "schema_version": 2,
        "contract_set_revision": contract_set.revision,
        "command": public_command,
        "invocation": {"command": command.path, **parsed.as_dict()},
        "approval": approval,
        "assurance": _assurance(command.path, assurance, mode=mode),
        "context": {"profile": context_name, **mutable_json_copy(context)},
        "reads": reads,
        "writes": writes,
        "postconditions": postconditions,
        "required_references": references,
        "policy_contracts": policy_contracts,
        "migrations": [],
        "migration_preview_hash": None,
        "session_boundary": configuration.get("session_boundary"),
        "bulk": bool(configuration.get("bulk", False)),
        "token_estimate": execution_contract.get("token_estimate"),
    }
    scan_configuration = configuration.get("repository_scan")
    if isinstance(scan_configuration, Mapping):
        selected_tier = parsed.value("--scan") or scan_configuration.get("default_tier")
        scan = contract_set.contract("repository_scan")
        scan_profiles = _mapping(scan.get("profiles"), "repository scan profiles")
        if not isinstance(selected_tier, str) or selected_tier not in scan_profiles:
            raise UsageError("INVALID_SCAN_TIER", "Unknown repository scan tier")
        result["repository_scan"] = {
            "tier": selected_tier,
            "context": mutable_json_copy(scan_profiles[selected_tier]),
            "policy": _policy_reference(contract_set, "repository_scan"),
        }
    if configuration.get("orchestration") is not None:
        result["orchestration"] = {
            "profile": configuration["orchestration"],
            "policy": _policy_reference(contract_set, "routing"),
        }
    if isolation is not None:
        result["isolation"] = isolation
    if command.path == "milestone run":
        result["mode"] = mode
    return result


def reachable_references(contract_set: ContractSet | None = None) -> set[str]:
    """Every reference and template some compiled command can require.

    Compilation is the only authority on what an agent is told to read, so reachability is
    derived from the compiler rather than restated. Used by ``docs check`` to catch a
    governing document that no command loads.
    """

    selected = contract_set or get_contract_set()
    execution_contract = selected.contract("execution")
    configurations = _mapping(execution_contract.get("commands"), "execution commands")
    parallel = selected.contract("parallel_execution")
    single = _mapping(parallel.get("single_execution"), "parallel single execution")
    receipt_template = single.get("receipt_template")
    # optional single-task isolation adds its receipt template outside _required_references
    reached: set[str] = {"references/ripwire.md", "references/parallel-execution.md"}
    if isinstance(receipt_template, str):
        reached.add(receipt_template)
    for command in selected.commands:
        if not command.legacy_names:
            reached.update(_native_references(command))
            continue
        configuration = _mapping(
            configurations.get(command.legacy_runtime_command),
            f"execution command {command.legacy_runtime_command}",
        )
        modes = tuple(command.modes) or ("",)
        for mode in modes:
            templates = {command.template}
            mode_spec = _mode_spec(command, mode)
            if mode_spec is not None:
                templates.add(mode_spec.template)
            for template in templates:
                reached.update(
                    _required_references(
                        command,
                        configuration,
                        mode=mode,
                        template=template,
                        contract_set=selected,
                    )
                )
    return reached


def compile_public_command(
    path: str,
    arguments: tuple[str, ...] = (),
    *,
    assurance: str | None = None,
    contract_set: ContractSet | None = None,
) -> ExecutionEnvelope:
    selected = contract_set or get_contract_set()
    if contract_set is not None:
        validate_contract_set(selected)
    command = selected.by_path.get(path)
    if command is None:
        raise UsageError("COMMAND_NOT_FOUND", f"Unknown v2 command: {path}")
    if "--autopilot" in arguments:
        raise UsageError(
            "LEGACY_OPTION_REMOVED",
            "The v1 --autopilot option was removed; use --mode loop",
            details={"legacy_option": "--autopilot", "replacement": "--mode loop"},
        )
    parsed = parse_public_arguments(command, arguments)
    argument_assurance = parsed.value("--assurance")
    if assurance is not None and assurance not in ASSURANCE_VALUES:
        raise UsageError("INVALID_ASSURANCE", "assurance must be fast, balanced, or strict")
    if assurance is not None and argument_assurance is not None and assurance != argument_assurance:
        raise UsageError(
            "ASSURANCE_CONFLICT",
            "The explicit assurance conflicts with the command arguments",
            details={"explicit": assurance, "argument": argument_assurance},
        )
    effective_assurance = argument_assurance or assurance or "balanced"
    runtime_name, mode = _runtime_command(path, parsed, command.legacy_runtime_command)
    compiled = _compile_contract(
        command,
        parsed,
        runtime_name=runtime_name,
        mode=mode,
        assurance=effective_assurance,
        contract_set=selected,
    )
    override = parsed.value("--ripwire") or "inherit"
    compiled["ripwire"] = {
        "run_override": override,
        "child_arguments": [] if override == "inherit" else ["--ripwire", override],
        "resolution": "after-child-repository-resolution",
        "optional": True,
    }
    if _resolves_repository(compiled):
        compiled["required_references"] = [
            *_text_list(compiled["required_references"], "required references"),
            "references/ripwire.md",
        ]

    from ..domains.context import bind_envelope

    compiled = bind_envelope(compiled)
    return ExecutionEnvelope(
        command=command,
        assurance=effective_assurance,
        arguments=arguments,
        contract=compiled,
    )
