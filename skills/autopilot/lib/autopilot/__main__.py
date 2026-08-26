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

from . import gitops, prompt, render, supervise
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
    except (StateError, PlanError, RosterError, gitops.GitError, supervise.SupervisionError) as error:
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
    p.add_argument("--requirements", type=Path, help="confirmed requirements file to copy in")
    p.add_argument("--root", type=Path, default=None, help="repository root (default: cwd)")
    p.set_defaults(handler=cmd_init)

    p = sub.add_parser("plan", help="open the flight plan; --dispatch writes it via the planner role")
    p.add_argument("--dispatch", action="store_true", help="run the roster's planner to write the plan")
    p.add_argument("--prompt", action="store_true", help="print the planner prompt and exit")
    p.add_argument("--no-open", action="store_true")
    p.set_defaults(handler=cmd_plan)

    p = sub.add_parser("start", help="seed tasks from the plan and launch the driver")
    p.add_argument("--foreground", action="store_true", help="run in this terminal instead of detached")
    p.add_argument("--max-iterations", type=int, help="override the plan's iteration ceiling")
    p.set_defaults(handler=cmd_start)

    p = sub.add_parser("drive", help=argparse.SUPPRESS)
    p.add_argument("root", type=Path)
    p.add_argument("--max-iterations", type=int)
    p.set_defaults(handler=cmd_drive)

    p = sub.add_parser("status", help="how the flight is going")
    p.add_argument("--open", action="store_true", help="open the plan, or the wrap-up once landed")
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

    p = sub.add_parser("land", help="after landing: keep the record, remove the workspace, list follow-ups")
    p.add_argument("--no-open", action="store_true")
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
    branch = args.branch or f"autopilot/{_slug(args.goal)}"
    gitops.exclude(root, ".autopilot/")
    if gitops.is_dirty(root):
        raise StateError("the working tree is dirty; commit or stash before starting a flight")
    gitops.ensure_branch(root, branch)
    flight.create(args.goal.strip(), branch, gitops.head(root))
    if args.requirements:
        shutil.copyfile(args.requirements, flight.requirements_path)
    flight.event(f"flight created on {branch}")
    print(f"Flight created in {flight.dir} (untracked) on branch {branch}.")
    print("Next: write the plan (`autopilot plan --dispatch`, or dispatch the planner yourself), review it, then `autopilot start`.")
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    flight = _flight()
    if args.prompt:
        print(prompt.planner_prompt(flight))
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
            prompt.planner_prompt(flight),
            cwd=flight.root,
            log_path=log_path,
            timeout=flight.config["iteration_timeout"],
            environment=env,
        )
        flight.event(f"planner via {binding.label}: {outcome.exit_class} — {outcome.detail}")
        if outcome.exit_class != "ok":
            raise StateError(f"planner {outcome.exit_class}: {outcome.detail} (see {log_path})")
    if not flight.plan_path.exists():
        raise StateError(f"no plan at {flight.plan_path}; write one from the template or run with --dispatch")
    read_plan(flight.plan_path)
    if not args.no_open:
        _open_in_browser(flight.plan_path)
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    flight = _flight()
    if flight.data["status"] == "landed":
        raise StateError("this flight has landed; start a new flight for new work")
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


def _records_dir(root: Path) -> Path:
    base = os.environ.get("AUTOPILOT_RECORDS") or str(Path.home() / ".local" / "state" / "autopilot")
    return Path(base).expanduser() / root.name


def cmd_status(args: argparse.Namespace) -> int:
    try:
        flight = _flight()
    except StateError:
        records = _records_dir(Path(os.getcwd()).resolve())
        past = sorted(records.glob("*/wrap-up.html")) if records.is_dir() else []
        if not past:
            raise
        latest = past[-1]
        print(f"No flight in progress here. Last landed flight: {latest.parent.name}")
        print(f"Wrap-up: {latest}")
        if args.open:
            _open_in_browser(latest)
        return 0
    driver = supervise.read_status(flight.runtime_dir)
    if args.json:
        print(json.dumps({"flight": flight.data, "driver": driver.__dict__}, indent=2, sort_keys=True))
        return 0
    if args.open:
        target = flight.dir / "wrap-up.html" if flight.data["status"] == "landed" else flight.plan_path
        _open_in_browser(target)
    print(f"Goal:    {flight.data['goal']}")
    print(f"Branch:  {flight.data['branch']}")
    live = "alive" if driver.alive else "not running"
    print(f"Flight:  {flight.data['status']} · iteration {flight.data['iteration']}/{flight.config['max_iterations']} · driver {live} ({driver.reason})")
    print("Chunks:")
    for chunk in flight.chunks:
        tasks = flight.chunk_tasks(chunk["id"])
        done = sum(1 for task in tasks if task["status"] == "done")
        marker = "done" if chunk["status"] == "done" else f"{done}/{len(tasks)}"
        print(f"  {chunk['id']}. {chunk['title']} [{marker}]")
    active = [task for task in flight.tasks if task["status"] == "doing"]
    for task in active:
        print(f"Working: task {task['id']} — {task['title']}")
    open_escalations = flight.open_escalations()
    if open_escalations:
        print("Waiting on you:")
        for item in open_escalations:
            where = f"task {item['task']}: " if item["task"] is not None else ""
            print(f"  #{item['id']} {where}{item['text']}")
        print("  Answer with: autopilot answer <id> \"…\"")
    parked = flight.parked_tasks()
    if parked:
        print(f"Parked (follow-ups): {', '.join(str(task['id']) for task in parked)}")
    if flight.data["status"] == "landed":
        print(f"Wrap-up: {flight.dir / 'wrap-up.html'}  (autopilot status --open)")
    print("Recent events:")
    for line in flight.recent_events(8):
        print(f"  {line}")
    return 0


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
    stamp = flight.data.get("created", "")[:10].replace("-", "") or "flight"
    record = _records_dir(flight.root) / f"{_slug(flight.data['goal'])}-{stamp}"
    if record.exists():
        raise StateError(f"a record already exists at {record}; move it aside first")
    record.parent.mkdir(parents=True, exist_ok=True)
    follow_ups = flight.parked_tasks()
    shutil.move(str(flight.dir), str(record))
    print(f"Flight record kept at {record}")
    print(f"Branch {flight.data['branch']} is ready for review and merge; the wrap-up page is its front page.")
    if follow_ups:
        print("Follow-ups to file (on the operator's word), e.g. with the tasks skill:")
        for task in follow_ups:
            print(f"  tasks add \"{task['title']}\"")
    if not args.no_open:
        _open_in_browser(record / "wrap-up.html")
    return 0


def cmd_page(args: argparse.Namespace) -> int:
    source: Path = args.markdown
    try:
        body = source.read_text(encoding="utf-8")
    except OSError as error:
        raise StateError(f"cannot read {source}: {error}") from error
    title = args.title
    lines = body.splitlines()
    if not title:
        heading = next((line for line in lines if line.startswith("# ")), None)
        if heading:
            title = heading[2:].strip()
            body = "\n".join(line for line in lines if line is not heading)
        else:
            title = source.stem.replace("-", " ")
    out = args.out or source.with_suffix(".html")
    out.write_text(render.page(title, body), encoding="utf-8")
    print(f"Wrote {out}")
    if not args.no_open:
        _open_in_browser(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
