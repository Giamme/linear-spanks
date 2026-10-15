"""Isolated-worktree preflight, receipt, and transition domain."""

from __future__ import annotations

from typing import Any

from . import _isolation_v1 as legacy
from ._validation import checked


def preflight(payload: dict[str, Any]) -> dict[str, Any]:
    return checked(legacy.validate_isolation_preflight, payload)


def validate_receipt(payload: dict[str, Any]) -> dict[str, Any]:
    return checked(legacy.validate_isolation_receipt, payload)


def transition(receipt: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    return checked(legacy.transition_isolation_receipt, receipt, request)
