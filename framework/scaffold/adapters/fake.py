"""Scripted fake worker used by the framework's deterministic test flights."""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
import subprocess
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
        holder = _required_text(binding, "holder")
        lease_id = _required_text(binding, "lease_id")
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
        try:
            if self._position >= len(self._steps):
                raise ValueError("fake script has no remaining step")
            step = self._steps[self._position]
            self._position += 1
            if step["task_id"] != task_id:
                raise ValueError(
                    f"fake step expected {step['task_id']}, received {task_id}"
                )
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
            evidence_source = result_root / "claim-source.json"
            evidence_source.write_text(
                json.dumps(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "task_id": task_id,
                        "holder": holder,
                        "lease_id": lease_id,
                        "claim": "passes",
                        "candidate_head": candidate_head,
                        "artifacts": step["artifacts"],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            self.store.file_claim(task_id, evidence_source)
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
        return DispatchResult(exit_class, transcript_path, last_message_path)

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
    commit_message = _required_text(value, "commit_message")
    writes = value.get("writes")
    if not isinstance(writes, dict) or not writes:
        raise ValueError(f"fake step {task_id} writes must be a non-empty object")
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
    return {
        "task_id": task_id,
        "commit_message": commit_message,
        "writes": dict(writes),
        "artifacts": list(artifacts),
    }


def _safe_product_path(root: Path, relative_name: str) -> Path:
    relative = Path(relative_name)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"fake write escapes product root: {relative_name}")
    candidate = (root / relative).resolve()
    if os.path.commonpath([root, candidate]) != str(root):
        raise ValueError(f"fake write escapes product root: {relative_name}")
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
