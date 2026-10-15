from __future__ import annotations

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.contract_support import ROOT

from linear_spanks.core.errors import FilesystemError, GovernedStop, UsageError
from linear_spanks.installation import skill_installer, snapshots
from linear_spanks.installation.clients import client_registry


def local_repository(root: Path) -> tuple[Path, Path]:
    repository = root / "repository"
    skill = repository / "skills" / "example"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# Example\n", encoding="utf-8")
    manifest = repository / "skills-manifest.txt"
    manifest.write_text("example linear\n", encoding="utf-8")
    return repository, manifest


class ClientRegistryTest(unittest.TestCase):
    def test_all_skill_and_model_destination_branches_are_typed(self) -> None:
        registry = client_registry()
        environment = {
            "HOME": "/home/tester",
            "CODEX_HOME": "/configured/codex",
            "OPENCLAUDE_HOME": "/configured/openclaude",
            "KIMI_CODE_HOME": "/configured/kimi",
            "XDG_CONFIG_HOME": "/configured/xdg",
            "OPENCLAUDE_CONFIG": "/configured/openclaude.json",
        }
        expected_skills = {
            "codex": "/configured/codex/skills",
            "openclaude": "/configured/openclaude/skills",
            "claude": "/home/tester/.claude/skills",
            "antigravity-cli": "/home/tester/.gemini/antigravity-cli/skills",
            "antigravity-ide": "/home/tester/.gemini/config/skills",
            "kimi": "/configured/kimi/skills",
            "opencode": "/configured/xdg/opencode/skills",
        }
        for name, expected in expected_skills.items():
            with self.subTest(name=name):
                self.assertEqual(
                    str(registry.clients[name].skill_destination(environment)), expected
                )

        self.assertEqual(
            registry.clients["codex"].model_destination(environment),
            Path("/configured/codex/agents"),
        )
        self.assertEqual(
            registry.clients["claude"].model_destination(environment),
            Path("/home/tester/.claude/agents"),
        )
        self.assertEqual(
            registry.clients["opencode"].model_destination(environment),
            Path("/configured/xdg/opencode/agents"),
        )
        self.assertEqual(
            registry.clients["openclaude"].model_destination(environment),
            Path("/configured/openclaude.json"),
        )
        self.assertIsNone(registry.clients["kimi"].model_destination(environment))

        self.assertEqual(registry.routing_clients("antigravity"), ("antigravity",))
        self.assertEqual(len(registry.destinations("both", environment)), 2)
        with self.assertRaises(UsageError) as caught:
            registry.expand("missing")
        self.assertEqual(caught.exception.code, "INVALID_CLIENT")
        with self.assertRaises(TypeError):
            registry.clients["new"] = registry.clients["codex"]  # type: ignore[index]


