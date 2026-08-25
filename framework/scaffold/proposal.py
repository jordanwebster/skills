"""Typed contracts for proposal filing and planning-context folding."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import hashlib
import json
import math
import re
from typing import Any, Protocol


SCHEMA_VERSION = 1
DISPOSITIONS = frozenset(
    {"in-envelope", "beyond-flight", "envelope-breaking"}
)


def normalize_proposal_templates(value: Any) -> dict[str, dict[str, Any]]:
    """Validate plan-owned templates used to materialize proposed tasks."""

    if not isinstance(value, Mapping):
        raise ValueError("proposal_templates must be an object")
    normalized: dict[str, dict[str, Any]] = {}
    required = {"role", "effort", "check", "test_changes"}
    for name, raw_template in value.items():
        _validate_id(name, "proposal template id")
        if not isinstance(raw_template, Mapping) or set(raw_template) != required:
            raise ValueError("proposal template has the wrong fields")
        template = deepcopy(dict(raw_template))
        for field in ("role", "effort", "check"):
            _required_text(template, field)
        if not isinstance(template["test_changes"], bool):
            raise ValueError("proposal template test_changes must be a boolean")
        normalized[name] = template
    return normalized


class Planner(Protocol):
    """A fresh, read-only planning context invoked at a batch point."""

    def fold(
        self,
        state: Mapping[str, Any],
        proposals: Sequence[Mapping[str, Any]],
        batch_id: str,
    ) -> Mapping[str, Any]: ...


def normalize_claim_proposals(value: Any) -> list[dict[str, Any]]:
    """Validate the proposal list carried by one worker claim."""

    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("claim proposals must be a list")
    normalized = [_normalize_claim_proposal(item) for item in value]
    ids = [item["id"] for item in normalized]
    if len(set(ids)) != len(ids):
        raise ValueError("claim proposal ids must be unique")
    return normalized


def normalize_proposal(value: Any) -> dict[str, Any]:
    """Validate one durable proposal record."""

    required = {
        "schema_version",
        "id",
        "source_task_id",
        "title",
        "rationale",
        "suggested_dependencies",
        "origin",
        "created_at",
        "routing",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise ValueError("proposal record has the wrong fields")
    normalized = deepcopy(dict(value))
    if normalized["schema_version"] != SCHEMA_VERSION:
        raise ValueError("proposal schema version is unsupported")
    for field in ("id", "source_task_id", "title", "rationale", "origin"):
        _required_text(normalized, field)
    _validate_id(normalized["id"], "proposal id")
    _validate_id(normalized["source_task_id"], "proposal source task id")
    if normalized["origin"] not in {"worker", "judgment"}:
        raise ValueError("proposal origin must be worker or judgment")
    dependencies = normalized["suggested_dependencies"]
    if not isinstance(dependencies, list) or any(
        not isinstance(item, str) or not item for item in dependencies
    ):
        raise ValueError(
            "proposal suggested_dependencies must be a list of task ids"
        )
    for dependency in dependencies:
        _validate_id(dependency, "proposal dependency")
    if len(set(dependencies)) != len(dependencies):
        raise ValueError("proposal suggested dependencies must be unique")
    created_at = normalized["created_at"]
    if (
        isinstance(created_at, bool)
        or not isinstance(created_at, (int, float))
        or not math.isfinite(created_at)
        or created_at < 0
    ):
        raise ValueError("proposal created_at must be a non-negative number")
    normalized["created_at"] = float(created_at)
    routing = normalized["routing"]
    if routing is not None:
        normalized["routing"] = normalize_routing_record(routing)
    return normalized


def pending_proposals(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return pending proposals in their durable insertion order."""

    proposals = state.get("proposals", [])
    if not isinstance(proposals, list):
        raise ValueError("state proposals must be a list")
    return [
        normalize_proposal(item)
        for item in proposals
        if isinstance(item, Mapping) and item.get("routing") is None
    ]


