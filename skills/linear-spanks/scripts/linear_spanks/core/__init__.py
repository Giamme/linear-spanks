"""Dependency-free primitives shared by all Linear Spanks domains."""

from .errors import ExitCode, LinearSpanksError
from .types import CliResult, CommandSpec, ContractSet, ExecutionEnvelope

__all__ = [
    "CliResult",
    "CommandSpec",
    "ContractSet",
    "ExecutionEnvelope",
    "ExitCode",
    "LinearSpanksError",
]
