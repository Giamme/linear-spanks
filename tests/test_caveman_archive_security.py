from __future__ import annotations

import io
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "linear-spanks" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from linear_spanks.installation import caveman  # noqa: E402


def write_archive(path: Path, members: list[tuple[tarfile.TarInfo, bytes]]) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for member, content in members:
            archive.addfile(member, io.BytesIO(content) if member.isreg() else None)


def regular(name: str, content: bytes = b"data") -> tuple[tarfile.TarInfo, bytes]:
    member = tarfile.TarInfo(name)
    member.size = len(content)
    return member, content


class CavemanArchiveSecurityTest(unittest.TestCase):
    def test_rejects_absolute_and_traversal_paths(self) -> None:
        for name in ("/absolute", "bundle/../../escape"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                archive = root / "bad.tar.gz"
                write_archive(archive, [regular(name)])
                with self.assertRaisesRegex(caveman.UsageError, "Unsafe archive path"):
                    caveman.safe_extract_archive(archive, root / "staging")
                self.assertFalse((root / "escape").exists())

    def test_rejects_symbolic_and_hard_links(self) -> None:
        for member_type, label in (
            (tarfile.SYMTYPE, "symbolic link"),
            (tarfile.LNKTYPE, "hard link"),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                archive = root / "link.tar.gz"
                member = tarfile.TarInfo("bundle/link")
                member.type = member_type
                member.linkname = "../../outside"
                write_archive(archive, [(member, b"")])
                with self.assertRaisesRegex(caveman.UsageError, label):
                    caveman.safe_extract_archive(archive, root / "staging")

    def test_rejects_special_members(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "fifo.tar.gz"
            member = tarfile.TarInfo("bundle/pipe")
            member.type = tarfile.FIFOTYPE
            write_archive(archive, [(member, b"")])
            with self.assertRaisesRegex(caveman.UsageError, "special member"):
                caveman.safe_extract_archive(archive, root / "staging")

    def test_enforces_archive_expanded_and_member_limits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "limits.tar.gz"
            write_archive(
                archive,
                [regular("bundle/one", b"123456"), regular("bundle/two", b"x")],
            )
            with self.assertRaisesRegex(caveman.UsageError, "Archive exceeds"):
                caveman.safe_extract_archive(
                    archive,
                    root / "archive-limit",
                    limits=caveman.ArchiveLimits(archive_bytes=1, expanded_bytes=100, members=10),
                )
            with self.assertRaisesRegex(caveman.UsageError, "expands beyond"):
                caveman.safe_extract_archive(
                    archive,
                    root / "expanded-limit",
                    limits=caveman.ArchiveLimits(
                        archive_bytes=1024 * 1024, expanded_bytes=5, members=10
                    ),
                )
            with self.assertRaisesRegex(caveman.UsageError, "members"):
                caveman.safe_extract_archive(
                    archive,
                    root / "member-limit",
                    limits=caveman.ArchiveLimits(
                        archive_bytes=1024 * 1024,
                        expanded_bytes=1024 * 1024,
                        members=1,
                    ),
                )

    def test_member_preflight_is_incremental_and_never_calls_getmembers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "many.tar.gz"
            write_archive(
                archive,
                [regular(f"bundle/{index}", b"") for index in range(4)],
            )
            with (
                mock.patch.object(
                    tarfile.TarFile,
                    "getmembers",
                    side_effect=AssertionError("unbounded materialization"),
                ),
                self.assertRaisesRegex(caveman.UsageError, "more than 2 members"),
            ):
                caveman.safe_extract_archive(
                    archive,
                    root / "bounded",
                    limits=caveman.ArchiveLimits(
                        archive_bytes=1024 * 1024,
                        expanded_bytes=1024 * 1024,
                        members=2,
                    ),
                )

    def test_rejects_gnu_longname_and_pax_metadata_before_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            gnu_archive = root / "gnu-longname.tar.gz"
            long_member = tarfile.TarInfo(f"bundle/{'x' * 200_000}")
            long_member.size = 0
            with tarfile.open(gnu_archive, "w:gz", format=tarfile.GNU_FORMAT) as bundle:
                bundle.addfile(long_member)
            gnu_destination = root / "gnu-staging"
            with self.assertRaises(caveman.UsageError) as gnu_error:
                caveman.safe_extract_archive(
                    gnu_archive,
                    gnu_destination,
                    limits=caveman.ArchiveLimits(
                        archive_bytes=1024 * 1024,
                        expanded_bytes=1024 * 1024,
                        members=10,
                        metadata_bytes=1024,
                        path_bytes=512,
                    ),
                )
            self.assertEqual(gnu_error.exception.code, "ARCHIVE_PATH_LIMIT")
            self.assertFalse(gnu_destination.exists())

            pax_archive = root / "pax-metadata.tar.gz"
            pax_member = tarfile.TarInfo("bundle/file")
            pax_member.size = 0
            pax_member.pax_headers = {"comment": "x" * 200_000}
            with tarfile.open(pax_archive, "w:gz", format=tarfile.PAX_FORMAT) as bundle:
                bundle.addfile(pax_member)
            pax_destination = root / "pax-staging"
            with self.assertRaises(caveman.UsageError) as pax_error:
                caveman.safe_extract_archive(
                    pax_archive,
                    pax_destination,
                    limits=caveman.ArchiveLimits(
                        archive_bytes=1024 * 1024,
                        expanded_bytes=1024 * 1024,
                        members=10,
                        metadata_bytes=1024,
                        path_bytes=512,
                    ),
                )
            self.assertEqual(pax_error.exception.code, "ARCHIVE_METADATA_LIMIT")
            self.assertFalse(pax_destination.exists())

    def test_interrupted_cache_swap_restores_previous_managed_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = root / "cache"
            cache.mkdir()
            (cache / caveman.CACHE_MARKER).write_text(
                f"{caveman.UPSTREAM_REPOSITORY}\nmain\n", encoding="utf-8"
            )
            (cache / "old").write_text("preserved\n", encoding="utf-8")
            staged = root / "staged"
            staged.mkdir()
            (staged / caveman.CACHE_MARKER).write_text(
                f"{caveman.UPSTREAM_REPOSITORY}\nmain\n", encoding="utf-8"
            )
            (staged / "new").write_text("replacement\n", encoding="utf-8")
            original_publish = caveman.publish_staged_exclusive

            def fail_staged_swap(source: Path, target: Path) -> None:
                if Path(source) == staged and Path(target) == cache:
                    raise OSError("simulated interrupted swap")
                original_publish(source, target)

            with (
                mock.patch.object(
                    caveman,
                    "publish_staged_exclusive",
                    side_effect=fail_staged_swap,
                ),
                self.assertRaisesRegex(OSError, "simulated interrupted swap"),
            ):
                caveman.swap_managed_cache(staged, cache)

            self.assertEqual((cache / "old").read_text(encoding="utf-8"), "preserved\n")
            self.assertFalse((cache / "new").exists())

    def test_unmanaged_cache_is_never_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = root / "cache"
            cache.mkdir()
            (cache / "mine").write_text("keep\n", encoding="utf-8")
            staged = root / "staged"
            staged.mkdir()
            (staged / caveman.CACHE_MARKER).write_text(
                f"{caveman.UPSTREAM_REPOSITORY}\nmain\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(caveman.UsageError, "unmanaged cache"):
                caveman.swap_managed_cache(staged, cache)
            self.assertEqual((cache / "mine").read_text(encoding="utf-8"), "keep\n")


if __name__ == "__main__":
    unittest.main()
