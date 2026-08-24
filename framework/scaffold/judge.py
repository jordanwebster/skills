"""Typed contracts for ephemeral failure judges."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any, Protocol


SCHEMA_VERSION = 1
CLOSED_DECISIONS = frozenset(
    {
        "split",
        "rebrief",
        "rebind",
        "park",
        "impossible",
        "defer-to-operator",
    }
)
CLOSED_TRIGGERS = frozenset(
    {
        "retry-cap",
        "ambiguity",
        "stall",
        "identical-error",
        "wall-clock-cap",
    }
)


class Judge(Protocol):
    """A read-only, ephemeral decision maker invoked by the loop."""

    def decide(
        self,
        task: Mapping[str, Any],
        trigger: str,
        failure: str,
    ) -> Mapping[str, Any]: ...


def normalize_decision(
    value: Any,
    *,
    task_id: str | None = None,
    trigger: str | None = None,
) -> dict[str, Any]:
    """Validate one judge output against the closed decision contract."""

    required = {"schema_version", "task_id", "trigger", "decision", "reason"}
    if not isinstance(value, Mapping) or set(value) != required:
        raise ValueError("judge decision has the wrong fields")
    normalized = deepcopy(dict(value))
    if normalized["schema_version"] != SCHEMA_VERSION:
        raise ValueError("judge decision has an unsupported schema version")
    for field in ("task_id", "trigger", "decision", "reason"):
        candidate = normalized[field]
        if not isinstance(candidate, str) or not candidate.strip():
            raise ValueError(f"judge decision {field} must be non-empty text")
    if normalized["trigger"] not in CLOSED_TRIGGERS:
        raise ValueError("judge decision trigger is outside the closed trigger enum")
    if normalized["decision"] not in CLOSED_DECISIONS:
        raise ValueError("judge decision is outside the closed decision enum")
    if task_id is not None and normalized["task_id"] != task_id:
        raise ValueError("judge decision names a different task")
    if trigger is not None and normalized["trigger"] != trigger:
        raise ValueError("judge decision names a different trigger")
    return normalized
