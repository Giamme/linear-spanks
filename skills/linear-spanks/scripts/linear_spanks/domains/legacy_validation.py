"""Cross-contract validation retained for frozen v1 characterization."""

from __future__ import annotations

from typing import Any

from ..contracts.legacy import (
    command_transitions,
    execution_contract,
    human_verification_contract,
    issue_workflow_contract,
    load_json,
    milestone_review_contract,
    milestone_runtime_contract,
)
from ..core.legacy_constants import COMMANDS_PATH, WORKFLOW_PATH
from .execution import execution_envelope


def validate_contracts() -> dict[str, Any]:
    commands = load_json(COMMANDS_PATH).get("commands")
    workflow = load_json(WORKFLOW_PATH)
    if not isinstance(commands, list):
        raise ValueError("commands.json must contain a commands array")
    transitions = workflow.get("transitions")
    if not isinstance(transitions, dict):
        raise ValueError("workflow contract requires transitions")
    issue_contract = issue_workflow_contract()
    human_verification_contract()
    milestone_review_contract()
    milestone_runtime_contract()
    issue_transitions = issue_contract["transitions"]
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
        for transition in command_transitions(command):
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
    execution_contract()
    for name in names:
        execution_envelope(name)
    return {"commands": len(names), "status": "valid"}
