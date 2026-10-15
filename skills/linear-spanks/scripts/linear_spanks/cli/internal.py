"""Namespaced internal operations replacing the flat v1 helper surface."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, TextIO

from ..core.errors import ExitCode, LinearSpanksError, UsageError
from ..core.jsonio import (
    StrictJsonError,
    load_json_object,
    mutable_json_copy,
    read_text,
    strict_json_loads,
)
from ..domains import _context_v1 as context_v1
from ..domains import _graphs_v1 as graphs_v1
from ..domains import _isolation_v1 as isolation_v1
from ..domains import _orchestration_v1 as orchestration_v1
from ..domains import _reviews_v1 as reviews_v1
from ..domains import _routing_v1 as routing_v1
from ..domains import _runtime_v1 as runtime_v1
from ..domains import _state_v1 as state_v1
from ..domains import _verification_v1 as verification_v1
from ..domains import context as context_domain
from ..domains import execution as execution_v1
from ..domains import graphs as graphs_api
from ..domains import milestone_checkpoint, task_checkpoint
from ..domains import reviews as reviews_api
from ..domains import runtime as runtime_domain
from ..domains import state as state_api
from ..domains import verification as verification_api
from ..domains._validation import checked
from ..domains.artifacts import ArtifactStore
from ..domains.commands import command as get_command
from ..domains.commands import compile_command, contracts, validate
from ..domains.documentation import check_reachable, check_links, generate
from ..domains.legacy_validation import validate_contracts as validate_legacy_contracts
from ..domains.migrations import (
    ArtifactBinding,
    FilesystemArtifactBackend,
    MigrationCoordinator,
    parse_migration_authorization,
)
from ..installation import caveman, model_routing, skill_installer
from ..installation.clients import client_registry
from .internal_arguments import InternalHelp
from .internal_arguments import build_parser as build_internal_parser

INTERNAL_OPERATIONS: dict[str, dict[str, str]] = {
    "context": {
        "check": "context-check",
        "packet": "context-packet",
        "scan-checkpoint": "scan-checkpoint",
        "project-capsule": "project-capsule-check",
        "rollover-receipt": "rollover-receipt-check",
        "rollover-transition": "rollover-transition",
    },
    "reviews": {
        "milestone-checkpoint": "milestone-review-checkpoint",
        "milestone-finalize": "milestone-review-finalize",
        "milestone-budget": "milestone-review-budget",
        "incremental-plan": "incremental-plan-check",
        "plan-drift": "plan-drift-check",
        "coverage": "review-coverage-check",
        "next-wave": "next-wave-check",
        "findings": "milestone-findings-check",
    },
    "runtime": {
        "milestone-check": "milestone-runtime-check",
        "storage-check": "milestone-runtime-storage-check",
        "migrate": "milestone-runtime-migrate",
        "autopilot-policy": "autopilot-policy-check",
        "autopilot-binding": "autopilot-binding-check",
        "mode": "milestone-run-mode-check",
        "loop": "autopilot-loop-check",
        "preflight": "preflight-check",
        "readback-plan": "linear-readback-plan",
        "completion-receipt": "completion-receipt-check",
    },
    "routing": {
        "recommend": "tier-recommend",
        "check": "routing-check",
        "decide": "orchestration-decision",
    },
    "state": {
        "transition": "transition",
        "issue-transition": "issue-transition",
        "marker": "marker",
        "parse-marker": "parse-marker",
        "advance": "advance-state",
        "payload-hash": "payload-hash",
        "idempotency-key": "idempotency-key",
    },
    "graphs": {
        "build": "dependency-graph-build",
        "check": "dependency-graph-check",
        "render": "dependency-graph-render",
        "parse": "parse-dependency-graph",
        "upsert": "dependency-graph-upsert",
        "wave-select": "wave-select",
        "wave-receipt": "wave-receipt-check",
    },
    "isolation": {
        "preflight": "isolation-preflight-check",
        "receipt": "isolation-receipt-check",
        "transition": "isolation-transition",
    },
    "orchestration": {
        "project-role": "project-role-card",
        "milestone-role": "milestone-role-card",
        "project-next": "project-loop-next",
        "project-receipt": "project-loop-receipt-check",
        "project-transition": "project-loop-transition",
        "milestone-next": "milestone-loop-next",
        "milestone-receipt": "milestone-loop-receipt-check",
        "milestone-transition": "milestone-loop-transition",
        "scope": "orchestration-scope-check",
        "handoff": "role-handoff-check",
        "capability": "role-capability-check",
        "task-attempt": "task-attempt-check",
        "model-escalation": "model-escalation-check",
        "verification-ledger": "verification-ledger-check",
    },
    "verification": {
        "policy-check": "human-verification-policy-check",
        "override-check": "human-verification-override-check",
        "policy-document": "human-verification-policy-document-check",
        "effective": "human-verification-effective",
        "preview-check": "human-verification-preview-check",
        "gate-check": "human-verification-gate-check",
        "checklist-check": "human-verification-checklist-check",
        "action-check": "human-verification-action-check",
        "filter-gates": "filter-human-verification-gates",
        "policy-binding": "orchestration-policy-binding-check",
        "marker": "human-verification-marker-check",
    },
}


def _parse_exact_options(
    arguments: tuple[str, ...],
    *,
    allowed: frozenset[str],
) -> tuple[str, dict[str, str]]:
    if not arguments or arguments[0].startswith("--"):
        raise UsageError("MISSING_PATH", "Artifact operation requires a path")
    path = arguments[0]
    options: dict[str, str] = {}
    index = 1
    while index < len(arguments):
        token = arguments[index]
        if not token.startswith("--"):
            raise UsageError("UNEXPECTED_ARGUMENT", f"Unexpected artifact argument: {token}")
        name, separator, inline_value = token.partition("=")
        if name not in allowed:
            raise UsageError("UNKNOWN_OPTION", f"Unknown artifact option: {name}")
        if name in options:
            raise UsageError("DUPLICATE_OPTION", f"{name} may be supplied only once")
        if separator:
            value = inline_value
        else:
            index += 1
            if index >= len(arguments) or arguments[index].startswith("--"):
                raise UsageError("MISSING_OPTION_VALUE", f"{name} requires a value")
            value = arguments[index]
        if not value:
            raise UsageError("MISSING_OPTION_VALUE", f"{name} requires a value")
        options[name] = value
        index += 1
    return path, options


def _command_payload(namespace: str, name: str) -> dict[str, Any]:
    command = get_command(f"{namespace} {name}")
    return {
        "path": command.path,
        "tier": command.tier,
        "access": command.access,
        "approval": command.approval,
        "profiles": list(command.profiles),
        "template": command.template,
        "transitions": list(command.transitions),
        "legacy_names": list(command.legacy_names),
        "summary": command.summary,
        "usage": command.usage,
    }


def _contract_operation(operation: str, arguments: tuple[str, ...]) -> Any:
    if operation == "validate":
        if arguments:
            raise UsageError("INVALID_ARGUMENTS", "contracts validate accepts no arguments")
        typed = validate()
        legacy = validate_legacy_contracts()
        return {**typed, "legacy_validation": legacy}
    if operation == "command":
        if len(arguments) != 2:
            raise UsageError("INVALID_ARGUMENTS", "Usage: contracts command <namespace> <command>")
        return _command_payload(arguments[0], arguments[1])
    if operation in {"envelope", "brief", "runtime-card"}:
        if len(arguments) < 2:
            raise UsageError(
                "INVALID_ARGUMENTS",
                f"Usage: contracts {operation} <namespace> <command> [options]",
            )
        path = f"{arguments[0]} {arguments[1]}"
        remainder = tuple(arguments[2:])
        compiled = compile_command(path, remainder)
        if operation == "envelope":
            return dict(compiled.contract)
        contract = compiled.contract
        fields: tuple[str, ...]
        if operation == "brief":
            fields = (
                "schema_version",
                "contract_set_revision",
                "command",
                "invocation",
                "assurance",
                "approval",
                "session_boundary",
                "context",
                "reads",
                "writes",
                "postconditions",
                "required_references",
                "policy_contracts",
            )
        else:
            fields = (
                "schema_version",
                "contract_set_revision",
                "command",
                "invocation",
                "assurance",
                "isolation",
                "orchestration",
                "repository_scan",
                "required_references",
                "policy_contracts",
            )
        return {field: contract[field] for field in fields if field in contract}
    raise UsageError("OPERATION_NOT_FOUND", f"Unknown contracts operation: {operation}")


def _artifact_operation(operation: str, arguments: tuple[str, ...]) -> Any:
    if "--authorized" in arguments or "--approved-source-hash" in arguments:
        raise UsageError(
            "LEGACY_MIGRATION_AUTHORIZATION_REMOVED",
            "Bare migration authorization was removed; use an exact preview and receipt",
            details={
                "replacement": (
                    "artifacts preview ... then artifacts migrate ... --authorization <file>"
                )
            },
        )
    allowed_by_operation = {
        "inspect": frozenset({"--kind"}),
        "preview": frozenset({"--kind", "--command", "--arguments", "--target"}),
        "migrate": frozenset(
            {
                "--kind",
                "--command",
                "--arguments",
                "--target",
                "--authorization",
            }
        ),
    }
    allowed = allowed_by_operation.get(operation)
    if allowed is None:
        raise UsageError("OPERATION_NOT_FOUND", f"Unknown artifacts operation: {operation}")
    raw_path, options = _parse_exact_options(arguments, allowed=allowed)
    path = Path(raw_path)
    kind = options.get("--kind")
    if kind is None:
        raise UsageError("MISSING_OPTION", "--kind is required")
    store = ArtifactStore()
    if operation == "inspect":
        return store.inspect(path, kind)
    if operation in {"preview", "migrate"}:
        command = options.get("--command")
        if command is None:
            raise UsageError("MISSING_OPTION", "--command is required")
        arguments_path = options.get("--arguments")
        target = options.get("--target")
        if (arguments_path is None) == (target is None):
            raise UsageError(
                "INVALID_ARGUMENTS",
                "Provide exactly one of --target or --arguments",
            )
        if arguments_path is not None:
            try:
                execution_arguments = strict_json_loads(read_text(Path(arguments_path)))
            except (json.JSONDecodeError, StrictJsonError) as error:
                message = error.msg if isinstance(error, json.JSONDecodeError) else str(error)
                raise UsageError(
                    "INVALID_JSON",
                    f"Execution arguments are not valid JSON: {message}",
                ) from error
            if (
                not isinstance(execution_arguments, list)
                or not execution_arguments
                or not all(isinstance(item, str) for item in execution_arguments)
            ):
                raise UsageError(
                    "INVALID_EXECUTION_ARGUMENTS",
                    "Execution arguments must be a non-empty JSON array of strings",
                )
            compiled = compile_command(command, tuple(execution_arguments))
        else:
            assert target is not None
            compiled = compile_command(command, (target,))
        coordinator = MigrationCoordinator({"filesystem": FilesystemArtifactBackend()})
        prepared = coordinator.prepare(
            compiled,
            (ArtifactBinding("filesystem", str(path), kind),),
        )
        if operation == "preview":
            return {
                "execution": mutable_json_copy(prepared.contract),
                "authorization_template": coordinator.authorization_template(prepared),
            }
        authorization_path = options.get("--authorization")
        if authorization_path is None:
            raise UsageError("MISSING_OPTION", "--authorization is required")
        authorization = parse_migration_authorization(load_json_object(Path(authorization_path)))
        return coordinator.commit(prepared, authorization)
    raise AssertionError(operation)


def _command_operand(path: str, mode: str | None) -> str:
    try:
        command = get_command(path)
    except UsageError as error:
        raise UsageError(
            "INVALID_COMMAND_OPERAND",
            f"Command operands require a registered namespaced path, found: {path}",
        ) from error
    if mode is None or mode == "step":
        return command.legacy_runtime_command
    if path == "milestone run" and mode == "loop":
        return "run-milestone-loop"
    raise UsageError(
        "INVALID_COMMAND_OPERAND",
        f"Command operand {path} does not support mode {mode}",
    )


def _translate_command_prefix(arguments: tuple[str, ...]) -> tuple[str, ...]:
    if len(arguments) < 2 or arguments[0].startswith("--") or arguments[1].startswith("--"):
        raise UsageError(
            "INVALID_COMMAND_OPERAND",
            "Command operands require <namespace> <command>",
        )
    path = f"{arguments[0]} {arguments[1]}"
    remainder = list(arguments[2:])
    mode: str | None = None
    if remainder and remainder[0] == "--mode":
        if len(remainder) < 2:
            raise UsageError("MISSING_OPTION_VALUE", "--mode requires step or loop")
        mode = remainder[1]
        del remainder[:2]
    elif remainder and remainder[0].startswith("--mode="):
        mode = remainder.pop(0).split("=", 1)[1]
    if mode not in {None, "step", "loop"}:
        raise UsageError("INVALID_COMMAND_OPERAND", "Command mode must be step or loop")
    return (_command_operand(path, mode), *remainder)


def _translate_command_option(arguments: tuple[str, ...], option: str) -> tuple[str, ...]:
    command_indexes = [
        position
        for position, token in enumerate(arguments)
        if token == option or token.startswith(f"{option}=")
    ]
    if len(command_indexes) > 1:
        raise UsageError("DUPLICATE_OPTION", f"{option} may be supplied only once")
    if not command_indexes:
        return arguments
    index = command_indexes[0]
    if arguments[index] != option:
        raise UsageError(
            "INVALID_COMMAND_OPERAND",
            f"{option} requires separate <namespace> <command> operands",
        )
    if (
        index + 2 >= len(arguments)
        or arguments[index + 1].startswith("--")
        or arguments[index + 2].startswith("--")
    ):
        raise UsageError(
            "INVALID_COMMAND_OPERAND",
            f"{option} requires <namespace> <command>",
        )
    path = f"{arguments[index + 1]} {arguments[index + 2]}"
    mode: str | None = None
    mode_indexes = [
        position
        for position, token in enumerate(arguments)
        if token == "--command-mode" or token.startswith("--command-mode=")
    ]
    if len(mode_indexes) > 1:
        raise UsageError("DUPLICATE_OPTION", "--command-mode may be supplied only once")
    if mode_indexes:
        mode_index = mode_indexes[0]
        token = arguments[mode_index]
        if token == "--command-mode":
            if mode_index + 1 >= len(arguments) or arguments[mode_index + 1].startswith("--"):
                raise UsageError("MISSING_OPTION_VALUE", "--command-mode requires step or loop")
            mode = arguments[mode_index + 1]
            consumed_mode = {mode_index, mode_index + 1}
        else:
            mode = token.split("=", 1)[1]
            consumed_mode = {mode_index}
    else:
        consumed_mode = set()
    if mode not in {None, "step", "loop"}:
        raise UsageError("INVALID_COMMAND_OPERAND", "Command mode must be step or loop")
    translated = _command_operand(path, mode)
    result: list[str] = []
    for position, token in enumerate(arguments):
        if position in consumed_mode or position == index + 2:
            continue
        result.append(translated if position == index + 1 else token)
    return tuple(result)


def _translate_public_command_argument(
    namespace: str, operation: str, arguments: tuple[str, ...]
) -> tuple[str, ...]:
    if namespace == "context" and operation in {"check", "packet"}:
        return _translate_command_prefix(arguments)
    if namespace == "state" and operation == "issue-transition":
        return _translate_command_prefix(arguments)
    if namespace == "state" and operation in {"advance", "idempotency-key"}:
        return _translate_command_option(arguments, "--command")
    if namespace == "state" and operation == "marker":
        return _translate_command_option(arguments, "--last-command")
    return arguments


def _documentation_operation(operation: str, arguments: tuple[str, ...]) -> Any:
    if arguments:
        raise UsageError("INVALID_ARGUMENTS", f"docs {operation} accepts no arguments")
    if operation == "generate":
        return generate(check=False)
    if operation == "check":
        generated = generate(check=True)
        return {**generated, "reachability": check_reachable()}
    if operation == "reachable":
        return check_reachable()
    if operation == "links":
        repository = contracts().root.parents[1]
        markdown = [
            path
            for path in repository.rglob("*.md")
            if ".git" not in path.parts and ".worktrees" not in path.parts
        ]
        return check_links(markdown)
    raise UsageError("OPERATION_NOT_FOUND", f"Unknown docs operation: {operation}")


def _capture_main(
    operation: str,
    function: Callable[[Sequence[str] | None], int],
    arguments: tuple[str, ...],
) -> Mapping[str, Any]:
    output = io.StringIO()
    errors = io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
        try:
            exit_code = function(list(arguments))
        except SystemExit as error:
            exit_code = error.code if isinstance(error.code, int) else int(ExitCode.USAGE)
    if exit_code != 0:
        try:
            stable_exit = ExitCode(exit_code)
        except ValueError:
            stable_exit = ExitCode.INTERNAL
        raise LinearSpanksError(
            "INSTALLATION_OPERATION_FAILED",
            errors.getvalue().strip() or f"{operation} failed",
            exit_code=stable_exit,
        )
    return {"status": "completed", "output": output.getvalue().splitlines()}


def _installation_operation(operation: str, arguments: tuple[str, ...]) -> Any:
    if operation == "clients":
        if len(arguments) > 1:
            raise UsageError("INVALID_ARGUMENTS", "Usage: installation clients [selector]")
        selector = arguments[0] if arguments else "all"
        registry = client_registry()
        return {
            "clients": [
                {
                    "name": client.name,
                    "routing_name": client.routing_name,
                    "capability": client.capability,
                    "destination": str(client.skill_destination(os.environ)),
                }
                for client in registry.expand(selector)
            ]
        }
    if operation == "skills":
        return _capture_main(operation, skill_installer.main, arguments)
    if operation == "model-routing":
        return _capture_main(operation, model_routing.main, arguments)
    raise UsageError("OPERATION_NOT_FOUND", f"Unknown installation operation: {operation}")


def _extension_operation(operation: str, arguments: tuple[str, ...]) -> Any:
    if operation == "ripwire":
        from ..extensions.ripwire import dispatch

        return dispatch(arguments)
    if operation == "caveman":
        return _capture_main(operation, caveman.main, arguments)
    raise UsageError("OPERATION_NOT_FOUND", f"Unknown extensions operation: {operation}")


def _payload_from(path: str | None, stdin: TextIO, label: str) -> dict[str, Any]:
    if path is not None:
        return load_json_object(Path(path))
    try:
        value = strict_json_loads(stdin.read())
    except (json.JSONDecodeError, StrictJsonError) as error:
        message = error.msg if isinstance(error, json.JSONDecodeError) else str(error)
        raise UsageError(
            "INVALID_JSON",
            f"{label} input is not valid JSON: {message}",
        ) from error
    if not isinstance(value, dict):
        raise UsageError("INVALID_PAYLOAD", f"{label} input must be a JSON object")
    return value


def _text_from(path: str | None, stdin: TextIO) -> str:
    return read_text(Path(path)) if path is not None else stdin.read()


def _dispatch_context(action: str, args: argparse.Namespace, stdin: TextIO) -> Any:
    if action == "context-check":
        return routing_v1.validate_context_usage(
            args.name,
            args.estimated_tokens,
            args.metric,
            args.scope,
            args.scan,
        )
    if action == "context-packet":
        return context_v1.measure_context_packet(
            args.name,
            load_json_object(Path(args.path)),
            args.scope,
            args.scan,
        )
    if action == "scan-checkpoint":
        return context_v1.validate_repository_checkpoint(
            load_json_object(Path(args.path)),
            args.expected_source_revision,
            Path(args.path),
            args.drift_classification,
        )
    if action == "project-capsule-check":
        return context_v1.validate_project_capsule(_payload_from(args.path, stdin, action))
    if action == "rollover-receipt-check":
        return context_v1.validate_rollover_receipt(
            _payload_from(args.path, stdin, action),
            args.expected_source_revision,
            args.expected_source_snapshot_hash,
            args.expected_approved_plan_hash,
        )
    if action == "rollover-transition":
        return context_v1.validate_rollover_transition(args.current, args.target)
    raise AssertionError(action)


def _dispatch_review_or_runtime(action: str, args: argparse.Namespace, stdin: TextIO) -> Any:
    if action == "milestone-review-budget":
        return reviews_v1._validate_review_budget(
            {
                "model_turns": args.model_turns,
                "active_context_tokens": args.active_context_tokens,
                "cumulative_input_tokens": args.cumulative_input_tokens,
                "phase_cumulative_input_tokens": args.phase_cumulative_input_tokens,
                "planned_batches": args.planned_batches,
                "telemetry_available": args.telemetry_available,
            }
        )
    if action == "preflight-check":
        return execution_v1.validate_preflight_receipt(
            load_json_object(Path(args.receipt)),
            load_json_object(Path(args.current)),
        )
    if action == "linear-readback-plan":
        return execution_v1.linear_readback_plan(_payload_from(args.path, stdin, action))
    if action == "completion-receipt-check":
        return execution_v1.validate_completion_receipt(_payload_from(args.path, stdin, action))
    payload = _payload_from(args.path, stdin, action)
    if action == "milestone-review-checkpoint":
        source_revisions = (
            load_json_object(Path(args.current_source_revisions))
            if args.current_source_revisions
            else None
        )
        return reviews_v1.validate_milestone_review_checkpoint(
            payload,
            current_session_id=args.current_session_id,
            expected_marker_revision=args.expected_marker_revision,
            expected_matrix_hash=args.expected_matrix_hash,
            expected_dependency_graph_hash=args.expected_dependency_graph_hash,
            expected_coverage_hash=args.expected_coverage_hash,
            current_source_revisions=source_revisions,
        )
    validators: Mapping[str, Callable[[dict[str, Any]], Any]] = {
        "milestone-review-finalize": reviews_v1.validate_milestone_review_finalization,
        "incremental-plan-check": reviews_v1.validate_incremental_plan,
        "plan-drift-check": reviews_v1.classify_plan_drift,
        "review-coverage-check": reviews_v1.calculate_incremental_review_coverage,
        "next-wave-check": reviews_v1.select_next_planning_wave,
        "milestone-runtime-check": runtime_v1.validate_milestone_runtime,
        "milestone-runtime-storage-check": runtime_v1.reconcile_milestone_runtime_storage,
        "milestone-runtime-migrate": runtime_v1.migrate_milestone_runtime_projection,
        "autopilot-policy-check": runtime_v1.validate_autopilot_policy,
        "autopilot-binding-check": runtime_v1.validate_guarded_autopilot_binding,
        "milestone-run-mode-check": runtime_v1.resolve_milestone_run_mode,
        "autopilot-loop-check": runtime_v1.validate_autopilot_loop,
        "milestone-findings-check": runtime_v1.validate_milestone_findings,
    }
    validator = validators.get(action)
    if validator is None:
        raise AssertionError(action)
    return validator(payload)


def _dispatch_routing(action: str, args: argparse.Namespace, stdin: TextIO) -> Any:
    if action == "routing-check":
        return routing_v1.routing_check(
            args.harness,
            args.role,
            args.strength,
            args.configured_model,
            args.assurance,
        )
    payload = _payload_from(args.path, stdin, action)
    if action == "tier-recommend":
        return routing_v1.tier_recommendation(payload)
    if action == "orchestration-decision":
        return routing_v1.orchestration_decision(payload)
    raise AssertionError(action)


def _dispatch_graphs(action: str, args: argparse.Namespace, stdin: TextIO) -> Any:
    if action == "parse-dependency-graph":
        return graphs_api.parse(_text_from(args.path, stdin))
    if action == "dependency-graph-upsert":
        return graphs_api.upsert(
            read_text(Path(args.description)),
            load_json_object(Path(args.graph)),
        )
    payload = _payload_from(args.path, stdin, action)
    if action == "dependency-graph-build":
        return graphs_v1.build_dependency_graph(payload)
    if action == "dependency-graph-check":
        return graphs_api.validate(payload)
    if action == "dependency-graph-render":
        return graphs_api.render(payload)
    if action == "wave-select":
        return graphs_v1.select_parallel_wave(payload, args.max_parallel, args.capacity)
    if action == "wave-receipt-check":
        return graphs_v1.validate_wave_receipt(payload)
    raise AssertionError(action)


def _dispatch_isolation(action: str, args: argparse.Namespace, stdin: TextIO) -> Any:
    if action == "isolation-transition":
        return isolation_v1.transition_isolation_receipt(
            load_json_object(Path(args.receipt)),
            load_json_object(Path(args.request)),
        )
    payload = _payload_from(args.path, stdin, action)
    if action == "isolation-preflight-check":
        return isolation_v1.validate_isolation_preflight(payload)
    if action == "isolation-receipt-check":
        return isolation_v1.validate_isolation_receipt(payload)
    raise AssertionError(action)


def _dispatch_orchestration(action: str, args: argparse.Namespace, stdin: TextIO) -> Any:
    if action == "project-role-card":
        return orchestration_v1.project_role_card(args.role)
    if action == "milestone-role-card":
        return orchestration_v1.milestone_role_card(args.role)
    if action == "project-loop-transition":
        return orchestration_v1.transition_project_loop_receipt(
            load_json_object(Path(args.receipt)),
            load_json_object(Path(args.request)),
        )
    if action == "milestone-loop-transition":
        return orchestration_v1.transition_milestone_loop_receipt(
            load_json_object(Path(args.receipt)),
            load_json_object(Path(args.request)),
        )
    payload = _payload_from(args.path, stdin, action)
    if action == "project-loop-next":
        return orchestration_v1.select_project_loop_event(payload)
    if action == "project-loop-receipt-check":
        return orchestration_v1.check_project_loop_receipts(payload)
    if action == "milestone-loop-next":
        return orchestration_v1.select_milestone_loop_event(payload)
    if action == "milestone-loop-receipt-check":
        return orchestration_v1.check_milestone_loop_receipts(payload)
    if action == "orchestration-scope-check":
        return orchestration_v1.check_orchestration_scope(payload)
    if action == "role-handoff-check":
        receipt = load_json_object(Path(args.receipt)) if args.receipt else None
        return orchestration_v1.validate_role_handoff(payload, receipt, args.orchestration)
    if action == "role-capability-check":
        return orchestration_v1.validate_role_capability(payload, args.orchestration)
    if action == "task-attempt-check":
        return orchestration_v1.validate_task_attempt(payload)
    if action == "model-escalation-check":
        return orchestration_v1.validate_model_escalation(payload)
    if action == "verification-ledger-check":
        return orchestration_v1.validate_verification_ledger(
            payload,
            args.expected_task_id,
            args.expected_verifier_id,
            args.expected_plan_revision,
        )
    raise AssertionError(action)


def _dispatch_state(action: str, args: argparse.Namespace, stdin: TextIO) -> Any:
    if action == "transition":
        return state_v1.validate_transition(args.name, args.current, args.resume_stage, args.mode)
    if action == "issue-transition":
        return state_v1.validate_issue_transition(args.command, args.from_status, args.to_status)
    if action == "marker":
        payload = state_v1.marker_payload(args)
        encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        return f"<!-- linear-spanks:state {encoded} -->"
    if action == "parse-marker":
        return state_api.parse_marker(_text_from(args.path, stdin))
    if action == "advance-state":
        return state_v1.validate_state_advance(
            args.command,
            args.transition,
            state_api.parse_marker(read_text(Path(args.current_marker))),
            state_api.parse_marker(read_text(Path(args.replacement_marker))),
            args.mode,
        )
    if action == "payload-hash":
        try:
            payload = strict_json_loads(_text_from(args.path, stdin))
        except (json.JSONDecodeError, StrictJsonError) as error:
            message = error.msg if isinstance(error, json.JSONDecodeError) else str(error)
            raise UsageError("INVALID_JSON", f"Payload is not valid JSON: {message}") from error
        return state_api.payload_hash(payload)
    if action == "idempotency-key":
        return state_v1.idempotency_key(
            args.project_id,
            args.entity_id,
            args.command,
            args.revision,
            args.operation_id,
            args.payload_hash,
        )
    raise AssertionError(action)


def _dispatch_verification(action: str, args: argparse.Namespace, stdin: TextIO) -> Any:
    if action == "human-verification-marker-check":
        return verification_api.parse_marker(
            args.kind,
            _text_from(args.path, stdin),
        )
    payload = _payload_from(args.path, stdin, action)
    validators: Mapping[str, Callable[[dict[str, Any]], Any]] = {
        "human-verification-policy-check": verification_v1.validate_human_project_policy,
        "human-verification-override-check": (verification_v1.validate_human_milestone_override),
        "human-verification-policy-document-check": verification_api.check_policy_document,
        "human-verification-effective": (verification_v1.resolve_human_verification_policy),
        "human-verification-preview-check": (verification_v1.validate_human_verification_preview),
        "human-verification-gate-check": verification_v1.validate_human_gate,
        "human-verification-checklist-check": verification_v1.validate_human_checklist,
        "human-verification-action-check": (verification_v1.validate_human_verification_action),
        "filter-human-verification-gates": verification_api.filter_gates,
    }
    if action == "orchestration-policy-binding-check":
        if set(payload) != {"binding", "effective_policy"}:
            raise ValueError(
                "orchestration policy binding input requires binding and effective_policy"
            )
        return verification_v1.validate_orchestration_policy_binding(
            payload["binding"], payload["effective_policy"]
        )
    validator = validators.get(action)
    if validator is None:
        raise AssertionError(action)
    return validator(payload)


def _domain_operation(
    namespace: str,
    operation: str,
    action: str,
    arguments: tuple[str, ...],
    stdin: TextIO,
) -> Any:
    try:
        parsed = build_internal_parser().parse_args((action, *arguments))
    except InternalHelp as requested:
        help_text = requested.help_text.replace(
            f"linear_spanks_cli.py {action}",
            f"linear_spanks_cli.py {namespace} {operation}",
            1,
        )
        return {"operation": f"{namespace} {operation}", "help": help_text}
    dispatchers: Mapping[str, Callable[[str, argparse.Namespace, TextIO], Any]] = {
        "context": _dispatch_context,
        "reviews": _dispatch_review_or_runtime,
        "runtime": _dispatch_review_or_runtime,
        "routing": _dispatch_routing,
        "graphs": _dispatch_graphs,
        "isolation": _dispatch_isolation,
        "orchestration": _dispatch_orchestration,
        "state": _dispatch_state,
        "verification": _dispatch_verification,
    }
    dispatcher = dispatchers.get(namespace)
    if dispatcher is None:
        raise UsageError("NAMESPACE_NOT_FOUND", f"Unknown internal namespace: {namespace}")
    return checked(dispatcher, action, parsed, stdin)


def _run_internal(
    namespace: str,
    operation: str,
    arguments: tuple[str, ...],
    stdin: TextIO,
) -> Any:
    if namespace == "contracts":
        return _contract_operation(operation, arguments)
    if namespace == "artifacts":
        return _artifact_operation(operation, arguments)
    if namespace == "docs":
        return _documentation_operation(operation, arguments)
    if namespace == "installation":
        return _installation_operation(operation, arguments)
    if namespace == "extensions":
        return _extension_operation(operation, arguments)
    operations = INTERNAL_OPERATIONS.get(namespace)
    if operations is None:
        raise UsageError("NAMESPACE_NOT_FOUND", f"Unknown internal namespace: {namespace}")
    legacy_action = operations.get(operation)
    if legacy_action is None:
        raise UsageError("OPERATION_NOT_FOUND", f"Unknown {namespace} operation: {operation}")
    translated = (
        arguments
        if arguments in {("--help",), ("-h",)}
        else _translate_public_command_argument(namespace, operation, arguments)
    )
    return _domain_operation(namespace, operation, legacy_action, translated, stdin)


CONTEXT_OPERATIONS: dict[str, Callable[[dict[str, Any]], Any]] = {
    "milestone-checkpoint-preview": milestone_checkpoint.preview,
    "milestone-checkpoint-next": milestone_checkpoint.next_operation,
    "archived-task": milestone_checkpoint.resolve_archived_task,
    "task-checkpoint-preview": task_checkpoint.preview,
    "task-checkpoint-next": task_checkpoint.next_operation,
    "task-comment-slots": task_checkpoint.read_slots,
    "task-comment-slot": task_checkpoint.slot_plan,
    "dispatch-check": context_domain.validate_dispatch,
    "compile": context_domain.compile_packet,
    "validate": context_domain.validate_packet,
    "resolve-budget": lambda p: context_domain.resolve_budget(p).as_dict(),
    "inspect-state": context_domain.inspect_context,
    "checkpoint-preview": context_domain.checkpoint_preview,
    "artifact-check": context_domain.validate_context_artifact,
    "repair-next": context_domain.repair_action,
    "reuse": context_domain.reuse_analysis,
    "detect-evidence": context_domain.detect_repository_evidence,
    "select-skills": context_domain.select_skills,
    "load-skills": context_domain.load_skills,
    "compressor": context_domain.compressor_slot,
}
DOCUMENT_OPERATIONS = {"budget-prepare", "activate-prepare", "delta-prepare", "expand", "assemble"}
for _name in (*CONTEXT_OPERATIONS, *DOCUMENT_OPERATIONS):
    INTERNAL_OPERATIONS["context"][_name] = _name
INTERNAL_OPERATIONS["runtime"]["inspect-state"] = "inspect-state"
WORKFLOW_OPERATIONS = {
    ("routing", "task-policy"): routing_v1.task_execution_policy,
    ("runtime", "task-next"): runtime_domain.task_next,
    ("reviews", "refresh-prepare"): reviews_api.prepare_refresh,
}
for _namespace, _operation in WORKFLOW_OPERATIONS:
    INTERNAL_OPERATIONS[_namespace][_operation] = _operation


def run_internal(namespace: str, operation: str, arguments: tuple[str, ...], stdin: TextIO) -> Any:
    # One optional refreshed policy inventory wraps every validator, including legacy readers.
    remaining = list(arguments)
    policy = None
    if "--context-policy" in remaining:
        index = remaining.index("--context-policy")
        if index + 1 >= len(remaining) or remaining.count("--context-policy") != 1:
            raise UsageError(
                "INVALID_CONTEXT_POLICY", "--context-policy requires one inventory file"
            )
        policy = _payload_from(remaining[index + 1], stdin, "context policy")
        del remaining[index : index + 2]
    if remaining == ["--help"] and (
        (namespace == "context" and operation in CONTEXT_OPERATIONS.keys() | DOCUMENT_OPERATIONS)
        or (namespace == "runtime" and operation == "inspect-state")
        or (namespace, operation) in WORKFLOW_OPERATIONS
    ):
        return {
            "operation": f"{namespace} {operation}",
            "help": f"usage: linear_spanks_cli.py {namespace} {operation} [JSON-path] [--context-policy inventory.json]",
        }
    with context_domain.budget_session(policy):
        if (namespace, operation) in WORKFLOW_OPERATIONS:
            if len(remaining) > 1:
                raise UsageError(
                    "INVALID_ARGUMENTS", "Workflow operation accepts one JSON path or stdin"
                )
            return checked(
                WORKFLOW_OPERATIONS[(namespace, operation)],
                _payload_from(remaining[0] if remaining else None, stdin, operation),
            )
        if namespace == "context" and operation in CONTEXT_OPERATIONS.keys() | DOCUMENT_OPERATIONS:
            if len(remaining) > 1:
                raise UsageError(
                    "INVALID_ARGUMENTS", "Context operation accepts one JSON path or stdin"
                )
            payload = _payload_from(remaining[0] if remaining else None, stdin, operation)
            if operation in DOCUMENT_OPERATIONS:
                return checked(context_domain.prepare_document_operation, operation, payload)
            return checked(CONTEXT_OPERATIONS[operation], payload)
        if namespace == "runtime" and operation == "inspect-state":
            if len(remaining) > 1:
                raise UsageError(
                    "INVALID_ARGUMENTS", "Runtime inspection accepts one JSON path or stdin"
                )
            return checked(
                runtime_domain.inspect,
                _payload_from(remaining[0] if remaining else None, stdin, operation),
            )
        return _run_internal(namespace, operation, tuple(remaining), stdin)
