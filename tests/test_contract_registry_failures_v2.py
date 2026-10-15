from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

from linear_spanks.contracts.compiler import compile_public_command
from linear_spanks.contracts.registry import (
    _command_spec,
    _ordered_command_specs,
    _read_contract,
    get_contract_set,
    load_contract_set,
    validate_contract_set,
)
from linear_spanks.core.errors import FilesystemError, UsageError
from linear_spanks.core.jsonio import mutable_json_copy
from linear_spanks.core.types import CommandModeSpec, ContractSet


class ContractRegistryFailureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        selected = get_contract_set()
        cls.registry = mutable_json_copy(selected.contract("command_registry"))
        cls.command = copy.deepcopy(cls.registry["commands"][0])

    def assert_invalid_command(self, value: Any) -> None:
        with self.assertRaises(UsageError) as caught:
            _command_spec(value)
        self.assertIn(
            caught.exception.code,
            {"INVALID_COMMAND_REGISTRY", "INVALID_CONTRACT_SET"},
        )

    def test_command_specs_reject_every_malformed_typed_field(self) -> None:
        self.assert_invalid_command(None)
        mutations: list[tuple[str, Any]] = [
            ("path", ["task"]),
            ("path", ["unknown", "run"]),
            ("tier", "hidden"),
            ("access", "delete"),
            ("approval", None),
            ("summary", ""),
            ("usage", 1),
            ("legacy_runtime_command", ""),
            ("template", 1),
            ("profiles", None),
            ("transitions", None),
            ("legacy_names", None),
            ("modes", []),
        ]
        for field, value in mutations:
            with self.subTest(field=field, value=value):
                candidate = copy.deepcopy(self.command)
                candidate[field] = value
                self.assert_invalid_command(candidate)
        candidate = copy.deepcopy(self.command)
        candidate["unknown"] = True
        self.assert_invalid_command(candidate)

        milestone = next(
            copy.deepcopy(command)
            for command in self.registry["commands"]
            if command["path"] == ["milestone", "run"]
        )
        for modes in (
            {"unknown": {}},
            {"loop": []},
            {"loop": {}},
            {
                "loop": {
                    "approval": "approved",
                    "summary": "summary",
                    "usage": "usage",
                    "template": 1,
                    "profiles": [],
                    "transitions": [],
                    "unknown": True,
                }
            },
            {
                "loop": {
                    "approval": "approved",
                    "summary": "summary",
                    "usage": "usage",
                    "template": None,
                    "profiles": None,
                    "transitions": [],
                }
            },
        ):
            with self.subTest(modes=modes):
                candidate = copy.deepcopy(milestone)
                candidate["modes"] = modes
                self.assert_invalid_command(candidate)

    def test_display_order_rejects_duplicates_gaps_and_tier_inversions(self) -> None:
        commands = copy.deepcopy(self.registry["commands"])
        self.assertEqual(len(_ordered_command_specs(self.registry, commands)), len(commands))

        for field, value in (
            ("version", "changed"),
            ("default_format", "xml"),
            ("schema_version", 2.0),
        ):
            malformed_metadata = copy.deepcopy(self.registry)
            malformed_metadata[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(UsageError):
                _ordered_command_specs(malformed_metadata, commands)
        unknown_metadata = copy.deepcopy(self.registry)
        unknown_metadata["unknown"] = True
        with self.assertRaises(UsageError):
            _ordered_command_specs(unknown_metadata, commands)

        duplicate = copy.deepcopy(commands)
        duplicate.append(copy.deepcopy(duplicate[0]))
        with self.assertRaises(UsageError):
            _ordered_command_specs(self.registry, duplicate)

        no_display = copy.deepcopy(self.registry)
        no_display["display"] = None
        with self.assertRaises(UsageError):
            _ordered_command_specs(no_display, commands)

        invalid_namespaces = copy.deepcopy(self.registry)
        invalid_namespaces["display"]["namespace_order"] = ["task"]
        with self.assertRaises(UsageError):
            _ordered_command_specs(invalid_namespaces, commands)

        invalid_names = copy.deepcopy(self.registry)
        invalid_names["display"]["commands"]["task"] = [""]
        with self.assertRaises(UsageError):
            _ordered_command_specs(invalid_names, commands)

        missing = copy.deepcopy(self.registry)
        missing["display"]["commands"]["task"][0] = "missing"
        with self.assertRaises(UsageError):
            _ordered_command_specs(missing, commands)

        inverted = copy.deepcopy(self.registry)
        task_names = inverted["display"]["commands"]["task"]
        core_index = next(
            index
            for index, name in enumerate(task_names)
            if next(command for command in commands if command["path"] == ["task", name])["tier"]
            == "core"
        )
        advanced_index = next(
            index
            for index, name in enumerate(task_names)
            if next(command for command in commands if command["path"] == ["task", name])["tier"]
            == "advanced"
        )
        task_names[core_index], task_names[advanced_index] = (
            task_names[advanced_index],
            task_names[core_index],
        )
        with self.assertRaises(UsageError):
            _ordered_command_specs(inverted, commands)

        uncovered = copy.deepcopy(self.registry)
        uncovered["display"]["commands"]["task"].pop()
        with self.assertRaises(UsageError):
            _ordered_command_specs(uncovered, commands)

    def test_legacy_replacements_exactly_cover_registered_legacy_names(self) -> None:
        commands = copy.deepcopy(self.registry["commands"])
        malformed = copy.deepcopy(self.registry)
        malformed["legacy_replacements"] = []
        with self.assertRaises(UsageError):
            _ordered_command_specs(malformed, commands)

        missing = copy.deepcopy(self.registry)
        missing["legacy_replacements"].pop("analyze-codebase")
        with self.assertRaises(UsageError):
            _ordered_command_specs(missing, commands)

        wrong = copy.deepcopy(self.registry)
        wrong["legacy_replacements"]["analyze-codebase"] = "codebase import"
        with self.assertRaises(UsageError):
            _ordered_command_specs(wrong, commands)

        swapped_modes = copy.deepcopy(self.registry)
        swapped_modes["legacy_replacements"]["run-milestone"] = "milestone run --mode loop"
        with self.assertRaises(UsageError):
            _ordered_command_specs(swapped_modes, commands)

    def test_contract_index_and_filesystem_errors_are_structured(self) -> None:
        with self.assertRaises(FilesystemError) as missing:
            _read_contract(Path("/definitely/missing/linear-spanks-contract.json"), "0" * 64)
        self.assertEqual(missing.exception.code, "CONTRACT_READ_FAILED")

        base = {
            "schema_version": 2,
            "version": "2.0.0",
            "revision": "test",
            "contracts": {},
            "artifact_integrity": {
                "algorithm": "sha256",
                "canonicalization": "json-sort-keys-utf8-v1",
                "future_version_policy": "reject",
                "migration_policy": "authorized-write-only",
            },
        }
        invalid_indexes = (
            {**base, "schema_version": 1},
            {**base, "schema_version": 2.0},
            {**base, "version": "99.0.0"},
            {**base, "revision": ""},
            {**base, "revision": " untrimmed"},
            {**base, "unknown": True},
            {
                **base,
                "artifact_integrity": {
                    **base["artifact_integrity"],
                    "future_version_policy": "accept",
                },
            },
            {
                **base,
                "artifact_integrity": {
                    **base["artifact_integrity"],
                    "migration_policy": "implicit",
                },
            },
            base,
            {
                **base,
                "contracts": {
                    "bad": {"path": "../outside.json", "sha256": "0" * 64, "schema_versions": [1]}
                },
            },
            {
                **base,
                "contracts": {
                    "bad": {"path": "value.json", "sha256": "short", "schema_versions": [1]}
                },
            },
            {
                **base,
                "contracts": {
                    "bad": {
                        "path": "value.json",
                        "sha256": "0" * 64,
                        "schema_versions": [1],
                        "unknown": True,
                    }
                },
            },
            {
                **base,
                "contracts": {
                    "bad": {"path": "value.json", "sha256": "0" * 64, "schema_versions": []}
                },
            },
            {
                **base,
                "contracts": {
                    "bad": {
                        "path": "value.json",
                        "sha256": "0" * 64,
                        "schema_versions": [True],
                    }
                },
            },
        )
        with tempfile.TemporaryDirectory() as directory:
            index_path = Path(directory) / "skill" / "contracts" / "contract-set.v2.json"
            index_path.parent.mkdir(parents=True)
            for index in invalid_indexes:
                with self.subTest(index=index):
                    index_path.write_text(json.dumps(index), encoding="utf-8")
                    with self.assertRaises(UsageError):
                        load_contract_set(index_path)

            root = index_path.parent.parent
            document = root / "value.json"
            document.write_text('{"schema_version": 2}\n', encoding="utf-8")
            digest = hashlib.sha256(document.read_bytes()).hexdigest()
            index_path.write_text(
                json.dumps(
                    {
                        **base,
                        "contracts": {
                            "command_registry": {
                                "path": "value.json",
                                "sha256": digest,
                                "schema_versions": [1],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(UsageError) as unsupported:
                load_contract_set(index_path)
            self.assertIn("Unsupported schema version", unsupported.exception.message)

    def test_cross_contract_validation_rejects_malformed_references(self) -> None:
        selected = get_contract_set()
        documents = {
            name: mutable_json_copy(document) for name, document in selected.contracts.items()
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def contract_set(
                *, contracts: dict[str, dict[str, Any]], commands: tuple[Any, ...]
            ) -> ContractSet:
                return ContractSet(
                    schema_version=2,
                    revision="test",
                    root=root,
                    contracts=contracts,
                    commands=commands,
                    sources=selected.sources,
                )

            malformed = copy.deepcopy(documents)
            malformed["legacy_commands"]["commands"] = "invalid"
            with self.assertRaises(UsageError):
                validate_contract_set(contract_set(contracts=malformed, commands=()))

            malformed = copy.deepcopy(documents)
            malformed["workflow"]["transitions"] = []
            with self.assertRaises(UsageError):
                validate_contract_set(contract_set(contracts=malformed, commands=()))

            command = selected.commands[0]
            bare_command = replace(command, template=None)
            missing_legacy = replace(command, legacy_names=("missing-command",))
            with self.assertRaises(UsageError):
                validate_contract_set(contract_set(contracts=documents, commands=(missing_legacy,)))

            missing_template = replace(command, template="missing-template.md")
            with self.assertRaises(FilesystemError):
                validate_contract_set(
                    contract_set(contracts=documents, commands=(missing_template,))
                )

            missing_transition = replace(bare_command, transitions=("missing-transition",))
            with self.assertRaises(UsageError):
                validate_contract_set(
                    contract_set(contracts=documents, commands=(missing_transition,))
                )

            mode = CommandModeSpec(
                approval="preview",
                profiles=(),
                template=None,
                transitions=(),
                summary="summary",
                usage="usage",
            )
            invalid_mode_owner = replace(bare_command, modes=MappingProxyType({"loop": mode}))
            with self.assertRaises(UsageError):
                validate_contract_set(
                    contract_set(contracts=documents, commands=(invalid_mode_owner,))
                )

    def test_semantic_safety_policies_cannot_be_weakened_in_an_injected_set(self) -> None:
        selected = get_contract_set()
        mutations: tuple[tuple[str, tuple[str, ...], Any], ...] = (
            ("issue_workflow", ("statuses", "human_draft"), "Draft"),
            (
                "human_verification",
                ("lifecycle", "requires_linear_completion_readback"),
                False,
            ),
            ("milestone_review", ("session_boundary",), "unbounded"),
            ("milestone_runtime", ("storage", "preferred"), "managed-comment"),
            ("routing", ("roles",), ["executor", "planner", "reviewer"]),
            ("repository_scan", ("security", "follow_symlinks"), True),
            ("project_epoch", ("capsule", "max_body_bytes"), 1),
            ("parallel_execution", ("waves", "assurance"), "fast"),
            (
                "project_orchestration",
                ("task_loop", "no_automatic_stronger_model_retry"),
                False,
            ),
            (
                "milestone_orchestration",
                ("supervisor", "fresh_session_per_event"),
                False,
            ),
            (
                "execution",
                ("context_profiles", "task", "max_input_tokens"),
                0,
            ),
        )
        for contract_name, path, value in mutations:
            with self.subTest(contract=contract_name, path=path):
                documents = {
                    name: mutable_json_copy(document)
                    for name, document in selected.contracts.items()
                }
                target: dict[str, Any] = documents[contract_name]
                for field in path[:-1]:
                    target = target[field]
                target[path[-1]] = value
                injected = ContractSet(
                    schema_version=2,
                    revision="unsafe-test",
                    root=selected.root,
                    contracts=documents,
                    commands=selected.commands,
                )
                with self.assertRaises(UsageError) as caught:
                    validate_contract_set(injected)
                self.assertEqual(caught.exception.code, "INVALID_CONTRACT_SET")

    def test_injected_registry_cannot_diverge_from_characterized_execution(self) -> None:
        selected = get_contract_set()
        mutations: tuple[tuple[tuple[str, str], tuple[str, ...], Any], ...] = (
            (("milestone", "status"), ("access",), "write"),
            (("task", "run"), ("approval",), "none"),
            (("task", "run"), ("template",), None),
            (("task", "run"), ("transitions",), []),
            (("task", "run"), ("profiles",), ["read_report", "lifecycle"]),
            (("task", "run"), ("legacy_runtime_command",), "next-task"),
            (("milestone", "run"), ("modes", "loop", "approval"), "none"),
            (("milestone", "run"), ("modes", "loop", "profiles"), []),
        )
        for command_path, field_path, value in mutations:
            with self.subTest(command=command_path, field=field_path):
                documents = {
                    name: mutable_json_copy(document)
                    for name, document in selected.contracts.items()
                }
                registry = documents["command_registry"]
                raw_command = next(
                    command
                    for command in registry["commands"]
                    if command["path"] == list(command_path)
                )
                target = raw_command
                for field in field_path[:-1]:
                    target = target[field]
                target[field_path[-1]] = value
                parsed = _ordered_command_specs(registry, registry["commands"])
                injected = ContractSet(
                    schema_version=2,
                    revision="unsafe-registry-test",
                    root=selected.root,
                    contracts=documents,
                    commands=parsed,
                    sources=selected.sources,
                )
                with self.assertRaises(UsageError) as caught:
                    validate_contract_set(injected)
                self.assertEqual(caught.exception.code, "INVALID_COMMAND_REGISTRY")
                with self.assertRaises(UsageError):
                    compile_public_command(
                        f"{command_path[0]} {command_path[1]}",
                        ("target-1",),
                        contract_set=injected,
                    )

        status = selected.by_path["milestone status"]
        inconsistent = replace(status, access="write")
        typed_drift = ContractSet(
            schema_version=2,
            revision="typed-drift-test",
            root=selected.root,
            contracts=selected.contracts,
            commands=tuple(
                inconsistent if command.path == status.path else command
                for command in selected.commands
            ),
            sources=selected.sources,
        )
        with self.assertRaises(UsageError) as typed_error:
            validate_contract_set(typed_drift)
        self.assertEqual(typed_error.exception.code, "INVALID_COMMAND_REGISTRY")

    def test_every_contract_schema_version_rejects_boolean_values(self) -> None:
        selected = get_contract_set()
        for contract_name in selected.contracts:
            with self.subTest(contract=contract_name):
                documents = {
                    name: mutable_json_copy(document)
                    for name, document in selected.contracts.items()
                }
                documents[contract_name]["schema_version"] = True
                injected = ContractSet(
                    schema_version=2,
                    revision="boolean-schema-test",
                    root=selected.root,
                    contracts=documents,
                    commands=selected.commands,
                    sources=selected.sources,
                )
                with self.assertRaises(UsageError) as caught:
                    validate_contract_set(injected)
                self.assertEqual(caught.exception.code, "INVALID_CONTRACT_SET")

    def test_injected_contract_set_metadata_is_complete_and_typed(self) -> None:
        selected = get_contract_set()
        candidates = (
            replace(selected, schema_version=999),
            replace(selected, revision=""),
            replace(selected, revision=" untrimmed"),
            replace(selected, sources={}),
            replace(
                selected,
                sources={
                    name: replace(source, sha256="not-a-digest") if name == "execution" else source
                    for name, source in selected.sources.items()
                },
            ),
        )
        for candidate in candidates:
            with self.subTest(candidate=candidate), self.assertRaises(UsageError) as caught:
                validate_contract_set(candidate)
            self.assertEqual(caught.exception.code, "INVALID_CONTRACT_SET")

        for field, value in (
            ("version", "9.0.0"),
            ("default_format", "xml"),
            ("unknown", True),
        ):
            documents = {
                name: mutable_json_copy(document) for name, document in selected.contracts.items()
            }
            documents["command_registry"][field] = value
            injected = ContractSet(
                schema_version=2,
                revision="registry-metadata-injection",
                root=selected.root,
                contracts=documents,
                commands=selected.commands,
                sources=selected.sources,
            )
            with self.subTest(field=field), self.assertRaises(UsageError) as caught:
                validate_contract_set(injected)
            self.assertEqual(caught.exception.code, "INVALID_COMMAND_REGISTRY")


if __name__ == "__main__":
    unittest.main()
