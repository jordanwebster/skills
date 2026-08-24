"""Crash-safe current state and append-only transition journal."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any
import uuid


SCHEMA_VERSION = 1


class StoreError(Exception):
    """Base class for task-store errors."""


class StoreCorruption(StoreError):
    """Raised when durable state cannot be interpreted safely."""


class StoreExists(StoreError):
    """Raised when initialization would overwrite an existing store."""


class InvalidTransition(StoreError):
    """Raised when a requested state transition is not legal."""


class TaskUnavailable(StoreError):
    """Raised when a task cannot be leased from the current frontier."""


@dataclass(frozen=True)
class Lease:
    """A time-limited claim on one frontier task."""

    task_id: str
    holder: str
    lease_id: str
    acquired_at: float
    expires_at: float


def initial_state(goal: str, *, test_paths: list[str] | None = None) -> dict[str, Any]:
    """Return the empty version-one state for a flight."""

    if not isinstance(goal, str) or not goal.strip():
        raise ValueError("goal must be a non-empty string")
    paths = list(test_paths or [])
    if any(not isinstance(path, str) or not path for path in paths):
        raise ValueError("test paths must be non-empty strings")
    return {
        "schema_version": SCHEMA_VERSION,
        "goal": goal,
        "test_paths": paths,
        "plan_digest": None,
        "tasks": [],
    }


class Store:
    """Own a flight's materialized state and canonical transition journal.

    Each journal row includes the full state after its transition. This keeps M0's
    recovery rule simple and deterministic: the append-only journal is authoritative,
    while ``tasks.json`` is an atomically replaceable current-state view.
    """

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.state_path = self.root / "tasks.json"
        self.journal_path = self.root / "journal.jsonl"
        self.lock_path = self.root / "store.lock"
        self.claims_path = self.root / "claims"

    def create(self, state: Mapping[str, Any]) -> dict[str, Any]:
        """Create a new store without overwriting any durable state."""

        normalized = _normalize_state(state)
        with self._locked():
            if self.state_path.exists() or self.journal_path.exists():
                raise StoreExists(f"store already exists at {self.root}")

            entry = _journal_entry(1, {"type": "initialized"}, normalized)
            _append_json_line(self.journal_path, entry)
            _atomic_write_json(self.state_path, normalized)
        return deepcopy(normalized)

    def load(self) -> dict[str, Any]:
        """Load state, replaying the journal if its materialized view is stale."""

        with self._locked():
            return self._load_unlocked()

    def _load_unlocked(self) -> dict[str, Any]:
        entries = self.read_journal()
        self._drop_torn_tail()
        if not entries:
            raise StoreCorruption(f"journal has no complete entries: {self.journal_path}")
        journal_state = _validate_entry(entries[-1], entries[-1]["sequence"])

        try:
            disk_state = _read_json_object(self.state_path)
            normalized_disk = _normalize_state(disk_state)
        except (FileNotFoundError, StoreCorruption, ValueError):
            normalized_disk = None

        if normalized_disk != journal_state:
            _atomic_write_json(self.state_path, journal_state)
        return deepcopy(journal_state)

    def _replace_unlocked(
        self,
        state: Mapping[str, Any],
        transition: Mapping[str, Any],
    ) -> dict[str, Any]:
        normalized = _normalize_state(state)
        normalized_transition = _normalize_transition(transition)
        entries = self.read_journal()
        self._drop_torn_tail()
        if not entries:
            raise StoreCorruption(f"journal has no complete entries: {self.journal_path}")
        _validate_entry(entries[-1], entries[-1]["sequence"])

        entry = _journal_entry(
            entries[-1]["sequence"] + 1,
            normalized_transition,
            normalized,
        )
        _append_json_line(self.journal_path, entry)
        _atomic_write_json(self.state_path, normalized)
        return deepcopy(normalized)

    def ready(
        self,
        profile: str | None = None,
        *,
        now: float | None = None,
    ) -> list[dict[str, Any]]:
        """Return the dependency-ready, unleased frontier in plan order."""

        if profile is not None and (not isinstance(profile, str) or not profile):
            raise ValueError("profile must be a non-empty string or None")
        if now is not None and (
            isinstance(now, bool) or not isinstance(now, (int, float))
        ):
            raise ValueError("now must be a number or None")
        observed_at = time.time() if now is None else now
        state = self.load()
        by_id = {task["id"]: task for task in state["tasks"]}
        frontier: list[dict[str, Any]] = []
        for task in state["tasks"]:
            if profile is not None and task["role"] != profile:
                continue
            if not _task_can_enter_frontier(task, by_id, observed_at):
                continue
            frontier.append(deepcopy(task))
        return frontier

    def claim(
        self,
        task_id: str,
        holder: str,
        *,
        ttl_seconds: float = 300,
        now: float | None = None,
    ) -> Lease:
        """Atomically lease one ready task while enforcing v1's single worker."""

        task_id = validate_task_id(task_id)
        if not isinstance(holder, str) or not holder:
            raise ValueError("holder must be a non-empty string")
        if not isinstance(ttl_seconds, (int, float)) or ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if now is not None and (
            isinstance(now, bool) or not isinstance(now, (int, float))
        ):
            raise ValueError("now must be a number or None")
        acquired_at = time.time() if now is None else float(now)
        expires_at = acquired_at + float(ttl_seconds)
        lease_id = uuid.uuid4().hex

        with self._locked():
            state = self._load_unlocked()
            by_id = {task["id"]: task for task in state["tasks"]}
            try:
                task = by_id[task_id]
            except KeyError as error:
                raise TaskUnavailable(f"unknown task: {task_id}") from error

            for other in state["tasks"]:
                lease = other["lease"]
                if lease is not None and lease["expires_at"] > acquired_at:
                    raise TaskUnavailable(
                        f"active lease already held for task {other['id']}"
                    )
            if not _task_can_enter_frontier(task, by_id, acquired_at):
                raise TaskUnavailable(f"task is not on the frontier: {task_id}")

            reclaimed = task["lease"] is not None
            task["lease"] = {
                "lease_id": lease_id,
                "holder": holder,
                "acquired_at": acquired_at,
                "expires_at": expires_at,
            }
            self._replace_unlocked(
                state,
                {
                    "type": "task-leased",
                    "task_id": task_id,
                    "holder": holder,
                    "lease_id": lease_id,
                    "reclaimed": reclaimed,
                },
            )
        return Lease(task_id, holder, lease_id, acquired_at, expires_at)

    def file_claim(
        self,
        task_id: str,
        evidence_path: str | Path,
        *,
        now: float | None = None,
    ) -> Path:
        """Validate and durably retain a worker's typed completion claim."""

        task_id = validate_task_id(task_id)
        if now is not None and (
            isinstance(now, bool) or not isinstance(now, (int, float))
        ):
            raise ValueError("now must be a number or None")
        observed_at = time.time() if now is None else float(now)
        source = Path(evidence_path)
        try:
            claim = _read_json_object(source)
        except (FileNotFoundError, StoreCorruption) as error:
            raise ValueError(f"invalid claim evidence: {error}") from error
        normalized = _normalize_claim(claim)
        if normalized["task_id"] != task_id:
            raise ValueError("claim task_id does not match requested task")

        with self._locked():
            state = self._load_unlocked()
            task = _task_by_id(state, task_id)
            lease = task["lease"]
            if lease is None or lease["holder"] != normalized["holder"]:
                raise InvalidTransition("claim holder does not own the task lease")
            if lease["lease_id"] != normalized["lease_id"]:
                raise InvalidTransition("claim does not belong to the current lease")
            if lease["expires_at"] <= observed_at:
                raise InvalidTransition("task lease expired before the claim was filed")
            destination = self.claims_path / f"{task_id}.json"
            _atomic_write_json(destination, normalized)
        return destination

    def read_claim(self, task_id: str) -> dict[str, Any]:
        """Read a previously validated worker claim."""

        task_id = validate_task_id(task_id)
        try:
            return _normalize_claim(
                _read_json_object(self.claims_path / f"{task_id}.json")
            )
        except FileNotFoundError as error:
            raise InvalidTransition(f"no filed claim for task {task_id}") from error

    def apply(self, transition: Mapping[str, Any]) -> dict[str, Any]:
        """Apply one legal framework-owned transition and append its journal row."""

        normalized = _normalize_transition(transition)
        with self._locked():
            state = self._load_unlocked()
            transition_type = normalized["type"]
            if transition_type == "plan-imported":
                _apply_plan_imported(state, normalized)
            elif transition_type == "task-verification-recorded":
                if "observed_at" not in normalized:
                    normalized["observed_at"] = time.time()
                self._apply_task_verification(state, normalized)
            elif transition_type == "task-released":
                _apply_task_released(state, normalized)
            else:
                raise InvalidTransition(
                    f"unsupported transition type: {transition_type}"
                )
            normalized_state = _normalize_state(state)
            return self._replace_unlocked(normalized_state, normalized)

    def _apply_task_verification(
        self,
        state: dict[str, Any],
        transition: Mapping[str, Any],
    ) -> None:
        task_id = _required_text(transition, "task_id")
        holder = _required_text(transition, "holder")
        lease_id = _required_text(transition, "lease_id")
        verification_path = _required_text(transition, "verification_path")
        verification_sha256 = _required_text(
            transition, "verification_sha256"
        )
        observed_at = transition.get("observed_at")
        if isinstance(observed_at, bool) or not isinstance(
            observed_at, (int, float)
        ):
            raise InvalidTransition("task verification observed_at must be a number")
        task = _task_by_id(state, task_id)
        lease = task["lease"]
        if task["completion"] != "pending" or task["verdict"] is not None:
            raise InvalidTransition(f"task is already terminal: {task_id}")
        if (
            lease is None
            or lease["holder"] != holder
            or lease["lease_id"] != lease_id
        ):
            raise InvalidTransition("verified task is not leased by the holder")
        if lease["expires_at"] <= observed_at:
            raise InvalidTransition("task lease expired before verification")
        verification = self._read_verification(
            verification_path, verification_sha256
        )
        if (
            verification["task_id"] != task_id
            or verification["holder"] != holder
            or verification["lease_id"] != lease_id
        ):
            raise InvalidTransition(
                "verification artifact does not belong to the active task lease"
            )
        if verification["check_command"] != task["check"]:
            raise InvalidTransition("verification artifact names a different check")
        expected_check_id = hashlib.sha256(task["check"].encode("utf-8")).hexdigest()
        if verification["check_id"] != expected_check_id:
            raise InvalidTransition("verification artifact check digest is invalid")
        if (
            verification["verdict"] == "green"
            and verification["protected_changes"]
            and not task["test_changes"]
        ):
            raise InvalidTransition(
                "green verification cannot contain out-of-scope test changes"
            )
        claim = self.read_claim(task_id)
        if (
            claim["holder"] != holder
            or claim["lease_id"] != lease["lease_id"]
            or claim["candidate_head"] != verification["candidate_head"]
        ):
            raise InvalidTransition("verified result does not match the filed claim")
        task["completion"] = "complete"
        task["verdict"] = verification["verdict"]
        if verification["verdict"] == "green":
            task["verified_head"] = verification["candidate_head"]
        else:
            task["attempts"]["work"] += 1
        task["evidence"].append(
            {
                "claim_path": str(self.claims_path / f"{task_id}.json"),
                "artifacts": claim["artifacts"],
                "lease_id": lease_id,
                "candidate_head": verification["candidate_head"],
                "verification_path": verification_path,
                "verification_sha256": verification_sha256,
                "verdict": verification["verdict"],
                "reason": verification["reason"],
                "protected_changes": verification["protected_changes"],
                "check_id": verification["check_id"],
                "observation_count": (
                    len(verification["result"]["observations"])
                    if isinstance(verification.get("result"), Mapping)
                    and isinstance(
                        verification["result"].get("observations"), list
                    )
                    else 0
                ),
                "duration_seconds": (
                    verification["process"].get("duration_seconds")
                    if isinstance(verification.get("process"), Mapping)
                    else None
                ),
            }
        )
        task["lease"] = None

    def _read_verification(
        self, relative_name: str, expected_sha256: str
    ) -> dict[str, Any]:
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            raise InvalidTransition("verification_sha256 must be a SHA-256 digest")
        relative = Path(relative_name)
        if relative.is_absolute() or ".." in relative.parts:
            raise InvalidTransition("verification artifact path escapes the store")
        path = (self.root / relative).resolve()
        root = self.root.resolve()
        if os.path.commonpath([root, path]) != str(root):
            raise InvalidTransition("verification artifact path escapes the store")
        try:
            payload = path.read_bytes()
        except OSError as error:
            raise InvalidTransition(
                f"cannot read verification artifact: {error}"
            ) from error
        if hashlib.sha256(payload).hexdigest() != expected_sha256:
            raise InvalidTransition("verification artifact digest does not match")
        try:
            value = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise InvalidTransition("verification artifact is not valid JSON") from error
        return _normalize_verification(value)

    @contextmanager
    def _locked(self):
        self.root.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def read_journal(self) -> list[dict[str, Any]]:
        """Read complete rows, dropping only a torn trailing row."""

        try:
            payload = self.journal_path.read_bytes()
        except FileNotFoundError as error:
            raise StoreCorruption(f"journal is missing: {self.journal_path}") from error

        complete_payload = payload
        if payload and not payload.endswith(b"\n"):
            newline = payload.rfind(b"\n")
            complete_payload = payload[: newline + 1] if newline >= 0 else b""

        entries: list[dict[str, Any]] = []
        for position, raw_line in enumerate(complete_payload.splitlines(), start=1):
            try:
                decoded = json.loads(raw_line)
            except (json.JSONDecodeError, UnicodeDecodeError) as error:
                raise StoreCorruption(
                    f"journal corruption at complete line {position}"
                ) from error
            if not isinstance(decoded, dict):
                raise StoreCorruption(
                    f"journal corruption at complete line {position}: expected object"
                )
            _validate_entry(decoded, position)
            entries.append(decoded)
        return entries

    def _drop_torn_tail(self) -> None:
        payload = self.journal_path.read_bytes()
        if not payload or payload.endswith(b"\n"):
            return
        newline = payload.rfind(b"\n")
        complete_length = newline + 1 if newline >= 0 else 0
        with self.journal_path.open("r+b") as handle:
            handle.truncate(complete_length)
            handle.flush()
            os.fsync(handle.fileno())
        _fsync_directory(self.journal_path.parent)


