"""Framework-owned driver lifetime, liveness, and crash recovery."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import fcntl
import json
import math
import os
from pathlib import Path
import signal
import stat
import subprocess
import tempfile
import threading
import time
from typing import Any
import uuid

from .store import Lease, Store


RUNTIME_SCHEMA_VERSION = 1
HEARTBEAT_INTERVAL_SECONDS = 1.0
HEARTBEAT_STALE_SECONDS = 10.0


class SupervisionError(RuntimeError):
    """Base class for a driver-lifetime failure."""


class DriverBusy(SupervisionError):
    """Raised when another driver owns the flight."""


class LaunchError(SupervisionError):
    """Raised when a detached driver never establishes liveness."""


class StopSignal(BaseException):
    """Internal unwind used by a supervised driver's signal handler."""


@dataclass(frozen=True)
class DriverStatus:
    """Plain status derived only from the heartbeat record."""

    state: str
    reason: str
    run_id: str | None
    updated_at: float | None


class DriverLock:
    """An OS-released, non-blocking ownership lock for one flight driver."""

    def __init__(self, workspace: str | Path, run_id: str):
        self.workspace = Path(workspace).resolve()
        self.path = self.workspace / "driver.lock"
        self.run_id = _safe_run_id(run_id)
        self._descriptor: int | None = None

    def acquire(self) -> None:
        self.workspace.mkdir(parents=True, exist_ok=True)
        descriptor = _open_lock(self.path)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            os.close(descriptor)
            raise DriverBusy("another driver already owns this flight") from error
        try:
            owner = {
                "schema_version": RUNTIME_SCHEMA_VERSION,
                "run_id": self.run_id,
                "pid": os.getpid(),
                "pgid": os.getpgrp(),
            }
            payload = _canonical_json(owner) + b"\n"
            os.ftruncate(descriptor, 0)
            os.lseek(descriptor, 0, os.SEEK_SET)
            written = 0
            while written < len(payload):
                written += os.write(descriptor, payload[written:])
            os.fsync(descriptor)
        except BaseException:
            os.close(descriptor)
            raise
        self._descriptor = descriptor

    def release(self) -> None:
        if self._descriptor is None:
            return
        descriptor = self._descriptor
        self._descriptor = None
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)

    def __enter__(self) -> DriverLock:
        self.acquire()
        return self

    def __exit__(self, *_: object) -> None:
        self.release()


