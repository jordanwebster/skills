"""Roster-backed, read-only dispatch for proposal-folding planners."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any

from .claude import ClaudeAdapter
from .codex import CodexAdapter
from .judge import _extract_decision, _judge_command, _retain_judge_result
from .process import (
    _read_output,
    _redact,
    _redact_value,
    _run_process,
    _worker_environment,
)
from .roster import Roster
from ..proposal import normalize_folding
from ..store import Store


_PLANNED_TASK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string", "minLength": 1},
        "title": {"type": "string", "minLength": 1},
        "template": {"type": "string", "minLength": 1},
        "depends_on": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
        },
        "decisions": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
        },
    },
    "required": [
        "id",
        "title",
        "template",
        "depends_on",
        "decisions",
    ],
}

PLANNER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "schema_version": {"const": 1},
        "batch_id": {"type": "string", "minLength": 1},
        "routes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "proposal_id": {"type": "string", "minLength": 1},
                    "disposition": {
                        "enum": [
                            "in-envelope",
                            "beyond-flight",
                            "envelope-breaking",
                        ]
                    },
                    "reason": {"type": "string", "minLength": 1},
                    "task": {"anyOf": [_PLANNED_TASK_SCHEMA, {"type": "null"}]},
                },
                "required": ["proposal_id", "disposition", "reason", "task"],
            },
        },
    },
    "required": ["schema_version", "batch_id", "routes"],
}


class RosterPlanner:
    """Resolve the planner role once and fold proposals without product access."""

    def __init__(self, store: Store, roster: Roster):
        self.store = store
        self.binding = roster.resolve_default("planner")

    def fold(
        self,
        state: Mapping[str, Any],
        proposals: Sequence[Mapping[str, Any]],
        batch_id: str,
    ) -> Mapping[str, Any]:
        prompt = _planner_prompt(state, proposals, batch_id)
        result_root = self.store.root / "adapter-results" / "planner" / batch_id
        result_root.mkdir(parents=True, exist_ok=True)
        transcript_path = result_root / "transcript.json"
        last_message_path = result_root / "last-message.json"
        parent_environment = os.environ.copy()
        executable = Path(self.binding.cli).name.casefold()
        allowed_secrets = (
            CodexAdapter.auth_environment_names
            if executable == "codex"
            else ClaudeAdapter.auth_environment_names
        )
        environment = _worker_environment(parent_environment, allowed_secrets)
        transcript: dict[str, Any] = {
            "adapter": executable,
            "job": "planner",
            "batch_id": batch_id,
            "proposal_ids": [item["id"] for item in proposals],
            "binding": self.binding.label,
            "sandbox": "read-only",
            "prompt_bytes": len(prompt.encode("utf-8")),
        }
        raw_last = ""
        try:
            with tempfile.TemporaryDirectory(prefix="scaffold-planner-") as temporary:
                working_root = Path(temporary)
                schema_path = working_root / "planner-schema.json"
                raw_last_path = working_root / "last-message.json"
                stdout_path = working_root / "stdout"
                stderr_path = working_root / "stderr"
                schema_path.write_text(
                    json.dumps(PLANNER_SCHEMA, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                command = _judge_command(
                    self.binding,
                    executable,
                    working_root,
                    schema_path,
                    raw_last_path,
                    schema=PLANNER_SCHEMA,
                    job="planner",
                    allow_tools=False,
                )
                transcript["command"] = command
                return_code, timed_out = _run_process(
                    command,
                    prompt=prompt,
                    cwd=working_root,
                    environment=environment,
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    timeout=60,
                )
                stdout = _read_output(stdout_path)
                stderr = _read_output(stderr_path)
                transcript["return_code"] = return_code
                transcript["stdout"] = _redact(stdout, parent_environment)
                transcript["stderr"] = _redact(stderr, parent_environment)
                if timed_out:
                    raise ValueError("planner exceeded its dispatch timeout")
                if return_code != 0:
                    detail = stderr.strip() or stdout.strip()
                    raise ValueError(
                        f"planner exited {return_code}"
                        + (f": {detail[:500]}" if detail else "")
                    )
                value, raw_last = _extract_decision(
                    executable, stdout, raw_last_path, job="planner"
                )
                folding = normalize_folding(
                    value,
                    batch_id=batch_id,
                    proposal_ids=[item["id"] for item in proposals],
                )
                folding = _redact_value(folding, parent_environment)
                transcript["dispositions"] = [
                    item["disposition"] for item in folding["routes"]
                ]
        except (OSError, subprocess.SubprocessError, ValueError) as error:
            retained_error = _redact(str(error), parent_environment)
            transcript["error"] = retained_error
            transcript["exit_class"] = "malformed"
            _retain_judge_result(
                transcript_path,
                last_message_path,
                transcript,
                raw_last or json.dumps({"error": retained_error}),
                parent_environment,
            )
            raise ValueError(retained_error) from error

        transcript["exit_class"] = "success"
        _retain_judge_result(
            transcript_path,
            last_message_path,
            transcript,
            raw_last,
            parent_environment,
        )
        return folding


def _planner_prompt(
    state: Mapping[str, Any],
    proposals: Sequence[Mapping[str, Any]],
    batch_id: str,
) -> str:
    template = (
        Path(__file__).parents[1] / "prompts" / "planner.txt"
    ).read_text(encoding="utf-8")
    context = {
        "batch_id": batch_id,
        "goal": state["goal"],
        "proposal_templates": {
            name: {"role": value["role"], "effort": value["effort"]}
            for name, value in state["proposal_templates"].items()
        },
        "tasks": [
            {
                "id": task["id"],
                "title": task["title"],
                "role": task["role"],
                "depends_on": task["depends_on"],
                "completion": task["completion"],
                "verdict": task["verdict"],
                "parked": task["parked"],
            }
            for task in state["tasks"]
        ],
        "proposals": [dict(item) for item in proposals],
    }
    return template.rstrip() + "\n\nPLANNING CONTEXT\n" + json.dumps(
        context, ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n"