def _normalize_state(state: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(state, Mapping):
        raise ValueError("state must be an object")
    normalized = deepcopy(dict(state))
    normalized.setdefault("plan_digest", None)
    if normalized.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"state schema_version must be {SCHEMA_VERSION}")
    if not isinstance(normalized.get("goal"), str) or not normalized["goal"].strip():
        raise ValueError("state goal must be a non-empty string")
    if not isinstance(normalized.get("test_paths"), list) or any(
        not isinstance(path, str) or not path for path in normalized["test_paths"]
    ):
        raise ValueError("state test_paths must be a list of non-empty strings")
    if normalized.get("plan_digest") is not None and (
        not isinstance(normalized["plan_digest"], str)
        or not normalized["plan_digest"]
    ):
        raise ValueError("state plan_digest must be a non-empty string or null")
    if not isinstance(normalized.get("tasks"), list):
        raise ValueError("state tasks must be a list")
    normalized["tasks"] = [_normalize_task(task) for task in normalized["tasks"]]
    _validate_graph(normalized["tasks"])
    _canonical_json(normalized)
    return normalized


def _normalize_task(task: Any) -> dict[str, Any]:
    if not isinstance(task, Mapping):
        raise ValueError("each task must be an object")
    normalized = deepcopy(dict(task))
    normalized.setdefault("test_changes", False)
    if normalized.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"task schema_version must be {SCHEMA_VERSION}")
    for field in ("id", "title", "role", "effort", "check"):
        _required_text(normalized, field)
    validate_task_id(normalized["id"])
    if not isinstance(normalized.get("depends_on"), list) or any(
        not isinstance(item, str) or not item for item in normalized["depends_on"]
    ):
        raise ValueError("task depends_on must be a list of non-empty strings")
    if len(set(normalized["depends_on"])) != len(normalized["depends_on"]):
        raise ValueError(f"task {normalized['id']} has duplicate dependencies")
    if not isinstance(normalized.get("decisions"), list) or any(
        not isinstance(item, str) or not item for item in normalized["decisions"]
    ):
        raise ValueError("task decisions must be a list of non-empty strings")
    if not isinstance(normalized.get("test_changes"), bool):
        raise ValueError("task test_changes must be a boolean")
    attempts = normalized.get("attempts")
    if not isinstance(attempts, Mapping) or set(attempts) != {
        "work",
        "infra",
        "diagnostic",
    }:
        raise ValueError("task attempts must contain work, infra, and diagnostic")
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in attempts.values()
    ):
        raise ValueError("task attempt counts must be non-negative integers")
    normalized["attempts"] = dict(attempts)
    if normalized.get("completion") not in {"pending", "complete"}:
        raise ValueError("task completion must be pending or complete")
    verdict = normalized.get("verdict")
    if verdict is not None and verdict not in {
        "green",
        "red",
        "infra",
        "killed",
        "malformed",
    }:
        raise ValueError("task verdict is outside the closed verdict enum")
    if normalized["completion"] == "complete" and verdict is None:
        raise ValueError("a complete task must have a verdict")
    if normalized["completion"] == "pending" and verdict == "green":
        raise ValueError("a green task must be complete")
    if not isinstance(normalized.get("evidence"), list):
        raise ValueError("task evidence must be a list")
    if normalized.get("verified_head") is not None and (
        not isinstance(normalized["verified_head"], str)
        or not normalized["verified_head"]
    ):
        raise ValueError("task verified_head must be a non-empty string or null")
    lineage = normalized.get("lineage")
    if not isinstance(lineage, Mapping) or set(lineage) != {
        "retired",
        "revoked",
        "superseded_by",
    }:
        raise ValueError("task lineage has an invalid shape")
    if not isinstance(lineage["retired"], bool) or not isinstance(
        lineage["revoked"], bool
    ):
        raise ValueError("task lineage flags must be booleans")
    if lineage["superseded_by"] is not None and (
        not isinstance(lineage["superseded_by"], str)
        or not lineage["superseded_by"]
    ):
        raise ValueError("task superseded_by must be a non-empty string or null")
    normalized["lineage"] = dict(lineage)
    lease = normalized.get("lease")
    if lease is not None:
        if not isinstance(lease, Mapping) or set(lease) != {
            "lease_id",
            "holder",
            "acquired_at",
            "expires_at",
        }:
            raise ValueError("task lease has an invalid shape")
        _required_text(lease, "lease_id")
        _required_text(lease, "holder")
        for field in ("acquired_at", "expires_at"):
            if isinstance(lease[field], bool) or not isinstance(
                lease[field], (int, float)
            ):
                raise ValueError(f"task lease {field} must be a number")
        if lease["expires_at"] <= lease["acquired_at"]:
            raise ValueError("task lease must expire after it is acquired")
        normalized["lease"] = dict(lease)
    _canonical_json(normalized)
    return normalized


