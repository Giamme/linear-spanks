"""Structured errors and stable process exit codes."""

from __future__ import annotations

from collections.abc import Mapping
from enum import IntEnum
from typing import Any


class ExitCode(IntEnum):
    """Stable v2 process outcomes."""

    SUCCESS = 0
    INTERNAL = 1
    USAGE = 2
    GOVERNED_STOP = 3
    FILESYSTEM = 4


class LinearSpanksError(Exception):
    """An expected failure safe to expose through the CLI envelope."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        exit_code: ExitCode = ExitCode.USAGE,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code
        self.details = dict(details or {})

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


class UsageError(LinearSpanksError):
    def __init__(
        self, code: str, message: str, *, details: Mapping[str, Any] | None = None
    ) -> None:
        super().__init__(code, message, exit_code=ExitCode.USAGE, details=details)


class GovernedStop(LinearSpanksError):
    def __init__(
        self, code: str, message: str, *, details: Mapping[str, Any] | None = None
    ) -> None:
        super().__init__(code, message, exit_code=ExitCode.GOVERNED_STOP, details=details)


class FilesystemError(LinearSpanksError):
    def __init__(
        self, code: str, message: str, *, details: Mapping[str, Any] | None = None
    ) -> None:
        super().__init__(code, message, exit_code=ExitCode.FILESYSTEM, details=details)
