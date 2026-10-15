from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.contract_support import (
    dependency_graph_source_fixture,
    isolation_receipt_fixture,
    milestone_loop_receipt_fixture,
    project_loop_receipt_fixture,
    state_marker_fixture,
    verification_ledger_fixture,
)

from linear_spanks.core.errors import FilesystemError, UsageError
from linear_spanks.core.hashing import sha256_bytes, sha256_digest
from linear_spanks.core.jsonio import (
    atomic_write_json,
    dump_json,
    freeze_json,
    load_json_object,
    mutable_json_copy,
    read_text,
)
from linear_spanks.core.validation import (
    require_object,
    require_positive_int,
    require_sha256,
    require_text,
)
from linear_spanks.domains import (
    commands,
    context,
    graphs,
    isolation,
    orchestration,
    reviews,
    routing,
    runtime,
    state,
)
from linear_spanks.domains._validation import checked


class DomainApiTest(unittest.TestCase):
    def test_typed_domains_execute_owned_implementations_directly(self) -> None:
        artifacts = json.loads(
            (Path(__file__).parent / "fixtures" / "v1" / "artifacts.json").read_text(
                encoding="utf-8"
            )
        )["artifacts"]
        graph = graphs.build(dependency_graph_source_fixture())
        self.assertEqual(graphs.validate(graph), graph)
        rendered = graphs.render(graph)
        self.assertEqual(graphs.parse(rendered), graph)

        marker = state_marker_fixture()
        marker_text = f"<!-- linear-spanks:state {json.dumps(marker)} -->"
        self.assertEqual(state.parse_marker(marker_text), marker)
        self.assertTrue(state.payload_hash(marker).startswith("sha256:"))
        for value in (float("nan"), float("inf"), "\ud800"):
            with self.subTest(payload_hash_value=value):
                with self.assertRaises(UsageError) as invalid_hash:
                    state.payload_hash({"value": value})
                self.assertEqual(invalid_hash.exception.code, "INVALID_JSON_VALUE")
        self.assertEqual(
            state.transition("clarify", "draft"),
            "clarified",
        )

        self.assertEqual(
            isolation.validate_receipt(isolation_receipt_fixture())["state"],
            "prepared",
        )
        self.assertEqual(
            orchestration.validate_project_receipt(project_loop_receipt_fixture())["state"],
            "prepared",
        )
        self.assertEqual(
            orchestration.validate_milestone_receipt(milestone_loop_receipt_fixture())["state"],
            "prepared",
        )
        self.assertEqual(
            orchestration.validate_ledger(verification_ledger_fixture())["status"],
            "valid",
        )
        self.assertEqual(routing.check("codex", "planner", "high")["effective_strength"], "high")
        self.assertEqual(
            runtime.validate_projection(artifacts["milestone-runtime-projection"])["revision"],
            1,
        )
        self.assertEqual(
            context.validate_checkpoint(artifacts["repository-checkpoint"])["status"],
            "valid",
        )

        for operation in (
            lambda: graphs.build({}),
            lambda: isolation.validate_receipt({}),
            lambda: orchestration.validate_project_receipt({}),
            lambda: reviews.incremental_plan({}),
            lambda: routing.recommend({}),
            lambda: runtime.validate_projection({}),
            lambda: context.validate_checkpoint({}),
        ):
            with self.subTest(operation=operation), self.assertRaises(UsageError) as caught:
                operation()
            self.assertEqual(caught.exception.code, "PAYLOAD_VALIDATION_FAILED")

    def test_domain_boundary_normalizes_validation_errors(self) -> None:
        self.assertEqual(checked(lambda value: value + 1, 1), 2)
        for error in (ValueError("bad"), KeyError("bad"), TypeError("bad")):
            with self.subTest(error=type(error).__name__):
                with self.assertRaises(UsageError) as caught:
                    checked(lambda selected=error: (_ for _ in ()).throw(selected))
                self.assertEqual(caught.exception.code, "PAYLOAD_VALIDATION_FAILED")

    def test_command_domain_exposes_injectable_typed_contracts(self) -> None:
        contract_set = commands.contracts()
        self.assertEqual(commands.validate()["status"], "valid")
        self.assertEqual(commands.command("project run", contract_set).path, "project run")
        self.assertEqual(
            commands.compile_command(
                "milestone run", ("milestone-1",), contract_set=contract_set
            ).command.path,
            "milestone run",
        )
        with self.assertRaises(UsageError) as caught:
            commands.command("project missing", contract_set)
        self.assertEqual(caught.exception.code, "COMMAND_NOT_FOUND")

    def test_core_validation_hashing_and_json_adapters(self) -> None:
        digest = "sha256:" + "a" * 64
        self.assertEqual(require_object({"a": 1}, "object"), {"a": 1})
        self.assertEqual(require_text("value", "text"), "value")
        self.assertEqual(require_positive_int(1, "number"), 1)
        self.assertEqual(require_sha256(digest, "digest"), digest)
        invalid_calls = (
            lambda: require_object([], "object"),
            lambda: require_text(" ", "text"),
            lambda: require_positive_int(True, "number"),
            lambda: require_sha256("no", "digest"),
        )
        for call in invalid_calls:
            with self.assertRaises(UsageError):
                call()

        value = {"list": [{"nested": True}]}
        frozen = freeze_json(value)
        with self.assertRaises(TypeError):
            frozen["list"][0]["nested"] = False
        self.assertEqual(mutable_json_copy(frozen), value)
        self.assertTrue(dump_json(value).endswith("\n"))
        self.assertIn("\n  ", dump_json(value, pretty=True))
        self.assertTrue(sha256_digest(value).startswith("sha256:"))
        self.assertEqual(len(sha256_bytes(b"value")), 71)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "nested" / "value.json"
            atomic_write_json(path, value)
            self.assertEqual(load_json_object(path), value)
            self.assertEqual(read_text(path), dump_json(value, pretty=True))

            array_path = root / "array.json"
            array_path.write_text("[]", encoding="utf-8")
            with self.assertRaises(UsageError) as array_error:
                load_json_object(array_path)
            self.assertEqual(array_error.exception.code, "INVALID_JSON_OBJECT")

            malformed_path = root / "malformed.json"
            malformed_path.write_text("{", encoding="utf-8")
            with self.assertRaises(UsageError) as malformed:
                load_json_object(malformed_path)
            self.assertEqual(malformed.exception.code, "INVALID_JSON")

            with self.assertRaises(FilesystemError):
                read_text(root / "missing.json")


if __name__ == "__main__":
    unittest.main()
