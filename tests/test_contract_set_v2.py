from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

from tests.contract_support import SKILL, v1_runtime

from linear_spanks.contracts.compiler import compile_public_command
from linear_spanks.contracts.registry import (
    INDEX_PATH,
    get_contract_set,
    load_contract_set,
)
from linear_spanks.core.errors import FilesystemError, UsageError
from linear_spanks.core.types import ContractSet


class ContractSetTest(unittest.TestCase):
    def test_snapshot_is_cached_recursively_immutable_and_injectable(self) -> None:
        first = get_contract_set()
        second = get_contract_set()
        self.assertIs(first, second)

        registry = first.contract("command_registry")
        with self.assertRaises(TypeError):
            registry["version"] = "changed"  # type: ignore[index]
        display = registry["display"]
        with self.assertRaises(TypeError):
            display["commands"]["project"][0] = "changed"

        envelope = compile_public_command("task refine", ("ENG-1",), contract_set=first)
        self.assertEqual(envelope.command.path, "task refine")
        source = first.sources["execution"]
        self.assertEqual(source.path, "execution-contract.json")
        self.assertEqual(len(source.sha256), 64)
        with self.assertRaises(TypeError):
            first.sources["execution"] = source  # type: ignore[index]

    def test_v1_adapter_receives_an_isolated_mutable_copy(self) -> None:
        mutable = v1_runtime.load_json(v1_runtime.COMMANDS_PATH)
        mutable["commands"][0]["name"] = "changed-in-test"
        current = get_contract_set().contract("legacy_commands")
        self.assertNotEqual(current["commands"][0]["name"], "changed-in-test")

    def test_injected_contract_mappings_are_defensively_frozen(self) -> None:
        nested = [{"value": "original"}]
        source = {"example": MappingProxyType({"nested": (nested,)})}
        contract_set = ContractSet(
            schema_version=2,
            revision="test",
            root=Path("."),
            contracts=source,
            commands=(),
        )
        nested[0]["value"] = "mutated"
        self.assertEqual(
            contract_set.contract("example")["nested"][0][0]["value"],
            "original",
        )
        with self.assertRaises(TypeError):
            contract_set.contract("example")["nested"][0][0]["value"] = "blocked"

    def test_injected_contracts_reject_values_outside_strict_json(self) -> None:
        invalid_values = (
            {"set": {"mutable"}},
            {1: "non-text key"},
            {"number": float("inf")},
            {"text": "\ud800"},
        )
        for value in invalid_values:
            with (
                self.subTest(value_type=type(next(iter(value.values()))).__name__),
                self.assertRaises((UsageError, ValueError)),
            ):
                ContractSet(
                    schema_version=2,
                    revision="test",
                    root=Path("."),
                    contracts={"example": value},  # type: ignore[dict-item]
                    commands=(),
                )

    def test_injected_commands_and_modes_are_defensively_frozen_with_consistent_indexes(
        self,
    ) -> None:
        original = get_contract_set().by_path["milestone run"]
        profiles = list(original.profiles)
        transitions = list(original.transitions)
        legacy_names = list(original.legacy_names)
        loop_profiles = list(original.modes["loop"].profiles)
        loop_transitions = list(original.modes["loop"].transitions)
        modes = {
            "loop": replace(
                original.modes["loop"],
                profiles=loop_profiles,  # type: ignore[arg-type]
                transitions=loop_transitions,  # type: ignore[arg-type]
            )
        }
        commands = [
            replace(
                original,
                profiles=profiles,  # type: ignore[arg-type]
                transitions=transitions,  # type: ignore[arg-type]
                legacy_names=legacy_names,  # type: ignore[arg-type]
                modes=modes,
            )
        ]
        contract_set = ContractSet(
            schema_version=2,
            revision="test",
            root=Path("."),
            contracts={},
            commands=commands,  # type: ignore[arg-type]
        )
        commands.clear()
        modes.clear()
        profiles.clear()
        transitions.clear()
        legacy_names.clear()
        loop_profiles.clear()
        loop_transitions.clear()

        self.assertEqual(len(contract_set.commands), 1)
        self.assertIs(contract_set.commands[0], contract_set.by_path["milestone run"])
        self.assertIn("loop", contract_set.commands[0].modes)
        self.assertTrue(contract_set.commands[0].profiles)
        self.assertTrue(contract_set.commands[0].transitions)
        self.assertEqual(
            set(contract_set.commands[0].legacy_names),
            {"run-milestone", "run-milestone-loop"},
        )
        self.assertTrue(contract_set.commands[0].modes["loop"].profiles)
        with self.assertRaises(TypeError):
            contract_set.commands[0].modes["step"] = contract_set.commands[0].modes["loop"]  # type: ignore[index]

    def test_contract_index_detects_content_drift_before_parsing(self) -> None:
        index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            skill_root = Path(directory) / "linear-spanks"
            copied_index = skill_root / "contracts" / "contract-set.v2.json"
            copied_index.parent.mkdir(parents=True)
            copied_index.write_text(json.dumps(index), encoding="utf-8")
            for entry in index["contracts"].values():
                relative = Path(entry["path"])
                destination = skill_root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(SKILL / relative, destination)
            shutil.copytree(SKILL / "templates", skill_root / "templates")

            loaded = load_contract_set(copied_index)
            self.assertEqual(loaded.revision, index["revision"])

            registry_path = skill_root / index["contracts"]["command_registry"]["path"]
            registry_path.write_text("{}\n", encoding="utf-8")
            with self.assertRaises(FilesystemError) as caught:
                load_contract_set(copied_index)
        self.assertEqual(caught.exception.code, "CONTRACT_INTEGRITY_MISMATCH")


if __name__ == "__main__":
    unittest.main()
