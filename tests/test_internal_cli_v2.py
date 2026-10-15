from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.contract_support import state_marker_fixture
from tests.test_cli_v2 import run_cli

from linear_spanks.cli import app, internal
from linear_spanks.cli.render import render_text
from linear_spanks.core.errors import LinearSpanksError, UsageError
from linear_spanks.core.types import CliResult
from linear_spanks.domains.documentation import render_command_catalog


class InternalCliTest(unittest.TestCase):
    def test_state_payload_hash_uses_the_strict_v2_canonical_boundary(self) -> None:
        valid_code, valid_output = run_cli(
            "state",
            "payload-hash",
            stdin_text='{"value":1}',
        )
        self.assertEqual(valid_code, 0, valid_output)
        self.assertTrue(json.loads(valid_output)["result"].startswith("sha256:"))

        for payload in ('{"value":1e9999}', '{"value":"\\ud800"}'):
            with self.subTest(payload=payload):
                code, output = run_cli("state", "payload-hash", stdin_text=payload)
                self.assertEqual(code, 2, output)
                self.assertIn(
                    json.loads(output)["error"]["code"],
                    {"INVALID_JSON", "INVALID_JSON_VALUE"},
                )

    def test_generated_catalog_renders_every_command_mode_override(self) -> None:
        catalog = render_command_catalog()
        self.assertIn("#### Mode override: `loop`", catalog)
        self.assertIn(
            "`milestone run <goal|milestone> --mode loop [--max-parallel <2..8>]",
            catalog,
        )
        self.assertIn(
            "- Profiles: `staged_milestone_orchestration`, `milestone`, `planning`",
            catalog,
        )
        self.assertIn("- Template: `milestone-orchestration-receipt.md`", catalog)

    def test_contract_operations_cover_command_envelope_brief_and_runtime_card(self) -> None:
        for arguments in (
            ("contracts", "command", "project", "run"),
            (
                "contracts",
                "envelope",
                "milestone",
                "run",
                "milestone-1",
                "--mode",
                "loop",
            ),
            ("contracts", "brief", "milestone", "run", "milestone-1", "--mode", "loop"),
            ("contracts", "runtime-card", "task", "run", "ENG-1"),
        ):
            with self.subTest(arguments=arguments):
                exit_code, output = run_cli(*arguments)
                self.assertEqual(exit_code, 0, output)
                self.assertTrue(json.loads(output)["ok"])

        invalid_cases = (
            ("contracts", "validate", "unexpected"),
            ("contracts", "command", "project"),
            ("contracts", "envelope", "project"),
            ("contracts", "unknown"),
            ("contracts", "envelope", "project", "run", "--assurance"),
            (
                "contracts",
                "envelope",
                "project",
                "run",
                "--assurance",
                "fast",
                "--assurance",
                "strict",
            ),
        )
        for arguments in invalid_cases:
            with self.subTest(arguments=arguments):
                exit_code, output = run_cli(*arguments)
                self.assertEqual(exit_code, 2)
                self.assertFalse(json.loads(output)["ok"])

    def test_internal_parser_actions_are_exhaustively_namespaced_and_help_is_json(self) -> None:
        parser = internal.build_internal_parser()
        subparsers = next(action for action in parser._actions if action.dest == "action")
        parser_actions = set(subparsers.choices)
        routed = {
            action
            for operations in internal.INTERNAL_OPERATIONS.values()
            for action in operations.values()
        }
        contract_actions = {
            "command",
            "execution-envelope",
            "execution-brief",
            "runtime-card",
            "validate-contracts",
        }
        self.assertEqual(
            parser_actions
            | set(internal.CONTEXT_OPERATIONS)
            | internal.DOCUMENT_OPERATIONS
            | {"inspect-state"}
            | {operation for _, operation in internal.WORKFLOW_OPERATIONS},
            routed | contract_actions,
        )

        help_code, help_output = run_cli("graphs", "build", "--help")
        self.assertEqual(help_code, 0)
        help_envelope = json.loads(help_output)
        self.assertTrue(help_envelope["ok"])
        self.assertIn(
            "usage: linear_spanks_cli.py graphs build",
            help_envelope["result"]["help"],
        )
        self.assertNotIn("dependency-graph-build", help_envelope["result"]["help"])

        for namespace, operation, legacy_action in (
            ("context", "check", "context-check"),
            ("runtime", "preflight", "preflight-check"),
            ("verification", "action-check", "human-verification-action-check"),
        ):
            with self.subTest(namespace=namespace, operation=operation):
                code, output = run_cli(namespace, operation, "--help")
                self.assertEqual(code, 0, output)
                result = json.loads(output)["result"]
                self.assertIn(
                    f"usage: linear_spanks_cli.py {namespace} {operation}",
                    result["help"],
                )
                self.assertNotIn(legacy_action, result["help"])
                self.assertEqual(result["operation"], f"{namespace} {operation}")

        abbreviated_code, abbreviated_output = run_cli(
            "context",
            "check",
            "task",
            "run",
            "--estimated-t",
            "1",
        )
        self.assertEqual(abbreviated_code, 2, abbreviated_output)
        self.assertEqual(json.loads(abbreviated_output)["error"]["code"], "INVALID_ARGUMENTS")

        step_code, step_output = run_cli(
            "context", "check", "milestone", "run", "--estimated-tokens", "1"
        )
        loop_code, loop_output = run_cli(
            "context",
            "check",
            "milestone",
            "run",
            "--mode",
            "loop",
            "--estimated-tokens",
            "1",
        )
        self.assertEqual(step_code, 0, step_output)
        self.assertEqual(loop_code, 0, loop_output)
        self.assertEqual(json.loads(step_output)["result"]["command"], "run-milestone")
        self.assertEqual(json.loads(loop_output)["result"]["command"], "run-milestone-loop")

    def test_artifact_and_translation_argument_errors_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(json.dumps(state_marker_fixture()), encoding="utf-8")
            for arguments in (
                ("artifacts", "inspect"),
                ("artifacts", "inspect", str(path)),
                (
                    "artifacts",
                    "inspect",
                    str(path),
                    "--kind",
                    "state-marker",
                    "unexpected",
                ),
                (
                    "artifacts",
                    "inspect",
                    str(path),
                    "--kind",
                    "state-marker",
                    "--knid",
                    "state-marker",
                ),
                ("artifacts", "unknown", str(path), "--kind", "state-marker"),
            ):
                with self.subTest(arguments=arguments):
                    code, output = run_cli(*arguments)
                    self.assertEqual(code, 2)
                    self.assertFalse(json.loads(output)["ok"])

            binary = Path(directory) / "binary.json"
            binary.write_bytes(b"\xff")
            code, output = run_cli(
                "artifacts",
                "inspect",
                str(binary),
                "--kind",
                "state-marker",
            )
            self.assertEqual(code, 4, output)
            self.assertEqual(json.loads(output)["error"]["code"], "FILE_READ_FAILED")

        with self.assertRaises(UsageError):
            internal._translate_command_prefix(("project",))
        with self.assertRaises(UsageError):
            internal._translate_command_prefix(("project", "missing"))
        self.assertEqual(
            internal._translate_command_prefix(("project", "run", "target")),
            ("run-project", "target"),
        )
        self.assertEqual(internal._translate_command_option(("x",), "--command"), ("x",))
        incomplete = ("--command", "project")
        with self.assertRaises(UsageError):
            internal._translate_command_option(incomplete, "--command")
        unknown = ("--command", "project", "missing")
        with self.assertRaises(UsageError):
            internal._translate_command_option(unknown, "--command")
        translated = internal._translate_command_option(
            ("--command", "project", "run", "--revision", "2"), "--command"
        )
        self.assertEqual(translated[1], "run-project")
        self.assertEqual(
            internal._translate_command_prefix(
                ("milestone", "run", "--mode", "loop", "--estimated-tokens", "1")
            )[0],
            "run-milestone-loop",
        )
        self.assertEqual(
            internal._translate_command_option(
                (
                    "--command",
                    "milestone",
                    "run",
                    "--command-mode",
                    "loop",
                    "--revision",
                    "2",
                ),
                "--command",
            )[1],
            "run-milestone-loop",
        )
        for option in ("--last-command", "--command"):
            for mode_arguments in (
                ("--command-mode", "loop"),
                ("--command-mode=loop",),
            ):
                with self.subTest(option=option, mode_arguments=mode_arguments):
                    translated_mode = internal._translate_command_option(
                        (
                            option,
                            "milestone",
                            "run",
                            *mode_arguments,
                            "--revision",
                            "2",
                        ),
                        option,
                    )
                    self.assertEqual(translated_mode[1], "run-milestone-loop")
                    self.assertFalse(
                        any(token.startswith("--command-mode") for token in translated_mode)
                    )
            for arguments in (
                (f"{option}=run-task", option, "task", "run"),
                (option, "task", "run", f"{option}=run-task"),
            ):
                with self.subTest(option=option, duplicate_arguments=arguments):
                    with self.assertRaises(UsageError) as duplicate_command:
                        internal._translate_command_option(arguments, option)
                    self.assertEqual(duplicate_command.exception.code, "DUPLICATE_OPTION")
        with self.assertRaises(UsageError) as duplicate_mode:
            internal._translate_command_option(
                (
                    "--command",
                    "milestone",
                    "run",
                    "--command-mode",
                    "loop",
                    "--command-mode=loop",
                ),
                "--command",
            )
        self.assertEqual(duplicate_mode.exception.code, "DUPLICATE_OPTION")

        loop_results = []
        for command_arguments in (
            ("--command-mode", "loop", "--command", "milestone", "run"),
            ("--command-mode=loop", "--command", "milestone", "run"),
            ("--command", "milestone", "run", "--command-mode", "loop"),
            ("--command", "milestone", "run", "--command-mode=loop"),
        ):
            with self.subTest(command_arguments=command_arguments):
                code, output = run_cli(
                    "state",
                    "idempotency-key",
                    "--project-id",
                    "project-1",
                    "--entity-id",
                    "milestone-1",
                    *command_arguments,
                    "--revision",
                    "1",
                    "--operation-id",
                    "operation-1",
                    "--payload-hash",
                    "sha256:" + "a" * 64,
                )
                self.assertEqual(code, 0, output)
                loop_results.append(json.loads(output)["result"])
        self.assertEqual(len(set(loop_results)), 1)

        for duplicate_arguments in (
            ("--command=run-task", "--command", "task", "run"),
            ("--command", "task", "run", "--command=run-task"),
        ):
            code, output = run_cli(
                "state",
                "idempotency-key",
                "--project-id",
                "project-1",
                "--entity-id",
                "ENG-1",
                *duplicate_arguments,
                "--revision",
                "1",
            )
            self.assertEqual(code, 2, output)
            self.assertEqual(json.loads(output)["error"]["code"], "DUPLICATE_OPTION")
        self.assertEqual(
            internal._translate_public_command_argument(
                "state", "issue-transition", ("task", "run")
            )[0],
            "run-task",
        )
        self.assertEqual(
            internal._translate_public_command_argument(
                "state", "advance", ("--command", "task", "run")
            )[1],
            "run-task",
        )
        self.assertEqual(
            internal._translate_public_command_argument(
                "state", "marker", ("--last-command", "task", "run")
            )[1],
            "run-task",
        )
        untouched = ("value",)
        self.assertEqual(
            internal._translate_public_command_argument("graphs", "build", untouched),
            untouched,
        )

        namespaced_code, namespaced_output = run_cli(
            "state",
            "issue-transition",
            "task",
            "refine",
            "--from-status",
            "Human draft",
            "--to-status",
            "Unplanned",
        )
        self.assertEqual(namespaced_code, 0, namespaced_output)
        for arguments in (
            ("context", "check", "run-task", "--estimated-tokens", "1"),
            (
                "state",
                "issue-transition",
                "refine-task",
                "--from-status",
                "Human draft",
                "--to-status",
                "Unplanned",
            ),
        ):
            with self.subTest(arguments=arguments):
                code, output = run_cli(*arguments)
                self.assertEqual(code, 2, output)
                self.assertEqual(
                    json.loads(output)["error"]["code"],
                    "INVALID_COMMAND_OPERAND",
                )

    def test_artifact_cli_binds_full_execution_preview_and_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "state.json"
            artifact.write_text(json.dumps(state_marker_fixture()), encoding="utf-8")
            arguments_file = root / "arguments.json"
            arguments_file.write_text(
                json.dumps(["project-1", "--next-release", "2.0"]),
                encoding="utf-8",
            )
            preview_code, preview_output = run_cli(
                "artifacts",
                "preview",
                str(artifact),
                "--kind",
                "state-marker",
                "--command",
                "project rollover",
                "--arguments",
                str(arguments_file),
            )
            self.assertEqual(preview_code, 0, preview_output)
            preview = json.loads(preview_output)["result"]
            execution = preview["execution"]
            self.assertEqual(execution["invocation"]["target"], "project-1")
            self.assertEqual(execution["invocation"]["options"]["next_release"], "2.0")
            authorization = dict(preview["authorization_template"])
            authorization["receipt_id"] = "approved-project-write-1"
            authorization["decision"] = "approved"
            authorization_path = root / "authorization.json"
            authorization_path.write_text(json.dumps(authorization), encoding="utf-8")

            migrate_code, migrate_output = run_cli(
                "artifacts",
                "migrate",
                str(artifact),
                "--kind",
                "state-marker",
                "--command",
                "project rollover",
                "--arguments",
                str(arguments_file),
                "--authorization",
                str(authorization_path),
            )
            self.assertEqual(migrate_code, 0, migrate_output)
            self.assertEqual(json.loads(migrate_output)["result"]["status"], "migrated")
            self.assertEqual(json.loads(artifact.read_text())["schema_version"], 2)

            legacy_code, legacy_output = run_cli(
                "artifacts",
                "migrate",
                str(artifact),
                "--kind",
                "state-marker",
                "--authorized",
                "--approved-source-hash",
                "sha256:old",
            )
            self.assertEqual(legacy_code, 2)
            self.assertEqual(
                json.loads(legacy_output)["error"]["code"],
                "LEGACY_MIGRATION_AUTHORIZATION_REMOVED",
            )

    def test_docs_installation_extensions_and_dispatch_edges(self) -> None:
        for arguments in (
            ("docs", "check"),
            ("docs", "links"),
            ("installation", "clients", "both"),
        ):
            with self.subTest(arguments=arguments):
                code, output = run_cli(*arguments)
                self.assertEqual(code, 0, output)

        for arguments in (
            ("installation", "clients", "both", "unexpected"),
            ("docs", "check", "unexpected"),
            ("extensions", "caveman", "--bogus"),
        ):
            with self.subTest(arguments=arguments):
                code, output = run_cli(*arguments)
                self.assertEqual(code, 2)
                self.assertFalse(json.loads(output)["ok"])

        with patch.object(internal, "generate", return_value={"status": "generated"}):
            self.assertEqual(
                internal.run_internal("docs", "generate", (), io.StringIO()),
                {"status": "generated"},
            )
        for operation in ("check", "unknown"):
            with self.subTest(operation=operation), self.assertRaises(UsageError):
                internal._documentation_operation(operation, ("unexpected",))
        with self.assertRaises(UsageError):
            internal._documentation_operation("unknown", ())

        def successful_main(arguments: list[str] | None) -> int:
            print("preview")
            return 0

        for operation in ("skills", "model-routing"):
            target = internal.skill_installer if operation == "skills" else internal.model_routing
            with patch.object(target, "main", side_effect=successful_main):
                result = internal._installation_operation(operation, ("--dry-run",))
                self.assertEqual(result["output"], ["preview"])
        with patch.object(internal.caveman, "main", side_effect=successful_main):
            result = internal.run_internal("extensions", "caveman", ("--dry-run",), io.StringIO())
            self.assertEqual(result["status"], "completed")

        with self.assertRaises(UsageError):
            internal._installation_operation("unknown", ())
        with self.assertRaises(UsageError):
            internal._extension_operation("unknown", ())
        with self.assertRaises(UsageError):
            internal.run_internal("unknown", "operation", (), io.StringIO())
        with self.assertRaises(UsageError):
            internal.run_internal("graphs", "unknown", (), io.StringIO())

        result = internal.run_internal(
            "state",
            "transition",
            ("clarify", "--from", "draft"),
            io.StringIO(),
        )
        self.assertEqual(result, "clarified")

    def test_capture_main_maps_known_and_unknown_exit_codes(self) -> None:
        def fail_known(arguments: list[str] | None) -> int:
            print("bad input", file=sys.stderr)
            return 2

        with self.assertRaises(LinearSpanksError) as known:
            internal._capture_main("operation", fail_known, ())
        self.assertEqual(int(known.exception.exit_code), 2)
        self.assertEqual(known.exception.message, "bad input")

        def fail_unknown(arguments: list[str] | None) -> int:
            return 99

        with self.assertRaises(LinearSpanksError) as unknown:
            internal._capture_main("operation", fail_unknown, ())
        self.assertEqual(int(unknown.exception.exit_code), 1)
        self.assertEqual(unknown.exception.message, "operation failed")

        def argparse_exit(arguments: list[str] | None) -> int:
            print("usage: installer", file=sys.stderr)
            raise SystemExit(2)

        with self.assertRaises(LinearSpanksError) as argparse_error:
            internal._capture_main("operation", argparse_exit, ())
        self.assertEqual(int(argparse_error.exception.exit_code), 2)
        self.assertEqual(argparse_error.exception.message, "usage: installer")

    def test_app_and_text_renderer_reject_malformed_options_and_interrupts(self) -> None:
        cases = (
            ("--format",),
            ("--format", "json", "--format=text", "help"),
            ("--format", "xml", "help"),
            ("help", "--unknown"),
            ("project", "run", "--assurance"),
            ("contracts",),
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                code, output = run_cli(*arguments)
                self.assertEqual(code, 2)
                self.assertFalse(json.loads(output)["ok"])

        installer_code, installer_output = run_cli("installation", "skills", "--bogus")
        self.assertEqual(installer_code, 2)
        installer_envelope = json.loads(installer_output)
        self.assertFalse(installer_envelope["ok"])
        self.assertEqual(installer_envelope["error"]["code"], "INSTALLATION_OPERATION_FAILED")

        code, output = run_cli("help", "--internal")
        self.assertEqual(code, 0)
        self.assertIn("internal", json.loads(output)["result"])
        self.assertEqual(app._attempted_command(()), "help")
        self.assertEqual(app._attempted_command(("unknown",)), "unknown")

        for interrupt in (KeyboardInterrupt(), BrokenPipeError()):
            with (
                self.subTest(interrupt=type(interrupt).__name__),
                patch.object(app, "_dispatch", side_effect=interrupt),
            ):
                self.assertEqual(app.run(("help",), stdin=io.StringIO(), stdout=io.StringIO()), 1)

        self.assertEqual(render_text(CliResult(command="value", ok=True, result="text")), "text\n")
        detailed = render_text(
            CliResult(
                command="value",
                ok=False,
                error={"code": "BAD", "message": "failed", "details": {"field": "x"}},
            )
        )
        self.assertIn('"field": "x"', detailed)
        minimal = render_text(CliResult(command="value", ok=False))
        self.assertIn("UNKNOWN_ERROR", minimal)


if __name__ == "__main__":
    unittest.main()
