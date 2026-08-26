"""The `tasks` command: find, file, edit, and close tracked work.

The command knows nothing about any tracker. It reads the operator's
config, tags every task with the repository it belongs to, and hands each
operation to a backend executable that speaks JSON on stdin and stdout.
Adding a tracker means adding one executable, not editing this file.
"""

from __future__ import annotations

import argparse
from difflib import SequenceMatcher
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib
from typing import Any


BACKENDS_DIR = Path(__file__).resolve().parent.parent.parent / "backends"
PROTOCOL_VERSION = 1

# A task's stage is its place in the lifecycle, orthogonal to open/closed:
# filed (an idea; inert), shaped (statement and requirements settled, not
# scheduled), ready (an agent may pick it up), doing (an agent has it).
STAGES = ("filed", "shaped", "ready", "doing")
WORKABLE = ("ready", "doing")


class TasksError(RuntimeError):
    def __init__(self, message: str, *, failure_class: str = "backend", recovery: str | None = None):
        super().__init__(message)
        self.failure_class = failure_class
        self.recovery = recovery or "Run `tasks doctor` for one actionable diagnosis."


# -- config ---------------------------------------------------------------------------


def config_path() -> Path:
    explicit = os.environ.get("TASKS_CONFIG")
    return Path(explicit).expanduser() if explicit else Path.home() / ".config" / "tasks" / "config.toml"


def load_config() -> dict[str, Any]:
    path = config_path()
    if not path.exists():
        return {"backend": {"provider": "local"}, "repos": {}}
    try:
        with path.open("rb") as handle:
            value = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise TasksError(
            f"cannot read {path}: {error}",
            failure_class="configuration",
            recovery=f"Correct {path}, then retry the tasks command.",
        ) from error
    if not isinstance(value, dict):
        raise TasksError(
            f"cannot read {path}: top level must be a table",
            failure_class="configuration",
            recovery=f"Correct {path}, then retry the tasks command.",
        )
    backend = value.setdefault("backend", {})
    repos = value.setdefault("repos", {})
    if not isinstance(backend, dict) or not isinstance(repos, dict):
        raise TasksError(
            f"cannot read {path}: backend and repos must be tables",
            failure_class="configuration",
            recovery=f"Correct {path}, then retry the tasks command.",
        )
    backend.setdefault("provider", "local")
    return value


def current_repo(config: dict[str, Any], explicit: str | None) -> str:
    if explicit:
        return explicit
    if os.environ.get("TASKS_REPO"):
        return os.environ["TASKS_REPO"]
    try:
        top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        top = os.getcwd()
    name = Path(top).name
    for repo, entry in config["repos"].items():
        path = entry.get("path") if isinstance(entry, dict) else None
        if path and Path(path).expanduser().resolve() == Path(top).resolve():
            return repo
    return name


# -- backend protocol -------------------------------------------------------------------


def backend_executable(provider: str) -> Path:
    name = f"tasks-backend-{provider}"
    bundled = BACKENDS_DIR / name
    if bundled.is_file() and os.access(bundled, os.X_OK):
        return bundled
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(directory) / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise TasksError(
        f"no backend named {provider!r}: expected {bundled} or {name} on PATH "
        f"(available: {', '.join(available_backends()) or 'none'})",
        failure_class="configuration",
        recovery="Choose an available backend in the tasks config, then retry.",
    )


def available_backends() -> list[str]:
    names: set[str] = set()
    for path in BACKENDS_DIR.glob("tasks-backend-*"):
        if os.access(path, os.X_OK):
            names.add(path.name.removeprefix("tasks-backend-"))
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        for path in Path(directory).glob("tasks-backend-*") if Path(directory).is_dir() else []:
            if os.access(path, os.X_OK):
                names.add(path.name.removeprefix("tasks-backend-"))
    return sorted(names)


