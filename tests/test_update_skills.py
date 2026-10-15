import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.home = self.root / "home"
        self.home.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.env = dict(
            os.environ,
            HOME=str(self.home),
            PATH=str(self.bin) + ":" + os.environ["PATH"],
            GIT_AUTHOR_NAME="test",
            GIT_AUTHOR_EMAIL="test@test",
            GIT_COMMITTER_NAME="test",
            GIT_COMMITTER_EMAIL="test@test",
        )
        self.seed = self.root / "seed"
        self.seed.mkdir()
        self.git(self.seed, "init", "-q")
        (self.seed / "scripts").mkdir()
        shutil.copyfile(ROOT / "scripts/update-skills", self.seed / "scripts/update-skills")
        (self.seed / "skills/linear-spanks").mkdir(parents=True)
        (self.seed / "skills/linear-spanks/SKILL.md").write_text("fixture")
        (self.seed / "scripts/install-skills").write_text(
            "import json, os, sys\nfrom pathlib import Path\n"
            "if '--dry-run' not in sys.argv:\n"
            " Path(os.environ['HOME'], 'calls').write_text(json.dumps(sys.argv[1:]))\n"
            "sys.exit(int(os.environ.get('FAIL_INSTALL', '0')))\n"
        )
        (self.seed / "SKILL.md").write_text("old skill\n")
        self.git(self.seed, "add", ".")
        self.git(self.seed, "commit", "-qm", "initial")
        self.source = self.root / "checkout with spaces"
        self.git(self.root, "clone", "-q", str(self.seed), str(self.source))

    def git(self, cwd, *args):
        return (
            subprocess.check_output(
                ["git", "-C", str(cwd), *args], env=self.env, stderr=subprocess.PIPE
            )
            .decode()
            .strip()
        )

    def update(self, *args, source=None):
        return subprocess.run(
            ["/bin/bash", str((source or self.source) / "scripts/update-skills"), *args],
            env=self.env,
            cwd=self.root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

    def advance(self):
        (self.seed / "SKILL.md").write_text("new skill\n")
        self.git(self.seed, "commit", "-qam", "update")

    def test_fast_forward_invokes_refreshed_installer(self):
        self.advance()
        result = self.update()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(
            self.git(self.source, "rev-parse", "HEAD"), self.git(self.seed, "rev-parse", "HEAD")
        )
        self.assertEqual((self.home / "calls").read_text(), '["--client", "all"]')

    def test_dry_run_does_not_fetch_or_install(self):
        self.advance()
        before = self.git(self.source, "rev-parse", "HEAD")
        result = self.update("--dry-run")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.git(self.source, "rev-parse", "HEAD"), before)
        self.assertFalse((self.source / ".git/FETCH_HEAD").exists())
        self.assertFalse((self.home / "calls").exists())
        self.assertFalse((self.home / ".codex/skills/forge").exists())

    def test_dirty_checkout_rejected_but_local_refresh_allowed(self):
        (self.source / "mine").write_text("keep me")
        result = self.update()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("local changes", result.stdout)
        self.assertFalse((self.source / ".git/FETCH_HEAD").exists())
        self.assertEqual(self.update("--local").returncode, 0)
        self.assertEqual((self.source / "mine").read_text(), "keep me")

    def test_divergence_and_fetch_failure_do_not_install(self):
        self.advance()
        (self.source / "local").write_text("local work")
        self.git(self.source, "add", ".")
        self.git(self.source, "commit", "-qm", "local")
        before = self.git(self.source, "rev-parse", "HEAD")
        result = self.update()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.git(self.source, "rev-parse", "HEAD"), before)
        self.assertFalse((self.home / "calls").exists())
        self.git(self.source, "remote", "set-url", "origin", str(self.root / "absent"))
        self.assertNotEqual(self.update().returncode, 0)
        self.assertFalse((self.home / "calls").exists())

    def test_install_failure_and_options(self):
        self.env["FAIL_INSTALL"] = "7"
        result = self.update("--local", "--client", "codex", "--mode", "copy")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("retry with --local", result.stdout)
        self.assertIn('"--mode", "copy"', (self.home / "calls").read_text())

    def test_detached_and_missing_upstream(self):
        self.git(self.source, "branch", "--unset-upstream")
        self.assertIn("no upstream", self.update().stdout)
        self.git(self.source, "checkout", "--detach", "-q")
        self.assertIn("detached HEAD", self.update().stdout)
        self.assertEqual(self.update("--local").returncode, 0)

    def test_invalid_options(self):
        self.assertNotEqual(self.update("--unknown").returncode, 0)
        self.assertNotEqual(self.update("--client").returncode, 0)

    def test_real_installer_updates_all_client_copies(self):
        self.env.update(
            CODEX_HOME="",
            OPENCLAUDE_HOME="",
            KIMI_CODE_HOME="",
            XDG_CONFIG_HOME=str(self.home / ".config"),
        )
        for _ in range(2):
            result = subprocess.run(
                [
                    "bash",
                    str(ROOT / "scripts/update-skills"),
                    "--local",
                    "--mode",
                    "copy",
                    "--without-ripwire",
                ],
                env=self.env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
        for suffix in (
            ".codex/skills",
            ".openclaude/skills",
            ".claude/skills",
            ".gemini/antigravity-cli/skills",
            ".gemini/config/skills",
            ".kimi-code/skills",
            ".config/opencode/skills",
        ):
            skill = self.home / suffix / "linear-spanks"
            self.assertFalse(skill.is_symlink())
            self.assertEqual(
                (skill / "SKILL.md").read_bytes(),
                (ROOT / "skills/linear-spanks/SKILL.md").read_bytes(),
            )
