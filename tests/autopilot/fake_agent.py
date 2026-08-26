"""A scripted stand-in for a real agent CLI.

It reads the prompt on stdin like a real CLI would, then acts through the
same `autopilot` command real agents use. Markers in task titles script the
failure modes the loop must handle:

  [fail-once]   leave the task in progress on its first attempt
  [badcheck]    mark done with output that fails the task's check
  [escalate]    raise an escalation instead of working, once
  [stall]       exit without touching anything

"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


ROOT = Path(os.environ["AUTOPILOT_ROOT"])
ROLE = os.environ.get("AUTOPILOT_ROLE", "implementer")


def autopilot(*arguments: str) -> str:
    completed = subprocess.run(
        ["autopilot", *arguments], cwd=ROOT, capture_output=True, text=True, check=False
    )
    if completed.returncode != 0:
        raise SystemExit(f"autopilot {' '.join(arguments)} failed: {completed.stderr}")
    return completed.stdout


def git(*arguments: str) -> None:
    subprocess.run(["git", *arguments], cwd=ROOT, check=True, capture_output=True)


def flight() -> dict:
    return json.loads((ROOT / ".autopilot" / "flight.json").read_text())


def work() -> None:
    for task in json.loads(autopilot("task", "list", "--json")):
        title = task["title"]
        if "[stall]" in title:
            return
        if "[escalate]" in title and not any(
            item["task"] == task["id"] for item in flight()["escalations"]
        ):
            autopilot("escalate", str(task["id"]), "blocked on the marker; I would remove it; blast radius none")
            continue
        autopilot("task", "start", str(task["id"]))
        if "[fail-once]" in title and task["attempts"] == 0:
            autopilot("task", "note", str(task["id"]), "stopped halfway through")
            return
        path = ROOT / f"{task['id']}.txt"
        path.write_text("wrong\n" if "[badcheck]" in title else "ok\n")
        git("add", path.name)
        git("commit", "-q", "-m", f"Add {path.name}")
        autopilot("task", "done", str(task["id"]))
    notes = ROOT / ".autopilot" / "NOTES.md"
    notes.write_text(notes.read_text() + f"- {ROLE} ran\n")


def review() -> None:
    chunk = os.environ["AUTOPILOT_CHUNK"]
    review_dir = ROOT / ".autopilot" / "reviews"
    review_dir.mkdir(exist_ok=True)
    (review_dir / f"chunk-{chunk}.md").write_text("# Review\n\n## Must fix\n\nnone\n")
    if os.environ.get("FAKE_REVIEW_FINDINGS"):
        autopilot("task", "add", f"Fix review finding in chunk {chunk}", "--done-when", "fixed", "--origin", "review")


def close() -> None:
    gaps = os.environ.get("FAKE_CLOSER_GAPS") and flight()["closer_rounds"] == 1
    if gaps:
        autopilot("task", "add", "Close the acceptance gap", "--done-when", "closed", "--origin", "closer")
        return
    workspace = ROOT / ".autopilot" / "handoff"
    evidence = workspace / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    source = next(iter(sorted(ROOT.glob("*.txt"))), None)
    (evidence / "toy.txt").write_text(source.read_text() if source else "ok\n")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    (workspace / "proof.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mode": "page",
                "title": "Toy result",
                "reviewed_commit": head,
                "review": {
                    "reviewer": "Closer",
                    "reviewed_commit": head,
                    "summary": "Exercised the committed result and checked its capture.",
                    "limitations": [],
                },
                "changes": ["The toy now produces the expected result."],
                "accepted_demonstrations": [
                    {"id": "toy-result", "description": "The toy result is visible."}
                ],
                "claims": [
                    {
                        "claim": "The toy produces its result.",
                        "demonstrations": ["toy-result"],
                        "artifacts": [{"path": "evidence/toy.txt", "label": "Captured result"}],
                        "replay": {"kind": "command", "command": "test -f 1.txt"},
                        "gap": "none",
                    }
                ],
                "decisions": [],
                "follow_ups": [],
            },
            indent=2,
        )
    )


def replan(prompt: str) -> None:
    match = re.search(r"### Task (\d+)", prompt)
    if not match:
        raise SystemExit("replan prompt names no task")
    task_id = match.group(1)
    title = [task for task in flight()["tasks"] if task["id"] == int(task_id)][0]["title"]
    autopilot("task", "edit", task_id, "--title", "Re-briefed: " + re.sub(r"\[[a-z-]+\]", "", title).strip())
    autopilot("task", "reset", task_id)


def main() -> int:
    prompt = sys.stdin.read()
    if "connectivity check" in prompt:
        print("ok")
        return 0
    if os.environ.get("FAKE_SLEEP"):
        time.sleep(float(os.environ["FAKE_SLEEP"]))
    if os.environ.get("FAKE_INFRA"):
        print("API Error: 529 Overloaded")
        return 1
    if os.environ.get("FAKE_CONFIG"):
        print("unknown option --obsolete-effort")
        return 2
    if ROLE == "reviewer":
        review()
    elif ROLE == "closer":
        close()
    elif ROLE == "planner":
        replan(prompt)
    else:
        work()
    return 0


if __name__ == "__main__":
    sys.exit(main())
