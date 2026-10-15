"""One typed registry for client aliases, destinations, and harness capabilities."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from ..core.errors import UsageError


@dataclass(frozen=True, slots=True)
class ClientSpec:
    name: str
    routing_name: str
    skill_destination_suffix: tuple[str, ...]
    skill_home_environment: str | None
    routing_destination: str
    capability: str

    def skill_destination(self, environment: Mapping[str, str]) -> Path:
        home = Path(environment.get("HOME") or Path.home())
        configured_base = (
            environment.get(self.skill_home_environment) if self.skill_home_environment else None
        )
        if configured_base:
            base = Path(configured_base)
        else:
            if self.name == "codex":
                base = home / ".codex"
            elif self.name == "openclaude":
                base = home / ".openclaude"
            elif self.name == "kimi":
                base = home / ".kimi-code"
            elif self.name == "opencode":
                base = Path(environment.get("XDG_CONFIG_HOME") or home / ".config")
            else:
                base = home
        return base.joinpath(*self.skill_destination_suffix)

    def model_destination(self, environment: Mapping[str, str]) -> Path | None:
        home = Path(environment.get("HOME") or Path.home())
        if self.routing_destination == "codex-agents":
            return Path(environment.get("CODEX_HOME") or home / ".codex") / "agents"
        if self.routing_destination == "claude-agents":
            return home / ".claude" / "agents"
        if self.routing_destination == "opencode-agents":
            config = Path(environment.get("XDG_CONFIG_HOME") or home / ".config")
            return config / "opencode" / "agents"
        if self.routing_destination == "openclaude-settings":
            return Path(environment.get("OPENCLAUDE_CONFIG") or home / ".openclaude.json")
        return None


class ClientRegistry:
    def __init__(
        self,
        clients: Mapping[str, ClientSpec],
        aliases: Mapping[str, tuple[str, ...]],
    ) -> None:
        self.clients = MappingProxyType(dict(clients))
        self.aliases = MappingProxyType(dict(aliases))

    def expand(self, selector: str) -> tuple[ClientSpec, ...]:
        names = self.aliases.get(selector)
        if names is None:
            names = (selector,) if selector in self.clients else None
        if names is None:
            raise UsageError("INVALID_CLIENT", f"Invalid client: {selector}")
        return tuple(self.clients[name] for name in names)

    def routing_clients(self, selector: str) -> tuple[str, ...]:
        result: list[str] = []
        for client in self.expand(selector):
            if client.routing_name not in result:
                result.append(client.routing_name)
        return tuple(result)

    def destinations(
        self, selector: str, environment: Mapping[str, str] | None = None
    ) -> tuple[tuple[str, Path], ...]:
        selected_environment = environment or os.environ
        return tuple(
            (client.name, client.skill_destination(selected_environment))
            for client in self.expand(selector)
        )


def client_registry() -> ClientRegistry:
    clients = {
        "codex": ClientSpec(
            "codex", "codex", ("skills",), "CODEX_HOME", "codex-agents", "native-model"
        ),
        "openclaude": ClientSpec(
            "openclaude",
            "openclaude",
            ("skills",),
            "OPENCLAUDE_HOME",
            "openclaude-settings",
            "native-model",
        ),
        "claude": ClientSpec(
            "claude", "claude", (".claude", "skills"), None, "claude-agents", "native-model"
        ),
        "antigravity-cli": ClientSpec(
            "antigravity-cli",
            "antigravity",
            (".gemini", "antigravity-cli", "skills"),
            None,
            "none",
            "inherited-model",
        ),
        "antigravity-ide": ClientSpec(
            "antigravity-ide",
            "antigravity",
            (".gemini", "config", "skills"),
            None,
            "none",
            "inherited-model",
        ),
        "kimi": ClientSpec("kimi", "kimi", ("skills",), "KIMI_CODE_HOME", "none", "advisory-only"),
        "opencode": ClientSpec(
            "opencode",
            "opencode",
            ("opencode", "skills"),
            "XDG_CONFIG_HOME",
            "opencode-agents",
            "native-model",
        ),
    }
    aliases = {
        "claude-code": ("claude",),
        "kimi-code": ("kimi",),
        "antigravity": ("antigravity-cli", "antigravity-ide"),
        "both": ("codex", "openclaude"),
        "all": tuple(clients),
    }
    return ClientRegistry(clients, aliases)
