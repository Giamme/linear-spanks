"""Public command discovery and execution-envelope compilation."""

from __future__ import annotations

from typing import Any

from ..contracts import compile_public_command, get_contract_set, validate_contract_set
from ..core.errors import UsageError
from ..core.types import CommandSpec, ContractSet, ExecutionEnvelope


def contracts() -> ContractSet:
    return get_contract_set()


def validate() -> dict[str, Any]:
    return validate_contract_set()


def command(path: str, contract_set: ContractSet | None = None) -> CommandSpec:
    selected = contract_set or get_contract_set()
    result = selected.by_path.get(path)
    if result is None:
        raise UsageError("COMMAND_NOT_FOUND", f"Unknown v2 command: {path}")
    return result


def compile_command(
    path: str,
    arguments: tuple[str, ...] = (),
    *,
    assurance: str | None = None,
    contract_set: ContractSet | None = None,
) -> ExecutionEnvelope:
    return compile_public_command(path, arguments, assurance=assurance, contract_set=contract_set)
