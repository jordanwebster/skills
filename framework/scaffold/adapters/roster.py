"""Mechanical delegate-roster resolution and vendor adapter selection."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os
from pathlib import Path
import shlex
import tomllib
from typing import Any

from .base import DispatchResult
from .claude import ClaudeAdapter
from .codex import CodexAdapter
from ..store import Store


KNOWN_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})


class RosterError(ValueError):
    """Raised when the operator roster cannot produce a safe binding."""


@dataclass(frozen=True)
class ResolvedBinding:
    """One validated role-to-mind lookup from the operator roster."""

    role: str
    cli: str
    args: tuple[str, ...]
    model: str
    effort: str
    effort_args: tuple[str, ...]
    used_default: bool
    effort_fallback: bool

    @property
    def label(self) -> str:
        return f"{Path(self.cli).name}/{self.model}/{self.effort}"


class Roster:
    """An immutable snapshot of the delegate roster for one driver slice."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        try:
            with self.path.open("rb") as handle:
                value = tomllib.load(handle)
        except (OSError, tomllib.TOMLDecodeError) as error:
            raise RosterError(f"cannot read delegate roster {self.path}: {error}") from error
        if not isinstance(value, dict) or "default" not in value:
            raise RosterError("delegate roster must contain a default binding")
        self._bindings = {
            role: _normalize_binding(role, binding)
            for role, binding in value.items()
        }

    def resolve(self, role: str, requested_effort: str) -> ResolvedBinding:
        """Resolve role first, then a recognized plan effort, without judgment."""

        if not isinstance(role, str) or not role:
            raise RosterError("task role must be a non-empty string")
        if not isinstance(requested_effort, str) or not requested_effort:
            raise RosterError("task effort must be a non-empty string")
        used_default = role not in self._bindings
        selected = self._bindings["default" if used_default else role]
        roster_effort = selected["effort"]
        effort_fallback = requested_effort not in KNOWN_EFFORTS
        effort = roster_effort if effort_fallback else requested_effort
        effort_template = selected.get("effort_arg")
        effort_args: tuple[str, ...] = ()
        if effort_template is not None:
            expanded = effort_template.replace("<effort>", effort)
            effort_args = tuple(shlex.split(expanded))
            if not effort_args:
                raise RosterError(f"binding {role} effort_arg expands to no arguments")
        return ResolvedBinding(
            role=role,
            cli=selected["cli"],
            args=selected["args"],
            model=selected["model"],
            effort=effort,
            effort_args=effort_args,
            used_default=used_default,
            effort_fallback=effort_fallback,
        )


class RosterAdapter:
    """Dispatch through the vendor named by a mechanically resolved roster row."""

    def __init__(self, store: Store, roster_path: str | Path | None = None):
        selected = roster_path or os.environ.get("DELEGATE_ROSTER")
        if selected is None:
            selected = Path.home() / ".config" / "delegate" / "roster.toml"
        self.store = store
        self.roster = Roster(selected)

    def dispatch(
        self,
        prompt: str,
        binding: Mapping[str, Any],
        sandbox: str,
        timeout: float,
    ) -> DispatchResult:
        role = _required_text(binding, "role")
        requested_effort = _required_text(binding, "effort")
        resolved = self.roster.resolve(role, requested_effort)
        executable = Path(resolved.cli).name.casefold()
        if executable == "codex":
            adapter = CodexAdapter(self.store, resolved)
        elif executable == "claude":
            adapter = ClaudeAdapter(self.store, resolved)
        else:
            raise RosterError(
                f"binding {role} names unsupported CLI {resolved.cli!r}"
            )
        return adapter.dispatch(prompt, binding, sandbox, timeout)


def _normalize_binding(role: str, value: Any) -> dict[str, Any]:
    if not isinstance(role, str) or not role or not isinstance(value, dict):
        raise RosterError("roster bindings must be named TOML tables")
    allowed = {"cli", "args", "model", "effort", "effort_arg"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise RosterError(f"binding {role} has unknown fields: {', '.join(unknown)}")
    for field in ("cli", "model", "effort"):
        candidate = value.get(field)
        if not isinstance(candidate, str) or not candidate or candidate.startswith("-"):
            raise RosterError(f"binding {role} {field} must be a safe non-empty string")
    if Path(value["cli"]).name.casefold() not in {"claude", "codex"}:
        raise RosterError(
            f"binding {role} names unsupported CLI {value['cli']!r}"
        )
    if value["effort"] not in KNOWN_EFFORTS:
        raise RosterError(f"binding {role} effort is not recognized: {value['effort']}")
    args = value.get("args", [])
    if not isinstance(args, list) or any(
        not isinstance(argument, str) or not argument for argument in args
    ):
        raise RosterError(f"binding {role} args must be a list of non-empty strings")
    effort_arg = value.get("effort_arg")
    if effort_arg is not None and (
        not isinstance(effort_arg, str)
        or effort_arg.count("<effort>") != 1
    ):
        raise RosterError(
            f"binding {role} effort_arg must contain <effort> exactly once"
        )
    normalized = dict(value)
    normalized["args"] = tuple(args)
    return normalized


def _required_text(value: Mapping[str, Any], field: str) -> str:
    candidate = value.get(field)
    if not isinstance(candidate, str) or not candidate:
        raise RosterError(f"{field} must be a non-empty string")
    return candidate
