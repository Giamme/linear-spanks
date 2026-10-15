"""Explicit UTF-8 JSON and atomic filesystem adapters."""

from __future__ import annotations

import json
import math
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .errors import FilesystemError, UsageError


class StrictJsonError(ValueError):
    """Strict JSON interoperability requirement was violated."""


class NonFiniteJsonValue(StrictJsonError):
    """A non-standard or overflowing numeric value was found in JSON."""


class DuplicateJsonKey(StrictJsonError):
    """A JSON object declared the same key more than once."""


class InvalidJsonText(StrictJsonError):
    """A JSON string contains text that cannot be encoded as UTF-8."""


class UnsupportedJsonValue(StrictJsonError):
    """A value is outside the interoperable JSON data model."""


def _validate_text(value: str) -> None:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise InvalidJsonText("unpaired surrogate code point is not valid UTF-8 JSON") from error


def validate_strict_json_value(value: Any) -> None:
    """Validate a complete value against the finite, UTF-8 JSON data model."""

    if value is None or isinstance(value, bool | int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise NonFiniteJsonValue("non-finite number is not valid JSON")
        return
    if isinstance(value, str):
        _validate_text(value)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise UnsupportedJsonValue("JSON object keys must be strings")
            _validate_text(key)
            validate_strict_json_value(item)
        return
    if isinstance(value, list | tuple):
        for item in value:
            validate_strict_json_value(item)
        return
    raise UnsupportedJsonValue(f"unsupported JSON value type: {type(value).__name__}")


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze_json(item) for item in value)
    return value


def freeze_json(value: Any) -> Any:
    """Return a defensive, recursively immutable copy of strict JSON data."""

    try:
        validate_strict_json_value(value)
        return _freeze_json(value)
    except (StrictJsonError, RecursionError) as error:
        raise UsageError(
            "INVALID_JSON_VALUE",
            f"Value cannot be frozen as strict JSON: {error}",
        ) from error


def mutable_json_copy(value: Any) -> Any:
    """Return an isolated mutable JSON-compatible copy of frozen data."""

    if isinstance(value, Mapping):
        return {str(key): mutable_json_copy(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [mutable_json_copy(item) for item in value]
    return value


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise FilesystemError(
            "FILE_READ_FAILED",
            f"Unable to read {path}: {error}",
            details={"path": str(path)},
        ) from error


def load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = strict_json_loads(read_text(path))
    except (json.JSONDecodeError, StrictJsonError) as error:
        message = error.msg if isinstance(error, json.JSONDecodeError) else str(error)
        raise UsageError(
            "INVALID_JSON",
            f"{path} is not valid JSON: {message}",
            details={
                "path": str(path),
                "line": error.lineno if isinstance(error, json.JSONDecodeError) else None,
                "column": error.colno if isinstance(error, json.JSONDecodeError) else None,
            },
        ) from error
    if not isinstance(value, dict):
        raise UsageError(
            "INVALID_JSON_OBJECT",
            f"{path} must contain a JSON object",
            details={"path": str(path)},
        )
    return value


def dump_json(value: Any, *, pretty: bool = False) -> str:
    try:
        validate_strict_json_value(value)
        serializable = mutable_json_copy(value)
        if pretty:
            return (
                json.dumps(
                    serializable,
                    indent=2,
                    sort_keys=True,
                    ensure_ascii=False,
                    allow_nan=False,
                )
                + "\n"
            )
        return (
            json.dumps(
                serializable,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        )
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise UsageError(
            "INVALID_JSON_VALUE",
            f"Value cannot be represented as strict JSON: {error}",
        ) from error


def _reject_non_finite(value: str) -> None:
    raise NonFiniteJsonValue(f"non-finite number {value} is not valid JSON")


def _parse_finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise NonFiniteJsonValue(f"number {value} exceeds the finite JSON range")
    return parsed


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJsonKey(f"duplicate object key {key!r} is not valid strict JSON")
        result[key] = value
    return result


def strict_json_loads(text: str) -> Any:
    """Parse finite UTF-8 JSON with unique keys and bounded Python primitives."""

    try:
        value = json.loads(
            text,
            parse_constant=_reject_non_finite,
            parse_float=_parse_finite_float,
            object_pairs_hook=_reject_duplicate_keys,
        )
        validate_strict_json_value(value)
    except (json.JSONDecodeError, StrictJsonError):
        raise
    except (ValueError, UnicodeError, RecursionError) as error:
        raise StrictJsonError(f"JSON parser rejected the input: {error}") from error
    return value


def atomic_write_text(path: Path, content: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    except (OSError, UnicodeError) as error:
        raise FilesystemError(
            "FILE_WRITE_FAILED",
            f"Unable to write {path}: {error}",
            details={"path": str(path)},
        ) from error


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, dump_json(value, pretty=True))
