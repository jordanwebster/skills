"""The `autopilot` command: what operators, chat agents, and flight agents all use."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time
from typing import Any

from . import acceptance, approval, gitops, preflight, prompt, render, supervise
from .dispatch import run_agent
from .loop import Driver
from .plan import PlanError, read_plan, seed_flight
from .roster import Roster, RosterError
from .state import Flight, StateError


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args) or 0
    except RosterError as error:
        if getattr(args, "json", False):
            print(
                json.dumps(
                    {
                        "schema_version": 1,
                        "status": "error",
                        "error": {"class": "config", "message": str(error), "recovery": error.recovery},
                    },
                    sort_keys=True,
                )
            )
        else:
            print(f"autopilot: {error}", file=sys.stderr)
            print(f"Next: {error.recovery}", file=sys.stderr)
        return 1
    except (StateError, PlanError, gitops.GitError, supervise.SupervisionError) as error:
        if getattr(args, "json", False):
            print(
                json.dumps(
                    {
                        "schema_version": 1,
                        "status": "error",
                        "error": {"class": "invalid_work", "message": str(error), "recovery": str(error)},
                    },
                    sort_keys=True,
                )
            )
            return 1
        print(f"autopilot: {error}", file=sys.stderr)
        return 1


# -- parser ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="autopilot",
        description="Fly a repository branch toward a goal with an unattended loop of fresh agents.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="create the flight workspace and branch")
    p.add_argument("--goal", required=True, help="one sentence: what the flight delivers")
    p.add_argument("--branch", help="flight branch (default: autopilot/<goal-slug>)")
    p.add_argument("--requirements", type=Path, required=True, help="confirmed acceptance contract to copy in")
    p.add_argument("--root", type=Path, default=None, help="repository root (default: cwd)")
    p.set_defaults(handler=cmd_init)

    p = sub.add_parser("plan", help="open the flight plan; --dispatch writes it via the planner role")
    p.add_argument("--dispatch", action="store_true", help="run the roster's planner to write the plan")
    p.add_argument("--prompt", action="store_true", help="print the planner prompt and exit")
    p.add_argument("--no-open", action="store_true")
    p.add_argument("--feedback", help="operator feedback for a fresh revision planner")
    p.add_argument("--reason", help="why the current plan was rejected")
    p.add_argument("--observations", type=Path, help="new repository observations for revision")
    p.set_defaults(handler=cmd_plan)

    p = sub.add_parser("approve", help="record explicit approval of the current plan and staffing")
    p.add_argument("--json", action="store_true")
    p.set_defaults(handler=cmd_approve)

    p = sub.add_parser("preflight", help="check approval, staffing, CLIs, and plan prerequisites locally")
    p.set_defaults(handler=cmd_preflight)

    p = sub.add_parser("start", help="preflight, seed tasks from the plan, and launch the driver")
    p.add_argument("--foreground", action="store_true", help="run in this terminal instead of detached")
    p.add_argument("--max-iterations", type=int, help="override the plan's iteration ceiling")
    p.set_defaults(handler=cmd_start)

    p = sub.add_parser("drive", help=argparse.SUPPRESS)
    p.add_argument("root", type=Path)
    p.add_argument("--max-iterations", type=int)
    p.set_defaults(handler=cmd_drive)

    p = sub.add_parser("status", help="how the flight is going")
    p.add_argument("--open", action="store_true", help="open the plan, or the completion page once landed")
    p.add_argument("--json", action="store_true")
    p.set_defaults(handler=cmd_status)

    p = sub.add_parser("stop", help="stop the driver now")
    p.set_defaults(handler=cmd_stop)
    p = sub.add_parser("drain", help="stop the driver after the current iteration")
    p.set_defaults(handler=cmd_drain)

    p = sub.add_parser("log", help="recent flight events")
    p.add_argument("-n", type=int, default=20)
    p.set_defaults(handler=cmd_log)

    task = sub.add_parser("task", help="list, claim, finish, file, and shape tasks")
    tsub = task.add_subparsers(dest="task_command", required=True)

    p = tsub.add_parser("list", help="ready tasks (for your role and chunk when dispatched)")
    p.add_argument("--all", action="store_true", help="every task, every status")
    p.add_argument("--role")
    p.add_argument("--chunk", type=int)
    p.add_argument("--json", action="store_true")
    p.set_defaults(handler=cmd_task_list)

    p = tsub.add_parser("show", help="one task in full")
    p.add_argument("id", type=int)
    p.set_defaults(handler=cmd_task_show)

    p = tsub.add_parser("start", help="claim a task")
    p.add_argument("id", type=int)
    p.set_defaults(handler=cmd_task_start)

    p = tsub.add_parser("done", help="mark a task finished; the driver confirms its check")
    p.add_argument("id", type=int)
    p.set_defaults(handler=cmd_task_done)

    p = tsub.add_parser("note", help="append a note to a task")
    p.add_argument("id", type=int)
    p.add_argument("text")
    p.set_defaults(handler=cmd_task_note)

    p = tsub.add_parser("add", help="file a new task")
    p.add_argument("title")
    p.add_argument("--done-when", default="", help="observable completion criterion")
    p.add_argument("--chunk", type=int, help="chunk id (default: your chunk, else the last one)")
    p.add_argument("--after", default="", help="comma-separated task ids this depends on")
    p.add_argument("--check", help="command that must exit 0 for the task to count")
    p.add_argument("--role")
    p.add_argument("--effort")
    p.add_argument("--origin", help="who filed it (default: your role, else 'operator')")
    p.add_argument("--later", action="store_true", help="record as a follow-up, not scheduled")
    p.set_defaults(handler=cmd_task_add)

    p = tsub.add_parser("edit", help="re-brief a task")
    p.add_argument("id", type=int)
    p.add_argument("--title")
    p.add_argument("--done-when")
    p.add_argument("--check")
    p.add_argument("--role")
    p.add_argument("--effort")
    p.add_argument("--after", help="comma-separated task ids this depends on")
    p.set_defaults(handler=cmd_task_edit)

    p = tsub.add_parser("park", help="set a task aside; it surfaces as a follow-up")
    p.add_argument("id", type=int)
    p.add_argument("reason", nargs="?", default="")
    p.set_defaults(handler=cmd_task_park)

    p = tsub.add_parser("unpark", help="schedule a parked task again")
    p.add_argument("id", type=int)
    p.set_defaults(handler=cmd_task_unpark)

    p = tsub.add_parser("reset", help="clear a task's attempts after re-briefing it")
    p.add_argument("id", type=int)
    p.set_defaults(handler=cmd_task_reset)

    p = sub.add_parser("escalate", help="ask the operator; the flight continues on other work")
    p.add_argument("id", nargs="?", help="task id the question blocks (omit for a flight-level question)")
    p.add_argument("text", help="blocked on X; I would do Y; blast radius if Y is wrong is Z")
    p.set_defaults(handler=cmd_escalate)

    p = sub.add_parser("answer", help="answer an escalation and resume the flight")
    p.add_argument("id", type=int)
    p.add_argument("text")
    p.add_argument("--no-start", action="store_true", help="record the answer without relaunching")
    p.set_defaults(handler=cmd_answer)

    p = sub.add_parser("notes", help="print the flight notes")
    p.set_defaults(handler=cmd_notes)

    p = sub.add_parser("land", help="after landing: delete the workspace and list the follow-ups")
    p.set_defaults(handler=cmd_land)

    p = sub.add_parser("page", help="render a front-page Markdown file as HTML and open it")
    p.add_argument("markdown", type=Path)
    p.add_argument("--title", help="page title (default: the file's first heading or name)")
    p.add_argument("--out", type=Path, help="where to write the HTML (default: beside the Markdown)")
    p.add_argument("--no-open", action="store_true")
    p.set_defaults(handler=cmd_page)
    return parser


# -- helpers ------------------------------------------------------------------------------


def _flight() -> Flight:
    return Flight.find(os.environ.get("AUTOPILOT_ROOT"))


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:40] or "flight"


def _open_in_browser(path: Path) -> None:
    opener = "open" if platform.system() == "Darwin" else shutil.which("xdg-open")
    if not opener or os.environ.get("AUTOPILOT_NO_BROWSER"):
        print(f"Open in your browser: {path}")
        return
    subprocess.run([opener, str(path)], check=False)


def _driver_command(root: Path, max_iterations: int | None) -> list[str]:
    command = [sys.executable, "-m", "autopilot", "drive", str(root)]
    if max_iterations:
        command += ["--max-iterations", str(max_iterations)]
    return command


def _role_from_env() -> str | None:
    return os.environ.get("AUTOPILOT_ROLE")


def _chunk_from_env() -> int | None:
    value = os.environ.get("AUTOPILOT_CHUNK")
    return int(value) if value and value.isdigit() else None


def _ids(text: str) -> list[int]:
    return [int(item) for item in re.split(r"[,\s]+", text.strip()) if item]


# -- flight commands --------------------------------------------------------------------


def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.root or os.getcwd()).resolve()
    if not (root / ".git").exists():
        raise StateError(f"{root} is not a git repository root")
    flight = Flight(root)
    if flight.exists():
        raise StateError(f"a flight already exists at {flight.dir}; land or remove it first")
    receipt = args.requirements.with_name(args.requirements.name + ".acceptance.json")
    if not receipt.is_file():
        raise StateError(
            f"confirmed acceptance receipt not found at {receipt}; if this contract is already confirmed, "
            f"record it with `intake finalize {args.requirements}`"
        )
    approval.validate_acceptance_files(args.requirements, receipt)
    inspection = acceptance.inspect(args.requirements, receipt)
    branch = args.branch or f"autopilot/{_slug(args.goal)}"
    gitops.exclude(root, ".autopilot/")
    if gitops.is_dirty(root):
        raise StateError("the working tree is dirty; commit or stash before starting a flight")
    gitops.ensure_branch(root, branch)
    flight.create(args.goal.strip(), branch, gitops.head(root))
    shutil.copyfile(args.requirements, flight.requirements_path)
    shutil.copyfile(receipt, flight.acceptance_receipt_path)
    acceptance.write(flight.acceptance_path, inspection)
    flight.event(f"flight created on {branch}")
    print(f"Flight created in {flight.dir} (untracked) on branch {branch}.")
    print("Next: write the plan (`autopilot plan --dispatch`, or dispatch the planner yourself), review it, then `autopilot start`.")
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    flight = _flight()
    if args.dispatch and flight.tasks:
        raise StateError("the flight has already started; do not replace its approved plan")
    if bool(args.feedback) != bool(args.reason):
        raise StateError("plan revision needs both --feedback and --reason")
    observations = None
    if args.observations:
        try:
            observations = args.observations.read_text(encoding="utf-8")
        except OSError as error:
            raise StateError(f"cannot read observations: {error}") from error
    planner_text = prompt.planner_prompt(
        flight,
        feedback=args.feedback,
        reason=args.reason,
        observations=observations,
    )
    if args.prompt:
        print(planner_text)
        return 0
    if args.dispatch:
        roster = Roster()
        binding = roster.resolve("planner")
        log_path = flight.runtime_dir / "logs" / "planner.log"
        env = dict(os.environ)
        env["PATH"] = f"{prompt.SCRIPTS_DIR}{os.pathsep}{env.get('PATH', '')}"
        env["AUTOPILOT_ROOT"] = str(flight.root)
        print(f"Dispatching planner via {binding.label}; log at {log_path}")
        outcome = run_agent(
            binding,
            planner_text,
            cwd=flight.root,
            log_path=log_path,
            timeout=flight.config["iteration_timeout"],
            environment=env,
        )
        flight.event(f"planner via {binding.label}: {outcome.exit_class} — {outcome.detail}")
        if outcome.exit_class != "ok":
            recovery = f" Next: {outcome.recovery}" if outcome.recovery else ""
            raise StateError(f"planner {outcome.exit_class}: {outcome.detail} (see {log_path}).{recovery}")
    if not flight.plan_path.exists():
        raise StateError(f"no plan at {flight.plan_path}; write one from the template or run with --dispatch")
    page = _render_plan(flight)
    print(f"Plan page: {page}")
    if not args.no_open:
        _open_in_browser(page)
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    flight = _flight()
    if flight.tasks:
        raise StateError("the flight has already started; its seeded plan cannot be reapproved in place")
    plan = read_plan(flight.plan_path)
    inspection = acceptance.inspect(flight.requirements_path, flight.acceptance_receipt_path)
    receipt = approval.approve(flight, plan, Roster())
    acceptance.write(flight.acceptance_path, inspection)
    flight.event("current plan and semantic staffing approved")
    if args.json:
        print(json.dumps({"schema_version": 1, "status": "approved", **receipt}, sort_keys=True))
    else:
        print("Plan approved for the confirmed acceptance and current staffing.")
        print("Next: start the flight.")
    return 0


def _render_plan(flight: Flight) -> Path:
    """Render the Markdown plan to its HTML page; the page is always regenerated."""

    plan = read_plan(flight.plan_path)
    staffing, _ = approval.resolved_staffing(plan, Roster())
    text = flight.plan_path.read_text(encoding="utf-8")
    title, body = render.split_title(text, default=f"Flight plan: {flight.data['goal']}")
    flight.plan_page_path.write_text(
        render.flight_plan(body, plan, title=title, base=flight.dir, staffing=staffing),
        encoding="utf-8",
    )
    return flight.plan_page_path


def _preflight(flight: Flight) -> bool:
    plan = read_plan(flight.plan_path)
    roster = Roster()
    approval.validate(flight, plan, roster)
    checks = preflight.run(flight, plan, roster)
    print("Preflight:")
    print(preflight.report(checks))
    failed = [check for check in checks if not check.ok]
    flight.event(f"preflight: {len(checks) - len(failed)}/{len(checks)} deterministic checks passed")
    if failed:
        print(f"{len(failed)} check(s) failed.")
        print("Next: fix the first failed prerequisite, then start again.")
        return False
    return True


def cmd_preflight(args: argparse.Namespace) -> int:
    return 0 if _preflight(_flight()) else 1


def cmd_start(args: argparse.Namespace) -> int:
    flight = _flight()
    if flight.data["status"] == "landed":
        raise StateError("this flight has landed; start a new flight for new work")
    if args.max_iterations and args.max_iterations > flight.config["max_iterations"]:
        raise StateError("--max-iterations cannot exceed the operator-approved plan ceiling")
    if not _preflight(flight):
        return 1
    if not flight.tasks:
        seed_flight(flight, read_plan(flight.plan_path))
        flight.event(f"seeded {len(flight.tasks)} tasks in {len(flight.chunks)} chunks from the plan")
    if args.foreground:
        return cmd_drive(argparse.Namespace(root=flight.root, max_iterations=args.max_iterations))
    if supervise.locked_owner(flight.runtime_dir):
        raise StateError("a driver is already running for this flight")
    pid = supervise.start_detached(_driver_command(flight.root, args.max_iterations), flight.runtime_dir)
    print(f"Driver running (pid {pid}). `autopilot status` at any time; `autopilot stop` to halt.")
    return 0


def cmd_drive(args: argparse.Namespace) -> int:
    flight = Flight(args.root).load()
    roster = Roster()
    supervise.install_stop_handlers()
    with supervise.Supervisor(flight.runtime_dir) as supervisor:
        driver = Driver(flight, roster, supervisor=supervisor, max_iterations=args.max_iterations)
        status = driver.run()
        supervisor.finish(status, f"flight {status}")
    print(f"flight {status}")
    return 0 if status in ("landed", "stopped") else 2


def cmd_status(args: argparse.Namespace) -> int:
    flight = _flight()
    driver = supervise.read_status(flight.runtime_dir)
    payload = _status_payload(flight, driver)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.open:
        handoff = flight.data.get("handoff") or {}
        if flight.data["status"] == "landed" and handoff.get("output"):
            target = Path(handoff["output"])
        elif flight.plan_path.is_file():
            target = _render_plan(flight)
        else:
            raise StateError("there is no plan to open yet; dispatch the planner first")
        _open_in_browser(target)
    print(f"Goal: {payload['goal']}")
    progress = payload["progress"]
    visible_state = payload["readiness"]["state"] if payload["status"] == "planned" else payload["status"]
    print(f"Progress: {progress['milestones_done']}/{progress['milestones_total']} milestones · {visible_state}")
    print(f"Driver: {payload['driver']['health']} — {payload['driver']['summary']}")
    if payload["current_work"]:
        print("Current: " + "; ".join(item["title"] for item in payload["current_work"]))
    if payload["questions"]:
        print("Waiting on you: " + payload["questions"][0]["question"])
    print(f"Next: {payload['next_action']['text']}")
    return 0


def _status_payload(flight: Flight, driver: Any) -> dict[str, Any]:
    active = [task for task in flight.tasks if task["status"] == "doing"]
    questions = [
        {"id": item["id"], "question": item["text"], "task_id": item["task"]}
        for item in flight.open_escalations()
    ]
    failure = flight.data.get("failure")
    readiness = _prestart_readiness(flight) if flight.data["status"] == "planned" else {"state": "not_applicable"}
    if flight.data["status"] == "landed":
        next_action = {"kind": "read_completion", "text": "read the completion page.", "command": "autopilot status --open"}
    elif questions:
        next_action = {
            "kind": "answer",
            "text": f"answer “{questions[0]['question']}”",
            "command": f"autopilot answer {questions[0]['id']} \"…\"",
        }
    elif isinstance(failure, dict) and failure.get("class") == "config":
        next_action = {"kind": "repair_config", "text": str(failure.get("recovery") or "repair configuration, then restart.")}
    elif readiness["state"] == "needs_plan":
        next_action = {"kind": "write_plan", "text": "dispatch the planner.", "command": "autopilot plan --dispatch"}
    elif readiness["state"] == "invalid_plan":
        next_action = {"kind": "repair_plan", "text": readiness["recovery"]}
    elif readiness["state"] == "needs_approval":
        next_action = {"kind": "approve", "text": "review the plan and approve it.", "command": "autopilot plan"}
    elif readiness["state"] == "stale_approval":
        next_action = {"kind": "reapprove", "text": readiness["recovery"], "command": "autopilot approve"}
    elif readiness["state"] == "blocked_configuration":
        next_action = {"kind": "repair_config", "text": readiness["recovery"]}
    elif flight.data["status"] == "exhausted":
        next_action = {"kind": "review_exhaustion", "text": "review the exhausted flight and decide whether to start a revised one."}
    elif flight.data["status"] == "stopped" or (flight.data["status"] == "running" and not driver.alive):
        next_action = {"kind": "restart", "text": "restart the flight.", "command": "autopilot start"}
    elif readiness["state"] == "ready_to_start":
        next_action = {"kind": "start", "text": "start the flight.", "command": "autopilot start"}
    else:
        next_action = {"kind": "none", "text": "nothing needed."}
    return {
        "schema_version": 1,
        "goal": flight.data["goal"],
        "status": flight.data["status"],
        "readiness": readiness,
        "progress": {
            "milestones_done": sum(chunk["status"] == "done" for chunk in flight.chunks),
            "milestones_total": len(flight.chunks),
            "milestones": [
                {"title": chunk["title"], "status": chunk["status"]}
                for chunk in flight.chunks
            ],
        },
        "current_work": [{"title": task["title"], "role": flight.task_role(task)} for task in active],
        "driver": {"health": "alive" if driver.alive else "not running", "summary": driver.reason},
        "questions": questions,
        "failure": failure,
        "completion": flight.data.get("handoff"),
        "next_action": next_action,
        "diagnostics": {
            "iteration": flight.data["iteration"],
            "iteration_limit": flight.config["max_iterations"],
            "dispatches": flight.data.get("dispatches", []),
            "recent_events": flight.recent_events(20),
        },
    }


def _prestart_readiness(flight: Flight) -> dict[str, str]:
    if not flight.plan_path.is_file():
        return {"state": "needs_plan"}
    try:
        plan = read_plan(flight.plan_path)
    except PlanError as error:
        return {"state": "invalid_plan", "detail": str(error), "recovery": "repair the flight plan, then render it again."}
    if not flight.approval_path.is_file():
        return {"state": "needs_approval"}
    try:
        approval.validate(flight, plan, Roster())
    except RosterError as error:
        return {"state": "blocked_configuration", "detail": str(error), "recovery": error.recovery}
    except StateError as error:
        return {
            "state": "stale_approval",
            "detail": str(error),
            "recovery": "review the changed acceptance, plan, or staffing and approve it again.",
        }
    return {"state": "ready_to_start"}


def cmd_stop(args: argparse.Namespace) -> int:
    flight = _flight()
    if supervise.stop_driver(flight.runtime_dir):
        print("Driver stopped.")
    else:
        print("No driver is running.")
    return 0


def cmd_drain(args: argparse.Namespace) -> int:
    flight = _flight()
    if supervise.request_drain(flight.runtime_dir):
        print("Driver will stop after the current iteration.")
    else:
        print("No driver is running.")
    return 0


def cmd_log(args: argparse.Namespace) -> int:
    for line in _flight().recent_events(args.n):
        print(line)
    return 0


def cmd_notes(args: argparse.Namespace) -> int:
    print(_flight().notes(), end="")
    return 0


# -- task commands ------------------------------------------------------------------------


def cmd_task_list(args: argparse.Namespace) -> int:
    flight = _flight()
    if args.all:
        tasks = list(flight.tasks)
    else:
        tasks = flight.ready_tasks(role=args.role or _role_from_env(), chunk=args.chunk or _chunk_from_env())
        if not tasks and (args.role or _role_from_env() or args.chunk or _chunk_from_env()):
            tasks = flight.ready_tasks()
            if tasks:
                print("(no ready task matches your role and chunk; showing all ready tasks)")
    if args.json:
        print(json.dumps(tasks, indent=2))
        return 0
    if not tasks:
        print("No ready tasks.")
        return 0
    for task in tasks:
        role = flight.task_role(task)
        print(f"{task['id']:>3}  [{task['status']}] (chunk {task['chunk']}, {role}) {task['title']}")
    return 0


def cmd_task_show(args: argparse.Namespace) -> int:
    flight = _flight()
    task = flight.task(args.id)
    print(prompt.format_task(flight, task).rstrip())
    print(f"Status: {task['status']} · chunk {task['chunk']} · role {flight.task_role(task)} · origin {task['origin']}")
    if task["commit"]:
        print(f"Commit: {task['commit']}")
    return 0


def cmd_task_start(args: argparse.Namespace) -> int:
    flight = _flight()
    task = flight.task(args.id)
    if task["status"] not in ("todo", "doing"):
        raise StateError(f"task {task['id']} is {task['status']}, not ready")
    unmet = [dep for dep in task["depends_on"] if flight.task(dep)["status"] != "done"]
    if unmet:
        raise StateError(f"task {task['id']} still depends on {', '.join(map(str, unmet))}")
    flight.set_status(task, "doing")
    flight.save()
    print(f"Task {task['id']} started: {task['title']}")
    return 0


def cmd_task_done(args: argparse.Namespace) -> int:
    flight = _flight()
    task = flight.task(args.id)
    if task["status"] == "done":
        print(f"Task {task['id']} is already done.")
        return 0
    flight.set_status(task, "done")
    flight.save()
    flight.event(f"task {task['id']} marked done by {_role_from_env() or 'operator'}")
    check = f" The driver will confirm with `{task['check']}`." if task.get("check") else ""
    print(f"Task {task['id']} done.{check}")
    return 0


def cmd_task_note(args: argparse.Namespace) -> int:
    flight = _flight()
    flight.note(flight.task(args.id), args.text)
    flight.save()
    return 0


def cmd_task_add(args: argparse.Namespace) -> int:
    flight = _flight()
    chunk = args.chunk or _chunk_from_env() or (flight.chunks[-1]["id"] if flight.chunks else None)
    if chunk is None:
        raise StateError("no chunk to file the task into; seed the flight first")
    task = flight.add_task(
        args.title,
        chunk=chunk,
        done_when=args.done_when,
        check=args.check,
        role=args.role,
        effort=args.effort,
        depends_on=_ids(args.after),
        origin=args.origin or _role_from_env() or "operator",
        status="parked" if args.later else "todo",
        notes="Filed as a follow-up." if args.later else "",
    )
    flight.save()
    flight.event(f"task {task['id']} filed by {task['origin']}: {task['title']}" + (" (later)" if args.later else ""))
    print(f"Task {task['id']} filed in chunk {chunk}.")
    return 0


def cmd_task_edit(args: argparse.Namespace) -> int:
    flight = _flight()
    task = flight.task(args.id)
    for field in ("title", "done_when", "check", "role", "effort"):
        value = getattr(args, field)
        if value is not None:
            task[field] = value
    if args.after is not None:
        dependencies = _ids(args.after)
        for dependency in dependencies:
            flight.task(dependency)
        task["depends_on"] = sorted(set(dependencies) - {task["id"]})
    flight.save()
    flight.event(f"task {task['id']} re-briefed by {_role_from_env() or 'operator'}")
    return 0


def cmd_task_park(args: argparse.Namespace) -> int:
    flight = _flight()
    task = flight.task(args.id)
    flight.set_status(task, "parked")
    if args.reason:
        flight.note(task, f"Parked: {args.reason}")
    flight.save()
    flight.event(f"task {task['id']} parked by {_role_from_env() or 'operator'}")
    return 0


def cmd_task_unpark(args: argparse.Namespace) -> int:
    flight = _flight()
    task = flight.task(args.id)
    if task["status"] != "parked":
        raise StateError(f"task {task['id']} is {task['status']}, not parked")
    flight.set_status(task, "todo")
    task["attempts"] = 0
    flight.save()
    flight.event(f"task {task['id']} unparked")
    return 0


def cmd_task_reset(args: argparse.Namespace) -> int:
    flight = _flight()
    task = flight.task(args.id)
    task["attempts"] = 0
    if task["status"] in ("blocked", "parked"):
        flight.set_status(task, "todo")
    flight.save()
    flight.event(f"task {task['id']} attempts reset")
    return 0


def cmd_escalate(args: argparse.Namespace) -> int:
    flight = _flight()
    task_id: int | None = None
    if args.id is not None:
        if args.id.isdigit():
            task_id = int(args.id)
            flight.task(task_id)
        else:
            args.text = f"{args.id} {args.text}"
    escalation = flight.add_escalation(task_id, args.text)
    flight.save()
    flight.event(f"escalation #{escalation['id']} raised by {_role_from_env() or 'operator'}: {args.text[:80]}")
    print(f"Escalation #{escalation['id']} recorded; the flight continues on other work.")
    return 0


def cmd_answer(args: argparse.Namespace) -> int:
    flight = _flight()
    escalation = flight.answer_escalation(args.id, args.text)
    flight.save()
    flight.event(f"escalation #{escalation['id']} answered")
    print(f"Answer recorded for #{escalation['id']}.")
    if args.no_start or supervise.locked_owner(flight.runtime_dir):
        return 0
    if flight.data["status"] in ("escalated", "stopped", "exhausted") and not flight.open_escalations():
        pid = supervise.start_detached(_driver_command(flight.root, None), flight.runtime_dir)
        print(f"Driver relaunched (pid {pid}).")
    elif flight.open_escalations():
        print("Other escalations are still open; relaunch with `autopilot start` when all are answered.")
    return 0


def cmd_land(args: argparse.Namespace) -> int:
    flight = _flight()
    if flight.data["status"] != "landed":
        raise StateError(f"the flight is {flight.data['status']}, not landed; nothing to tidy yet")
    if supervise.locked_owner(flight.runtime_dir):
        raise StateError("a driver is still running; stop it first")
    follow_ups = flight.parked_tasks()
    handoff = flight.data.get("handoff") or {}
    reviewed_commit = str(handoff.get("reviewed_commit") or "unknown")
    if not flight.handoff_dir.is_dir():
        raise StateError("the landed flight has no final Handoff workspace to preserve")
    gitops.exclude(flight.root, ".handoff/")
    export_root = flight.root / ".handoff"
    export_root.mkdir(parents=True, exist_ok=True)
    export_path = export_root / f"{_slug(flight.data['goal'])}-{reviewed_commit[:12]}"
    if export_path.exists():
        raise StateError(f"final Handoff export already exists at {export_path}; move it aside, then land again")
    shutil.move(str(flight.handoff_dir), str(export_path))
    output_name = Path(str(handoff.get("output") or "handoff.html")).name
    preserved_output = export_path / output_name
    shutil.rmtree(flight.dir)
    print(f"Final Handoff preserved: {preserved_output}")
    print(f"Flight machinery deleted. Branch {flight.data['branch']} is ready for review and merge.")
    if follow_ups:
        print("Follow-ups to file (on the operator's word), e.g. with the tasks skill:")
        for task in follow_ups:
            print(f"  tasks add \"{task['title']}\"")
    return 0


def cmd_page(args: argparse.Namespace) -> int:
    source: Path = args.markdown
    try:
        body = source.read_text(encoding="utf-8")
    except OSError as error:
        raise StateError(f"cannot read {source}: {error}") from error
    title, body = render.split_title(body, default=args.title or source.stem.replace("-", " "))
    if args.title:
        title = args.title
    out = args.out or source.with_suffix(".html")
    out.write_text(render.page(title, body, base=source.resolve().parent), encoding="utf-8")
    print(f"Wrote {out}")
    if not args.no_open:
        _open_in_browser(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
