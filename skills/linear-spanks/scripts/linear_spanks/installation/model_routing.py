#!/usr/bin/env python3
"""Preview or apply user-owned model routing for supported agent harnesses."""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ..contracts.legacy import routing_contract as validated_routing_contract
from ..core.errors import ExitCode, FilesystemError, LinearSpanksError
from ..core.jsonio import StrictJsonError, read_text, strict_json_loads
from .clients import client_registry
from .snapshots import (
    ABSENT_PATH,
    matches_snapshot,
    publish_staged_exclusive,
    quarantine_expected,
    require_unchanged,
    snapshot_path,
    text_path_snapshot,
    vacate_expected,
    write_text_exclusive,
)

MANAGED_MARKER = "managed-by: linear-spanks model-routing v1"
PROFILE_CLIENTS = {"codex", "claude", "opencode"}
CLIENT_ORDER = ("codex", "openclaude", "claude", "antigravity", "kimi", "opencode")
PROFILE_SPECS = (
    ("planner", "planner", "high"),
    ("planner-medium", "planner", "medium"),
    ("executor-low", "executor", "low"),
    ("executor-medium", "executor", "medium"),
    ("executor-high", "executor", "high"),
    ("reviewer-medium", "reviewer", "medium"),
    ("reviewer-high", "reviewer", "high"),
)
ROLE_INSTRUCTIONS = {
    "planner": (
        "Run read-only. Inspect only the bounded repository evidence required by the routing "
        "contract. Return the structured plan packet and do not modify files or Linear. Return "
        "CONTEXT_OVERFLOW when required planning evidence cannot fit."
    ),
    "executor": (
        "Implement exactly one task from the authoritative current plan and worker handoff. Do "
        "not mutate Linear or downgrade the planner tier. Return REPLAN_REQUIRED on scope, "
        "interface, dependency, or evidence drift. Run the required verification and return a "
        "compact execution receipt."
    ),
    "reviewer": (
        "Review independently against the authoritative plan, acceptance criteria, diff, and "
        "verification evidence. Do not modify source files or Linear. Return a structured review "
        "result with blocking findings and the evidence inspected."
    ),
}


def load_routing_contract() -> dict[str, Any]:
    value = validated_routing_contract()
    harnesses = value.get("harnesses")
    if not isinstance(harnesses, dict):
        raise ValueError("routing-contract.json requires harnesses")
    for client in CLIENT_ORDER:
        if client not in harnesses:
            raise ValueError(f"routing-contract.json is missing harness {client}")
    return value


def expand_clients(selector: str) -> tuple[str, ...]:
    try:
        return client_registry().routing_clients(selector)
    except Exception as error:
        raise ValueError(f"invalid client: {selector}") from error


def validate_model_identifier(label: str, value: str) -> str:
    if not value or value != value.strip():
        raise ValueError(f"{label} model identifier must be non-empty and trimmed")
    if len(value) > 256 or any(character.isspace() or ord(character) < 32 for character in value):
        raise ValueError(
            f"{label} model identifier must not contain whitespace or control characters"
        )
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError(f"{label} model identifier must be valid UTF-8 text") from error
    return value


def default_destination(client: str) -> Path | None:
    registry = client_registry()
    for spec in registry.clients.values():
        if spec.routing_name == client:
            return spec.model_destination(os.environ)
    raise ValueError(f"invalid client: {client}")


def quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def profile_name(suffix: str) -> str:
    return f"linear-spanks-{suffix}"


def profile_description(role: str, strength: str) -> str:
    if role == "planner":
        return f"Read-only {strength}-strength planner for authoritative linear-spanks task plans."
    if role == "executor":
        return f"{strength.title()}-strength worker for one planned linear-spanks task."
    return f"Independent {strength}-strength reviewer for a planned linear-spanks task."


def render_codex_profile(suffix: str, role: str, strength: str, model: str) -> str:
    access = "workspace-write" if role == "executor" else "read-only"
    return "\n".join(
        (
            f"# {MANAGED_MARKER}",
            f"name = {quote(profile_name(suffix))}",
            f"description = {quote(profile_description(role, strength))}",
            f"developer_instructions = {quote(ROLE_INSTRUCTIONS[role])}",
            f"model = {quote(model)}",
            f"sandbox_mode = {quote(access)}",
            "",
        )
    )


