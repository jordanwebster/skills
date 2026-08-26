"""Check everything a flight will depend on before it takes off.

A flight fails at the first dispatch if a role is missing from the roster,
a CLI is not installed, a flag the roster records is no longer accepted,
or the tool a proof needs is absent. Each of those is cheap to find now
and expensive to find at iteration twelve with nobody watching. The smoke
check launches every distinct binding once with a trivial prompt: it is
the only way to learn whether a CLI actually accepts its flags.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import time
from typing import Any

from . import dispatch, prompt
from .plan import plan_roles
from .roster import Binding, Roster, RosterError
from .state import Flight


SMOKE_PROMPT = (
    "This is a connectivity check before an unattended run. Reply with the "
    "single word: ok. Do not read, create, or change any file."
)
SMOKE_TIMEOUT = 300
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
    smoke: bool,
    environment: Mapping[str, str] | None = None,
) -> list[Check]:
    checks: list[Check] = []
    bindings: dict[str, Binding] = {}
    for role in plan_roles(plan):
        try:
            binding = roster.resolve(role)
        except RosterError as error:
            checks.append(Check("role", role, False, str(error)))
            continue
        bindings[role] = binding
        checks.append(Check("role", role, True, binding.label))
    seen: set[str] = set()
    for binding in bindings.values():
        if binding.cli in seen:
            continue
        seen.add(binding.cli)
        found = shutil.which(binding.cli)
        checks.append(Check("cli", binding.cli, found is not None, found or "not found on PATH"))
    for command in plan.get("config", {}).get("preflight", []):
        passed, output = dispatch.run_check(command, cwd=flight.root, timeout=COMMAND_TIMEOUT)
        checks.append(Check("command", command, passed, _last_line(output) if not passed else "ok"))
    if smoke:
        env = dict(os.environ if environment is None else environment)
        env["PATH"] = f"{prompt.SCRIPTS_DIR}{os.pathsep}{env.get('PATH', '')}"
        env["AUTOPILOT_ROOT"] = str(flight.root)
        env["AUTOPILOT_ROLE"] = "preflight"
        launched: set[tuple] = set()
        for binding in bindings.values():
            if binding.key in launched or not shutil.which(binding.cli):
                continue
            launched.add(binding.key)
            log_path = flight.runtime_dir / "logs" / f"preflight-{Path(binding.cli).name}-{binding.model}.log"
            started = time.monotonic()
            outcome = dispatch.run_agent(
                binding, SMOKE_PROMPT, cwd=flight.root, log_path=log_path, timeout=SMOKE_TIMEOUT, environment=env
            )
            elapsed = time.monotonic() - started
            detail = f"{elapsed:.0f}s" if outcome.exit_class == dispatch.EXIT_OK else f"{outcome.detail} (see {log_path})"
            checks.append(Check("smoke", binding.label, outcome.exit_class == dispatch.EXIT_OK, detail))
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
