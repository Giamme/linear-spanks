#!/usr/bin/env python3
"""Generate or verify v2 command and artifact documentation."""

from __future__ import annotations

import argparse

from linear_spanks.domains.documentation import generate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    generate(check=args.check)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
