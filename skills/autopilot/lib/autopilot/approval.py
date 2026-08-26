"""Narrow, semantic approval receipts for an Autopilot plan."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .plan import plan_bindings
from .roster import Roster
from .state import Flight, StateError


SCHEMA_VERSION = 1


def digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def acceptance_digest(flight: Flight) -> str:
    if not flight.requirements_path.is_file() or not flight.acceptance_receipt_path.is_file():
        raise StateError(
            "confirmed acceptance is missing; provide a contract with a current compatible acceptance receipt"
        )
    return validate_acceptance_files(flight.requirements_path, flight.acceptance_receipt_path)


def validate_acceptance_files(contract: Path, receipt_path: Path) -> str:
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise StateError(f"acceptance receipt is unreadable: {error}") from error
    try:
        actual = digest_bytes(contract.read_bytes())
    except OSError as error:
        raise StateError(f"acceptance contract is unreadable: {error}") from error
    required = {"schema_version", "contract_digest", "confirmed_at"}
    if (
        not isinstance(receipt, dict)
        or set(receipt) != required
        or receipt.get("schema_version") != 1
        or not isinstance(receipt.get("contract_digest"), str)
        or not isinstance(receipt.get("confirmed_at"), str)
        or not receipt["confirmed_at"].strip()
    ):
        raise StateError(
            "acceptance receipt is invalid; record explicit confirmation again with a compatible finalizer"
        )
    if receipt["contract_digest"] != actual:
        raise StateError(
            "acceptance confirmation is stale; finalize the current contract again, then reinitialize the flight"
        )
    return actual


def plan_digest(flight: Flight) -> str:
    try:
        return digest_bytes(flight.plan_path.read_bytes())
    except OSError as error:
        raise StateError(f"cannot read the plan: {error}") from error


def resolved_staffing(plan: dict[str, Any], roster: Roster) -> tuple[list[dict[str, Any]], list[Any]]:
    semantic: list[dict[str, Any]] = []
    bindings = []
    for role, effort in plan_bindings(plan):
        binding = roster.resolve(role, effort)
        bindings.append(binding)
        semantic.append(binding.semantic())
    return semantic, bindings


def staffing_digest(plan: dict[str, Any], roster: Roster) -> tuple[str, list[Any]]:
    semantic, bindings = resolved_staffing(plan, roster)
    encoded = json.dumps(semantic, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return digest_bytes(encoded), bindings


def approve(flight: Flight, plan: dict[str, Any], roster: Roster) -> dict[str, Any]:
    staffing, _ = staffing_digest(plan, roster)
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "acceptance_digest": acceptance_digest(flight),
        "plan_digest": plan_digest(flight),
        "staffing_digest": staffing,
        "confirmed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    _write_json(flight.approval_path, receipt)
    return receipt


def validate(flight: Flight, plan: dict[str, Any], roster: Roster) -> dict[str, Any]:
    try:
        receipt = json.loads(flight.approval_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise StateError("the plan is not approved; review it, confirm it in conversation, then run `autopilot approve`") from error
    except (OSError, json.JSONDecodeError) as error:
        raise StateError(f"plan approval receipt is unreadable: {error}") from error
    expected = {
        "schema_version": SCHEMA_VERSION,
        "acceptance_digest": acceptance_digest(flight),
        "plan_digest": plan_digest(flight),
        "staffing_digest": staffing_digest(plan, roster)[0],
    }
    stale = [key for key, value in expected.items() if receipt.get(key) != value]
    if stale:
        names = ", ".join(item.replace("_", " ") for item in stale)
        raise StateError(f"plan approval is stale ({names}); review the changes and run `autopilot approve` again")
    return receipt


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
