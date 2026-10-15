"""Typed runtime for Linear Spanks v2."""

from .core.errors import ExitCode, LinearSpanksError
from .core.types import (
    ArtifactCodec,
    CliResult,
    CommandSpec,
    ContractSet,
    ExecutionEnvelope,
)

__all__ = [
    "ArtifactCodec",
    "CliResult",
    "CommandSpec",
    "ContractSet",
    "ExecutionEnvelope",
    "ExitCode",
    "LinearSpanksError",
]

__version__ = "1.0.0"
