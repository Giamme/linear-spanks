"""Generate canonical command and artifact documentation from typed registries."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from ..core.errors import FilesystemError
from ..core.jsonio import atomic_write_text, read_text
from .artifacts import ARTIFACT_SPECS
from .commands import contracts

NAMESPACE_ORDER = (
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


def render_command_catalog() -> str:
    contract_set = contracts()
    lines = [
        "# Command catalog",
        "",
        "<!-- Generated from contracts/command-registry.v2.json; do not edit. -->",
        "",
        "All commands emit the v2 JSON envelope by default. Add `--format text` for a compact",
        "human-readable result. Shared workflow targeting options remain contract-defined.",
        "Shared option: `--ripwire on|off|inherit` (default inherit); see [Ripwire](ripwire.md).",
        "",
        "## Overview",
        "",
        "| Namespace | Core | Advanced |",
        "|---|---|---|",
    ]
    for namespace in NAMESPACE_ORDER:
        core = [
            command.name
            for command in contract_set.commands
            if command.namespace == namespace and command.tier == "core"
        ]
        advanced = [
            command.name
            for command in contract_set.commands
            if command.namespace == namespace and command.tier == "advanced"
        ]
        lines.append(
            f"| `{namespace}` | {', '.join(f'`{name}`' for name in core) or '—'} | "
            f"{', '.join(f'`{name}`' for name in advanced) or '—'} |"
        )
    for namespace in NAMESPACE_ORDER:
        lines.extend(("", f"## {namespace.title()}", ""))
        selected = [command for command in contract_set.commands if command.namespace == namespace]
        for command in selected:
            lines.extend(
                (
                    f"### `{command.usage}`",
                    "",
                    command.summary,
                    "",
                    f"- Tier: `{command.tier}`",
                    f"- Access: `{command.access}`",
                    f"- Approval: {command.approval}",
                    f"- Profiles: {', '.join(f'`{item}`' for item in command.profiles)}",
                    f"- Template: `{command.template}`" if command.template else "- Template: none",
                    f"- Transitions: {', '.join(f'`{item}`' for item in command.transitions)}"
                    if command.transitions
                    else "- Transitions: none",
                    f"- Removed v1 names: {', '.join(f'`{item}`' for item in command.legacy_names) or 'none'}",
                    "",
                )
            )
            for mode, variant in command.modes.items():
                lines.extend(
                    (
                        f"#### Mode override: `{mode}`",
                        "",
                        f"`{variant.usage}`",
                        "",
                        variant.summary,
                        "",
                        f"- Approval: {variant.approval}",
                        f"- Profiles: {', '.join(f'`{item}`' for item in variant.profiles)}",
                        f"- Template: `{variant.template}`"
                        if variant.template
                        else "- Template: none",
                        f"- Transitions: {', '.join(f'`{item}`' for item in variant.transitions)}"
                        if variant.transitions
                        else "- Transitions: none",
                        "",
                    )
                )
    lines.extend(
        (
            "## Removed v1 command mapping",
            "",
            "Flat commands are rejected and never executed as aliases.",
            "",
            "| Removed command | Exact replacement |",
            "|---|---|",
        )
    )
    registry = contract_set.contract("command_registry")
    replacements = registry.get("legacy_replacements", {})
    if isinstance(replacements, Mapping):
        for old, replacement in sorted(replacements.items()):
            lines.append(f"| `{old}` | `{replacement}` |")
    return "\n".join(lines).rstrip() + "\n"


def render_artifact_reference() -> str:
    lines = [
        "# Artifact and schema reference",
        "",
        "<!-- Generated from the artifact codec registry; do not edit. -->",
        "",
        "Every durable v2 artifact has exactly these top-level fields:",
        "",
        "| Field | Contract |",
        "|---|---|",
        "| `kind` | Stable codec key |",
        "| `schema_version` | `2` |",
        "| `revision` | Non-negative source revision or deterministic fallback |",
        "| `provenance` | Original product/schema version and canonical source hash |",
        "| `payload` | Validated source payload, including its original hashes |",
        "| `integrity` | SHA-256 over the other canonical v2 fields |",
        "",
        "## Registered kinds",
        "",
        "| Kind | Accepted v1 schema | Revision source | Integrity |",
        "|---|---:|---|---|",
    ]
    for spec in ARTIFACT_SPECS:
        versions = ", ".join(str(version) for version in spec.source_schema_versions)
        revisions = ", ".join(f"`{field}`" for field in spec.revision_fields) or "fallback"
        lines.append(f"| `{spec.kind}` | {versions} | {revisions} | SHA-256 |")
    lines.extend(
        (
            "",
            "## Lazy migration protocol",
            "",
            "1. Decode and validate v1 without changing the source.",
            "2. Include the exact path, source hash, source schema, revision, and v2 target in the",
            "   normal write preview.",
            "3. After the enclosing write is authorized, re-read and compare the source hash.",
            "4. Atomically persist v2 and perform a typed read-back.",
            "",
            "Read-only commands stop after step 1. Malformed, drifted, and future-version artifacts",
            "fail closed. There is no implicit bulk Linear migration.",
        )
    )
    return "\n".join(lines).rstrip() + "\n"


def generated_outputs() -> dict[Path, str]:
    root = contracts().root
    return {
        root / "references" / "command-catalog.md": render_command_catalog(),
        root / "references" / "artifact-schemas.md": render_artifact_reference(),
    }


def generate(*, check: bool = False) -> dict[str, Any]:
    outputs = generated_outputs()
    drifted = [
        str(path)
        for path, expected in outputs.items()
        if not path.is_file() or read_text(path) != expected
    ]
    if check and drifted:
        raise FilesystemError(
            "GENERATED_DOCUMENT_DRIFT",
            "Generated documentation is stale",
            details={"files": drifted},
        )
    if not check:
        for path, content in outputs.items():
            atomic_write_text(path, content)
    return {
        "status": "current" if not drifted else "generated",
        "files": [str(path) for path in outputs],
    }


READER_ONLY_DOCUMENTS = frozenset(
    {
        # routing catalog an operator consults directly (SKILL.md step 1)
        "references/command-catalog.md",
        # generated migration reference pointed at by SKILL.md
        "references/artifact-schemas.md",
        # human-readable source; its normative content is dispatched as the core_policy slice
        "references/core-policy.md",
    }
)


def check_reachable() -> dict[str, Any]:
    """Fail when a reference or template no compiled command ever loads.

    SKILL.md tells the agent to read only the compiled ``required_references``, so a
    governing document that no envelope requires cannot reach the agent at all. Anything
    genuinely written for a human reader belongs in READER_ONLY_DOCUMENTS.
    """

    from ..contracts.compiler import reachable_references

    root = contracts().root
    reached = reachable_references()
    on_disk = {
        f"{folder}/{path.name}"
        for folder in ("references", "templates")
        for path in sorted((root / folder).glob("*.md"))
    }
    unreachable = sorted(on_disk - reached - READER_ONLY_DOCUMENTS)
    if unreachable:
        raise FilesystemError(
            "UNREACHABLE_REFERENCE",
            "No compiled command requires these documents",
            details={"documents": unreachable},
        )
    missing = sorted(reached - on_disk)
    if missing:
        raise FilesystemError(
            "REFERENCE_NOT_FOUND",
            "Compiled commands require documents that do not exist",
            details={"documents": missing},
        )
    return {"status": "valid", "reachable": len(reached), "reader_only": len(READER_ONLY_DOCUMENTS)}


MARKDOWN_LINK_RE = re.compile(r"\[[^]]+\]\(([^)]+)\)")


def check_links(paths: Iterable[Path]) -> dict[str, Any]:
    checked = 0
    broken: list[dict[str, str]] = []
    for path in paths:
        text = read_text(path)
        for raw_target in MARKDOWN_LINK_RE.findall(text):
            target = raw_target.strip().strip("<>").split("#", 1)[0]
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            checked += 1
            resolved = (path.parent / target).resolve()
            if not resolved.exists():
                broken.append({"source": str(path), "target": raw_target})
    if broken:
        raise FilesystemError(
            "BROKEN_DOCUMENT_LINK",
            "Documentation contains broken local links",
            details={"links": broken},
        )
    return {"status": "valid", "links": checked}
