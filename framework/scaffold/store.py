"""Crash-safe current state and append-only transition journal."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
import fcntl
import fnmatch
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any
import uuid

from .judge import normalize_decision
from .proposal import (
    normalize_claim_proposals,
    normalize_folding,
    normalize_proposal,
    normalize_proposal_templates,
    normalize_routing_record,
    pending_proposals,
    proposal_batch_id,
)


SCHEMA_VERSION = 1
REVIEW_SEVERITIES = ("low", "medium", "high", "critical")


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
        "review_severity_bar": None,
        "proposal_templates": {},
        "phase": "working",
        "presented_head": None,
        "bless_subject": None,
        "blessing": None,
        "demonstrations": [],
        "blessed_demonstrations": [],
        "tasks": [],
        "proposals": [],
        "followups": [],
        "outbox": [],
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
        reservation_seconds: float | None = None,
        now: float | None = None,
    ) -> Path:
        """Retain a typed claim and reserve its lease in one transition."""

        task_id = validate_task_id(task_id)
        if reservation_seconds is not None and (
            isinstance(reservation_seconds, bool)
            or not isinstance(reservation_seconds, (int, float))
            or reservation_seconds <= 0
        ):
            raise ValueError("reservation_seconds must be positive or None")
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
            if task["role"] == "reviewer" and normalized.get("review") is None:
                raise InvalidTransition("reviewer claim must contain a review result")
            if task["role"] != "reviewer" and normalized.get("review") is not None:
                raise InvalidTransition("only reviewer tasks may file review findings")
            existing_proposal_ids = {item["id"] for item in state["proposals"]}
            claimed_proposal_ids = {
                item["id"] for item in normalized.get("proposals", [])
            }
            if existing_proposal_ids & claimed_proposal_ids:
                raise InvalidTransition("claim proposal id already exists")
            lease = task["lease"]
            if lease is None or lease["holder"] != normalized["holder"]:
                raise InvalidTransition("claim holder does not own the task lease")
            if lease["lease_id"] != normalized["lease_id"]:
                raise InvalidTransition("claim does not belong to the current lease")
            if lease["expires_at"] <= observed_at:
                raise InvalidTransition("task lease expired before the claim was filed")
            lease_duration = lease["expires_at"] - lease["acquired_at"]
            reserved_for = (
                lease_duration
                if reservation_seconds is None
                else float(reservation_seconds)
            )
            expires_at = observed_at + reserved_for
            destination = self.claims_path / f"{task_id}.json"
            _atomic_write_json(destination, normalized)
            lease["expires_at"] = expires_at
            self._replace_unlocked(
                state,
                {
                    "type": "task-lease-renewed",
                    "task_id": task_id,
                    "holder": normalized["holder"],
                    "lease_id": normalized["lease_id"],
                    "observed_at": observed_at,
                    "expires_at": expires_at,
                    "reason": "claim-filed",
                },
            )
        return destination

    def renew(
        self,
        task_id: str,
        holder: str,
        lease_id: str,
        *,
        ttl_seconds: float,
        now: float | None = None,
    ) -> Lease:
        """Extend the current claimed lease before framework verification."""

        task_id = validate_task_id(task_id)
        if not isinstance(holder, str) or not holder:
            raise ValueError("holder must be a non-empty string")
        if not isinstance(lease_id, str) or not lease_id:
            raise ValueError("lease_id must be a non-empty string")
        if (
            isinstance(ttl_seconds, bool)
            or not isinstance(ttl_seconds, (int, float))
            or ttl_seconds <= 0
        ):
            raise ValueError("ttl_seconds must be positive")
        if now is not None and (
            isinstance(now, bool) or not isinstance(now, (int, float))
        ):
            raise ValueError("now must be a number or None")
        observed_at = time.time() if now is None else float(now)

        with self._locked():
            state = self._load_unlocked()
            task = _task_by_id(state, task_id)
            lease = task["lease"]
            if (
                task["completion"] != "pending"
                or task["verdict"] is not None
                or lease is None
                or lease["holder"] != holder
                or lease["lease_id"] != lease_id
            ):
                raise InvalidTransition(
                    "renewed task is not pending under the named lease"
                )
            claim = self.read_claim(task_id)
            if claim["holder"] != holder or claim["lease_id"] != lease_id:
                raise InvalidTransition(
                    "lease cannot be renewed without its current filed claim"
                )
            expires_at = observed_at + float(ttl_seconds)
            lease["expires_at"] = expires_at
            self._replace_unlocked(
                state,
                {
                    "type": "task-lease-renewed",
                    "task_id": task_id,
                    "holder": holder,
                    "lease_id": lease_id,
                    "observed_at": observed_at,
                    "expires_at": expires_at,
                },
            )
            return Lease(
                task_id,
                holder,
                lease_id,
                lease["acquired_at"],
                expires_at,
            )

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
            if transition_type == "flight-blessed":
                if not self._apply_flight_blessed(state, normalized):
                    return deepcopy(state)
            elif state["phase"] == "accepted":
                raise InvalidTransition("an accepted flight is terminal")
            elif transition_type == "plan-imported":
                _apply_plan_imported(state, normalized)
            elif transition_type == "task-verification-recorded":
                if "observed_at" not in normalized:
                    normalized["observed_at"] = time.time()
                self._apply_task_verification(state, normalized)
            elif transition_type == "task-released":
                _apply_task_released(state, normalized)
            elif transition_type == "task-judged":
                _apply_task_judged(state, normalized)
            elif transition_type == "proposal-batch-folded":
                _apply_proposal_batch_folded(state, normalized)
            elif transition_type == "proposal-batch-failed":
                _apply_proposal_batch_failed(state, normalized)
            elif transition_type == "demonstration-invalidated":
                _apply_demonstration_invalidated(state, normalized)
            elif transition_type == "demonstrations-refresh-started":
                _apply_demonstrations_refresh_started(state, normalized)
            elif transition_type == "demonstration-captured":
                self._apply_demonstration_captured(state, normalized)
            elif transition_type == "demonstrations-ready":
                self._apply_demonstrations_ready(state, normalized)
            else:
                raise InvalidTransition(
                    f"unsupported transition type: {transition_type}"
                )
            normalized_state = _normalize_state(state)
            return self._replace_unlocked(normalized_state, normalized)

    def _apply_flight_blessed(
        self,
        state: dict[str, Any],
        transition: Mapping[str, Any],
    ) -> bool:
        subject = _required_text(transition, "subject")
        accepted_at = transition.get("accepted_at")
        if (
            isinstance(accepted_at, bool)
            or not isinstance(accepted_at, (int, float))
            or not math.isfinite(accepted_at)
            or accepted_at < 0
        ):
            raise InvalidTransition("blessing accepted_at must be a finite timestamp")
        if state["phase"] == "accepted":
            blessing = state["blessing"]
            if blessing is not None and blessing["subject"] == subject:
                return False
            raise InvalidTransition("flight was already accepted for another subject")
        if state["phase"] != "done-pending-bless":
            raise InvalidTransition("flight is not ready for acceptance")
        if subject != state["bless_subject"]:
            raise InvalidTransition("acceptance does not match the presented subject")

        blessed: list[dict[str, Any]] = []
        for demonstration in state["demonstrations"]:
            candidate = demonstration["candidate"]
            if candidate is None:
                raise InvalidTransition(
                    f"demonstration has no candidate to bless: {demonstration['id']}"
                )
            artifact = self._read_demonstration_artifact(
                demonstration,
                candidate["artifact_path"],
                candidate["artifact_sha256"],
            )
            if artifact["verified_head"] != state["presented_head"]:
                raise InvalidTransition(
                    "blessed demonstration names a different presented head"
                )
            blessed.append(
                {
                    "demonstration_id": demonstration["id"],
                    "verified_head": candidate["verified_head"],
                    "artifact_path": candidate["artifact_path"],
                    "artifact_sha256": candidate["artifact_sha256"],
                    "surface_fingerprints": deepcopy(
                        candidate["surface_fingerprints"]
                    ),
                    "captured_at": candidate["captured_at"],
                    "blessed_at": float(accepted_at),
                }
            )
        state["phase"] = "accepted"
        state["blessing"] = {
            "subject": subject,
            "presented_head": state["presented_head"],
            "accepted_at": float(accepted_at),
        }
        state["blessed_demonstrations"] = blessed
        return True

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
        if verification["verdict"] == "green" and task["role"] == "reviewer":
            _apply_review_routing(
                state,
                task,
                claim["review"],
                observed_at=float(observed_at),
            )
        if verification["verdict"] == "green":
            _retain_claim_proposals(
                state,
                task,
                claim.get("proposals", []),
                observed_at=float(observed_at),
            )

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

    def read_demonstration_capture(self, demonstration_id: str) -> dict[str, Any]:
        """Read and validate the retained artifact for one candidate capture."""

        demonstration_id = validate_task_id(demonstration_id)
        state = self.load()
        demonstration = _demonstration_by_id(state, demonstration_id)
        candidate = demonstration["candidate"]
        if candidate is None:
            raise InvalidTransition(
                f"demonstration has no candidate capture: {demonstration_id}"
            )
        return self._read_demonstration_artifact(
            demonstration,
            candidate["artifact_path"],
            candidate["artifact_sha256"],
        )

    def _apply_demonstration_captured(
        self,
        state: dict[str, Any],
        transition: Mapping[str, Any],
    ) -> None:
        demonstration_id = _required_text(transition, "demonstration_id")
        demonstration = _demonstration_by_id(state, demonstration_id)
        candidate = _normalize_demonstration_candidate(
            transition.get("candidate")
        )
        artifact = self._read_demonstration_artifact(
            demonstration,
            candidate["artifact_path"],
            candidate["artifact_sha256"],
        )
        if artifact["verified_head"] != candidate["verified_head"]:
            raise InvalidTransition(
                "demonstration artifact names a different verified head"
            )
        if artifact["surface_fingerprints"] != candidate["surface_fingerprints"]:
            raise InvalidTransition(
                "demonstration artifact surface fingerprints do not match"
            )
        demonstration["candidate"] = candidate
        state["phase"] = "working"
        state["presented_head"] = None
        state["bless_subject"] = None

    def _apply_demonstrations_ready(
        self,
        state: dict[str, Any],
        transition: Mapping[str, Any],
    ) -> None:
        presented_head = _required_text(transition, "presented_head")
        active_tasks = [
            task
            for task in state["tasks"]
            if not task["lineage"]["retired"]
            and not task["lineage"]["revoked"]
            and task["lineage"]["superseded_by"] is None
        ]
        if not active_tasks or any(
            task["completion"] != "complete" or task["verdict"] != "green"
            for task in active_tasks
        ):
            raise InvalidTransition(
                "demonstrations cannot be ready before every active task is green"
            )
        if pending_proposals(state):
            raise InvalidTransition(
                "demonstrations cannot be ready while proposals await routing"
            )
        if any(item["status"] == "open" for item in state["outbox"]):
            raise InvalidTransition(
                "demonstrations cannot be ready while operator answers are pending"
            )
        for demonstration in state["demonstrations"]:
            candidate = demonstration["candidate"]
            if candidate is None or candidate["verified_head"] != presented_head:
                raise InvalidTransition(
                    f"demonstration is not fresh at the presented commit: "
                    f"{demonstration['id']}"
                )
            self._read_demonstration_artifact(
                demonstration,
                candidate["artifact_path"],
                candidate["artifact_sha256"],
            )
        state["phase"] = "done-pending-bless"
        state["presented_head"] = presented_head
        state["bless_subject"] = _blessing_subject(state)

    def _read_demonstration_artifact(
        self,
        demonstration: Mapping[str, Any],
        relative_name: str,
        expected_sha256: str,
    ) -> dict[str, Any]:
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            raise InvalidTransition(
                "demonstration artifact digest must be a SHA-256 digest"
            )
        path = _contained_store_path(self.root, relative_name)
        try:
            payload = path.read_bytes()
        except OSError as error:
            raise InvalidTransition(
                f"cannot read demonstration artifact: {error}"
            ) from error
        if hashlib.sha256(payload).hexdigest() != expected_sha256:
            raise InvalidTransition("demonstration artifact digest does not match")
        try:
            value = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise InvalidTransition(
                "demonstration artifact is not valid JSON"
            ) from error
        artifact = _normalize_demonstration_artifact(value)
        if artifact["demonstration_id"] != demonstration["id"]:
            raise InvalidTransition(
                "demonstration artifact belongs to a different demonstration"
            )
        if artifact["command"] != demonstration["command"]:
            raise InvalidTransition("demonstration artifact names a different command")
        if artifact["title"] != demonstration["title"]:
            raise InvalidTransition("demonstration artifact names a different title")
        fingerprints = artifact["surface_fingerprints"]
        if not fingerprints or any(
            not any(
                _matches_product_pattern(path, pattern)
                for pattern in demonstration["surface_paths"]
            )
            for path in fingerprints
        ):
            raise InvalidTransition(
                "demonstration artifact fingerprints undeclared surfaces"
            )
        stdout_outputs = [
            output for output in artifact["outputs"] if output["kind"] == "stdout"
        ]
        stderr_outputs = [
            output for output in artifact["outputs"] if output["kind"] == "stderr"
        ]
        artifact_outputs = [
            output
            for output in artifact["outputs"]
            if output["kind"] == "artifact"
        ]
        if (
            len(stdout_outputs) != 1
            or stdout_outputs[0]["source"] != ""
            or len(stderr_outputs) != 1
            or stderr_outputs[0]["source"] != ""
            or {output["source"] for output in artifact_outputs}
            != set(demonstration["artifact_paths"])
        ):
            raise InvalidTransition(
                "demonstration outputs do not match the planned capture set"
            )
        for output in artifact["outputs"]:
            output_path = _contained_store_path(self.root, output["path"])
            try:
                output_payload = output_path.read_bytes()
            except OSError as error:
                raise InvalidTransition(
                    f"cannot read retained demonstration output: {error}"
                ) from error
            if len(output_payload) != output["size"]:
                raise InvalidTransition("demonstration output size does not match")
            if hashlib.sha256(output_payload).hexdigest() != output["sha256"]:
                raise InvalidTransition("demonstration output digest does not match")
        return artifact

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
    if "review_severity_bar" not in normalized:
        normalized["review_severity_bar"] = (
            "medium" if normalized.get("plan_digest") is not None else None
        )
    normalized.setdefault("proposals", [])
    normalized.setdefault("followups", [])
    normalized.setdefault("proposal_templates", {})
    normalized.setdefault("outbox", [])
    normalized.setdefault("phase", "working")
    normalized.setdefault("presented_head", None)
    normalized.setdefault("bless_subject", None)
    normalized.setdefault("blessing", None)
    normalized.setdefault("demonstrations", [])
    normalized.setdefault("blessed_demonstrations", [])
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
    if normalized["review_severity_bar"] is not None and (
        normalized["review_severity_bar"] not in REVIEW_SEVERITIES
    ):
        raise ValueError(
            "state review_severity_bar must be low, medium, high, critical, or null"
        )
    normalized["proposal_templates"] = normalize_proposal_templates(
        normalized["proposal_templates"]
    )
    if normalized["phase"] not in {"working", "done-pending-bless", "accepted"}:
        raise ValueError(
            "state phase must be working, done-pending-bless, or accepted"
        )
    if normalized["presented_head"] is not None and (
        not isinstance(normalized["presented_head"], str)
        or not normalized["presented_head"]
    ):
        raise ValueError("state presented_head must be non-empty text or null")
    if normalized["phase"] == "working" and normalized["presented_head"] is not None:
        raise ValueError("a working flight cannot name a presented head")
    if normalized["phase"] in {"done-pending-bless", "accepted"} and (
        normalized["presented_head"] is None
    ):
        raise ValueError("a ready or accepted flight must name its presented head")
    if not isinstance(normalized["demonstrations"], list):
        raise ValueError("state demonstrations must be a list")
    normalized["demonstrations"] = [
        normalize_demonstration(item) for item in normalized["demonstrations"]
    ]
    demonstration_ids = [item["id"] for item in normalized["demonstrations"]]
    if len(set(demonstration_ids)) != len(demonstration_ids):
        raise ValueError("state demonstration ids must be unique")
    if normalized["phase"] in {"done-pending-bless", "accepted"} and any(
        demonstration["candidate"] is None
        or demonstration["candidate"]["verified_head"]
        != normalized["presented_head"]
        for demonstration in normalized["demonstrations"]
    ):
        raise ValueError(
            "a ready or accepted flight requires fresh demonstration candidates"
        )
    if normalized["phase"] in {"done-pending-bless", "accepted"}:
        expected_subject = _blessing_subject(normalized)
        if normalized["bless_subject"] is None:
            normalized["bless_subject"] = expected_subject
        elif normalized["bless_subject"] != expected_subject:
            raise ValueError("state bless_subject does not match its presented subject")
    elif normalized["bless_subject"] is not None:
        raise ValueError("a working flight cannot name a blessing subject")

    blessing = normalized["blessing"]
    if blessing is not None:
        normalized["blessing"] = _normalize_blessing(blessing)
    if not isinstance(normalized["blessed_demonstrations"], list):
        raise ValueError("state blessed_demonstrations must be a list")
    normalized["blessed_demonstrations"] = [
        _normalize_blessed_demonstration(item)
        for item in normalized["blessed_demonstrations"]
    ]
    blessed_ids = [
        item["demonstration_id"]
        for item in normalized["blessed_demonstrations"]
    ]
    if len(set(blessed_ids)) != len(blessed_ids):
        raise ValueError("blessed demonstration ids must be unique")
    if normalized["phase"] == "accepted":
        if blessing is None:
            raise ValueError("an accepted flight requires its blessing record")
        if (
            normalized["blessing"]["subject"] != normalized["bless_subject"]
            or normalized["blessing"]["presented_head"]
            != normalized["presented_head"]
        ):
            raise ValueError("accepted flight blessing does not match its subject")
        candidates = {
            item["id"]: item["candidate"]
            for item in normalized["demonstrations"]
        }
        if set(blessed_ids) != set(candidates):
            raise ValueError("accepted flight must bless every demonstration")
        for item in normalized["blessed_demonstrations"]:
            candidate = candidates[item["demonstration_id"]]
            if candidate is None or any(
                item[field] != candidate[field]
                for field in (
                    "verified_head",
                    "artifact_path",
                    "artifact_sha256",
                    "surface_fingerprints",
                    "captured_at",
                )
            ):
                raise ValueError(
                    "blessed demonstration does not match its accepted candidate"
                )
            if item["blessed_at"] != normalized["blessing"]["accepted_at"]:
                raise ValueError("blessed demonstration has a different acceptance time")
    elif blessing is not None or normalized["blessed_demonstrations"]:
        raise ValueError("only an accepted flight may retain blessed demonstrations")
    if not isinstance(normalized.get("tasks"), list):
        raise ValueError("state tasks must be a list")
    normalized["tasks"] = [_normalize_task(task) for task in normalized["tasks"]]
    _validate_graph(normalized["tasks"])
    tasks_by_id = {task["id"]: task for task in normalized["tasks"]}
    for task in normalized["tasks"]:
        review = task["review"]
        if review is None:
            continue
        origin = tasks_by_id.get(review["origin_task_id"])
        if review["round"] == 0 and review["origin_task_id"] != task["id"]:
            raise ValueError("initial review must name itself as its origin")
        if review["round"] == 1 and (
            origin is None
            or origin["role"] != "reviewer"
            or origin["review"]["round"] != 0
        ):
            raise ValueError("re-review must name an initial reviewer task")
    if not isinstance(normalized.get("proposals"), list):
        raise ValueError("state proposals must be a list")
    normalized["proposals"] = [
        normalize_proposal(item) for item in normalized["proposals"]
    ]
    proposal_ids = [item["id"] for item in normalized["proposals"]]
    if len(set(proposal_ids)) != len(proposal_ids):
        raise ValueError("state proposal ids must be unique")
    for proposal in normalized["proposals"]:
        if proposal["source_task_id"] not in tasks_by_id:
            raise ValueError("proposal names an unknown source task")
        routing = proposal["routing"]
        if routing is None:
            continue
        if routing["disposition"] == "in-envelope" and (
            routing["task_id"] not in tasks_by_id
        ):
            raise ValueError("routed proposal names an unknown task")
    if not isinstance(normalized.get("followups"), list):
        raise ValueError("state followups must be a list")
    normalized["followups"] = [
        _normalize_followup(item) for item in normalized["followups"]
    ]
    followup_ids = [item["proposal_id"] for item in normalized["followups"]]
    if len(set(followup_ids)) != len(followup_ids):
        raise ValueError("state followups must name unique proposals")
    for followup in normalized["followups"]:
        if followup["proposal_id"] not in proposal_ids:
            raise ValueError("followup names an unknown proposal")
        proposal = next(
            item
            for item in normalized["proposals"]
            if item["id"] == followup["proposal_id"]
        )
        if (
            proposal["routing"] is None
            or proposal["routing"]["disposition"] != "beyond-flight"
        ):
            raise ValueError("followup lacks a beyond-flight proposal route")
    if not isinstance(normalized.get("outbox"), list):
        raise ValueError("state outbox must be a list")
    normalized["outbox"] = [
        _normalize_escalation(item) for item in normalized["outbox"]
    ]
    escalation_ids = [item["id"] for item in normalized["outbox"]]
    if len(set(escalation_ids)) != len(escalation_ids):
        raise ValueError("state outbox ids must be unique")
    for escalation in normalized["outbox"]:
        task = tasks_by_id.get(escalation["task_id"])
        if task is None:
            raise ValueError("state outbox names an unknown task")
        if not any(
            judgment["decision"] == "defer-to-operator"
            and judgment["trigger"] == escalation["trigger"]
            and judgment["observed_at"] == escalation["created_at"]
            for judgment in task["judgments"]
        ):
            raise ValueError("state outbox lacks its matching task judgment")
    if normalized["phase"] in {"done-pending-bless", "accepted"}:
        active_tasks = [
            task
            for task in normalized["tasks"]
            if not task["lineage"]["retired"]
            and not task["lineage"]["revoked"]
            and task["lineage"]["superseded_by"] is None
        ]
        if not active_tasks or any(
            task["completion"] != "complete" or task["verdict"] != "green"
            for task in active_tasks
        ):
            raise ValueError("a ready flight requires every active task to be green")
        if pending_proposals(normalized):
            raise ValueError("a ready flight cannot have unrouted proposals")
        if any(item["status"] == "open" for item in normalized["outbox"]):
            raise ValueError("a ready flight cannot await an operator answer")
    _canonical_json(normalized)
    return normalized


def _normalize_task(task: Any) -> dict[str, Any]:
    if not isinstance(task, Mapping):
        raise ValueError("each task must be an object")
    normalized = deepcopy(dict(task))
    normalized.setdefault("test_changes", False)
    normalized.setdefault("parked", False)
    normalized.setdefault("judgments", [])
    normalized.setdefault("review", None)
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
    if not isinstance(normalized.get("parked"), bool):
        raise ValueError("task parked must be a boolean")
    if not isinstance(normalized.get("judgments"), list):
        raise ValueError("task judgments must be a list")
    normalized["judgments"] = [
        _normalize_recorded_judgment(item) for item in normalized["judgments"]
    ]
    if any(
        judgment["task_id"] != normalized["id"]
        for judgment in normalized["judgments"]
    ):
        raise ValueError("task judgment names a different task")
    review = normalized["review"]
    if normalized["role"] == "reviewer":
        if review is None:
            review = {
                "origin_task_id": normalized["id"],
                "round": 0,
                "remediation": {
                    "role": "implementer",
                    "effort": normalized["effort"],
                    "check": normalized["check"],
                    "test_changes": False,
                },
                "findings": None,
            }
        normalized["review"] = _normalize_review_task(review)
    elif review is not None:
        raise ValueError("only reviewer tasks may contain review routing state")
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


def normalize_demonstration(value: Any) -> dict[str, Any]:
    """Normalize one planned demonstration and its optional candidate."""

    required = {
        "schema_version",
        "id",
        "title",
        "command",
        "surface_paths",
        "artifact_paths",
        "candidate",
    }
    if not isinstance(value, Mapping):
        raise ValueError("each demonstration must be an object")
    normalized = deepcopy(dict(value))
    normalized.setdefault("schema_version", SCHEMA_VERSION)
    normalized.setdefault("artifact_paths", [])
    normalized.setdefault("candidate", None)
    if set(normalized) != required:
        raise ValueError("demonstration has the wrong fields")
    if normalized["schema_version"] != SCHEMA_VERSION:
        raise ValueError(
            f"demonstration schema_version must be {SCHEMA_VERSION}"
        )
    validate_task_id(normalized.get("id"))
    for field in ("title", "command"):
        _required_text(normalized, field)
    for field in ("surface_paths", "artifact_paths"):
        paths = normalized.get(field)
        if not isinstance(paths, list) or any(
            not _safe_product_pattern(path) for path in paths
        ):
            raise ValueError(
                f"demonstration {field} must contain safe relative paths"
            )
        if len(set(paths)) != len(paths):
            raise ValueError(f"demonstration {field} must be unique")
        normalized[field] = list(paths)
    if not normalized["surface_paths"]:
        raise ValueError("demonstration surface_paths must not be empty")
    candidate = normalized.get("candidate")
    if candidate is not None:
        normalized["candidate"] = _normalize_demonstration_candidate(candidate)
    _canonical_json(normalized)
    return normalized


def _normalize_demonstration_candidate(value: Any) -> dict[str, Any]:
    required = {
        "verified_head",
        "artifact_path",
        "artifact_sha256",
        "surface_fingerprints",
        "captured_at",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise ValueError("demonstration candidate has the wrong fields")
    normalized = deepcopy(dict(value))
    for field in ("verified_head", "artifact_path", "artifact_sha256"):
        _required_text(normalized, field)
    if not re.fullmatch(r"[0-9a-f]{64}", normalized["artifact_sha256"]):
        raise ValueError("demonstration candidate digest must be SHA-256")
    _validate_relative_path(normalized["artifact_path"], "artifact_path")
    fingerprints = normalized.get("surface_fingerprints")
    if not isinstance(fingerprints, Mapping) or any(
        not _safe_product_pattern(path)
        or not isinstance(digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", digest)
        for path, digest in fingerprints.items()
    ):
        raise ValueError("demonstration candidate surface fingerprints are invalid")
    normalized["surface_fingerprints"] = dict(fingerprints)
    captured_at = normalized.get("captured_at")
    if (
        isinstance(captured_at, bool)
        or not isinstance(captured_at, (int, float))
        or not math.isfinite(captured_at)
        or captured_at < 0
    ):
        raise ValueError("demonstration captured_at must be a finite timestamp")
    normalized["captured_at"] = float(captured_at)
    return normalized


def _blessing_subject(state: Mapping[str, Any]) -> str:
    presented_head = state.get("presented_head")
    if not isinstance(presented_head, str) or not presented_head:
        raise ValueError("a blessing subject requires a presented head")
    demonstrations = state.get("demonstrations")
    if not isinstance(demonstrations, list):
        raise ValueError("a blessing subject requires demonstrations")
    subject = {
        "schema_version": SCHEMA_VERSION,
        "goal": state.get("goal"),
        "plan_digest": state.get("plan_digest"),
        "presented_head": presented_head,
        "demonstrations": [
            {
                "id": demonstration["id"],
                "candidate": demonstration["candidate"],
            }
            for demonstration in demonstrations
        ],
    }
    return hashlib.sha256(_canonical_json(subject)).hexdigest()


def _normalize_blessing(value: Any) -> dict[str, Any]:
    required = {"subject", "presented_head", "accepted_at"}
    if not isinstance(value, Mapping) or set(value) != required:
        raise ValueError("blessing record has the wrong fields")
    normalized = deepcopy(dict(value))
    for field in ("subject", "presented_head"):
        _required_text(normalized, field)
    if not re.fullmatch(r"[0-9a-f]{64}", normalized["subject"]):
        raise ValueError("blessing subject must be a SHA-256 digest")
    accepted_at = normalized["accepted_at"]
    if (
        isinstance(accepted_at, bool)
        or not isinstance(accepted_at, (int, float))
        or not math.isfinite(accepted_at)
        or accepted_at < 0
    ):
        raise ValueError("blessing accepted_at must be a finite timestamp")
    normalized["accepted_at"] = float(accepted_at)
    return normalized


def _normalize_blessed_demonstration(value: Any) -> dict[str, Any]:
    required = {
        "demonstration_id",
        "verified_head",
        "artifact_path",
        "artifact_sha256",
        "surface_fingerprints",
        "captured_at",
        "blessed_at",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise ValueError("blessed demonstration has the wrong fields")
    normalized = deepcopy(dict(value))
    validate_task_id(normalized.get("demonstration_id"))
    candidate = _normalize_demonstration_candidate(
        {
            field: normalized[field]
            for field in (
                "verified_head",
                "artifact_path",
                "artifact_sha256",
                "surface_fingerprints",
                "captured_at",
            )
        }
    )
    blessed_at = normalized["blessed_at"]
    if (
        isinstance(blessed_at, bool)
        or not isinstance(blessed_at, (int, float))
        or not math.isfinite(blessed_at)
        or blessed_at < 0
    ):
        raise ValueError("blessed_at must be a finite timestamp")
    return {
        "demonstration_id": normalized["demonstration_id"],
        **candidate,
        "blessed_at": float(blessed_at),
    }


def _normalize_demonstration_artifact(value: Any) -> dict[str, Any]:
    required = {
        "schema_version",
        "demonstration_id",
        "title",
        "command",
        "verified_head",
        "surface_fingerprints",
        "captured_at",
        "process",
        "outputs",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise InvalidTransition("demonstration artifact has the wrong fields")
    normalized = deepcopy(dict(value))
    if normalized.get("schema_version") != SCHEMA_VERSION:
        raise InvalidTransition("demonstration artifact schema version is invalid")
    try:
        validate_task_id(normalized.get("demonstration_id"))
        for field in ("title", "command", "verified_head"):
            _required_text(normalized, field)
        candidate = _normalize_demonstration_candidate(
            {
                "verified_head": normalized["verified_head"],
                "artifact_path": "placeholder.json",
                "artifact_sha256": "0" * 64,
                "surface_fingerprints": normalized["surface_fingerprints"],
                "captured_at": normalized["captured_at"],
            }
        )
    except ValueError as error:
        raise InvalidTransition(str(error)) from error
    normalized["surface_fingerprints"] = candidate["surface_fingerprints"]
    normalized["captured_at"] = candidate["captured_at"]
    process = normalized.get("process")
    if not isinstance(process, Mapping) or set(process) != {
        "returncode",
        "timed_out",
    }:
        raise InvalidTransition("demonstration process has the wrong fields")
    if (
        isinstance(process["returncode"], bool)
        or not isinstance(process["returncode"], int)
        or process["returncode"] != 0
        or process["timed_out"] is not False
    ):
        raise InvalidTransition("retained demonstration process did not succeed")
    outputs = normalized.get("outputs")
    if not isinstance(outputs, list) or len(outputs) < 2:
        raise InvalidTransition("demonstration must retain stdout and stderr")
    normalized_outputs = [_normalize_demonstration_output(item) for item in outputs]
    paths = [item["path"] for item in normalized_outputs]
    if len(set(paths)) != len(paths):
        raise InvalidTransition("demonstration output paths must be unique")
    normalized["process"] = dict(process)
    normalized["outputs"] = normalized_outputs
    return normalized


def _normalize_demonstration_output(value: Any) -> dict[str, Any]:
    required = {"kind", "source", "path", "sha256", "size"}
    if not isinstance(value, Mapping) or set(value) != required:
        raise InvalidTransition("demonstration output has the wrong fields")
    normalized = deepcopy(dict(value))
    if normalized.get("kind") not in {"stdout", "stderr", "artifact"}:
        raise InvalidTransition("demonstration output kind is invalid")
    if not isinstance(normalized.get("source"), str):
        raise InvalidTransition("demonstration output source must be text")
    try:
        _validate_relative_path(normalized.get("path"), "output path")
    except ValueError as error:
        raise InvalidTransition(str(error)) from error
    if not isinstance(normalized.get("sha256"), str) or not re.fullmatch(
        r"[0-9a-f]{64}", normalized["sha256"]
    ):
        raise InvalidTransition("demonstration output digest is invalid")
    size = normalized.get("size")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise InvalidTransition("demonstration output size is invalid")
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
    allowed = {
        "schema_version",
        "task_id",
        "holder",
        "lease_id",
        "claim",
        "candidate_head",
        "artifacts",
        "review",
        "proposals",
    }
    if set(normalized) - allowed:
        raise ValueError("claim has unexpected fields")
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
    review = normalized.get("review")
    if review is not None:
        normalized["review"] = _normalize_review_result(review)
    normalized["proposals"] = normalize_claim_proposals(
        normalized.get("proposals", [])
    )
    _canonical_json(normalized)
    return normalized


def _normalize_review_result(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"findings"}:
        raise ValueError("review result must contain only findings")
    findings = value["findings"]
    if not isinstance(findings, list):
        raise ValueError("review findings must be a list")
    normalized = [_normalize_review_finding(item) for item in findings]
    ids = [item["id"] for item in normalized]
    if len(set(ids)) != len(ids):
        raise ValueError("review finding ids must be unique")
    return {"findings": normalized}


def _normalize_review_finding(value: Any) -> dict[str, str]:
    required = {"id", "severity", "summary", "evidence"}
    if not isinstance(value, Mapping) or set(value) != required:
        raise ValueError("review finding has the wrong fields")
    normalized = deepcopy(dict(value))
    validate_task_id(normalized.get("id"))
    if normalized.get("severity") not in REVIEW_SEVERITIES:
        raise ValueError("review finding severity is outside the closed enum")
    for field in ("summary", "evidence"):
        _required_text(normalized, field)
    return normalized


def _normalize_review_task(value: Any) -> dict[str, Any]:
    required = {"origin_task_id", "round", "remediation", "findings"}
    if not isinstance(value, Mapping) or set(value) != required:
        raise ValueError("review routing state has the wrong fields")
    normalized = deepcopy(dict(value))
    validate_task_id(normalized.get("origin_task_id"))
    if normalized.get("round") not in {0, 1}:
        raise ValueError("review round must be zero or one")
    remediation = normalized.get("remediation")
    if isinstance(remediation, Mapping):
        remediation = dict(remediation)
        remediation.setdefault("test_changes", False)
    if not isinstance(remediation, Mapping) or set(remediation) != {
        "role",
        "effort",
        "check",
        "test_changes",
    }:
        raise ValueError("review remediation template has the wrong fields")
    for field in ("role", "effort", "check"):
        _required_text(remediation, field)
    if remediation["role"] != "implementer":
        raise ValueError("review remediation role must be implementer")
    if not isinstance(remediation["test_changes"], bool):
        raise ValueError("review remediation test_changes must be a boolean")
    normalized["remediation"] = dict(remediation)
    findings = normalized.get("findings")
    if findings is not None:
        normalized["findings"] = _normalize_review_result(
            {"findings": findings}
        )["findings"]
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
        or task["parked"]
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


def _demonstration_by_id(
    state: Mapping[str, Any], demonstration_id: str
) -> dict[str, Any]:
    demonstration_id = validate_task_id(demonstration_id)
    for demonstration in state["demonstrations"]:
        if demonstration["id"] == demonstration_id:
            return demonstration
    raise InvalidTransition(f"unknown demonstration: {demonstration_id}")


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


def _safe_product_pattern(value: Any) -> bool:
    if not isinstance(value, str) or not value or len(value) > 512:
        return False
    if "\0" in value or "\\" in value or value.startswith("/"):
        return False
    return all(part not in {"", ".", ".."} for part in value.split("/"))


def _matches_product_pattern(path: str, pattern: str) -> bool:
    if fnmatch.fnmatchcase(path, pattern):
        return True
    return pattern.startswith("**/") and fnmatch.fnmatchcase(path, pattern[3:])


def _validate_relative_path(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be non-empty text")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{field} must stay inside the store")
    return value


def _contained_store_path(root: Path, relative_name: str) -> Path:
    try:
        _validate_relative_path(relative_name, "artifact path")
    except ValueError as error:
        raise InvalidTransition(str(error)) from error
    resolved_root = root.resolve()
    path = (resolved_root / relative_name).resolve()
    if os.path.commonpath([resolved_root, path]) != str(resolved_root):
        raise InvalidTransition("artifact path escapes the store")
    return path


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
    review_severity_bar = transition.get("review_severity_bar", "medium")
    proposal_templates = transition.get("proposal_templates", {})
    tasks = transition.get("tasks")
    candidate = deepcopy(state)
    candidate["plan_digest"] = digest
    candidate["test_paths"] = deepcopy(test_paths)
    candidate["review_severity_bar"] = review_severity_bar
    candidate["proposal_templates"] = deepcopy(proposal_templates)
    candidate["demonstrations"] = deepcopy(
        transition.get("demonstrations", [])
    )
    candidate["tasks"] = deepcopy(tasks)
    normalized = _normalize_state(candidate)
    state.clear()
    state.update(normalized)


def _apply_demonstration_invalidated(
    state: dict[str, Any], transition: Mapping[str, Any]
) -> None:
    demonstration_id = _required_text(transition, "demonstration_id")
    _required_text(transition, "reason")
    demonstration = _demonstration_by_id(state, demonstration_id)
    if demonstration["candidate"] is None:
        raise InvalidTransition(
            f"demonstration has no candidate to invalidate: {demonstration_id}"
        )
    demonstration["candidate"] = None
    state["phase"] = "working"
    state["presented_head"] = None
    state["bless_subject"] = None


def _apply_demonstrations_refresh_started(
    state: dict[str, Any], transition: Mapping[str, Any]
) -> None:
    _required_text(transition, "target_head")
    state["phase"] = "working"
    state["presented_head"] = None
    state["bless_subject"] = None


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


def _apply_task_judged(
    state: dict[str, Any], transition: Mapping[str, Any]
) -> None:
    task_id = _required_text(transition, "task_id")
    source = _required_text(transition, "source")
    if source not in {"judge", "framework-rule", "fallback"}:
        raise InvalidTransition("task judgment source is invalid")
    observed_at = transition.get("observed_at")
    if isinstance(observed_at, bool) or not isinstance(observed_at, (int, float)):
        raise InvalidTransition("task judgment observed_at must be a number")
    try:
        decision = normalize_decision(
            transition.get("decision"), task_id=task_id
        )
    except ValueError as error:
        raise InvalidTransition(str(error)) from error
    if source == "framework-rule" and (
        decision["trigger"] != "ambiguity"
        or decision["decision"] != "defer-to-operator"
    ):
        raise InvalidTransition(
            "framework-rule judgments are reserved for ambiguity escalation"
        )
    if source == "fallback" and decision["decision"] != "defer-to-operator":
        raise InvalidTransition("fallback judgments must defer to the operator")
    task = _task_by_id(state, task_id)
    if (
        task["completion"] != "pending"
        or task["verdict"] is not None
        or task["lease"] is not None
        or task["parked"]
    ):
        raise InvalidTransition("judged task is not unleased pending work")

    escalation_value = transition.get("escalation")
    if decision["decision"] == "defer-to-operator":
        if escalation_value is None:
            raise InvalidTransition(
                "defer-to-operator requires an escalation record"
            )
        try:
            escalation = _normalize_escalation(escalation_value)
        except ValueError as error:
            raise InvalidTransition(str(error)) from error
        if (
            escalation["task_id"] != task_id
            or escalation["trigger"] != decision["trigger"]
            or escalation["created_at"] != float(observed_at)
        ):
            raise InvalidTransition(
                "escalation does not match the judged task and trigger"
            )
        if escalation["status"] != "open":
            raise InvalidTransition("new escalation status must be open")
        if any(item["id"] == escalation["id"] for item in state["outbox"]):
            raise InvalidTransition("escalation id already exists")
        state["outbox"].append(escalation)
    elif escalation_value is not None:
        raise InvalidTransition(
            "only defer-to-operator may create an escalation record"
        )

    task["parked"] = True
    task["judgments"].append(
        {
            **decision,
            "source": source,
            "observed_at": float(observed_at),
        }
    )
    if decision["decision"] in {"split", "rebrief", "rebind"}:
        proposal_id = _derived_task_id(
            "planning",
            task_id,
            decision["trigger"],
            decision["decision"],
            str(float(observed_at)),
        )
        if any(item["id"] == proposal_id for item in state["proposals"]):
            raise InvalidTransition("judgment planning proposal already exists")
        state["proposals"].append(
            normalize_proposal(
                {
                    "schema_version": SCHEMA_VERSION,
                    "id": proposal_id,
                    "source_task_id": task_id,
                    "title": (
                        f"{decision['decision'].capitalize()} {task['title']}"
                    ),
                    "rationale": decision["reason"],
                    "suggested_dependencies": list(task["depends_on"]),
                    "origin": "judgment",
                    "created_at": float(observed_at),
                    "routing": None,
                }
            )
        )


def _retain_claim_proposals(
    state: dict[str, Any],
    task: Mapping[str, Any],
    proposals: Any,
    *,
    observed_at: float,
) -> None:
    normalized = normalize_claim_proposals(proposals)
    existing_ids = {item["id"] for item in state["proposals"]}
    for proposal in normalized:
        if proposal["id"] in existing_ids:
            raise InvalidTransition("claim proposal id already exists")
        existing_ids.add(proposal["id"])
        state["proposals"].append(
            normalize_proposal(
                {
                    "schema_version": SCHEMA_VERSION,
                    **proposal,
                    "source_task_id": task["id"],
                    "origin": "worker",
                    "created_at": observed_at,
                    "routing": None,
                }
            )
        )


def _apply_proposal_batch_folded(
    state: dict[str, Any], transition: Mapping[str, Any]
) -> None:
    pending = pending_proposals(state)
    if not pending:
        raise InvalidTransition("proposal batch has no pending inputs")
    batch_id = _required_text(transition, "batch_id")
    if batch_id != proposal_batch_id(pending):
        raise InvalidTransition("proposal folding batch id does not match inputs")
    try:
        folding = normalize_folding(
            transition.get("folding"),
            batch_id=batch_id,
            proposal_ids=[item["id"] for item in pending],
        )
    except ValueError as error:
        raise InvalidTransition(str(error)) from error
    observed_at = transition.get("observed_at")
    if isinstance(observed_at, bool) or not isinstance(observed_at, (int, float)):
        raise InvalidTransition("proposal folding observed_at must be a number")
    proposal_by_id = {item["id"]: item for item in state["proposals"]}
    task_ids = {item["id"] for item in state["tasks"]}
    for route in folding["routes"]:
        proposal = proposal_by_id[route["proposal_id"]]
        disposition = route["disposition"]
        routed_task_id: str | None = None
        if disposition == "in-envelope":
            planned = route["task"]
            routed_task_id = planned["id"]
            if routed_task_id in task_ids:
                raise InvalidTransition("planned proposal task id already exists")
            task_ids.add(routed_task_id)
            state["tasks"].append(_task_from_proposal(state, planned, proposal))
            if proposal["origin"] == "judgment":
                source = _task_by_id(state, proposal["source_task_id"])
                if source["id"] in planned["depends_on"]:
                    raise InvalidTransition(
                        "judgment replacement cannot depend on its parked source"
                    )
                successors = [
                    item
                    for item in state["tasks"]
                    if item["id"] != routed_task_id
                    and source["id"] in item["depends_on"]
                ]
                source["lineage"]["superseded_by"] = routed_task_id
                for successor in successors:
                    successor["depends_on"] = [
                        routed_task_id if dependency == source["id"] else dependency
                        for dependency in successor["depends_on"]
                    ]
        elif disposition == "beyond-flight":
            state["followups"].append(
                _normalize_followup(
                    {
                        "proposal_id": proposal["id"],
                        "source_task_id": proposal["source_task_id"],
                        "title": proposal["title"],
                        "rationale": proposal["rationale"],
                        "routing_reason": route["reason"],
                        "status": "local",
                    }
                )
            )
        else:
            _append_proposal_escalation(
                state,
                proposal,
                trigger="proposal-envelope",
                reason=route["reason"],
                observed_at=float(observed_at),
                escalation_id=(
                    "esc-proposal-"
                    + hashlib.sha256(proposal["id"].encode("utf-8")).hexdigest()[:16]
                ),
            )
        proposal["routing"] = normalize_routing_record(
            {
                "batch_id": batch_id,
                "disposition": disposition,
                "reason": route["reason"],
                "task_id": routed_task_id,
            }
        )


def _apply_proposal_batch_failed(
    state: dict[str, Any], transition: Mapping[str, Any]
) -> None:
    pending = pending_proposals(state)
    if not pending:
        raise InvalidTransition("failed proposal batch has no pending inputs")
    batch_id = _required_text(transition, "batch_id")
    if batch_id != proposal_batch_id(pending):
        raise InvalidTransition("failed proposal batch id does not match inputs")
    reason = _required_text(transition, "reason")
    proposal_ids = transition.get("proposal_ids")
    if proposal_ids != [item["id"] for item in pending]:
        raise InvalidTransition("failed proposal batch does not match pending inputs")
    observed_at = transition.get("observed_at")
    if isinstance(observed_at, bool) or not isinstance(observed_at, (int, float)):
        raise InvalidTransition("failed proposal batch observed_at must be a number")
    escalation_id = _required_text(transition, "escalation_id")
    first = next(
        item for item in state["proposals"] if item["id"] == proposal_ids[0]
    )
    _append_proposal_escalation(
        state,
        first,
        trigger="proposal-folding",
        reason=reason,
        observed_at=float(observed_at),
        escalation_id=escalation_id,
    )
    for proposal in state["proposals"]:
        if proposal["id"] not in proposal_ids:
            continue
        proposal["routing"] = normalize_routing_record(
            {
                "batch_id": batch_id,
                "disposition": "planning-failed",
                "reason": reason,
                "task_id": None,
            }
        )


def _append_proposal_escalation(
    state: dict[str, Any],
    proposal: Mapping[str, Any],
    *,
    trigger: str,
    reason: str,
    observed_at: float,
    escalation_id: str,
) -> None:
    task = _task_by_id(state, proposal["source_task_id"])
    decision = {
        "schema_version": SCHEMA_VERSION,
        "task_id": task["id"],
        "trigger": trigger,
        "decision": "defer-to-operator",
        "reason": reason,
        "source": "framework-rule",
        "observed_at": observed_at,
    }
    task["judgments"].append(decision)
    task["parked"] = True
    escalation = {
        "id": escalation_id,
        "task_id": task["id"],
        "trigger": trigger,
        "blocked_on": (
            f"The proposed work '{proposal['title']}' cannot be routed safely: "
            f"{reason}"
        ),
        "proposed_action": (
            "Confirm whether this work belongs in the current goal and revise the "
            "plan if it does."
        ),
        "effect": (
            "This proposal stays out of the task graph; independent work can continue."
        ),
        "request": "veto-or-confirm",
        "status": "open",
        "created_at": observed_at,
    }
    try:
        normalized_escalation = _normalize_escalation(escalation)
    except ValueError as error:
        raise InvalidTransition(str(error)) from error
    if any(item["id"] == escalation_id for item in state["outbox"]):
        raise InvalidTransition("proposal escalation id already exists")
    state["outbox"].append(normalized_escalation)


def _task_from_proposal(
    state: Mapping[str, Any],
    planned: Mapping[str, Any],
    proposal: Mapping[str, Any],
) -> dict[str, Any]:
    template_id = planned["template"]
    if template_id == "source-task":
        if proposal["origin"] != "judgment":
            raise InvalidTransition(
                "source-task template is reserved for judgment replacements"
            )
        source = _task_by_id(state, proposal["source_task_id"])
        template = {
            "role": source["role"],
            "effort": source["effort"],
            "check": source["check"],
            "test_changes": source["test_changes"],
        }
    else:
        try:
            template = state["proposal_templates"][template_id]
        except KeyError as error:
            raise InvalidTransition(
                f"unknown plan-owned proposal template: {template_id}"
            ) from error
    check = template["check"].replace("{task_id}", planned["id"])
    return _normalize_task(
        {
            "schema_version": SCHEMA_VERSION,
            "id": planned["id"],
            "title": planned["title"],
            "role": template["role"],
            "effort": template["effort"],
            "check": check,
            "depends_on": deepcopy(planned["depends_on"]),
            "decisions": [
                *planned["decisions"],
                f"Plan-owned proposal template: {template_id}",
                f"Routed from proposal {proposal['id']}: {proposal['rationale']}",
            ],
            "test_changes": template["test_changes"],
            "attempts": {"work": 0, "infra": 0, "diagnostic": 0},
            "completion": "pending",
            "verdict": None,
            "parked": False,
            "judgments": [],
            "review": None,
            "evidence": [],
            "verified_head": None,
            "lineage": {
                "retired": False,
                "revoked": False,
                "superseded_by": None,
            },
            "lease": None,
        }
    )


def _apply_review_routing(
    state: dict[str, Any],
    task: dict[str, Any],
    review_result: Mapping[str, Any],
    *,
    observed_at: float,
) -> None:
    review = task["review"]
    if review is None:
        raise InvalidTransition("completed reviewer task lacks routing state")
    if review["findings"] is not None:
        raise InvalidTransition("review findings were already routed")
    findings = _normalize_review_result(review_result)["findings"]
    review["findings"] = findings
    severity_bar = state.get("review_severity_bar")
    if severity_bar not in REVIEW_SEVERITIES:
        raise InvalidTransition("flight lacks a valid review severity bar")
    bar_index = REVIEW_SEVERITIES.index(severity_bar)
    actionable = [
        finding
        for finding in findings
        if REVIEW_SEVERITIES.index(finding["severity"]) >= bar_index
    ]
    if not actionable:
        return

    if review["round"] == 1:
        reason = (
            f"The bounded re-review still found {len(actionable)} finding(s) "
            f"at or above the {severity_bar} severity bar."
        )
        decision = {
            "schema_version": SCHEMA_VERSION,
            "task_id": task["id"],
            "trigger": "review-findings",
            "decision": "defer-to-operator",
            "reason": reason,
            "source": "framework-rule",
            "observed_at": observed_at,
        }
        task["judgments"].append(decision)
        task["parked"] = True
        escalation_id = "esc-review-" + hashlib.sha256(
            (task["id"] + "\0" + ",".join(item["id"] for item in actionable)).encode(
                "utf-8"
            )
        ).hexdigest()[:16]
        if any(item["id"] == escalation_id for item in state["outbox"]):
            raise InvalidTransition("review escalation id already exists")
        state["outbox"].append(
            {
                "id": escalation_id,
                "task_id": task["id"],
                "trigger": "review-findings",
                "blocked_on": reason,
                "proposed_action": (
                    "Revise the plan or explicitly accept the remaining findings "
                    "before continuing."
                ),
                "effect": (
                    "The reviewed work stays verified, but the flight cannot finish "
                    "while this question is open."
                ),
                "request": "veto-or-confirm",
                "status": "open",
                "created_at": observed_at,
            }
        )
        return

    existing_ids = {item["id"] for item in state["tasks"]}
    planned_successors = [
        item for item in state["tasks"] if task["id"] in item["depends_on"]
    ]
    rereview_id = _derived_task_id(
        "rereview",
        review["origin_task_id"],
        ",".join(item["id"] for item in actionable),
    )
    if rereview_id in existing_ids:
        raise InvalidTransition("derived re-review task id already exists")
    existing_ids.add(rereview_id)
    remediation_ids: list[str] = []
    template = review["remediation"]
    for position, finding in enumerate(actionable, start=1):
        remediation_id = _derived_task_id(
            "remediate",
            review["origin_task_id"],
            finding["id"],
        )
        if remediation_id in existing_ids:
            raise InvalidTransition("derived remediation task id already exists")
        existing_ids.add(remediation_id)
        remediation_ids.append(remediation_id)
        state["tasks"].append(
            _normalize_task(
                {
                    "schema_version": SCHEMA_VERSION,
                    "id": remediation_id,
                    "title": f"Remediate review finding {finding['id']}",
                    "role": template["role"],
                    "effort": template["effort"],
                    "check": template["check"],
                    "depends_on": [task["id"]],
                    "decisions": [
                        f"Source review: {task['id']}",
                        f"Finding severity: {finding['severity']}",
                        f"Finding summary: {finding['summary']}",
                        f"Finding evidence: {finding['evidence']}",
                        f"Finding position: {position} of {len(actionable)}",
                    ],
                    "test_changes": template["test_changes"],
                    "attempts": {"work": 0, "infra": 0, "diagnostic": 0},
                    "completion": "pending",
                    "verdict": None,
                    "parked": False,
                    "judgments": [],
                    "review": None,
                    "evidence": [],
                    "verified_head": None,
                    "lineage": {
                        "retired": False,
                        "revoked": False,
                        "superseded_by": None,
                    },
                    "lease": None,
                }
            )
        )

    state["tasks"].append(
        _normalize_task(
            {
                "schema_version": SCHEMA_VERSION,
                "id": rereview_id,
                "title": f"Re-review remediation from {task['title']}",
                "role": "reviewer",
                "effort": task["effort"],
                "check": task["check"],
                "depends_on": remediation_ids,
                "decisions": [
                    f"This is the only re-review round for {task['id']}.",
                    "Review the remediations for the recorded at-or-above-bar findings.",
                ],
                "test_changes": False,
                "attempts": {"work": 0, "infra": 0, "diagnostic": 0},
                "completion": "pending",
                "verdict": None,
                "parked": False,
                "judgments": [],
                "review": {
                    "origin_task_id": review["origin_task_id"],
                    "round": 1,
                    "remediation": deepcopy(template),
                    "findings": None,
                },
                "evidence": [],
                "verified_head": None,
                "lineage": {
                    "retired": False,
                    "revoked": False,
                    "superseded_by": None,
                },
                "lease": None,
            }
        )
    )
    for successor in planned_successors:
        successor["depends_on"] = [
            rereview_id if dependency == task["id"] else dependency
            for dependency in successor["depends_on"]
        ]


def _derived_task_id(kind: str, *parts: str) -> str:
    digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{kind}-{digest}"


def _normalize_recorded_judgment(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("recorded judgment must be an object")
    decision_fields = {
        "schema_version",
        "task_id",
        "trigger",
        "decision",
        "reason",
    }
    if set(value) != decision_fields | {"source", "observed_at"}:
        raise ValueError("recorded judgment has the wrong fields")
    decision = normalize_decision(
        {field: value[field] for field in decision_fields}
    )
    source = value["source"]
    if source not in {"judge", "framework-rule", "fallback"}:
        raise ValueError("recorded judgment source is invalid")
    if source == "framework-rule" and (
        decision["trigger"]
        not in {
            "ambiguity",
            "review-findings",
            "proposal-envelope",
            "proposal-folding",
        }
        or decision["decision"] != "defer-to-operator"
    ):
        raise ValueError(
            "framework-rule judgments are reserved for mandatory escalations"
        )
    if source == "fallback" and decision["decision"] != "defer-to-operator":
        raise ValueError("fallback judgments must defer to the operator")
    observed_at = value["observed_at"]
    if (
        isinstance(observed_at, bool)
        or not isinstance(observed_at, (int, float))
        or not math.isfinite(observed_at)
        or observed_at < 0
    ):
        raise ValueError("recorded judgment observed_at must be a number")
    return {**decision, "source": source, "observed_at": float(observed_at)}


def _normalize_followup(value: Any) -> dict[str, str]:
    required = {
        "proposal_id",
        "source_task_id",
        "title",
        "rationale",
        "routing_reason",
        "status",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise ValueError("followup record has the wrong fields")
    normalized = deepcopy(dict(value))
    for field in required:
        _required_text(normalized, field)
    validate_task_id(normalized["proposal_id"])
    validate_task_id(normalized["source_task_id"])
    if normalized["status"] != "local":
        raise ValueError("followup status must be local")
    return normalized


def _normalize_escalation(value: Any) -> dict[str, Any]:
    required = {
        "id",
        "task_id",
        "trigger",
        "blocked_on",
        "proposed_action",
        "effect",
        "request",
        "status",
        "created_at",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise ValueError("escalation record has the wrong fields")
    normalized = deepcopy(dict(value))
    for field in (
        "id",
        "task_id",
        "trigger",
        "blocked_on",
        "proposed_action",
        "effect",
        "request",
        "status",
    ):
        _required_text(normalized, field)
    validate_task_id(normalized["task_id"])
    if not re.fullmatch(r"esc-[a-z0-9][a-z0-9-]{0,119}", normalized["id"]):
        raise ValueError("escalation id must be an esc- prefixed path-safe id")
    if normalized["trigger"] not in {
        "retry-cap",
        "ambiguity",
        "stall",
        "identical-error",
        "wall-clock-cap",
        "review-findings",
        "proposal-envelope",
        "proposal-folding",
    }:
        raise ValueError("escalation trigger is outside the closed trigger enum")
    if normalized["request"] != "veto-or-confirm":
        raise ValueError("escalation request must be veto-or-confirm")
    if normalized["status"] not in {"open", "resolved"}:
        raise ValueError("escalation status must be open or resolved")
    created_at = normalized["created_at"]
    if (
        isinstance(created_at, bool)
        or not isinstance(created_at, (int, float))
        or not math.isfinite(created_at)
        or created_at < 0
    ):
        raise ValueError("escalation created_at must be a number")
    normalized["created_at"] = float(created_at)
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
