"""Run one Delegate-resolved agent process and classify how it ended."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os
from pathlib import Path
import re
import signal
import subprocess
import time

from .roster import Binding


EXIT_OK = "ok"
EXIT_CONFIG = "config"
EXIT_INFRA = "infrastructure"
EXIT_WORK = "work"
# Compatibility names for callers while the stable classes above are adopted.
EXIT_TIMEOUT = EXIT_WORK
EXIT_ERROR = EXIT_WORK

# Output fragments that mean the provider or CLI, not the work, failed.
# Matching one of these keeps the iteration from consuming a retry.
_CONFIG_MARKERS = (
    "not authenticated",
    "not logged in",
    "please log in",
    "please run /login",
    "authentication required",
    "unexpected argument",
    "unknown option",
    "unknown flag",
    "invalid value",
    "no such file or directory",
    "permission denied",
)
_INFRA_MARKERS = (
    "quota",
    "rate limit",
    "rate_limit",
    "overloaded",
    "at capacity",
    "too many requests",
    "usage limit",
    "network error",
    "connection refused",
    "connection reset",
    "could not resolve",
    "temporarily unavailable",
)
_SECRET_ENV_NAME = re.compile(
    r"(?:api[_-]?key|auth|credential|passwd|password|secret|token)", re.IGNORECASE
)
_KNOWN_SECRET_PATTERNS = (
    re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}\b"),
    re.compile(r"(?i)(authorization\s*:\s*(?:bearer|basic)\s+)\S+"),
)


@dataclass(frozen=True)
class Outcome:
    exit_class: str
    return_code: int | None
    log_path: Path
    detail: str
    recovery: str | None = None


def build_command(binding: Binding, cwd: Path) -> list[str]:
    """Return Delegate's argv unchanged; Delegate owns vendor construction."""

    del cwd
    return list(binding.command)


def run_agent(
    binding: Binding,
    prompt: str,
    *,
    cwd: Path,
    log_path: Path,
    timeout: float,
    environment: Mapping[str, str] | None = None,
) -> Outcome:
    command = build_command(binding, cwd)
    env = dict(os.environ if environment is None else environment)
    env.update(
        {
            "AUTOPILOT_MODEL": binding.model,
            "AUTOPILOT_EFFORT": binding.effort,
            "PWD": str(cwd),
        }
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    timed_out = False
    return_code: int | None = None
    try:
        with log_path.open("wb") as log:
            log.write(f"$ {' '.join(command)}\n\n".encode("utf-8"))
            log.flush()
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env=env,
                stdin=subprocess.PIPE,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            try:
                process.communicate(prompt.encode("utf-8"), timeout=timeout)
                return_code = process.returncode
            except subprocess.TimeoutExpired:
                timed_out = True
            finally:
                _terminate_group(process)
    except (FileNotFoundError, PermissionError) as error:
        log_path.write_text(f"cannot launch agent: {error}\n", encoding="utf-8")
        return Outcome(
            EXIT_CONFIG,
            None,
            log_path,
            f"cannot launch {command[0]}: {error}",
            "Run `delegate doctor`, fix the binding, then restart.",
        )
    output = _redact(log_path.read_bytes().decode("utf-8", errors="replace"), env)
    log_path.write_text(output, encoding="utf-8")
    elapsed = time.monotonic() - started
    if timed_out:
        return Outcome(EXIT_WORK, None, log_path, f"agent exceeded {int(timeout)}s")
    if return_code == 0:
        return Outcome(EXIT_OK, 0, log_path, f"finished in {elapsed:.0f}s")
    tail = output[-3000:].casefold()
    if any(marker in tail for marker in _CONFIG_MARKERS):
        return Outcome(
            EXIT_CONFIG,
            return_code,
            log_path,
            _last_line(output),
            "Run `delegate doctor`, fix the binding, then restart.",
        )
    if any(marker in tail for marker in _INFRA_MARKERS):
        return Outcome(EXIT_INFRA, return_code, log_path, _last_line(output))
    return Outcome(EXIT_WORK, return_code, log_path, _last_line(output))


def run_check(command: str, *, cwd: Path, timeout: float) -> tuple[bool, str]:
    """Run a verification command; return (passed, output tail)."""

    try:
        completed = subprocess.run(
            ["bash", "-lc", command],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            start_new_session=True,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, f"check exceeded {int(timeout)}s: {command}"
    output = (completed.stdout + completed.stderr).strip()
    return completed.returncode == 0, output[-3000:]


def _terminate_group(process: subprocess.Popen[bytes]) -> None:
    group = process.pid
    if process.poll() is not None and not _group_alive(group):
        return
    for signum, grace in ((signal.SIGTERM, 5.0), (signal.SIGKILL, 2.0)):
        try:
            os.killpg(group, signum)
        except ProcessLookupError:
            break
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline and _group_alive(group):
            time.sleep(0.05)
        if not _group_alive(group):
            break
    if process.poll() is None:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


def _group_alive(group: int) -> bool:
    try:
        os.killpg(group, 0)
    except (PermissionError, ProcessLookupError):
        return False
    return True


def _last_line(output: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return lines[-1][:300] if lines else "no output"


def _redact(text: str, environment: Mapping[str, str]) -> str:
    secrets = sorted(
        {
            value
            for name, value in environment.items()
            if _SECRET_ENV_NAME.search(name) and len(value) >= 6
        },
        key=len,
        reverse=True,
    )
    for secret in secrets:
        text = text.replace(secret, "<redacted>")
    for pattern in _KNOWN_SECRET_PATTERNS:
        text = pattern.sub(
            lambda match: f"{match.group(1)}<redacted>" if match.lastindex else "<redacted>",
            text,
        )
    return text
