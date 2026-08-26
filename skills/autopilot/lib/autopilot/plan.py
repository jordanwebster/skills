"""Read the flight plan's machine block and seed the task list from it.

The plan is one Markdown file the planner writes and the operator reads as
a rendered page. Its prose is for the operator; the single fenced block
opened with ```flight-plan holds the JSON the loop reads. The page renders
that block as tables, so what the operator approved and what the loop
seeds cannot drift apart.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .state import Flight, StateError


PLAN_FENCE = "```flight-plan"

KNOWN_ROLES = ("planner", "implementer", "ui-developer", "prober", "qa-tester", "reviewer", "closer")


class PlanError(ValueError):
    """Raised when the plan has no usable machine block."""


def read_plan(path: str | Path) -> dict[str, Any]:
    """Return the plan's machine block, validated enough to seed a flight."""

    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as error:
        raise PlanError(f"cannot read plan {source}: {error}") from error
    blocks = plan_blocks(text)
    if len(blocks) != 1:
        raise PlanError(
            f"plan must contain exactly one {PLAN_FENCE} block, found {len(blocks)}"
        )
    try:
        plan = json.loads(blocks[0])
    except json.JSONDecodeError as error:
        raise PlanError(f"plan block is not valid JSON: {error}") from error
    return _validate(plan)


def plan_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    buffer: list[str] | None = None
    for line in text.splitlines():
        if buffer is None:
            if line.strip() == PLAN_FENCE:
                buffer = []
        elif line.strip() == "```":
            blocks.append("\n".join(buffer))
            buffer = None
        else:
            buffer.append(line)
    return blocks


def plan_roles(plan: dict[str, Any]) -> list[str]:
    """Every role the plan will dispatch, in first-use order."""

    roles: list[str] = []

    def add(role: str | None) -> None:
        if role and role not in roles:
            roles.append(role)

    add("planner")
    for chunk in plan["chunks"]:
        add(chunk.get("role") or "implementer")
    for task in plan["tasks"]:
        add(task.get("role"))
    if any(chunk.get("review") is not False for chunk in plan["chunks"]):
        add("reviewer")
    add("closer")
    return roles


def _validate(plan: Any) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise PlanError("plan block must be a JSON object")
    goal = plan.get("goal")
    if not isinstance(goal, str) or not goal.strip():
        raise PlanError("plan needs a non-empty goal")
    chunks = plan.get("chunks")
    tasks = plan.get("tasks")
    if not isinstance(chunks, list) or not chunks:
        raise PlanError("plan needs at least one chunk")
    if not isinstance(tasks, list) or not tasks:
        raise PlanError("plan needs at least one task")
    config = plan.get("config", {})
    if not isinstance(config, dict):
        raise PlanError("plan config must be an object")
    preflight = config.get("preflight", [])
    if not isinstance(preflight, list) or any(not isinstance(item, str) for item in preflight):
        raise PlanError("plan config.preflight must be a list of shell commands")

    chunk_ids: set[int] = set()
    for chunk in chunks:
        _require_fields(chunk, "chunk", ("id", "title"))
        if not isinstance(chunk["id"], int) or chunk["id"] in chunk_ids:
            raise PlanError(f"chunk ids must be unique integers (chunk {chunk.get('id')!r})")
        chunk_ids.add(chunk["id"])
    task_ids: set[int] = set()
    for task in tasks:
        _require_fields(task, "task", ("id", "chunk", "title"))
        if not isinstance(task["id"], int) or task["id"] in task_ids:
            raise PlanError(f"task ids must be unique integers (task {task.get('id')!r})")
        if task["chunk"] not in chunk_ids:
            raise PlanError(f"task {task['id']} names unknown chunk {task['chunk']}")
        task_ids.add(task["id"])
    for task in tasks:
        for dependency in task.get("depends_on", []):
            if dependency not in task_ids:
                raise PlanError(f"task {task['id']} depends on unknown task {dependency}")
    return plan


def _require_fields(value: Any, kind: str, fields: tuple[str, ...]) -> None:
    if not isinstance(value, dict):
        raise PlanError(f"each {kind} must be an object")
    for field in fields:
        if field not in value:
            raise PlanError(f"{kind} is missing required field {field!r}")


def seed_flight(flight: Flight, plan: dict[str, Any]) -> None:
    """Load chunks, tasks, and config from the plan into an unseeded flight."""

    if flight.tasks:
        raise StateError("flight already has tasks; the plan seeds only once")
    flight.data["goal"] = plan["goal"].strip()
    config = dict(flight.data.get("config", {}))
    config.update(plan.get("config", {}))
    flight.data["config"] = config
    for chunk in plan["chunks"]:
        flight.add_chunk(
            chunk["title"],
            role=chunk.get("role", "implementer"),
            check=chunk.get("check"),
            review=chunk.get("review", True),
            effort=chunk.get("effort"),
            chunk_id=chunk["id"],
        )
    for task in sorted(plan["tasks"], key=lambda item: item["id"]):
        flight.add_task(
            task["title"],
            chunk=task["chunk"],
            done_when=task.get("done_when", ""),
            check=task.get("check"),
            role=task.get("role"),
            effort=task.get("effort"),
            depends_on=[],
            task_id=task["id"],
        )
    for task in plan["tasks"]:
        flight.task(task["id"])["depends_on"] = sorted(
            {int(item) for item in task.get("depends_on", [])}
        )
    flight.save()
