"""Start coverage in subprocesses only when the verification script requests it."""

from __future__ import annotations

import os

if os.environ.get("COVERAGE_PROCESS_START"):
    import coverage

    coverage.process_startup()
