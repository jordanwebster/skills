"""Driver lifetime: one owner per flight, liveness by heartbeat, clean stops.

Liveness is read from a heartbeat file and ownership from an OS-released
flock, never from the process table: sandboxes routinely deny `ps`, and a
stale PID file says nothing. A detached start succeeds only when the child
publishes a matching heartbeat, so a driver that dies on launch is reported
rather than assumed running.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import threading
import time
from typing import Any
import uuid


HEARTBEAT_INTERVAL = 2.0
HEARTBEAT_STALE_AFTER = 15.0


class SupervisionError(RuntimeError):
    pass


class DriverBusy(SupervisionError):
    pass


class StopSignal(BaseException):
    """Unwinds the driver when SIGTERM/SIGINT arrives."""


@dataclass(frozen=True)
class DriverStatus:
    alive: bool
    state: str
    reason: str
    updated_at: float | None


class Supervisor:
    """Hold the flight lock and publish a heartbeat while the driver runs."""

    def __init__(self, runtime_dir: str | Path, *, interval: float = HEARTBEAT_INTERVAL):
        self.runtime_dir = Path(runtime_dir)
        self.lock_path = self.runtime_dir / "driver.lock"
        self.heartbeat_path = self.runtime_dir / "heartbeat.json"
        self.drain_path = self.runtime_dir / "drain"
        self.run_id = uuid.uuid4().hex
        self.interval = interval
        self._descriptor: int | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._state = "starting"
        self._reason = "driver is starting"
        self._closed = False

    def __enter__(self) -> Supervisor:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        if os.getpgrp() != os.getpid():
            os.setpgid(0, 0)
        descriptor = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            os.close(descriptor)
            raise DriverBusy("another driver already owns this flight") from error
        self._descriptor = descriptor
        os.ftruncate(descriptor, 0)
        os.write(descriptor, json.dumps({"run_id": self.run_id, "pid": os.getpid(),
                                          "pgid": os.getpgrp()}).encode("utf-8"))
        self.drain_path.unlink(missing_ok=True)
        self.set_state("running", "driver is working")
        self._thread = threading.Thread(target=self._beat, name="autopilot-heartbeat", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, error_type: object, *_: object) -> None:
        if self._closed:
            return
        if error_type is None:
            self.finish("stopped", "driver exited")
        elif error_type is StopSignal:
            self.finish("stopped", "driver was stopped")
        else:
            self.finish("failed", "driver exited after an unexpected failure")

    def set_state(self, state: str, reason: str) -> None:
        self._state = state
        self._reason = reason
        self._write()

    def finish(self, state: str, reason: str) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=self.interval * 2)
        self._state = state
        self._reason = reason
        self._write()
        self.drain_path.unlink(missing_ok=True)
        if self._descriptor is not None:
            fcntl.flock(self._descriptor, fcntl.LOCK_UN)
            os.close(self._descriptor)
            self._descriptor = None

    def drain_requested(self) -> bool:
        return self.drain_path.exists()

    def _beat(self) -> None:
        while not self._stop.wait(self.interval):
            self._write()

    def _write(self) -> None:
        value = {
            "run_id": self.run_id,
            "pid": os.getpid(),
            "pgid": os.getpgrp(),
            "state": self._state,
            "reason": self._reason,
            "updated_at": time.time(),
        }
        _atomic_write(self.heartbeat_path, json.dumps(value))


def install_stop_handlers() -> None:
    def handler(signum: int, _frame: object) -> None:
        raise StopSignal(f"signal {signum}")

    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, handler)


def start_detached(command: Sequence[str], runtime_dir: str | Path, *, launch_timeout: float = 10.0) -> int:
    """Launch the driver detached and wait for its heartbeat before returning."""

    runtime = Path(runtime_dir)
    runtime.mkdir(parents=True, exist_ok=True)
    heartbeat = runtime / "heartbeat.json"
    before = _read_json(heartbeat)
    with (runtime / "driver.log").open("ab") as log:
        process = subprocess.Popen(
            list(command),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    deadline = time.monotonic() + launch_timeout
    while time.monotonic() < deadline:
        current = _read_json(heartbeat)
        if current and current != before and current.get("pid") == process.pid:
            return process.pid
        if process.poll() is not None:
            raise SupervisionError(
                f"driver exited with status {process.returncode} before starting; "
                f"see {runtime / 'driver.log'}"
            )
        time.sleep(0.05)
    _signal_group(process.pid, signal.SIGKILL)
    raise SupervisionError("driver did not publish a heartbeat in time")


def read_status(runtime_dir: str | Path, *, stale_after: float = HEARTBEAT_STALE_AFTER) -> DriverStatus:
    heartbeat = _read_json(Path(runtime_dir) / "heartbeat.json")
    if not heartbeat:
        return DriverStatus(False, "idle", "no driver has run", None)
    state = str(heartbeat.get("state", "unknown"))
    reason = str(heartbeat.get("reason", ""))
    updated = float(heartbeat.get("updated_at", 0))
    if state in ("starting", "running", "paused"):
        age = time.time() - updated
        if age > stale_after:
            return DriverStatus(False, "dead", f"heartbeat stale by {age:.0f}s", updated)
        return DriverStatus(True, state, reason, updated)
    return DriverStatus(False, state, reason, updated)


def locked_owner(runtime_dir: str | Path) -> dict[str, Any] | None:
    path = Path(runtime_dir) / "driver.lock"
    if not path.exists():
        return None
    descriptor = os.open(path, os.O_RDWR)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            payload = os.read(descriptor, 4096)
            try:
                return json.loads(payload)
            except json.JSONDecodeError:
                return {}
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        return None
    finally:
        os.close(descriptor)


def request_drain(runtime_dir: str | Path) -> bool:
    """Ask the driver to stop after the current iteration; False if none runs."""

    if locked_owner(runtime_dir) is None:
        return False
    (Path(runtime_dir) / "drain").write_text("drain\n", encoding="utf-8")
    return True


def stop_driver(runtime_dir: str | Path, *, timeout: float = 10.0) -> bool:
    """Stop the running driver's whole process group; False if none runs."""

    owner = locked_owner(runtime_dir)
    if not owner or "pgid" not in owner:
        return False
    _signal_group(int(owner["pgid"]), signal.SIGTERM)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if locked_owner(runtime_dir) is None:
            return True
        time.sleep(0.1)
    _signal_group(int(owner["pgid"]), signal.SIGKILL)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if locked_owner(runtime_dir) is None:
            return True
        time.sleep(0.1)
    raise SupervisionError("driver did not release its lock after being killed")


def _signal_group(pgid: int, signum: int) -> None:
    try:
        os.killpg(pgid, signum)
    except ProcessLookupError:
        pass


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
