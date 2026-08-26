"""Construct fallback CLI argv without invoking a provider."""

from __future__ import annotations

from .roster import Binding, DelegateError


def build(binding: Binding) -> list[str]:
    family = binding.family.casefold()
    if family == "claude":
        command = [binding.cli, *binding.args, "--model", binding.model]
        if binding.effort:
            command += list(binding.effort_args) or ["--effort", binding.effort]
    elif family == "codex":
        command = [binding.cli, "-a", "never", *binding.args, "--model", binding.model]
        if binding.effort:
            command += list(binding.effort_args) or ["-c", f"model_reasoning_effort={binding.effort}"]
        command.append("-")
    else:
        command = [binding.cli, *binding.args, *binding.effort_args]
    if any(not isinstance(part, str) or not part or "\0" in part for part in command):
        raise DelegateError(
            "invalid_command",
            f"role {binding.role!r} produced an invalid fallback command",
            "Correct the binding's cli, args, or effort_arg and run delegate doctor.",
        )
    return command


def payload(binding: Binding) -> dict[str, object]:
    return {
        "role": binding.role,
        "mind": {"family": binding.family, "model": binding.model, "effort": binding.effort},
        "constraints": dict(binding.constraints),
        "transports": {
            "preferred": {"kind": "native", "family": binding.family},
            "fallback": {"kind": "cli", "command": build(binding), "prompt": "stdin", "cwd": "process"},
        },
    }