def call(config: dict[str, Any], operation: str, **arguments: Any) -> Any:
    provider = config["backend"]["provider"]
    executable = backend_executable(provider)
    request = {
        "protocol": PROTOCOL_VERSION,
        "operation": operation,
        "config": config["backend"],
        "args": arguments,
    }
    try:
        completed = subprocess.run(
            [str(executable), operation],
            input=json.dumps(request),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise TasksError(f"backend {provider} timed out on {operation}") from error
    except OSError as error:
        raise TasksError(f"cannot launch backend {provider} for {operation}: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "no detail"
        raise TasksError(f"backend {provider} failed on {operation}: {detail}")
    try:
        response = json.loads(completed.stdout or "null")
    except json.JSONDecodeError as error:
        raise TasksError(f"backend {provider} returned invalid JSON for {operation}") from error
    if isinstance(response, dict) and "error" in response:
        raise TasksError(f"backend {provider}: {response['error']}")
    return response


# -- commands -------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args) or 0
    except TasksError as error:
        if getattr(args, "json", False):
            print(json.dumps({
                "ok": False,
                "error": {
                    "class": error.failure_class,
                    "message": str(error),
                    "recovery": error.recovery,
                },
            }, indent=2, sort_keys=True))
        else:
            print(f"tasks: {error}", file=sys.stderr)
            print(f"Recovery: {error.recovery}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tasks", description="Find, file, edit, and close tracked work.")
    parser.add_argument("--repo", help="repository the task belongs to (default: the current one)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    # The same two options are accepted after the verb, where agents
    # naturally put them; SUPPRESS keeps a value given before the verb.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", default=argparse.SUPPRESS)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list", parents=[common], help="workable tasks for this repository (ready and doing)")
    p.add_argument("--all-repos", action="store_true")
    p.add_argument("--stage", choices=(*STAGES, "all"), help="one stage, or all open stages")
    p.add_argument("--state", choices=("open", "closed", "all"), default="open")
    p.add_argument("--label", action="append", default=[])
    p.add_argument("--search", help="text to match in titles and bodies")
    p.set_defaults(handler=cmd_list)

    p = sub.add_parser("show", parents=[common], help="one task in full")
    p.add_argument("id")
    p.set_defaults(handler=cmd_show)

    p = sub.add_parser("add", parents=[common], help="file a task at stage filed (a same-titled open task is returned instead)")
    p.add_argument("title")
    p.add_argument("--body", default="")
    p.add_argument("--label", action="append", default=[])
    p.set_defaults(handler=cmd_add)

    p = sub.add_parser("shape", parents=[common], help="settle a task's statement and requirements; stage becomes shaped")
    p.add_argument("id")
    p.add_argument("--title")
    p.add_argument("--body", help="the settled statement and requirements (replaces the body)")
    p.add_argument("--append", help="text to append to the body instead of replacing it")
    p.set_defaults(handler=cmd_shape)

    p = sub.add_parser("ready", parents=[common], help="on the operator's word: an agent may pick this up now")
    p.add_argument("id")
    p.set_defaults(handler=cmd_ready)

    p = sub.add_parser("start", parents=[common], help="an agent has taken the task")
    p.add_argument("id")
    p.set_defaults(handler=cmd_start)

    p = sub.add_parser("stage", parents=[common], help="set a task's stage directly")
    p.add_argument("id")
    p.add_argument("stage", choices=STAGES)
    p.set_defaults(handler=cmd_stage)

    p = sub.add_parser("edit", parents=[common], help="change a task's title, body, or labels")
    p.add_argument("id")
    p.add_argument("--title")
    p.add_argument("--body")
    p.add_argument("--add-label", action="append", default=[])
    p.add_argument("--remove-label", action="append", default=[])
    p.set_defaults(handler=cmd_edit)

    p = sub.add_parser("close", parents=[common], help="mark a task done (or --cancel)")
    p.add_argument("id")
    p.add_argument("--reason", default="")
    p.add_argument("--cancel", action="store_true")
    p.set_defaults(handler=cmd_close)

    p = sub.add_parser("reopen", parents=[common], help="put a closed task back")
    p.add_argument("id")
    p.set_defaults(handler=cmd_reopen)

    p = sub.add_parser("backends", parents=[common], help="backends this install can use")
    p.set_defaults(handler=cmd_backends)

    p = sub.add_parser("doctor", parents=[common], help="diagnose configuration and backend access")
    p.set_defaults(handler=cmd_doctor)
    return parser


def _emit(args: argparse.Namespace, value: Any, text: str) -> None:
    if args.json:
        print(json.dumps(value, indent=2, sort_keys=True))
    else:
        print(text)


def _line(task: dict[str, Any]) -> str:
    labels = " ".join(f"[{label}]" for label in task.get("labels", []) if not label.startswith("repo:"))
    state = task.get("stage", "filed") if task.get("state") == "open" else task.get("state")
    return f"{task['id']:<10} {state:<7} {task['title']} {labels}".rstrip()


def _detail(task: dict[str, Any]) -> str:
    lines = [
        f"{task['id']}  {task['title']}",
        f"state: {task.get('state')}  stage: {task.get('stage', 'filed')}  repo: {task.get('repo', '')}",
    ]
    if task.get("labels"):
        lines.append("labels: " + ", ".join(task["labels"]))
    if task.get("url"):
        lines.append(f"url: {task['url']}")
    if task.get("body"):
        lines += ["", task["body"].rstrip()]
    return "\n".join(lines)


def cmd_list(args: argparse.Namespace) -> int:
    config = load_config()
    repo = None if args.all_repos else current_repo(config, args.repo)
    if args.stage == "all" or args.state != "open":
        stages: list[str] = []
    elif args.stage:
        stages = [args.stage]
    else:
        stages = list(WORKABLE)
    every = call(config, "list", repo=repo, state=args.state, stages=[], labels=args.label, search=args.search)
    tasks = [task for task in every if not stages or task.get("stage", "filed") in stages]
    text = "\n".join(_line(task) for task in tasks)
    counts = {stage: sum(1 for task in every if task.get("stage", "filed") == stage) for stage in STAGES}
    if stages == list(WORKABLE):
        # The default view hides the backlog; say how much is hidden so it
        # is discoverable without a flag the operator has to remember.
        hidden = [task for task in every if task.get("stage", "filed") not in WORKABLE]
        text = text or "No tasks ready or doing."
        if hidden:
            hidden_counts = {stage: counts[stage] for stage in STAGES if stage not in WORKABLE}
            text += "\nAlso open: " + ", ".join(f"{count} {stage}" for stage, count in hidden_counts.items() if count)
            text += "  (tasks list --stage " + "|".join(stage for stage, count in hidden_counts.items() if count) + ")"
    if not args.json:
        lifecycle = "  ".join(f"{stage} {counts[stage]}" for stage in STAGES)
        text = (text or "No tasks.") + f"\nLifecycle: {lifecycle}"
    _emit(args, tasks, text or "No tasks.")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    config = load_config()
    task = call(config, "get", id=args.id)
    _emit(args, task, _detail(task))
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    config = load_config()
    repo = current_repo(config, args.repo)
    labels = list(dict.fromkeys(args.label))
    existing = call(config, "list", repo=repo, state="open", stages=[], labels=[], search="")
    duplicate = next((task for task in existing if task["title"].strip().casefold() == args.title.strip().casefold()), None)
    if duplicate:
        result = dict(duplicate, already_exists=True, near_duplicates=[])
        _emit(args, result, f"Already filed: {_line(duplicate)}")
        return 0
    wanted = " ".join(args.title.casefold().split())
    near = [
        task for task in existing
        if SequenceMatcher(None, wanted, " ".join(task["title"].casefold().split())).ratio() >= 0.72
    ][:3]
    task = call(config, "create", repo=repo, title=args.title, body=args.body, labels=labels, stage="filed")
    result = dict(task, already_exists=False, near_duplicates=[
        {"id": item["id"], "title": item["title"], "stage": item.get("stage", "filed")}
        for item in near
    ])
    text = f"Filed: {_line(task)}"
    if near:
        text += "\nPossible duplicate: " + "; ".join(f"{item['id']} {item['title']}" for item in near)
    _emit(args, result, text)
    return 0


def cmd_edit(args: argparse.Namespace) -> int:
    config = load_config()
    task = call(
        config,
        "update",
        id=args.id,
        title=args.title,
        body=args.body,
        add_labels=args.add_label,
        remove_labels=args.remove_label,
    )
    _emit(args, task, f"Updated: {_line(task)}")
    return 0


def cmd_close(args: argparse.Namespace) -> int:
    config = load_config()
    task = call(config, "close", id=args.id, reason=args.reason, cancel=args.cancel)
    _emit(args, task, f"{'Canceled' if args.cancel else 'Closed'}: {_line(task)}")
    return 0


def cmd_reopen(args: argparse.Namespace) -> int:
    config = load_config()
    task = call(config, "update", id=args.id, state="open", stage="filed")
    _emit(args, task, f"Reopened: {_line(task)}")
    return 0


def cmd_shape(args: argparse.Namespace) -> int:
    config = load_config()
    body = args.body
    if args.append:
        current = call(config, "get", id=args.id)
        body = (current.get("body", "").rstrip() + "\n\n" + args.append).strip()
    task = call(config, "update", id=args.id, title=args.title, body=body, stage="shaped")
    _emit(args, task, f"Shaped: {_line(task)}")
    return 0


def cmd_ready(args: argparse.Namespace) -> int:
    config = load_config()
    task = call(config, "update", id=args.id, stage="ready")
    _emit(args, task, f"Ready: {_line(task)}")
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    config = load_config()
    task = call(config, "update", id=args.id, stage="doing")
    _emit(args, task, f"Started: {_line(task)}")
    return 0


def cmd_stage(args: argparse.Namespace) -> int:
    config = load_config()
    task = call(config, "update", id=args.id, stage=args.stage)
    _emit(args, task, f"Stage {args.stage}: {_line(task)}")
    return 0


def cmd_backends(args: argparse.Namespace) -> int:
    config = load_config()
    names = available_backends()
    current = config["backend"]["provider"]
    _emit(args, {"available": names, "configured": current}, "\n".join(
        f"{name}{'  (configured)' if name == current else ''}" for name in names
    ) or "No backends found.")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    config = load_config()
    provider = config["backend"]["provider"]
    executable = backend_executable(provider)
    repo = current_repo(config, args.repo)
    backend = call(config, "doctor", repo=repo)
    if not isinstance(backend, dict):
        raise TasksError(f"backend {provider} returned an invalid doctor result")
    result = {
        "ok": True,
        "config": {"path": str(config_path()), "exists": config_path().exists()},
        "backend": {
            "provider": provider,
            "executable": str(executable),
            "reachable": bool(backend.get("reachable")),
            "authenticated": bool(backend.get("authenticated")),
            "detail": backend.get("detail", ""),
        },
        "repository": {"name": repo, "label": f"repo:{repo}"},
        "next_action": "No action needed; tasks is ready.",
    }
    text = (
        f"Tasks ready: {provider} ({executable})\n"
        f"Config: {result['config']['path']} ({'present' if result['config']['exists'] else 'defaults'})\n"
        f"Repository: {repo}  label: repo:{repo}\n"
        f"Next: {result['next_action']}"
    )
    _emit(args, result, text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
