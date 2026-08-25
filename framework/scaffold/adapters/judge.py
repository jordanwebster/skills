"""Roster-backed, read-only dispatch for ephemeral failure judges."""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any

from .claude import ClaudeAdapter
from .codex import CodexAdapter
from .process import (
    _read_output,
    _redact,
    _redact_value,
    _run_process,
    _worker_environment,
)
from .roster import ResolvedBinding, Roster
from ..judge import CLOSED_DECISIONS, normalize_decision
from ..store import Store, validate_task_id


JUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "schema_version": {"const": 1},
        "task_id": {"type": "string", "minLength": 1},
        "trigger": {"type": "string", "minLength": 1},
        "decision": {"enum": sorted(CLOSED_DECISIONS)},
        "reason": {"type": "string", "minLength": 1},
    },
    "required": ["schema_version", "task_id", "trigger", "decision", "reason"],
}


class RosterJudge:
    """Resolve the judge role once and dispatch it without product write access."""

    def __init__(self, store: Store, roster: Roster):
        self.store = store
        self.binding = roster.resolve_default("judge")

    def decide(
        self,
        task: Mapping[str, Any],
        trigger: str,
        failure: str,
    ) -> Mapping[str, Any]:
        task_id = validate_task_id(task.get("id"))
        prompt = _judge_prompt(task, trigger, failure)
        result_root = self.store.root / "adapter-results" / "judge" / (
            f"{task_id}-{trigger}"
        )
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
            "job": "judge",
            "task_id": task_id,
            "trigger": trigger,
            "binding": self.binding.label,
            "sandbox": "read-only",
            "prompt_bytes": len(prompt.encode("utf-8")),
        }
        raw_last = ""
        try:
            with tempfile.TemporaryDirectory(prefix="scaffold-judge-") as temporary:
                working_root = Path(temporary)
                schema_path = working_root / "judge-schema.json"
                raw_last_path = working_root / "last-message.json"
                stdout_path = working_root / "stdout"
                stderr_path = working_root / "stderr"
                schema_path.write_text(
                    json.dumps(JUDGE_SCHEMA, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                command = _judge_command(
                    self.binding,
                    executable,
                    working_root,
                    schema_path,
                    raw_last_path,
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
                    raise ValueError("judge exceeded its dispatch timeout")
                if return_code != 0:
                    detail = stderr.strip() or stdout.strip()
                    raise ValueError(
                        f"judge exited {return_code}"
                        + (f": {detail[:500]}" if detail else "")
                    )
                value, raw_last = _extract_decision(
                    executable, stdout, raw_last_path
                )
                decision = normalize_decision(
                    value, task_id=task_id, trigger=trigger
                )
                decision["reason"] = _redact(
                    decision["reason"], parent_environment
                )
                transcript["decision"] = decision["decision"]
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
        return decision


def _judge_prompt(
    task: Mapping[str, Any], trigger: str, failure: str
) -> str:
    template = (
        Path(__file__).parents[1] / "prompts" / "judge.txt"
    ).read_text(encoding="utf-8")
    context = {
        "task": dict(task),
        "trigger": trigger,
        "failure": failure,
    }
    return template.rstrip() + "\n\nJUDGMENT CONTEXT\n" + json.dumps(
        context, ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n"


def _judge_command(
    binding: ResolvedBinding,
    executable: str,
    working_root: Path,
    schema_path: Path,
    raw_last_path: Path,
    *,
    schema: Mapping[str, Any] = JUDGE_SCHEMA,
    job: str = "judge",
    allow_tools: bool = True,
) -> list[str]:
    if executable == "codex":
        if not allow_tools:
            raise ValueError(
                "codex planner binding is unsupported because this CLI cannot "
                "disable local tools"
            )
        if list(binding.args) != ["exec"]:
            raise ValueError(f"codex {job} args must be exactly ['exec']")
        if list(binding.effort_args) != [
            "-c",
            f"model_reasoning_effort={binding.effort}",
        ]:
            raise ValueError(
                f"codex {job} effort_arg must be "
                "'-c model_reasoning_effort=<effort>'"
            )
        return [
            binding.cli,
            "-a",
            "never",
            *binding.args,
            "--model",
            binding.model,
            *binding.effort_args,
            "--sandbox",
            "read-only",
            "--ignore-user-config",
            "-c",
            "shell_environment_policy.inherit=core",
            "--ephemeral",
            "--json",
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(raw_last_path),
            "--cd",
            str(working_root),
            "-",
        ]
    if executable == "claude":
        if list(binding.args) not in (["-p"], ["--print"]):
            raise ValueError(
                f"claude {job} args must be exactly ['-p'] or ['--print']"
            )
        if binding.effort_args:
            raise ValueError(f"claude {job} binding must not define effort_arg")
        settings_path = working_root / "claude-settings.json"
        settings_path.write_text(
            json.dumps(
                {
                    "sandbox": {
                        "enabled": True,
                        "autoAllowBashIfSandboxed": False,
                        "filesystem": {
                            "allowWrite": [],
                            "denyWrite": [str(working_root)],
                        },
                    }
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return [
            binding.cli,
            *binding.args,
            "--model",
            binding.model,
            "--effort",
            binding.effort,
            "--settings",
            str(settings_path),
            "--setting-sources",
            "project",
            "--permission-mode",
            "auto",
            "--strict-mcp-config",
            "--mcp-config",
            "{}",
            "--no-session-persistence",
            "--no-chrome",
            "--tools",
            "Read,Glob,Grep" if allow_tools else "",
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(schema, separators=(",", ":"), sort_keys=True),
        ]
    raise ValueError(f"{job} binding names unsupported CLI {binding.cli!r}")


def _extract_decision(
    executable: str,
    stdout: str,
    raw_last_path: Path,
    *,
    job: str = "judge",
) -> tuple[Mapping[str, Any], str]:
    if executable == "codex":
        try:
            raw = raw_last_path.read_text(encoding="utf-8")
            value = json.loads(raw)
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(
                f"codex {job} output is not valid JSON: {error}"
            ) from error
    else:
        try:
            envelope = json.loads(stdout)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"claude {job} output is not valid JSON: {error}"
            ) from error
        if not isinstance(envelope, Mapping):
            raise ValueError("claude judge output must be an object")
        value = envelope.get("structured_output")
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n"
    if not isinstance(value, Mapping):
        raise ValueError(f"{job} structured output must be an object")
    return value, raw


def _retain_judge_result(
    transcript_path: Path,
    last_message_path: Path,
    transcript: Mapping[str, Any],
    raw_last: str,
    environment: Mapping[str, str],
) -> None:
    transcript_path.write_text(
        json.dumps(
            _redact_value(transcript, environment),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    last_message_path.write_text(
        _redact(raw_last, environment).rstrip() + "\n",
        encoding="utf-8",
    )
