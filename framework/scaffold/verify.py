"""Framework-owned verification of immutable candidate commits."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time
from typing import Any

from .store import SCHEMA_VERSION, validate_task_id


CLOSED_VERDICTS = frozenset({"green", "red", "infra", "killed", "malformed"})
_MAX_RESULT_BYTES = 1024 * 1024


@dataclass(frozen=True)
class Verdict:
    """One retained, closed-enum verification outcome."""

    kind: str
    reason: str
    artifact_path: Path
    artifact_sha256: str
    protected_changes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.kind not in CLOSED_VERDICTS:
            raise ValueError(f"verdict is outside the closed enum: {self.kind}")


def verify(
    task: Mapping[str, Any],
    product_root: str | Path,
    store_root: str | Path,
    *,
    holder: str,
    lease_id: str,
    base_head: str,
    candidate_head: str,
    test_paths: Sequence[str],
    timeout: float,
    minimum_observations: int = 0,
    require_clean_worktree: bool = False,
    clock: Callable[[], float] = time.monotonic,
) -> Verdict:
    """Verify a candidate in a restored checkout and retain the result artifact."""

    task_id = validate_task_id(_required_text(task, "id"))
    check_command = _required_text(task, "check")
    _safe_component(lease_id, "lease_id")
    if not isinstance(holder, str) or not holder:
        raise ValueError("holder must be a non-empty string")
    if not isinstance(base_head, str) or not base_head:
        raise ValueError("base_head must be a non-empty string")
    if not isinstance(candidate_head, str) or not candidate_head:
        raise ValueError("candidate_head must be a non-empty string")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ValueError("verification timeout must be positive")
    if (
        isinstance(minimum_observations, bool)
        or not isinstance(minimum_observations, int)
        or minimum_observations < 0
    ):
        raise ValueError("minimum_observations must be a non-negative integer")
    if any(not isinstance(pattern, str) or not pattern for pattern in test_paths):
        raise ValueError("test_paths must contain non-empty strings")
    if not isinstance(require_clean_worktree, bool):
        raise ValueError("require_clean_worktree must be a boolean")
    test_changes = task.get("test_changes", False)
    if not isinstance(test_changes, bool):
        raise ValueError("task test_changes must be a boolean")

    product = Path(product_root).resolve()
    store = Path(store_root).resolve()
    run_root = store / "verifications" / task_id / lease_id
    store.mkdir(parents=True, exist_ok=True)
    _ensure_durable_descendant(store, run_root)
    check_id = hashlib.sha256(check_command.encode("utf-8")).hexdigest()
    common = {
        "schema_version": SCHEMA_VERSION,
        "task_id": task_id,
        "holder": holder,
        "lease_id": lease_id,
        "base_head": base_head,
        "candidate_head": candidate_head,
        "check_id": check_id,
        "check_command": check_command,
        "minimum_observations": minimum_observations,
    }

    try:
        observed_head = _git(product, "rev-parse", "HEAD").strip()
        if observed_head != candidate_head:
            return _finish(
                run_root,
                store,
                common,
                "red",
                "filed candidate is not the product repository HEAD",
            )
        if require_clean_worktree and _git(product, "status", "--porcelain").strip():
            return _finish(
                run_root,
                store,
                common,
                "red",
                "product worktree contains uncommitted worker changes",
            )
        _git(product, "cat-file", "-e", f"{base_head}^{{commit}}")
        _git(product, "cat-file", "-e", f"{candidate_head}^{{commit}}")
        if base_head == candidate_head:
            return _finish(
                run_root,
                store,
                common,
                "red",
                "candidate must add at least one new commit",
            )
        ancestor = _git_process(
            product,
            ("merge-base", "--is-ancestor", base_head, candidate_head),
        )
        if ancestor.returncode == 1:
            return _finish(
                run_root,
                store,
                common,
                "red",
                "candidate does not descend from the pre-dispatch base commit",
            )
        if ancestor.returncode != 0:
            raise RuntimeError(_git_failure(ancestor))
        candidate_tree = _git(
            product, "rev-parse", f"{candidate_head}^{{tree}}"
        ).strip()
        protected_hashes = {
            "base": _protected_hashes(product, base_head, test_paths),
            "candidate": _protected_hashes(product, candidate_head, test_paths),
        }
        protected_changes = sorted(
            set(protected_hashes["base"]) | set(protected_hashes["candidate"])
        )
        protected_changes = [
            path
            for path in protected_changes
            if protected_hashes["base"].get(path)
            != protected_hashes["candidate"].get(path)
        ]
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        return _finish(
            run_root,
            store,
            common,
            "infra",
            f"cannot restore candidate commit for verification: {error}",
        )

    context = {
        **common,
        "candidate_tree": candidate_tree,
        "protected_changes": protected_changes,
        "protected_hashes": protected_hashes,
    }
    if protected_changes and not test_changes:
        return _finish(
            run_root,
            store,
            context,
            "red",
            "out-of-scope test or check edits require judgment: "
            + ", ".join(protected_changes),
        )

    stdout_path = run_root / "stdout.txt"
    stderr_path = run_root / "stderr.txt"
    try:
        with tempfile.TemporaryDirectory(prefix="scaffold-verify-") as temporary:
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
                raise RuntimeError(
                    "git clone failed: " + _decode_detail(clone.stderr, clone.stdout)
                )
            _git(checkout, "checkout", "--quiet", "--detach", candidate_head)
            restored_tree = _git(checkout, "rev-parse", "HEAD^{tree}").strip()
            if restored_tree != candidate_tree:
                raise RuntimeError("restored checkout tree does not match candidate tree")
            result_path = Path(temporary) / "check-result.json"
            environment = os.environ.copy()
            environment.update(
                {
                    "SCAFFOLD_RESULT_PATH": str(result_path),
                    "SCAFFOLD_CANDIDATE_HEAD": candidate_head,
                    "SCAFFOLD_CHECK_ID": check_id,
                }
            )
            started = clock()
            completed = _execute_check(
                check_command,
                checkout,
                environment,
                timeout,
            )
            duration = max(0.0, clock() - started)
            _atomic_write_bytes(stdout_path, completed.stdout)
            _atomic_write_bytes(stderr_path, completed.stderr)
            if completed.timed_out:
                return _finish(
                    run_root,
                    store,
                    {
                        **context,
                        "process": {
                            "returncode": completed.returncode,
                            "duration_seconds": duration,
                            "timed_out": True,
                        },
                        "result": None,
                    },
                    "killed",
                    f"verification exceeded its {timeout:g}-second timeout",
                    (stdout_path, stderr_path),
                )
            process = {
                "returncode": completed.returncode,
                "duration_seconds": duration,
                "timed_out": False,
            }
            if completed.returncode < 0:
                return _finish(
                    run_root,
                    store,
                    {**context, "process": process, "result": None},
                    "killed",
                    f"verification process was killed by signal {-completed.returncode}",
                    (stdout_path, stderr_path),
                )
            try:
                result = _read_check_result(result_path, candidate_head, check_id)
            except ValueError as error:
                return _finish(
                    run_root,
                    store,
                    {**context, "process": process, "result": None},
                    "red",
                    str(error),
                    (stdout_path, stderr_path),
                )
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        return _finish(
            run_root,
            store,
            context,
            "infra",
            f"verification runner could not execute the check: {error}",
            tuple(path for path in (stdout_path, stderr_path) if path.exists()),
        )

    observations_green = all(
        observation["status"] == "passed" for observation in result["observations"]
    )
    if len(result["observations"]) < minimum_observations and not test_changes:
        kind = "red"
        reason = (
            "structured observation count shrank from "
            f"{minimum_observations} to {len(result['observations'])} without "
            "recorded test-change scope"
        )
    elif completed.returncode == 0 and observations_green:
        kind = "green"
        reason = f"{len(result['observations'])} structured observation(s) passed"
    elif completed.returncode != 0 and not observations_green:
        kind = "red"
        reason = "structured check observations failed"
    else:
        kind = "red"
        reason = "process exit and structured check result disagree"
    return _finish(
        run_root,
        store,
        {**context, "process": process, "result": result},
        kind,
        reason,
        (stdout_path, stderr_path),
    )


def _finish(
    run_root: Path,
    store_root: Path,
    context: Mapping[str, Any],
    kind: str,
    reason: str,
    artifacts: Sequence[Path] = (),
) -> Verdict:
    if kind not in CLOSED_VERDICTS:
        raise ValueError(f"verdict is outside the closed enum: {kind}")
    relative_artifacts = [
        str(path.resolve().relative_to(store_root)) for path in artifacts
    ]
    value = {
        **dict(context),
        "verdict": kind,
        "reason": reason,
        "artifacts": relative_artifacts,
    }
    artifact_path = run_root / "verdict.json"
    payload = _canonical_json(value) + b"\n"
    _atomic_write_bytes(artifact_path, payload)
    return Verdict(
        kind,
        reason,
        artifact_path,
        hashlib.sha256(payload).hexdigest(),
        tuple(value.get("protected_changes", ())),
    )


def _read_check_result(path: Path, candidate_head: str, check_id: str) -> dict[str, Any]:
    try:
        stat = path.lstat()
    except FileNotFoundError as error:
        raise ValueError("check did not produce a structured result artifact") from error
    if path.is_symlink() or not path.is_file():
        raise ValueError("check result artifact must be a regular file")
    if stat.st_size > _MAX_RESULT_BYTES:
        raise ValueError("check result artifact exceeds the 1 MiB limit")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"check result artifact is malformed: {error}") from error
    if not isinstance(value, dict):
        raise ValueError("check result artifact must be a JSON object")
    required = {"schema_version", "candidate_head", "check_id", "observations"}
    if set(value) != required:
        raise ValueError("check result artifact has the wrong fields")
    if value["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"check result schema_version must be {SCHEMA_VERSION}")
    if value["candidate_head"] != candidate_head:
        raise ValueError("check result names a different candidate commit")
    if value["check_id"] != check_id:
        raise ValueError("check result names a different check command")
    observations = value["observations"]
    if not isinstance(observations, list) or not observations:
        raise ValueError("check result must contain at least one observation")
    normalized: list[dict[str, str]] = []
    ids: set[str] = set()
    for observation in observations:
        if not isinstance(observation, dict) or set(observation) != {"id", "status"}:
            raise ValueError("each check observation must contain only id and status")
        observation_id = observation["id"]
        status = observation["status"]
        if not isinstance(observation_id, str) or not observation_id:
            raise ValueError("check observation id must be a non-empty string")
        if observation_id in ids:
            raise ValueError("check observation ids must be unique")
        if status not in {"passed", "failed"}:
            raise ValueError("check observation status must be passed or failed")
        ids.add(observation_id)
        normalized.append({"id": observation_id, "status": status})
    return {
        "schema_version": SCHEMA_VERSION,
        "candidate_head": candidate_head,
        "check_id": check_id,
        "observations": normalized,
    }


def _protected_hashes(
    root: Path, commit: str, patterns: Sequence[str]
) -> dict[str, str]:
    raw = _git_bytes(root, "ls-tree", "-r", "-z", commit)
    protected: dict[str, str] = {}
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
            payload = _git_bytes(root, "cat-file", "blob", object_id.decode("ascii"))
        else:
            payload = object_id
        protected[path] = hashlib.sha256(mode + b"\0" + payload).hexdigest()
    return protected


def _matches(path: str, pattern: str) -> bool:
    if fnmatch.fnmatchcase(path, pattern):
        return True
    return pattern.startswith("**/") and fnmatch.fnmatchcase(path, pattern[3:])


def _git(root: Path, *arguments: str) -> str:
    completed = _git_process(root, arguments)
    if completed.returncode != 0:
        raise RuntimeError(_git_failure(completed))
    return completed.stdout.decode("utf-8", errors="surrogateescape")


def _git_bytes(root: Path, *arguments: str) -> bytes:
    completed = _git_process(root, arguments)
    if completed.returncode != 0:
        raise RuntimeError(_git_failure(completed))
    return completed.stdout


def _git_process(
    root: Path, arguments: Sequence[str]
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=False,
        capture_output=True,
        timeout=30,
    )


def _git_failure(completed: subprocess.CompletedProcess[bytes]) -> str:
    return "git command failed: " + _decode_detail(completed.stderr, completed.stdout)


def _decode_detail(*values: bytes) -> str:
    for value in values:
        detail = value.decode("utf-8", errors="replace").strip()
        if detail:
            return detail
    return "no diagnostic output"


def _required_text(value: Mapping[str, Any], field: str) -> str:
    candidate = value.get(field)
    if not isinstance(candidate, str) or not candidate:
        raise ValueError(f"{field} must be a non-empty string")
    return candidate


def _safe_component(value: str, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,160}", value):
        raise ValueError(f"{field} must be a safe path component")
    return value


@dataclass(frozen=True)
class _CheckProcessResult:
    returncode: int
    stdout: bytes
    stderr: bytes
    timed_out: bool


def _execute_check(
    command: str,
    checkout: Path,
    environment: Mapping[str, str],
    timeout: float,
) -> _CheckProcessResult:
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
        _signal_process_group(process.pid, signal.SIGTERM)
        try:
            stdout, stderr = process.communicate(timeout=1)
        except subprocess.TimeoutExpired:
            _signal_process_group(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate(timeout=5)
    finally:
        _signal_process_group(process.pid, signal.SIGKILL)
    return _CheckProcessResult(
        process.returncode,
        stdout or b"",
        stderr or b"",
        timed_out,
    )


def _signal_process_group(process_group: int, signal_number: int) -> None:
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
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        _fsync_directory(path.parent)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _ensure_durable_descendant(root: Path, directory: Path) -> None:
    try:
        relative = directory.relative_to(root)
    except ValueError as error:
        raise ValueError(f"verification directory escapes store root: {directory}") from error
    if not root.is_dir():
        raise ValueError(f"store root is not a directory: {root}")
    parent = root
    for component in relative.parts:
        child = parent / component
        try:
            child.mkdir()
        except FileExistsError:
            if not child.is_dir():
                raise ValueError(
                    f"verification path parent is not a directory: {child}"
                )
        _fsync_directory(parent)
        parent = child


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
