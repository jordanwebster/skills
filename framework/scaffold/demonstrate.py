"""Replay planned demonstrations against immutable product commits."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
from typing import Any

from .store import InvalidTransition, SCHEMA_VERSION, Store


_MAX_CAPTURE_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class RefreshResult:
    """Outcome of refreshing every planned demonstration at one commit."""

    fresh: bool
    reason: str
    captured_ids: tuple[str, ...]


def refresh_demonstrations(
    store: Store,
    product_root: str | Path,
    verified_head: str,
    *,
    timeout: float = 60,
    clock: Callable[[], float] = time.time,
) -> RefreshResult:
    """Validate or replay all demonstrations at ``verified_head``."""

    if not isinstance(verified_head, str) or not verified_head:
        raise ValueError("verified_head must be non-empty text")
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or timeout <= 0
    ):
        raise ValueError("demonstration timeout must be positive")
    product = Path(product_root).resolve()
    if _git(product, "rev-parse", "HEAD").strip() != verified_head:
        return RefreshResult(False, "product HEAD changed before capture", ())
    if _git(product, "status", "--porcelain").strip():
        return RefreshResult(False, "product worktree is dirty before capture", ())

    captured: list[str] = []
    state = store.load()
    for demonstration in state["demonstrations"]:
        demonstration_id = demonstration["id"]
        try:
            fingerprints = fingerprint_paths(
                product,
                verified_head,
                demonstration["surface_paths"],
            )
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            return RefreshResult(
                False,
                f"cannot fingerprint demonstration {demonstration_id}: {error}",
                tuple(captured),
            )
        if not fingerprints:
            return RefreshResult(
                False,
                f"demonstration {demonstration_id} surface paths matched no files",
                tuple(captured),
            )

        candidate = demonstration["candidate"]
        if candidate is not None:
            try:
                store.read_demonstration_capture(demonstration_id)
            except (InvalidTransition, ValueError):
                _invalidate(
                    store,
                    demonstration_id,
                    "retained capture is missing or malformed",
                )
                candidate = None
            else:
                if candidate["surface_fingerprints"] != fingerprints:
                    _invalidate(
                        store,
                        demonstration_id,
                        "a declared demonstration surface changed",
                    )
                    candidate = None
                elif candidate["verified_head"] == verified_head:
                    continue

        result = _capture(
            store,
            product,
            demonstration,
            verified_head,
            fingerprints,
            timeout=float(timeout),
            captured_at=float(clock()),
        )
        if not result.fresh:
            return RefreshResult(False, result.reason, tuple(captured))
        captured.append(demonstration_id)
    return RefreshResult(
        True,
        "every planned demonstration is fresh at the presented commit",
        tuple(captured),
    )


def fingerprint_paths(
    product_root: Path,
    commit: str,
    patterns: Sequence[str],
) -> dict[str, str]:
    """Fingerprint modes and bytes for tracked paths selected by plan globs."""

    raw = _git_bytes(product_root, "ls-tree", "-r", "-z", commit)
    fingerprints: dict[str, str] = {}
    for item in raw.split(b"\0"):
        if not item:
            continue
        try:
            metadata, raw_path = item.split(b"\t", 1)
            mode, object_type, object_id = metadata.split(b" ", 2)
        except ValueError as error:
            raise RuntimeError("git ls-tree returned malformed output") from error
        path = raw_path.decode("utf-8", errors="surrogateescape")
        if not any(_matches(path, pattern) for pattern in patterns):
            continue
        if object_type == b"blob":
            payload = _git_bytes(
                product_root,
                "cat-file",
                "blob",
                object_id.decode("ascii"),
            )
        else:
            payload = object_id
        fingerprints[path] = hashlib.sha256(mode + b"\0" + payload).hexdigest()
    return fingerprints


def _capture(
    store: Store,
    product: Path,
    demonstration: Mapping[str, Any],
    verified_head: str,
    fingerprints: Mapping[str, str],
    *,
    timeout: float,
    captured_at: float,
) -> RefreshResult:
    demonstration_id = demonstration["id"]
    with tempfile.TemporaryDirectory(prefix="scaffold-demonstrate-") as temporary:
        checkout = Path(temporary) / "candidate"
        clone = subprocess.run(
            [
                "git",
                "clone",
                "--quiet",
                "--no-checkout",
                "--shared",
                str(product),
                str(checkout),
            ],
            check=False,
            capture_output=True,
            timeout=timeout,
        )
        if clone.returncode != 0:
            return RefreshResult(
                False,
                f"cannot restore demonstration {demonstration_id}: "
                + _decode_detail(clone.stderr, clone.stdout),
                (),
            )
        _git(checkout, "checkout", "--quiet", "--detach", verified_head)
        _git(checkout, "remote", "remove", "origin")
        environment = os.environ.copy()
        environment.update(
            {
                "SCAFFOLD_DEMONSTRATION_ID": demonstration_id,
                "SCAFFOLD_PRESENTED_HEAD": verified_head,
            }
        )
        completed = _execute(
            demonstration["command"],
            checkout,
            environment,
            timeout,
        )
        if completed.timed_out:
            return RefreshResult(
                False,
                f"demonstration {demonstration_id} exceeded its timeout",
                (),
            )
        if completed.returncode != 0:
            detail = _decode_detail(completed.stderr, completed.stdout)
            return RefreshResult(
                False,
                f"demonstration {demonstration_id} failed: {detail}",
                (),
            )
        if (
            len(completed.stdout) > _MAX_CAPTURE_BYTES
            or len(completed.stderr) > _MAX_CAPTURE_BYTES
        ):
            return RefreshResult(
                False,
                f"demonstration {demonstration_id} transcript exceeds 16 MiB",
                (),
            )

        capture_root = (
            store.root / "demonstrations" / demonstration_id / verified_head
        )
        outputs = [
            _retain_output(
                store,
                capture_root / "stdout.txt",
                completed.stdout,
                kind="stdout",
                source="",
            ),
            _retain_output(
                store,
                capture_root / "stderr.txt",
                completed.stderr,
                kind="stderr",
                source="",
            ),
        ]
        for relative_name in demonstration["artifact_paths"]:
            source = (checkout / relative_name).resolve()
            if os.path.commonpath([checkout.resolve(), source]) != str(
                checkout.resolve()
            ):
                return RefreshResult(
                    False,
                    f"demonstration artifact escapes its checkout: {relative_name}",
                    (),
                )
            try:
                stat = source.lstat()
                payload = source.read_bytes()
            except OSError as error:
                return RefreshResult(
                    False,
                    f"demonstration artifact is unavailable: {relative_name}: {error}",
                    (),
                )
            if source.is_symlink() or not source.is_file():
                return RefreshResult(
                    False,
                    f"demonstration artifact is not a regular file: {relative_name}",
                    (),
                )
            if stat.st_size > _MAX_CAPTURE_BYTES or len(payload) > _MAX_CAPTURE_BYTES:
                return RefreshResult(
                    False,
                    f"demonstration artifact exceeds 16 MiB: {relative_name}",
                    (),
                )
            outputs.append(
                _retain_output(
                    store,
                    capture_root / "files" / relative_name,
                    payload,
                    kind="artifact",
                    source=relative_name,
                )
            )

    artifact = {
        "schema_version": SCHEMA_VERSION,
        "demonstration_id": demonstration_id,
        "title": demonstration["title"],
        "command": demonstration["command"],
        "verified_head": verified_head,
        "surface_fingerprints": dict(fingerprints),
        "captured_at": captured_at,
        "process": {"returncode": 0, "timed_out": False},
        "outputs": outputs,
    }
    artifact_path = capture_root / "capture.json"
    payload = _canonical_json(artifact) + b"\n"
    _atomic_write_bytes(artifact_path, payload)
    candidate = {
        "verified_head": verified_head,
        "artifact_path": str(artifact_path.relative_to(store.root)),
        "artifact_sha256": hashlib.sha256(payload).hexdigest(),
        "surface_fingerprints": dict(fingerprints),
        "captured_at": captured_at,
    }
    store.apply(
        {
            "type": "demonstration-captured",
            "demonstration_id": demonstration_id,
            "candidate": candidate,
        }
    )
    return RefreshResult(True, "capture retained", (demonstration_id,))


def _invalidate(store: Store, demonstration_id: str, reason: str) -> None:
    store.apply(
        {
            "type": "demonstration-invalidated",
            "demonstration_id": demonstration_id,
            "reason": reason,
        }
    )


@dataclass(frozen=True)
class _ProcessResult:
    returncode: int
    stdout: bytes
    stderr: bytes
    timed_out: bool


def _execute(
    command: str,
    checkout: Path,
    environment: Mapping[str, str],
    timeout: float,
) -> _ProcessResult:
    process = subprocess.Popen(
        command,
        cwd=checkout,
        shell=True,
        executable="/bin/sh",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=dict(environment),
        start_new_session=True,
    )
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _signal_group(process.pid, signal.SIGTERM)
        try:
            stdout, stderr = process.communicate(timeout=1)
        except subprocess.TimeoutExpired:
            _signal_group(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate(timeout=5)
    finally:
        _signal_group(process.pid, signal.SIGKILL)
    return _ProcessResult(
        process.returncode,
        stdout or b"",
        stderr or b"",
        timed_out,
    )


def _retain_output(
    store: Store,
    path: Path,
    payload: bytes,
    *,
    kind: str,
    source: str,
) -> dict[str, Any]:
    _atomic_write_bytes(path, payload)
    return {
        "kind": kind,
        "source": source,
        "path": str(path.relative_to(store.root)),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size": len(payload),
    }


def _matches(path: str, pattern: str) -> bool:
    if fnmatch.fnmatchcase(path, pattern):
        return True
    return pattern.startswith("**/") and fnmatch.fnmatchcase(path, pattern[3:])


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "git command failed: " + _decode_detail(
                completed.stderr.encode(), completed.stdout.encode()
            )
        )
    return completed.stdout


def _git_bytes(root: Path, *arguments: str) -> bytes:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=False,
        capture_output=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "git command failed: " + _decode_detail(
                completed.stderr, completed.stdout
            )
        )
    return completed.stdout


def _decode_detail(*values: bytes) -> str:
    for value in values:
        detail = value.decode("utf-8", errors="replace").strip()
        if detail:
            return detail
    return "no diagnostic output"


def _signal_group(process_group: int, signal_number: int) -> None:
    try:
        os.killpg(process_group, signal_number)
    except ProcessLookupError:
        pass


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