class Supervisor:
    """Hold driver ownership, publish liveness, and retain recovery intent."""

    def __init__(
        self,
        workspace: str | Path,
        product_root: str | Path,
        *,
        run_id: str | None = None,
        heartbeat_interval: float = HEARTBEAT_INTERVAL_SECONDS,
        isolate_process_group: bool = True,
    ):
        if (
            isinstance(heartbeat_interval, bool)
            or not isinstance(heartbeat_interval, (int, float))
            or heartbeat_interval <= 0
        ):
            raise ValueError("heartbeat_interval must be positive")
        self.workspace = Path(workspace).resolve()
        self.product_root = Path(product_root).resolve()
        self.run_id = _safe_run_id(run_id or uuid.uuid4().hex)
        self.heartbeat_interval = float(heartbeat_interval)
        self.isolate_process_group = isolate_process_group
        self.runtime_root = self.workspace / "runtime"
        self.heartbeat_path = self.runtime_root / "heartbeat.json"
        self.active_path = self.runtime_root / "active-task.json"
        self.drain_path = self.runtime_root / "drain.json"
        self._lock: DriverLock | None = None
        self._heartbeat_thread: threading.Thread | None = None
        self._heartbeat_stop = threading.Event()
        self._write_lock = threading.Lock()
        self._started_at = time.time()
        self._state = "starting"
        self._reason = "driver is starting"
        self._active_task_id: str | None = None
        self._closed = False

    def __enter__(self) -> Supervisor:
        if self.isolate_process_group:
            isolate_driver_process_group()
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        self._lock = DriverLock(self.workspace, self.run_id)
        self._lock.acquire()
        try:
            self._state = "running"
            self._reason = "driver is working"
            self._write_heartbeat()
            self._heartbeat_thread = threading.Thread(
                target=self._heartbeat_loop,
                name="scaffold-heartbeat",
                daemon=True,
            )
            self._heartbeat_thread.start()
        except BaseException:
            self._lock.release()
            raise
        return self

    def __exit__(self, error_type: object, *_: object) -> None:
        if not self._closed:
            if error_type is None:
                self.finish("paused", "driver exited without a terminal result")
            elif error_type is StopSignal:
                self.finish("stopped", "driver was stopped")
            else:
                self.finish("failed", "driver exited after an unexpected failure")

    def recover(self, store: Store) -> None:
        """Restore an interrupted candidate before the loop can dispatch again."""

        state = store.load()
        active = _read_optional_json(self.active_path)
        if active is None:
            leased = [task for task in state["tasks"] if task["lease"] is not None]
            if not leased:
                return
            if len(leased) != 1:
                raise SupervisionError("interrupted store has multiple active leases")
            if _git(self.product_root, "status", "--porcelain").strip():
                raise SupervisionError(
                    "interrupted flight has an unrecorded dirty product worktree"
                )
            task = leased[0]
            lease = task["lease"]
            store.apply(
                {
                    "type": "task-released",
                    "task_id": task["id"],
                    "holder": lease["holder"],
                    "lease_id": lease["lease_id"],
                    "attempt_type": "infra",
                    "reason": "driver stopped before dispatch began",
                }
            )
            return

        receipt = _normalize_active(active, self.product_root)
        try:
            task = next(
                item for item in state["tasks"] if item["id"] == receipt["task_id"]
            )
        except StopIteration as error:
            raise SupervisionError(
                f"active-task receipt names unknown task {receipt['task_id']}"
            ) from error

        if task["completion"] == "complete" and task["verdict"] == "green":
            observed_head = _git(self.product_root, "rev-parse", "HEAD").strip()
            if observed_head != task["verified_head"] or _git(
                self.product_root, "status", "--porcelain"
            ).strip():
                raise SupervisionError(
                    "verified product commit does not match the interrupted task state"
                )
            self.clear_active_task()
            return

        _restore_product(self.product_root, receipt["base_head"])
        lease = task["lease"]
        if lease is not None:
            if (
                lease["holder"] != receipt["holder"]
                or lease["lease_id"] != receipt["lease_id"]
            ):
                raise SupervisionError(
                    "active-task receipt does not own the interrupted lease"
                )
            store.apply(
                {
                    "type": "task-released",
                    "task_id": task["id"],
                    "holder": lease["holder"],
                    "lease_id": lease["lease_id"],
                    "attempt_type": "infra",
                    "reason": "driver interrupted before verification completed",
                }
            )
        self.clear_active_task()

    def task_started(
        self,
        task: Mapping[str, Any],
        lease: Lease,
        base_head: str,
    ) -> None:
        """Durably record the cleanup base before any worker can mutate product."""

        value = {
            "schema_version": RUNTIME_SCHEMA_VERSION,
            "task_id": lease.task_id,
            "holder": lease.holder,
            "lease_id": lease.lease_id,
            "base_head": base_head,
            "product_root": str(self.product_root),
        }
        _atomic_write_json(self.active_path, value, durable=True)
        self._active_task_id = lease.task_id
        self._write_heartbeat()

    def task_finished(self) -> None:
        self.clear_active_task()

    def clear_active_task(self) -> None:
        self.active_path.unlink(missing_ok=True)
        self._active_task_id = None
        self._write_heartbeat()

    def should_drain(self) -> bool:
        request = _read_optional_json(self.drain_path)
        if request is None:
            return False
        if (
            not isinstance(request, dict)
            or set(request) != {"schema_version", "run_id", "requested_at"}
            or request["schema_version"] != RUNTIME_SCHEMA_VERSION
            or request["run_id"] != self.run_id
        ):
            self.drain_path.unlink(missing_ok=True)
            return False
        requested_at = request["requested_at"]
        if (
            isinstance(requested_at, bool)
            or not isinstance(requested_at, (int, float))
            or not math.isfinite(requested_at)
            or requested_at < 0
        ):
            self.drain_path.unlink(missing_ok=True)
            return False
        return True

    def finish(self, state: str, reason: str) -> None:
        if self._closed:
            return
        if state not in {"complete", "drained", "paused", "failed", "stopped"}:
            raise ValueError(f"unsupported terminal driver state: {state}")
        self._state = state
        self._reason = reason
        self._heartbeat_stop.set()
        if (
            self._heartbeat_thread is not None
            and self._heartbeat_thread is not threading.current_thread()
        ):
            self._heartbeat_thread.join(timeout=max(1.0, self.heartbeat_interval * 2))
        self._write_heartbeat()
        if state in {"complete", "drained"}:
            self.drain_path.unlink(missing_ok=True)
        if self._lock is not None:
            self._lock.release()
        self._closed = True

    def _heartbeat_loop(self) -> None:
        while not self._heartbeat_stop.wait(self.heartbeat_interval):
            self._write_heartbeat()

    def _write_heartbeat(self) -> None:
        value = {
            "schema_version": RUNTIME_SCHEMA_VERSION,
            "run_id": self.run_id,
            "pid": os.getpid(),
            "pgid": os.getpgrp(),
            "state": self._state,
            "reason": self._reason,
            "started_at": self._started_at,
            "updated_at": time.time(),
            "active_task_id": self._active_task_id,
        }
        with self._write_lock:
            _atomic_write_json(self.heartbeat_path, value, durable=False)


