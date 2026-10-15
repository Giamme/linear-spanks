"""Fail-closed structural validators shared by orchestration domains."""

from __future__ import annotations

import re
from typing import Any


def _require_exact_object_fields(
    payload: Any, required_fields: list[str], field: str
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError(f"{field} must be an object")
    missing = sorted(set(required_fields) - set(payload))
    extra = sorted(set(payload) - set(required_fields))
    if missing or extra:
        raise ValueError(f"{field} field mismatch; missing={missing}, extra={extra}")
    return payload


def _require_nonempty_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    return value


def _require_positive_revision(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _require_commit(value: Any, field: str, allow_none: bool = False) -> str | None:
    if allow_none and value is None:
        return None
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40,64}", value) is None:
        raise ValueError(f"{field} must be a 40 to 64 character lowercase commit hash")
    return value
