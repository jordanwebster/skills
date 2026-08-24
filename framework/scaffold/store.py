"""Crash-safe current state and append-only transition journal."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any


SCHEMA_VERSION = 1


class StoreError(Exception):
    """Base class for task-store errors."""


class StoreCorruption(StoreError):
    """Raised when durable state cannot be interpreted safely."""


class StoreExists(StoreError):
    """Raised when initialization would overwrite an existing store."""


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

    def create(self, state: Mapping[str, Any]) -> dict[str, Any]:
        """Create a new store without overwriting any durable state."""

        normalized = _normalize_state(state)
        self.root.mkdir(parents=True, exist_ok=True)
        if self.state_path.exists() or self.journal_path.exists():
            raise StoreExists(f"store already exists at {self.root}")

        entry = _journal_entry(1, {"type": "initialized"}, normalized)
        _append_json_line(self.journal_path, entry)
        _atomic_write_json(self.state_path, normalized)
        return deepcopy(normalized)

    def load(self) -> dict[str, Any]:
        """Load state, replaying the journal if its materialized view is stale."""

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

    def replace(
        self,
        state: Mapping[str, Any],
        transition: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Append one transition and atomically materialize its resulting state."""

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
    if normalized.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"state schema_version must be {SCHEMA_VERSION}")
    if not isinstance(normalized.get("goal"), str) or not normalized["goal"].strip():
        raise ValueError("state goal must be a non-empty string")
    if not isinstance(normalized.get("test_paths"), list) or any(
        not isinstance(path, str) or not path for path in normalized["test_paths"]
    ):
        raise ValueError("state test_paths must be a list of non-empty strings")
    if not isinstance(normalized.get("tasks"), list):
        raise ValueError("state tasks must be a list")
    _canonical_json(normalized)
    return normalized


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
        state = _normalize_state(entry["state_after"])
    except (KeyError, TypeError, ValueError) as error:
        raise StoreCorruption(
            f"invalid journal entry at complete line {position}: {error}"
        ) from error
    if entry.get("state_hash") != _state_hash(state):
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