def isolate_driver_process_group() -> None:
    """Put a foreground driver in its own killable process group."""

    if os.getpgrp() != os.getpid():
        os.setpgid(0, 0)


def install_stop_signal_handlers() -> dict[int, Any]:
    """Install handlers that unwind through child-process cleanup blocks."""

    previous: dict[int, Any] = {}

    def stop_driver(signum: int, _frame: object) -> None:
        raise StopSignal(f"driver received signal {signum}")

    for signum in (signal.SIGTERM, signal.SIGINT):
        previous[signum] = signal.getsignal(signum)
        signal.signal(signum, stop_driver)
    return previous


def restore_signal_handlers(previous: Mapping[int, Any]) -> None:
    for signum, handler in previous.items():
        signal.signal(signum, handler)


def request_drain(workspace: str | Path) -> None:
    root = Path(workspace).resolve()
    owner = _locked_owner(root)
    if owner is None:
        raise SupervisionError("flight has no active driver to drain")
    _atomic_write_json(
        root / "runtime" / "drain.json",
        {
            "schema_version": RUNTIME_SCHEMA_VERSION,
            "run_id": owner["run_id"],
            "requested_at": time.time(),
        },
        durable=True,
    )


def stop_driver(workspace: str | Path, *, timeout: float = 5.0) -> None:
    """Stop the exact locked driver process group without a PID liveness probe."""

    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ValueError("stop timeout must be positive")
    root = Path(workspace).resolve()
    owner = _locked_owner(root)
    if owner is None:
        raise SupervisionError("flight has no active driver to stop")
    heartbeat = _normalize_heartbeat(
        _read_required_json(root / "runtime" / "heartbeat.json")
    )
    if any(
        heartbeat[field] != owner[field] for field in ("run_id", "pid", "pgid")
    ):
        raise SupervisionError(
            "driver lock and heartbeat disagree; refusing to signal a process group"
        )
    _signal_group(owner["pgid"], signal.SIGTERM)
    deadline = time.monotonic() + float(timeout)
    while time.monotonic() < deadline:
        if _locked_owner(root) is None:
            return
        time.sleep(0.05)
    _signal_group(owner["pgid"], signal.SIGKILL)
    kill_deadline = time.monotonic() + min(2.0, float(timeout))
    while time.monotonic() < kill_deadline:
        if _locked_owner(root) is None:
            return
        time.sleep(0.05)
    raise SupervisionError("driver process group did not release its lock after stop")


