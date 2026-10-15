from __future__ import annotations

import unittest
from collections.abc import Mapping, Sequence
from typing import Any
from unittest.mock import patch

from linear_spanks.domains import legacy_validation


class LegacyContractValidationTest(unittest.TestCase):
    def _validate(
        self,
        commands: object,
        *,
        transitions: object | None = None,
        issue_transitions: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        workflow = {"transitions": {} if transitions is None else transitions}

        def load(path: object) -> dict[str, Any]:
            if path == legacy_validation.COMMANDS_PATH:
                return {"commands": commands}
            return workflow

        with (
            patch.object(legacy_validation, "load_json", side_effect=load),
            patch.object(
                legacy_validation,
                "issue_workflow_contract",
                return_value={"transitions": dict(issue_transitions or {})},
            ),
            patch.object(legacy_validation, "human_verification_contract"),
            patch.object(legacy_validation, "milestone_review_contract"),
            patch.object(legacy_validation, "milestone_runtime_contract"),
            patch.object(legacy_validation, "execution_contract"),
            patch.object(legacy_validation, "execution_envelope"),
            patch.object(
                legacy_validation,
                "command_transitions",
                side_effect=lambda command: tuple(command.get("transitions", ())),
            ),
        ):
            return legacy_validation.validate_contracts()

    def test_valid_minimal_contract_is_accepted(self) -> None:
        result = self._validate([{"name": "demo", "access": "read"}])
        self.assertEqual(result, {"commands": 1, "status": "valid"})

    def test_top_level_shapes_are_required(self) -> None:
        with self.assertRaisesRegex(ValueError, "commands array"):
            self._validate({"name": "demo"})
        with self.assertRaisesRegex(ValueError, "requires transitions"):
            self._validate([], transitions=[])
        with self.assertRaisesRegex(ValueError, "every command must be an object"):
            self._validate(["demo"])

    def test_command_identity_access_and_transition_references_are_exact(self) -> None:
        cases: Sequence[tuple[list[object], str]] = (
            ([{"name": "", "access": "read"}], "invalid or duplicated command"),
            (
                [
                    {"name": "demo", "access": "read"},
                    {"name": "demo", "access": "read"},
                ],
                "invalid or duplicated command",
            ),
            ([{"name": "demo", "access": "execute"}], "invalid access"),
            (
                [{"name": "demo", "access": "read", "transitions": ["missing"]}],
                "unknown transition",
            ),
        )
        for commands, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                self._validate(commands)

    def test_issue_transition_references_and_coverage_are_bidirectional(self) -> None:
        command = {"name": "demo", "access": "write", "issue_transition": "start"}
        with self.assertRaisesRegex(ValueError, "unknown issue transition"):
            self._validate([command])
        with self.assertRaisesRegex(ValueError, "is not allowed"):
            self._validate(
                [command],
                issue_transitions={"start": {"commands": ["other"]}},
            )
        with self.assertRaisesRegex(ValueError, "coverage mismatch"):
            self._validate(
                [{"name": "demo", "access": "read"}],
                issue_transitions={"start": {"commands": ["demo"]}},
            )

        result = self._validate(
            [command],
            issue_transitions={"start": {"commands": ["demo"]}},
        )
        self.assertEqual(result["status"], "valid")


if __name__ == "__main__":
    unittest.main()
