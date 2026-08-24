"""Import the canonical machine block embedded in a readable HTML plan."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from .store import SCHEMA_VERSION, Store


PLAN_BLOCK_ID = "scaffold-plan"


class PlanError(ValueError):
    """Raised when a readable plan lacks one valid canonical machine block."""


@dataclass(frozen=True)
class ImportedPlan:
    """The normalized machine contract extracted from a plan."""

    goal: str
    test_paths: list[str]
    tasks: list[dict[str, Any]]
    digest: str


class _PlanBlockParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._capturing = False
        self._parts: list[str] = []
        self.blocks: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attributes = dict(attrs)
        if tag.lower() != "script" or attributes.get("id") != PLAN_BLOCK_ID:
            return
        if attributes.get("type") != "application/json":
            raise PlanError(
                f"#{PLAN_BLOCK_ID} must have type application/json"
            )
        if self._capturing:
            raise PlanError(f"nested #{PLAN_BLOCK_ID} blocks are invalid")
        self._capturing = True
        self._parts = []

    def handle_data(self, data: str) -> None:
        if self._capturing:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._capturing:
            self.blocks.append("".join(self._parts))
            self._capturing = False
            self._parts = []


def read_plan(path: str | Path) -> ImportedPlan:
    """Read exactly one canonical JSON block, ignoring all surrounding prose."""

    plan_path = Path(path)
    return _parse_plan_source(plan_path, _read_plan_source(plan_path))


def _read_plan_source(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as error:
        raise PlanError(f"cannot read plan {path}: {error}") from error


def _parse_plan_source(plan_path: Path, source: bytes) -> ImportedPlan:
    parser = _PlanBlockParser()
    try:
        parser.feed(source.decode("utf-8"))
        parser.close()
    except UnicodeDecodeError as error:
        raise PlanError(f"plan {plan_path} is not valid UTF-8") from error
    if parser._capturing:
        raise PlanError(f"unterminated #{PLAN_BLOCK_ID} block")
    if len(parser.blocks) != 1:
        raise PlanError(
            f"plan must contain exactly one #{PLAN_BLOCK_ID} block; "
            f"found {len(parser.blocks)}"
        )
    try:
        machine = json.loads(parser.blocks[0])
    except json.JSONDecodeError as error:
        raise PlanError(f"invalid JSON in #{PLAN_BLOCK_ID}: {error}") from error
    return _normalize_plan(machine)


def import_plan(store: Store, path: str | Path) -> ImportedPlan:
    """Apply a plan to an initialized empty store and retain its source."""

    plan_path = Path(path)
    source = _read_plan_source(plan_path)
    plan = _parse_plan_source(plan_path, source)
    destination = retained_plan_path(store, plan.digest)
    _ensure_durable_descendant(store.root, destination.parent)
    _atomic_write_once_bytes(destination, source)
    store.apply(
        {
            "type": "plan-imported",
            "goal": plan.goal,
            "test_paths": plan.test_paths,
            "tasks": plan.tasks,
            "plan_digest": plan.digest,
        }
    )
    return plan


def retained_plan_path(store: Store, digest: str | None = None) -> Path:
    """Return the immutable retained source selected by the store's plan digest."""

    selected = digest if digest is not None else store.load()["plan_digest"]
    if not isinstance(selected, str) or not re.fullmatch(r"[0-9a-f]{64}", selected):
        raise PlanError("store does not name a valid imported plan digest")
    return store.root / "inputs" / "plans" / f"{selected}.html"


def _normalize_plan(value: Any) -> ImportedPlan:
    if not isinstance(value, dict):
        raise PlanError("canonical plan must be a JSON object")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise PlanError(f"plan schema_version must be {SCHEMA_VERSION}")
    goal = value.get("goal")
    if not isinstance(goal, str) or not goal.strip():
        raise PlanError("plan goal must be a non-empty string")
    test_paths = value.get("test_paths")
    if not isinstance(test_paths, list) or any(
        not isinstance(path, str) or not path for path in test_paths
    ):
        raise PlanError("plan test_paths must be a list of non-empty strings")
    raw_tasks = value.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise PlanError("plan tasks must be a non-empty list")
    tasks = [_plan_task(task) for task in raw_tasks]
    machine = {
        "schema_version": SCHEMA_VERSION,
        "goal": goal,
        "test_paths": list(test_paths),
        "tasks": tasks,
    }
    digest = hashlib.sha256(_canonical_json(machine)).hexdigest()
    return ImportedPlan(goal, list(test_paths), tasks, digest)


def _plan_task(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PlanError("each plan task must be an object")
    for field in ("id", "title", "role", "effort", "check"):
        candidate = value.get(field)
        if not isinstance(candidate, str) or not candidate:
            raise PlanError(f"task {field} must be a non-empty string")
    depends_on = value.get("depends_on")
    if not isinstance(depends_on, list) or any(
        not isinstance(item, str) or not item for item in depends_on
    ):
        raise PlanError("task depends_on must be a list of non-empty strings")
    decisions = value.get("decisions", [])
    if not isinstance(decisions, list) or any(
        not isinstance(item, str) or not item for item in decisions
    ):
        raise PlanError("task decisions must be a list of non-empty strings")
    task = {
        "schema_version": SCHEMA_VERSION,
        "id": value["id"],
        "title": value["title"],
        "role": value["role"],
        "effort": value["effort"],
        "check": value["check"],
        "depends_on": list(depends_on),
        "decisions": list(decisions),
        "attempts": {"work": 0, "infra": 0, "diagnostic": 0},
        "completion": "pending",
        "verdict": None,
        "evidence": [],
        "verified_head": None,
        "lineage": {
            "retired": False,
            "revoked": False,
            "superseded_by": None,
        },
        "lease": None,
    }
    # Reuse the store's public validation boundary without importing internals:
    # plan application validates the complete graph before writing any transition.
    return deepcopy(task)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _atomic_write_once_bytes(path: Path, payload: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary_path, path)
        except FileExistsError:
            if path.read_bytes() != payload:
                raise PlanError(
                    f"retained plan {path.name} already exists with different bytes"
                )
        _fsync_directory(path.parent)
    finally:
        temporary_path.unlink(missing_ok=True)


def _ensure_durable_descendant(root: Path, directory: Path) -> None:
    try:
        relative = directory.relative_to(root)
    except ValueError as error:
        raise PlanError(
            f"retained plan directory escapes store root: {directory}"
        ) from error
    if not root.is_dir():
        raise PlanError(f"store root is not a directory: {root}")

    parent = root
    for component in relative.parts:
        child = parent / component
        try:
            child.mkdir()
        except FileExistsError:
            if not child.is_dir():
                raise PlanError(f"retained plan parent is not a directory: {child}")
        _fsync_directory(parent)
        parent = child


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
