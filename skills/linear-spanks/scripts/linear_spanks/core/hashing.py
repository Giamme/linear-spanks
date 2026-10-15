"""Canonical hashing used for receipts, artifacts, and approvals."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .errors import UsageError
from .jsonio import mutable_json_copy, validate_strict_json_value


def canonical_json_bytes(value: Any) -> bytes:
    try:
        validate_strict_json_value(value)
        serializable = mutable_json_copy(value)
        encoded = json.dumps(
            serializable,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        return encoded.encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise UsageError(
            "INVALID_JSON_VALUE",
            f"Value cannot be canonically hashed as strict JSON: {error}",
        ) from error


def sha256_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()
