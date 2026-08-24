"""Scripted fake worker used by the framework's deterministic test flights."""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any

from .base import DispatchResult
from ..store import SCHEMA_VERSION, Store, StoreError, validate_task_id


class FakeAdapter:
    """Execute ordered JSON-scripted product edits and file typed claims."""

    def __init__(self, script_path: str | Path, store: Store):
        self.script_path = Path(script_path)
        self.store = store
        self._steps = self._load_steps()
        self._position = 0

    def dispatch(
        self,
        prompt: str,
        binding: Mapping[str, Any],
        sandbox: str,
        timeout: float,
    ) -> DispatchResult:
        """Run one scripted step without invoking a model or network service."""

        task_id = validate_task_id(_required_text(binding, "task_id"))
        role = _required_text(binding, "role")
        holder = _required_text(binding, "holder")
        lease_id = _required_text(binding, "lease_id")
        claim_reservation_seconds = _required_positive_number(
            binding, "claim_reservation_seconds"
        )
        product_root = Path(_required_text(binding, "product_root")).resolve()
        result_root = self.store.root / "adapter-results" / task_id
        transcript_path = result_root / "transcript.json"
        last_message_path = result_root / "last-message.txt"
        result_root.mkdir(parents=True, exist_ok=True)

        transcript: dict[str, Any] = {
            "adapter": "fake",
            "task_id": task_id,
            "sandbox": sandbox,
            "prompt_bytes": len(prompt.encode("utf-8")),
        }
        failure_reason: str | None = None
        try:
            if self._position >= len(self._steps):
                raise ValueError("fake script has no remaining step")
            step = self._steps[self._position]
            self._position += 1
            if step["task_id"] != task_id:
                raise ValueError(
                    f"fake step expected {step['task_id']}, received {task_id}"
                )
            if step["outcome"] == "ambiguity":
                failure_reason = step["reason"]
                transcript.update(
                    {"exit_class": "ambiguity", "reason": failure_reason}
                )
                message = f"reported ambiguity for {task_id}: {failure_reason}\n"
                exit_class = "ambiguity"
            else:
                if role == "reviewer":
                    if step["review"] is None:
                        raise ValueError("reviewer fake step requires a review result")
                    if step["writes"]:
                        raise ValueError("reviewer fake step cannot mutate the product")
                    candidate_head = _required_text(binding, "base_head")
                else:
                    if step["review"] is not None:
                        raise ValueError("only reviewer fake steps may contain findings")
                    for relative_name, content in step["writes"].items():
                        destination = _safe_product_path(product_root, relative_name)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_text(content, encoding="utf-8")
                    _git(
                        product_root,
                        ["add", "--all"],
                        timeout=timeout,
                    )
                    _git(
                        product_root,
                        ["commit", "--no-gpg-sign", "-m", step["commit_message"]],
                        timeout=timeout,
                    )
                    candidate_head = _git(
                        product_root,
                        ["rev-parse", "HEAD"],
                        timeout=timeout,
                    ).strip()
                if step["pause_seconds"]:
                    time.sleep(step["pause_seconds"])
                evidence_source = result_root / "claim-source.json"
                claim = {
                    "schema_version": SCHEMA_VERSION,
                    "task_id": task_id,
                    "holder": holder,
                    "lease_id": lease_id,
                    "claim": "passes",
                    "candidate_head": candidate_head,
                    "artifacts": step["artifacts"],
                }
                if step["review"] is not None:
                    claim["review"] = step["review"]
                if step["proposals"]:
                    claim["proposals"] = step["proposals"]
                evidence_source.write_text(
                    json.dumps(
                        claim,
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                self.store.file_claim(
                    task_id,
                    evidence_source,
                    reservation_seconds=claim_reservation_seconds,
                )
                transcript.update(
                    {
                        "exit_class": "success",
                        "candidate_head": candidate_head,
                        "artifacts": step["artifacts"],
                    }
                )
                message = f"filed passing claim for {task_id} at {candidate_head}\n"
                exit_class = "success"
        except (OSError, subprocess.SubprocessError, StoreError, ValueError) as error:
            transcript.update({"exit_class": "worker-error", "error": str(error)})
            message = f"fake worker failed for {task_id}: {error}\n"
            exit_class = "worker-error"

        transcript_path.write_text(
            json.dumps(transcript, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        last_message_path.write_text(message, encoding="utf-8")
        return DispatchResult(
            exit_class,
            transcript_path,
            last_message_path,
            failure_reason=failure_reason,
        )

    def _load_steps(self) -> list[dict[str, Any]]:
        try:
            value = json.loads(self.script_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"invalid fake adapter script: {error}") from error
        if not isinstance(value, dict) or not isinstance(value.get("steps"), list):
            raise ValueError("fake adapter script must contain a steps list")
        return [_normalize_step(step) for step in value["steps"]]


def _normalize_step(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("each fake adapter step must be an object")
    task_id = _required_text(value, "task_id")
    outcome = value.get("outcome", "passes")
    if outcome not in {"passes", "ambiguity"}:
        raise ValueError("fake step outcome must be passes or ambiguity")
    commit_message = value.get("commit_message", "")
    writes = value.get("writes", {})
    if not isinstance(writes, dict):
        raise ValueError("fake step writes must be an object")
    review = value.get("review")
    if review is not None and not isinstance(review, dict):
        raise ValueError("fake review result must be an object")
    proposals = value.get("proposals", [])
    if not isinstance(proposals, list) or any(
        not isinstance(item, dict) for item in proposals
    ):
        raise ValueError("fake proposals must be a list of objects")
    if outcome == "passes" and review is None and (
        not isinstance(commit_message, str) or not commit_message or not writes
    ):
        raise ValueError(
            f"passing fake step {task_id} requires a commit message and writes"
        )
    if outcome == "ambiguity" and (commit_message or writes):
        raise ValueError("ambiguous fake steps cannot mutate the product")
    if any(
        not isinstance(path, str)
        or not path
        or not isinstance(content, str)
        for path, content in writes.items()
    ):
        raise ValueError("fake writes must map non-empty paths to strings")
    artifacts = value.get("artifacts", list(writes))
    if not isinstance(artifacts, list) or any(
        not isinstance(item, str) or not item for item in artifacts
    ):
        raise ValueError("fake artifacts must be a list of non-empty strings")
    pause_seconds = value.get("pause_seconds", 0)
    if (
        isinstance(pause_seconds, bool)
        or not isinstance(pause_seconds, (int, float))
        or pause_seconds < 0
    ):
        raise ValueError("fake pause_seconds must be a non-negative number")
    reason = value.get("reason", "")
    if outcome == "ambiguity" and (
        not isinstance(reason, str) or not reason.strip()
    ):
        raise ValueError("ambiguous fake steps require a non-empty reason")
    return {
        "task_id": task_id,
        "outcome": outcome,
        "commit_message": commit_message,
        "writes": dict(writes),
        "artifacts": list(artifacts),
        "pause_seconds": float(pause_seconds),
        "reason": reason,
        "review": review,
        "proposals": list(proposals),
    }


def _safe_product_path(root: Path, relative_name: str) -> Path:
    relative = Path(relative_name)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"fake write escapes product root: {relative_name}")
    if any(part.casefold() == ".scaffolding" for part in relative.parts):
        raise ValueError("fake worker cannot write framework control state")
    candidate = (root / relative).resolve()
    if os.path.commonpath([root, candidate]) != str(root):
        raise ValueError(f"fake write escapes product root: {relative_name}")
    control_root = (root / ".scaffolding").resolve()
    if os.path.commonpath([control_root, candidate]) == str(control_root):
        raise ValueError("fake worker cannot write framework control state")
    return candidate


def _git(root: Path, arguments: list[str], *, timeout: float) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ValueError(f"git {' '.join(arguments)} failed: {detail}")
    return completed.stdout


def _required_text(value: Mapping[str, Any], field: str) -> str:
    candidate = value.get(field)
    if not isinstance(candidate, str) or not candidate:
        raise ValueError(f"{field} must be a non-empty string")
    return candidate


def _required_positive_number(value: Mapping[str, Any], field: str) -> float:
    candidate = value.get(field)
    if (
        isinstance(candidate, bool)
        or not isinstance(candidate, (int, float))
        or candidate <= 0
    ):
        raise ValueError(f"{field} must be positive")
    return float(candidate)
