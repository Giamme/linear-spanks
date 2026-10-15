"""Small fail-closed validation helpers."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .errors import UsageError

SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def require_object(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise UsageError("INVALID_PAYLOAD", f"{field} must be an object")
    return value


def require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UsageError("INVALID_PAYLOAD", f"{field} must be non-empty text")
    return value


def require_positive_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise UsageError("INVALID_PAYLOAD", f"{field} must be a positive integer")
    return value


def require_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise UsageError("INVALID_PAYLOAD", f"{field} must be a sha256 digest")
    return value
