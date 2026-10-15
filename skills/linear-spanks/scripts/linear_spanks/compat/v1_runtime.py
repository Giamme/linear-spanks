#!/usr/bin/env python3
"""Frozen v1 diagnostic CLI adapter over the owned domain implementations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ..contracts.legacy import *  # noqa: F403
from ..core.legacy_constants import *  # noqa: F403
from ..core.legacy_validation import (
    _require_exact_object_fields,
    _require_nonempty_text,
    _require_positive_revision,
)
from ..domains._context_v1 import *  # noqa: F403
from ..domains._graphs_v1 import *  # noqa: F403
from ..domains._isolation_v1 import *  # noqa: F403
from ..domains._orchestration_v1 import *  # noqa: F403
from ..domains._reviews_v1 import *  # noqa: F403
from ..domains._reviews_v1 import _validate_review_budget
from ..domains._routing_v1 import *  # noqa: F403
from ..domains._runtime_v1 import *  # noqa: F403
from ..domains._state_v1 import *  # noqa: F403
from ..domains._verification_v1 import *  # noqa: F403
from ..domains.execution import *  # noqa: F403
from ..domains.legacy_validation import validate_contracts

def marker_from_path(path: str) -> dict[str, Any]:
    return parse_marker(Path(path).read_text(encoding="utf-8"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)

    command = subparsers.add_parser("command")
    command.add_argument("name")

    envelope = subparsers.add_parser("execution-envelope")
    envelope.add_argument("name")
    envelope.add_argument("--scan", choices=REPOSITORY_SCAN_TIERS)
    envelope.add_argument("--assurance", choices=ASSURANCE_VALUES)
    envelope.add_argument("--isolated-worktree", action="store_true")
    envelope.add_argument("--milestone-stage")

    brief = subparsers.add_parser("execution-brief")
    brief.add_argument("name")
    brief.add_argument("--scan", choices=REPOSITORY_SCAN_TIERS)
    brief.add_argument("--assurance", choices=ASSURANCE_VALUES, default="balanced")
    brief.add_argument("--isolated-worktree", action="store_true")
    brief.add_argument("--milestone-stage")

    runtime_card = subparsers.add_parser("runtime-card")
    runtime_card.add_argument("name")
    runtime_card.add_argument("--isolated-worktree", action="store_true")
    runtime_card.add_argument("--milestone-stage")

    context = subparsers.add_parser("context-check")
    context.add_argument("name")
    context.add_argument("--estimated-tokens", type=int, required=True)
    context.add_argument("--metric", action="append", default=[])
    context.add_argument(
        "--scope", choices=("command", "planner", "repository"), default="command"
    )
    context.add_argument("--scan", choices=REPOSITORY_SCAN_TIERS)

    packet = subparsers.add_parser("context-packet")
    packet.add_argument("name")
    packet.add_argument("path", help="JSON object with items and measured metrics")
    packet.add_argument(
        "--scope", choices=("command", "planner", "repository"), default="command"
    )
    packet.add_argument("--scan", choices=REPOSITORY_SCAN_TIERS)

    checkpoint = subparsers.add_parser("scan-checkpoint")
    checkpoint.add_argument("path", help="repository scan checkpoint JSON file")
    checkpoint.add_argument("--expected-source-revision")
    checkpoint.add_argument(
        "--drift-classification",
        choices=("valid", "safe-refresh", "material"),
    )

    review_checkpoint = subparsers.add_parser("milestone-review-checkpoint")
    review_checkpoint.add_argument("path", nargs="?", help="checkpoint JSON; omit for stdin")
    review_checkpoint.add_argument("--current-session-id")
    review_checkpoint.add_argument("--expected-marker-revision", type=int)
    review_checkpoint.add_argument("--expected-matrix-hash")
    review_checkpoint.add_argument("--expected-dependency-graph-hash")
    review_checkpoint.add_argument("--expected-coverage-hash")
    review_checkpoint.add_argument("--current-source-revisions")

    review_finalize = subparsers.add_parser("milestone-review-finalize")
    review_finalize.add_argument("path", nargs="?", help="finalization JSON; omit for stdin")

    review_budget = subparsers.add_parser("milestone-review-budget")
    review_budget.add_argument("--model-turns", type=int, required=True)
    review_budget.add_argument("--active-context-tokens", type=int, required=True)
    review_budget.add_argument("--cumulative-input-tokens", type=int)
    review_budget.add_argument("--phase-cumulative-input-tokens", type=int)
    review_budget.add_argument("--planned-batches", type=int, required=True)
    review_budget.add_argument("--telemetry-available", action="store_true")

    for action, help_text in (
        ("incremental-plan-check", "incremental implementation plan"),
        ("plan-drift-check", "bound plan and current evidence"),
        ("review-coverage-check", "incremental review coverage input"),
        ("next-wave-check", "next planning wave input"),
        ("milestone-runtime-check", "milestone runtime projection"),
        ("milestone-runtime-storage-check", "runtime storage inventory"),
        ("milestone-runtime-migrate", "legacy milestone runtime inventory"),
        ("autopilot-policy-check", "autopilot policy decision"),
        ("autopilot-binding-check", "persisted guarded autopilot policy"),
        ("milestone-run-mode-check", "run-milestone alias and loop options"),
        ("autopilot-loop-check", "autopilot loop state"),
        ("milestone-findings-check", "testing findings batch"),
    ):
        action_parser = subparsers.add_parser(action)
        action_parser.add_argument(
            "path", nargs="?", help=f"{help_text}; omit to read stdin"
        )

    tier = subparsers.add_parser("tier-recommend")
    tier.add_argument("path", nargs="?", help="assessment JSON file; omit to read stdin")

    routing = subparsers.add_parser("routing-check")
    routing.add_argument("--harness", required=True)
    routing.add_argument("--role", required=True)
    routing.add_argument("--strength", required=True)
    routing.add_argument("--configured-model")
    routing.add_argument("--assurance", choices=ASSURANCE_VALUES, default="strict")

    decision = subparsers.add_parser("orchestration-decision")
    decision.add_argument("path", nargs="?", help="decision JSON file; omit to read stdin")

    preflight = subparsers.add_parser("preflight-check")
    preflight.add_argument("receipt", help="preflight receipt JSON file")
    preflight.add_argument("current", help="current preflight fields JSON file")

    readback = subparsers.add_parser("linear-readback-plan")
    readback.add_argument("path", nargs="?", help="read-back JSON file; omit to read stdin")

    completion = subparsers.add_parser("completion-receipt-check")
    completion.add_argument("path", nargs="?", help="receipt JSON file; omit to read stdin")

    capsule = subparsers.add_parser("project-capsule-check")
    capsule.add_argument("path", nargs="?", help="project capsule JSON file; omit to read stdin")

    rollover_receipt = subparsers.add_parser("rollover-receipt-check")
    rollover_receipt.add_argument(
        "path", nargs="?", help="rollover receipt JSON file; omit to read stdin"
    )
    rollover_receipt.add_argument("--expected-source-revision", type=int)
    rollover_receipt.add_argument("--expected-source-snapshot-hash")
    rollover_receipt.add_argument("--expected-approved-plan-hash")

    rollover_transition = subparsers.add_parser("rollover-transition")
    rollover_transition.add_argument("--from", dest="current", required=True)
    rollover_transition.add_argument("--to", dest="target", required=True)

    graph_build = subparsers.add_parser("dependency-graph-build")
    graph_build.add_argument("path", nargs="?", help="graph source JSON; omit to read stdin")

    graph_check = subparsers.add_parser("dependency-graph-check")
    graph_check.add_argument("path", nargs="?", help="graph JSON; omit to read stdin")

    graph_render = subparsers.add_parser("dependency-graph-render")
    graph_render.add_argument("path", nargs="?", help="graph JSON; omit to read stdin")

    graph_parse = subparsers.add_parser("parse-dependency-graph")
    graph_parse.add_argument("path", nargs="?", help="milestone description; omit to read stdin")

    graph_upsert = subparsers.add_parser("dependency-graph-upsert")
    graph_upsert.add_argument("description", help="milestone description file")
    graph_upsert.add_argument("graph", help="validated graph JSON file")

    wave_select = subparsers.add_parser("wave-select")
    wave_select.add_argument("path", nargs="?", help="graph JSON; omit to read stdin")
    wave_select.add_argument("--max-parallel", type=int, default=2)
    wave_select.add_argument("--capacity", type=int, required=True)

    wave_receipt = subparsers.add_parser("wave-receipt-check")
    wave_receipt.add_argument("path", nargs="?", help="wave receipt JSON; omit to read stdin")

    isolation_preflight = subparsers.add_parser("isolation-preflight-check")
    isolation_preflight.add_argument(
        "path", nargs="?", help="isolation preflight JSON; omit to read stdin"
    )

    isolation_receipt = subparsers.add_parser("isolation-receipt-check")
    isolation_receipt.add_argument(
        "path", nargs="?", help="isolation receipt JSON; omit to read stdin"
    )

    isolation_transition = subparsers.add_parser("isolation-transition")
    isolation_transition.add_argument("receipt", help="isolation receipt JSON file")
    isolation_transition.add_argument(
        "request", help="isolation transition request JSON file"
    )

    for action, help_text in (
        ("human-verification-policy-check", "project policy payload"),
        ("human-verification-override-check", "milestone override payload"),
        ("human-verification-policy-document-check", "project document lookup payload"),
        ("human-verification-effective", "policy resolution payload"),
        ("human-verification-preview-check", "policy change preview"),
        ("human-verification-gate-check", "managed gate payload"),
        ("human-verification-checklist-check", "human checklist payload"),
        ("human-verification-action-check", "human verification lifecycle action"),
        ("filter-human-verification-gates", "issue inventory"),
        ("orchestration-policy-binding-check", "receipt and effective policy binding"),
    ):
        human_action = subparsers.add_parser(action)
        human_action.add_argument(
            "path", nargs="?", help=f"{help_text}; omit to read stdin"
        )

    human_marker = subparsers.add_parser("human-verification-marker-check")
    human_marker.add_argument(
        "kind",
        choices=("project-policy", "milestone-override", "gate", "checklist", "repair"),
    )
    human_marker.add_argument(
        "path", nargs="?", help="managed marker text; omit to read stdin"
    )

    project_role = subparsers.add_parser("project-role-card")
    project_role.add_argument(
        "role",
        choices=(
            "project-orchestrator", "milestone-orchestrator",
            "task-executor", "task-verifier",
        ),
    )

    milestone_role = subparsers.add_parser("milestone-role-card")
    milestone_role.add_argument(
        "role", choices=("milestone-orchestrator", "task-executor", "task-verifier")
    )

    project_next = subparsers.add_parser("project-loop-next")
    project_next.add_argument(
        "path", nargs="?", help="project loop event input; omit to read stdin"
    )

    project_receipt = subparsers.add_parser("project-loop-receipt-check")
    project_receipt.add_argument(
        "path", nargs="?", help="project loop receipt or selection; omit to read stdin"
    )

    project_transition = subparsers.add_parser("project-loop-transition")
    project_transition.add_argument("receipt", help="project loop receipt JSON file")
    project_transition.add_argument("request", help="project loop transition JSON file")

    milestone_next = subparsers.add_parser("milestone-loop-next")
    milestone_next.add_argument(
        "path", nargs="?", help="milestone loop event input; omit to read stdin"
    )

    milestone_receipt = subparsers.add_parser("milestone-loop-receipt-check")
    milestone_receipt.add_argument(
        "path", nargs="?", help="milestone loop receipt or selection; omit to read stdin"
    )

    milestone_transition = subparsers.add_parser("milestone-loop-transition")
    milestone_transition.add_argument("receipt", help="milestone loop receipt JSON file")
    milestone_transition.add_argument("request", help="milestone loop transition JSON file")

    scope_check = subparsers.add_parser("orchestration-scope-check")
    scope_check.add_argument(
        "path", nargs="?", help="orchestration scope input; omit to read stdin"
    )

    role_handoff = subparsers.add_parser("role-handoff-check")
    role_handoff.add_argument("path", nargs="?", help="role handoff; omit to read stdin")
    role_handoff.add_argument(
        "--receipt", help="project loop receipt used to bind the logical role"
    )
    role_handoff.add_argument("--orchestration", choices=("project", "milestone"), default="project")

    role_capability = subparsers.add_parser("role-capability-check")
    role_capability.add_argument(
        "path", nargs="?", help="role capability request; omit to read stdin"
    )
    role_capability.add_argument("--orchestration", choices=("project", "milestone"), default="project")

    task_attempt = subparsers.add_parser("task-attempt-check")
    task_attempt.add_argument("path", nargs="?", help="task attempt; omit to read stdin")

    model_escalation = subparsers.add_parser("model-escalation-check")
    model_escalation.add_argument(
        "path", nargs="?", help="model escalation request; omit to read stdin"
    )

    verification_ledger = subparsers.add_parser("verification-ledger-check")
    verification_ledger.add_argument(
        "path", nargs="?", help="verification ledger; omit to read stdin"
    )
    verification_ledger.add_argument("--expected-task-id")
    verification_ledger.add_argument("--expected-verifier-id")
    verification_ledger.add_argument("--expected-plan-revision", type=int)

    transition = subparsers.add_parser("transition")
    transition.add_argument("name")
    transition.add_argument("--from", dest="current", required=True)
    transition.add_argument("--resume-stage")
    transition.add_argument("--mode", choices=("legacy", "next-wave", "incremental"))

    issue_transition = subparsers.add_parser("issue-transition")
    issue_transition.add_argument("command")
    issue_transition.add_argument("--from-status", required=True)
    issue_transition.add_argument("--to-status", required=True)

    marker = subparsers.add_parser("marker")
    marker.add_argument("--project-id", required=True)
    marker.add_argument("--milestone-id", required=True)
    marker.add_argument("--stage", required=True)
    marker.add_argument("--resume-stage")
    marker.add_argument("--revision", type=int, required=True)
    marker.add_argument("--last-command", required=True)
    marker.add_argument("--run-id", required=True)
    marker.add_argument("--updated-at")

    parse = subparsers.add_parser("parse-marker")
    parse.add_argument("path", nargs="?", help="description file; omit to read stdin")

    advance = subparsers.add_parser("advance-state")
    advance.add_argument("--command", required=True)
    advance.add_argument("--transition", required=True)
    advance.add_argument("--current-marker", required=True)
    advance.add_argument("--replacement-marker", required=True)
    advance.add_argument("--mode", choices=("legacy", "next-wave", "incremental"))

    payload = subparsers.add_parser("payload-hash")
    payload.add_argument("path", nargs="?", help="JSON payload file; omit to read stdin")

    validate = subparsers.add_parser("validate-contracts")

    key = subparsers.add_parser("idempotency-key")
    key.add_argument("--project-id", required=True)
    key.add_argument("--entity-id", required=True)
    key.add_argument("--command", required=True)
    key.add_argument("--revision", type=int, required=True)
    key.add_argument("--operation-id")
    key.add_argument("--payload-hash")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.action == "command":
            print(json.dumps(command_by_name(args.name), sort_keys=True))
        elif args.action == "execution-envelope":
            print(
                json.dumps(
                    execution_envelope(
                        args.name, args.scan, args.assurance, args.isolated_worktree,
                        args.milestone_stage,
                    ), sort_keys=True
                )
            )
        elif args.action == "execution-brief":
            print(
                json.dumps(
                    execution_brief(
                        args.name, args.assurance, args.scan, args.isolated_worktree,
                        args.milestone_stage,
                    ), sort_keys=True
                )
            )
        elif args.action == "runtime-card":
            print(json.dumps(task_runtime_card(
                args.name, args.isolated_worktree, args.milestone_stage
            ), sort_keys=True))
        elif args.action == "project-role-card":
            print(json.dumps(project_role_card(args.role), sort_keys=True))
        elif args.action == "milestone-role-card":
            print(json.dumps(milestone_role_card(args.role), sort_keys=True))
        elif args.action == "context-check":
            print(
                json.dumps(
                    validate_context_usage(
                        args.name,
                        args.estimated_tokens,
                        args.metric,
                        args.scope,
                        args.scan,
                    ),
                    sort_keys=True,
                )
            )
        elif args.action == "context-packet":
            print(
                json.dumps(
                    measure_context_packet(
                        args.name,
                        load_json(Path(args.path)),
                        args.scope,
                        args.scan,
                    ),
                    sort_keys=True,
                )
            )
        elif args.action == "scan-checkpoint":
            print(
                json.dumps(
                    validate_repository_checkpoint(
                        load_json(Path(args.path)),
                        args.expected_source_revision,
                        Path(args.path),
                        args.drift_classification,
                    ),
                    sort_keys=True,
                )
            )
        elif args.action == "milestone-review-budget":
            print(json.dumps(_validate_review_budget({
                "model_turns": args.model_turns,
                "active_context_tokens": args.active_context_tokens,
                "cumulative_input_tokens": args.cumulative_input_tokens,
                "phase_cumulative_input_tokens": args.phase_cumulative_input_tokens,
                "planned_batches": args.planned_batches,
                "telemetry_available": args.telemetry_available,
            }), sort_keys=True))
        elif args.action in {
            "milestone-review-checkpoint", "milestone-review-finalize",
            "incremental-plan-check", "plan-drift-check", "review-coverage-check",
            "next-wave-check", "milestone-runtime-check",
            "milestone-runtime-storage-check", "milestone-runtime-migrate",
            "autopilot-policy-check", "autopilot-binding-check",
            "milestone-run-mode-check", "autopilot-loop-check",
            "milestone-findings-check",
        }:
            runtime_text = (
                Path(args.path).read_text(encoding="utf-8") if args.path else sys.stdin.read()
            )
            runtime_payload = json.loads(runtime_text)
            if not isinstance(runtime_payload, dict):
                raise ValueError(f"{args.action} input must be a JSON object")
            if args.action == "milestone-review-checkpoint":
                source_revisions = (
                    load_json(Path(args.current_source_revisions))
                    if args.current_source_revisions else None
                )
                runtime_output = validate_milestone_review_checkpoint(
                    runtime_payload,
                    current_session_id=args.current_session_id,
                    expected_marker_revision=args.expected_marker_revision,
                    expected_matrix_hash=args.expected_matrix_hash,
                    expected_dependency_graph_hash=args.expected_dependency_graph_hash,
                    expected_coverage_hash=args.expected_coverage_hash,
                    current_source_revisions=source_revisions,
                )
            elif args.action == "milestone-review-finalize":
                runtime_output = validate_milestone_review_finalization(runtime_payload)
            else:
                validators = {
                    "incremental-plan-check": validate_incremental_plan,
                    "plan-drift-check": classify_plan_drift,
                    "review-coverage-check": calculate_incremental_review_coverage,
                    "next-wave-check": select_next_planning_wave,
                    "milestone-runtime-check": validate_milestone_runtime,
                    "milestone-runtime-storage-check": reconcile_milestone_runtime_storage,
                    "milestone-runtime-migrate": migrate_milestone_runtime_projection,
                    "autopilot-policy-check": validate_autopilot_policy,
                    "autopilot-binding-check": validate_guarded_autopilot_binding,
                    "milestone-run-mode-check": resolve_milestone_run_mode,
                    "autopilot-loop-check": validate_autopilot_loop,
                    "milestone-findings-check": validate_milestone_findings,
                }
                runtime_output = validators[args.action](runtime_payload)
            print(json.dumps(runtime_output, sort_keys=True))
        elif args.action == "tier-recommend":
            if args.path:
                assessment = load_json(Path(args.path))
            else:
                assessment = json.loads(sys.stdin.read())
                if not isinstance(assessment, dict):
                    raise ValueError("assessment input must be a JSON object")
            print(json.dumps(tier_recommendation(assessment), sort_keys=True))
        elif args.action == "routing-check":
            print(
                json.dumps(
                    routing_check(
                        args.harness,
                        args.role,
                        args.strength,
                        args.configured_model,
                        args.assurance,
                    ),
                    sort_keys=True,
                )
            )
        elif args.action == "orchestration-decision":
            if args.path:
                decision_payload = load_json(Path(args.path))
            else:
                decision_payload = json.loads(sys.stdin.read())
                if not isinstance(decision_payload, dict):
                    raise ValueError("orchestration decision input must be a JSON object")
            print(json.dumps(orchestration_decision(decision_payload), sort_keys=True))
        elif args.action == "preflight-check":
            print(
                json.dumps(
                    validate_preflight_receipt(
                        load_json(Path(args.receipt)), load_json(Path(args.current))
                    ),
                    sort_keys=True,
                )
            )
        elif args.action == "linear-readback-plan":
            readback_payload = (
                load_json(Path(args.path)) if args.path else json.loads(sys.stdin.read())
            )
            if not isinstance(readback_payload, dict):
                raise ValueError("Linear read-back input must be a JSON object")
            print(json.dumps(linear_readback_plan(readback_payload), sort_keys=True))
        elif args.action == "completion-receipt-check":
            completion_payload = (
                load_json(Path(args.path)) if args.path else json.loads(sys.stdin.read())
            )
            if not isinstance(completion_payload, dict):
                raise ValueError("completion receipt input must be a JSON object")
            print(json.dumps(validate_completion_receipt(completion_payload), sort_keys=True))
        elif args.action == "project-capsule-check":
            capsule_payload = (
                load_json(Path(args.path)) if args.path else json.loads(sys.stdin.read())
            )
            if not isinstance(capsule_payload, dict):
                raise ValueError("project capsule input must be a JSON object")
            print(json.dumps(validate_project_capsule(capsule_payload), sort_keys=True))
        elif args.action == "rollover-receipt-check":
            rollover_payload = (
                load_json(Path(args.path)) if args.path else json.loads(sys.stdin.read())
            )
            if not isinstance(rollover_payload, dict):
                raise ValueError("rollover receipt input must be a JSON object")
            print(
                json.dumps(
                    validate_rollover_receipt(
                        rollover_payload,
                        args.expected_source_revision,
                        args.expected_source_snapshot_hash,
                        args.expected_approved_plan_hash,
                    ),
                    sort_keys=True,
                )
            )
        elif args.action == "rollover-transition":
            print(validate_rollover_transition(args.current, args.target))
        elif args.action in {
            "dependency-graph-build", "dependency-graph-check", "dependency-graph-render",
            "wave-select", "wave-receipt-check", "isolation-preflight-check",
            "isolation-receipt-check",
        }:
            graph_text = Path(args.path).read_text(encoding="utf-8") if args.path else sys.stdin.read()
            graph_payload = json.loads(graph_text)
            if not isinstance(graph_payload, dict):
                raise ValueError(f"{args.action} input must be a JSON object")
            if args.action == "dependency-graph-build":
                print(json.dumps(build_dependency_graph(graph_payload), sort_keys=True))
            elif args.action == "dependency-graph-check":
                print(json.dumps(validate_dependency_graph(graph_payload), sort_keys=True))
            elif args.action == "dependency-graph-render":
                print(render_dependency_graph(graph_payload), end="")
            elif args.action == "wave-select":
                print(json.dumps(select_parallel_wave(
                    graph_payload, args.max_parallel, args.capacity
                ), sort_keys=True))
            elif args.action == "isolation-preflight-check":
                print(json.dumps(validate_isolation_preflight(graph_payload), sort_keys=True))
            elif args.action == "isolation-receipt-check":
                print(json.dumps(validate_isolation_receipt(graph_payload), sort_keys=True))
            else:
                print(json.dumps(validate_wave_receipt(graph_payload), sort_keys=True))
        elif args.action == "isolation-transition":
            print(json.dumps(transition_isolation_receipt(
                load_json(Path(args.receipt)), load_json(Path(args.request))
            ), sort_keys=True))
        elif args.action in {
            "human-verification-policy-check",
            "human-verification-override-check",
            "human-verification-policy-document-check",
            "human-verification-effective",
            "human-verification-preview-check",
            "human-verification-gate-check",
            "human-verification-checklist-check",
            "human-verification-action-check",
            "filter-human-verification-gates",
            "orchestration-policy-binding-check",
        }:
            human_text = (
                Path(args.path).read_text(encoding="utf-8") if args.path else sys.stdin.read()
            )
            human_payload = json.loads(human_text)
            if not isinstance(human_payload, dict):
                raise ValueError(f"{args.action} input must be a JSON object")
            validators = {
                "human-verification-policy-check": validate_human_project_policy,
                "human-verification-override-check": validate_human_milestone_override,
                "human-verification-policy-document-check": check_human_policy_document,
                "human-verification-effective": resolve_human_verification_policy,
                "human-verification-preview-check": validate_human_verification_preview,
                "human-verification-gate-check": validate_human_gate,
                "human-verification-checklist-check": validate_human_checklist,
                "human-verification-action-check": validate_human_verification_action,
                "filter-human-verification-gates": filter_human_verification_gates,
            }
            if args.action == "orchestration-policy-binding-check":
                wrapper = _require_exact_object_fields(
                    human_payload, ["binding", "effective_policy"],
                    "orchestration policy binding input",
                )
                human_output = validate_orchestration_policy_binding(
                    wrapper["binding"], wrapper["effective_policy"]
                )
            else:
                human_output = validators[args.action](human_payload)
            print(json.dumps(human_output, sort_keys=True))
        elif args.action == "human-verification-marker-check":
            human_marker_text = (
                Path(args.path).read_text(encoding="utf-8") if args.path else sys.stdin.read()
            )
            print(json.dumps(
                parse_human_verification_marker(args.kind, human_marker_text),
                sort_keys=True,
            ))
        elif args.action in {
            "project-loop-next", "project-loop-receipt-check", "milestone-loop-next",
            "milestone-loop-receipt-check", "orchestration-scope-check",
            "role-handoff-check", "role-capability-check", "task-attempt-check",
            "model-escalation-check", "verification-ledger-check",
        }:
            project_text = (
                Path(args.path).read_text(encoding="utf-8")
                if args.path else sys.stdin.read()
            )
            project_payload = json.loads(project_text)
            if not isinstance(project_payload, dict):
                raise ValueError(f"{args.action} input must be a JSON object")
            if args.action == "project-loop-next":
                output = select_project_loop_event(project_payload)
            elif args.action == "project-loop-receipt-check":
                output = check_project_loop_receipts(project_payload)
            elif args.action == "milestone-loop-next":
                output = select_milestone_loop_event(project_payload)
            elif args.action == "milestone-loop-receipt-check":
                output = check_milestone_loop_receipts(project_payload)
            elif args.action == "orchestration-scope-check":
                output = check_orchestration_scope(project_payload)
            elif args.action == "role-handoff-check":
                receipt_payload = (
                    load_json(Path(args.receipt)) if args.receipt else None
                )
                output = validate_role_handoff(
                    project_payload, receipt_payload, args.orchestration
                )
            elif args.action == "role-capability-check":
                output = validate_role_capability(project_payload, args.orchestration)
            elif args.action == "task-attempt-check":
                output = validate_task_attempt(project_payload)
            elif args.action == "model-escalation-check":
                output = validate_model_escalation(project_payload)
            else:
                output = validate_verification_ledger(
                    project_payload,
                    args.expected_task_id,
                    args.expected_verifier_id,
                    args.expected_plan_revision,
                )
            print(json.dumps(output, sort_keys=True))
        elif args.action == "project-loop-transition":
            print(json.dumps(transition_project_loop_receipt(
                load_json(Path(args.receipt)), load_json(Path(args.request))
            ), sort_keys=True))
        elif args.action == "milestone-loop-transition":
            print(json.dumps(transition_milestone_loop_receipt(
                load_json(Path(args.receipt)), load_json(Path(args.request))
            ), sort_keys=True))
        elif args.action == "parse-dependency-graph":
            graph_text = Path(args.path).read_text(encoding="utf-8") if args.path else sys.stdin.read()
            print(json.dumps(parse_dependency_graph(graph_text), sort_keys=True))
        elif args.action == "dependency-graph-upsert":
            description = Path(args.description).read_text(encoding="utf-8")
            print(upsert_dependency_graph(description, load_json(Path(args.graph))), end="")
        elif args.action == "transition":
            print(validate_transition(args.name, args.current, args.resume_stage, args.mode))
        elif args.action == "issue-transition":
            print(
                json.dumps(
                    validate_issue_transition(
                        args.command, args.from_status, args.to_status
                    ),
                    sort_keys=True,
                )
            )
        elif args.action == "marker":
            payload = marker_payload(args)
            encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True)
            print(f"<!-- linear-spanks:state {encoded} -->")
        elif args.action == "parse-marker":
            text = Path(args.path).read_text(encoding="utf-8") if args.path else sys.stdin.read()
            print(json.dumps(parse_marker(text), sort_keys=True))
        elif args.action == "advance-state":
            print(
                json.dumps(
                    validate_state_advance(
                        args.command,
                        args.transition,
                        marker_from_path(args.current_marker),
                        marker_from_path(args.replacement_marker),
                        args.mode,
                    ),
                    sort_keys=True,
                )
            )
        elif args.action == "payload-hash":
            text = Path(args.path).read_text(encoding="utf-8") if args.path else sys.stdin.read()
            print(normalized_payload_hash(json.loads(text)))
        elif args.action == "validate-contracts":
            print(json.dumps(validate_contracts(), sort_keys=True))
        elif args.action == "idempotency-key":
            print(
                idempotency_key(
                    args.project_id,
                    args.entity_id,
                    args.command,
                    args.revision,
                    args.operation_id,
                    args.payload_hash,
                )
            )
        else:
            raise AssertionError(args.action)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"workflow contract error: {error}", file=sys.stderr)
        return 2
    return 0
