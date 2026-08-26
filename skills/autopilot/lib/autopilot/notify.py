"""Best-effort desktop notification so the operator knows to open a chat."""

from __future__ import annotations

import platform
import shutil
import subprocess


def notify(title: str, message: str) -> None:
    try:
        if platform.system() == "Darwin":
            script = (
                f'display notification "{_escape(message)}" '
                f'with title "{_escape(title)}"'
            )
            subprocess.run(["osascript", "-e", script], check=False, timeout=10,
                           capture_output=True)
        elif shutil.which("notify-send"):
            subprocess.run(["notify-send", title, message], check=False, timeout=10,
                           capture_output=True)
    except (OSError, subprocess.SubprocessError):
        pass


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')[:200]
