"""Deterministic prompt assembly from shipped and flight-durable files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping


_TEMPLATE_PATH = Path(__file__).parent / "prompts" / "worker.txt"


def assemble_prompt(
    task: Mapping[str, Any],
    durable_paths: Iterable[str | Path],
) -> str:
    """Concatenate the worker template, task record, and ordered durable inputs."""

    sections = [
        _TEMPLATE_PATH.read_text(encoding="utf-8").rstrip(),
        "\n\n--- TASK RECORD ---\n",
        json.dumps(task, ensure_ascii=False, indent=2, sort_keys=True),
    ]
    for raw_path in durable_paths:
        path = Path(raw_path)
        sections.extend(
            [
                f"\n\n--- DURABLE INPUT: {path.name} ---\n",
                path.read_text(encoding="utf-8").rstrip(),
            ]
        )
    return "".join(sections).rstrip() + "\n"
