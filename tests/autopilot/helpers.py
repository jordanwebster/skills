"""Shared fixtures: a throwaway repository, a plan, and a roster of fake agents."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from autopilot import gitops
from autopilot.plan import read_plan, seed_flight
from autopilot.roster import Roster
from autopilot.state import Flight


HERE = Path(__file__).resolve().parent
FAKE_AGENT = HERE / "fake_agent.py"
SKILL_DIR = HERE.parent.parent / "skills" / "autopilot"


def git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=root, check=True, capture_output=True, text=True
    ).stdout


def make_repo(root: Path) -> None:
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.name", "Autopilot Tests")
    git(root, "config", "user.email", "autopilot@example.invalid")
    (root / "README.md").write_text("# Toy\n")
    git(root, "add", "README.md")
    git(root, "commit", "-q", "-m", "Initial commit")


def plan_html(plan: dict) -> str:
    return (
        "<h1>Toy plan</h1>\n"
        '<script type="application/json" id="flight-plan">\n'
        + json.dumps(plan, indent=2)
        + "\n</script>\n"
    )


def toy_plan(tasks: list[dict], *, chunks: list[dict] | None = None, config: dict | None = None) -> dict:
    return {
        "goal": "Build the toy",
        "config": config or {"max_iterations": 30},
        "chunks": chunks or [{"id": 1, "title": "Files", "role": "implementer", "check": "test -f README.md"}],
        "tasks": tasks,
    }


def task(task_id: int, title: str, *, chunk: int = 1, depends_on: list[int] | None = None, check: str | None = "default", role: str | None = None) -> dict:
    return {
        "id": task_id,
        "chunk": chunk,
        "title": title,
        "done_when": f"{task_id}.txt exists and says ok",
        "check": f"grep -q ok {task_id}.txt" if check == "default" else check,
        "depends_on": depends_on or [],
        "role": role,
    }


def write_roster(path: Path) -> Path:
    path.write_text(
        "[default]\n"
        'cli = "python3"\n'
        f'args = ["{FAKE_AGENT}"]\n'
        'model = "fake"\n'
        'effort = "low"\n'
    )
    return path


class FlightCase(unittest.TestCase):
    """A test with a fresh repository, a seeded flight, and a fake roster."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "repo"
        self.root.mkdir()
        make_repo(self.root)
        self.roster_path = write_roster(self.base / "roster.toml")
        self.roster = Roster(self.roster_path)
        self.env = dict(os.environ)
        self.env.update(
            {
                "DELEGATE_ROSTER": str(self.roster_path),
                "AUTOPILOT_INFRA_WAIT": "0",
                "AUTOPILOT_NO_BROWSER": "1",
                "PYTHONPATH": str(SKILL_DIR / "lib"),
                "GIT_AUTHOR_NAME": "Autopilot Tests",
                "GIT_AUTHOR_EMAIL": "autopilot@example.invalid",
                "GIT_COMMITTER_NAME": "Autopilot Tests",
                "GIT_COMMITTER_EMAIL": "autopilot@example.invalid",
            }
        )
        for name in ("FAKE_REVIEW_FINDINGS", "FAKE_CLOSER_GAPS", "FAKE_INFRA", "FAKE_SLEEP"):
            self.env.pop(name, None)

    def seed(self, plan: dict) -> Flight:
        gitops.exclude(self.root, ".autopilot/")
        flight = Flight(self.root).create(plan["goal"], "autopilot/toy", git(self.root, "rev-parse", "HEAD").strip())
        flight.plan_path.write_text(plan_html(plan))
        seed_flight(flight, read_plan(flight.plan_path))
        git(self.root, "checkout", "-q", "-b", "autopilot/toy")
        return flight

    def cli(self, *arguments: str, cwd: Path | None = None, env: dict | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "autopilot", *arguments],
            cwd=cwd or self.root,
            env=env or self.env,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
