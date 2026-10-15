"""Load the complete contract collection once and expose immutable typed views."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

from ..core.errors import FilesystemError, UsageError
from ..core.jsonio import freeze_json, load_json_object, mutable_json_copy
from ..core.types import CommandModeSpec, CommandSpec, ContractSet, ContractSource
from .semantic_validation import validate_contract_documents

SKILL_ROOT = Path(__file__).resolve().parents[3]
INDEX_PATH = SKILL_ROOT / "contracts" / "contract-set.v2.json"
NAMESPACES = {
    "codebase",
    "project",
    "milestone",
    "task",
    "wave",
    "verification",
    "learning",
    "context",
    "runtime",
}
REGISTRY_FIELDS = {
    "schema_version",
    "version",
    "default_format",
    "display",
    "commands",
    "legacy_replacements",
}
COMMAND_FIELDS = {
    "path",
    "tier",
    "access",
    "approval",
    "profiles",
    "template",
    "transitions",
    "legacy_names",
    "legacy_runtime_command",
    "usage",
    "summary",
}
MODE_FIELDS = {"approval", "profiles", "template", "transitions", "usage", "summary"}


def _read_contract(path: Path, expected_digest: str) -> dict[str, Any]:
    try:
        encoded = path.read_bytes()
    except OSError as error:
        raise FilesystemError(
            "CONTRACT_READ_FAILED",
            f"Unable to read contract {path}: {error}",
            details={"path": str(path)},
        ) from error
    actual = hashlib.sha256(encoded).hexdigest()
    if actual != expected_digest:
        raise FilesystemError(
            "CONTRACT_INTEGRITY_MISMATCH",
            f"Contract digest does not match the versioned index: {path.name}",
            details={"path": str(path), "expected": expected_digest, "actual": actual},
        )
    return load_json_object(path)


def _text_list(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise UsageError("INVALID_CONTRACT_SET", f"{field} must be a text array")
    return tuple(cast(list[str], value))


def _command_spec(value: Any) -> CommandSpec:
    if not isinstance(value, dict):
        raise UsageError("INVALID_COMMAND_REGISTRY", "Every command must be an object")
    if frozenset(value) not in {
        frozenset(COMMAND_FIELDS),
        frozenset(COMMAND_FIELDS | {"modes"}),
    }:
        raise UsageError(
            "INVALID_COMMAND_REGISTRY",
            "Command fields are incomplete or unknown",
        )
    path = value.get("path")
    if (
        not isinstance(path, list)
        or len(path) != 2
        or not all(isinstance(item, str) and item for item in path)
    ):
        raise UsageError("INVALID_COMMAND_REGISTRY", "Command path must contain two names")
    namespace, name = cast(list[str], path)
    if namespace not in NAMESPACES:
        raise UsageError("INVALID_COMMAND_REGISTRY", f"Unknown command namespace: {namespace}")
    tier = value.get("tier")
    access = value.get("access")
    approval = value.get("approval")
    summary = value.get("summary")
    usage = value.get("usage")
    runtime = value.get("legacy_runtime_command")
    if tier not in {"core", "advanced"}:
        raise UsageError("INVALID_COMMAND_REGISTRY", f"Invalid tier for {namespace} {name}")
    if access not in {"read", "write", "conditional"}:
        raise UsageError("INVALID_COMMAND_REGISTRY", f"Invalid access for {namespace} {name}")
    for field, item in (
        ("approval", approval),
        ("summary", summary),
        ("usage", usage),
        ("legacy_runtime_command", runtime),
    ):
        if not isinstance(item, str) or not item:
            raise UsageError("INVALID_COMMAND_REGISTRY", f"{namespace} {name} has invalid {field}")
    template = value.get("template")
    if template is not None and (not isinstance(template, str) or not template):
        raise UsageError("INVALID_COMMAND_REGISTRY", f"{namespace} {name} has invalid template")
    raw_modes = value.get("modes", {})
    if not isinstance(raw_modes, dict):
        raise UsageError("INVALID_COMMAND_REGISTRY", f"{namespace} {name} has invalid modes")
    modes: dict[str, CommandModeSpec] = {}
    for mode, raw_mode in raw_modes.items():
        if (
            mode not in {"step", "loop"}
            or not isinstance(raw_mode, dict)
            or set(raw_mode) != MODE_FIELDS
        ):
            raise UsageError(
                "INVALID_COMMAND_REGISTRY", f"{namespace} {name} has invalid mode {mode}"
            )
        mode_approval = raw_mode.get("approval")
        mode_summary = raw_mode.get("summary")
        mode_usage = raw_mode.get("usage")
        mode_template = raw_mode.get("template")
        if not all(
            isinstance(item, str) and item for item in (mode_approval, mode_summary, mode_usage)
        ):
            raise UsageError(
                "INVALID_COMMAND_REGISTRY", f"{namespace} {name} mode {mode} is incomplete"
            )
        if mode_template is not None and (not isinstance(mode_template, str) or not mode_template):
            raise UsageError(
                "INVALID_COMMAND_REGISTRY", f"{namespace} {name} mode {mode} has invalid template"
            )
        modes[mode] = CommandModeSpec(
            approval=cast(str, mode_approval),
            profiles=_text_list(raw_mode.get("profiles"), f"{mode} profiles"),
            template=mode_template,
            transitions=_text_list(raw_mode.get("transitions"), f"{mode} transitions"),
            summary=cast(str, mode_summary),
            usage=cast(str, mode_usage),
        )
    return CommandSpec(
        namespace=namespace,
        name=name,
        tier=cast(str, tier),
        access=cast(str, access),
        approval=cast(str, approval),
        profiles=_text_list(value.get("profiles"), "profiles"),
        template=template,
        transitions=_text_list(value.get("transitions"), "transitions"),
        legacy_names=_text_list(value.get("legacy_names"), "legacy_names"),
        summary=cast(str, summary),
        usage=cast(str, usage),
        legacy_runtime_command=cast(str, runtime),
        modes=MappingProxyType(modes),
    )


def _ordered_command_specs(
    registry: dict[str, Any], raw_commands: list[Any]
) -> tuple[CommandSpec, ...]:
    if (
        set(registry) != REGISTRY_FIELDS
        or type(registry.get("schema_version")) is not int
        or registry["schema_version"] != 2
        or registry.get("version") != "2.0.0"
        or registry.get("default_format") != "json"
    ):
        raise UsageError(
            "INVALID_COMMAND_REGISTRY",
            "Command registry metadata is not the exact v2 schema",
        )
    parsed = tuple(_command_spec(item) for item in raw_commands)
    by_path = {command.path: command for command in parsed}
    if len(by_path) != len(parsed):
        raise UsageError("INVALID_COMMAND_REGISTRY", "Command paths must be unique")

    display = registry.get("display")
    if not isinstance(display, dict) or set(display) != {"namespace_order", "commands"}:
        raise UsageError("INVALID_COMMAND_REGISTRY", "Command registry requires display order")
    namespace_order = display.get("namespace_order")
    names_by_namespace = display.get("commands")
    if (
        not isinstance(namespace_order, list)
        or not all(isinstance(item, str) for item in namespace_order)
        or len(namespace_order) != len(set(namespace_order))
        or set(namespace_order) != NAMESPACES
        or not isinstance(names_by_namespace, dict)
        or set(names_by_namespace) != NAMESPACES
    ):
        raise UsageError("INVALID_COMMAND_REGISTRY", "Command display namespaces are invalid")

    ordered_paths: list[str] = []
    for namespace in cast(list[str], namespace_order):
        names = names_by_namespace.get(namespace)
        if (
            not isinstance(names, list)
            or not all(isinstance(name, str) and name for name in names)
            or len(names) != len(set(names))
        ):
            raise UsageError(
                "INVALID_COMMAND_REGISTRY",
                f"Command display order is invalid for {namespace}",
            )
        seen_advanced = False
        for name in cast(list[str], names):
            path = f"{namespace} {name}"
            command = by_path.get(path)
            if command is None:
                raise UsageError(
                    "INVALID_COMMAND_REGISTRY", f"Display order references missing {path}"
                )
            if command.tier == "advanced":
                seen_advanced = True
            elif seen_advanced:
                raise UsageError(
                    "INVALID_COMMAND_REGISTRY",
                    f"Core command {path} appears after advanced commands",
                )
            ordered_paths.append(path)
    if len(ordered_paths) != len(set(ordered_paths)) or set(ordered_paths) != set(by_path):
        raise UsageError(
            "INVALID_COMMAND_REGISTRY", "Command display order must cover every command once"
        )
    replacements = registry.get("legacy_replacements")
    if not isinstance(replacements, dict) or not all(
        isinstance(name, str) and name and isinstance(replacement, str) and replacement
        for name, replacement in replacements.items()
    ):
        raise UsageError("INVALID_COMMAND_REGISTRY", "Legacy replacements must be a text mapping")
    expected_replacements: dict[str, str] = {}
    for command in parsed:
        for legacy_name in command.legacy_names:
            if legacy_name == "run-milestone":
                replacement = "milestone run --mode step"
            elif legacy_name == "run-milestone-loop":
                replacement = "milestone run --mode loop"
            else:
                replacement = command.path
            expected_replacements[legacy_name] = replacement
    if replacements != expected_replacements:
        raise UsageError(
            "INVALID_COMMAND_REGISTRY",
            "Legacy replacements must exactly cover command legacy names",
        )
    return tuple(by_path[path] for path in ordered_paths)


def _legacy_transitions(command: Mapping[str, Any]) -> tuple[str, ...]:
    declared = command.get("transitions")
    if isinstance(declared, Sequence) and not isinstance(declared, str | bytes):
        return tuple(cast(Sequence[str], declared))
    transition = command.get("transition")
    return (transition,) if isinstance(transition, str) and transition else ()


def _execution_profiles(execution: Mapping[str, Any], name: str) -> tuple[str, ...]:
    profiles: list[str] = []
    for field in ("execution", "context"):
        value = execution.get(field)
        if not isinstance(value, str) or not value:
            raise UsageError(
                "INVALID_COMMAND_REGISTRY",
                f"Legacy execution {name} has invalid {field} profile",
            )
        profiles.append(value)
    orchestration = execution.get("orchestration")
    if orchestration is not None:
        if not isinstance(orchestration, str) or not orchestration:
            raise UsageError(
                "INVALID_COMMAND_REGISTRY",
                f"Legacy execution {name} has invalid orchestration profile",
            )
        profiles.append(orchestration)
    return tuple(profiles)


def _validate_command_projection(
    command: CommandSpec,
    legacy_name: str,
    legacy: Mapping[str, Any],
    execution: Mapping[str, Any],
) -> None:
    expected_approval = legacy.get("approval")
    if command.path == "milestone run" and legacy_name == "run-milestone":
        if not isinstance(expected_approval, str):
            raise UsageError("INVALID_COMMAND_REGISTRY", "run-milestone approval is invalid")
        expected_approval = expected_approval.replace("--autopilot", "--mode loop")
    expected = {
        "access": legacy.get("access"),
        "approval": expected_approval,
        "template": legacy.get("template"),
        "transitions": _legacy_transitions(legacy),
        "profiles": _execution_profiles(execution, legacy_name),
    }
    actual = {
        "access": command.access,
        "approval": command.approval,
        "template": command.template,
        "transitions": command.transitions,
        "profiles": command.profiles,
    }
    if actual != expected:
        raise UsageError(
            "INVALID_COMMAND_REGISTRY",
            f"{command.path} does not match characterized command {legacy_name}",
            details={"expected": expected, "actual": actual},
        )


def _validate_command_registry_semantics(
    commands: Sequence[CommandSpec],
    documents: Mapping[str, Mapping[str, Any]],
) -> None:
    manifest = documents.get("legacy_commands", {}).get("commands")
    execution_commands = documents.get("execution", {}).get("commands")
    if (
        not isinstance(manifest, Sequence)
        or isinstance(manifest, str | bytes)
        or not isinstance(execution_commands, Mapping)
    ):
        raise UsageError("INVALID_CONTRACT_SET", "Legacy command contracts are malformed")
    legacy_by_name = {item.get("name"): item for item in manifest if isinstance(item, Mapping)}
    expected_legacy_names = set(legacy_by_name) - {"help"}
    actual_legacy_names = {name for command in commands for name in command.legacy_names}
    if actual_legacy_names != expected_legacy_names:
        raise UsageError(
            "INVALID_COMMAND_REGISTRY",
            "The v2 registry must cover every removed v1 command except help exactly once",
        )
    for command in commands:
        if not command.legacy_names:
            native = documents.get("context_management", {}).get("commands", {}).get(command.path)
            if not isinstance(native, Mapping) or command.legacy_runtime_command != command.path:
                raise UsageError(
                    "INVALID_COMMAND_REGISTRY", "Native command lacks indexed context contract"
                )
            if (
                command.access != native["access"]
                or command.approval != native["approval"]
                or command.profiles != ("context_management",)
                or command.transitions
            ):
                raise UsageError(
                    "INVALID_COMMAND_REGISTRY", "Native context command contract drift"
                )
            continue
        if command.legacy_runtime_command not in command.legacy_names:
            raise UsageError(
                "INVALID_COMMAND_REGISTRY",
                f"{command.path} runtime identity is not one of its removed v1 commands",
            )
        legacy = legacy_by_name.get(command.legacy_runtime_command)
        execution = execution_commands.get(command.legacy_runtime_command)
        if not isinstance(legacy, Mapping) or not isinstance(execution, Mapping):
            raise UsageError(
                "INVALID_COMMAND_REGISTRY",
                f"{command.path} runtime identity is not characterized",
            )
        _validate_command_projection(
            command,
            command.legacy_runtime_command,
            legacy,
            execution,
        )
        if command.path == "milestone run":
            if set(command.modes) != {"loop"} or set(command.legacy_names) != {
                "run-milestone",
                "run-milestone-loop",
            }:
                raise UsageError(
                    "INVALID_COMMAND_REGISTRY",
                    "milestone run must expose the characterized step and loop runtimes",
                )
            loop = command.modes["loop"]
            loop_legacy = legacy_by_name.get("run-milestone-loop")
            loop_execution = execution_commands.get("run-milestone-loop")
            if not isinstance(loop_legacy, Mapping) or not isinstance(loop_execution, Mapping):
                raise UsageError(
                    "INVALID_COMMAND_REGISTRY",
                    "milestone run loop runtime is not characterized",
                )
            expected_loop = {
                "access": loop_legacy.get("access"),
                "approval": loop_legacy.get("approval"),
                "template": loop_legacy.get("template"),
                "transitions": _legacy_transitions(loop_legacy),
                "profiles": _execution_profiles(loop_execution, "run-milestone-loop"),
            }
            actual_loop = {
                "access": command.access,
                "approval": loop.approval,
                "template": loop.template,
                "transitions": loop.transitions,
                "profiles": loop.profiles,
            }
            if actual_loop != expected_loop:
                raise UsageError(
                    "INVALID_COMMAND_REGISTRY",
                    "milestone run loop metadata does not match run-milestone-loop",
                    details={"expected": expected_loop, "actual": actual_loop},
                )
        elif command.modes:
            raise UsageError(
                "INVALID_COMMAND_REGISTRY",
                f"{command.path} cannot declare command modes",
            )


def load_contract_set(index_path: Path = INDEX_PATH) -> ContractSet:
    index = load_json_object(index_path)
    expected_index_fields = {
        "schema_version",
        "version",
        "revision",
        "contracts",
        "artifact_integrity",
    }
    if set(index) != expected_index_fields:
        raise UsageError(
            "INVALID_CONTRACT_SET",
            "Contract-set index fields are incomplete or unknown",
        )
    if type(index.get("schema_version")) is not int or index["schema_version"] != 2:
        raise UsageError("INVALID_CONTRACT_SET", "Contract-set schema_version must be 2")
    if index.get("version") != "2.0.0":
        raise UsageError("INVALID_CONTRACT_SET", "Contract-set version must be 2.0.0")
    integrity = index.get("artifact_integrity")
    expected_integrity = {
        "algorithm": "sha256",
        "canonicalization": "json-sort-keys-utf8-v1",
        "future_version_policy": "reject",
        "migration_policy": "authorized-write-only",
    }
    if integrity != expected_integrity:
        raise UsageError(
            "INVALID_CONTRACT_SET",
            "Contract-set artifact integrity policy is not the required v2 policy",
        )
    revision = index.get("revision")
    entries = index.get("contracts")
    if not isinstance(revision, str) or not revision or revision != revision.strip():
        raise UsageError("INVALID_CONTRACT_SET", "Contract set requires a revision")
    if not isinstance(entries, dict) or not entries:
        raise UsageError("INVALID_CONTRACT_SET", "Contract set requires contracts")

    root = index_path.parent.parent
    documents: dict[str, dict[str, Any]] = {}
    sources: dict[str, ContractSource] = {}
    for name, raw_entry in entries.items():
        if (
            not isinstance(name, str)
            or not name
            or name != name.strip()
            or not isinstance(raw_entry, dict)
            or set(raw_entry) != {"path", "sha256", "schema_versions"}
        ):
            raise UsageError("INVALID_CONTRACT_SET", "Invalid contract index entry")
        relative = raw_entry.get("path")
        digest = raw_entry.get("sha256")
        versions = raw_entry.get("schema_versions")
        if (
            not isinstance(relative, str)
            or not relative
            or relative != relative.strip()
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or not isinstance(versions, list)
            or not versions
            or not all(
                isinstance(version, int) and not isinstance(version, bool) and version > 0
                for version in versions
            )
        ):
            raise UsageError("INVALID_CONTRACT_SET", f"Invalid index entry: {name}")
        document = _read_contract(root / relative, digest)
        document_version = document.get("schema_version")
        if (
            not isinstance(document_version, int)
            or isinstance(document_version, bool)
            or document_version not in versions
        ):
            raise UsageError(
                "INVALID_CONTRACT_SET", f"Unsupported schema version for contract: {name}"
            )
        documents[name] = document
        sources[name] = ContractSource(
            path=relative,
            sha256=digest,
            schema_versions=tuple(cast(list[int], versions)),
        )

    registry = documents.get("command_registry")
    if registry is None:
        raise UsageError("INVALID_CONTRACT_SET", "Command registry is missing")
    raw_commands = registry.get("commands")
    if not isinstance(raw_commands, list):
        raise UsageError("INVALID_COMMAND_REGISTRY", "Command registry requires commands")
    commands = _ordered_command_specs(registry, raw_commands)
    legacy_names = [name for command in commands for name in command.legacy_names]
    if len(set(legacy_names)) != len(legacy_names):
        raise UsageError("INVALID_COMMAND_REGISTRY", "Legacy command mappings must be unique")
    contracts = {
        name: cast(Mapping[str, Any], freeze_json(document)) for name, document in documents.items()
    }
    selected = ContractSet(
        schema_version=2,
        revision=revision,
        root=root,
        contracts=MappingProxyType(contracts),
        commands=commands,
        sources=MappingProxyType(sources),
    )
    validate_contract_set(selected)
    return selected


@lru_cache(maxsize=1)
def get_contract_set() -> ContractSet:
    return load_contract_set()


def validate_contract_set(contract_set: ContractSet | None = None) -> dict[str, Any]:
    selected = contract_set or get_contract_set()
    if selected.schema_version != 2:
        raise UsageError("INVALID_CONTRACT_SET", "ContractSet schema_version must be 2")
    if not selected.revision or selected.revision != selected.revision.strip():
        raise UsageError(
            "INVALID_CONTRACT_SET", "ContractSet revision must be non-empty and trimmed"
        )
    if set(selected.sources) != set(selected.contracts):
        raise UsageError(
            "INVALID_CONTRACT_SET",
            "ContractSet sources must exactly cover indexed contracts",
        )
    for name, document in selected.contracts.items():
        source = selected.sources[name]
        source_path = Path(source.path)
        document_version = document.get("schema_version")
        if (
            not source.path
            or source_path.is_absolute()
            or ".." in source_path.parts
            or re.fullmatch(r"[0-9a-f]{64}", source.sha256) is None
            or not source.schema_versions
            or not all(
                isinstance(version, int) and not isinstance(version, bool) and version > 0
                for version in source.schema_versions
            )
            or not isinstance(document_version, int)
            or isinstance(document_version, bool)
            or document_version not in source.schema_versions
        ):
            raise UsageError(
                "INVALID_CONTRACT_SET",
                f"ContractSet source metadata is invalid for {name}",
            )
    validate_contract_documents(selected.contracts)
    legacy_manifest = selected.contract("legacy_commands").get("commands")
    execution_commands = selected.contract("execution").get("commands")
    transitions = selected.contract("workflow").get("transitions")
    if (
        not isinstance(legacy_manifest, Sequence)
        or isinstance(legacy_manifest, str | bytes)
        or not isinstance(execution_commands, Mapping)
    ):
        raise UsageError("INVALID_CONTRACT_SET", "Legacy command contracts are malformed")
    if not isinstance(transitions, Mapping):
        raise UsageError("INVALID_CONTRACT_SET", "Workflow transitions are malformed")
    legacy_by_name = {
        item.get("name"): item for item in legacy_manifest if isinstance(item, Mapping)
    }
    for command in selected.commands:
        for legacy_name in command.legacy_names:
            if legacy_name not in legacy_by_name or legacy_name not in execution_commands:
                raise UsageError(
                    "INVALID_COMMAND_REGISTRY",
                    f"{command.path} references missing legacy command {legacy_name}",
                )
        if (
            command.template is not None
            and not (selected.root / "templates" / command.template).is_file()
        ):
            raise FilesystemError(
                "TEMPLATE_NOT_FOUND",
                f"Template does not exist: {command.template}",
            )
        for transition in command.transitions:
            if transition not in transitions:
                raise UsageError(
                    "INVALID_COMMAND_REGISTRY",
                    f"{command.path} references missing transition {transition}",
                )
        for mode, variant in command.modes.items():
            if command.path != "milestone run":
                raise UsageError(
                    "INVALID_COMMAND_REGISTRY",
                    f"{command.path} cannot declare mode {mode}",
                )
            if (
                variant.template is not None
                and not (selected.root / "templates" / variant.template).is_file()
            ):
                raise FilesystemError(
                    "TEMPLATE_NOT_FOUND",
                    f"Template does not exist: {variant.template}",
                )
            for transition in variant.transitions:
                if transition not in transitions:
                    raise UsageError(
                        "INVALID_COMMAND_REGISTRY",
                        f"{command.path} mode {mode} references missing transition {transition}",
                    )
    registry = selected.contract("command_registry")
    raw_commands = registry.get("commands")
    if not isinstance(raw_commands, Sequence) or isinstance(raw_commands, str | bytes):
        raise UsageError("INVALID_COMMAND_REGISTRY", "Command registry requires commands")
    registry_commands = _ordered_command_specs(
        mutable_json_copy(registry),
        mutable_json_copy(raw_commands),
    )
    if tuple(selected.commands) != registry_commands:
        raise UsageError(
            "INVALID_COMMAND_REGISTRY",
            "Typed commands do not match the indexed command registry",
        )
    _validate_command_registry_semantics(selected.commands, selected.contracts)
    return {
        "status": "valid",
        "version": "2.0.0",
        "revision": selected.revision,
        "commands": len(selected.commands),
        "contracts": len(selected.contracts),
    }
