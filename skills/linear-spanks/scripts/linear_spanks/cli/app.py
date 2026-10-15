"""Application boundary for the breaking, namespaced Linear Spanks v2 CLI."""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from typing import Any, TextIO

from ..core.errors import ExitCode, LinearSpanksError, UsageError
from ..core.types import CliResult
from ..domains.commands import compile_command, contracts
from .internal import INTERNAL_OPERATIONS, run_internal
from .render import render_json, render_text

PUBLIC_NAMESPACE_ORDER = (
    "codebase",
    "project",
    "milestone",
    "task",
    "wave",
    "verification",
    "learning",
    "context",
    "runtime",
)
INTERNAL_NAMESPACES = {
    "contracts",
    "state",
    "routing",
    "context",
    "reviews",
    "runtime",
    "graphs",
    "isolation",
    "orchestration",
    "artifacts",
    "docs",
    "installation",
    "extensions",
}


def _extract_format(arguments: Sequence[str]) -> tuple[str, tuple[str, ...]]:
    output: list[str] = []
    selected: str | None = None
    index = 0
    while index < len(arguments):
        value = arguments[index]
        if value == "--format":
            if selected is not None:
                raise UsageError("DUPLICATE_OPTION", "--format may be supplied only once")
            if index + 1 >= len(arguments):
                raise UsageError("MISSING_OPTION_VALUE", "--format requires json or text")
            selected = arguments[index + 1]
            index += 2
            continue
        if value.startswith("--format="):
            if selected is not None:
                raise UsageError("DUPLICATE_OPTION", "--format may be supplied only once")
            selected = value.split("=", 1)[1]
            index += 1
            continue
        output.append(value)
        index += 1
    chosen = selected or "json"
    if chosen not in {"json", "text"}:
        raise UsageError("INVALID_FORMAT", "--format must be json or text")
    return chosen, tuple(output)


def _help(advanced: bool, internal: bool) -> dict[str, Any]:
    contract_set = contracts()
    namespaces: dict[str, list[str]] = {}
    for namespace in PUBLIC_NAMESPACE_ORDER:
        names = [
            command.name
            for command in contract_set.commands
            if command.namespace == namespace and (advanced or command.tier == "core")
        ]
        if names:
            namespaces[namespace] = names
    payload: dict[str, Any] = {
        "version": "2.0.0",
        "default_format": "json",
        "namespaces": namespaces,
        "advanced_included": advanced,
        "hint": "help --advanced",
    }
    if internal:
        payload["internal"] = {
            **{name: sorted(operations) for name, operations in INTERNAL_OPERATIONS.items()},
            "contracts": ["brief", "command", "envelope", "runtime-card", "validate"],
            "artifacts": ["inspect", "preview", "migrate"],
            "docs": ["check", "generate", "links"],
            "installation": ["clients", "model-routing", "skills"],
            "extensions": ["caveman", "ripwire"],
        }
    return payload


def _public_result(path: str, arguments: tuple[str, ...]) -> dict[str, Any]:
    command = contracts().by_path.get(path)
    if command is None:
        raise UsageError("COMMAND_NOT_FOUND", f"Unknown v2 command: {path}")
    compiled = compile_command(path, arguments)
    resolved = compiled.contract.get("command")
    if not isinstance(resolved, Mapping):
        raise UsageError("INVALID_CONTRACT_SET", "Compiled command metadata is missing")
    return {
        "path": resolved.get("path"),
        "tier": resolved.get("tier"),
        "access": resolved.get("access"),
        "approval": resolved.get("approval"),
        "profiles": resolved.get("profiles"),
        "template": resolved.get("template"),
        "transitions": resolved.get("transitions"),
        "execution": dict(compiled.contract),
    }


