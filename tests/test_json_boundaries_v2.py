from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

from linear_spanks.cli.render import render_json
from linear_spanks.core.errors import FilesystemError, LinearSpanksError, UsageError
from linear_spanks.core.hashing import canonical_json_bytes
from linear_spanks.core.jsonio import (
    atomic_write_text,
    dump_json,
    freeze_json,
    load_json_object,
    strict_json_loads,
)
from linear_spanks.core.types import CliResult
from linear_spanks.domains import graphs, state, verification
from linear_spanks.domains.artifacts import ArtifactStore, artifact_codecs

from tests.test_artifact_migration import v1_artifacts
from tests.test_cli_v2 import run_cli


class StrictJsonBoundaryTest(unittest.TestCase):
    def test_embedded_durable_markers_use_strict_json_in_domains_and_cli(self) -> None:
        payloads = v1_artifacts()
        cases = (
            (
                "state",
                payloads["state-marker"],
                lambda encoded: f"<!-- linear-spanks:state {encoded} -->",
                state.parse_marker,
                ("state", "parse-marker"),
            ),
            (
                "graph",
                payloads["dependency-graph"],
                lambda encoded: f"<!-- linear-spanks:dependency-graph {encoded} -->",
                graphs.parse,
                ("graphs", "parse"),
            ),
            (
                "verification",
                payloads["human-verification-override"],
                lambda encoded: (
                    "<!-- linear-spanks:human-verification-override " + encoded + " -->"
                ),
                lambda text: verification.parse_marker("milestone-override", text),
                ("verification", "marker", "milestone-override"),
            ),
        )
        for label, payload, wrap, parser, cli_arguments in cases:
            encoded = json.dumps(payload, sort_keys=True)
            surrogate = {**payload, "project_id": "\ud800"}
            boolean_version = {**payload, "schema_version": True}
            hostile_values = (
                '{"project_id":"attacker",' + encoded[1:],
                '{"_overflow":1e9999,' + encoded[1:],
                json.dumps(surrogate, sort_keys=True),
                json.dumps(boolean_version, sort_keys=True),
            )
            for hostile in hostile_values:
                marker = wrap(hostile)
                with self.subTest(label=label, hostile=hostile[:30]):
                    with self.assertRaises(LinearSpanksError) as domain_error:
                        parser(marker)
                    self.assertIn(
                        domain_error.exception.code,
                        {"PAYLOAD_VALIDATION_FAILED", "HUMAN_VERIFICATION_POLICY_MALFORMED"},
                    )
                    code, output = run_cli(*cli_arguments, stdin_text=marker)
                    self.assertEqual(code, int(domain_error.exception.exit_code), output)
                    self.assertEqual(
                        json.loads(output)["error"]["code"],
                        domain_error.exception.code,
                    )

        gate = payloads["human-verification-gate"]
        encoded_gate = json.dumps(gate, sort_keys=True)
        duplicate_gate = (
            "<!-- linear-spanks:human-verification-gate "
            + '{"project_id":"attacker",'
            + encoded_gate[1:]
            + " -->"
        )
        gate_payload = {"issues": [{"id": gate["issue_id"], "description": duplicate_gate}]}
        with self.assertRaises(UsageError):
            verification.filter_gates(gate_payload)
        code, output = run_cli(
            "verification",
            "filter-gates",
            stdin_text=json.dumps(gate_payload),
        )
        self.assertEqual(code, 2, output)
        self.assertEqual(
            json.loads(output)["error"]["code"],
            "PAYLOAD_VALIDATION_FAILED",
        )

        boolean_graph = {**payloads["dependency-graph"], "schema_version": True}
        for operation in (graphs.validate, graphs.render):
            with self.assertRaises(UsageError) as rejected_graph:
                operation(boolean_graph)
            self.assertEqual(rejected_graph.exception.code, "PAYLOAD_VALIDATION_FAILED")
        for operation in ("check", "render"):
            code, output = run_cli(
                "graphs",
                operation,
                stdin_text=json.dumps(boolean_graph),
            )
            self.assertEqual(code, 2, output)
            self.assertEqual(
                json.loads(output)["error"]["code"],
                "PAYLOAD_VALIDATION_FAILED",
            )

    def test_atomic_text_write_normalizes_encoding_errors_and_cleans_temporary_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "artifact.json"
            with self.assertRaises(FilesystemError) as caught:
                atomic_write_text(target, "\ud800")
            self.assertEqual(caught.exception.code, "FILE_WRITE_FAILED")
            self.assertFalse(target.exists())
            self.assertEqual(tuple(root.iterdir()), ())

    def test_frozen_generic_mappings_remain_dumpable_and_hashable(self) -> None:
        plain = {"outer": {"items": [1, {"value": "two"}]}}
        frozen = freeze_json(plain)
        self.assertEqual(json.loads(dump_json(frozen)), plain)
        self.assertEqual(canonical_json_bytes(frozen), canonical_json_bytes(plain))
        self.assertEqual(state.payload_hash(frozen), state.payload_hash(plain))

    def test_non_finite_values_cannot_enter_artifacts_hashes_or_output(self) -> None:
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                payload = {**v1_artifacts()["state-marker"], "extension": value}
                with self.assertRaises(UsageError) as artifact:
                    artifact_codecs()["state-marker"].decode(payload)
                self.assertEqual(artifact.exception.code, "INVALID_JSON_VALUE")
                for operation in (
                    lambda selected=value: dump_json({"value": selected}),
                    lambda selected=value: canonical_json_bytes({"value": selected}),
                    lambda selected=value: render_json(
                        CliResult(command="test", ok=True, result=selected)
                    ),
                ):
                    with self.assertRaises(UsageError) as caught:
                        operation()
                    self.assertEqual(caught.exception.code, "INVALID_JSON_VALUE")

        raw = json.dumps(v1_artifacts()["state-marker"]).replace(
            '"revision": 1',
            '"revision": NaN',
        )
        with self.assertRaises(UsageError) as parsed:
            ArtifactStore()._decode_text(raw, Path("artifact.json"), "state-marker")
        self.assertEqual(parsed.exception.code, "INVALID_JSON")

        for encoded in ('{"value":1e9999}', '{"value":-1e9999}'):
            with self.subTest(encoded=encoded), self.assertRaises(ValueError):
                strict_json_loads(encoded)

    def test_surrogates_parser_limits_and_deep_nesting_never_escape_as_internal_errors(
        self,
    ) -> None:
        payload = v1_artifacts()["state-marker"]
        payload["project_id"] = "\ud800"
        encoded = json.dumps(payload)
        with self.assertRaises(UsageError) as surrogate:
            ArtifactStore()._decode_text(encoded, Path("artifact.json"), "state-marker")
        self.assertEqual(surrogate.exception.code, "INVALID_JSON")

        for operation in (
            lambda: dump_json({"value": "\ud800"}),
            lambda: canonical_json_bytes({"value": "\ud800"}),
        ):
            with self.subTest(operation=operation):
                with self.assertRaises(UsageError) as rejected:
                    operation()
                self.assertEqual(rejected.exception.code, "INVALID_JSON_VALUE")

        oversized_integer = '{"schema_version":' + ("9" * 5000) + "}"
        excessive_nesting = ("[" * 2000) + "]" * 2000
        for hostile in (oversized_integer, excessive_nesting):
            with self.subTest(length=len(hostile)):
                with self.assertRaises(UsageError) as rejected:
                    ArtifactStore()._decode_text(
                        hostile,
                        Path("artifact.json"),
                        "state-marker",
                    )
                self.assertEqual(rejected.exception.code, "INVALID_JSON")

    def test_duplicate_keys_are_rejected_for_artifacts_and_authorization(self) -> None:
        payload = json.dumps(v1_artifacts()["state-marker"])
        duplicate_schema = '{"schema_version":999,' + payload[1:]
        with self.assertRaises(UsageError) as schema:
            ArtifactStore()._decode_text(
                duplicate_schema,
                Path("artifact.json"),
                "state-marker",
            )
        self.assertEqual(schema.exception.code, "INVALID_JSON")

        encoded = artifact_codecs()["state-marker"].encode_v2(
            artifact_codecs()["state-marker"].decode(v1_artifacts()["state-marker"])
        )
        duplicate_integrity = '{"integrity":{},' + json.dumps(encoded)[1:]
        with self.assertRaises(UsageError) as integrity:
            ArtifactStore()._decode_text(
                duplicate_integrity,
                Path("artifact.json"),
                "state-marker",
            )
        self.assertEqual(integrity.exception.code, "INVALID_JSON")

        with self.assertRaises(ValueError):
            strict_json_loads('{"decision":"pending","decision":"approved"}')
        with tempfile.TemporaryDirectory() as directory:
            authorization = Path(directory) / "authorization.json"
            authorization.write_text(
                '{"decision":"pending","decision":"approved"}',
                encoding="utf-8",
            )
            with self.assertRaises(UsageError) as duplicate:
                load_json_object(authorization)
            self.assertEqual(duplicate.exception.code, "INVALID_JSON")


if __name__ == "__main__":
    unittest.main()
