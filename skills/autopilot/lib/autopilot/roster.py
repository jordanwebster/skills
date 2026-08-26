"""Resolve a role to a mind through the operator's delegate roster.

The roster file is owned by the operator (see the `delegate` skill). This
module only looks roles up; it never decides staffing. A role the roster
does not know is an error, not a fallback: an unattended flight must fail
before takeoff on a typo, never quietly run a task on the wrong model.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shlex
import tomllib
from typing import Any


class RosterError(ValueError):
    """Raised when the roster is missing, malformed, or lacks a role."""


@dataclass(frozen=True)
class Binding:
    role: str
    cli: str
    args: tuple[str, ...]
    model: str
    effort: str
    effort_args: tuple[str, ...]

    @property
    def label(self) -> str:
        return f"{Path(self.cli).name}/{self.model}/{self.effort}"

    @property
    def key(self) -> tuple[str, tuple[str, ...], str, str]:
        """What makes two bindings the same launch, whatever role names them."""

        return (self.cli, self.args, self.model, self.effort)


def roster_path(explicit: str | Path | None = None) -> Path:
    selected = explicit or os.environ.get("DELEGATE_ROSTER")
    if selected is None:
        selected = Path.home() / ".config" / "delegate" / "roster.toml"
    return Path(selected).expanduser()


class Roster:
    def __init__(self, path: str | Path | None = None):
        self.path = roster_path(path)
        try:
            with self.path.open("rb") as handle:
                value = tomllib.load(handle)
        except (OSError, tomllib.TOMLDecodeError) as error:
            raise RosterError(f"cannot read delegate roster {self.path}: {error}") from error
        if not isinstance(value, dict) or not value:
            raise RosterError(f"delegate roster {self.path} names no roles")
        self._bindings = {role: _normalize(role, binding) for role, binding in value.items()}

    @property
    def roles(self) -> list[str]:
        return list(self._bindings)

    def resolve(self, role: str, effort: str | None = None) -> Binding:
        if role not in self._bindings:
            raise RosterError(
                f"role {role!r} is not in the roster {self.path} (roles: {', '.join(self.roles)})"
            )
        selected = self._bindings[role]
        chosen_effort = effort or selected["effort"]
        template = selected.get("effort_arg")
        effort_args: tuple[str, ...] = ()
        if template:
            effort_args = tuple(shlex.split(template.replace("<effort>", chosen_effort)))
        return Binding(
            role=role,
            cli=selected["cli"],
            args=selected["args"],
            model=selected["model"],
            effort=chosen_effort,
            effort_args=effort_args,
        )


def _normalize(role: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RosterError(f"roster binding {role} must be a TOML table")
    for field in ("cli", "model"):
        if not isinstance(value.get(field), str) or not value[field]:
            raise RosterError(f"roster binding {role} needs a non-empty {field}")
    args = value.get("args", [])
    if not isinstance(args, list) or any(not isinstance(item, str) for item in args):
        raise RosterError(f"roster binding {role} args must be a list of strings")
    effort = value.get("effort", "")
    if not isinstance(effort, str):
        raise RosterError(f"roster binding {role} effort must be a string")
    effort_arg = value.get("effort_arg")
    if effort_arg is not None and (
        not isinstance(effort_arg, str) or effort_arg.count("<effort>") != 1
    ):
        raise RosterError(f"roster binding {role} effort_arg must contain <effort> once")
    return {
        "cli": value["cli"],
        "args": tuple(args),
        "model": value["model"],
        "effort": effort,
        "effort_arg": effort_arg,
    }
