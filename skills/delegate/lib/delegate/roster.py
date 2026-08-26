"""Read the operator-owned roster and resolve a requested role and effort."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shlex
import tomllib
from typing import Any


class DelegateError(ValueError):
    """A stable, actionable staffing configuration failure."""

    def __init__(self, code: str, message: str, recovery: str):
        super().__init__(message)
        self.code = code
        self.recovery = recovery


@dataclass(frozen=True)
class Binding:
    role: str
    cli: str
    args: tuple[str, ...]
    family: str
    model: str
    effort: str
    effort_args: tuple[str, ...]
    constraints: dict[str, str | int | float | bool]


def roster_path(explicit: str | Path | None = None) -> Path:
    selected = explicit or os.environ.get("DELEGATE_ROSTER")
    if selected is None:
        selected = Path.home() / ".config" / "delegate" / "roster.toml"
    return Path(selected).expanduser().resolve()


class Roster:
    def __init__(self, path: str | Path | None = None):
        self.path = roster_path(path)
        try:
            with self.path.open("rb") as handle:
                value = tomllib.load(handle)
        except FileNotFoundError as error:
            raise DelegateError(
                "roster_missing",
                f"delegate roster does not exist at {self.path}",
                "Copy the bundled roster.toml template there or set DELEGATE_ROSTER.",
            ) from error
        except (OSError, tomllib.TOMLDecodeError) as error:
            raise DelegateError(
                "invalid_roster",
                f"cannot read delegate roster {self.path}: {error}",
                "Correct the roster TOML and run delegate doctor.",
            ) from error
        if not isinstance(value, dict) or not value:
            raise DelegateError(
                "invalid_roster",
                f"delegate roster {self.path} names no roles",
                "Add at least one role binding from the bundled template.",
            )
        self._entries: dict[str, dict[str, Any]] = {}
        for role, entry in value.items():
            if not isinstance(role, str) or not role:
                raise DelegateError("invalid_roster", "roster role names must be non-empty", "Correct the roster TOML.")
            self._entries[role] = _normalize(role, entry)

    @property
    def roles(self) -> tuple[str, ...]:
        return tuple(self._entries)

    def resolve(self, role: str, effort: str | None = None) -> Binding:
        if role not in self._entries:
            available = ", ".join(self.roles) or "none"
            raise DelegateError(
                "unknown_role",
                f"role {role!r} is not in delegate roster {self.path} (roles: {available})",
                "Correct the role tag or add an operator-approved binding to the roster.",
            )
        entry = self._entries[role]
        unavailable = entry.get("unavailable")
        if unavailable:
            raise DelegateError(
                "unavailable_binding",
                f"role {role!r} is unavailable: {unavailable}",
                "Choose an approved available binding in the roster, then resolve again.",
            )
        selected_effort = effort if effort is not None else entry["effort"]
        effort_args: tuple[str, ...] = ()
        if selected_effort and entry.get("effort_arg"):
            rendered = entry["effort_arg"].replace("<effort>", selected_effort)
            try:
                effort_args = tuple(shlex.split(rendered))
            except ValueError as error:
                raise DelegateError(
                    "invalid_roster",
                    f"roster binding {role!r} has an invalid effort_arg: {error}",
                    "Correct effort_arg and run delegate doctor.",
                ) from error
        return Binding(
            role=role,
            cli=entry["cli"],
            args=entry["args"],
            family=entry["family"],
            model=entry["model"],
            effort=selected_effort,
            effort_args=effort_args,
            constraints=dict(entry["constraints"]),
        )


def _normalize(role: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DelegateError(
            "invalid_roster", f"roster binding {role!r} must be a TOML table", "Correct the roster TOML."
        )
    unavailable = value.get("unavailable")
    if unavailable is not None:
        if not isinstance(unavailable, str) or not unavailable.strip():
            raise DelegateError(
                "invalid_roster",
                f"roster binding {role!r} unavailable must be a non-empty reason",
                "Give unavailable a useful reason or remove it.",
            )
        return {"unavailable": unavailable.strip()}
    for field in ("cli", "model"):
        if not isinstance(value.get(field), str) or not value[field].strip():
            raise DelegateError(
                "invalid_roster",
                f"roster binding {role!r} needs a non-empty {field}",
                f"Set {field} in the operator-owned roster.",
            )
    args = value.get("args", [])
    if not isinstance(args, list) or any(not isinstance(item, str) or "\0" in item for item in args):
        raise DelegateError(
            "invalid_roster",
            f"roster binding {role!r} args must be a list of strings",
            "Correct args and run delegate doctor.",
        )
    effort = value.get("effort", "")
    if not isinstance(effort, str):
        raise DelegateError(
            "invalid_roster", f"roster binding {role!r} effort must be a string", "Correct effort in the roster."
        )
    effort_arg = value.get("effort_arg")
    if effort_arg is not None and (
        not isinstance(effort_arg, str) or effort_arg.count("<effort>") != 1
    ):
        raise DelegateError(
            "invalid_roster",
            f"roster binding {role!r} effort_arg must contain <effort> exactly once",
            "Correct effort_arg and run delegate doctor.",
        )
    family = value.get("family", _family(value["cli"]))
    if not isinstance(family, str) or not family.strip():
        raise DelegateError(
            "invalid_roster", f"roster binding {role!r} family must be a string", "Correct family in the roster."
        )
    constraints = value.get("constraints", {})
    scalar = (str, int, float, bool)
    if not isinstance(constraints, dict) or any(
        not isinstance(key, str) or not key or not isinstance(item, scalar)
        for key, item in constraints.items()
    ):
        raise DelegateError(
            "invalid_roster",
            f"roster binding {role!r} constraints must be a table of scalar values",
            "Use an inline TOML table such as constraints = { sandbox = 'read-only' }.",
        )
    return {
        "cli": value["cli"],
        "args": tuple(args),
        "family": family.strip(),
        "model": value["model"],
        "effort": effort,
        "effort_arg": effort_arg,
        "constraints": dict(constraints),
    }


def _family(cli: str) -> str:
    name = Path(cli).name.casefold()
    if name.startswith("claude"):
        return "claude"
    if name.startswith("codex"):
        return "codex"
    return name
