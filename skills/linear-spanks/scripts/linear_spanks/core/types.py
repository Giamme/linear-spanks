"""Typed contributor interfaces for contracts, artifacts, execution, and CLI results."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol, TypeAlias

from .jsonio import freeze_json

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class CommandModeSpec:
    """Canonical metadata override for one public command mode."""

    approval: str
    profiles: tuple[str, ...]
    template: str | None
    transitions: tuple[str, ...]
    summary: str
    usage: str


@dataclass(frozen=True, slots=True)
class CommandSpec:
    """Canonical description of one public v2 command."""

    namespace: str
    name: str
    tier: str
    access: str
    approval: str
    profiles: tuple[str, ...]
    template: str | None
    transitions: tuple[str, ...]
    legacy_names: tuple[str, ...]
    summary: str
    usage: str
    legacy_runtime_command: str
    modes: Mapping[str, CommandModeSpec] = field(default_factory=dict)

    @property
    def path(self) -> str:
        return f"{self.namespace} {self.name}"


@dataclass(frozen=True, slots=True)
class ContractSource:
    """Indexed source metadata for one immutable contract document."""

    path: str
    sha256: str
    schema_versions: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ContractSet:
    """One immutable, injectable snapshot of every runtime contract."""

    schema_version: int
    revision: str
    root: Path
    contracts: Mapping[str, Mapping[str, Any]]
    commands: tuple[CommandSpec, ...]
    sources: Mapping[str, ContractSource] = field(default_factory=dict)
    by_path: Mapping[str, CommandSpec] = field(init=False)
    by_legacy_name: Mapping[str, CommandSpec] = field(init=False)

    def __post_init__(self) -> None:
        frozen_contracts: dict[str, Mapping[str, Any]] = {}
        for name, contract in self.contracts.items():
            if not isinstance(name, str) or not name:
                raise ValueError("Contract names must be non-empty strings")
            if not isinstance(contract, Mapping):
                raise ValueError(f"Contract {name} must be a JSON object")
            frozen_contracts[name] = freeze_json(contract)
        object.__setattr__(self, "contracts", MappingProxyType(frozen_contracts))
        object.__setattr__(self, "sources", MappingProxyType(dict(self.sources)))
        commands = tuple(
            replace(
                command,
                profiles=tuple(command.profiles),
                transitions=tuple(command.transitions),
                legacy_names=tuple(command.legacy_names),
                modes=MappingProxyType(
                    {
                        name: replace(
                            mode,
                            profiles=tuple(mode.profiles),
                            transitions=tuple(mode.transitions),
                        )
                        for name, mode in command.modes.items()
                    }
                ),
            )
            for command in self.commands
        )
        object.__setattr__(self, "commands", commands)
        by_path = {command.path: command for command in commands}
        by_legacy: dict[str, CommandSpec] = {}
        for command in commands:
            for legacy_name in command.legacy_names:
                by_legacy[legacy_name] = command
        object.__setattr__(self, "by_path", MappingProxyType(by_path))
        object.__setattr__(self, "by_legacy_name", MappingProxyType(by_legacy))

    def contract(self, name: str) -> Mapping[str, Any]:
        return self.contracts[name]


@dataclass(frozen=True, slots=True)
class ExecutionEnvelope:
    """Compiled command metadata passed to a domain operation."""

    command: CommandSpec
    assurance: str
    arguments: tuple[str, ...]
    contract: Mapping[str, Any]
    migrations: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class MigrationAuthorization:
    """Approval receipt bound to one exact execution and migration preview."""

    command: str
    target: str
    preview_hash: str
    receipt_id: str
    decision: str = "approved"
    schema_version: int = 2


@dataclass(frozen=True, slots=True)
class CliResult:
    """Stable JSON-first result envelope."""

    command: str
    ok: bool
    result: Mapping[str, Any] | Sequence[Any] | str | int | float | bool | None = None
    error: Mapping[str, Any] | None = None
    warnings: tuple[str, ...] = ()
    schema_version: int = 2

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "command": self.command,
            "ok": self.ok,
        }
        if self.ok:
            payload["result"] = self.result
        else:
            payload["error"] = dict(self.error or {})
        payload["warnings"] = list(self.warnings)
        return payload


@dataclass(frozen=True, slots=True)
class DecodedArtifact:
    """A validated artifact plus migration metadata."""

    kind: str
    schema_version: int
    revision: int
    provenance: Mapping[str, Any]
    payload: Mapping[str, Any]
    integrity: Mapping[str, Any]
    needs_migration: bool
    source_hash: str


class ArtifactCodec(Protocol):
    """Contributor interface implemented by every durable artifact kind."""

    kind: str

    def decode(self, value: Mapping[str, Any]) -> DecodedArtifact:
        """Validate v1/v2 data without mutating its source."""

    def encode_v2(self, artifact: DecodedArtifact) -> JsonObject:
        """Produce the canonical v2 representation."""

    def migration_preview(self, artifact: DecodedArtifact, source: str) -> Mapping[str, Any]:
        """Describe the exact authorized-write migration."""
