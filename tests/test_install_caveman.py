from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install-caveman"
SKILLS = (
    "cavecrew",
    "caveman",
    "caveman-commit",
    "caveman-compress",
    "caveman-help",
    "caveman-review",
    "caveman-stats",
)


def create_source(root: Path) -> Path:
    source = root / "caveman-source"
    for name in SKILLS:
        skill = source / "skills" / name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: Test {name} skill\n---\n# {name}\n",
            encoding="utf-8",
        )
    return source


def run_installer(source: Path, destination: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            str(INSTALLER),
            "--source-dir",
            str(source),
            "--dest",
            str(destination),
            *args,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


class InstallCavemanTest(unittest.TestCase):
    def test_core_bundle_installs_only_caveman_and_is_repeatable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = create_source(root)
            destination = root / "installed"

            first = run_installer(source, destination)
            second = run_installer(source, destination)

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(
                {path.name for path in destination.iterdir() if path.is_symlink()},
                {"caveman"},
            )
            self.assertEqual((destination / "caveman").readlink(), source / "skills" / "caveman")

    def test_all_bundle_installs_and_uninstalls_all_seven_skills(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = create_source(root)
            destination = root / "installed"

            install = run_installer(source, destination, "--bundle", "all")
            uninstall = run_installer(source, destination, "--uninstall")

            self.assertEqual(install.returncode, 0, install.stderr)
            self.assertEqual(uninstall.returncode, 0, uninstall.stderr)
            self.assertFalse(any(path.is_symlink() for path in destination.iterdir()))

    def test_copy_mode_refreshes_a_managed_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = create_source(root)
            destination = root / "installed"
            first = run_installer(source, destination, "--mode", "copy")
            self.assertEqual(first.returncode, 0, first.stderr)

            source_skill = source / "skills" / "caveman" / "SKILL.md"
            source_skill.write_text(
                source_skill.read_text(encoding="utf-8") + "updated\n", encoding="utf-8"
            )
            second = run_installer(source, destination, "--mode", "copy")

            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn(
                "updated", (destination / "caveman" / "SKILL.md").read_text(encoding="utf-8")
            )

    def test_refuses_to_replace_unmanaged_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = create_source(root)
            destination = root / "installed"
            unmanaged = destination / "caveman"
            unmanaged.mkdir(parents=True)

            result = run_installer(source, destination)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not managed", result.stderr)
            self.assertTrue(unmanaged.is_dir())

    def test_rejects_external_skill_containing_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = create_source(root)
            destination = root / "installed"
            (source / "skills" / "caveman" / "unsafe").symlink_to(root)

            result = run_installer(source, destination)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("containing symbolic links", result.stderr)
            self.assertFalse((destination / "caveman").exists())

    def test_dry_run_does_not_require_network_or_source(self) -> None:
        result = subprocess.run(
            [str(INSTALLER), "--dry-run", "--client", "antigravity", "--bundle", "all"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("JuliusBrussee/caveman@main", result.stdout)
        self.assertIn("antigravity-cli", result.stdout)
        self.assertIn("antigravity-ide", result.stdout)

    def test_multi_client_failure_does_not_partially_install(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = create_source(root)
            codex = root / "codex"
            openclaude = root / "openclaude"
            unmanaged = openclaude / "skills" / "caveman"
            unmanaged.mkdir(parents=True)
            environment = os.environ.copy()
            environment.update(
                {
                    "HOME": str(root),
                    "CODEX_HOME": str(codex),
                    "OPENCLAUDE_HOME": str(openclaude),
                }
            )
            result = subprocess.run(
                [
                    str(INSTALLER),
                    "--source-dir",
                    str(source),
                    "--client",
                    "both",
                ],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertFalse((codex / "skills" / "caveman").exists())
            self.assertTrue(unmanaged.is_dir())


if __name__ == "__main__":
    unittest.main()
