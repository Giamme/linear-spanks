"""Ripwire preferences; resolving a setting never indexes or downloads source."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..core.errors import UsageError
from ..core.jsonio import strict_json_loads
from ..installation.skill_installer import Change, InstallPlan, _apply_plans
from ..installation.snapshots import snapshot_path, write_text_exclusive

MODES = ("on", "off", "inherit")


def user_root(environment: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environment is None else environment
    return (
        Path(
            env.get("XDG_CONFIG_HOME") or str(Path(env.get("HOME") or str(Path.home())) / ".config")
        ).resolve()
        / "linear-spanks"
    )


def config_path(repo: Path | None = None, environment: Mapping[str, str] | None = None) -> Path:
    return (
        repo / ".linear-spanks" if repo is not None else user_root(environment)
    ) / "ripwire.json"


def safe_path(path: Path) -> None:
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise UsageError("RIPWIRE_UNSAFE_PATH", "Ripwire managed paths cannot contain symlinks")


def read_mode(path: Path) -> str:
    safe_path(path)
    if not path.exists():
        return "inherit"
    try:
        if path.stat().st_size > 4096:
            raise ValueError("configuration is too large")
        data = strict_json_loads(path.read_text())
        if (
            not isinstance(data, dict)
            or set(data) != {"schema_version", "mode"}
            or type(data["schema_version"]) is not int
            or data["schema_version"] != 1
            or data["mode"] not in MODES
        ):
            raise ValueError("expected schema_version 1 and mode on, off, or inherit")
        return str(data["mode"])
    except (ValueError, TypeError, OSError) as error:
        raise UsageError(
            "RIPWIRE_INVALID_CONFIG", f"Invalid Ripwire configuration at {path}: {error}"
        ) from error


def resolve(
    repo: Path | None, override: str = "inherit", environment: Mapping[str, str] | None = None
) -> dict[str, str]:
    if override not in MODES:
        raise UsageError("RIPWIRE_INVALID_MODE", "Ripwire mode must be on, off, or inherit")
    if override != "inherit":
        return {"mode": override, "source": "run"}
    if repo is not None:
        mode = read_mode(config_path(repo, environment))
        if mode != "inherit":
            return {"mode": mode, "source": "repository"}
    mode = read_mode(config_path(environment=environment))
    return {
        "mode": "on" if mode == "inherit" else mode,
        "source": "default" if mode == "inherit" else "user",
    }


def configure(
    mode: str, repo: Path | None = None, environment: Mapping[str, str] | None = None
) -> dict[str, Any]:
    if mode not in MODES:
        raise UsageError("RIPWIRE_INVALID_MODE", "Ripwire mode must be on, off, or inherit")
    path = config_path(repo, environment)
    safe_path(path)
    expected = snapshot_path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Reuse the installer's guarded publication and rollback for configuration too.
    import tempfile

    with tempfile.TemporaryDirectory(prefix=".ripwire-config-", dir=path.parent) as temporary:
        staged = Path(temporary) / "ripwire.json"
        write_text_exclusive(staged, json.dumps({"schema_version": 1, "mode": mode}) + "\n")
        record = path.parent / ".ripwire-config-managed"
        _apply_plans(
            [
                InstallPlan(
                    [Change(path, staged)],
                    record,
                    {path.name},
                    False,
                    "",
                    "",
                    snapshot_path(record),
                    {path: expected},
                )
            ]
        )
    return {"path": str(path), "mode": mode}
