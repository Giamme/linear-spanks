#!/usr/bin/env python3
"""Compatibility import for the packaged model-routing implementation."""

from __future__ import annotations

from typing import Any

from linear_spanks.installation import model_routing as _implementation
from linear_spanks.installation.model_routing import *  # noqa: F403

atomic_write = _implementation.atomic_write


def apply_reports(reports: list[dict[str, Any]]) -> None:
    """Forward while preserving monkeypatchable compatibility for rollback tests."""

    original = _implementation.atomic_write
    _implementation.atomic_write = atomic_write
    try:
        _implementation.apply_reports(reports)
    finally:
        _implementation.atomic_write = original


if __name__ == "__main__":
    raise SystemExit(_implementation.main())
