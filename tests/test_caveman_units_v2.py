from __future__ import annotations

import contextlib
import io
import os
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_install_caveman import create_source

from linear_spanks.core.errors import FilesystemError, GovernedStop, UsageError
from linear_spanks.installation import caveman, snapshots
from linear_spanks.installation.clients import client_registry


def write_archive(path: Path, entries: list[tuple[tarfile.TarInfo, bytes]]) -> None:
    with tarfile.open(path, "w:gz") as bundle:
        for member, content in entries:
            bundle.addfile(member, io.BytesIO(content) if member.isreg() else None)


def regular(name: str, content: bytes = b"data") -> tuple[tarfile.TarInfo, bytes]:
    member = tarfile.TarInfo(name)
    member.size = len(content)
    member.mode = 0
    return member, content


class FakeResponse(io.BytesIO):
    def __init__(self, content: bytes, content_length: str | None = None) -> None:
        super().__init__(content)
        self.headers = {} if content_length is None else {"Content-Length": content_length}

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class CavemanUnitTest(unittest.TestCase):
    def test_fetched_cache_copy_install_is_repeatable_and_uninstallable(self) -> None:
        client = client_registry().expand("codex")[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            staged_source = create_source(root)
            (staged_source / caveman.CACHE_MARKER).write_text(
                f"{caveman.UPSTREAM_REPOSITORY}\nmain\n",
                encoding="utf-8",
            )
            cache = root / "cache"
            destination = root / "destination"
            first = caveman._prepare_install(
                client,
                destination,
                staged_source,
                ("caveman",),
                mode="copy",
                uninstall=False,
                stage=True,
                installed_source_root=cache,
            )
            caveman._apply_install_plans(
                (first,),
                cache_plan=caveman.CavemanCachePlan(
                    staged=staged_source,
                    target=cache,
                    expected=caveman.snapshot_path(cache),
                ),
            )
            target = destination / "caveman"
            expected_source = str(cache / "skills" / "caveman")
            self.assertTrue(caveman._is_managed_install(target, expected_source))

            repeat = caveman._prepare_install(
                client,
                destination,
                cache,
                ("caveman",),
                mode="copy",
                uninstall=False,
                stage=True,
            )
            caveman._apply_install_plans((repeat,))
            self.assertTrue(caveman._is_managed_install(target, expected_source))

            uninstall = caveman._prepare_install(
                client,
                destination,
                cache,
                ("caveman",),
                mode="copy",
                uninstall=True,
                stage=False,
            )
            caveman._apply_install_plans((uninstall,))
            self.assertFalse(target.exists())
            self.assertFalse((destination / caveman.OWNERSHIP_RECORD).exists())

    def test_path_overrides_are_exact_and_relative_cache_links_are_absolute(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = {"HOME": str(root), "CODEX_HOME": ""}
            for option in ("--dest", "--cache-dir", "--source-dir"):
                with self.subTest(option=option):
                    stderr = io.StringIO()
                    with contextlib.redirect_stderr(stderr):
                        code = caveman.main([option, "", "--dry-run"], environment)
                    self.assertEqual(code, 2)
                    self.assertIn("non-empty and trimmed", stderr.getvalue())
            self.assertFalse((root / ".codex").exists())

            override = root / "override"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = caveman.main(
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

            staged_root = root / "staged-fetch"
            source = create_source(staged_root)
            staged = caveman.StagedCaveman(
                source,
                staged_root,
                caveman.snapshot_path(root / "relative-cache"),
            )
            destination = root / "installed"
            with (
                contextlib.chdir(root),
                patch.object(caveman, "stage_caveman", return_value=staged),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                code = caveman.main(
                    [
                        "--client",
                        "codex",
                        "--cache-dir",
                        "relative-cache",
                        "--dest",
                        str(destination),
                    ],
                    environment,
                )
            self.assertEqual(code, 0)
            installed = destination / "caveman"
            self.assertTrue(installed.is_symlink())
            self.assertTrue(installed.readlink().is_absolute())
            self.assertTrue((installed / "SKILL.md").is_file())

    def test_target_and_record_drift_after_prepare_never_overwrites_user_data(self) -> None:
        client = client_registry().expand("codex")[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = create_source(root)
            destination = root / "destination"
            create_plan = caveman._prepare_install(
                client,
                destination,
                source,
                ("caveman",),
                mode="copy",
                uninstall=False,
                stage=True,
            )
            target = destination / "caveman"
            target.mkdir()
            user_file = target / "user.txt"
            user_file.write_text("created concurrently", encoding="utf-8")
            with self.assertRaises(GovernedStop) as created:
                caveman._apply_install_plans((create_plan,))
            self.assertEqual(created.exception.code, "INSTALLATION_TARGET_DRIFT")
            self.assertEqual(user_file.read_text(encoding="utf-8"), "created concurrently")

            target.rename(root / "concurrent-caveman")
            caveman.install_to(
                client,
                destination,
                source,
                ("caveman",),
                mode="copy",
                uninstall=False,
            )
            (source / "skills" / "caveman" / "SKILL.md").write_text(
                "name: caveman\ndescription: Updated\n", encoding="utf-8"
            )
            modify_plan = caveman._prepare_install(
                client,
                destination,
                source,
                ("caveman",),
                mode="copy",
                uninstall=False,
                stage=True,
            )
            installed_file = target / "SKILL.md"
            installed_file.write_text("user changed", encoding="utf-8")
            with self.assertRaises(GovernedStop):
                caveman._apply_install_plans((modify_plan,))
            self.assertEqual(installed_file.read_text(encoding="utf-8"), "user changed")

            record_plan = caveman._prepare_install(
                client,
                destination,
                source,
                ("caveman",),
                mode="copy",
                uninstall=True,
                stage=False,
            )
            record = destination / caveman.OWNERSHIP_RECORD
            record.write_text(
                record.read_text(encoding="utf-8") + "cavecrew\t/source\n",
                encoding="utf-8",
            )
            with self.assertRaises(GovernedStop):
                caveman._apply_install_plans((record_plan,))
            self.assertTrue(target.exists())

    def test_expected_absent_target_record_and_cache_preserve_racing_data(self) -> None:
        client = client_registry().expand("codex")[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = create_source(root)
            destination = root / "destination"
            plan = caveman._prepare_install(
                client,
                destination,
                source,
                ("caveman",),
                mode="link",
                uninstall=False,
                stage=True,
            )
            target = destination / "caveman"
            original_symlink = Path.symlink_to
            injected = False

            def racing_symlink(
                path: Path, source_path: Path | str, target_is_directory: bool = False
            ) -> None:
                nonlocal injected
                if path == target and not injected:
                    injected = True
                    path.write_text("USER TARGET", encoding="utf-8")
                original_symlink(path, source_path, target_is_directory)

            with (
                patch.object(Path, "symlink_to", new=racing_symlink),
                self.assertRaises(GovernedStop),
            ):
                caveman._apply_install_plans((plan,))
            self.assertEqual(target.read_text(), "USER TARGET")

            target.unlink()
            plan = caveman._prepare_install(
                client,
                destination,
                source,
                ("caveman",),
                mode="link",
                uninstall=False,
                stage=True,
            )
            record = destination / caveman.OWNERSHIP_RECORD
            original_write = caveman.write_text_exclusive

            def racing_record(path: Path, content: str, *, mode: int = 0o600) -> None:
                if path == record:
                    path.write_text("USER RECORD\n", encoding="utf-8")
                original_write(path, content, mode=mode)

            with (
                patch.object(caveman, "write_text_exclusive", side_effect=racing_record),
                self.assertRaises(GovernedStop),
            ):
                caveman._apply_install_plans((plan,))
            self.assertEqual(record.read_text(), "USER RECORD\n")
            self.assertFalse(target.exists())

            cache = root / "cache"
            staged = root / "staged-cache"
            staged.mkdir()
            (staged / caveman.CACHE_MARKER).write_text(
                f"{caveman.UPSTREAM_REPOSITORY}\nmain\n", encoding="utf-8"
            )
            original_publish = caveman.publish_staged_exclusive

            def racing_cache(staged_path: Path, cache_path: Path) -> None:
                if cache_path == cache:
                    cache.mkdir()
                    (cache / "USER").write_text("preserve", encoding="utf-8")
                original_publish(staged_path, cache_path)

            with (
                patch.object(caveman, "publish_staged_exclusive", side_effect=racing_cache),
                self.assertRaises(GovernedStop),
            ):
                caveman.swap_managed_cache(staged, cache, caveman.snapshot_path(cache))
            self.assertEqual((cache / "USER").read_text(), "preserve")

    def test_failed_caveman_backup_moves_preserve_target_record_and_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "destination"
            destination.mkdir()
            target = destination / "caveman"
            target.write_text("old target", encoding="utf-8")
            staged_root = destination / ".staged"
            staged_root.mkdir()
            staged = staged_root / "caveman"
            staged.write_text("new target", encoding="utf-8")
            record = destination / caveman.OWNERSHIP_RECORD
            record.write_text("caveman\t/source\n", encoding="utf-8")
            real_replace = os.replace

            def fail_target(source: Path, destination_path: Path) -> None:
                if Path(source) == target:
                    raise OSError("target backup failed")
                real_replace(source, destination_path)

            with (
                patch.object(snapshots.os, "replace", side_effect=fail_target),
                self.assertRaisesRegex(OSError, "target backup failed"),
            ):
                caveman._apply_install_changes([(target, staged)], record, {"caveman": "/source"})
            self.assertEqual(target.read_text(), "old target")
            self.assertEqual(record.read_text(), "caveman\t/source\n")

            def fail_record(source: Path, destination_path: Path) -> None:
                if Path(source) == record:
                    raise OSError("record backup failed")
                real_replace(source, destination_path)

            with (
                patch.object(snapshots.os, "replace", side_effect=fail_record),
                self.assertRaisesRegex(OSError, "record backup failed"),
            ):
                caveman._apply_install_changes([], record, {"caveman": "/source"})
            self.assertEqual(record.read_text(), "caveman\t/source\n")

            cache = root / "cache"
            cache.mkdir()
            (cache / caveman.CACHE_MARKER).write_text(
                f"{caveman.UPSTREAM_REPOSITORY}\nold\n", encoding="utf-8"
            )
            (cache / "OLD").write_text("preserve", encoding="utf-8")
            staged_cache = root / "staged-cache"
            staged_cache.mkdir()
            (staged_cache / caveman.CACHE_MARKER).write_text(
                f"{caveman.UPSTREAM_REPOSITORY}\nnew\n", encoding="utf-8"
            )

            def fail_cache(source: Path, destination_path: Path) -> None:
                if Path(source) == cache:
                    raise OSError("cache backup failed")
                real_replace(source, destination_path)

            with (
                patch.object(snapshots.os, "replace", side_effect=fail_cache),
                self.assertRaisesRegex(OSError, "cache backup failed"),
            ):
                caveman._apply_install_plans(
                    (),
                    cache_plan=caveman.CavemanCachePlan(
                        staged=staged_cache,
                        target=cache,
                        expected=caveman.snapshot_path(cache),
                    ),
                )
            self.assertEqual((cache / "OLD").read_text(), "preserve")

    def test_ref_member_and_copy_validation_edges(self) -> None:
        self.assertEqual(caveman.validate_ref("release/v2.0"), "release/v2.0")
        for ref in ("../main", "bad ref"):
            with self.subTest(ref=ref), self.assertRaises(UsageError):
                caveman.validate_ref(ref)
        for name in ("", "bad\\path", "bad\x00path", "./bundle"):
            with self.subTest(name=name), self.assertRaises(UsageError):
                caveman._safe_member_path(name)

        duplicate = tarfile.TarInfo("bundle/file")
        duplicate.size = 0
        with self.assertRaisesRegex(UsageError, "Duplicate"):
            caveman._validate_members([duplicate, duplicate], caveman.DEFAULT_LIMITS)
        negative = tarfile.TarInfo("bundle/negative")
        negative.size = -1
        with self.assertRaisesRegex(UsageError, "invalid size"):
            caveman._validate_members([negative], caveman.DEFAULT_LIMITS)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(UsageError, "exceeded declared size"):
                caveman._copy_member(io.BytesIO(b"too long"), root / "long", 2)
            with self.assertRaisesRegex(UsageError, "size changed"):
                caveman._copy_member(io.BytesIO(b"x"), root / "short", 2)

    def test_successful_extraction_and_layout_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "good.tar.gz"
            folder = tarfile.TarInfo("bundle/")
            folder.type = tarfile.DIRTYPE
            write_archive(archive, [(folder, b""), regular("bundle/file", b"value")])
            extracted = caveman.safe_extract_archive(archive, root / "extracted")
            self.assertEqual((extracted / "file").read_bytes(), b"value")

            bad = root / "bad-layout.tar.gz"
            write_archive(bad, [regular("one/file"), regular("two/file")])
            with self.assertRaisesRegex(UsageError, "top-level"):
                caveman.safe_extract_archive(bad, root / "bad-extracted")
            self.assertFalse((root / "bad-extracted").exists())

    def test_download_enforces_headers_stream_limits_and_io_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(
                caveman.urllib.request,
                "urlopen",
                return_value=FakeResponse(b"data", "4"),
            ):
                target = root / "good.tar.gz"
                caveman.download_archive(
                    "https://example.test/archive", target, limits=caveman.ArchiveLimits(4, 8, 2)
                )
                self.assertEqual(target.read_bytes(), b"data")

            with (
                patch.object(
                    caveman.urllib.request,
                    "urlopen",
                    return_value=FakeResponse(b"data", "5"),
                ),
                self.assertRaisesRegex(UsageError, "Archive exceeds"),
            ):
                caveman.download_archive(
                    "https://example.test/archive",
                    root / "header.tar.gz",
                    limits=caveman.ArchiveLimits(4, 8, 2),
                )
            with (
                patch.object(
                    caveman.urllib.request,
                    "urlopen",
                    return_value=FakeResponse(b"too much"),
                ),
                self.assertRaisesRegex(UsageError, "Archive exceeds"),
            ):
                caveman.download_archive(
                    "https://example.test/archive",
                    root / "stream.tar.gz",
                    limits=caveman.ArchiveLimits(4, 8, 2),
                )
            with patch.object(caveman.urllib.request, "urlopen", side_effect=OSError("offline")):
                with self.assertRaises(FilesystemError) as caught:
                    caveman.download_archive("https://example.test/archive", root / "offline")
                self.assertEqual(caught.exception.code, "ARCHIVE_DOWNLOAD_FAILED")

    def test_skill_tree_validation_rejects_limits_special_files_and_bad_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = create_source(root)
            caveman.validate_skill_tree(source, ("caveman",))

            with self.assertRaisesRegex(UsageError, "too many members"):
                caveman.validate_skill_tree(
                    source, ("caveman",), limits=caveman.ArchiveLimits(100, 100, 0)
                )
            with self.assertRaisesRegex(UsageError, "expanded size"):
                caveman.validate_skill_tree(
                    source, ("caveman",), limits=caveman.ArchiveLimits(100, 1, 100)
                )

            fifo = source / "pipe"
            os.mkfifo(fifo)
            with self.assertRaisesRegex(UsageError, "special file"):
                caveman.validate_skill_tree(source, ("caveman",))
            fifo.unlink()

            with self.assertRaisesRegex(UsageError, "missing missing/SKILL.md"):
                caveman.validate_skill_tree(source, ("missing",))
            skill_file = source / "skills" / "caveman" / "SKILL.md"
            skill_file.write_text("name: wrong\ndescription: value\n", encoding="utf-8")
            with self.assertRaisesRegex(UsageError, "name mismatch"):
                caveman.validate_skill_tree(source, ("caveman",))
            skill_file.write_text("name: caveman\n", encoding="utf-8")
            with self.assertRaisesRegex(UsageError, "no description"):
                caveman.validate_skill_tree(source, ("caveman",))

    def test_fetch_cache_records_and_management_helpers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = create_source(root)
            cache = root / "cache" / "caveman"
            with (
                patch.object(caveman, "download_archive") as download,
                patch.object(caveman, "safe_extract_archive", return_value=source) as extract,
                patch.object(caveman, "validate_skill_tree") as validate,
                patch.object(caveman, "swap_managed_cache") as swap,
            ):
                self.assertEqual(caveman.fetch_caveman("main", cache), cache)
            self.assertTrue(download.called)
            self.assertTrue(extract.called)
            validate.assert_called_once_with(
                source, caveman.ALL_SKILLS, limits=caveman.DEFAULT_LIMITS
            )
            swap.assert_called_once_with(
                source,
                cache,
                caveman.PathSnapshot("absent", None),
            )
            self.assertTrue((source / caveman.CACHE_MARKER).is_file())

            missing_record = root / "missing-record"
            self.assertEqual(caveman._read_record(missing_record), {})
            record = root / "record"
            record.write_text("caveman\t/source\n", encoding="utf-8")
            self.assertEqual(caveman._read_record(record), {"caveman": "/source"})
            record.write_text("malformed\n", encoding="utf-8")
            with self.assertRaisesRegex(UsageError, "Malformed"):
                caveman._read_record(record)
            record.write_text("../victim\t/source\n", encoding="utf-8")
            with self.assertRaisesRegex(UsageError, "Invalid Caveman skill"):
                caveman._read_record(record)

            link = root / "link"
            link.symlink_to(source)
            self.assertTrue(caveman._is_managed_install(link, str(source)))
            self.assertFalse(caveman._is_managed_install(link, "/different"))
            copied = root / "copied"
            copied.mkdir()
            (copied / caveman.COPY_MARKER).write_text(
                f"{caveman.UPSTREAM_REPOSITORY}\n/source\n", encoding="utf-8"
            )
            self.assertTrue(caveman._is_managed_install(copied, "/source"))
            self.assertFalse(caveman._is_managed_install(copied, "/different"))
            (copied / caveman.COPY_MARKER).write_text(
                f"{caveman.UPSTREAM_REPOSITORY}\n/source\nextra\n", encoding="utf-8"
            )
            self.assertFalse(caveman._is_managed_install(copied, "/source"))
            self.assertFalse(caveman._is_managed_install(root / "absent", "/source"))

            file_path = root / "file"
            file_path.write_text("value", encoding="utf-8")
            caveman._cleanup(file_path)
            caveman._cleanup(copied)
            self.assertFalse(file_path.exists())
            self.assertFalse(copied.exists())

    def test_record_traversal_and_symlinked_cache_marker_are_never_managed(self) -> None:
        client = client_registry().expand("codex")[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = create_source(root)
            destination = root / "destination"
            destination.mkdir()
            victim = root / "victim"
            victim.mkdir()
            (victim / caveman.COPY_MARKER).write_text(
                f"{caveman.UPSTREAM_REPOSITORY}\n/source\n", encoding="utf-8"
            )
            sentinel = victim / "keep.txt"
            sentinel.write_text("owned", encoding="utf-8")
            (destination / caveman.OWNERSHIP_RECORD).write_text(
                "../victim\t/source\n", encoding="utf-8"
            )
            for uninstall in (True, False):
                with self.subTest(uninstall=uninstall), self.assertRaises(UsageError):
                    caveman._prepare_install(
                        client,
                        destination,
                        source,
                        ("caveman",),
                        mode="copy",
                        uninstall=uninstall,
                        stage=False,
                    )
                self.assertEqual(sentinel.read_text(encoding="utf-8"), "owned")

            cache = root / "cache"
            cache.mkdir()
            marker_target = root / "marker-owner"
            marker_target.write_text("managed", encoding="utf-8")
            (cache / caveman.CACHE_MARKER).symlink_to(marker_target)
            self.assertFalse(caveman._managed_cache(cache))
            staged = root / "staged-cache"
            staged.mkdir()
            (staged / caveman.CACHE_MARKER).write_text(
                f"{caveman.UPSTREAM_REPOSITORY}\nmain\n", encoding="utf-8"
            )
            with self.assertRaises(UsageError) as unmanaged:
                caveman.swap_managed_cache(staged, cache)
            self.assertEqual(unmanaged.exception.code, "UNMANAGED_CACHE")
            self.assertTrue((cache / caveman.CACHE_MARKER).is_symlink())

            for index, content in enumerate(
                (
                    "",
                    "https://example.test/foreign\nmain\n",
                    f"{caveman.UPSTREAM_REPOSITORY}\n../main\n",
                    f"{caveman.UPSTREAM_REPOSITORY}\nmain\nextra\n",
                )
            ):
                malformed_cache = root / f"malformed-cache-{index}"
                malformed_cache.mkdir()
                (malformed_cache / caveman.CACHE_MARKER).write_text(content, encoding="utf-8")
                self.assertFalse(caveman._managed_cache(malformed_cache))

    def test_copy_with_stale_recorded_source_is_preserved_as_unmanaged(self) -> None:
        client = client_registry().expand("codex")[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = create_source(root)
            destination = root / "destination"
            target = destination / "caveman"
            target.mkdir(parents=True)
            sentinel = target / "USER.txt"
            sentinel.write_text("preserve", encoding="utf-8")
            (target / caveman.COPY_MARKER).write_text(
                f"{caveman.UPSTREAM_REPOSITORY}\n/actual-source\n",
                encoding="utf-8",
            )
            (destination / caveman.OWNERSHIP_RECORD).write_text(
                "caveman\t/recorded-source\n",
                encoding="utf-8",
            )
            with self.assertRaises(UsageError) as caught:
                caveman._prepare_install(
                    client,
                    destination,
                    source,
                    ("caveman",),
                    mode="copy",
                    uninstall=True,
                    stage=False,
                )
            self.assertEqual(caught.exception.code, "UNMANAGED_ENTRY")
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")

    def test_cache_swap_success_and_incomplete_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            staged = root / "staged"
            staged.mkdir()
            (staged / caveman.CACHE_MARKER).write_text(
                f"{caveman.UPSTREAM_REPOSITORY}\nmain\n", encoding="utf-8"
            )
            cache = root / "cache"
            caveman.swap_managed_cache(staged, cache)
            self.assertTrue((cache / caveman.CACHE_MARKER).is_file())

            replacement = root / "replacement"
            replacement.mkdir()
            (replacement / caveman.CACHE_MARKER).write_text(
                f"{caveman.UPSTREAM_REPOSITORY}\nmain\n", encoding="utf-8"
            )
            (replacement / "new").write_text("new", encoding="utf-8")
            caveman.swap_managed_cache(replacement, cache)
            self.assertTrue((cache / "new").is_file())

            interrupted = root / "interrupted"
            interrupted.mkdir()
            (interrupted / caveman.CACHE_MARKER).write_text(
                f"{caveman.UPSTREAM_REPOSITORY}\nmain\n", encoding="utf-8"
            )
            original_publish = caveman.publish_staged_exclusive

            def fail_swap_and_restore(source: Path, target: Path) -> None:
                if Path(source) == interrupted or ".backup-" in Path(source).name:
                    raise OSError("replace failed")
                original_publish(source, target)

            with (
                patch.object(
                    caveman,
                    "publish_staged_exclusive",
                    side_effect=fail_swap_and_restore,
                ),
                self.assertRaises(FilesystemError) as rollback,
            ):
                caveman.swap_managed_cache(interrupted, cache)
            self.assertEqual(rollback.exception.code, "INSTALLATION_ROLLBACK_FAILED")

    def test_fetch_cache_rollback_preserves_a_concurrent_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "cache"
            cache.mkdir()
            (cache / caveman.CACHE_MARKER).write_text(
                f"{caveman.UPSTREAM_REPOSITORY}\nmain\n",
                encoding="utf-8",
            )
            (cache / "old").write_text("recoverable", encoding="utf-8")
            work = root / "fetch-work"
            staged = work / "staged"
            staged.mkdir(parents=True)
            (staged / caveman.CACHE_MARKER).write_text(
                f"{caveman.UPSTREAM_REPOSITORY}\nnext\n",
                encoding="utf-8",
            )
            package = caveman.StagedCaveman(
                source=staged,
                temporary_root=work,
                expected_cache=caveman.snapshot_path(cache),
            )
            original_publish = caveman.publish_staged_exclusive

            def race_before_failed_swap(source: Path, target: Path) -> None:
                if Path(source) == staged and Path(target) == cache:
                    cache.mkdir()
                    (cache / "concurrent").write_text("preserve", encoding="utf-8")
                    raise OSError("injected staged swap failure")
                original_publish(source, target)

            with (
                patch.object(caveman, "stage_caveman", return_value=package),
                patch.object(
                    caveman,
                    "publish_staged_exclusive",
                    side_effect=race_before_failed_swap,
                ),
                self.assertRaises(FilesystemError) as rollback,
            ):
                caveman.fetch_caveman("next", cache)

            self.assertEqual(rollback.exception.code, "INSTALLATION_ROLLBACK_FAILED")
            self.assertEqual((cache / "concurrent").read_text(encoding="utf-8"), "preserve")
            backups = tuple(root.glob(".cache.backup-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual((backups[0] / "old").read_text(encoding="utf-8"), "recoverable")
            self.assertFalse(work.exists())

    def test_interrupted_skill_install_restores_the_existing_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "destination"
            destination.mkdir()
            target = destination / "caveman"
            target.write_text("old", encoding="utf-8")
            staged_root = destination / ".staged"
            staged_root.mkdir()
            staged = staged_root / "caveman"
            staged.write_text("new", encoding="utf-8")
            record = destination / caveman.OWNERSHIP_RECORD
            record.write_text("caveman\t/source\n", encoding="utf-8")
            original_publish = caveman.publish_staged_exclusive

            def fail_staged_replace(source: Path, replacement: Path) -> None:
                if Path(source) == staged:
                    raise OSError("interrupted install")
                original_publish(source, replacement)

            with (
                patch.object(
                    caveman,
                    "publish_staged_exclusive",
                    side_effect=fail_staged_replace,
                ),
                self.assertRaisesRegex(OSError, "interrupted install"),
            ):
                caveman._apply_install_changes([(target, staged)], record, {"caveman": "/source"})
            self.assertEqual(target.read_text(encoding="utf-8"), "old")
            self.assertEqual(record.read_text(encoding="utf-8"), "caveman\t/source\n")

    def test_multi_destination_apply_failure_rolls_back_every_plan(self) -> None:
        clients = client_registry().expand("both")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = create_source(root)
            plans = [
                caveman._prepare_install(
                    client,
                    root / client.name,
                    source,
                    ("caveman",),
                    mode="link",
                    uninstall=False,
                    stage=True,
                )
                for client in clients
            ]
            second_staged = plans[1].changes[0][1]
            assert second_staged is not None
            original_publish = caveman.publish_staged_exclusive

            def fail_second_destination(source_path: Path, destination: Path) -> None:
                if Path(source_path) == second_staged:
                    raise OSError("second destination failed")
                original_publish(source_path, destination)

            with (
                patch.object(
                    caveman,
                    "publish_staged_exclusive",
                    side_effect=fail_second_destination,
                ),
                self.assertRaisesRegex(OSError, "second destination failed"),
            ):
                caveman._apply_install_plans(plans)
            for client in clients:
                with self.subTest(client=client.name):
                    self.assertFalse((root / client.name / "caveman").exists())
                    self.assertFalse((root / client.name / caveman.OWNERSHIP_RECORD).exists())

    def test_rollback_preserves_concurrent_caveman_target_edits(self) -> None:
        clients = client_registry().expand("both")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = create_source(root)
            plans = [
                caveman._prepare_install(
                    client,
                    root / client.name,
                    source,
                    ("caveman",),
                    mode="copy",
                    uninstall=False,
                    stage=True,
                )
                for client in clients
            ]
            second_staged = plans[1].changes[0][1]
            assert second_staged is not None
            first_target = plans[0].changes[0][0]
            original_publish = caveman.publish_staged_exclusive

            def race_then_fail(source_path: Path, destination: Path) -> None:
                if Path(source_path) == second_staged:
                    (first_target / "USER.txt").write_text("preserve", encoding="utf-8")
                    raise OSError("second destination failed")
                original_publish(source_path, destination)

            with (
                patch.object(
                    caveman,
                    "publish_staged_exclusive",
                    side_effect=race_then_fail,
                ),
                self.assertRaises(FilesystemError) as caught,
            ):
                caveman._apply_install_plans(plans)
            self.assertEqual(caught.exception.code, "INSTALLATION_ROLLBACK_FAILED")
            self.assertEqual((first_target / "USER.txt").read_text(), "preserve")

    def test_rollback_quarantines_caveman_target_before_removal(self) -> None:
        clients = client_registry().expand("both")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = create_source(root)
            plans = [
                caveman._prepare_install(
                    client,
                    root / client.name,
                    source,
                    ("caveman",),
                    mode="copy",
                    uninstall=False,
                    stage=True,
                )
                for client in clients
            ]
            first_target = plans[0].changes[0][0]
            second_staged = plans[1].changes[0][1]
            assert second_staged is not None
            original_publish = caveman.publish_staged_exclusive
            real_replace = os.replace

            def fail_later(source_path: Path, destination: Path) -> None:
                if Path(source_path) == second_staged:
                    raise OSError("later publication failed")
                original_publish(source_path, destination)

            def race_quarantine(source_path: Path, destination: Path) -> None:
                if Path(source_path) == first_target and ".rollback-" in Path(destination).name:
                    (first_target / "USER.txt").write_text("preserve", encoding="utf-8")
                real_replace(source_path, destination)

            with (
                patch.object(caveman, "publish_staged_exclusive", side_effect=fail_later),
                patch.object(snapshots.os, "replace", side_effect=race_quarantine),
                self.assertRaises(FilesystemError) as caught,
            ):
                caveman._apply_install_plans(plans)
            self.assertEqual(caught.exception.code, "INSTALLATION_ROLLBACK_FAILED")
            self.assertEqual((first_target / "USER.txt").read_text(), "preserve")

    def test_cache_and_destinations_share_one_rollback_boundary(self) -> None:
        clients = client_registry().expand("both")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "cache"
            old_skill = cache / "skills" / "caveman"
            old_skill.mkdir(parents=True)
            (cache / caveman.CACHE_MARKER).write_text(
                f"{caveman.UPSTREAM_REPOSITORY}\nold\n", encoding="utf-8"
            )
            (old_skill / "SKILL.md").write_text("old\n", encoding="utf-8")

            first_destination = root / clients[0].name
            first_destination.mkdir()
            live_link = first_destination / "caveman"
            live_link.symlink_to(old_skill)
            (first_destination / caveman.OWNERSHIP_RECORD).write_text(
                f"caveman\t{old_skill}\n", encoding="utf-8"
            )

            staged_root = root / "fetch"
            source = create_source(staged_root)
            (source / caveman.CACHE_MARKER).write_text(
                f"{caveman.UPSTREAM_REPOSITORY}\nnew\n", encoding="utf-8"
            )
            plans = [
                caveman._prepare_install(
                    client,
                    first_destination if index == 0 else root / client.name,
                    source,
                    ("caveman",),
                    mode="link",
                    uninstall=False,
                    stage=True,
                    installed_source_root=cache,
                )
                for index, client in enumerate(clients)
            ]
            second_staged = plans[1].changes[0][1]
            assert second_staged is not None
            original_publish = caveman.publish_staged_exclusive

            def fail_second_destination(source_path: Path, destination: Path) -> None:
                if Path(source_path) == second_staged:
                    raise OSError("second destination failed after cache swap")
                original_publish(source_path, destination)

            with (
                patch.object(
                    caveman,
                    "publish_staged_exclusive",
                    side_effect=fail_second_destination,
                ),
                self.assertRaisesRegex(OSError, "second destination failed after cache swap"),
            ):
                caveman._apply_install_plans(
                    plans,
                    cache_plan=caveman.CavemanCachePlan(
                        staged=source,
                        target=cache,
                        expected=caveman.snapshot_path(cache),
                    ),
                )

            self.assertEqual((cache / "skills" / "caveman" / "SKILL.md").read_text(), "old\n")
            self.assertEqual((live_link / "SKILL.md").read_text(), "old\n")
            self.assertFalse((root / clients[1].name / "caveman").exists())

    def test_unmanaged_second_destination_does_not_publish_staged_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "cache"
            old_skill = cache / "skills" / "caveman"
            old_skill.mkdir(parents=True)
            (cache / caveman.CACHE_MARKER).write_text(
                f"{caveman.UPSTREAM_REPOSITORY}\nold\n", encoding="utf-8"
            )
            (old_skill / "SKILL.md").write_text("old\n", encoding="utf-8")

            codex_destination = root / "codex" / "skills"
            codex_destination.mkdir(parents=True)
            live_link = codex_destination / "caveman"
            live_link.symlink_to(old_skill)
            (codex_destination / caveman.OWNERSHIP_RECORD).write_text(
                f"caveman\t{old_skill}\n", encoding="utf-8"
            )
            unmanaged = root / "openclaude" / "skills" / "caveman"
            unmanaged.mkdir(parents=True)

            staged_root = root / "fetch"
            source = create_source(staged_root)
            (source / caveman.CACHE_MARKER).write_text(
                f"{caveman.UPSTREAM_REPOSITORY}\nnew\n", encoding="utf-8"
            )
            environment = {
                "HOME": str(root),
                "CODEX_HOME": str(root / "codex"),
                "OPENCLAUDE_HOME": str(root / "openclaude"),
            }
            with (
                patch.object(
                    caveman,
                    "stage_caveman",
                    return_value=caveman.StagedCaveman(source, staged_root),
                ),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                result = caveman.main(
                    ["--client", "both", "--cache-dir", str(cache)],
                    environment,
                )

            self.assertEqual(result, 2)
            self.assertEqual((cache / "skills" / "caveman" / "SKILL.md").read_text(), "old\n")
            self.assertEqual((live_link / "SKILL.md").read_text(), "old\n")
            self.assertTrue(unmanaged.is_dir())

    def test_uninstall_missing_and_unmanaged_entries(self) -> None:
        client = client_registry().expand("codex")[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "destination"
            destination.mkdir()
            record = destination / caveman.OWNERSHIP_RECORD
            record.write_text("caveman\t/source\n", encoding="utf-8")
            message = caveman.install_to(
                client,
                destination,
                root,
                ("caveman",),
                mode="link",
                uninstall=True,
            )
            self.assertIn("Uninstalled", message)
            self.assertFalse(record.exists())

            target = destination / "caveman"
            target.mkdir()
            record.write_text("caveman\t/source\n", encoding="utf-8")
            with self.assertRaisesRegex(UsageError, "Refusing to remove unmanaged"):
                caveman.install_to(
                    client,
                    destination,
                    root,
                    ("caveman",),
                    mode="link",
                    uninstall=True,
                )

    def test_main_covers_destinations_fetch_uninstall_and_error_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = {"HOME": str(root)}
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                self.assertEqual(
                    caveman.main(["--client", "both", "--print-destinations"], environment),
                    0,
                )
            self.assertIn("codex", stdout.getvalue())

            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                self.assertEqual(
                    caveman.main(["--client", "both", "--dest", str(root)], environment), 2
                )
            self.assertIn("--dest requires", stderr.getvalue())

            missing = root / "missing"
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(
                    caveman.main(
                        ["--source-dir", str(missing), "--dest", str(root / "dest")],
                        environment,
                    ),
                    2,
                )

            source = create_source(root)
            with (
                patch.object(caveman, "validate_skill_tree", side_effect=OSError("io failure")),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(
                    caveman.main(
                        ["--source-dir", str(source), "--dest", str(root / "dest")],
                        environment,
                    ),
                    4,
                )

            staged = caveman.StagedCaveman(source, root / "staged-fetch")
            staged.temporary_root.mkdir()
            with (
                patch.object(caveman, "stage_caveman", return_value=staged) as fetch,
                patch.object(caveman, "validate_skill_tree"),
                patch.object(caveman, "_apply_install_plans") as install,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(caveman.main(["--dest", str(root / "fetched")], environment), 0)
            self.assertTrue(fetch.called)
            self.assertTrue(install.called)

            with (
                patch.object(caveman, "_apply_install_plans") as uninstall,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(
                    caveman.main(
                        [
                            "--uninstall",
                            "--cache-dir",
                            str(root / "cache"),
                            "--dest",
                            str(root / "uninstall"),
                        ],
                        environment,
                    ),
                    0,
                )
            self.assertTrue(uninstall.called)


if __name__ == "__main__":
    unittest.main()