def _validate_graph(tasks: list[dict[str, Any]]) -> None:
    ids = [task["id"] for task in tasks]
    if len(set(ids)) != len(ids):
        raise ValueError("task ids must be unique")
    known = set(ids)
    for task in tasks:
        missing = set(task["depends_on"]) - known
        if missing:
            raise ValueError(
                f"task {task['id']} has unknown dependencies: {sorted(missing)}"
            )
        if task["id"] in task["depends_on"]:
            raise ValueError(f"task {task['id']} cannot depend on itself")

    visiting: set[str] = set()
    visited: set[str] = set()
    dependencies = {task["id"]: task["depends_on"] for task in tasks}

    def visit(task_id: str) -> None:
        if task_id in visiting:
            raise ValueError(f"task graph contains a cycle at {task_id}")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency in dependencies[task_id]:
            visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in ids:
        visit(task_id)


def _normalize_claim(claim: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(claim, Mapping):
        raise ValueError("claim must be an object")
    normalized = deepcopy(dict(claim))
    if normalized.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"claim schema_version must be {SCHEMA_VERSION}")
    for field in ("task_id", "holder", "lease_id", "candidate_head"):
        _required_text(normalized, field)
    validate_task_id(normalized["task_id"])
    if normalized.get("claim") != "passes":
        raise ValueError("claim must be the typed value 'passes'")
    if not isinstance(normalized.get("artifacts"), list) or any(
        not isinstance(item, str) or not item for item in normalized["artifacts"]
    ):
        raise ValueError("claim artifacts must be a list of non-empty strings")
    _canonical_json(normalized)
    return normalized


