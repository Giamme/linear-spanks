from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.contract_support import (
    ROOT,
    SCRIPTS,
    dependency_graph_source_fixture,
    state_marker_fixture,
)

from linear_spanks.cli import app
from linear_spanks.contracts.compiler import compile_public_command
from linear_spanks.contracts.registry import get_contract_set, validate_contract_set
from linear_spanks.core.errors import UsageError
from linear_spanks.core.hashing import sha256_digest

CLI = SCRIPTS / "linear_spanks_cli.py"
LEGACY_CLI = SCRIPTS / "workflow_contract.py"


def run_cli(*arguments: str, stdin_text: str = "") -> tuple[int, str]:
    output = io.StringIO()
    exit_code = app.run(arguments, stdin=io.StringIO(stdin_text), stdout=output)
    return exit_code, output.getvalue()


class NamespacedCliTest(unittest.TestCase):
    def test_output_stream_and_renderer_failures_stay_inside_the_cli_boundary(self) -> None:
        class BrokenWriter(io.StringIO):
            def write(self, value: str) -> int:
                del value
                raise BrokenPipeError("closed pipe")

        self.assertEqual(
            app.run(("help",), stdin=io.StringIO(), stdout=BrokenWriter()),
            1,
        )

        output = io.StringIO()
        actual_render = app.render_json
        render_calls = 0

        def fail_once(result: object) -> str:
            nonlocal render_calls
            render_calls += 1
            if render_calls == 1:
                raise RuntimeError("renderer failed")
            return actual_render(result)  # type: ignore[arg-type]

        with patch.object(app, "render_json", side_effect=fail_once):
            exit_code = app.run(("help",), stdin=io.StringIO(), stdout=output)
        self.assertEqual(exit_code, 1)
        self.assertEqual(json.loads(output.getvalue())["error"]["code"], "INTERNAL_ERROR")

    def test_public_text_arguments_reject_empty_or_untrimmed_values(self) -> None:
        cases = (
            ("task", "run", ""),
            ("task", "run", "   "),
            ("task", "run", " ENG-1"),
            ("verification", "fail", "M-1", "--reason", "   "),
            ("project", "rollover", "P-1", "--next-release", "  "),
            (
                "milestone",
                "report-findings",
                "M-1",
                "--session-id",
                " ",
                "--finding",
                " ",
            ),
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                exit_code, output = run_cli(*arguments)
                self.assertEqual(exit_code, 2, output)
                error = json.loads(output)["error"]
                self.assertIn(
                    error["code"],
                    {"INVALID_POSITIONAL_VALUE", "INVALID_OPTION_VALUE"},
                )

    def test_default_and_advanced_discovery_match_the_registry(self) -> None:
        exit_code, output = run_cli("help")
        self.assertEqual(exit_code, 0)
        envelope = json.loads(output)
        self.assertEqual(
            envelope,
            {
                "schema_version": 2,
                "command": "help",
                "ok": True,
                "result": {
                    "version": "2.0.0",
                    "default_format": "json",
                    "namespaces": {
                        "codebase": ["analyze", "import"],
                        "project": ["create", "review", "run"],
                        "milestone": [
                            "clarify",
                            "design",
                            "create-tasks",
                            "plan",
                            "review",
                            "run",
                            "status",
                            "verify",
                            "wrap",
                        ],
                        "task": ["refine", "plan", "next", "run"],
                    },
                    "advanced_included": False,
                    "hint": "help --advanced",
                },
                "warnings": [],
            },
        )

        advanced_code, advanced_output = run_cli("help", "--advanced")
        self.assertEqual(advanced_code, 0)
        advanced = json.loads(advanced_output)["result"]
        self.assertTrue(advanced["advanced_included"])
        discovered = {
            f"{namespace} {name}"
            for namespace, names in advanced["namespaces"].items()
            for name in names
        }
        self.assertEqual(discovered, set(get_contract_set().by_path))

    def test_contract_set_and_every_legacy_replacement_are_complete(self) -> None:
        validation = validate_contract_set()
        self.assertEqual(validation["commands"], 59)
        registry = get_contract_set().contract("command_registry")
        replacements = registry["legacy_replacements"]
        self.assertEqual(len(replacements), 55)
        for legacy, replacement in replacements.items():
            with self.subTest(legacy=legacy):
                exit_code, output = run_cli(str(legacy))
                self.assertEqual(exit_code, 2)
                envelope = json.loads(output)
                self.assertEqual(envelope["command"], legacy)
                self.assertFalse(envelope["ok"])
                self.assertEqual(envelope["error"]["code"], "LEGACY_COMMAND_REMOVED")
                self.assertEqual(envelope["error"]["details"]["replacement"], replacement)

        loop_code, loop_output = run_cli("run-milestone", "milestone-1", "--autopilot")
        self.assertEqual(loop_code, 2)
        loop_error = json.loads(loop_output)["error"]
        self.assertEqual(loop_error["code"], "LEGACY_COMMAND_REMOVED")
        self.assertEqual(loop_error["details"]["replacement"], "milestone run --mode loop")

    def test_milestone_run_compiles_step_and_loop_modes(self) -> None:
        step = compile_public_command("milestone run", ("milestone-1",))
        explicit_step = compile_public_command("milestone run", ("milestone-1", "--mode", "step"))
        loop = compile_public_command(
            "milestone run", ("milestone-1", "--mode", "loop", "--max-events", "4")
        )
        self.assertEqual(step.contract["schema_version"], 2)
        self.assertNotIn("contract_version", step.contract)
        self.assertEqual(step.contract["command"]["path"], "milestone run")
        self.assertEqual(step.contract["mode"], "step")
        self.assertEqual(explicit_step.contract["mode"], "step")
        self.assertEqual(loop.contract["command"]["path"], "milestone run")
        self.assertEqual(loop.contract["mode"], "loop")
        self.assertEqual(step.contract["command"]["template"], "milestone-spec.md")
        self.assertEqual(
            loop.contract["command"]["template"],
            "milestone-orchestration-receipt.md",
        )
        self.assertEqual(loop.contract["command"]["transitions"], [])
        self.assertEqual(
            loop.contract["command"]["profiles"],
            ["staged_milestone_orchestration", "milestone", "planning"],
        )
        self.assertEqual(
            loop.contract["command"]["approval"],
            "invocation covers guarded automatic operations inside the bound milestone policy; "
            "material change, integration, model selection, merge, and push remain gated",
        )
        self.assertIn(
            "templates/milestone-orchestration-receipt.md",
            loop.contract["required_references"],
        )
        execution = get_contract_set().contract("execution")
        loop_configuration = execution["commands"]["run-milestone-loop"]
        loop_profile = execution["execution_profiles"][loop_configuration["execution"]]
        for field in ("reads", "writes", "postconditions"):
            expected = list(
                dict.fromkeys([*loop_profile[field], *loop_configuration.get(field, [])])
            )
            self.assertEqual(loop.contract[field], expected)

        with self.assertRaises(UsageError) as caught:
            compile_public_command("milestone run", ("milestone-1", "--max-events", "4"))
        self.assertEqual(caught.exception.code, "LOOP_OPTION_REQUIRES_LOOP_MODE")
        with self.assertRaises(UsageError) as invalid:
            compile_public_command("milestone run", ("milestone-1", "--mode", "forever"))
        self.assertEqual(invalid.exception.code, "INVALID_MODE")
        with self.assertRaises(UsageError) as legacy:
            compile_public_command("milestone run", ("milestone-1", "--autopilot"))
        self.assertEqual(legacy.exception.code, "LEGACY_OPTION_REMOVED")
        self.assertEqual(legacy.exception.details["replacement"], "--mode loop")
        accepted_ceiling = compile_public_command(
            "milestone run",
            ("milestone-1", "--mode", "loop", "--max-events", "100"),
        )
        self.assertEqual(accepted_ceiling.contract["invocation"]["options"]["max_events"], "100")
        with self.assertRaises(UsageError) as ceiling:
            compile_public_command(
                "milestone run",
                ("milestone-1", "--mode", "loop", "--max-events", "101"),
            )
        self.assertEqual(ceiling.exception.code, "INVALID_OPTION_VALUE")
        normalized_until = compile_public_command(
            "milestone run",
            (
                "milestone-1",
                "--mode",
                "loop",
                "--until",
                "milestone-done,approval-required",
            ),
        )
        self.assertEqual(
            normalized_until.contract["invocation"]["options"]["until"],
            "approval-required,milestone-done",
        )
        for value in ("nonsense", "blocked,blocked", "blocked,"):
            with self.subTest(until=value), self.assertRaises(UsageError) as invalid_until:
                compile_public_command(
                    "milestone run",
                    ("milestone-1", "--mode", "loop", "--until", value),
                )
            self.assertEqual(invalid_until.exception.code, "INVALID_OPTION_VALUE")

        loop_isolation = compile_public_command(
            "milestone run",
            ("milestone-1", "--mode", "loop", "--isolated-worktree"),
        ).contract["isolation"]
        self.assertEqual(loop_isolation["mode"], "always")
        self.assertEqual(loop_isolation["status"], "idempotent-assertion")
        self.assertEqual(
            loop_isolation["orchestration_policy"]["name"],
            "milestone_orchestration",
        )

    def test_milestone_run_result_metadata_matches_the_resolved_mode(self) -> None:
        for mode in ("step", "loop"):
            with self.subTest(mode=mode):
                exit_code, output = run_cli("milestone", "run", "milestone-1", "--mode", mode)
                self.assertEqual(exit_code, 0, output)
                result = json.loads(output)["result"]
                resolved = result["execution"]["command"]
                for field in (
                    "path",
                    "tier",
                    "access",
                    "approval",
                    "profiles",
                    "template",
                    "transitions",
                ):
                    self.assertEqual(result[field], resolved[field])
        self.assertEqual(result["template"], "milestone-orchestration-receipt.md")
        self.assertEqual(result["transitions"], [])

    def test_assurance_has_one_canonical_authority(self) -> None:
        argument = compile_public_command("task run", ("ENG-1", "--assurance=strict"))
        explicit = compile_public_command("task run", ("ENG-1",), assurance="strict")
        agreed = compile_public_command(
            "task run", ("ENG-1", "--assurance", "strict"), assurance="strict"
        )
        self.assertEqual(argument.contract["assurance"], explicit.contract["assurance"])
        self.assertEqual(agreed.assurance, "strict")
        with self.assertRaises(UsageError) as caught:
            compile_public_command("task run", ("ENG-1", "--assurance", "strict"), assurance="fast")
        self.assertEqual(caught.exception.code, "ASSURANCE_CONFLICT")

    def test_policy_sources_and_optional_isolation_are_complete(self) -> None:
        envelope = compile_public_command("task run", ("ENG-1", "--isolated-worktree")).contract
        references = envelope["required_references"]
        # staged-scan and import-synthesis guidance stays with the codebase namespace
        self.assertIn("references/repository-scan.md", references)
        self.assertNotIn("references/codebase-analysis.md", references)
        self.assertIn("references/parallel-execution.md", references)
        self.assertIn("templates/isolation-receipt.md", references)
        self.assertIn("durable_isolation_receipt", envelope["writes"])
        self.assertIn("verified_parent_fast_forward", envelope["writes"])
        self.assertIn("exact_integration_preview_approved", envelope["postconditions"])
        self.assertEqual(
            envelope["isolation"]["governance"]["merge_strategy"],
            "merge-commit-no-ff",
        )
        for policy in envelope["policy_contracts"]:
            self.assertIn("path", policy)
            self.assertIn("sha256", policy)
            self.assertIn("contract_schema_version", policy)
            self.assertNotIn("schema_version", policy)
            self.assertNotIn(policy["path"], envelope["required_references"])
            self.assertIn("policy_slice", policy)
            self.assertEqual(policy["policy_slice_sha256"], sha256_digest(policy["policy_slice"]))
            source = get_contract_set().root / policy["path"]
            self.assertTrue(source.is_file())
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), policy["sha256"])

    def test_compiled_references_leave_context_budget_for_target_evidence(self) -> None:
        cases = (
            ("task run", ("ENG-1",)),
            ("task run", ("ENG-1", "--isolated-worktree")),
            ("project run", ("project-1",)),
            ("milestone run", ("milestone-1", "--mode", "loop")),
        )
        root = get_contract_set().root
        for path, arguments in cases:
            with self.subTest(path=path, arguments=arguments):
                contract = compile_public_command(path, arguments).contract
                reference_bytes = sum(
                    (root / reference).stat().st_size
                    for reference in contract["required_references"]
                )
                self.assertLessEqual(
                    reference_bytes,
                    int(contract["context"]["max_input_tokens"] * 3),
                )

    def test_json_and_text_formats_are_stable(self) -> None:
        exit_code, output = run_cli("project", "review", "project-1")
        self.assertEqual(exit_code, 0)
        envelope = json.loads(output)
        self.assertEqual(set(envelope), {"schema_version", "command", "ok", "result", "warnings"})
        self.assertEqual(envelope["command"], "project review")
        self.assertTrue(envelope["ok"])

    def test_public_argument_grammar_rejects_missing_targets_unknown_flags_and_bad_values(
        self,
    ) -> None:
        cases = (
            (("project", "create"), "MISSING_TARGET"),
            (("task", "run", "ENG-1", "--nonsense"), "UNKNOWN_OPTION"),
            (("project", "run", "project-1", "--max-parallel", "9"), "INVALID_OPTION_VALUE"),
            (("project", "rollover", "project-1"), "MISSING_REQUIRED_OPTION"),
            (("verification", "policy-set", "project-1"), "INVALID_POLICY_SELECTION"),
            (
                ("verification", "policy-set", "project-1", "--default", "maybe"),
                "INVALID_OPTION_VALUE",
            ),
        )
        for arguments, expected_code in cases:
            with self.subTest(arguments=arguments):
                exit_code, output = run_cli(*arguments)
                self.assertEqual(exit_code, 2)
                envelope = json.loads(output)
                self.assertFalse(envelope["ok"])
                self.assertEqual(envelope["error"]["code"], expected_code)

        first_code, first_output = run_cli("task", "run", "ENG-1")
        second_code, second_output = run_cli("task", "run", "ENG-2")
        self.assertEqual((first_code, second_code), (0, 0))
        first_execution = json.loads(first_output)["result"]["execution"]
        second_execution = json.loads(second_output)["result"]["execution"]
        self.assertEqual(first_execution["invocation"]["target"], "ENG-1")
        self.assertEqual(second_execution["invocation"]["target"], "ENG-2")
        self.assertNotEqual(first_execution, second_execution)

        text_code, text_output = run_cli("--format", "text", "help")
        self.assertEqual(text_code, 0)
        self.assertTrue(text_output.startswith("Linear Spanks 1.0.0\n"))
        self.assertIn("project: create, review, run", text_output)
        self.assertNotIn('"schema_version"', text_output)

        error_code, error_output = run_cli("--format=text", "not-a-namespace")
        self.assertEqual(error_code, 2)
        self.assertTrue(error_output.startswith("ERROR NAMESPACE_NOT_FOUND:"))

    def test_stdin_and_file_payloads_produce_the_same_result(self) -> None:
        source = dependency_graph_source_fixture()
        encoded = json.dumps(source)
        stdin_code, stdin_output = run_cli("graphs", "build", stdin_text=encoded)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "graph-source.json"
            path.write_text(encoded, encoding="utf-8")
            file_code, file_output = run_cli("graphs", "build", str(path))
        self.assertEqual(stdin_code, 0)
        self.assertEqual(file_code, 0)
        self.assertEqual(json.loads(stdin_output), json.loads(file_output))

    def test_structured_errors_cover_all_exit_code_classes(self) -> None:
        success_code, success_output = run_cli("contracts", "validate")
        self.assertEqual(success_code, 0)
        self.assertTrue(json.loads(success_output)["ok"])

        usage_code, usage_output = run_cli("milestone")
        self.assertEqual(usage_code, 2)
        self.assertEqual(json.loads(usage_output)["error"]["code"], "COMMAND_REQUIRED")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(json.dumps(state_marker_fixture()), encoding="utf-8")
            preview_code, preview_output = run_cli(
                "artifacts",
                "preview",
                str(path),
                "--kind",
                "state-marker",
                "--command",
                "task run",
                "--target",
                "ENG-1",
            )
            self.assertEqual(preview_code, 0)
            authorization = json.loads(preview_output)["result"]["authorization_template"]
            authorization["receipt_id"] = "pending-approval-1"
            authorization["decision"] = "pending"
            authorization_path = Path(directory) / "authorization.json"
            authorization_path.write_text(json.dumps(authorization), encoding="utf-8")
            governed_code, governed_output = run_cli(
                "artifacts",
                "migrate",
                str(path),
                "--kind",
                "state-marker",
                "--command",
                "task run",
                "--target",
                "ENG-1",
                "--authorization",
                str(authorization_path),
            )
        self.assertEqual(governed_code, 3)
        self.assertEqual(json.loads(governed_output)["error"]["code"], "MIGRATION_APPROVAL_INVALID")

        missing = ROOT / "this-file-does-not-exist.json"
        filesystem_code, filesystem_output = run_cli(
            "artifacts", "inspect", str(missing), "--kind", "state-marker"
        )
        self.assertEqual(filesystem_code, 4)
        self.assertEqual(json.loads(filesystem_output)["error"]["code"], "FILE_READ_FAILED")

        with patch.object(app, "_dispatch", side_effect=RuntimeError("synthetic failure")):
            internal_code, internal_output = run_cli("help")
        self.assertEqual(internal_code, 1)
        self.assertEqual(json.loads(internal_output)["error"]["code"], "INTERNAL_ERROR")

    def test_namespace_entrypoint_smoke_uses_the_same_envelope(self) -> None:
        environment = dict(os.environ)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        completed = subprocess.run(
            [sys.executable, str(CLI), "milestone", "status", "milestone-1"],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        envelope = json.loads(completed.stdout)
        self.assertEqual(envelope["command"], "milestone status")
        self.assertTrue(envelope["ok"])

        removed = subprocess.run(
            [sys.executable, str(LEGACY_CLI), "run-milestone"],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(removed.returncode, 2)
        legacy_envelope = json.loads(removed.stdout)
        self.assertEqual(legacy_envelope["error"]["code"], "LEGACY_COMMAND_REMOVED")
        self.assertEqual(
            legacy_envelope["error"]["details"]["replacement"],
            "milestone run --mode step",
        )


if __name__ == "__main__":
    unittest.main()
