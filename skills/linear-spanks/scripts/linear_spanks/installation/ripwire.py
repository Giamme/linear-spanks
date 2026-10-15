"""Install only the checksum-pinned Ripwire binary and license, shared by clients."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..core.errors import UsageError
from ..extensions.ripwire_settings import safe_path, user_root
from .caveman import download_archive, safe_extract_archive
from .skill_installer import Change, InstallPlan, _apply_plans
from .snapshots import ABSENT_PATH, snapshot_path

RELEASE = Path(__file__).resolve().parents[3] / "ripwire-release.json"
VERSION = "0.4.0"


def install_root(environment: Mapping[str, str] | None = None) -> Path:
    return user_root(environment) / "extensions" / "ripwire" / VERSION


def binary_path(environment: Mapping[str, str] | None = None) -> Path:
    return install_root(environment) / "ripwire"


def platform_key() -> str:
    system = {"Darwin": "macos", "Linux": "linux"}.get(platform.system())
    architecture = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x64", "AMD64": "x64"}.get(
        platform.machine()
    )
    if system is None or architecture is None:
        raise UsageError(
            "RIPWIRE_UNSUPPORTED_PLATFORM", "Ripwire supports macOS/Linux ARM64 and x64"
        )
    return f"{system}-{architecture}"


def available(environment: Mapping[str, str] | None = None) -> bool:
    root = install_root(environment)
    safe_path(root / "ripwire")
    safe_path(root / "receipt.json")
    safe_path(root / "LICENSE")
    try:
        if (root / "receipt.json").stat().st_size > 4096:
            return False
        receipt = json.loads((root / "receipt.json").read_text())
        return bool(
            receipt["version"] == VERSION
            and receipt["platform"] == platform_key()
            and receipt["license_sha256"]
            == hashlib.sha256((root / "LICENSE").read_bytes()).hexdigest()
            and os.access(root / "ripwire", os.X_OK)
            and receipt["binary_sha256"]
            == hashlib.sha256((root / "ripwire").read_bytes()).hexdigest()
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False


def install(
    environment: Mapping[str, str] | None = None, *, dry_run: bool = False
) -> dict[str, Any]:
    target = install_root(environment)
    if dry_run:
        return {"status": "planned", "version": VERSION, "path": str(target)}
    safe_path(target)
    key = platform_key()
    if available(environment):
        return {"status": "available", "version": VERSION, "path": str(target)}
    record = target.parent / ".linear-spanks-ripwire-managed"
    safe_path(record)
    expected = snapshot_path(target)
    expected_record = snapshot_path(record)
    if expected != ABSENT_PATH and (
        not record.is_file() or VERSION not in record.read_text().splitlines()
    ):
        raise UsageError(
            "RIPWIRE_UNOWNED_TARGET", "Refusing to replace an unmanaged Ripwire installation"
        )
    asset = json.loads(RELEASE.read_text())["assets"][key]
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix=".ripwire-", dir=target.parent) as temporary:
        staging = Path(temporary)
        archive = staging / "release.tar.gz"
        download_archive(asset["url"], archive)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != asset["sha256"]:
            raise UsageError("RIPWIRE_CHECKSUM_MISMATCH", "Ripwire release checksum mismatch")
        extracted = safe_extract_archive(archive, staging / "extracted")
        published = staging / "published"
        published.mkdir(mode=0o700)
        for name in ("ripwire", "LICENSE"):
            if not (extracted / name).is_file():
                raise UsageError("RIPWIRE_INVALID_RELEASE", f"Release is missing {name}")
            shutil.copyfile(extracted / name, published / name)
        os.chmod(published / "ripwire", 0o700)
        receipt = {
            "version": VERSION,
            "platform": key,
            "archive_sha256": asset["sha256"],
            "binary_sha256": hashlib.sha256((published / "ripwire").read_bytes()).hexdigest(),
            "license_sha256": hashlib.sha256((published / "LICENSE").read_bytes()).hexdigest(),
        }
        (published / "receipt.json").write_text(json.dumps(receipt) + "\n")
        _apply_plans(
            [
                InstallPlan(
                    [Change(target, published)],
                    record,
                    {VERSION},
                    False,
                    "",
                    "",
                    expected_record,
                    {target: expected},
                )
            ]
        )
    return {"status": "installed", "version": VERSION, "path": str(target)}
