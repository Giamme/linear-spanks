"""Argument grammar for namespaced internal diagnostic operations."""

from __future__ import annotations

import argparse
from typing import Any, Never

from ..core.errors import UsageError
from ..core.legacy_constants import ASSURANCE_VALUES, REPOSITORY_SCAN_TIERS


class InternalHelp(Exception):
    def __init__(self, help_text: str) -> None:
        super().__init__(help_text)
        self.help_text = help_text


class InternalArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("allow_abbrev", False)
        super().__init__(*args, **kwargs)

    def error(self, message: str) -> Never:
        raise UsageError("INVALID_ARGUMENTS", message)

    def exit(self, status: int = 0, message: str | None = None) -> Never:
        if status == 0:
            raise InternalHelp(self.format_help())
        raise UsageError("INVALID_ARGUMENTS", message or "invalid internal arguments")

    def print_help(self, file: object | None = None) -> None:
        del file


def build_parser() -> argparse.ArgumentParser:
    parser = InternalArgumentParser(prog="linear_spanks_cli.py", description=__doc__)
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
    context.add_argument("--scope", choices=("command", "planner", "repository"), default="command")
    context.add_argument("--scan", choices=REPOSITORY_SCAN_TIERS)

    packet = subparsers.add_parser("context-packet")
    packet.add_argument("name")
    packet.add_argument("path", help="JSON object with items and measured metrics")
    packet.add_argument("--scope", choices=("command", "planner", "repository"), default="command")
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
        action_parser.add_argument("path", nargs="?", help=f"{help_text}; omit to read stdin")

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
    isolation_transition.add_argument("request", help="isolation transition request JSON file")

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
        human_action.add_argument("path", nargs="?", help=f"{help_text}; omit to read stdin")

    human_marker = subparsers.add_parser("human-verification-marker-check")
    human_marker.add_argument(
        "kind",
        choices=("project-policy", "milestone-override", "gate", "checklist", "repair"),
    )
    human_marker.add_argument("path", nargs="?", help="managed marker text; omit to read stdin")

    project_role = subparsers.add_parser("project-role-card")
    project_role.add_argument(
        "role",
        choices=(
            "project-orchestrator",
            "milestone-orchestrator",
            "task-executor",
            "task-verifier",
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
    role_handoff.add_argument(
        "--orchestration", choices=("project", "milestone"), default="project"
    )

    role_capability = subparsers.add_parser("role-capability-check")
    role_capability.add_argument(
        "path", nargs="?", help="role capability request; omit to read stdin"
    )
    role_capability.add_argument(
        "--orchestration", choices=("project", "milestone"), default="project"
    )

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
    marker.add_argument("--command-mode", choices=("step", "loop"))
    marker.add_argument("--run-id", required=True)
    marker.add_argument("--updated-at")

    parse = subparsers.add_parser("parse-marker")
    parse.add_argument("path", nargs="?", help="description file; omit to read stdin")

    advance = subparsers.add_parser("advance-state")
    advance.add_argument("--command", required=True)
    advance.add_argument("--command-mode", choices=("step", "loop"))
    advance.add_argument("--transition", required=True)
    advance.add_argument("--current-marker", required=True)
    advance.add_argument("--replacement-marker", required=True)
    advance.add_argument("--mode", choices=("legacy", "next-wave", "incremental"))

    payload = subparsers.add_parser("payload-hash")
    payload.add_argument("path", nargs="?", help="JSON payload file; omit to read stdin")

    subparsers.add_parser("validate-contracts")

    key = subparsers.add_parser("idempotency-key")
    key.add_argument("--project-id", required=True)
    key.add_argument("--entity-id", required=True)
    key.add_argument("--command", required=True)
    key.add_argument("--command-mode", choices=("step", "loop"))
    key.add_argument("--revision", type=int, required=True)
    key.add_argument("--operation-id")
    key.add_argument("--payload-hash")
    return parser
