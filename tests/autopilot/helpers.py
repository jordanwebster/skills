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
from autopilot import acceptance, approval
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


def plan_markdown(plan: dict) -> str:
    routes = []
    for chunk in plan["chunks"]:
        routes.append(
            f"### Milestone {chunk['id']} — {chunk['title']}\n\n"
            f"- **Produces:** The {chunk['title']} result.\n"
            f"- **Unlocks:** The next planned boundary.\n"
            f"- **Validated by:** A fast deterministic boundary check.\n"
        )
    return (
        "# Toy plan\n\n## Goal\n\nBuild the toy.\n\n**Done means:** The toy is observable.\n\n"
        "## Route\n\n" + "\n".join(routes) + "\n"
        "## Shape\n\n"
        "### Components\n\n- **Toy** — owns the result, lives in `toy/`.\n\n"
        "### Interfaces and APIs\n\n- `toy()` — returns the result, never raises.\n\n"
        "### Data shapes\n\n- **Result** — the text the toy produced.\n\n"
        "## Human judgment\n\nConfirm the result is useful.\n\n"
        "## What you will be asked\n\n"
        "| Act | When | Default | Exposure |\n| --- | --- | --- | --- |\n"
        "| Approve this route | Now | Nothing starts | Planned flight |\n\n"
        "```flight-plan\n" + json.dumps(plan, indent=2) + "\n```\n"
    )


def toy_plan(tasks: list[dict], *, chunks: list[dict] | None = None, config: dict | None = None) -> dict:
    ceiling = (config or {}).get("max_iterations", 30)
    selected_config = {
        "max_iterations": 30,
        "expected_iterations": {"min": min(3, ceiling), "max": min(8, ceiling)},
    }
    selected_config.update(config or {})
    return {
        "goal": "Build the toy",
        "config": selected_config,
        "evidence": [
            {
                "id": "toy-result",
                "claim": "The toy works",
                "demonstrations": ["toy-result"],
                "artifacts": ["evidence/toy.txt"],
                "stages": [1],
                "replay": {"kind": "command", "command": "test -f 1.txt"},
            }
        ],
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


ROLES = ("planner", "implementer", "ui-developer", "prober", "qa-tester", "reviewer", "closer")


def write_roster(path: Path, roles: tuple[str, ...] = ROLES, *, cli: str = "python3") -> Path:
    path.write_text(
        "".join(
            f"[{role}]\ncli = \"{cli}\"\nargs = [\"{FAKE_AGENT}\"]\nfamily = \"generic\"\nmodel = \"fake\"\neffort = \"low\"\n\n"
            for role in roles
        )
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
        self.env = dict(os.environ)
        self.env.update(
            {
                "DELEGATE_ROSTER": str(self.roster_path),
                "DELEGATE_COMMAND": str(SKILL_DIR.parent / "delegate" / "scripts" / "delegate"),
                "AUTOPILOT_INFRA_WAIT": "0",
                "AUTOPILOT_NO_BROWSER": "1",
                "PYTHONPATH": str(SKILL_DIR / "lib"),
                "GIT_AUTHOR_NAME": "Autopilot Tests",
                "GIT_AUTHOR_EMAIL": "autopilot@example.invalid",
                "GIT_COMMITTER_NAME": "Autopilot Tests",
                "GIT_COMMITTER_EMAIL": "autopilot@example.invalid",
            }
        )
        self.roster = Roster(environment=self.env)
        for name in (
            "FAKE_REVIEW_FINDINGS", "FAKE_CLOSER_GAPS", "FAKE_CLOSER_TRIAGE",
            "FAKE_CLOSER_BAD_PROOF", "FAKE_CLOSER_EVIDENCE_GAP",
            "FAKE_CLOSER_PARKED_GAP", "FAKE_TRIAGE_CLOSE_RESOLVE",
            "FAKE_INFRA", "FAKE_CONFIG", "FAKE_SLEEP",
        ):
            self.env.pop(name, None)

    def seed(self, plan: dict, *, approve: bool = True) -> Flight:
        gitops.exclude(self.root, ".autopilot/")
        flight = Flight(self.root).create(plan["goal"], "autopilot/toy", git(self.root, "rev-parse", "HEAD").strip())
        flight.requirements_path.write_text("# Confirmed acceptance\n\nThe toy result is visible.\n")
        flight.acceptance_receipt_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "contract_digest": approval.digest_bytes(flight.requirements_path.read_bytes()),
                    "confirmed_at": "2026-01-01T00:00:00+00:00",
                }
            )
        )
        acceptance.write(
            flight.acceptance_path,
            {
                "schema_version": 1,
                "ok": True,
                "contract_digest": approval.digest_bytes(flight.requirements_path.read_bytes()),
                "confirmed_at": "2026-01-01T00:00:00+00:00",
                "acceptance": {
                    "goal": "Build the toy",
                    "expectations": [
                        {"id": "toy-expectation", "description": "The toy result is visible.", "kind": "outcome"}
                    ],
                    "demonstrations": [
                        {
                            "id": "toy-result",
                            "description": "The toy result is visible.",
                            "covers": ["toy-expectation"],
                            "demonstration": "A transcript contains the completed result.",
                            "limitation": "None.",
                        }
                    ],
                    "accepted_gaps": [],
                },
            },
        )
        flight.plan_path.write_text(plan_markdown(plan))
        seed_flight(flight, read_plan(flight.plan_path))
        if approve:
            approval.approve(flight, read_plan(flight.plan_path), self.roster)
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
