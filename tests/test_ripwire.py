from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from linear_spanks.contracts.compiler import compile_public_command
from linear_spanks.core.errors import UsageError
from linear_spanks.extensions import ripwire as runtime
from linear_spanks.extensions import ripwire_settings as settings
from linear_spanks.installation import ripwire as installer
from linear_spanks.installation import skill_installer

from tests.contract_support import ROOT


class RipwireFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.environment = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(self.root),
            "XDG_CONFIG_HOME": str(self.root / "config"),
        }
        self.env_patch = patch.dict(os.environ, self.environment, clear=True)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def archive(self, *, unsafe: bool = False, missing: bool = False) -> Path:
        archive = self.root / "fixture.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            for name, data in {
                "ripwire": b"#!/bin/sh\nprintf 'fixture evidence'\n",
                "LICENSE": b"MIT license",
                "hooks/hook.sh": b"do not install",
            }.items():
                if missing and name == "LICENSE":
                    continue
                entry = tarfile.TarInfo("release/" + name)
                entry.size = len(data)
                bundle.addfile(entry, io.BytesIO(data))
            if unsafe:
                link = tarfile.TarInfo("release/link")
                link.type = tarfile.SYMTYPE
                link.linkname = "/tmp"
                bundle.addfile(link)
        return archive

    def install_fixture(self, archive: Path | None = None) -> dict:
        archive = archive or self.archive()
        manifest = self.root / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "assets": {
                        installer.platform_key(): {
                            "url": "https://fixture.invalid/release",
                            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                        }
                    }
                }
            )
        )
        with (
            patch.object(installer, "RELEASE", manifest),
            patch.object(
                installer,
                "download_archive",
                side_effect=lambda _url, target: shutil.copyfile(archive, target),
            ),
        ):
            return installer.install()


