"""Indexed v1 policy views used by the versioned domain implementations.

The v2 ``ContractSet`` performs integrity, schema-version, cross-reference, and
exhaustive characterized safety-policy validation once at its load boundary.
These accessors intentionally avoid repeating those literal semantic checks on
every domain call.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from ..core.legacy_constants import (
    COMMANDS_PATH,
    EXECUTION_PATH,
    HUMAN_VERIFICATION_PATH,
    ISSUE_WORKFLOW_PATH,
    MILESTONE_ORCHESTRATION_PATH,
    MILESTONE_REVIEW_PATH,
    MILESTONE_RUNTIME_PATH,
    PARALLEL_EXECUTION_PATH,
    PROJECT_EPOCH_PATH,
    PROJECT_ORCHESTRATION_PATH,
    REPOSITORY_SCAN_PATH,
    ROUTING_PATH,
    SKILL_ROOT,
    WORKFLOW_PATH,
)

_CONTRACT_NAMES = {
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


def load_json(path: Path) -> dict[str, Any]:
    contract_name = _CONTRACT_NAMES.get(path)
    if contract_name is not None:
        # Lazy imports avoid a package-startup cycle while retaining one cached
        # immutable ContractSet as the source of every policy view.
        from ..contracts.registry import get_contract_set
        from ..core.jsonio import mutable_json_copy

        value = mutable_json_copy(get_contract_set().contract(contract_name))
    else:
        value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def _contract(path: Path) -> dict[str, Any]:
    contract = load_json(path)
    version = contract.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool) or version <= 0:
        raise ValueError(f"{path.name} requires a positive schema_version")
    return contract


def command_by_name(name: str) -> dict[str, Any]:
    commands = load_json(COMMANDS_PATH).get("commands", [])
    if not isinstance(commands, list):
        raise ValueError("commands.json requires a command array")
    matches = [
        command for command in commands if isinstance(command, dict) and command.get("name") == name
    ]
    if len(matches) != 1:
        raise ValueError(f"unknown or duplicated command: {name}")
    return cast(dict[str, Any], matches[0])


def parse_rfc3339(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("updated_at must be RFC 3339 text")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise ValueError("updated_at must be RFC 3339 text") from error
    if parsed.tzinfo is None:
        raise ValueError("updated_at must be RFC 3339 text with a timezone")
    return parsed


def command_transitions(command: dict[str, Any]) -> set[str]:
    declared = command.get("transitions")
    if declared is not None:
        if (
            not isinstance(declared, list)
            or not declared
            or not all(isinstance(item, str) and item for item in declared)
        ):
            raise ValueError(f"command {command['name']} has invalid transitions")
        return set(declared)
    transition = command.get("transition")
    return {transition} if isinstance(transition, str) and transition else set()


def issue_workflow_contract() -> dict[str, Any]:
    return _contract(ISSUE_WORKFLOW_PATH)


def human_verification_contract() -> dict[str, Any]:
    return _contract(HUMAN_VERIFICATION_PATH)


def milestone_review_contract() -> dict[str, Any]:
    return _contract(MILESTONE_REVIEW_PATH)


def milestone_runtime_contract() -> dict[str, Any]:
    return _contract(MILESTONE_RUNTIME_PATH)


def routing_contract() -> dict[str, Any]:
    return _contract(ROUTING_PATH)


def repository_scan_contract() -> dict[str, Any]:
    return _contract(REPOSITORY_SCAN_PATH)


def project_epoch_contract() -> dict[str, Any]:
    return _contract(PROJECT_EPOCH_PATH)


def parallel_execution_contract() -> dict[str, Any]:
    return _contract(PARALLEL_EXECUTION_PATH)


def project_orchestration_contract() -> dict[str, Any]:
    return _contract(PROJECT_ORCHESTRATION_PATH)


def milestone_orchestration_contract() -> dict[str, Any]:
    contract = _contract(MILESTONE_ORCHESTRATION_PATH)
    project = project_orchestration_contract()
    topology = contract.get("topology")
    if not isinstance(topology, dict):
        raise ValueError("milestone orchestration requires topology")
    roles = topology.get("roles")
    if (
        not isinstance(roles, list)
        or not roles
        or not all(isinstance(role, str) and role for role in roles)
    ):
        raise ValueError("milestone orchestration requires topology roles")

    effective = dict(contract)
    effective["roles"] = {role: project["roles"][role] for role in roles}
    effective["task_loop"] = project["task_loop"]
    effective["verification_ledger"] = project["verification_ledger"]
    effective["role_handoff"] = project["role_handoff"]
    effective["capabilities"] = {role: project["capabilities"][role] for role in roles}
    return effective


def execution_contract() -> dict[str, Any]:
    return _contract(EXECUTION_PATH)


def required_references(
    command: dict[str, Any], configuration: dict[str, Any] | None = None
) -> list[str]:
    if command["name"] == "help":
        references = ["references/command-catalog.md"]
    else:
        references = [
            "references/core-policy.md",
            f"references/{command['family']}-commands.md",
            "references/context-management.md",
        ]
        if command["name"] in {
            "plan-tasks",
            "plan-task",
            "run-task",
            "replan-task",
            "implement-next",
            "implement-wave",
            "reconcile-wave",
            "verify-task",
        }:
            references.append("references/skill-composition.md")
        if configuration and configuration.get("orchestration"):
            references.append("references/model-routing.md")
        if configuration and configuration.get("repository_scan"):
            references.append("references/codebase-analysis.md")
        if command["name"] in {"checkpoint-project", "rollover-project"}:
            references.append("references/project-epoch.md")
        if command["name"] == "run-project":
            references.extend(
                (
                    "references/project-orchestration.md",
                    "references/parallel-execution.md",
                    "templates/completion-handoff.md",
                    "templates/verification-ledger.md",
                    "templates/task-verification-result.md",
                )
            )
        if command["name"] == "run-milestone-loop":
            references.extend(
                (
                    "references/milestone-orchestration.md",
                    "references/parallel-execution.md",
                    "templates/completion-handoff.md",
                    "templates/verification-ledger.md",
                    "templates/task-verification-result.md",
                )
            )
        if command["name"] in {"implement-wave", "reconcile-wave"}:
            references.append("references/parallel-execution.md")
        if command["name"] in {
            "set-human-verification-policy",
            "status-human-verification",
            "run-project",
            "run-milestone",
            "run-milestone-loop",
            "verify-milestone",
            "confirm-milestone",
            "fail-milestone-verification",
            "report-milestone-findings",
            "wrap-milestone",
            "status-milestone",
            "handoff-milestone",
        }:
            references.append("references/human-verification.md")
        if command.get("transition"):
            references.append("references/workflow-state.md")
        if command.get("issue_transition") or command["name"] == "organize-unplanned":
            references.append("references/issue-intake.md")
        if command.get("template"):
            references.append(f"templates/{command['template']}")
    result = list(dict.fromkeys(references))
    for reference in result:
        if not (SKILL_ROOT / reference).is_file():
            raise ValueError(f"missing required reference for {command['name']}: {reference}")
    return result
