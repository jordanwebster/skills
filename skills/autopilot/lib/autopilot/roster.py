"""Resolve staffing through Delegate's public command contract."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shlex
import subprocess
from typing import Any


class RosterError(ValueError):
    """A Delegate configuration or command-contract failure."""

    def __init__(self, message: str, *, recovery: str | None = None, code: str = "delegate_error"):
        super().__init__(message)
        self.recovery = recovery or "Run `delegate doctor`, fix the reported configuration, then restart."
        self.code = code


@dataclass(frozen=True)
class Binding:
    role: str
    family: str
    model: str
    effort: str
    constraints: Any
    preferred: Mapping[str, Any]
    command: tuple[str, ...]

    @property
    def label(self) -> str:
        parts = [self.family, self.model]
        if self.effort:
            parts.append(self.effort)
        return "/".join(parts)

    @property
    def key(self) -> tuple[str, ...]:
        return self.command

    def semantic(self) -> dict[str, Any]:
        """Approval-relevant staffing, excluding executable and adapter detail."""

        return {
            "role": self.role,
            "mind": {"family": self.family, "model": self.model, "effort": self.effort},
            "constraints": self.constraints,
            "preferred": {
                key: self.preferred[key]
                for key in ("sandbox", "authority")
                if key in self.preferred
            },
        }


class Roster:
    """Compatibility name for the Delegate CLI client used by the driver."""

    def __init__(
        self,
        command: str | os.PathLike[str] | None = None,
        *,
        environment: Mapping[str, str] | None = None,
    ):
        selected_environment = dict(os.environ if environment is None else environment)
        selected = command or selected_environment.get("DELEGATE_COMMAND") or _bundled_delegate()
        self.command = tuple(shlex.split(os.fspath(selected)))
        if not self.command:
            raise RosterError("Delegate command is empty")
        self.environment = selected_environment

    def resolve(self, role: str, effort: str | None = None) -> Binding:
        command = [*self.command, "resolve", role]
        if effort:
            command += ["--effort", effort]
        command.append("--json")
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
                env=self.environment,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RosterError(
                f"cannot run Delegate: {error}",
                recovery="Install Delegate or run `delegate doctor`, then restart.",
                code="delegate_unavailable",
            ) from error
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            detail = completed.stderr.strip() or completed.stdout.strip() or "no output"
            raise RosterError(
                f"Delegate returned invalid JSON: {detail[:300]}",
                recovery="Run `delegate doctor`, then repair or reinstall Delegate.",
                code="delegate_protocol",
            ) from error
        if completed.returncode or not payload.get("ok"):
            detail = payload.get("error") if isinstance(payload, dict) else None
            detail = detail if isinstance(detail, dict) else {}
            raise RosterError(
                str(detail.get("message") or f"Delegate failed for role {role!r}"),
                recovery=str(detail.get("recovery") or "Run `delegate doctor`, fix the binding, then restart."),
                code=str(detail.get("code") or "delegate_error"),
            )
        try:
            value = payload["binding"]
            mind = value["mind"]
            transports = value["transports"]
            fallback = transports["fallback"]
            argv = fallback["command"]
            if fallback.get("prompt") != "stdin" or not isinstance(argv, list) or not argv:
                raise ValueError("fallback must provide non-empty argv and prompt=stdin")
            if any(not isinstance(item, str) or not item for item in argv):
                raise ValueError("fallback command must be an argv array of non-empty strings")
            return Binding(
                role=str(value["role"]),
                family=str(mind["family"]),
                model=str(mind["model"]),
                effort=str(mind.get("effort") or ""),
                constraints=value.get("constraints") or {},
                preferred=transports.get("preferred") or {},
                command=tuple(argv),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise RosterError(
                f"Delegate returned an invalid binding for role {role!r}: {error}",
                recovery="Update Delegate and run `delegate doctor`, then restart.",
                code="delegate_protocol",
            ) from error


def _bundled_delegate() -> str:
    candidate = Path(__file__).resolve().parents[3] / "delegate" / "scripts" / "delegate"
    return str(candidate) if candidate.is_file() else "delegate"
