"""Measure the fixed governance overhead every dispatch pays before any target evidence.

The replay benchmark bounds what the context machinery *saves* across a long project. This
bounds what it *costs* per invocation: the compiled envelope plus the reference packet a
coordinator must load. Both halves need a ceiling, otherwise overhead grows unobserved.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any, ClassVar

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "skills/linear-spanks/scripts"))

from linear_spanks.contracts.compiler import compile_public_command  # noqa: E402
from linear_spanks.domains.execution import execution_brief  # noqa: E402

SKILL_ROOT = REPO_ROOT / "skills/linear-spanks"
BUDGETS_PATH = REPO_ROOT / "tests/fixtures/context/envelope-budgets.json"

# Public command -> full argument tuple -> the internal runtime name a coordinator compiles a
# brief for. A null name means the command has no optimized brief path and always loads the
# full reference packet.
MEASURED_COMMANDS: tuple[tuple[str, tuple[str, ...], str | None], ...] = (
    ("task run", ("ENG-123",), "run-task"),
    ("task plan", ("ENG-123",), "plan-task"),
    ("milestone run", ("ENG-42", "--mode", "loop"), "run-milestone-loop"),
    ("project run", ("PRJ-1",), None),
    ("context budget", ("task", "ENG-123", "--tokens", "24000"), None),
)


def estimated_tokens(text: str) -> int:
    return (len(text.encode("utf-8")) + 3) // 4


def reference_tokens(references: list[str]) -> int:
    total = 0
    for reference in references:
        path = SKILL_ROOT / reference
        if not path.exists():
            raise AssertionError(f"required reference is missing: {reference}")
        total += estimated_tokens(path.read_text())
    return total


def measure(command: str, positionals: tuple[str, ...], runtime_name: str | None) -> dict[str, Any]:
    envelope = compile_public_command(command, positionals).contract
    envelope_tokens = estimated_tokens(json.dumps(envelope, sort_keys=True))
    references = list(envelope.get("required_references", []))
    ceiling = envelope["context"]["max_input_tokens"]
    strict_overhead = envelope_tokens + reference_tokens(references)
    if runtime_name is None:
        optimized_overhead = strict_overhead
    else:
        brief = execution_brief(runtime_name, "balanced")
        brief_tokens = estimated_tokens(json.dumps(brief, sort_keys=True))
        brief_references = reference_tokens(list(brief.get("required_references", [])))
        optimized_overhead = brief_tokens + brief_references
    return {
        "envelope_tokens": envelope_tokens,
        "reference_tokens": reference_tokens(references),
        "strict_overhead_tokens": strict_overhead,
        "optimized_overhead_tokens": optimized_overhead,
        "ceiling_tokens": ceiling,
        "strict_overhead_percent": strict_overhead * 100 // ceiling,
        "optimized_overhead_percent": optimized_overhead * 100 // ceiling,
    }


class EnvelopeOverheadTest(unittest.TestCase):
    """Overhead is a fixed per-event tax; a regression here multiplies across every event."""

    envelope_metrics: ClassVar[dict[str, Any]] = {}

    def test_governance_overhead_stays_within_recorded_ceilings(self) -> None:
        budgets = json.loads(BUDGETS_PATH.read_text())
        self.assertEqual(budgets["schema_version"], 1)
        measured: dict[str, Any] = {}
        for command, positionals, runtime_name in MEASURED_COMMANDS:
            with self.subTest(command=command):
                metrics = measure(command, positionals, runtime_name)
                measured[command] = metrics
                allowed = budgets["commands"].get(command)
                self.assertIsNotNone(allowed, f"{command} has no recorded overhead budget")
                for field, ceiling in allowed.items():
                    self.assertLessEqual(
                        metrics[field],
                        ceiling,
                        f"{command}.{field} grew to {metrics[field]}, budget {ceiling}",
                    )
        worst = max(m["optimized_overhead_percent"] for m in measured.values())
        self.assertLessEqual(worst, budgets["max_optimized_overhead_percent"])
        type(self).envelope_metrics = {"commands": measured, "worst_optimized_percent": worst}

    def test_optimized_commands_actually_drop_the_reference_packet(self) -> None:
        """The brief path is the only thing keeping task dispatch overhead bounded."""
        brief = execution_brief("run-task", "balanced")
        self.assertEqual(brief["required_references"], [])
        self.assertIsNotNone(brief["runtime_card"])
        strict = execution_brief("run-task", "strict")
        self.assertTrue(strict["required_references"])


if __name__ == "__main__":
    unittest.main()
