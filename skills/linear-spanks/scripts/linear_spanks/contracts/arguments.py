"""Strict argument grammar and canonical invocation binding for public commands."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from ..core.errors import UsageError
from ..core.types import CommandSpec

OPTION_RE = re.compile(r"--[a-z][a-z0-9-]*")
COMMON_OPTIONS = {
    "--project",
    "--project-id",
    "--team",
    "--strict-project",
    "--include-cross-project-blockers",
    "--assurance",
    "--ripwire",
}
LOOP_OPTIONS = {"--max-parallel", "--resume", "--until", "--max-events", "--repair-safe"}
BOOLEAN_OPTIONS = {
    "--reset",
    "--strict-project",
    "--include-cross-project-blockers",
    "--isolated-worktree",
    "--next-wave",
    "--repair-safe",
    "--incremental",
    "--delete-merged-branches",
}
REPEATABLE_OPTIONS = {"--finding"}
LOOP_STOP_CONDITIONS = ("approval-required", "blocked", "milestone-done")
REQUIRED_OPTIONS: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "milestone report-findings": frozenset({"--session-id", "--finding"}),
        "project rollover": frozenset({"--next-release"}),
        "verification fail": frozenset({"--reason"}),
        "wave reconcile": frozenset({"--wave"}),
    }
)


@dataclass(frozen=True, slots=True)
class ParsedPublicArguments:
    positionals: tuple[str, ...]
    options: Mapping[str, tuple[str | None, ...]]

    def value(self, name: str) -> str | None:
        values = self.options.get(name, ())
        if not values:
            return None
        return values[-1]

    def as_dict(self) -> dict[str, Any]:
        options: dict[str, Any] = {}
        for name, values in sorted(self.options.items()):
            public_name = name.removeprefix("--").replace("-", "_")
            normalized = [True if value is None else value for value in values]
            options[public_name] = normalized if name in REPEATABLE_OPTIONS else normalized[0]
        return {
            "target": self.positionals[0],
            "positionals": list(self.positionals),
            "options": options,
        }


def _allowed_options(command: CommandSpec) -> set[str]:
    allowed = set(OPTION_RE.findall(command.usage)) | COMMON_OPTIONS
    if command.path == "milestone run":
        allowed |= LOOP_OPTIONS
    return allowed


def _normalize_known_value(name: str, value: str) -> str:
    choices = {
        "--ripwire": {"on", "off", "inherit"},
        "--assurance": {"fast", "balanced", "strict"},
        "--scan": {"fast", "medium", "heavy"},
        "--mode": {"step", "loop"},
        "--level": {"compact", "prune"},
        "--default": {"enabled", "disabled"},
        "--override": {"enabled", "disabled", "inherit"},
    }
    if name in choices and value not in choices[name]:
        code = "INVALID_MODE" if name == "--mode" else "INVALID_OPTION_VALUE"
        raise UsageError(
            code,
            f"{name} must be one of: {', '.join(sorted(choices[name]))}",
            details={"option": name, "value": value},
        )
    if name == "--max-parallel":
        try:
            parallelism = int(value)
        except ValueError as error:
            raise UsageError("INVALID_OPTION_VALUE", "--max-parallel must be an integer") from error
        if parallelism < 2 or parallelism > 8:
            raise UsageError("INVALID_OPTION_VALUE", "--max-parallel must be between 2 and 8")
    if name == "--max-events":
        try:
            events = int(value)
        except ValueError as error:
            raise UsageError("INVALID_OPTION_VALUE", "--max-events must be an integer") from error
        if events <= 0 or events > 100:
            raise UsageError("INVALID_OPTION_VALUE", "--max-events must be between 1 and 100")
    if name == "--until":
        conditions = value.split(",")
        unknown = sorted(set(conditions) - set(LOOP_STOP_CONDITIONS))
        if any(not condition for condition in conditions) or unknown:
            raise UsageError(
                "INVALID_OPTION_VALUE",
                "--until must be a comma-separated subset of: " + ", ".join(LOOP_STOP_CONDITIONS),
                details={"option": name, "value": value, "unknown": unknown},
            )
        if len(conditions) != len(set(conditions)):
            raise UsageError(
                "INVALID_OPTION_VALUE",
                "--until stop conditions may not be duplicated",
                details={"option": name, "value": value},
            )
        return ",".join(condition for condition in LOOP_STOP_CONDITIONS if condition in conditions)
    return value


def parse_public_arguments(
    command: CommandSpec, arguments: tuple[str, ...]
) -> ParsedPublicArguments:
    allowed = _allowed_options(command)
    positionals: list[str] = []
    parsed: dict[str, list[str | None]] = {}
    index = 0
    while index < len(arguments):
        token = arguments[index]
        if not token.startswith("--"):
            if not token or token != token.strip():
                raise UsageError(
                    "INVALID_POSITIONAL_VALUE",
                    f"Positional values for {command.path} must be non-empty and trimmed",
                )
            positionals.append(token)
            index += 1
            continue
        name, separator, inline_value = token.partition("=")
        if name not in allowed:
            raise UsageError(
                "UNKNOWN_OPTION",
                f"Unknown option for {command.path}: {name}",
                details={"option": name, "usage": command.usage},
            )
        if name in parsed and name not in REPEATABLE_OPTIONS:
            raise UsageError("DUPLICATE_OPTION", f"{name} may be provided only once")
        if name in BOOLEAN_OPTIONS:
            if separator:
                raise UsageError("UNEXPECTED_OPTION_VALUE", f"{name} does not accept a value")
            value: str | None = None
        else:
            if separator:
                value = inline_value
            else:
                index += 1
                if index >= len(arguments) or arguments[index].startswith("--"):
                    raise UsageError("MISSING_OPTION_VALUE", f"{name} requires a value")
                value = arguments[index]
            if not value:
                raise UsageError("MISSING_OPTION_VALUE", f"{name} requires a value")
            if value != value.strip():
                raise UsageError(
                    "INVALID_OPTION_VALUE",
                    f"{name} requires a non-empty trimmed value",
                    details={"option": name},
                )
            value = _normalize_known_value(name, value)
        parsed.setdefault(name, []).append(value)
        index += 1

    if not positionals:
        raise UsageError(
            "MISSING_TARGET",
            f"{command.path} requires a target",
            details={"usage": command.usage},
        )
    missing = sorted(REQUIRED_OPTIONS.get(command.path, frozenset()) - parsed.keys())
    if missing:
        raise UsageError(
            "MISSING_REQUIRED_OPTION",
            f"{command.path} requires {', '.join(missing)}",
            details={"options": missing, "usage": command.usage},
        )
    if command.path == "verification policy-set":
        policy_options = {"--default", "--override"} & parsed.keys()
        if len(policy_options) != 1:
            raise UsageError(
                "INVALID_POLICY_SELECTION",
                "verification policy-set requires exactly one of --default or --override",
            )
    if command.path in {"context budget", "context inspect", "runtime inspect"} and (
        len(positionals) != 2 or positionals[0] not in {"project", "milestone", "task"}
    ):
        raise UsageError("INVALID_CONTEXT_SCOPE", "Expected <project|milestone|task> <target>")
    if command.path == "context budget":
        if len({"--tokens", "--reset"} & parsed.keys()) != 1:
            raise UsageError("INVALID_CONTEXT_VALUE", "Specify exactly one of --tokens or --reset")
        if "--tokens" in parsed:
            raw = parsed["--tokens"][0]
            if raw is None or not raw.isascii() or not raw.isdecimal() or int(raw) <= 0:
                raise UsageError("INVALID_CONTEXT_VALUE", "--tokens must be a positive integer")
    frozen_options = MappingProxyType({name: tuple(values) for name, values in parsed.items()})
    return ParsedPublicArguments(tuple(positionals), frozen_options)
