"""Deterministically check every local prerequisite before takeoff."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import shutil
from typing import Any

from . import dispatch, landing
from .plan import plan_bindings
from .roster import Roster, RosterError
from .state import Flight


COMMAND_TIMEOUT = 120


@dataclass(frozen=True)
class Check:
    kind: str
    subject: str
    ok: bool
    detail: str


def run(
    flight: Flight,
    plan: dict[str, Any],
    roster: Roster,
    *,
    environment: Mapping[str, str] | None = None,
) -> list[Check]:
    checks: list[Check] = []
    handoff_command = landing.command(environment)
    handoff_executable = handoff_command[0] if handoff_command else "handoff"
    handoff_found = shutil.which(handoff_executable)
    checks.append(
        Check(
            "dependency",
            "handoff",
            handoff_found is not None,
            handoff_found or f"{handoff_executable} not found",
        )
    )
    seen_commands: set[str] = set()
    for role, effort in plan_bindings(plan):
        subject = role + (f"/{effort}" if effort else "")
        try:
            binding = roster.resolve(role, effort)
        except RosterError as error:
            checks.append(Check("staffing", subject, False, f"{error}. {error.recovery}"))
            continue
        checks.append(Check("staffing", subject, True, binding.label))
        executable = binding.command[0]
        if executable not in seen_commands:
            seen_commands.add(executable)
            found = shutil.which(executable)
            checks.append(Check("cli", executable, found is not None, found or "not found on PATH"))
    for command in plan.get("config", {}).get("preflight", []):
        passed, output = dispatch.run_check(command, cwd=flight.root, timeout=COMMAND_TIMEOUT)
        checks.append(Check("command", command, passed, _last_line(output) if not passed else "ok"))
    return checks


def report(checks: list[Check]) -> str:
    width = max((len(check.subject) for check in checks), default=10)
    lines = []
    for check in checks:
        mark = "ok  " if check.ok else "FAIL"
        lines.append(f"  {mark} {check.kind:<8} {check.subject:<{width}}  {check.detail}")
    return "\n".join(lines)


def _last_line(output: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return lines[-1][:200] if lines else "failed with no output"
