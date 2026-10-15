"""Stable JSON and compact human-readable CLI rendering."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..core.jsonio import dump_json
from ..core.types import CliResult


def render_json(result: CliResult) -> str:
    return dump_json(result.as_dict())


def _render_help(payload: Mapping[str, Any]) -> str:
    lines = ["Linear Spanks 1.0.0", "", "Core pipeline:"]
    namespaces = payload.get("namespaces")
    if isinstance(namespaces, dict):
        for namespace, commands in namespaces.items():
            if isinstance(commands, list) and commands:
                lines.append(f"  {namespace}: {', '.join(str(item) for item in commands)}")
    if payload.get("advanced_included") is not True:
        lines.extend(("", "Use `help --advanced` for the complete public surface."))
    return "\n".join(lines) + "\n"


def render_text(result: CliResult) -> str:
    if not result.ok:
        error = result.error or {}
        code = error.get("code", "UNKNOWN_ERROR")
        message = error.get("message", "Command failed")
        details = error.get("details")
        output = f"ERROR {code}: {message}"
        if isinstance(details, dict) and details:
            output += "\n" + dump_json(details, pretty=True).rstrip("\n")
        return output + "\n"
    if result.command == "help" and isinstance(result.result, dict):
        return _render_help(result.result)
    if isinstance(result.result, str):
        return result.result.rstrip("\n") + "\n"
    return dump_json(result.result, pretty=True)