def render_claude_profile(suffix: str, role: str, strength: str, model: str) -> str:
    tools = "Read, Edit, Write, Grep, Glob, Bash" if role == "executor" else "Read, Grep, Glob"
    permission_mode = "default" if role == "executor" else "plan"
    return "\n".join(
        (
            "---",
            f"name: {profile_name(suffix)}",
            f"description: {quote(profile_description(role, strength))}",
            f"tools: {tools}",
            f"model: {quote(model)}",
            f"permissionMode: {permission_mode}",
            "---",
            f"<!-- {MANAGED_MARKER} -->",
            ROLE_INSTRUCTIONS[role],
            "",
        )
    )


def render_opencode_profile(suffix: str, role: str, strength: str, model: str) -> str:
    edit_permission = "allow" if role == "executor" else "deny"
    bash_permission = "allow" if role == "executor" else "deny"
    return "\n".join(
        (
            "---",
            f"description: {quote(profile_description(role, strength))}",
            "mode: subagent",
            f"model: {quote(model)}",
            "permission:",
            f"  edit: {edit_permission}",
            f"  bash: {bash_permission}",
            "---",
            f"<!-- {MANAGED_MARKER} -->",
            ROLE_INSTRUCTIONS[role],
            "",
        )
    )


def render_profile(client: str, suffix: str, role: str, strength: str, model: str) -> str:
    if client == "codex":
        return render_codex_profile(suffix, role, strength, model)
    if client == "claude":
        return render_claude_profile(suffix, role, strength, model)
    if client == "opencode":
        return render_opencode_profile(suffix, role, strength, model)
    raise AssertionError(client)


def has_managed_profile_shape(existing: str, desired: str, marker: str) -> bool:
    """Require the ownership marker at its canonical managed-profile position."""

    lines = existing.splitlines()
    if marker.startswith("# "):
        return bool(lines) and lines[0] == marker

    desired_lines = desired.splitlines()
    marker_index = desired_lines.index(marker)
    if (
        len(lines) <= marker_index
        or lines[0] != "---"
        or lines[marker_index - 1] != "---"
        or lines[marker_index] != marker
    ):
        return False
    desired_keys = [line.partition(":")[0] for line in desired_lines[1 : marker_index - 1]]
    existing_keys = [line.partition(":")[0] for line in lines[1 : marker_index - 1]]
    if existing_keys != desired_keys:
        return False
    desired_name = next((line for line in desired_lines if line.startswith("name: ")), None)
    return desired_name is None or desired_name in lines[1 : marker_index - 1]


def operation_for_profile(path: Path, content: str) -> dict[str, Any]:
    expected = snapshot_path(path)
    if path.is_symlink():
        action = "conflict"
    elif not path.exists():
        action = "create"
    elif not path.is_file():
        action = "conflict"
    else:
        existing = read_text(path)
        marker = (
            f"# {MANAGED_MARKER}"
            if content.startswith(f"# {MANAGED_MARKER}\n")
            else f"<!-- {MANAGED_MARKER} -->"
        )
        has_exact_marker = has_managed_profile_shape(existing, content, marker)
        if existing == content:
            action = "unchanged"
        elif has_exact_marker:
            action = "update"
        else:
            action = "conflict"
    require_unchanged(path, expected)
    return {
        "path": str(path),
        "action": action,
        "managed": action != "conflict",
        "content": content,
        "_write_content": content,
        "_expected": expected,
    }


def profile_operations(
    client: str, destination: Path, models: dict[str, str]
) -> list[dict[str, Any]]:
    extension = "toml" if client == "codex" else "md"
    operations = []
    for suffix, role, strength in PROFILE_SPECS:
        model = models[strength]
        path = destination / f"{profile_name(suffix)}.{extension}"
        content = render_profile(client, suffix, role, strength, model)
        operations.append(operation_for_profile(path, content))
    return operations


