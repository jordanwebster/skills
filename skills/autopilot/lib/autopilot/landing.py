"""Validate and render a closer's proof through Handoff's public CLI."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shlex
import subprocess
from typing import Any


@dataclass(frozen=True)
class Result:
    ok: bool
    output: Path | None
    detail: str
    recovery: str | None = None
    payload: Mapping[str, Any] | None = None


def finish(workspace: Path, *, environment: Mapping[str, str] | None = None) -> Result:
    selected_environment = dict(os.environ if environment is None else environment)
    invocation = command(selected_environment)
    invocation += ["finish", str(workspace), "--json", "--no-open"]
    try:
        completed = subprocess.run(
            invocation,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            env=selected_environment,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return Result(False, None, f"cannot run Handoff: {error}", "Install Handoff, then restart the flight.")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        detail = completed.stderr.strip() or completed.stdout.strip() or "no output"
        return Result(False, None, f"Handoff returned invalid JSON: {detail[:300]}", "Repair or reinstall Handoff, then restart.")
    if completed.returncode or payload.get("status") != "ready":
        error = payload.get("error") if isinstance(payload, dict) else None
        error = error if isinstance(error, dict) else {}
        return Result(
            False,
            None,
            str(error.get("message") or "Handoff rejected the proof bundle"),
            str(error.get("recovery") or "Correct the proof bundle, then restart."),
            payload,
        )
    output = payload.get("output")
    return Result(True, Path(output) if isinstance(output, str) else None, "proof ready", payload=payload)


def command(environment: Mapping[str, str] | None = None) -> list[str]:
    selected_environment = dict(os.environ if environment is None else environment)
    selected = selected_environment.get("HANDOFF_COMMAND") or _bundled_handoff()
    return shlex.split(selected)


def _bundled_handoff() -> str:
    candidate = Path(__file__).resolve().parents[3] / "handoff" / "scripts" / "handoff"
    return str(candidate) if candidate.is_file() else "handoff"
