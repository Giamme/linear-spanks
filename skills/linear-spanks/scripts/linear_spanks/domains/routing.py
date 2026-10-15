"""Model routing and orchestration decision domain."""

from __future__ import annotations

from typing import Any

from . import _routing_v1 as legacy
from ._validation import checked


def recommend(payload: dict[str, Any]) -> dict[str, Any]:
    return checked(legacy.tier_recommendation, payload)


def check(
    harness: str,
    role: str,
    strength: str,
    configured_model: str | None = None,
    assurance: str = "strict",
) -> dict[str, Any]:
    return checked(
        legacy.routing_check,
        harness,
        role,
        strength,
        configured_model,
        assurance,
    )


def decide(payload: dict[str, Any]) -> dict[str, Any]:
    return checked(legacy.orchestration_decision, payload)


def task_policy(payload: dict[str, Any]) -> dict[str, Any]:
    return checked(legacy.task_execution_policy, payload)
