from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install-skills"


def run_installer(destination: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(INSTALLER), "--without-ripwire", "--dest", str(destination), *args],
        cwd=ROOT,
        env={**os.environ, "XDG_CONFIG_HOME": str(destination.parent.resolve() / "test-config")},
        text=True,
        capture_output=True,
        check=False,
    )


class InstallSkillsTest(unittest.TestCase):
    def test_all_clients_install_to_their_default_destinations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            environment = os.environ.copy()
            environment.update(
                {
                    "HOME": str(home),
                    "CODEX_HOME": "",
                    "OPENCLAUDE_HOME": "",
                    "KIMI_CODE_HOME": "",
                    "XDG_CONFIG_HOME": "",
                }
            )
            result = subprocess.run(
                [str(INSTALLER), "--without-ripwire", "--client", "all", "--scope", "linear"],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            destinations = (
                home / ".codex" / "skills",
                home / ".openclaude" / "skills",
                home / ".claude" / "skills",
                home / ".gemini" / "antigravity-cli" / "skills",
                home / ".gemini" / "config" / "skills",
                home / ".kimi-code" / "skills",
                home / ".config" / "opencode" / "skills",
            )
            for destination in destinations:
                with self.subTest(destination=destination):
                    self.assertEqual(
                        {path.name for path in destination.iterdir() if path.is_symlink()},
                        {"linear-spanks", "linear-spanks-git", "linear-workflow"},
                    )

    def test_all_client_destinations_match_supported_global_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            environment = os.environ.copy()
            environment.update(
                {
                    "HOME": str(home),
                    "CODEX_HOME": "",
                    "OPENCLAUDE_HOME": "",
                    "KIMI_CODE_HOME": "",
                    "XDG_CONFIG_HOME": "",
                }
            )
            result = subprocess.run(
                [str(INSTALLER), "--client", "all", "--print-destinations"],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            destinations = dict(line.split("\t", 1) for line in result.stdout.splitlines())
            self.assertEqual(
                destinations,
                {
                    "codex": str(home / ".codex" / "skills"),
                    "openclaude": str(home / ".openclaude" / "skills"),
                    "claude": str(home / ".claude" / "skills"),
                    "antigravity-cli": str(home / ".gemini" / "antigravity-cli" / "skills"),
                    "antigravity-ide": str(home / ".gemini" / "config" / "skills"),
                    "kimi": str(home / ".kimi-code" / "skills"),
                    "opencode": str(home / ".config" / "opencode" / "skills"),
                },
            )

    def test_antigravity_alias_targets_cli_and_ide(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            environment = os.environ.copy()
            environment["HOME"] = temporary
            result = subprocess.run(
                [str(INSTALLER), "--client", "antigravity", "--print-destinations"],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                {line.split("\t", 1)[0] for line in result.stdout.splitlines()},
                {"antigravity-cli", "antigravity-ide"},
            )

    def test_default_scope_installs_only_linear_skills_and_is_repeatable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "skills"
            first = run_installer(destination)
            second = run_installer(destination)

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            links = {path.name for path in destination.iterdir() if path.is_symlink()}
            self.assertEqual(links, {"linear-spanks", "linear-spanks-git", "linear-workflow"})
            self.assertEqual(
                (destination / "linear-spanks").readlink(), ROOT / "skills" / "linear-spanks"
            )

    def test_all_scope_installs_all_manifest_skills(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "skills"
            result = run_installer(destination, "--scope", "all")

            self.assertEqual(result.returncode, 0, result.stderr)
            links = [path for path in destination.iterdir() if path.is_symlink()]
            self.assertEqual(len(links), 30)

    def test_linear_scope_installs_three_skills(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "skills"
            result = run_installer(destination, "--scope", "linear")

            self.assertEqual(result.returncode, 0, result.stderr)
            links = {path.name for path in destination.iterdir() if path.is_symlink()}
            self.assertEqual(links, {"linear-spanks", "linear-spanks-git", "linear-workflow"})

    def test_narrower_reinstall_keeps_previous_entries_managed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "skills"
            self.assertEqual(run_installer(destination, "--scope", "all").returncode, 0)
            self.assertEqual(run_installer(destination, "--scope", "linear").returncode, 0)

            uninstall = run_installer(destination, "--uninstall")

            self.assertEqual(uninstall.returncode, 0, uninstall.stderr)
            self.assertFalse(any(path.is_symlink() for path in destination.iterdir()))

    def test_prune_scope_removes_skills_outside_selected_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "skills"
            self.assertEqual(run_installer(destination, "--scope", "all").returncode, 0)

            result = run_installer(destination, "--prune-scope")

            self.assertEqual(result.returncode, 0, result.stderr)
            links = {path.name for path in destination.iterdir() if path.is_symlink()}
            self.assertEqual(links, {"linear-spanks", "linear-spanks-git", "linear-workflow"})

    def test_copy_mode_can_be_uninstalled_safely(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "skills"
            install = run_installer(destination, "--scope", "linear", "--mode", "copy")
            uninstall = run_installer(destination, "--uninstall")

            self.assertEqual(install.returncode, 0, install.stderr)
            self.assertEqual(uninstall.returncode, 0, uninstall.stderr)
            self.assertFalse((destination / "linear-spanks").exists())

    def test_refuses_to_replace_unmanaged_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "skills"
            unmanaged = destination / "linear-spanks"
            unmanaged.mkdir(parents=True)
            result = run_installer(destination, "--scope", "linear")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Destination exists", result.stderr)
            self.assertTrue(unmanaged.is_dir())

    def test_multi_client_validation_failure_leaves_every_destination_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            codex = home / "codex"
            openclaude = home / "openclaude"
            unmanaged = openclaude / "skills" / "linear-spanks"
            unmanaged.mkdir(parents=True)
            environment = os.environ.copy()
            environment.update(
                {
                    "HOME": str(home),
                    "CODEX_HOME": str(codex),
                    "OPENCLAUDE_HOME": str(openclaude),
                }
            )
            result = subprocess.run(
                [str(INSTALLER), "--client", "both", "--scope", "linear"],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertFalse((codex / "skills" / "linear-spanks").exists())
            self.assertTrue(unmanaged.is_dir())


if __name__ == "__main__":
    unittest.main()