def openclaude_content(path: Path, models: dict[str, str]) -> tuple[str, str, str]:
    if path.is_symlink():
        raise ValueError(
            f"OpenClaude destination must not be a symlink; pass its resolved target: {path}"
        )
    if path.exists():
        if not path.is_file():
            raise ValueError(f"OpenClaude destination is not a file: {path}")
        existing_text = read_text(path)
        try:
            settings = strict_json_loads(existing_text)
        except (json.JSONDecodeError, StrictJsonError) as error:
            raise ValueError(f"OpenClaude settings are not valid JSON: {path}") from error
        if not isinstance(settings, dict):
            raise ValueError("OpenClaude settings must contain a JSON object")
    else:
        existing_text = ""
        settings = {}

    desired_models = {
        f"linear-spanks-{strength}": {"model": model} for strength, model in models.items()
    }
    desired_routing = {
        "linear-spanks-planner": "linear-spanks-high",
        "linear-spanks-planner-medium": "linear-spanks-medium",
        "linear-spanks-executor-low": "linear-spanks-low",
        "linear-spanks-executor-medium": "linear-spanks-medium",
        "linear-spanks-executor-high": "linear-spanks-high",
        "linear-spanks-reviewer-medium": "linear-spanks-medium",
        "linear-spanks-reviewer-high": "linear-spanks-high",
    }
    metadata = settings.get("linearSpanksModelRouting")
    if metadata is None:
        raw_managed_models: list[str] = []
        raw_managed_routes: list[str] = []
    else:
        if (
            not isinstance(metadata, dict)
            or set(metadata) != {"schemaVersion", "managedAgentModels", "managedAgentRouting"}
            or type(metadata.get("schemaVersion")) is not int
            or metadata["schemaVersion"] != 1
        ):
            raise ValueError("linearSpanksModelRouting has unknown or future metadata")
        raw_managed_models = metadata["managedAgentModels"]
        raw_managed_routes = metadata["managedAgentRouting"]
        if (
            not isinstance(raw_managed_models, list)
            or not isinstance(raw_managed_routes, list)
            or raw_managed_models != sorted(desired_models)
            or raw_managed_routes != sorted(desired_routing)
        ):
            raise ValueError("OpenClaude managed routing ownership is invalid")
    managed_models = set(raw_managed_models)
    managed_routes = set(raw_managed_routes)

    agent_models = settings.setdefault("agentModels", {})
    agent_routing = settings.setdefault("agentRouting", {})
    if not isinstance(agent_models, dict) or not isinstance(agent_routing, dict):
        raise ValueError("OpenClaude agentModels and agentRouting must be JSON objects")
    conflicts = []
    for key in desired_models:
        if key in agent_models and key not in managed_models:
            conflicts.append(f"agentModels.{key}")
    for key in desired_routing:
        if key in agent_routing and key not in managed_routes:
            conflicts.append(f"agentRouting.{key}")
    if conflicts:
        raise ValueError(
            "refusing to replace unmanaged OpenClaude routing keys: " + ", ".join(conflicts)
        )

    agent_models.update(desired_models)
    agent_routing.update(desired_routing)
    managed_metadata = {
        "schemaVersion": 1,
        "managedAgentModels": sorted(desired_models),
        "managedAgentRouting": sorted(desired_routing),
    }
    settings["linearSpanksModelRouting"] = managed_metadata
    content = json.dumps(settings, indent=2, sort_keys=True, allow_nan=False) + "\n"
    preview_content = (
        json.dumps(
            {
                "agentModels": desired_models,
                "agentRouting": desired_routing,
                "linearSpanksModelRouting": managed_metadata,
            },
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    )
    if not path.exists():
        action = "create"
    elif content == existing_text:
        action = "unchanged"
    else:
        action = "update"
    return content, preview_content, action


def openclaude_operations(path: Path, models: dict[str, str]) -> list[dict[str, Any]]:
    expected = snapshot_path(path)
    content, preview_content, action = openclaude_content(path, models)
    require_unchanged(path, expected)
    return [
        {
            "path": str(path),
            "action": action,
            "managed": True,
            "content": preview_content,
            "_write_content": content,
            "_expected": expected,
        }
    ]


def client_report(
    client: str,
    destination: Path | None,
    models: dict[str, str],
    contract: dict[str, Any],
) -> dict[str, Any]:
    harness = contract["harnesses"][client]
    role_profiles: dict[str, Any]
    if client in PROFILE_CLIENTS:
        if destination is None:
            raise ValueError(f"{client} requires a native agent destination")
        operations = profile_operations(client, destination, models)
        role_profiles = {
            "planner": {
                "medium": "linear-spanks-planner-medium",
                "high": "linear-spanks-planner",
            },
            "executor": {strength: f"linear-spanks-executor-{strength}" for strength in models},
            "reviewer": {
                "medium": "linear-spanks-reviewer-medium",
                "high": "linear-spanks-reviewer-high",
            },
        }
        notes = ["Native custom agents pin the user-provided model for each logical strength."]
    elif client == "openclaude":
        if destination is None:
            raise ValueError("openclaude requires a settings destination")
        operations = openclaude_operations(destination, models)
        role_profiles = {
            "planner": {
                "medium": "linear-spanks-planner-medium",
                "high": "linear-spanks-planner",
            },
            "executor": {strength: f"linear-spanks-executor-{strength}" for strength in models},
            "reviewer": {
                "medium": "linear-spanks-reviewer-medium",
                "high": "linear-spanks-reviewer-high",
            },
        }
        notes = [
            "Agent routing entries are namespaced; existing unrelated settings are preserved.",
            "Invoke the matching role route or pass its model route as the Agent model override.",
        ]
    elif client == "antigravity":
        operations = []
        role_profiles = {
            "planner": "dynamic-read-only-subagent",
            "executor": "dynamic-isolated-subagent",
            "reviewer": "dynamic-independent-subagent",
        }
        notes = [
            "Subagents inherit the parent model; requested strengths are advisory and must be "
            "reported as such."
        ]
    elif client == "kimi":
        operations = []
        role_profiles = harness["profiles"]
        notes = [
            "Use Kimi's plan, coder, and explore profiles; profile selection does not enforce "
            "per-worker models."
        ]
    else:
        raise AssertionError(client)
    return {
        "client": client,
        "capability": harness["capability"],
        "delegation": harness["delegation"],
        "configuration": harness["configuration"],
        "destination": str(destination) if destination is not None else None,
        "role_profiles": role_profiles,
        "operations": operations,
        "notes": notes,
    }


def atomic_write(path: Path, content: str) -> None:
    write_text_exclusive(path, content)


def apply_reports(reports: list[dict[str, Any]]) -> None:
    conflicts = [
        operation["path"]
        for report in reports
        for operation in report["operations"]
        if operation["action"] == "conflict"
    ]
    if conflicts:
        raise ValueError("refusing to replace unmanaged agent files: " + ", ".join(conflicts))
    changes = [
        operation
        for report in reports
        for operation in report["operations"]
        if operation["action"] in {"create", "update"}
    ]
    for operation in changes:
        require_unchanged(Path(operation["path"]), operation["_expected"])
    completed: list[Path] = []
    poststates: dict[Path, Any] = {}
    backups: dict[Path, Path | None] = {}
    backup_states: dict[Path, Any] = {}
    try:
        for operation in changes:
            path = Path(operation["path"])
            expected = operation["_expected"]
            require_unchanged(path, expected)
            if expected != ABSENT_PATH:
                candidate = path.with_name(f".{path.name}.backup-{uuid.uuid4().hex}")
                vacate_expected(path, expected, candidate)
                backups[path] = candidate
                backup_states[candidate] = expected
                poststates[path] = ABSENT_PATH
                completed.append(path)
            desired = text_path_snapshot(operation["_write_content"])
            try:
                atomic_write(path, operation["_write_content"])
            except BaseException:
                actual = snapshot_path(path)
                if actual == desired:
                    backups.setdefault(path, None)
                    poststates[path] = desired
                    if path not in completed:
                        completed.append(path)
                elif actual != ABSENT_PATH and path not in backups:
                    require_unchanged(path, ABSENT_PATH)
                raise
            backups.setdefault(path, None)
            poststates[path] = desired
            if path not in completed:
                completed.append(path)
            require_unchanged(path, desired)
        for path, poststate in poststates.items():
            require_unchanged(path, poststate)
    except BaseException as write_error:
        rollback_errors: list[str] = []
        for path in reversed(completed):
            try:
                backup = backups.get(path)
                if backup is not None and not matches_snapshot(backup, backup_states[backup]):
                    rollback_errors.append(f"{backup}: concurrent backup drift")
                    continue
                quarantine = quarantine_expected(path, poststates[path])
                if backup is not None and (backup.exists() or backup.is_symlink()):
                    publish_staged_exclusive(backup, path)
                if quarantine is not None:
                    quarantine.unlink()
            except Exception as error:
                rollback_errors.append(f"{path}: {error}")
        if rollback_errors:
            raise OSError(
                "configuration write failed and rollback was incomplete: "
                + "; ".join(rollback_errors)
            ) from write_error
        raise
    cleanup_errors: list[str] = []
    for backup in backups.values():
        if backup is None:
            continue
        try:
            require_unchanged(backup, backup_states[backup])
            backup.unlink()
        except (LinearSpanksError, OSError) as error:
            cleanup_errors.append(f"{backup}: {error}")
    if cleanup_errors:
        raise FilesystemError(
            "INSTALLATION_BACKUP_CLEANUP_FAILED",
            "Model routing committed, but backup cleanup was incomplete: "
            + "; ".join(cleanup_errors),
        )


def public_reports(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    public = []
    for report in reports:
        public_report = {key: value for key, value in report.items() if key != "operations"}
        public_report["operations"] = [
            {key: value for key, value in operation.items() if not key.startswith("_")}
            for operation in report["operations"]
        ]
        public.append(public_report)
    return public


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument(
        "--client",
        default="codex",
        help="codex, openclaude, claude, antigravity, kimi, opencode, both, or all",
    )
    parser.add_argument("--low-model", required=True)
    parser.add_argument("--medium-model", required=True)
    parser.add_argument("--high-model", required=True)
    parser.add_argument(
        "--dest",
        help="override one client's native destination (agent directory or OpenClaude JSON file)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write managed configuration; without this flag only a preview is printed",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        destination_override: Path | None = None
        if args.dest is not None:
            if not args.dest or args.dest != args.dest.strip():
                raise ValueError("--dest must be non-empty and trimmed")
            destination_override = Path(args.dest).expanduser().absolute()
        clients = expand_clients(args.client)
        if destination_override is not None and len(clients) != 1:
            raise ValueError("--dest requires a selector that resolves to one client")
        models = {
            "low": validate_model_identifier("low", args.low_model),
            "medium": validate_model_identifier("medium", args.medium_model),
            "high": validate_model_identifier("high", args.high_model),
        }
        contract = load_routing_contract()
        reports = []
        for client in clients:
            destination = (
                destination_override
                if destination_override is not None
                else default_destination(client)
            )
            reports.append(client_report(client, destination, models, contract))
        if args.apply:
            apply_reports(reports)
        output = {
            "routing_contract_version": contract["schema_version"],
            "mode": "apply" if args.apply else "preview",
            "models": models,
            "clients": public_reports(reports),
        }
        print(json.dumps(output, indent=2, sort_keys=True, allow_nan=False))
    except LinearSpanksError as error:
        print(f"model routing configuration error: {error.message}", file=sys.stderr)
        return int(error.exit_code)
    except OSError as error:
        print(f"model routing configuration error: {error}", file=sys.stderr)
        return int(ExitCode.FILESYSTEM)
    except (ValueError, json.JSONDecodeError) as error:
        print(f"model routing configuration error: {error}", file=sys.stderr)
        return int(ExitCode.USAGE)
    return int(ExitCode.SUCCESS)


if __name__ == "__main__":
    raise SystemExit(main())