def start_detached(
    command: Sequence[str],
    workspace: str | Path,
    run_id: str,
    *,
    launch_timeout: float = 5.0,
    environment: Mapping[str, str] | None = None,
) -> int:
    """Detach a driver and require its matching heartbeat as a launch handshake."""

    if not command or any(not isinstance(part, str) or not part for part in command):
        raise ValueError("detached command must contain non-empty strings")
    if (
        isinstance(launch_timeout, bool)
        or not isinstance(launch_timeout, (int, float))
        or launch_timeout <= 0
    ):
        raise ValueError("launch_timeout must be positive")
    root = Path(workspace).resolve()
    safe_run_id = _safe_run_id(run_id)
    runtime = root / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    log_path = runtime / "driver.log"
    with log_path.open("ab", buffering=0) as log:
        process = subprocess.Popen(
            list(command),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
            env=dict(environment) if environment is not None else None,
        )
    deadline = time.monotonic() + float(launch_timeout)
    heartbeat_path = runtime / "heartbeat.json"
    while time.monotonic() < deadline:
        heartbeat = _read_optional_json(heartbeat_path, malformed_is_missing=True)
        if heartbeat is not None:
            try:
                normalized = _normalize_heartbeat(heartbeat)
            except SupervisionError:
                normalized = None
            if (
                normalized is not None
                and normalized["run_id"] == safe_run_id
                and normalized["pid"] == process.pid
            ):
                return process.pid
        returncode = process.poll()
        if returncode is not None:
            raise LaunchError(
                f"driver exited with status {returncode} before publishing a heartbeat"
            )
        time.sleep(0.02)
    _signal_group(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        _signal_group(process.pid, signal.SIGKILL)
        process.wait(timeout=2)
    raise LaunchError("driver did not publish a heartbeat before launch timeout")


def read_status(
    workspace: str | Path,
    *,
    stale_after: float = HEARTBEAT_STALE_SECONDS,
    now: float | None = None,
) -> DriverStatus:
    """Read liveness from one heartbeat file; never inspect a process table."""

    if (
        isinstance(stale_after, bool)
        or not isinstance(stale_after, (int, float))
        or stale_after <= 0
    ):
        raise ValueError("stale_after must be positive")
    heartbeat_path = Path(workspace).resolve() / "runtime" / "heartbeat.json"
    try:
        heartbeat = _normalize_heartbeat(_read_required_json(heartbeat_path))
    except FileNotFoundError:
        return DriverStatus("paused", "no heartbeat has been recorded", None, None)
    except SupervisionError as error:
        return DriverStatus("paused", f"heartbeat is malformed: {error}", None, None)
    observed_at = time.time() if now is None else float(now)
    if heartbeat["state"] in {"starting", "running"}:
        age = max(0.0, observed_at - heartbeat["updated_at"])
        if age > float(stale_after):
            return DriverStatus(
                "paused",
                f"heartbeat is stale by {age:.1f} seconds",
                heartbeat["run_id"],
                heartbeat["updated_at"],
            )
    return DriverStatus(
        heartbeat["state"],
        heartbeat["reason"],
        heartbeat["run_id"],
        heartbeat["updated_at"],
    )


def _locked_owner(workspace: Path) -> dict[str, Any] | None:
    if not workspace.is_dir():
        return None
    path = workspace / "driver.lock"
    descriptor = _open_lock(path)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.lseek(descriptor, 0, os.SEEK_SET)
            payload = os.read(descriptor, 4096)
            try:
                value = json.loads(payload)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise SupervisionError("locked driver owner record is malformed") from error
            return _normalize_owner(value)
        else:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            return None
    finally:
        os.close(descriptor)


def _normalize_owner(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "schema_version", "run_id", "pid", "pgid"
    }:
        raise SupervisionError("driver owner record has the wrong fields")
    if value["schema_version"] != RUNTIME_SCHEMA_VERSION:
        raise SupervisionError("driver owner record has an unsupported schema")
    try:
        _safe_run_id(value["run_id"])
    except ValueError as error:
        raise SupervisionError("driver owner run_id is invalid") from error
    for field in ("pid", "pgid"):
        if isinstance(value[field], bool) or not isinstance(value[field], int) or value[field] <= 0:
            raise SupervisionError(f"driver owner {field} must be a positive integer")
    return dict(value)


def _normalize_heartbeat(value: Any) -> dict[str, Any]:
    required = {
        "schema_version", "run_id", "pid", "pgid", "state", "reason",
        "started_at", "updated_at", "active_task_id",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise SupervisionError("heartbeat has the wrong fields")
    owner = _normalize_owner(
        {field: value[field] for field in ("schema_version", "run_id", "pid", "pgid")}
    )
    if value["state"] not in {
        "starting", "running", "complete", "drained", "paused", "failed", "stopped"
    }:
        raise SupervisionError("heartbeat state is invalid")
    if not isinstance(value["reason"], str) or not value["reason"]:
        raise SupervisionError("heartbeat reason must be non-empty")
    for field in ("started_at", "updated_at"):
        candidate = value[field]
        if (
            isinstance(candidate, bool)
            or not isinstance(candidate, (int, float))
            or not math.isfinite(candidate)
            or candidate < 0
        ):
            raise SupervisionError(f"heartbeat {field} must be a finite timestamp")
    active = value["active_task_id"]
    if active is not None and (not isinstance(active, str) or not active):
        raise SupervisionError("heartbeat active_task_id must be text or null")
    return {**dict(value), **owner}


def _normalize_active(value: Any, product_root: Path) -> dict[str, str | int]:
    required = {
        "schema_version", "task_id", "holder", "lease_id", "base_head", "product_root"
    }
    if not isinstance(value, dict) or set(value) != required:
        raise SupervisionError("active-task receipt has the wrong fields")
    if value["schema_version"] != RUNTIME_SCHEMA_VERSION:
        raise SupervisionError("active-task receipt has an unsupported schema")
    for field in ("task_id", "holder", "lease_id", "base_head", "product_root"):
        if not isinstance(value[field], str) or not value[field]:
            raise SupervisionError(f"active-task {field} must be non-empty text")
    if Path(value["product_root"]).resolve() != product_root:
        raise SupervisionError("active-task receipt names a different product")
    return dict(value)


def _restore_product(product_root: Path, base_head: str) -> None:
    _git(product_root, "cat-file", "-e", f"{base_head}^{{commit}}")
    _git(product_root, "reset", "--hard", base_head)
    _git(product_root, "clean", "-fd")
    if _git(product_root, "rev-parse", "HEAD").strip() != base_head or _git(
        product_root, "status", "--porcelain"
    ).strip():
        raise SupervisionError("cannot restore interrupted product commit")


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
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise SupervisionError(f"git {' '.join(arguments)} failed: {detail}")
    return completed.stdout


def _signal_group(process_group: int, signum: int) -> None:
    try:
        os.killpg(process_group, signum)
    except ProcessLookupError:
        return


def _safe_run_id(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 160:
        raise ValueError("run_id must be 1-160 characters")
    if any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for character in value):
        raise ValueError("run_id contains unsafe characters")
    return value


def _read_required_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SupervisionError(f"invalid JSON in {path.name}") from error


def _open_lock(path: Path) -> int:
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as error:
        raise SupervisionError(f"cannot open driver lock: {error}") from error
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise SupervisionError("driver lock is not a regular file")
    return descriptor


def _read_optional_json(
    path: Path, *, malformed_is_missing: bool = False
) -> Any | None:
    try:
        return _read_required_json(path)
    except FileNotFoundError:
        return None
    except SupervisionError:
        if malformed_is_missing:
            return None
        raise


def _atomic_write_json(path: Path, value: Mapping[str, Any], *, durable: bool) -> None:
    payload = _canonical_json(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if durable:
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
