"""Allowlisted, bounded Ripwire queries with advisory evidence and safe fallback."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import os
import selectors
import signal
import stat
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..contracts.registry import get_contract_set
from ..core.errors import LinearSpanksError, UsageError
from ..core.hashing import sha256_digest
from ..domains.context import measurement
from ..installation.ripwire import VERSION, available, binary_path, install
from .ripwire_settings import MODES, configure, resolve

KINDS = {
    "map": None,
    "task": "--for",
    "symbol": "--around",
    "callers": "--callers",
    "impact": "--impact",
    "tests": "--affected",
}
TIMEOUT = 30.0
MAX_FILE_BYTES = 1024 * 1024


@dataclass(frozen=True)
class Query:
    repo: Path
    kind: str
    selector: str = ""
    mode: str = "inherit"
    remaining_tokens: int = 4000


def inventory(repo: Path, deadline: float) -> tuple[list[str], dict[str, Any]]:
    policy = get_contract_set().contract("repository_scan")["security"]
    root_code, root_output, _ = bounded_run(
        ["git", "rev-parse", "--show-toplevel"],
        repo,
        4096,
        max(0.001, deadline - time.monotonic()),
    )
    if root_code != 0 or Path(root_output.strip()).resolve() != repo:
        raise ValueError("Resolve the actual Git repository/worktree root before querying")
    code, ignored_output, _ = bounded_run(
        ["git", "ls-files", "--others", "--ignored", "--exclude-standard", "--directory", "-z"],
        repo,
        1024 * 1024,
        max(0.001, deadline - time.monotonic()),
    )
    if code != 0:
        raise ValueError("Git ignore rules unavailable; resolve a Git repository before querying")
    ignored = {path.rstrip("/") for path in ignored_output.split("\0") if path}
    excluded: list[str] = []
    hashes: dict[str, str] = {}

    def reject(path: Path) -> bool:
        return (
            path.relative_to(repo).as_posix() in ignored
            or path.is_symlink()
            or path.name in policy["excluded_directories"]
            or any(
                fnmatch.fnmatch(path.name.lower(), pattern)
                for pattern in policy["excluded_secret_patterns"]
            )
        )

    for base, directories, files in os.walk(repo, followlinks=False):
        if time.monotonic() > deadline:
            raise TimeoutError("source inventory timed out")
        for name in sorted([*directories, *files]):
            if time.monotonic() > deadline:
                raise TimeoutError("source inventory timed out")
            path = Path(base) / name
            relative = path.relative_to(repo).as_posix()
            if reject(path):
                excluded.append(relative)
                if name in directories:
                    directories.remove(name)
                continue
            if name in files:
                # Refuse symlink swaps and special files while hashing.
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(fd, "rb") as source:
                    info = os.fstat(source.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE_BYTES:
                        excluded.append(relative)
                        continue
                    data = source.read(MAX_FILE_BYTES + 1)
                    if len(data) > MAX_FILE_BYTES:
                        raise ValueError("source grew beyond file limit")
                    hashes[relative] = hashlib.sha256(data).hexdigest()
    return sorted(excluded), {
        "source_hashes_digest": sha256_digest(hashes),
        "source_files": len(hashes),
        "policy_hash": sha256_digest(policy),
    }


def validate_selector(query: Query, exclusions: list[str]) -> None:
    if (
        query.kind not in KINDS
        or (query.kind == "map" and query.selector)
        or (query.kind != "map" and not query.selector.strip())
    ):
        raise UsageError(
            "RIPWIRE_INVALID_QUERY", "Select map or a query kind with a nonempty selector"
        )
    if len(query.selector.encode()) > 4096 or any(ord(c) < 32 for c in query.selector):
        raise UsageError(
            "RIPWIRE_INVALID_SELECTOR", "Selector contains controls or exceeds 4096 bytes"
        )
    if query.kind in {"task", "map"}:
        return
    for item in query.selector.split(","):
        file_part = item.split(":", 1)[0]
        path = Path(file_part)
        if path.is_absolute() or ".." in path.parts or "\\" in file_part:
            raise UsageError(
                "RIPWIRE_INVALID_SELECTOR", "File selectors must stay within the repository"
            )
        if "/" in file_part or path.suffix or (query.repo / file_part).exists():
            relative = path.as_posix().removeprefix("./")
            if not (query.repo / relative).is_file() or any(
                excluded in relative for excluded in exclusions
            ):
                raise UsageError("RIPWIRE_EXCLUDED_SELECTOR", "File selector is absent or excluded")
            if not (query.repo / relative).resolve().is_relative_to(query.repo):
                raise UsageError("RIPWIRE_INVALID_SELECTOR", "File selector escapes the repository")


def bounded_run(
    arguments: list[str], repo: Path, limit: int, timeout: float
) -> tuple[int, str, str]:
    process = subprocess.Popen(
        arguments, cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True
    )
    output: dict[str, bytearray] = {"stdout": bytearray(), "stderr": bytearray()}
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            assert process.stdout is not None and process.stderr is not None
            selector.register(process.stdout, selectors.EVENT_READ, "stdout")
            selector.register(process.stderr, selectors.EVENT_READ, "stderr")
            while selector.get_map():
                if time.monotonic() >= deadline:
                    raise TimeoutError("Ripwire exceeded 30-second deadline")
                for key, _ in selector.select(min(0.1, max(0, deadline - time.monotonic()))):
                    chunk = os.read(key.fd, 8192)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    stream = str(key.data)
                    output[stream].extend(chunk)
                    if len(output[stream]) > (limit if stream == "stdout" else 2048):
                        raise ValueError("Ripwire output limit exceeded")
            code = process.wait(timeout=max(0.001, deadline - time.monotonic()))
        return (
            code,
            output["stdout"].decode("utf-8", errors="strict"),
            output["stderr"].decode("utf-8", errors="replace"),
        )
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()


def query(request: Query) -> dict[str, Any]:
    start = time.monotonic()
    result: dict[str, Any] = {
        "status": "unavailable",
        "advisory": True,
        "fallback": "Use existing search and targeted source reads",
        "diagnostics": [],
    }
    try:
        setting = resolve(request.repo, request.mode)
        result["setting"] = setting
        if setting["mode"] == "off":
            result["status"] = "disabled"
            result["elapsed_ms"] = round((time.monotonic() - start) * 1000, 2)
            return result
        if request.remaining_tokens < 512:
            raise ValueError("Insufficient remaining context budget")
        if not available():
            raise ValueError("Pinned Ripwire binary unavailable; run extensions ripwire install")
        repo = request.repo.resolve(strict=True)
        if not repo.is_dir():
            raise ValueError("Repository must be a directory")
        request = Query(
            repo, request.kind, request.selector, request.mode, request.remaining_tokens
        )
        deadline = start + TIMEOUT
        exclusions, sources = inventory(repo, deadline)
        validate_selector(request, exclusions)
        limit = min(65536, (request.remaining_tokens - 256) * 2)
        arguments = [
            str(binary_path()),
            str(repo),
            "--no-cache",
            f"--max-file-size={MAX_FILE_BYTES}",
        ]
        if request.kind in {"map", "task"}:
            arguments.extend([f"--max-tokens={limit // 4}", f"--token-budget={limit // 4}"])
        elif request.kind in {"callers", "impact"}:
            arguments.append(f"--limit={max(1, limit // 512)}")
        elif request.kind == "symbol":
            arguments.append(f"--top-k={max(1, limit // 512)}")
        flag = KINDS[request.kind]
        if flag is not None:
            arguments.append(f"{flag}={request.selector}")
        arguments.extend(f"--exclude={path}" for path in exclusions)
        code, native, diagnostic = bounded_run(
            arguments, repo, limit, max(0.001, deadline - time.monotonic())
        )
        if code != 0 or not native.strip():
            raise ValueError(f"Ripwire returned unusable output (exit {code}): {diagnostic[:1024]}")
        after_exclusions, after = inventory(repo, deadline)
        if after != sources or after_exclusions != exclusions:
            raise ValueError("Repository changed during query; discard and retry")
        provenance = {
            "repository": str(repo),
            "worktree_identity": [repo.stat().st_dev, repo.stat().st_ino],
            "version": VERSION,
            "binary_sha256": hashlib.sha256(binary_path().read_bytes()).hexdigest(),
            "query": {"kind": request.kind, "selector": request.selector},
            "exclusions_hash": sha256_digest(exclusions),
            "no_cache": True,
            "output_limit_bytes": limit,
            **sources,
        }
        body = {
            "native_output": native,
            "provenance": provenance,
            "diagnostics": [diagnostic[:1024]] if diagnostic else [],
            "advisory": True,
        }
        if measurement(body)["estimated_tokens"] > request.remaining_tokens:
            raise ValueError("Evidence including provenance exceeds remaining context budget")
        result.update(
            status="ok",
            **body,
            evidence_packet={
                "measurement": measurement(body),
                "binding": sha256_digest(provenance),
            },
        )
        if measurement(result)["estimated_tokens"] + 64 > request.remaining_tokens:
            for key in ("native_output", "provenance", "evidence_packet"):
                result.pop(key)
            result["status"] = "unavailable"
            raise ValueError("Complete query envelope exceeds remaining context budget")
        result.pop("fallback")
    except (LinearSpanksError, OSError, ValueError, subprocess.SubprocessError) as error:
        result["diagnostics"] = [str(error)[:1024]]
    result["elapsed_ms"] = round((time.monotonic() - start) * 1000, 2)
    return result


def dispatch(arguments: tuple[str, ...]) -> dict[str, Any]:
    parser = argparse.ArgumentParser(
        prog="extensions ripwire", allow_abbrev=False, exit_on_error=False
    )
    parser.add_argument("action", choices=("install", "configure", "status", "query"))
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--scope", choices=("user", "repository"), default="user")
    parser.add_argument("--mode", choices=MODES, default="inherit")
    parser.add_argument("--ripwire", choices=MODES, default="inherit")
    parser.add_argument("--kind", choices=tuple(KINDS), default="map")
    parser.add_argument("--selector", default="")
    parser.add_argument("--remaining-tokens", type=int, default=4000)
    parser.add_argument("--dry-run", action="store_true")
    try:
        args, extra = parser.parse_known_args(arguments)
        if extra:
            raise ValueError("Unknown arguments: " + " ".join(extra))
    except (argparse.ArgumentError, ValueError, SystemExit) as error:
        raise UsageError("RIPWIRE_INVALID_ARGUMENTS", str(error)) from error
    supplied = {token.split("=", 1)[0] for token in arguments if token.startswith("--")}
    allowed = {
        "install": {"--dry-run"},
        "configure": {"--scope", "--repo", "--mode"},
        "status": {"--repo", "--ripwire"},
        "query": {"--repo", "--ripwire", "--kind", "--selector", "--remaining-tokens"},
    }
    if supplied - allowed[args.action]:
        raise UsageError(
            "RIPWIRE_INVALID_ARGUMENTS", "Options are not valid for this Ripwire action"
        )
    if args.action == "configure" and "--mode" not in supplied:
        raise UsageError("RIPWIRE_INVALID_ARGUMENTS", "Configure requires --mode")
    if args.action == "install":
        return install(dry_run=args.dry_run)
    repo = args.repo.resolve() if args.repo is not None else None
    if args.action == "configure":
        if args.scope == "repository" and (repo is None or not repo.is_dir()):
            raise UsageError("RIPWIRE_REPOSITORY_REQUIRED", "Repository scope requires --repo PATH")
        return configure(args.mode, repo if args.scope == "repository" else None)
    if args.action == "status":
        try:
            return {
                "available": available(),
                "version": VERSION,
                "path": str(binary_path()),
                "setting": resolve(repo, args.ripwire),
            }
        except LinearSpanksError as error:
            return {"available": False, "diagnostics": [error.message]}
    if repo is None:
        raise UsageError("RIPWIRE_REPOSITORY_REQUIRED", "Query requires --repo PATH")
    return query(Query(repo, args.kind, args.selector, args.ripwire, args.remaining_tokens))