def _normalize_verification(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise InvalidTransition("verification artifact must be an object")
    normalized = deepcopy(dict(value))
    if normalized.get("schema_version") != SCHEMA_VERSION:
        raise InvalidTransition(
            f"verification schema_version must be {SCHEMA_VERSION}"
        )
    for field in (
        "task_id",
        "holder",
        "lease_id",
        "base_head",
        "candidate_head",
        "check_id",
        "check_command",
        "reason",
    ):
        try:
            _required_text(normalized, field)
        except ValueError as error:
            raise InvalidTransition(str(error)) from error
    validate_task_id(normalized["task_id"])
    if normalized.get("verdict") not in {"green", "red"}:
        raise InvalidTransition(
            "only green or red task verification can be recorded"
        )
    protected_changes = normalized.get("protected_changes", [])
    if not isinstance(protected_changes, list) or any(
        not isinstance(path, str) or not path for path in protected_changes
    ):
        raise InvalidTransition(
            "verification protected_changes must be a list of paths"
        )
    if len(set(protected_changes)) != len(protected_changes):
        raise InvalidTransition("verification protected_changes must be unique")
    normalized["protected_changes"] = list(protected_changes)
    artifacts = normalized.get("artifacts")
    if not isinstance(artifacts, list) or any(
        not isinstance(path, str) or not path for path in artifacts
    ):
        raise InvalidTransition("verification artifacts must be a list of paths")
    if normalized["verdict"] == "green":
        try:
            _required_text(normalized, "candidate_tree")
        except ValueError as error:
            raise InvalidTransition(str(error)) from error
        result = normalized.get("result")
        if not isinstance(result, Mapping):
            raise InvalidTransition("green verification requires a result object")
        if result.get("schema_version") != SCHEMA_VERSION:
            raise InvalidTransition("verification result schema version is invalid")
        if result.get("candidate_head") != normalized["candidate_head"]:
            raise InvalidTransition("verification result candidate does not match")
        if result.get("check_id") != normalized["check_id"]:
            raise InvalidTransition("verification result check does not match")
        observations = result.get("observations")
        if not isinstance(observations, list) or not observations:
            raise InvalidTransition("green verification requires observations")
        for observation in observations:
            if (
                not isinstance(observation, Mapping)
                or set(observation) != {"id", "status"}
                or not isinstance(observation["id"], str)
                or not observation["id"]
                or observation["status"] != "passed"
            ):
                raise InvalidTransition(
                    "green verification observations must all be passed"
                )
        process = normalized.get("process")
        if not isinstance(process, Mapping) or process.get("returncode") != 0:
            raise InvalidTransition("green verification process must exit zero")
    _canonical_json(normalized)
    return normalized


def _task_can_enter_frontier(
    task: Mapping[str, Any],
    by_id: Mapping[str, Mapping[str, Any]],
    now: float,
) -> bool:
    lineage = task["lineage"]
    if (
        task["completion"] != "pending"
        or task["verdict"] is not None
        or lineage["retired"]
        or lineage["revoked"]
        or lineage["superseded_by"] is not None
    ):
        return False
    lease = task["lease"]
    if lease is not None and lease["expires_at"] > now:
        return False
    return all(
        by_id[dependency]["completion"] == "complete"
        and by_id[dependency]["verdict"] == "green"
        for dependency in task["depends_on"]
    )


def _task_by_id(state: Mapping[str, Any], task_id: str) -> dict[str, Any]:
    for task in state["tasks"]:
        if task["id"] == task_id:
            return task
    raise InvalidTransition(f"unknown task: {task_id}")


def _required_text(value: Mapping[str, Any], field: str) -> str:
    candidate = value.get(field)
    if not isinstance(candidate, str) or not candidate:
        raise ValueError(f"{field} must be a non-empty string")
    return candidate


def validate_task_id(value: Any) -> str:
    """Return a task id that is safe as one workspace path component."""

    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}", value
    ):
        raise ValueError(
            "task id must be 1-120 ASCII letters, digits, dots, underscores, or "
            "hyphens and must start with a letter or digit"
        )
    return value


