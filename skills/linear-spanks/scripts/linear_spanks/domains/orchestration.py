"""Project/milestone orchestration receipts, roles, and verification ledgers."""

from __future__ import annotations

from typing import Any

from . import _orchestration_v1 as legacy
from ._validation import checked


def project_next(payload: dict[str, Any]) -> dict[str, Any]:
    return checked(legacy.select_project_loop_event, payload)


def milestone_next(payload: dict[str, Any]) -> dict[str, Any]:
    return checked(legacy.select_milestone_loop_event, payload)


def validate_project_receipt(payload: dict[str, Any]) -> dict[str, Any]:
    return checked(legacy.validate_project_loop_receipt, payload)


def validate_milestone_receipt(payload: dict[str, Any]) -> dict[str, Any]:
    return checked(legacy.validate_milestone_loop_receipt, payload)


def project_transition(receipt: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    return checked(legacy.transition_project_loop_receipt, receipt, request)


def milestone_transition(receipt: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    return checked(legacy.transition_milestone_loop_receipt, receipt, request)


def validate_scope(payload: dict[str, Any]) -> dict[str, Any]:
    return checked(legacy.check_orchestration_scope, payload)


def validate_handoff(
    payload: dict[str, Any],
    receipt: dict[str, Any] | None = None,
    orchestration: str = "project",
) -> dict[str, Any]:
    return checked(legacy.validate_role_handoff, payload, receipt, orchestration)


def validate_capability(payload: dict[str, Any], orchestration: str = "project") -> dict[str, Any]:
    return checked(legacy.validate_role_capability, payload, orchestration)


def validate_attempt(payload: dict[str, Any]) -> dict[str, Any]:
    return checked(legacy.validate_task_attempt, payload)


def validate_escalation(payload: dict[str, Any]) -> dict[str, Any]:
    return checked(legacy.validate_model_escalation, payload)


def validate_ledger(payload: dict[str, Any], **expected: Any) -> dict[str, Any]:
    return checked(legacy.validate_verification_ledger, payload, **expected)
