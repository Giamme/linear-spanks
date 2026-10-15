from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from linear_spanks.core.errors import FilesystemError, GovernedStop
from linear_spanks.installation import model_routing, snapshots

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts" / "configure-model-routing"
SNAPSHOTS = json.loads(
    (ROOT / "tests" / "fixtures" / "model-routing-snapshots.json").read_text(encoding="utf-8")
)
MODELS = {"low": "vendor/low", "medium": "vendor/medium", "high": "vendor/high"}


def load_configuration_module() -> Any:
    scripts = ROOT / "skills" / "linear-spanks" / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        spec = importlib.util.spec_from_file_location(
            "configure_model_routing_test", scripts / "configure_model_routing.py"
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(scripts))


def run_helper(
    client: str,
    destination: Path,
    *,
    apply: bool = False,
) -> subprocess.CompletedProcess[str]:
    command = [
        str(HELPER),
        "--client",
        client,
        "--low-model",
        MODELS["low"],
        "--medium-model",
        MODELS["medium"],
        "--high-model",
        MODELS["high"],
        "--dest",
        str(destination),
    ]
    if apply:
        command.append("--apply")
    return subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def normalized_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    report = payload["clients"][0]
    operations = report["operations"]
    files = {
        Path(operation["path"]).name: hashlib.sha256(
            operation["content"].encode("utf-8")
        ).hexdigest()
        for operation in operations
    }
    return {
        "capability": report["capability"],
        "configuration": report["configuration"],
        "delegation": report["delegation"],
        "operation_count": len(operations),
        "files": files,
        "role_profiles": report["role_profiles"],
    }


