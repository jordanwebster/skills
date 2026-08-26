"""Read the flight plan's machine block and seed the task list from it.

The plan is one HTML page. Its prose is for the operator; the single
`<script type="application/json" id="flight-plan">` block is the part the
loop reads. The page renders its own tables from that block, so what the
operator approved and what the loop seeds cannot drift apart.
"""

from __future__ import annotations

from html.parser import HTMLParser
import json
from pathlib import Path
from typing import Any

from .state import Flight, StateError


PLAN_BLOCK_ID = "flight-plan"


class PlanError(ValueError):
    """Raised when the plan page has no usable machine block."""


class _BlockParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.blocks: list[str] = []
        self._capturing = False
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag.lower() == "script" and attributes.get("id") == PLAN_BLOCK_ID:
            self._capturing = True
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._capturing:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._capturing:
            self._capturing = False
            self.blocks.append("".join(self._buffer))


def read_plan(path: str | Path) -> dict[str, Any]:
    """Return the plan's machine block, validated enough to seed a flight."""

    source = Path(path)
    try:
        html = source.read_text(encoding="utf-8")
    except OSError as error:
        raise PlanError(f"cannot read plan {source}: {error}") from error
    parser = _BlockParser()
    parser.feed(html)
    parser.close()
    if len(parser.blocks) != 1:
        raise PlanError(
            f"plan must contain exactly one <script id=\"{PLAN_BLOCK_ID}\"> block, "
            f"found {len(parser.blocks)}"
        )
    try:
        plan = json.loads(parser.blocks[0])
    except json.JSONDecodeError as error:
        raise PlanError(f"plan block is not valid JSON: {error}") from error
    return _validate(plan)


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