class SkillInstallerUnitTest(unittest.TestCase):
    def test_empty_destination_is_rejected_and_print_uses_the_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = {"HOME": str(root), "CODEX_HOME": ""}
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                code = skill_installer.main(
                    ["--client", "codex", "--dest", "", "--dry-run"],
                    environment,
                )
            self.assertEqual(code, 2)
            self.assertIn("non-empty and trimmed", stderr.getvalue())
            self.assertFalse((root / ".codex").exists())

            override = root / "override"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = skill_installer.main(
                    [
                        "--client",
                        "codex",
                        "--dest",
                        str(override),
                        "--print-destinations",
                    ],
                    environment,
                )
            self.assertEqual(code, 0)
            self.assertEqual(stdout.getvalue().strip(), f"codex\t{override}")

    def test_target_and_record_drift_after_prepare_never_overwrites_user_data(self) -> None:
        client = client_registry().expand("codex")[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository, manifest = local_repository(root)
            destination = root / "destination"

            create_plan = skill_installer._prepare_install(
                client,
                destination,
                mode="copy",
                scope="linear",
                force=False,
                prune=False,
                prune_scope=False,
                uninstall=False,
                stage=True,
                repo_root=repository,
                manifest_path=manifest,
            )
            target = destination / "example"
            target.mkdir()
            user_file = target / "user.txt"
            user_file.write_text("created concurrently", encoding="utf-8")
            with self.assertRaises(GovernedStop) as created:
                skill_installer._apply_plans((create_plan,))
            self.assertEqual(created.exception.code, "INSTALLATION_TARGET_DRIFT")
            self.assertEqual(user_file.read_text(encoding="utf-8"), "created concurrently")

            target.rename(root / "concurrent-target")
            skill_installer.install_to(
                client,
                destination,
                mode="copy",
                scope="linear",
                force=False,
                prune=False,
                prune_scope=False,
                uninstall=False,
                dry_run=False,
                repo_root=repository,
                manifest_path=manifest,
            )
            (repository / "skills" / "example" / "SKILL.md").write_text(
                "# Updated\n", encoding="utf-8"
            )
            modify_plan = skill_installer._prepare_install(
                client,
                destination,
                mode="copy",
                scope="linear",
                force=False,
                prune=False,
                prune_scope=False,
                uninstall=False,
                stage=True,
                repo_root=repository,
                manifest_path=manifest,
            )
            installed_file = target / "SKILL.md"
            installed_file.write_text("user changed", encoding="utf-8")
            with self.assertRaises(GovernedStop):
                skill_installer._apply_plans((modify_plan,))
            self.assertEqual(installed_file.read_text(encoding="utf-8"), "user changed")

            record_plan = skill_installer._prepare_install(
                client,
                destination,
                mode="copy",
                scope="linear",
                force=False,
                prune=False,
                prune_scope=False,
                uninstall=True,
                stage=False,
                repo_root=repository,
                manifest_path=manifest,
            )
            record = destination / skill_installer.OWNERSHIP_RECORD
            record.write_text(record.read_text(encoding="utf-8") + "concurrent\n", encoding="utf-8")
            with self.assertRaises(GovernedStop):
                skill_installer._apply_plans((record_plan,))
            self.assertTrue(target.exists())

    def test_expected_absent_link_and_record_publication_preserve_racing_files(self) -> None:
        client = client_registry().expand("codex")[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository, manifest = local_repository(root)
            destination = root / "destination"
            plan = skill_installer._prepare_install(
                client,
                destination,
                mode="link",
                scope="linear",
                force=False,
                prune=False,
                prune_scope=False,
                uninstall=False,
                stage=True,
                repo_root=repository,
                manifest_path=manifest,
            )
            target = destination / "example"
            original_symlink = Path.symlink_to
            injected = False

            def racing_symlink(
                path: Path, source: Path | str, target_is_directory: bool = False
            ) -> None:
                nonlocal injected
                if path == target and not injected:
                    injected = True
                    path.write_text("USER TARGET", encoding="utf-8")
                original_symlink(path, source, target_is_directory)

            with (
                patch.object(Path, "symlink_to", new=racing_symlink),
                self.assertRaises(GovernedStop),
            ):
                skill_installer._apply_plans((plan,))
            self.assertEqual(target.read_text(encoding="utf-8"), "USER TARGET")

            target.unlink()
            plan = skill_installer._prepare_install(
                client,
                destination,
                mode="link",
                scope="linear",
                force=False,
                prune=False,
                prune_scope=False,
                uninstall=False,
                stage=True,
                repo_root=repository,
                manifest_path=manifest,
            )
            record = destination / skill_installer.OWNERSHIP_RECORD
            original_write = skill_installer.write_text_exclusive

            def racing_record(path: Path, content: str, *, mode: int = 0o600) -> None:
                if path == record:
                    path.write_text("USER RECORD\n", encoding="utf-8")
                original_write(path, content, mode=mode)

            with (
                patch.object(skill_installer, "write_text_exclusive", side_effect=racing_record),
                self.assertRaises(GovernedStop),
            ):
                skill_installer._apply_plans((plan,))
            self.assertEqual(record.read_text(encoding="utf-8"), "USER RECORD\n")
            self.assertFalse(target.exists())

    def test_failed_target_and_record_backup_moves_never_delete_originals(self) -> None:
        for fail_after_move in (False, True):
            with (
                self.subTest(fail_after_move=fail_after_move),
                tempfile.TemporaryDirectory() as root,
            ):
                directory = Path(root)
                target = directory / "skill"
                target.write_text("old", encoding="utf-8")
                staged_root = directory / ".linear-spanks-stage-test"
                staged_root.mkdir()
                staged = staged_root / "skill"
                staged.write_text("new", encoding="utf-8")
                record = directory / skill_installer.OWNERSHIP_RECORD
                record.write_text("skill\n", encoding="utf-8")
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
                        raise OSError("target backup failed")
                    replace(source, destination)

                with (
                    patch.object(snapshots.os, "replace", side_effect=fail_move),
                    self.assertRaisesRegex(OSError, "target backup failed"),
                ):
                    skill_installer._apply_changes(
                        [skill_installer.Change(target=target, staged=staged)],
                        record,
                        {"skill"},
                    )
                self.assertEqual(target.read_text(encoding="utf-8"), "old")
                self.assertEqual(record.read_text(encoding="utf-8"), "skill\n")

        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            record = directory / skill_installer.OWNERSHIP_RECORD
            record.write_text("skill\n", encoding="utf-8")
            real_replace = os.replace

            def fail_record(source: Path, destination: Path) -> None:
                if Path(source) == record:
                    raise OSError("record backup failed")
                real_replace(source, destination)

            with (
                patch.object(snapshots.os, "replace", side_effect=fail_record),
                self.assertRaisesRegex(OSError, "record backup failed"),
            ):
                skill_installer._apply_changes([], record, {"skill"})
            self.assertEqual(record.read_text(encoding="utf-8"), "skill\n")

    def test_directory_publication_is_exclusive_transactional_and_mode_preserving(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            staged = directory / "staged"
            staged.mkdir(mode=0o777)
            os.chmod(staged, 0o777)
            (staged / "a").write_text("a", encoding="utf-8")
            target = directory / "target"
            with patch.object(snapshots, "_rename_directory_exclusive", return_value=False):
                snapshots.publish_staged_exclusive(staged, target)
            self.assertEqual(target.stat().st_mode & 0o777, 0o777)

            staged = directory / "staged-race"
            staged.mkdir()
            (staged / "a").write_text("a", encoding="utf-8")
            (staged / "b").write_text("b", encoding="utf-8")
            target = directory / "target-race"
            original_publish = snapshots.publish_staged_exclusive

            def fail_second(source: Path, destination: Path) -> None:
                if source == staged / "b":
                    raise OSError("second child failed")
                original_publish(source, destination)

            with (
                patch.object(snapshots, "publish_staged_exclusive", side_effect=fail_second),
                self.assertRaisesRegex(OSError, "second child failed"),
            ):
                snapshots._publish_directory_fallback(staged, target, 0o755)
            self.assertFalse(target.exists())
            self.assertEqual((staged / "a").read_text(), "a")
            self.assertEqual((staged / "b").read_text(), "b")

            staged = directory / "staged-exclusive"
            staged.mkdir()
            (staged / "managed").write_text("managed", encoding="utf-8")
            target = directory / "target-exclusive"
            target.mkdir()
            with self.assertRaises(OSError):
                snapshots.publish_staged_exclusive(staged, target)
            self.assertEqual(list(target.iterdir()), [])
            self.assertTrue((staged / "managed").is_file())

    def test_manifest_and_management_validation_edges(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest"
            manifest.write_text("bad unknown\n", encoding="utf-8")
            with self.assertRaisesRegex(UsageError, "Invalid manifest"):
                skill_installer.load_manifest(manifest)
            manifest.write_text("same linear\nsame exec\n", encoding="utf-8")
            with self.assertRaisesRegex(UsageError, "duplicate"):
                skill_installer.load_manifest(manifest)
            manifest.write_text("../victim linear\n", encoding="utf-8")
            with self.assertRaisesRegex(UsageError, "Invalid skill name"):
                skill_installer.load_manifest(manifest)
            manifest.write_bytes(b"\xff")
            with self.assertRaises(FilesystemError) as malformed_encoding:
                skill_installer.load_manifest(manifest)
            self.assertEqual(malformed_encoding.exception.code, "FILE_READ_FAILED")

            internal = root / "internal"
            internal.symlink_to(ROOT / "skills" / "linear-spanks")
            self.assertTrue(skill_installer.is_managed(internal, ROOT))
            relative = root / "relative"
            relative.symlink_to(Path("relative-target"))
            self.assertFalse(skill_installer.is_managed(relative, ROOT))
            external = root / "external"
            external.symlink_to(root / "elsewhere")
            self.assertFalse(skill_installer.is_managed(external, ROOT))

            copied = root / "copied"
            copied.mkdir()
            (copied / skill_installer.COPY_MARKER).write_text(str(ROOT), encoding="utf-8")
            self.assertTrue(skill_installer.is_managed(copied, ROOT))
            malformed_copy = root / "malformed-copy"
            malformed_copy.mkdir()
            (malformed_copy / skill_installer.COPY_MARKER).write_bytes(b"\xff")
            with self.assertRaises(FilesystemError) as invalid_copy_marker:
                skill_installer.is_managed(malformed_copy, ROOT)
            self.assertEqual(invalid_copy_marker.exception.code, "FILE_READ_FAILED")

            forged = root / "forged"
            forged.mkdir()
            owner_text = root / "owner-text"
            owner_text.write_text(str(ROOT), encoding="utf-8")
            (forged / skill_installer.COPY_MARKER).symlink_to(owner_text)
            self.assertFalse(skill_installer.is_managed(forged, ROOT))
            self.assertEqual(skill_installer._record_names(root / "missing"), set())
            binary_record = root / "binary-record"
            binary_record.write_bytes(b"\xff")
            with self.assertRaises(FilesystemError):
                skill_installer._record_names(binary_record)

    def test_recorded_path_traversal_cannot_escape_on_uninstall_or_prune(self) -> None:
        client = client_registry().expand("codex")[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository, manifest = local_repository(root)
            destination = root / "destination"
            destination.mkdir()
            victim = root / "victim"
            victim.mkdir()
            (victim / skill_installer.COPY_MARKER).write_text(
                str(repository) + "\n", encoding="utf-8"
            )
            sentinel = victim / "keep.txt"
            sentinel.write_text("owned", encoding="utf-8")
            record = destination / skill_installer.OWNERSHIP_RECORD
            record.write_text("../victim\n", encoding="utf-8")

            for uninstall, prune in ((True, False), (False, True)):
                with self.subTest(uninstall=uninstall, prune=prune):
                    with self.assertRaises(UsageError) as caught:
                        skill_installer.install_to(
                            client,
                            destination,
                            mode="copy",
                            scope="linear",
                            force=False,
                            prune=prune,
                            prune_scope=False,
                            uninstall=uninstall,
                            dry_run=False,
                            repo_root=repository,
                            manifest_path=manifest,
                        )
                    self.assertEqual(caught.exception.code, "INVALID_OWNERSHIP_RECORD")
                    self.assertEqual(sentinel.read_text(encoding="utf-8"), "owned")

    def test_matching_unrecorded_entry_is_still_unmanaged(self) -> None:
        client = client_registry().expand("codex")[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository, manifest = local_repository(root)
            destination = root / "destination"
            destination.mkdir()
            (destination / "example").symlink_to(repository / "skills" / "example")

            with self.assertRaisesRegex(UsageError, "unmanaged"):
                skill_installer.install_to(
                    client,
                    destination,
                    mode="link",
                    scope="linear",
                    force=False,
                    prune=False,
                    prune_scope=False,
                    uninstall=False,
                    dry_run=True,
                    repo_root=repository,
                    manifest_path=manifest,
                )

    def test_interrupted_staged_replacement_restores_existing_skill(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "skill"
            target.write_text("old", encoding="utf-8")
            staged_root = root / ".linear-spanks-stage-test"
            staged_root.mkdir()
            staged = staged_root / "skill"
            staged.write_text("new", encoding="utf-8")
            record = root / skill_installer.OWNERSHIP_RECORD
            record.write_text("skill\n", encoding="utf-8")
            original_publish = skill_installer.publish_staged_exclusive

            def fail_staged_replace(source: Path, destination: Path) -> None:
                if Path(source) == staged:
                    raise OSError("interrupted install")
                original_publish(source, destination)

            change = skill_installer.Change(target=target, staged=staged)
            with (
                patch.object(
                    skill_installer,
                    "publish_staged_exclusive",
                    side_effect=fail_staged_replace,
                ),
                self.assertRaisesRegex(OSError, "interrupted install"),
            ):
                skill_installer._apply_changes([change], record, {"skill"})
            self.assertEqual(target.read_text(encoding="utf-8"), "old")
            self.assertEqual(record.read_text(encoding="utf-8"), "skill\n")

    def test_multi_destination_apply_failure_rolls_back_every_plan(self) -> None:
        clients = client_registry().expand("both")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository, manifest = local_repository(root)
            plans = [
                skill_installer._prepare_install(
                    client,
                    root / client.name,
                    mode="link",
                    scope="linear",
                    force=False,
                    prune=False,
                    prune_scope=False,
                    uninstall=False,
                    stage=True,
                    repo_root=repository,
                    manifest_path=manifest,
                )
                for client in clients
            ]
            second_staged = plans[1].changes[0].staged
            assert second_staged is not None
            original_publish = skill_installer.publish_staged_exclusive

            def fail_second_destination(source: Path, destination: Path) -> None:
                if Path(source) == second_staged:
                    raise OSError("second destination failed")
                original_publish(source, destination)

            with (
                patch.object(
                    skill_installer,
                    "publish_staged_exclusive",
                    side_effect=fail_second_destination,
                ),
                self.assertRaisesRegex(OSError, "second destination failed"),
            ):
                skill_installer._apply_plans(plans)
            for client in clients:
                with self.subTest(client=client.name):
                    self.assertFalse((root / client.name / "example").exists())
                    self.assertFalse(
                        (root / client.name / skill_installer.OWNERSHIP_RECORD).exists()
                    )

    def test_rollback_preserves_concurrent_target_edits(self) -> None:
        clients = client_registry().expand("both")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository, manifest = local_repository(root)
            plans = [
                skill_installer._prepare_install(
                    client,
                    root / client.name,
                    mode="copy",
                    scope="linear",
                    force=False,
                    prune=False,
                    prune_scope=False,
                    uninstall=False,
                    stage=True,
                    repo_root=repository,
                    manifest_path=manifest,
                )
                for client in clients
            ]
            second_staged = plans[1].changes[0].staged
            assert second_staged is not None
            first_target = plans[0].changes[0].target
            original_publish = skill_installer.publish_staged_exclusive

            def race_then_fail(source: Path, destination: Path) -> None:
                if Path(source) == second_staged:
                    (first_target / "USER.txt").write_text("preserve", encoding="utf-8")
                    raise OSError("second destination failed")
                original_publish(source, destination)

            with (
                patch.object(
                    skill_installer,
                    "publish_staged_exclusive",
                    side_effect=race_then_fail,
                ),
                self.assertRaises(FilesystemError) as caught,
            ):
                skill_installer._apply_plans(plans)
            self.assertEqual(caught.exception.code, "INSTALLATION_ROLLBACK_FAILED")
            self.assertEqual((first_target / "USER.txt").read_text(), "preserve")

    def test_rollback_quarantines_exact_target_before_removal(self) -> None:
        clients = client_registry().expand("both")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository, manifest = local_repository(root)
            plans = [
                skill_installer._prepare_install(
                    client,
                    root / client.name,
                    mode="copy",
                    scope="linear",
                    force=False,
                    prune=False,
                    prune_scope=False,
                    uninstall=False,
                    stage=True,
                    repo_root=repository,
                    manifest_path=manifest,
                )
                for client in clients
            ]
            first_target = plans[0].changes[0].target
            second_staged = plans[1].changes[0].staged
            assert second_staged is not None
            original_publish = skill_installer.publish_staged_exclusive
            real_replace = os.replace

            def fail_later(source: Path, destination: Path) -> None:
                if Path(source) == second_staged:
                    raise OSError("later publication failed")
                original_publish(source, destination)

            def race_quarantine(source: Path, destination: Path) -> None:
                if Path(source) == first_target and ".rollback-" in Path(destination).name:
                    (first_target / "USER.txt").write_text("preserve", encoding="utf-8")
                real_replace(source, destination)

            with (
                patch.object(
                    skill_installer,
                    "publish_staged_exclusive",
                    side_effect=fail_later,
                ),
                patch.object(snapshots.os, "replace", side_effect=race_quarantine),
                self.assertRaises(FilesystemError) as caught,
            ):
                skill_installer._apply_plans(plans)
            self.assertEqual(caught.exception.code, "INSTALLATION_ROLLBACK_FAILED")
            self.assertEqual((first_target / "USER.txt").read_text(), "preserve")

    def test_unexpected_backup_path_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "skill"
            target.write_text("old", encoding="utf-8")
            backup = target.with_name(f".{target.name}.backup-{os.getpid()}-0")
            backup.write_text("owned", encoding="utf-8")
            with self.assertRaisesRegex(OSError, "unexpected backup"):
                skill_installer._apply_changes(
                    [skill_installer.Change(target=target, staged=None)],
                    root / skill_installer.OWNERSHIP_RECORD,
                    {"skill"},
                )
            self.assertEqual(target.read_text(encoding="utf-8"), "old")
            self.assertEqual(backup.read_text(encoding="utf-8"), "owned")

    def test_install_uninstall_prune_and_unmanaged_error_paths(self) -> None:
        client = client_registry().expand("codex")[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository, manifest = local_repository(root)
            destination = root / "destination"
            preview = skill_installer.install_to(
                client,
                destination,
                mode="copy",
                scope="linear",
                force=False,
                prune=False,
                prune_scope=False,
                uninstall=False,
                dry_run=True,
                repo_root=repository,
                manifest_path=manifest,
            )
            self.assertIn("Would install 1", preview)

            manifest.write_text("missing linear\n", encoding="utf-8")
            with self.assertRaisesRegex(UsageError, "has no SKILL.md"):
                skill_installer.install_to(
                    client,
                    destination,
                    mode="link",
                    scope="linear",
                    force=False,
                    prune=False,
                    prune_scope=False,
                    uninstall=False,
                    dry_run=True,
                    repo_root=repository,
                    manifest_path=manifest,
                )

            manifest.write_text("example linear\n", encoding="utf-8")
            unmanaged = destination / "example"
            unmanaged.mkdir(parents=True)
            with self.assertRaisesRegex(UsageError, "--force never replaces"):
                skill_installer.install_to(
                    client,
                    destination,
                    mode="link",
                    scope="linear",
                    force=True,
                    prune=False,
                    prune_scope=False,
                    uninstall=False,
                    dry_run=True,
                    repo_root=repository,
                    manifest_path=manifest,
                )

            unmanaged.rmdir()
            record = destination / skill_installer.OWNERSHIP_RECORD
            record.write_text("gone\n", encoding="utf-8")
            preview = skill_installer.install_to(
                client,
                destination,
                mode="link",
                scope="linear",
                force=False,
                prune=True,
                prune_scope=True,
                uninstall=False,
                dry_run=True,
                repo_root=repository,
                manifest_path=manifest,
            )
            self.assertIn("Would install", preview)

            record.write_text("gone\n", encoding="utf-8")
            uninstall = skill_installer.install_to(
                client,
                destination,
                mode="link",
                scope="linear",
                force=False,
                prune=False,
                prune_scope=False,
                uninstall=True,
                dry_run=True,
                repo_root=repository,
                manifest_path=manifest,
            )
            self.assertIn("Would uninstall 0", uninstall)

    def test_main_prints_destinations_and_maps_usage_and_filesystem_errors(self) -> None:
        environment = {"HOME": "/tmp/linear-spanks-installer-test"}
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(
                skill_installer.main(["--client", "both", "--print-destinations"], environment),
                0,
            )
        self.assertIn("openclaude", output.getvalue())

        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(
                skill_installer.main(["--client", "both", "--dest", "/tmp/value"], environment),
                2,
            )
        with (
            patch.object(skill_installer, "_prepare_install", side_effect=OSError("io failure")),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(skill_installer.main(["--dry-run"], environment), 4)


if __name__ == "__main__":
    unittest.main()
