"""Lock what the v2 public path actually tells an agent to read.

The contract suite historically asserted reference sets through the frozen v1 grammar in
``contract_support.run_contract``, so a v2 regression could not fail it. These tests compile
the shipping path directly.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from linear_spanks.contracts.compiler import compile_public_command, reachable_references
from linear_spanks.contracts.registry import get_contract_set
from linear_spanks.domains.documentation import READER_ONLY_DOCUMENTS

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "linear-spanks"
SNAPSHOT = ROOT / "tests" / "fixtures" / "v2-required-references.json"

# Commands whose usage requires more than a bare target.
ARGUMENTS: dict[str, tuple[str, ...]] = {
    "context budget": ("task", "ENG-42", "--tokens", "20000"),
    "context inspect": ("task", "ENG-42"),
    "runtime inspect": ("task", "ENG-42"),
    "verification policy-set": ("ENG-42", "--default", "enabled"),
    "verification fail": ("ENG-42", "--reason", "regression"),
    "milestone report-findings": ("ENG-42", "--session-id", "s1", "--finding", "f"),
    "project rollover": ("ENG-42", "--next-release", "r2"),
    "wave reconcile": ("ENG-42", "--wave", "w1"),
}


def compile_all() -> dict[str, list[str]]:
    contract_set = get_contract_set()
    compiled: dict[str, list[str]] = {}
    for command in contract_set.commands:
        arguments = ARGUMENTS.get(command.path, ("ENG-42",))
        envelope = compile_public_command(command.path, arguments, contract_set=contract_set)
        compiled[command.path] = list(envelope.contract["required_references"])
    return compiled


class V2ReferenceContractTest(unittest.TestCase):
    def test_every_registered_command_compiles_on_the_public_path(self) -> None:
        compiled = compile_all()
        self.assertEqual(len(compiled), len(get_contract_set().commands))

    def test_required_references_match_the_recorded_snapshot(self) -> None:
        expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        actual = compile_all()
        self.assertEqual(
            actual,
            expected,
            "required_references changed; review the diff and update the snapshot deliberately",
        )

    def test_governing_references_reach_the_commands_that_need_them(self) -> None:
        compiled = compile_all()
        contract_set = get_contract_set()
        execution = contract_set.contract("execution")["commands"]
        for command in contract_set.commands:
            references = compiled[command.path]
            configuration = execution.get(command.legacy_runtime_command) or {}
            with self.subTest(command=command.path):
                if configuration.get("orchestration") is not None:
                    self.assertIn("references/model-routing.md", references)
                    self.assertIn("references/task-workflow.md", references)
                if command.legacy_names and command.transitions:
                    self.assertIn("references/workflow-state.md", references)

    def test_core_policy_travels_as_a_bounded_slice_on_every_command(self) -> None:
        contract_set = get_contract_set()
        for command in contract_set.commands:
            arguments = ARGUMENTS.get(command.path, ("ENG-42",))
            envelope = compile_public_command(command.path, arguments, contract_set=contract_set)
            slices = {
                policy["name"]: policy["policy_slice"]
                for policy in envelope.contract["policy_contracts"]
            }
            with self.subTest(command=command.path):
                self.assertIn("core_policy", slices)
                self.assertIn("project_resolution", slices["core_policy"])

    def test_declared_postconditions_carry_their_definitions(self) -> None:
        """The envelope states postconditions as tokens; opaque tokens are not guidance."""

        contract_set = get_contract_set()
        definitions = contract_set.contract("core_policy")["postcondition_definitions"]
        for command in contract_set.commands:
            arguments = ARGUMENTS.get(command.path, ("ENG-42",))
            envelope = compile_public_command(command.path, arguments, contract_set=contract_set)
            declared = set(envelope.contract["postconditions"])
            core = next(
                policy["policy_slice"]
                for policy in envelope.contract["policy_contracts"]
                if policy["name"] == "core_policy"
            )
            supplied = set(core.get("postcondition_definitions", {}))
            with self.subTest(command=command.path):
                self.assertEqual(supplied, declared & set(definitions))

    def test_ripwire_only_reaches_commands_that_resolve_a_repository(self) -> None:
        compiled = compile_all()
        execution = get_contract_set().contract("execution")["commands"]
        for command in get_contract_set().commands:
            references = compiled[command.path]
            configuration = execution.get(command.legacy_runtime_command) or {}
            resolves = (
                configuration.get("repository_scan") is not None
                or configuration.get("orchestration") is not None
                or "references/project-orchestration.md" in references
                or "references/milestone-orchestration.md" in references
            )
            with self.subTest(command=command.path):
                self.assertEqual("references/ripwire.md" in references, resolves)

    def test_no_document_is_unreachable_from_every_compiled_command(self) -> None:
        reached = reachable_references()
        on_disk = {
            f"{folder}/{path.name}"
            for folder in ("references", "templates")
            for path in (SKILL / folder).glob("*.md")
        }
        self.assertEqual(sorted(on_disk - reached - READER_ONLY_DOCUMENTS), [])
        self.assertEqual(sorted(reached - on_disk), [])


if __name__ == "__main__":
    unittest.main()


class RepositoryEvidenceDetectorTest(unittest.TestCase):
    """Skill selection decides which guidance loads, so its inputs must be observed."""

    def detect(self, files: list[str], dependencies: list[str] | None = None) -> dict:
        from linear_spanks.domains.context import detect_repository_evidence

        return detect_repository_evidence({"files": files, "dependencies": dependencies or []})

    def test_technologies_are_proven_by_named_files(self) -> None:
        result = self.detect(["pyproject.toml", "src/app.py", "go.mod"])
        self.assertEqual(result["technologies"], ["go", "python"])
        self.assertIn("pyproject.toml", result["provenance"]["python"])
        self.assertIn("go.mod", result["provenance"]["go"])

    def test_declared_dependencies_prove_a_technology_without_a_manifest_name(self) -> None:
        result = self.detect(["src/index.js"], ["react"])
        self.assertIn("react", result["technologies"])
        self.assertEqual(result["provenance"]["react"], ["dependency:react"])

    def test_ui_and_coverage_are_derived_but_task_tags_are_not(self) -> None:
        result = self.detect(["web/App.tsx", "tests/test_app.py"])
        self.assertEqual(result["evidence"], ["coverage-required", "ui"])
        for tag in ("observed-failure", "refactoring", "security-sensitive"):
            self.assertNotIn(tag, result["evidence"])
            self.assertIn(tag, result["task_supplied"])

    def test_a_backend_only_repository_reports_no_ui(self) -> None:
        result = self.detect(["pyproject.toml", "src/service.py"])
        self.assertEqual(result["technologies"], ["python"])
        self.assertNotIn("ui", result["evidence"])

    def test_detection_is_deterministic_and_bound(self) -> None:
        files = ["pyproject.toml", "src/app.py"]
        reversed_files = list(reversed(files))
        self.assertEqual(self.detect(files)["binding"], self.detect(reversed_files)["binding"])

    def test_detected_tags_drive_selection_and_an_override_still_wins(self) -> None:
        from linear_spanks.domains.context import detect_repository_evidence, select_skills

        catalog = json.loads((SKILL / "skill-selection-catalog.json").read_text(encoding="utf-8"))
        detected = detect_repository_evidence(
            {"files": ["pyproject.toml", "src/app.py"], "dependencies": []}
        )
        selection = select_skills(
            {
                "catalog": catalog["catalog"],
                "role": "executor",
                "phase": "implementation",
                "technologies": detected["technologies"],
                "evidence": detected["evidence"],
            }
        )
        names = {entry["name"] for entry in selection["selected"]}
        self.assertIn("tech-python", names)
        self.assertNotIn("tech-react", names)
        self.assertNotIn("exec-accessibility", names)

        # an explicit caller decision still outranks the detector's default
        widened = select_skills(
            {
                "catalog": catalog["catalog"],
                "role": "executor",
                "phase": "implementation",
                "technologies": detected["technologies"],
                "evidence": [*detected["evidence"], "ui"],
            }
        )
        self.assertIn("exec-accessibility", {entry["name"] for entry in widened["selected"]})

    def test_invalid_inventory_is_rejected(self) -> None:
        from linear_spanks.core.errors import UsageError
        from linear_spanks.domains.context import detect_repository_evidence

        with self.assertRaises(UsageError) as caught:
            detect_repository_evidence({"files": "pyproject.toml"})
        self.assertEqual(caught.exception.code, "INVALID_REPOSITORY_INVENTORY")