class RipwireTest(RipwireFixture):
    def test_precedence_persistence_and_reenable(self) -> None:
        self.assertEqual(settings.resolve(self.repo), {"mode": "on", "source": "default"})
        settings.configure("off")
        self.assertEqual(settings.resolve(self.repo), {"mode": "off", "source": "user"})
        settings.configure("on", self.repo)
        self.assertEqual(settings.resolve(self.repo), {"mode": "on", "source": "repository"})
        self.assertEqual(settings.resolve(self.repo, "off"), {"mode": "off", "source": "run"})
        settings.configure("inherit", self.repo)
        self.assertEqual(settings.resolve(self.repo)["mode"], "off")
        settings.configure("on")
        self.assertEqual(settings.resolve(self.repo)["mode"], "on")
        settings.configure("inherit")
        self.assertEqual(settings.resolve(None)["source"], "default")
        self.assertEqual(
            settings.user_root({"HOME": str(self.root)}), self.root / ".config/linear-spanks"
        )

    def test_invalid_configuration_and_symlinks_fail_closed(self) -> None:
        path = settings.config_path(self.repo)
        path.parent.mkdir()
        for value in ["{}", '{"mode":"wat","schema_version":1}', "[]", "x" * 5000]:
            path.write_text(value)
            self.assertEqual(
                runtime.query(runtime.Query(self.repo, "map"))["status"], "unavailable"
            )
        path.unlink()
        path.symlink_to(self.root / "absent")
        with self.assertRaises(UsageError):
            settings.configure("off", self.repo)
        with self.assertRaises(UsageError):
            settings.resolve(None, "bad")
        with self.assertRaises(UsageError):
            settings.configure("bad")

    def test_disabled_does_no_inventory_or_binary_work(self) -> None:
        settings.configure("off")
        with (
            patch.object(runtime, "available", side_effect=AssertionError("binary touched")),
            patch.object(runtime, "inventory", side_effect=AssertionError("indexed")),
        ):
            self.assertEqual(runtime.query(runtime.Query(self.repo, "map"))["status"], "disabled")

    def test_compilation_is_pure_and_propagates_only_run_override(self) -> None:
        settings.configure("off", self.repo)
        with (
            patch.object(settings, "resolve", side_effect=AssertionError("configuration read")),
            patch.object(runtime, "query", side_effect=AssertionError("query called")),
        ):
            for command, args in [
                ("project run", ("P",)),
                ("milestone run", ("M", "--mode", "loop")),
                ("task run", ("T",)),
            ]:
                for mode in [None, "inherit", "on", "off"]:
                    extra = () if mode is None else ("--ripwire", mode)
                    compiled = compile_public_command(command, (*args, *extra)).contract
                    self.assertEqual(
                        compiled["ripwire"]["child_arguments"],
                        [] if mode in {None, "inherit"} else ["--ripwire", mode],
                    )
                    self.assertIn("references/ripwire.md", compiled["required_references"])
        child = self.root / "child"
        child.mkdir()
        settings.configure("on", child)
        self.assertEqual(settings.resolve(child)["mode"], "on")
        with self.assertRaises(UsageError):
            compile_public_command("project run", ("P", "--ripwire", "bad"))

    def test_install_pins_binary_licenses_ownership_and_repairs(self) -> None:
        settings.configure("off")
        self.assertEqual(self.install_fixture()["status"], "installed")
        target = installer.install_root()
        self.assertEqual({p.name for p in target.iterdir()}, {"ripwire", "LICENSE", "receipt.json"})
        self.assertTrue(installer.available())
        with patch.object(installer, "download_archive", side_effect=AssertionError("download")):
            self.assertEqual(installer.install()["status"], "available")
        self.assertEqual(settings.resolve(None)["mode"], "off")
        (target / "ripwire").write_text("damaged")
        self.assertFalse(installer.available())
        self.install_fixture()
        self.assertTrue(installer.available())

    def test_install_rejects_unowned_unsupported_checksum_and_archive(self) -> None:
        with (
            patch.object(installer.platform, "system", return_value="Windows"),
            self.assertRaises(UsageError),
        ):
            installer.install()
        target = installer.install_root()
        target.mkdir(parents=True)
        with self.assertRaisesRegex(UsageError, "unmanaged"):
            self.install_fixture()
        target.rmdir()
        with (
            patch.object(
                installer,
                "download_archive",
                side_effect=lambda _url, target: target.write_bytes(b"wrong"),
            ),
            self.assertRaisesRegex(UsageError, "checksum"),
        ):
            installer.install()
        with self.assertRaisesRegex(UsageError, "symbolic link"):
            self.install_fixture(self.archive(unsafe=True))
        with self.assertRaisesRegex(UsageError, "LICENSE"):
            self.install_fixture(self.archive(missing=True))
        self.assertFalse(target.exists())

    def test_repair_rollback_preserves_original(self) -> None:
        self.install_fixture()
        binary = installer.binary_path()
        binary.write_text("damaged but preserve on failure")
        original = skill_installer.publish_staged_exclusive

        def fail(staged: Path, target: Path) -> None:
            if target == installer.install_root() and staged.name == "published":
                raise OSError("publication failed")
            original(staged, target)

        with (
            patch.object(skill_installer, "publish_staged_exclusive", side_effect=fail),
            self.assertRaises(OSError),
        ):
            self.install_fixture()
        self.assertEqual(binary.read_text(), "damaged but preserve on failure")

    def test_default_install_optout_dryrun_and_failure_are_offline(self) -> None:
        args = ["--dest", str(self.root / "skills")]
        with (
            patch.object(installer, "install", return_value={"status": "installed"}) as install,
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(skill_installer.main([*args, "--dry-run"]), 0)
            install.assert_not_called()
            self.assertFalse((self.root / "config").exists())
            self.assertEqual(skill_installer.main(args), 0)
            install.assert_called_once()
            install.reset_mock()
            self.assertEqual(skill_installer.main([*args, "--without-ripwire"]), 0)
            self.assertEqual(skill_installer.main(args), 0)
            install.assert_not_called()
            settings.configure("on")
            install.side_effect = OSError("offline")
            self.assertEqual(skill_installer.main(args), 0)
            self.assertTrue((self.root / "skills/linear-spanks").exists())
        with patch.object(installer, "download_archive", side_effect=AssertionError("network")):
            self.assertEqual(installer.install(dry_run=True)["status"], "planned")

    def test_query_inventory_exclusions_and_dirty_freshness(self) -> None:
        self.install_fixture()
        (self.repo / "source.py").write_text("def answer():\n    return 42\n")
        (self.repo / ".env.local").write_text("SECRET")
        (self.repo / "secret.pem").write_text("SECRET")
        (self.repo / "node_modules").mkdir()
        (self.repo / "node_modules/bad.py").write_text("SECRET")
        (self.repo / "link.py").symlink_to(self.repo / "source.py")
        (self.repo / "linked").symlink_to(self.root, target_is_directory=True)
        excluded, _ = runtime.inventory(self.repo, time.monotonic() + 30)
        self.assertEqual(
            set(excluded), {".git", ".env.local", "secret.pem", "node_modules", "link.py", "linked"}
        )
        result = runtime.query(runtime.Query(self.repo, "map"))
        self.assertEqual(result["status"], "ok", result)
        self.assertEqual(result["native_output"], "fixture evidence")
        (self.repo / "source.py").write_text("def answer():\n    return 43\n")
        fresh = runtime.query(runtime.Query(self.repo, "map"))
        self.assertNotEqual(
            result["evidence_packet"]["binding"], fresh["evidence_packet"]["binding"]
        )
        for kind in ["task", "symbol", "callers", "impact", "tests"]:
            self.assertEqual(
                runtime.query(runtime.Query(self.repo, kind, "answer"))["status"], "ok"
            )
        for selector in [
            "../outside.py",
            "/outside.py",
            "link.py",
            "missing/file.py",
            ".env.local",
            "source.py\n",
            "x" * 4097,
        ]:
            self.assertEqual(
                runtime.query(runtime.Query(self.repo, "tests", selector))["status"], "unavailable"
            )
        self.assertEqual(
            runtime.query(runtime.Query(self.repo, "invalid"))["status"], "unavailable"
        )
        self.assertEqual(
            runtime.query(runtime.Query(self.repo, "map", "extra"))["status"], "unavailable"
        )

    def test_timeout_output_failure_and_unavailable_fallback(self) -> None:
        self.assertEqual(runtime.query(runtime.Query(self.repo, "map"))["status"], "unavailable")
        self.install_fixture()
        self.assertEqual(
            runtime.query(runtime.Query(self.repo, "map", remaining_tokens=1))["status"],
            "unavailable",
        )
        for code, output in [(1, "failure"), (0, "")]:
            with patch.object(runtime, "bounded_run", return_value=(code, output, "diagnostic")):
                self.assertEqual(
                    runtime.query(runtime.Query(self.repo, "map"))["status"], "unavailable"
                )
        with self.assertRaises(TimeoutError):
            runtime.bounded_run(
                [sys.executable, "-c", "import time; time.sleep(5)"], self.repo, 100, 0.05
            )
        for stream in ["stdout", "stderr"]:
            with self.assertRaisesRegex(ValueError, "output limit"):
                runtime.bounded_run(
                    [sys.executable, "-c", f"import sys; sys.{stream}.write('x'*10000)"],
                    self.repo,
                    100,
                    2,
                )
        with self.assertRaises(TimeoutError):
            runtime.inventory(self.repo, 0)
        with patch.object(runtime, "bounded_run", side_effect=TimeoutError("timeout")):
            self.assertEqual(
                runtime.query(runtime.Query(self.repo, "map"))["status"], "unavailable"
            )

    def test_drift_during_query_and_gitignore_are_not_reusable(self) -> None:
        self.install_fixture()
        nested = self.repo / "node_modules"
        nested.mkdir()
        with self.assertRaisesRegex(ValueError, "actual Git"):
            runtime.inventory(nested, time.monotonic() + 30)
        source = self.repo / "source.py"
        source.write_text("def initial(): pass\n")
        (self.repo / ".gitignore").write_text("ignored.py\n")
        (self.repo / "ignored.py").write_text("never hash me")
        excluded, before = runtime.inventory(self.repo, time.monotonic() + 30)
        self.assertIn("ignored.py", excluded)
        (self.repo / "ignored.py").write_text("changed ignored content")
        self.assertEqual(before, runtime.inventory(self.repo, time.monotonic() + 30)[1])
        original = runtime.bounded_run

        def mutate(arguments, repo, limit, timeout):
            result = original(arguments, repo, limit, timeout)
            if arguments[0] == str(installer.binary_path()):
                source.write_text("def changed(): pass\n")
            return result

        with patch.object(runtime, "bounded_run", side_effect=mutate):
            result = runtime.query(runtime.Query(self.repo, "map"))
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("changed during query", result["diagnostics"][0])
        self.assertNotIn("native_output", result)

    def test_platforms_and_license_repair(self) -> None:
        for system, architecture, expected in [
            ("Darwin", "arm64", "macos-arm64"),
            ("Darwin", "x86_64", "macos-x64"),
            ("Linux", "aarch64", "linux-arm64"),
            ("Linux", "x86_64", "linux-x64"),
        ]:
            with (
                patch.object(installer.platform, "system", return_value=system),
                patch.object(installer.platform, "machine", return_value=architecture),
            ):
                self.assertEqual(installer.platform_key(), expected)
        self.install_fixture()
        (installer.install_root() / "LICENSE").unlink()
        self.assertFalse(installer.available())
        self.install_fixture()
        self.assertTrue(installer.available())

    def test_dispatch_management_and_errors(self) -> None:
        self.assertEqual(runtime.dispatch(("configure", "--mode", "off"))["mode"], "off")
        self.assertFalse(runtime.dispatch(("status", "--repo", str(self.repo)))["available"])
        self.assertEqual(
            runtime.dispatch(("query", "--repo", str(self.repo)))["status"], "disabled"
        )
        self.assertEqual(runtime.dispatch(("install", "--dry-run"))["status"], "planned")
        for args in [
            ("bogus",),
            ("configure", "--dry-run", "--mode", "off"),
            ("install", "--mode", "off"),
            ("query",),
            ("configure", "--scope", "repository"),
            ("query", "--what"),
            ("query", "--remaining-tokens", "bad"),
        ]:
            with self.assertRaises(UsageError):
                runtime.dispatch(args)


PINNED_ARCHIVE = os.environ.get("RIPWIRE_TEST_ARCHIVE")


@unittest.skipUnless(PINNED_ARCHIVE, "set RIPWIRE_TEST_ARCHIVE to a local pinned release archive")
class PinnedRipwireTest(RipwireFixture):
    def test_pinned_discovery_exclusions_and_freshness(self) -> None:
        archive = Path(PINNED_ARCHIVE or "").resolve()
        with patch.object(
            installer,
            "download_archive",
            side_effect=lambda _url, target: shutil.copyfile(archive, target),
        ):
            installer.install()
        shutil.copytree(ROOT / "tests/fixtures/ripwire", self.repo, dirs_exist_ok=True)
        (self.repo / ".env.py").write_text("def forbidden_secret(): pass\n")
        (self.repo / "ignored.py").write_text("def forbidden_ignored(): pass\n")
        (self.repo / ".gitignore").write_text("ignored.py\n")
        (self.repo / "linked.py").symlink_to(self.repo / "ignored.py")
        cases = [
            ("map", "", "calculate_total"),
            ("task", "invoice total", "invoice_total"),
            ("symbol", "calculate_total", "calculate_total"),
            ("callers", "calculate_total", "invoice_total"),
            ("impact", "calculate_total", "invoice_total"),
            ("tests", "service.py", "test_service.py"),
        ]
        observations = []
        for kind, selector, expected in cases:
            result = runtime.query(runtime.Query(self.repo, kind, selector, remaining_tokens=8000))
            self.assertEqual(result["status"], "ok", result)
            self.assertIn(expected, result["native_output"])
            self.assertNotIn("forbidden_secret", result["native_output"])
            self.assertNotIn("forbidden_ignored", result["native_output"])
            observations.append(
                {
                    "kind": kind,
                    "bytes": result["evidence_packet"]["measurement"]["bytes"],
                    "elapsed_ms": result["elapsed_ms"],
                    "expected_found": True,
                }
            )
        before = runtime.query(runtime.Query(self.repo, "map"))
        with (self.repo / "service.py").open("a") as source:
            source.write("\ndef dirty_added_symbol(): return 1\n")
        after = runtime.query(runtime.Query(self.repo, "map"))
        self.assertIn("dirty_added_symbol", after["native_output"])
        self.assertNotEqual(
            before["evidence_packet"]["binding"], after["evidence_packet"]["binding"]
        )
        disabled = runtime.query(runtime.Query(self.repo, "map", mode="off"))
        self.assertEqual(disabled["status"], "disabled")
        baseline_start = time.monotonic()
        hits = subprocess.run(
            ["rg", "-n", "calculate_total|invoice_total", str(self.repo)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        reads = (self.repo / "service.py").read_text() + (self.repo / "test_service.py").read_text()
        self.assertIn("test_invoice_total", hits + reads)
        baseline = {
            "kind": "disabled-search-and-reads",
            "bytes": len((hits + reads).encode()),
            "elapsed_ms": round((time.monotonic() - baseline_start) * 1000, 2),
            "expected_found": True,
            "ripwire_calls": 0,
        }
        observations.extend(
            [
                {
                    "kind": "disabled-adapter",
                    "bytes": len(json.dumps(disabled).encode()),
                    "elapsed_ms": disabled["elapsed_ms"],
                    "ripwire_calls": 0,
                },
                baseline,
            ]
        )
        print("RIPWIRE_FIXTURE_MEASUREMENTS=" + json.dumps(observations))


if __name__ == "__main__":
    unittest.main()