def proposal_batch_id(proposals: Sequence[Mapping[str, Any]]) -> str:
    """Derive a stable identity for one exact pending-input batch."""

    normalized = [normalize_proposal(item) for item in proposals]
    payload = json.dumps(
        normalized,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "batch-" + hashlib.sha256(payload).hexdigest()[:20]


def normalize_folding(
    value: Any,
    *,
    batch_id: str,
    proposal_ids: Sequence[str],
) -> dict[str, Any]:
    """Validate a planner's complete, proposal-bound batch decision."""

    required = {"schema_version", "batch_id", "routes"}
    if not isinstance(value, Mapping) or set(value) != required:
        raise ValueError("proposal folding result has the wrong fields")
    normalized = deepcopy(dict(value))
    if normalized["schema_version"] != SCHEMA_VERSION:
        raise ValueError("proposal folding schema version is unsupported")
    if normalized["batch_id"] != batch_id:
        raise ValueError("proposal folding result names a different batch")
    routes = normalized["routes"]
    if not isinstance(routes, list):
        raise ValueError("proposal folding routes must be a list")
    normalized_routes = [_normalize_route(item) for item in routes]
    routed_ids = [item["proposal_id"] for item in normalized_routes]
    if len(set(routed_ids)) != len(routed_ids):
        raise ValueError("proposal folding routes contain duplicate ids")
    if routed_ids != list(proposal_ids):
        raise ValueError(
            "proposal folding routes must cover the pending batch in order"
        )
    normalized["routes"] = normalized_routes
    return normalized


def normalize_routing_record(value: Any) -> dict[str, Any]:
    """Validate the durable result attached to a routed proposal."""

    required = {"batch_id", "disposition", "reason", "task_id"}
    if not isinstance(value, Mapping) or set(value) != required:
        raise ValueError("proposal routing record has the wrong fields")
    normalized = deepcopy(dict(value))
    _required_text(normalized, "batch_id")
    _required_text(normalized, "reason")
    if normalized["disposition"] not in DISPOSITIONS | {"planning-failed"}:
        raise ValueError("proposal routing disposition is outside the closed enum")
    task_id = normalized["task_id"]
    if normalized["disposition"] == "in-envelope":
        _validate_id(task_id, "routed task id")
    elif task_id is not None:
        raise ValueError("only an in-envelope proposal may name a routed task")
    return normalized


def _normalize_claim_proposal(value: Any) -> dict[str, Any]:
    required = {"id", "title", "rationale", "suggested_dependencies"}
    if not isinstance(value, Mapping) or set(value) != required:
        raise ValueError("claim proposal has the wrong fields")
    normalized = deepcopy(dict(value))
    for field in ("id", "title", "rationale"):
        _required_text(normalized, field)
    _validate_id(normalized["id"], "proposal id")
    dependencies = normalized["suggested_dependencies"]
    if not isinstance(dependencies, list) or any(
        not isinstance(item, str) or not item for item in dependencies
    ):
        raise ValueError(
            "claim proposal suggested_dependencies must be a list of task ids"
        )
    for dependency in dependencies:
        _validate_id(dependency, "proposal dependency")
    if len(set(dependencies)) != len(dependencies):
        raise ValueError("claim proposal suggested dependencies must be unique")
    return normalized


def _normalize_route(value: Any) -> dict[str, Any]:
    required = {"proposal_id", "disposition", "reason", "task"}
    if not isinstance(value, Mapping) or set(value) != required:
        raise ValueError("proposal folding route has the wrong fields")
    normalized = deepcopy(dict(value))
    _validate_id(normalized.get("proposal_id"), "proposal route id")
    _required_text(normalized, "reason")
    disposition = normalized.get("disposition")
    if disposition not in DISPOSITIONS:
        raise ValueError("proposal route disposition is outside the closed enum")
    task = normalized.get("task")
    if disposition == "in-envelope":
        normalized["task"] = _normalize_planned_task(task)
    elif task is not None:
        raise ValueError("only an in-envelope route may contain a task")
    return normalized


def _normalize_planned_task(value: Any) -> dict[str, Any]:
    required = {
        "id",
        "title",
        "template",
        "depends_on",
        "decisions",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise ValueError("planned proposal task has the wrong fields")
    normalized = deepcopy(dict(value))
    for field in ("id", "title", "template"):
        _required_text(normalized, field)
    _validate_id(normalized["id"], "planned task id")
    _validate_id(normalized["template"], "planned task template id")
    for field in ("depends_on", "decisions"):
        items = normalized[field]
        if not isinstance(items, list) or any(
            not isinstance(item, str) or not item for item in items
        ):
            raise ValueError(f"planned task {field} must be non-empty strings")
        if len(set(items)) != len(items):
            raise ValueError(f"planned task {field} must be unique")
    for dependency in normalized["depends_on"]:
        _validate_id(dependency, "planned task dependency")
    return normalized


def _required_text(value: Mapping[str, Any], field: str) -> str:
    candidate = value.get(field)
    if not isinstance(candidate, str) or not candidate.strip():
        raise ValueError(f"{field} must be non-empty text")
    return candidate


def _validate_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}", value
    ):
        raise ValueError(f"{label} must be one path-safe ASCII component")
    return value
