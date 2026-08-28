"""The flight's durable state: one JSON file, a notes file, and an event log.

Everything a fresh agent needs to continue the flight lives under
`.autopilot/` in the repository, excluded from git so the product's history
never carries flight vocabulary. The file is rewritten atomically on every
change so a crash can never leave it torn; nothing else about it is clever.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Any


SCHEMA_VERSION = 1
WORKSPACE = ".autopilot"

TASK_STATUSES = ("todo", "doing", "done", "blocked", "parked")
CHUNK_STATUSES = ("open", "done")
FLIGHT_STATUSES = (
    "planned",
    "running",
    "escalated",
    "exhausted",
    "landed",
    "stopped",
)

DEFAULT_CONFIG: dict[str, Any] = {
    # Iterations are the flight's hard ceiling; the loop stops here whatever
    # the task list says, so a broken flight cannot spend without limit.
    "max_iterations": 60,
    # Iterations that touch a task without finishing it before the planner is
    # asked to split, re-brief, or park it. Never "try again" past this.
    "retry_cap": 3,
    # Seconds one dispatched agent may run. A firing timeout is a hang.
    "iteration_timeout": 3600,
    # Optional whole-flight verification, run before the closer.
    "check": None,
    # Seconds any check command may run.
    "check_timeout": 1800,
}


class StateError(RuntimeError):
    """Raised when the flight state is missing or cannot be used."""


class Flight:
    """The flight state for one repository, loaded from `.autopilot/flight.json`."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.dir = self.root / WORKSPACE
        self.path = self.dir / "flight.json"
        self.notes_path = self.dir / "NOTES.md"
        self.plan_path = self.dir / "flight-plan.md"
        self.plan_page_path = self.dir / "flight-plan.html"
        self.requirements_path = self.dir / "requirements.md"
        self.acceptance_receipt_path = self.dir / "acceptance-receipt.json"
        self.acceptance_path = self.dir / "acceptance.json"
        self.approval_path = self.dir / "plan-approval.json"
        self.handoff_dir = self.dir / "handoff"
        self.events_path = self.dir / "events.log"
        self.runtime_dir = self.dir / "runtime"
        self.data: dict[str, Any] = {}

    # -- persistence ---------------------------------------------------------

    @classmethod
    def find(cls, start: str | Path | None = None) -> Flight:
        """Locate the flight whose workspace encloses `start` (default: cwd)."""

        here = Path(start or os.getcwd()).resolve()
        for candidate in (here, *here.parents):
            if (candidate / WORKSPACE / "flight.json").is_file():
                return cls(candidate).load()
        raise StateError(
            f"no flight found from {here}: run `autopilot init` at the repository root"
        )

    def exists(self) -> bool:
        return self.path.is_file()

    def load(self) -> Flight:
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise StateError(f"no flight state at {self.path}") from error
        except (OSError, json.JSONDecodeError) as error:
            raise StateError(f"flight state at {self.path} is unreadable: {error}") from error
        if self.data.get("schema") != SCHEMA_VERSION:
            raise StateError("flight state has an unsupported schema version")
        # These fields were added without a schema break so an active flight
        # can resume after upgrading the skill.
        self.data.setdefault("acceptance_audits", [])
        for chunk in self.data.get("chunks", []):
            chunk.setdefault("completion_head", None)
        return self

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        descriptor, temporary = tempfile.mkstemp(dir=self.dir, prefix=".flight.", suffix=".tmp")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
            os.replace(temporary, self.path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

    def create(self, goal: str, branch: str, base: str) -> Flight:
        self.data = {
            "schema": SCHEMA_VERSION,
            "goal": goal,
            "branch": branch,
            "base": base,
            "created": _now(),
            "status": "planned",
            "config": dict(DEFAULT_CONFIG),
            "chunks": [],
            "tasks": [],
            "escalations": [],
            "iteration": 0,
            "acceptance_audits": [],
            "dispatches": [],
            "failure": None,
        }
        self.dir.mkdir(parents=True, exist_ok=True)
        if not self.notes_path.exists():
            self.notes_path.write_text(
                "# Flight notes\n\n"
                "What later iterations need to know: how to build and test, "
                "what surprised you, what to avoid. Keep it short; prune what "
                "is no longer true.\n",
                encoding="utf-8",
            )
        self.save()
        return self

    # -- accessors ----------------------------------------------------------

    @property
    def config(self) -> dict[str, Any]:
        merged = dict(DEFAULT_CONFIG)
        merged.update(self.data.get("config", {}))
        return merged

    @property
    def tasks(self) -> list[dict[str, Any]]:
        return self.data["tasks"]

    @property
    def chunks(self) -> list[dict[str, Any]]:
        return self.data["chunks"]

    @property
    def escalations(self) -> list[dict[str, Any]]:
        return self.data["escalations"]

    def task(self, task_id: int) -> dict[str, Any]:
        for task in self.tasks:
            if task["id"] == task_id:
                return task
        raise StateError(f"no task {task_id}")

    def chunk(self, chunk_id: int) -> dict[str, Any]:
        for chunk in self.chunks:
            if chunk["id"] == chunk_id:
                return chunk
        raise StateError(f"no chunk {chunk_id}")

    def escalation(self, escalation_id: int) -> dict[str, Any]:
        for escalation in self.escalations:
            if escalation["id"] == escalation_id:
                return escalation
        raise StateError(f"no escalation {escalation_id}")

    def chunk_tasks(self, chunk_id: int) -> list[dict[str, Any]]:
        return [task for task in self.tasks if task["chunk"] == chunk_id]

    def task_role(self, task: dict[str, Any]) -> str:
        return task.get("role") or self.chunk(task["chunk"]).get("role") or "implementer"

    def task_effort(self, task: dict[str, Any]) -> str | None:
        return task.get("effort") or self.chunk(task["chunk"]).get("effort")

    # -- mutation ------------------------------------------------------------

    def add_chunk(
        self,
        title: str,
        *,
        role: str = "implementer",
        check: str | None = None,
        review: bool = True,
        effort: str | None = None,
        chunk_id: int | None = None,
    ) -> dict[str, Any]:
        if chunk_id is None:
            chunk_id = 1 + max((chunk["id"] for chunk in self.chunks), default=0)
        elif any(chunk["id"] == chunk_id for chunk in self.chunks):
            raise StateError(f"chunk {chunk_id} already exists")
        chunk = {
            "id": chunk_id,
            "title": title,
            "role": role,
            "effort": effort,
            "check": check,
            "review": bool(review),
            "status": "open",
            "base": None,
            "completion_head": None,
            "reviewed": False,
            "fix_rounds": 0,
        }
        self.chunks.append(chunk)
        self.chunks.sort(key=lambda item: item["id"])
        return chunk

    def add_task(
        self,
        title: str,
        *,
        chunk: int,
        done_when: str = "",
        check: str | None = None,
        role: str | None = None,
        effort: str | None = None,
        depends_on: Iterable[int] = (),
        origin: str = "plan",
        status: str = "todo",
        notes: str = "",
        task_id: int | None = None,
    ) -> dict[str, Any]:
        self.chunk(chunk)
        if status not in TASK_STATUSES:
            raise StateError(f"unknown task status {status}")
        if task_id is None:
            task_id = 1 + max((task["id"] for task in self.tasks), default=0)
        elif any(task["id"] == task_id for task in self.tasks):
            raise StateError(f"task {task_id} already exists")
        dependencies = sorted({int(item) for item in depends_on})
        for dependency in dependencies:
            if dependency == task_id:
                raise StateError("a task cannot depend on itself")
            if not any(task["id"] == dependency for task in self.tasks):
                raise StateError(f"task {task_id} depends on unknown task {dependency}")
        task = {
            "id": task_id,
            "chunk": chunk,
            "title": title,
            "done_when": done_when,
            "check": check,
            "role": role,
            "effort": effort,
            "depends_on": dependencies,
            "status": status,
            "attempts": 0,
            "notes": notes,
            "commit": "",
            "attempt_head": "",
            "attempt_advanced": False,
            "origin": origin,
        }
        self.tasks.append(task)
        self.tasks.sort(key=lambda item: item["id"])
        chunk_record = self.chunk(chunk)
        if status in ("todo", "doing", "blocked") and chunk_record["status"] == "done":
            chunk_record["status"] = "open"
        return task

    def set_status(self, task: dict[str, Any], status: str) -> None:
        if status not in TASK_STATUSES:
            raise StateError(f"unknown task status {status}")
        task["status"] = status

    def set_dependencies(self, task_id: int, dependencies: Iterable[int]) -> None:
        task = self.task(task_id)
        selected = sorted({int(item) for item in dependencies})
        for dependency in selected:
            self.task(dependency)
        if task_id in selected:
            raise StateError("a task cannot depend on itself")
        previous = task["depends_on"]
        task["depends_on"] = selected
        if self._dependency_cycle():
            task["depends_on"] = previous
            raise StateError("task dependencies must remain acyclic")

    def _dependency_cycle(self) -> bool:
        visiting: set[int] = set()
        visited: set[int] = set()

        def visit(task_id: int) -> bool:
            if task_id in visiting:
                return True
            if task_id in visited:
                return False
            visiting.add(task_id)
            if any(visit(dependency) for dependency in self.task(task_id)["depends_on"]):
                return True
            visiting.remove(task_id)
            visited.add(task_id)
            return False

        return any(visit(task["id"]) for task in self.tasks if task["id"] not in visited)

    def note(self, task: dict[str, Any], text: str) -> None:
        text = text.strip()
        if not text:
            return
        existing = task.get("notes", "").rstrip()
        task["notes"] = f"{existing}\n{text}" if existing else text

    def add_escalation(
        self,
        task_id: int | None,
        text: str,
        *,
        pending_triage: bool = False,
    ) -> dict[str, Any]:
        escalation = {
            "id": 1 + max((item["id"] for item in self.escalations), default=0),
            "task": task_id,
            "text": text.strip(),
            "state": "pending_triage" if pending_triage else "operator",
            "operator_question": None,
            "resolution": None,
            "triaged": None,
            "answer": None,
            "iteration": self.data["iteration"],
            "created": _now(),
            "answered": None,
        }
        self.escalations.append(escalation)
        if task_id is not None:
            self.set_status(self.task(task_id), "blocked")
        return escalation

    def resolve_escalation(self, escalation_id: int, resolution: str) -> dict[str, Any]:
        escalation = self.escalation(escalation_id)
        if escalation.get("state") != "pending_triage":
            raise StateError(f"escalation {escalation_id} is not pending internal triage")
        resolution = resolution.strip()
        if not resolution:
            raise StateError("an internal resolution cannot be empty")
        escalation["state"] = "resolved"
        escalation["resolution"] = resolution
        escalation["triaged"] = _now()
        if escalation["task"] is not None:
            task = self.task(escalation["task"])
            if task["status"] == "blocked":
                self.set_status(task, "todo")
            self.note(task, f"Internal decision: {resolution}")
        return escalation

    def promote_escalation(self, escalation_id: int, question: str) -> dict[str, Any]:
        escalation = self.escalation(escalation_id)
        if escalation.get("state") != "pending_triage":
            raise StateError(f"escalation {escalation_id} is not pending internal triage")
        question = question.strip()
        if not question:
            raise StateError("an operator question cannot be empty")
        escalation["state"] = "operator"
        escalation["operator_question"] = question
        escalation["triaged"] = _now()
        return escalation

    def answer_escalation(self, escalation_id: int, answer: str) -> dict[str, Any]:
        escalation = self.escalation(escalation_id)
        if escalation.get("state", "operator") != "operator" or escalation["answer"] is not None:
            raise StateError(f"escalation {escalation_id} is not waiting on the operator")
        escalation["answer"] = answer.strip()
        escalation["answered"] = _now()
        escalation["state"] = "resolved"
        if escalation["task"] is not None:
            task = self.task(escalation["task"])
            if task["status"] == "blocked":
                self.set_status(task, "todo")
            self.note(task, f"Operator answer: {answer.strip()}")
        return escalation

    # -- selection ------------------------------------------------------------

    def is_ready(self, task: dict[str, Any]) -> bool:
        if task["status"] != "todo":
            return False
        if task["attempts"] >= self.config["retry_cap"]:
            return False
        return all(self.task(dependency)["status"] == "done" for dependency in task["depends_on"])

    def ready_tasks(
        self, *, role: str | None = None, chunk: int | None = None
    ) -> list[dict[str, Any]]:
        """Ready tasks in flight order: chunk by chunk, then by id."""

        order = {item["id"]: index for index, item in enumerate(self.chunks)}
        ready = [task for task in self.tasks if self.is_ready(task)]
        if chunk is not None:
            ready = [task for task in ready if task["chunk"] == chunk]
        if role is not None:
            ready = [task for task in ready if self.task_role(task) == role]
        ready.sort(key=lambda task: (order.get(task["chunk"], len(order)), task["id"]))
        return ready

    def next_task(self) -> dict[str, Any] | None:
        ready = self.ready_tasks()
        return ready[0] if ready else None

    def open_escalations(self) -> list[dict[str, Any]]:
        return [
            item
            for item in self.escalations
            if item.get("state", "operator") == "operator" and item["answer"] is None
        ]

    def pending_triage(self) -> list[dict[str, Any]]:
        return [item for item in self.escalations if item.get("state") == "pending_triage"]

    def chunk_complete(self, chunk: dict[str, Any]) -> bool:
        """Every task in the chunk is done or parked, and none is waiting."""

        tasks = self.chunk_tasks(chunk["id"])
        return all(task["status"] in ("done", "parked") for task in tasks)

    def parked_tasks(self) -> list[dict[str, Any]]:
        return [task for task in self.tasks if task["status"] == "parked"]

    # -- dispatch record ------------------------------------------------------

    def record_dispatch(self, role: str, label: str, seconds: float, exit_class: str) -> None:
        """Keep one line per agent launched, so cost and reliability are visible."""

        record = self.data.setdefault("dispatches", [])
        if isinstance(record, int):
            record = self.data["dispatches"] = []
        record.append({"role": role, "label": label, "seconds": round(seconds), "exit": exit_class})

    def dispatch_count(self) -> int:
        record = self.data.get("dispatches", [])
        return len(record) if isinstance(record, list) else int(record)

    def dispatch_summary(self) -> list[dict[str, Any]]:
        """Dispatches grouped by role and binding, in first-seen order."""

        record = self.data.get("dispatches", [])
        if not isinstance(record, list):
            return []
        rows: dict[tuple[str, str], dict[str, Any]] = {}
        for item in record:
            key = (item["role"], item["label"])
            row = rows.setdefault(key, {"role": item["role"], "label": item["label"], "count": 0, "seconds": 0, "failed": 0})
            row["count"] += 1
            row["seconds"] += item.get("seconds", 0)
            if item.get("exit") != "ok":
                row["failed"] += 1
        return list(rows.values())

    # -- events --------------------------------------------------------------

    def event(self, text: str) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        line = f"{_now()} {text.strip()}\n"
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(line)

    def recent_events(self, count: int = 10) -> list[str]:
        try:
            lines = self.events_path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []
        return lines[-count:]

    def notes(self) -> str:
        try:
            return self.notes_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
