#!/usr/bin/env python3
"""Linear Spanks v2 command-line entrypoint."""

import sys

if sys.version_info < (3, 11):  # noqa: UP036 - runs before the 3.11-only imports
    raise SystemExit(f"Linear Spanks needs Python 3.11 or newer; this is {sys.version.split()[0]}.")

from linear_spanks.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
