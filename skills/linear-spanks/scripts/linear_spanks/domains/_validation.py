"""Translate versioned domain validation failures into structured v2 usage errors."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import ParamSpec, TypeVar

from ..core.errors import GovernedStop, UsageError

P = ParamSpec("P")
R = TypeVar("R")


def checked(function: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R:
    try:
        return function(*args, **kwargs)
    except (ValueError, KeyError, TypeError) as error:
        message = str(error)
        match = re.match(r"^([A-Z][A-Z_]+)(?=[: ]|$)", message)
        if match:
            code = match.group(1)
            action = (
                "Partition context or preview compaction; request an explicit budget increase if necessary"
                if "OVERFLOW" in code
                else "Refresh affected source bindings and recompile; obtain fresh approval if bound scope changed"
                if "DRIFT" in code
                else "Obtain approval for the exact preview before mutation"
                if "APPROVAL" in code or "SELECTION_REQUIRED" in code
                else "Recover the unavailable prerequisite or use an authorized capable role"
                if "CAPABILITY" in code
                else "Diagnose the affected evidence and follow the command recovery contract"
            )
            raise GovernedStop(
                code, message, details={"evidence": message, "next_action": action}
            ) from error
        raise UsageError("PAYLOAD_VALIDATION_FAILED", message) from error
