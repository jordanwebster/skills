"""Consume Intake's public inspection contract without parsing its Markdown."""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
from typing import Any

from .state import StateError


class AcceptanceError(StateError):
    """Confirmed acceptance cannot be inspected or joined to final proof."""


def inspect(
    contract: Path,
    receipt: Path,
    *,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    selected_environment = dict(os.environ if environment is None else environment)
    invocation = command(selected_environment)
    invocation += ["inspect", str(contract), "--receipt", str(receipt), "--json"]
    try:
        completed = subprocess.run(
            invocation,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env=selected_environment,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise AcceptanceError(f"cannot inspect confirmed acceptance through Intake: {error}") from error
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        detail = completed.stderr.strip() or completed.stdout.strip() or "no output"
        raise AcceptanceError(f"Intake returned invalid inspection JSON: {detail[:300]}") from error
    if completed.returncode or not isinstance(payload, dict) or not payload.get("ok"):
        detail = payload.get("error") if isinstance(payload, dict) else None
        detail = detail if isinstance(detail, dict) else {}
        raise AcceptanceError(str(detail.get("message") or "Intake could not inspect confirmed acceptance"))
    _demonstrations(payload)
    if not isinstance(payload.get("contract_digest"), str):
        raise AcceptanceError("Intake inspection omitted contract_digest")
    return payload


def write(path: Path, inspection: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(inspection, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AcceptanceError(f"normalized acceptance is unreadable: {error}") from error
    if not isinstance(value, dict):
        raise AcceptanceError("normalized acceptance must be an object")
    _demonstrations(value)
    return value


def verify_proof(inspection_path: Path, workspace: Path) -> None:
    expected_payload = load(inspection_path)
    expected = {
        item["id"]: item["description"]
        for item in _demonstrations(expected_payload)
    }
    try:
        proof = json.loads((workspace / "proof.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AcceptanceError(f"cannot read final proof bundle: {error}") from error
    accepted = proof.get("accepted_demonstrations") if isinstance(proof, dict) else None
    if not isinstance(accepted, list):
        raise AcceptanceError("final proof omitted accepted_demonstrations")
    actual: dict[str, str] = {}
    for item in accepted:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not isinstance(item.get("description"), str):
            raise AcceptanceError("final proof has an invalid accepted demonstration")
        if item["id"] in actual:
            raise AcceptanceError(f"final proof repeats accepted demonstration {item['id']!r}")
        actual[item["id"]] = item["description"]
    if actual != expected:
        missing = [description for identifier, description in expected.items() if identifier not in actual]
        extra = [description for identifier, description in actual.items() if identifier not in expected]
        changed = [
            expected[identifier]
            for identifier in expected.keys() & actual.keys()
            if expected[identifier] != actual[identifier]
        ]
        details = []
        if missing:
            details.append("missing: " + "; ".join(missing))
        if extra:
            details.append("not accepted: " + "; ".join(extra))
        if changed:
            details.append("renamed: " + "; ".join(changed))
        raise AcceptanceError("final proof changed confirmed demonstrations (" + " | ".join(details) + ")")


def verify_plan(inspection: dict[str, Any], plan: dict[str, Any]) -> None:
    """Require the evidence plan to cover exactly the confirmed demonstrations."""

    expected = {item["id"]: item["description"] for item in _demonstrations(inspection)}
    actual = {
        str(identifier)
        for item in plan.get("evidence", [])
        for identifier in item.get("demonstrations", [])
    }
    missing = [expected[identifier] for identifier in expected if identifier not in actual]
    extra = sorted(actual - expected.keys())
    if missing or extra:
        details = []
        if missing:
            details.append("missing: " + "; ".join(missing))
        if extra:
            details.append("not accepted: " + "; ".join(extra))
        raise AcceptanceError("plan evidence does not match confirmed demonstrations (" + " | ".join(details) + ")")


def command(environment: Mapping[str, str] | None = None) -> list[str]:
    selected_environment = dict(os.environ if environment is None else environment)
    selected = selected_environment.get("INTAKE_COMMAND") or _bundled_intake()
    return shlex.split(selected)


def _bundled_intake() -> str:
    candidate = Path(__file__).resolve().parents[3] / "intake" / "scripts" / "intake"
    return str(candidate) if candidate.is_file() else "intake"


def _demonstrations(payload: dict[str, Any]) -> list[dict[str, str]]:
    acceptance = payload.get("acceptance")
    demonstrations = acceptance.get("demonstrations") if isinstance(acceptance, dict) else None
    if not isinstance(demonstrations, list) or not demonstrations:
        raise AcceptanceError("Intake inspection has no accepted demonstrations")
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in demonstrations:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not isinstance(item.get("description"), str):
            raise AcceptanceError("Intake inspection contains an invalid demonstration")
        if item["id"] in seen:
            raise AcceptanceError(f"Intake inspection repeats demonstration {item['id']!r}")
        seen.add(item["id"])
        normalized.append({"id": item["id"], "description": item["description"]})
    return normalized
