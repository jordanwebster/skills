"""Codex CLI dispatch adapter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .process import ProcessAdapter


class CodexAdapter(ProcessAdapter):
    """Invoke `codex exec` with a framework-owned sandbox and claim schema."""

    adapter_name = "codex"
    auth_environment_names = frozenset(
        {"AZURE_OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_API_KEY"}
    )

    def command(
        self,
        *,
        checkout: Path,
        schema_path: Path,
        raw_last_path: Path,
    ) -> list[str]:
        arguments = list(self.binding.args)
        if arguments != ["exec"]:
            raise ValueError("codex roster args must be exactly ['exec']")
        effort_args = list(self.binding.effort_args)
        if effort_args != [
            "-c",
            f"model_reasoning_effort={self.binding.effort}",
        ]:
            raise ValueError(
                "codex effort_arg must be '-c model_reasoning_effort=<effort>'"
            )
        return [
            self.binding.cli,
            "-a",
            "never",
            *arguments,
            "--model",
            self.binding.model,
            *effort_args,
            "--sandbox",
            "workspace-write",
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
            str(checkout),
            "-",
        ]

    def extract_claim(
        self,
        *,
        stdout: str,
        raw_last_path: Path,
    ) -> tuple[dict[str, Any], str]:
        try:
            raw = raw_last_path.read_text(encoding="utf-8")
            value = json.loads(raw)
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"codex did not produce a valid structured claim: {error}") from error
        if not isinstance(value, dict):
            raise ValueError("codex structured claim must be a JSON object")
        return value, raw