class ModelRoutingConfigurationTest(unittest.TestCase):
    def test_direct_openclaude_and_harness_adapter_branches(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = root / "openclaude.json"
            content, preview, action = model_routing.openclaude_content(settings, MODELS)
            self.assertEqual(action, "create")
            self.assertIn("linearSpanksModelRouting", preview)
            settings.write_text(content, encoding="utf-8")
            self.assertEqual(model_routing.openclaude_content(settings, MODELS)[2], "unchanged")

            value = json.loads(content)
            value["unrelated"] = {"preserved": True}
            settings.write_text(json.dumps(value), encoding="utf-8")
            updated, _, action = model_routing.openclaude_content(settings, MODELS)
            self.assertEqual(action, "update")
            self.assertEqual(json.loads(updated)["unrelated"], {"preserved": True})
            self.assertEqual(
                model_routing.openclaude_operations(root / "new.json", MODELS)[0]["action"],
                "create",
            )

            invalid_json = root / "invalid.json"
            invalid_json.write_text("{", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not valid JSON"):
                model_routing.openclaude_content(invalid_json, MODELS)
            invalid_json.write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "JSON object"):
                model_routing.openclaude_content(invalid_json, MODELS)
            invalid_json.unlink()
            invalid_json.mkdir()
            with self.assertRaisesRegex(ValueError, "not a file"):
                model_routing.openclaude_content(invalid_json, MODELS)

            target = root / "target.json"
            target.write_text("{}", encoding="utf-8")
            symlink = root / "symlink.json"
            symlink.symlink_to(target)
            with self.assertRaisesRegex(ValueError, "must not be a symlink"):
                model_routing.openclaude_content(symlink, MODELS)

            malformed = (
                {
                    "linearSpanksModelRouting": {
                        "schemaVersion": 2,
                        "managedAgentModels": [],
                        "managedAgentRouting": [],
                    }
                },
                {
                    "linearSpanksModelRouting": {
                        "schemaVersion": 1,
                        "managedAgentModels": ["wrong"],
                        "managedAgentRouting": [],
                    }
                },
                {"agentModels": []},
                {"agentModels": {"linear-spanks-low": {"model": "user"}}},
            )
            for index, payload in enumerate(malformed):
                path = root / f"malformed-{index}.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                with self.subTest(payload=payload), self.assertRaises(ValueError):
                    model_routing.openclaude_content(path, MODELS)

            contract = model_routing.load_routing_contract()
            for client in ("codex", "claude", "opencode", "openclaude"):
                destination = (
                    root / "direct-openclaude.json"
                    if client == "openclaude"
                    else root / f"direct-{client}"
                )
                report = model_routing.client_report(client, destination, MODELS, contract)
                self.assertTrue(report["operations"])
            for client in ("antigravity", "kimi"):
                report = model_routing.client_report(client, None, MODELS, contract)
                self.assertEqual(report["operations"], [])
            for client in ("codex", "openclaude"):
                with self.subTest(client=client), self.assertRaises(ValueError):
                    model_routing.client_report(client, None, MODELS, contract)
            invalid_contract = {
                **contract,
                "harnesses": {**contract["harnesses"], "unknown": {}},
            }
            with self.assertRaises(AssertionError):
                model_routing.client_report("unknown", None, MODELS, invalid_contract)
            with self.assertRaises(ValueError):
                model_routing.expand_clients("unknown")
            with self.assertRaises(ValueError):
                model_routing.default_destination("unknown")
            with self.assertRaises(AssertionError):
                model_routing.render_profile("unknown", "x", "planner", "high", "model")

    def test_main_direct_success_and_stable_error_exit_classes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "agents"
            arguments = [
                "--client",
                "codex",
                "--low-model",
                MODELS["low"],
                "--medium-model",
                MODELS["medium"],
                "--high-model",
                MODELS["high"],
                "--dest",
                str(destination),
            ]
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(model_routing.main(arguments), 0)
            self.assertEqual(json.loads(output.getvalue())["mode"], "preview")

            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(model_routing.main([*arguments[:-1], ""]), 2)
                self.assertEqual(
                    model_routing.main(
                        [
                            "--client",
                            "both",
                            "--low-model",
                            MODELS["low"],
                            "--medium-model",
                            MODELS["medium"],
                            "--high-model",
                            MODELS["high"],
                            "--dest",
                            str(destination),
                        ]
                    ),
                    2,
                )
            with (
                patch.object(model_routing, "client_report", side_effect=OSError("disk")),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(model_routing.main(arguments), 4)
            with (
                patch.object(
                    model_routing,
                    "client_report",
                    side_effect=GovernedStop("STOP", "governed"),
                ),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(model_routing.main(arguments), 3)

    def test_model_identifiers_reject_unpaired_surrogates(self) -> None:
        with self.assertRaisesRegex(ValueError, "valid UTF-8"):
            model_routing.validate_model_identifier("low", "vendor/\ud800")

    def test_empty_destination_and_abbreviated_options_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            environment = {**dict(os.environ), "HOME": str(home), "CODEX_HOME": ""}
            for extra in (("--dest", ""), ("--clie", "codex")):
                with self.subTest(extra=extra):
                    result = subprocess.run(
                        [
                            str(HELPER),
                            *extra,
                            "--low-model",
                            MODELS["low"],
                            "--medium-model",
                            MODELS["medium"],
                            "--high-model",
                            MODELS["high"],
                        ],
                        cwd=ROOT,
                        env=environment,
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 2)
            self.assertFalse((home / ".codex").exists())

    def test_apply_rejects_targets_created_or_modified_after_preview(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "agents"
            operations = model_routing.profile_operations("codex", destination, MODELS)
            target = Path(operations[0]["path"])
            target.parent.mkdir(parents=True)
            target.write_text("user created", encoding="utf-8")
            with self.assertRaises(GovernedStop):
                model_routing.apply_reports([{"operations": operations}])
            self.assertEqual(target.read_text(encoding="utf-8"), "user created")

            target.unlink()
            initial = model_routing.profile_operations("codex", destination, MODELS)
            model_routing.apply_reports([{"operations": initial}])
            updated_models = {**MODELS, "high": "vendor/new-high"}
            update = model_routing.profile_operations("codex", destination, updated_models)
            target.write_text("user modified", encoding="utf-8")
            with self.assertRaises(GovernedStop):
                model_routing.apply_reports([{"operations": update}])
            self.assertEqual(target.read_text(encoding="utf-8"), "user modified")

    def test_expected_absent_profile_publication_preserves_a_racing_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "profile.toml"
            operations = [
                {
                    "action": "create",
                    "path": str(target),
                    "_write_content": "managed\n",
                    "_expected": model_routing.snapshot_path(target),
                }
            ]
            original_write = model_routing.atomic_write

            def racing_write(path: Path, content: str) -> None:
                path.write_text("USER PROFILE\n", encoding="utf-8")
                original_write(path, content)

            with (
                patch.object(model_routing, "atomic_write", side_effect=racing_write),
                self.assertRaises(GovernedStop),
            ):
                model_routing.apply_reports([{"operations": operations}])
            self.assertEqual(target.read_text(encoding="utf-8"), "USER PROFILE\n")

    def test_failed_profile_backup_move_never_deletes_the_original(self) -> None:
        for fail_after_move in (False, True):
            with (
                self.subTest(fail_after_move=fail_after_move),
                tempfile.TemporaryDirectory() as root,
            ):
                target = Path(root) / "profile.toml"
                target.write_text("managed old\n", encoding="utf-8")
                operations = [
                    {
                        "action": "update",
                        "path": str(target),
                        "_write_content": "managed new\n",
                        "_expected": model_routing.snapshot_path(target),
                    }
                ]
                real_replace = os.replace

                def fail_move(
                    source: Path,
                    destination: Path,
                    *,
                    selected_target: Path = target,
                    fail_after: bool = fail_after_move,
                    replace: object = real_replace,
                ) -> None:
                    assert callable(replace)
                    if Path(source) == selected_target:
                        if fail_after:
                            replace(source, destination)
                        raise OSError("profile backup failed")
                    replace(source, destination)

                with (
                    patch.object(snapshots.os, "replace", side_effect=fail_move),
                    self.assertRaisesRegex(OSError, "profile backup failed"),
                ):
                    model_routing.apply_reports([{"operations": operations}])
                self.assertEqual(target.read_text(encoding="utf-8"), "managed old\n")

    def test_backup_cleanup_failure_keeps_the_committed_model_set(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            targets = (root / "first.toml", root / "second.toml")
            for target in targets:
                target.write_text("managed old\n", encoding="utf-8")
            operations = [
                {
                    "action": "update",
                    "path": str(target),
                    "_write_content": f"managed {target.stem}\n",
                    "_expected": model_routing.snapshot_path(target),
                }
                for target in targets
            ]
            real_unlink = Path.unlink
            backup_unlinks = 0

            def fail_second_backup_cleanup(path: Path, missing_ok: bool = False) -> None:
                nonlocal backup_unlinks
                if ".backup-" in path.name:
                    backup_unlinks += 1
                    if backup_unlinks == 2:
                        raise OSError("backup cleanup failed")
                real_unlink(path, missing_ok=missing_ok)

            with (
                patch.object(Path, "unlink", new=fail_second_backup_cleanup),
                self.assertRaises(FilesystemError) as caught,
            ):
                model_routing.apply_reports([{"operations": operations}])
            self.assertEqual(caught.exception.code, "INSTALLATION_BACKUP_CLEANUP_FAILED")
            self.assertEqual(targets[0].read_text(), "managed first\n")
            self.assertEqual(targets[1].read_text(), "managed second\n")
            self.assertEqual(len(tuple(root.glob(".*.backup-*"))), 1)

    def test_each_harness_adapter_matches_its_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for client in ("codex", "openclaude", "claude", "antigravity", "kimi", "opencode"):
                with self.subTest(client=client):
                    destination = (
                        root / "openclaude.json" if client == "openclaude" else root / client
                    )
                    result = run_helper(client, destination)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    snapshot = normalized_snapshot(json.loads(result.stdout))
                    self.assertEqual(snapshot, SNAPSHOTS[client])

    def test_preview_is_default_and_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "agents"
            result = run_helper("codex", destination)

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["mode"], "preview")
            self.assertFalse(destination.exists())
            self.assertTrue(
                all(
                    operation["action"] == "create"
                    for operation in payload["clients"][0]["operations"]
                )
            )

    def test_native_planner_profiles_cover_high_and_medium_as_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex = json.loads(run_helper("codex", root / "codex").stdout)
            claude = json.loads(run_helper("claude", root / "claude").stdout)
            opencode = json.loads(run_helper("opencode", root / "opencode").stdout)
            planner_content = {
                "codex": codex["clients"][0]["operations"][0]["content"],
                "claude": claude["clients"][0]["operations"][0]["content"],
                "opencode": opencode["clients"][0]["operations"][0]["content"],
            }
            medium_planner_content = {
                "codex": codex["clients"][0]["operations"][1]["content"],
                "claude": claude["clients"][0]["operations"][1]["content"],
                "opencode": opencode["clients"][0]["operations"][1]["content"],
            }

            codex_profile = tomllib.loads(planner_content["codex"])
            self.assertEqual(codex_profile["name"], "linear-spanks-planner")
            self.assertEqual(codex_profile["model"], "vendor/high")
            self.assertIn('model = "vendor/high"', planner_content["codex"])
            self.assertIn('sandbox_mode = "read-only"', planner_content["codex"])
            self.assertIn('model: "vendor/high"', planner_content["claude"])
            self.assertIn("permissionMode: plan", planner_content["claude"])
            self.assertNotIn("Write", planner_content["claude"])
            self.assertIn('model: "vendor/high"', planner_content["opencode"])
            self.assertIn("edit: deny", planner_content["opencode"])
            self.assertIn("bash: deny", planner_content["opencode"])
            self.assertIn('model = "vendor/medium"', medium_planner_content["codex"])
            self.assertIn('sandbox_mode = "read-only"', medium_planner_content["codex"])
            self.assertIn('model: "vendor/medium"', medium_planner_content["claude"])
            self.assertNotIn("Write", medium_planner_content["claude"])
            self.assertIn('model: "vendor/medium"', medium_planner_content["opencode"])
            self.assertIn("edit: deny", medium_planner_content["opencode"])

    def test_application_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "agents"
            first = run_helper("claude", destination, apply=True)
            second = run_helper("claude", destination, apply=True)

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(len(list(destination.glob("linear-spanks-*.md"))), 7)
            second_payload = json.loads(second.stdout)
            self.assertTrue(
                all(
                    operation["action"] == "unchanged"
                    for operation in second_payload["clients"][0]["operations"]
                )
            )

    def test_profile_application_preserves_unmanaged_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "agents"
            destination.mkdir()
            unmanaged = destination / "my-agent.toml"
            unmanaged.write_text('name = "mine"\n', encoding="utf-8")

            result = run_helper("codex", destination, apply=True)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(unmanaged.read_text(encoding="utf-8"), 'name = "mine"\n')

    def test_openclaude_merge_preserves_unmanaged_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "openclaude.json"
            destination.write_text(
                json.dumps(
                    {
                        "theme": "mine",
                        "agentModels": {
                            "custom": {"model": "vendor/custom", "api_key": "secret-value"}
                        },
                        "agentRouting": {"custom-agent": "custom"},
                    }
                ),
                encoding="utf-8",
            )

            first = run_helper("openclaude", destination, apply=True)
            second = run_helper("openclaude", destination, apply=True)

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertNotIn("secret-value", first.stdout)
            settings = json.loads(destination.read_text(encoding="utf-8"))
            self.assertEqual(settings["theme"], "mine")
            self.assertEqual(
                settings["agentModels"]["custom"],
                {"model": "vendor/custom", "api_key": "secret-value"},
            )
            self.assertEqual(settings["agentRouting"]["custom-agent"], "custom")
            self.assertEqual(
                json.loads(second.stdout)["clients"][0]["operations"][0]["action"],
                "unchanged",
            )

    def test_openclaude_refuses_future_or_extended_managed_metadata(self) -> None:
        for mutation in (
            {"schemaVersion": 2},
            {"unknownExtension": {"preserve": True}},
        ):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                destination = Path(temporary) / "openclaude.json"
                first = run_helper("openclaude", destination, apply=True)
                self.assertEqual(first.returncode, 0, first.stderr)
                settings = json.loads(destination.read_text(encoding="utf-8"))
                settings["linearSpanksModelRouting"].update(mutation)
                original = json.dumps(settings, sort_keys=True)
                destination.write_text(original, encoding="utf-8")

                rejected = run_helper("openclaude", destination, apply=True)

                self.assertEqual(rejected.returncode, 2, rejected.stderr)
                self.assertIn("unknown or future metadata", rejected.stderr)
                self.assertEqual(destination.read_text(encoding="utf-8"), original)

    def test_unmanaged_profile_collision_is_rejected_before_any_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "agents"
            destination.mkdir()
            collision = destination / "linear-spanks-planner.toml"
            collision.write_text('name = "unmanaged"\n', encoding="utf-8")

            result = run_helper("codex", destination, apply=True)

            self.assertEqual(result.returncode, 2)
            self.assertIn("refusing to replace unmanaged agent files", result.stderr)
            self.assertEqual({path.name for path in destination.iterdir()}, {collision.name})

    def test_marker_text_inside_user_content_does_not_claim_the_profile(self) -> None:
        for client, extension, content in (
            (
                "codex",
                "toml",
                'description = "Never trust managed-by: linear-spanks model-routing v1 text"\n',
            ),
            (
                "claude",
                "md",
                "User prose mentions managed-by: linear-spanks model-routing v1 inline.\n",
            ),
        ):
            with self.subTest(client=client), tempfile.TemporaryDirectory() as temporary:
                destination = Path(temporary) / "agents"
                destination.mkdir()
                collision = destination / f"linear-spanks-planner.{extension}"
                collision.write_text(content, encoding="utf-8")

                result = run_helper(client, destination, apply=True)

                self.assertEqual(result.returncode, 2)
                self.assertIn("refusing to replace unmanaged agent files", result.stderr)
                self.assertEqual(collision.read_text(encoding="utf-8"), content)

    def test_misplaced_markdown_marker_does_not_claim_user_profiles(self) -> None:
        marker = "<!-- managed-by: linear-spanks model-routing v1 -->"
        for client in ("claude", "opencode"):
            with self.subTest(client=client), tempfile.TemporaryDirectory() as temporary:
                destination = Path(temporary) / "agents"
                destination.mkdir()
                collision = destination / "linear-spanks-planner.md"
                content = f"---\ndescription: user owned\n---\nUser prose.\n{marker}\n"
                collision.write_text(content, encoding="utf-8")

                result = run_helper(client, destination, apply=True)

                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("refusing to replace unmanaged agent files", result.stderr)
                self.assertEqual(collision.read_text(encoding="utf-8"), content)

    def test_invalid_utf8_configuration_files_return_stable_filesystem_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            native = root / "agents"
            native.mkdir()
            (native / "linear-spanks-planner.toml").write_bytes(b"\xff")
            openclaude = root / "openclaude.json"
            openclaude.write_bytes(b"\xff")

            for client, destination in (("codex", native), ("openclaude", openclaude)):
                with self.subTest(client=client):
                    result = run_helper(client, destination, apply=True)
                    self.assertEqual(result.returncode, 4, result.stderr)
                    self.assertNotIn("Traceback", result.stderr)
                    self.assertIn("Unable to read", result.stderr)

    def test_unmanaged_profile_symlink_is_rejected_before_any_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "agents"
            destination.mkdir()
            collision = destination / "linear-spanks-planner.toml"
            collision.symlink_to(destination / "missing-unmanaged-profile.toml")

            result = run_helper("codex", destination, apply=True)

            self.assertEqual(result.returncode, 2)
            self.assertIn("refusing to replace unmanaged agent files", result.stderr)
            self.assertTrue(collision.is_symlink())
            self.assertEqual({path.name for path in destination.iterdir()}, {collision.name})

    def test_openclaude_does_not_claim_matching_unmanaged_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "openclaude.json"
            original = json.dumps(
                {
                    "agentModels": {
                        "linear-spanks-low": {"model": MODELS["low"]},
                    }
                }
            )
            destination.write_text(original, encoding="utf-8")

            result = run_helper("openclaude", destination, apply=True)

            self.assertEqual(result.returncode, 2)
            self.assertIn("refusing to replace unmanaged OpenClaude routing keys", result.stderr)
            self.assertEqual(destination.read_text(encoding="utf-8"), original)

    def test_openclaude_symlink_destination_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "settings.json"
            target.write_text("{}", encoding="utf-8")
            destination = Path(temporary) / "openclaude.json"
            destination.symlink_to(target)

            result = run_helper("openclaude", destination, apply=True)

            self.assertEqual(result.returncode, 2)
            self.assertIn("must not be a symlink", result.stderr)
            self.assertTrue(destination.is_symlink())
            self.assertEqual(target.read_text(encoding="utf-8"), "{}")

    def test_advisory_harnesses_report_capability_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            antigravity = run_helper("antigravity", root / "antigravity")
            kimi = run_helper("kimi", root / "kimi")

            self.assertEqual(antigravity.returncode, 0, antigravity.stderr)
            self.assertEqual(kimi.returncode, 0, kimi.stderr)
            antigravity_report = json.loads(antigravity.stdout)["clients"][0]
            kimi_report = json.loads(kimi.stdout)["clients"][0]
            self.assertEqual(antigravity_report["capability"], "inherited-model")
            self.assertEqual(kimi_report["capability"], "advisory-only")
            self.assertEqual(antigravity_report["operations"], [])
            self.assertEqual(kimi_report["operations"], [])
            self.assertIn("advisory", antigravity_report["notes"][0])
            self.assertIn("does not enforce", kimi_report["notes"][0])

    def test_model_identifiers_reject_whitespace_injection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(
                [
                    str(HELPER),
                    "--client",
                    "codex",
                    "--low-model",
                    "vendor/low\nmodel=evil",
                    "--medium-model",
                    MODELS["medium"],
                    "--high-model",
                    MODELS["high"],
                    "--dest",
                    str(Path(temporary) / "agents"),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("must not contain whitespace", result.stderr)

    def test_apply_rolls_back_earlier_profiles_when_a_later_write_fails(self) -> None:
        module = load_configuration_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            existing = root / "existing.toml"
            created = root / "created.toml"
            existing.write_text("original\n", encoding="utf-8")
            reports = [
                {
                    "operations": [
                        {
                            "action": "update",
                            "path": str(existing),
                            "_write_content": "changed\n",
                            "_expected": module.snapshot_path(existing),
                        },
                        {
                            "action": "create",
                            "path": str(created),
                            "_write_content": "new\n",
                            "_expected": module.snapshot_path(created),
                        },
                    ]
                }
            ]
            original_write = module.atomic_write
            writes = 0

            def fail_second_write(path: Path, content: str) -> None:
                nonlocal writes
                writes += 1
                if writes == 2:
                    raise OSError("simulated disk failure")
                original_write(path, content)

            module.atomic_write = fail_second_write
            try:
                with self.assertRaisesRegex(OSError, "simulated disk failure"):
                    module.apply_reports(reports)
            finally:
                module.atomic_write = original_write

            self.assertEqual(existing.read_text(encoding="utf-8"), "original\n")
            self.assertFalse(created.exists())

    def test_apply_rolls_back_earlier_profiles_after_an_encoding_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first.toml"
            second = root / "second.toml"
            operations = [
                {
                    "action": "create",
                    "path": str(first),
                    "_write_content": "managed\n",
                    "_expected": model_routing.snapshot_path(first),
                },
                {
                    "action": "create",
                    "path": str(second),
                    "_write_content": "\ud800",
                    "_expected": model_routing.snapshot_path(second),
                },
            ]
            with self.assertRaises(UnicodeEncodeError):
                model_routing.apply_reports([{"operations": operations}])
            self.assertFalse(first.exists())
            self.assertFalse(second.exists())

    def test_rollback_preserves_concurrent_profile_edits(self) -> None:
        module = load_configuration_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first.toml"
            second = root / "second.toml"
            reports = [
                {
                    "operations": [
                        {
                            "action": "create",
                            "path": str(first),
                            "_write_content": "managed\n",
                            "_expected": module.snapshot_path(first),
                        },
                        {
                            "action": "create",
                            "path": str(second),
                            "_write_content": "managed\n",
                            "_expected": module.snapshot_path(second),
                        },
                    ]
                }
            ]
            original_write = module.atomic_write
            writes = 0

            def race_then_fail(path: Path, content: str) -> None:
                nonlocal writes
                writes += 1
                if writes == 2:
                    first.write_text("managed\nuser edit\n", encoding="utf-8")
                    raise OSError("simulated disk failure")
                original_write(path, content)

            module.atomic_write = race_then_fail
            try:
                with self.assertRaisesRegex(OSError, "rollback was incomplete"):
                    module.apply_reports(reports)
            finally:
                module.atomic_write = original_write
            self.assertEqual(first.read_text(encoding="utf-8"), "managed\nuser edit\n")

    def test_rollback_quarantines_profile_before_removal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first.toml"
            second = root / "second.toml"
            operations = [
                {
                    "action": "create",
                    "path": str(path),
                    "_write_content": "managed\n",
                    "_expected": model_routing.snapshot_path(path),
                }
                for path in (first, second)
            ]
            original_write = model_routing.atomic_write
            real_replace = os.replace

            def fail_second(path: Path, content: str) -> None:
                if path == second:
                    raise OSError("later profile failed")
                original_write(path, content)

            def race_quarantine(source: Path, destination: Path) -> None:
                if Path(source) == first and ".rollback-" in Path(destination).name:
                    first.write_text("USER PROFILE\n", encoding="utf-8")
                real_replace(source, destination)

            with (
                patch.object(model_routing, "atomic_write", side_effect=fail_second),
                patch.object(snapshots.os, "replace", side_effect=race_quarantine),
                self.assertRaisesRegex(OSError, "rollback was incomplete"),
            ):
                model_routing.apply_reports([{"operations": operations}])
            self.assertEqual(first.read_text(), "USER PROFILE\n")


if __name__ == "__main__":
    unittest.main()
