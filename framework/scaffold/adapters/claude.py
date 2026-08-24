"""Claude CLI dispatch adapter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .process import CLAIM_SCHEMA, ProcessAdapter


class ClaudeAdapter(ProcessAdapter):
    """Invoke Claude in print mode with an invocation-scoped sandbox policy."""

    adapter_name = "claude"
    auth_environment_names = frozenset(
        {
            "ANTHROPIC_API_KEY",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN",
            "CLAUDE_CODE_OAUTH_TOKEN",
            "GOOGLE_APPLICATION_CREDENTIALS",
        }
    )

    def command(
        self,
        *,
        checkout: Path,
        schema_path: Path,
        raw_last_path: Path,
        sandbox: str,
    ) -> list[str]:
        arguments = list(self.binding.args)
        if arguments not in (["-p"], ["--print"]):
            raise ValueError("claude roster args must be exactly ['-p'] or ['--print']")
        if self.binding.effort_args:
            raise ValueError("claude binding must not define effort_arg")
        settings_path = schema_path.parent / "claude-settings.json"
        settings_path.write_text(
            json.dumps(
                {
                    "sandbox": {
                        "enabled": True,
                        "autoAllowBashIfSandboxed": True,
                        "filesystem": {
                            "allowWrite": (
                                [str(checkout)] if sandbox == "workspace-write" else []
                            ),
                            "denyWrite": [
                                str(checkout / ".scaffolding"),
                                str(checkout / ".SCAFFOLDING"),
                            ],
                        },
                    }
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return [
            self.binding.cli,
            *arguments,
            "--model",
            self.binding.model,
            "--effort",
            self.binding.effort,
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
            (
                "Bash,Edit,Read,Write,Glob,Grep"
                if sandbox == "workspace-write"
                else "Bash,Read,Glob,Grep"
            ),
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(CLAIM_SCHEMA, separators=(",", ":"), sort_keys=True),
        ]

    def extract_claim(
        self,
        *,
        stdout: str,
        raw_last_path: Path,
    ) -> tuple[dict[str, Any], str]:
        try:
            envelope = json.loads(stdout)
        except json.JSONDecodeError as error:
            raise ValueError(f"claude did not produce valid JSON output: {error}") from error
        if not isinstance(envelope, dict):
            raise ValueError("claude JSON output must be an object")
        value = envelope.get("structured_output")
        if not isinstance(value, dict):
            raise ValueError("claude output omitted structured_output claim")
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n"
        return value, raw