def _apply_plan_imported(
    state: dict[str, Any], transition: Mapping[str, Any]
) -> None:
    if state["tasks"] or state["plan_digest"] is not None:
        raise InvalidTransition("a plan has already been imported")
    goal = _required_text(transition, "goal")
    if goal != state["goal"]:
        raise InvalidTransition("imported plan goal does not match initialized goal")
    digest = _required_text(transition, "plan_digest")
    test_paths = transition.get("test_paths")
    tasks = transition.get("tasks")
    candidate = deepcopy(state)
    candidate["plan_digest"] = digest
    candidate["test_paths"] = deepcopy(test_paths)
    candidate["tasks"] = deepcopy(tasks)
    normalized = _normalize_state(candidate)
    state.clear()
    state.update(normalized)


def _apply_task_released(
    state: dict[str, Any], transition: Mapping[str, Any]
) -> None:
    task_id = _required_text(transition, "task_id")
    holder = _required_text(transition, "holder")
    lease_id = _required_text(transition, "lease_id")
    attempt_type = _required_text(transition, "attempt_type")
    if attempt_type not in {"work", "infra", "diagnostic"}:
        raise InvalidTransition(f"unknown attempt type: {attempt_type}")
    task = _task_by_id(state, task_id)
    lease = task["lease"]
    if (
        lease is None
        or lease["holder"] != holder
        or lease["lease_id"] != lease_id
    ):
        raise InvalidTransition("released task is not leased by the holder")
    task["attempts"][attempt_type] += 1
    task["lease"] = None


