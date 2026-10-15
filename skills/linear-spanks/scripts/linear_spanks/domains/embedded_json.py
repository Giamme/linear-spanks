"""Strict JSON decoding for durable JSON embedded inside text markers."""

from __future__ import annotations

import json
from typing import Any, cast

from ..core.jsonio import StrictJsonError, strict_json_loads


def parse_embedded_object(encoded: str, label: str) -> dict[str, Any]:
    try:
        value = strict_json_loads(encoded)
    except (json.JSONDecodeError, StrictJsonError) as error:
        message = error.msg if isinstance(error, json.JSONDecodeError) else str(error)
        raise ValueError(f"{label} payload is not strict JSON: {message}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} payload must be an object")
    return cast(dict[str, Any], value)
