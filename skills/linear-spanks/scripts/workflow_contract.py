#!/usr/bin/env python3
# ruff: noqa: I001
"""Deprecated v1 internal adapter.

The v2 executable is ``linear_spanks_cli.py``. This module remains importable so existing
persisted workflows and third-party diagnostic scripts can be characterized during migration.
It is not the public v2 command surface.
"""

from __future__ import annotations

from linear_spanks.compat.v1_runtime import *  # noqa: F403
from linear_spanks.cli import main as _v2_main


if __name__ == "__main__":
    raise SystemExit(_v2_main())
