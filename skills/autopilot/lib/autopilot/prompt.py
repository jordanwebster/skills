"""Assemble the prompt for one dispatched agent.

Prompts stay small on purpose: the goal, the role's contract, the tasks
this agent may pull, the flight notes, and the commands it can run. Design
context lives in the plan file, which the agent reads itself.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .state import Flight


PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"
SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"

# Roles that share the worker contract: anything that pulls tasks and edits
# the product. Roles missing here fall back to the worker prompt too, so an
# operator can invent a role in the roster without touching this file.
ROLE_PROMPTS = {
    "implementer": "worker.md",
    "ui-developer": "worker.md",
    "prober": "prober.md",
    "qa-tester": "qa-tester.md",
    "reviewer": "reviewer.md",
    "closer": "closer.md",
    "planner": "planner.md",
    "replan": "replan.md",
}


def role_prompt(name: str) -> str:
    filename = ROLE_PROMPTS.get(name, "worker.md")
    return (PROMPTS_DIR / filename).read_text(encoding="utf-8")


def header(flight: Flight, role: str) -> str:
    config = flight.config
    lines = [
        f"You are the {role} on an autopilot flight: an unattended loop of fresh agents "
        f"working one branch of this repository toward a goal.",
        f"Iteration {flight.data['iteration']} of at most {config['max_iterations']}.",
        "",
        f"Repository: {flight.root}",
        f"Branch: {flight.data['branch']}",
        f"Goal: {flight.data['goal']}",
        "",
        "Read before acting:",
        "- .autopilot/flight-plan.md — the approved design and plan",
        "- .autopilot/NOTES.md — what earlier iterations learned (included below)",
    ]
    if flight.requirements_path.exists():
        lines.append("- .autopilot/requirements.md — the operator's confirmed requirements")
    lines += [
        "",
        f"The `autopilot` command is at {SCRIPTS_DIR / 'autopilot'} and on your PATH. "
        "Run `autopilot task list` at any time to see ready work.",
        "",
    ]
    return "\n".join(lines)


def worker_prompt(
    flight: Flight,
    role: str,
    chunk: dict[str, Any],
    tasks: Sequence[dict[str, Any]],
) -> str:
    parts = [header(flight, role), role_prompt(role), "", "## Your chunk", ""]
    parts.append(f"Chunk {chunk['id']}: {chunk['title']}")
    if chunk.get("check"):
        parts.append(f"Chunk verification (runs when the chunk is complete): `{chunk['check']}`")
    parts += ["", "## Ready tasks for you, in order", ""]
    for task in tasks:
        parts.append(format_task(flight, task))
    parts += ["", "## Flight notes", "", flight.notes().strip() or "(none yet)", ""]
    parts += [commands_block(role)]
    return "\n".join(parts)


def format_task(flight: Flight, task: dict[str, Any]) -> str:
    lines = [f"### Task {task['id']} — {task['title']}"]
    if task.get("done_when"):
        lines.append(f"Done when: {task['done_when']}")
    if task.get("check"):
        lines.append(f"Check: `{task['check']}`")
    if task["depends_on"]:
        lines.append("Depends on: " + ", ".join(str(item) for item in task["depends_on"]))
    if task["attempts"]:
        lines.append(f"Earlier attempts: {task['attempts']}")
    if task.get("notes"):
        lines.append("Notes:")
        lines.extend(f"  {line}" for line in task["notes"].splitlines())
    lines.append("")
    return "\n".join(lines)


def commands_block(role: str) -> str:
    return "\n".join(
        [
            "## Commands",
            "",
            "```",
            "autopilot task list                          ready tasks for your role and chunk",
            "autopilot task show <id>                     one task in full",
            "autopilot task start <id>                    claim a task before working on it",
            "autopilot task done <id>                      mark it finished (the driver confirms)",
            "autopilot task note <id> \"text\"              record a decision, a partial state, a failure",
            "autopilot task add \"title\" --done-when \"…\" [--chunk N] [--after ID,...] [--check CMD] [--role R]",
            "autopilot task add \"title\" --later           record follow-up work without scheduling it",
            "autopilot task park <id> \"reason\"            set a task aside (surfaces as a follow-up)",
            "autopilot escalate <id> \"blocked on X; I would do Y; blast radius if Y is wrong is Z\"",
            "```",
            "",
        ]
    )


def reviewer_prompt(flight: Flight, chunk: dict[str, Any], *, base: str) -> str:
    from .gitops import diff_stat, log_oneline

    parts = [header(flight, "reviewer"), role_prompt("reviewer"), ""]
    parts += [
        "## The chunk under review",
        "",
        f"Chunk {chunk['id']}: {chunk['title']}",
        f"Commit range: {base[:12]}..HEAD  (run `git diff {base[:12]}..HEAD` to read it)",
        "",
        "Commits:",
        "```",
        log_oneline(flight.root, base).strip() or "(none)",
        "```",
        "",
        "Files:",
        "```",
        diff_stat(flight.root, base).strip() or "(no changes)",
        "```",
        "",
        "Tasks in this chunk:",
        "",
    ]
    for task in flight.chunk_tasks(chunk["id"]):
        parts.append(f"- Task {task['id']} [{task['status']}] {task['title']}")
        if task.get("done_when"):
            parts.append(f"  done when: {task['done_when']}")
    parts += ["", "## Flight notes", "", flight.notes().strip() or "(none yet)", ""]
    parts.append(f"Write your review to `.autopilot/reviews/chunk-{chunk['id']}.md`.")
    parts.append(
        f"File each must-fix finding with "
        f"`autopilot task add \"…\" --done-when \"…\" --chunk {chunk['id']} --origin review`."
    )
    return "\n".join(parts)


def closer_prompt(flight: Flight, *, check_result: str | None) -> str:
    from .gitops import diff_stat

    parts = [header(flight, "closer"), role_prompt("closer"), ""]
    parts += [
        "## The flight",
        "",
        f"Base commit: {flight.data['base'][:12]}  (run `git diff {flight.data['base'][:12]}..HEAD`)",
        "",
        "```",
        diff_stat(flight.root, flight.data["base"]).strip() or "(no changes)",
        "```",
        "",
    ]
    if check_result is not None:
        parts += ["Whole-flight verification:", "```", check_result, "```", ""]
    parts += ["Chunks:", ""]
    for chunk in flight.chunks:
        tasks = flight.chunk_tasks(chunk["id"])
        done = sum(1 for task in tasks if task["status"] == "done")
        parts.append(f"- Chunk {chunk['id']} {chunk['title']}: {done}/{len(tasks)} tasks done")
        review = flight.dir / "reviews" / f"chunk-{chunk['id']}.md"
        if review.exists():
            parts.append(f"  review: .autopilot/reviews/chunk-{chunk['id']}.md")
    parked = flight.parked_tasks()
    if parked:
        parts += ["", "Parked tasks (follow-ups, not built):", ""]
        parts += [f"- Task {task['id']} {task['title']}: {task['notes'].splitlines()[-1] if task['notes'] else ''}" for task in parked]
    parts += ["", "## Flight notes", "", flight.notes().strip() or "(none yet)", ""]
    parts.append("Write your verdict to `.autopilot/acceptance.md`.")
    parts.append(
        "File each genuine gap with `autopilot task add \"…\" --done-when \"…\" --origin closer` "
        "(it lands in the last chunk unless you pass --chunk)."
    )
    return "\n".join(parts)


def replan_prompt(flight: Flight, task: dict[str, Any], *, reason: str) -> str:
    parts = [header(flight, "planner"), role_prompt("replan"), ""]
    parts += ["## Why you were called", "", reason, "", "## The task", ""]
    parts.append(format_task(flight, task))
    chunk = flight.chunk(task["chunk"])
    parts += [f"Chunk {chunk['id']}: {chunk['title']} (role {chunk.get('role')})", ""]
    parts += ["## Flight notes", "", flight.notes().strip() or "(none yet)", ""]
    parts += [
        "## Commands",
        "",
        "```",
        f"autopilot task edit {task['id']} --title \"…\" --done-when \"…\" [--check CMD] [--role R]",
        f"autopilot task reset {task['id']}              clear attempts after re-briefing",
        f"autopilot task note {task['id']} \"text\"",
        "autopilot task add \"title\" --done-when \"…\" --chunk N [--after ID,...] [--check CMD] [--role R]",
        f"autopilot task park {task['id']} \"reason\"",
        f"autopilot escalate {task['id']} \"blocked on X; I would do Y; blast radius if Y is wrong is Z\"",
        "```",
        "",
    ]
    return "\n".join(parts)


def planner_prompt(flight: Flight) -> str:
    template = PROMPTS_DIR.parent / "templates" / "flight-plan.md"
    parts = [header(flight, "planner"), role_prompt("planner"), ""]
    parts += [
        f"Plan template: {template}",
        f"Write the plan to: {flight.plan_path}",
        "",
    ]
    if flight.requirements_path.exists():
        parts += ["## Confirmed requirements", "", flight.requirements_path.read_text(encoding="utf-8"), ""]
    return "\n".join(parts)