def _dispatch(arguments: tuple[str, ...], stdin: TextIO) -> tuple[str, Any]:
    if not arguments or arguments[0] in {"help", "-h", "--help"}:
        advanced = "--advanced" in arguments
        internal = "--internal" in arguments
        unknown = set(arguments[1:] if arguments else ()) - {"--advanced", "--internal"}
        if unknown:
            raise UsageError(
                "INVALID_ARGUMENTS", f"Unknown help options: {', '.join(sorted(unknown))}"
            )
        return "help", _help(advanced, internal)

    contract_set = contracts()
    first = arguments[0]
    replacement = contract_set.contract("command_registry").get("legacy_replacements", {})
    if isinstance(replacement, Mapping) and first in replacement:
        exact = (
            "milestone run --mode loop"
            if first == "run-milestone" and "--autopilot" in arguments[1:]
            else replacement[first]
        )
        raise UsageError(
            "LEGACY_COMMAND_REMOVED",
            f"The v1 command '{first}' was removed; use '{exact}'",
            details={"legacy_command": first, "replacement": exact},
        )

    if first in PUBLIC_NAMESPACE_ORDER:
        if len(arguments) < 2:
            available = [
                command.name for command in contract_set.commands if command.namespace == first
            ]
            raise UsageError(
                "COMMAND_REQUIRED",
                f"Choose a {first} command",
                details={"commands": available},
            )
        path = f"{first} {arguments[1]}"
        if path in contract_set.by_path:
            return path, _public_result(path, tuple(arguments[2:]))
        internal_operations = INTERNAL_OPERATIONS.get(first)
        if internal_operations is not None and arguments[1] in internal_operations:
            return path, run_internal(
                first,
                arguments[1],
                tuple(arguments[2:]),
                stdin,
            )
        return path, _public_result(path, tuple(arguments[2:]))

    if first in INTERNAL_NAMESPACES:
        if len(arguments) < 2:
            raise UsageError("OPERATION_REQUIRED", f"Choose a {first} operation")
        command = f"{first} {arguments[1]}"
        return command, run_internal(first, arguments[1], tuple(arguments[2:]), stdin)

    raise UsageError("NAMESPACE_NOT_FOUND", f"Unknown namespace or command: {first}")


def _attempted_command(arguments: tuple[str, ...]) -> str:
    if not arguments or arguments[0] in {"help", "-h", "--help"}:
        return "help"
    if arguments[0] in {*PUBLIC_NAMESPACE_ORDER, *INTERNAL_NAMESPACES} and len(arguments) >= 2:
        return f"{arguments[0]} {arguments[1]}"
    return arguments[0]


def run(
    argv: Sequence[str],
    *,
    stdin: TextIO,
    stdout: TextIO,
) -> int:
    command = "cli"
    output_format = "json"
    try:
        output_format, arguments = _extract_format(argv)
        command = _attempted_command(arguments)
        command, payload = _dispatch(arguments, stdin)
        result = CliResult(command=command, ok=True, result=payload)
        exit_code = ExitCode.SUCCESS
    except LinearSpanksError as error:
        result = CliResult(command=command, ok=False, error=error.as_dict())
        exit_code = error.exit_code
    except (KeyboardInterrupt, BrokenPipeError):
        return int(ExitCode.INTERNAL)
    except Exception as error:  # pragma: no cover - last-resort stable boundary
        result = CliResult(
            command=command,
            ok=False,
            error={"code": "INTERNAL_ERROR", "message": str(error) or type(error).__name__},
        )
        exit_code = ExitCode.INTERNAL
    try:
        rendered = render_text(result) if output_format == "text" else render_json(result)
    except (KeyboardInterrupt, BrokenPipeError):
        return int(ExitCode.INTERNAL)
    except Exception as error:  # pragma: no cover - defensive renderer boundary
        result = CliResult(
            command=command,
            ok=False,
            error={"code": "INTERNAL_ERROR", "message": str(error) or type(error).__name__},
        )
        exit_code = ExitCode.INTERNAL
        try:
            rendered = render_json(result)
        except Exception:
            return int(ExitCode.INTERNAL)
    try:
        stdout.write(rendered)
        stdout.flush()
    except KeyboardInterrupt:
        return int(ExitCode.INTERNAL)
    except Exception:
        return int(ExitCode.INTERNAL)
    return int(exit_code)


def main(argv: Sequence[str] | None = None) -> int:
    return run(sys.argv[1:] if argv is None else argv, stdin=sys.stdin, stdout=sys.stdout)