def _normalize_transition(transition: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(transition, Mapping):
        raise ValueError("transition must be an object")
    normalized = deepcopy(dict(transition))
    if not isinstance(normalized.get("type"), str) or not normalized["type"].strip():
        raise ValueError("transition type must be a non-empty string")
    _canonical_json(normalized)
    return normalized


def _journal_entry(
    sequence: int,
    transition: Mapping[str, Any],
    state: Mapping[str, Any],
) -> dict[str, Any]:
    state_copy = deepcopy(dict(state))
    return {
        "sequence": sequence,
        "transition": deepcopy(dict(transition)),
        "state_hash": _state_hash(state_copy),
        "state_after": state_copy,
    }


def _validate_entry(entry: Mapping[str, Any], position: int) -> dict[str, Any]:
    if entry.get("sequence") != position:
        raise StoreCorruption(
            f"journal sequence mismatch at complete line {position}"
        )
    try:
        transition = _normalize_transition(entry["transition"])
        raw_state = entry["state_after"]
        if not isinstance(raw_state, Mapping):
            raise ValueError("state_after must be an object")
        state = _normalize_state(raw_state)
    except (KeyError, TypeError, ValueError) as error:
        raise StoreCorruption(
            f"invalid journal entry at complete line {position}: {error}"
        ) from error
    if entry.get("state_hash") != _state_hash(raw_state):
        raise StoreCorruption(
            f"journal state hash mismatch at complete line {position}"
        )
    if dict(entry["transition"]) != transition:
        raise StoreCorruption(
            f"invalid journal transition at complete line {position}"
        )
    return state


def _state_hash(state: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(state)).hexdigest()


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError(f"value is not JSON-serializable: {error}") from error


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise StoreCorruption(f"invalid JSON in {path}") from error
    if not isinstance(value, dict):
        raise StoreCorruption(f"expected a JSON object in {path}")
    return value


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_canonical_json(value) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        _fsync_directory(path.parent)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _append_json_line(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _canonical_json(value) + b"\n"
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        written = os.write(descriptor, payload)
        if written != len(payload):
            raise OSError(f"short journal write: {written} of {len(payload)} bytes")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _fsync_directory(path.parent)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
