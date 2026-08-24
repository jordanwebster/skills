"""Vendor-neutral adapter result contract."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DispatchResult:
    """The retained outputs of one ephemeral worker dispatch."""

    exit_class: str
    transcript_path: Path
    last_message_path: Path
    binding_label: str | None = None
    failure_reason: str | None = None
