"""Command-line entry point for the scaffold framework."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import uuid

from . import __version__
from .adapters.fake import FakeAdapter
from .adapters.judge import RosterJudge
from .adapters.planner import RosterPlanner
from .adapters.roster import RosterAdapter, RosterError
from .loop import run_loop
from .plan import import_plan, retained_plan_path
from .store import InvalidTransition, Store, StoreCorruption, initial_state
from .supervise import (
    DriverBusy,
    StopSignal,
    SupervisionError,
    Supervisor,
    install_stop_signal_handlers,
    read_status,
    request_drain,
    restore_signal_handlers,
    start_detached,
    stop_driver,
)


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="scaffold",
        description="Run deterministic, file-backed build flights.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)

    init_parser = commands.add_parser("init", help="create a flight workspace")
    init_parser.add_argument("--repo", type=Path, default=Path.cwd())
    init_parser.add_argument("--goal", required=True)
    init_parser.add_argument("--slug")

    import_parser = commands.add_parser(
        "plan-import", help="import the plan's canonical JSON block"
    )
    import_parser.add_argument("workspace", type=Path)
    import_parser.add_argument("plan", type=Path)

    run_parser = commands.add_parser("run", help="run one foreground worker slice")
    _add_run_arguments(run_parser)
    run_parser.add_argument("--run-id", help=argparse.SUPPRESS)
    run_parser.add_argument(
        "--supervised-child",
        action="store_true",
        help=argparse.SUPPRESS,
    )

    start_parser = commands.add_parser(
        "start", help="start a detached supervised worker slice"
    )
    _add_run_arguments(start_parser)
    start_parser.add_argument("--launch-timeout", type=float, default=5.0)

    status_parser = commands.add_parser("status", help="read driver liveness")
    status_parser.add_argument("workspace", type=Path)
    status_parser.add_argument("--stale-after", type=float, default=10.0)

    drain_parser = commands.add_parser(
        "drain", help="finish the active task, then stop"
    )
    drain_parser.add_argument("workspace", type=Path)

    stop_parser = commands.add_parser(
        "stop", help="stop the active driver process group"
    )
    stop_parser.add_argument("workspace", type=Path)
    stop_parser.add_argument("--timeout", type=float, default=5.0)

    bless_parser = commands.add_parser(
        "bless", help="record explicit acceptance of the presented subject"
    )
    bless_parser.add_argument("workspace", type=Path)
    bless_parser.add_argument(
        "--accept",
        metavar="SUBJECT",
        help="exact blessing subject shown by the ready flight",
    )

    parsed = parser.parse_args(arguments)
    if parsed.command == "init":
        return _init(parsed.repo, parsed.goal, parsed.slug)
    if parsed.command == "plan-import":
        plan = import_plan(Store(parsed.workspace), parsed.plan)
        print(f"imported {len(plan.tasks)} tasks from canonical plan block")
        return 0
    if parsed.command == "run":
        return _run(parsed)
    if parsed.command == "start":
        return _start(parsed)
    if parsed.command == "status":
        status = read_status(parsed.workspace, stale_after=parsed.stale_after)
        print(f"{status.state}: {status.reason}")
        return 0
    if parsed.command == "drain":
        try:
            request_drain(parsed.workspace)
        except SupervisionError as error:
            print(f"cannot drain: {error}")
            return 1
        print("drain requested: the driver will stop after its active task")
        return 0
    if parsed.command == "stop":
        try:
            stop_driver(parsed.workspace, timeout=parsed.timeout)
        except SupervisionError as error:
            print(f"cannot stop: {error}")
            return 1
        print("stopped: the driver process group released its flight lock")
        return 0
    if parsed.command == "bless":
        return _bless(parsed.workspace, parsed.accept)
    parser.error(f"unknown command: {parsed.command}")


def _add_run_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--adapter", choices=("fake", "roster"), required=True)
    parser.add_argument("--script", type=Path)
    parser.add_argument("--roster", type=Path)
    parser.add_argument("--product", type=Path)
    parser.add_argument("--holder", default="fake-worker")
    parser.add_argument("--profile")


def _init(repo: Path, goal: str, requested_slug: str | None) -> int:
    product_root = repo.resolve()
    slug = requested_slug or _slugify(goal)
    if not re.fullmatch(r"[a-z0-9-]+", slug):
        raise ValueError("flight slug must contain only lowercase letters, digits, hyphens")
    _exclude_scaffolding(product_root)
    workspace = product_root / ".scaffolding" / slug
    store = Store(workspace)
    config = {
        "schema_version": 1,
        "product_root": str(product_root),
        "title": goal,
    }
    if store.state_path.exists() or store.journal_path.exists():
        state = store.load()
        if state["goal"] != goal:
            raise ValueError("existing workspace belongs to a different goal")
        _restore_or_validate_config(workspace / "config.json", config)
        print(workspace)
        return 0
    store.create(initial_state(goal))
    _atomic_write_json(workspace / "config.json", config)
    print(workspace)
    return 0


def _run(parsed: argparse.Namespace) -> int:
    workspace = parsed.workspace.resolve()
    store = Store(workspace)
    if parsed.product is None:
        config = json.loads(
            (workspace / "config.json").read_text(encoding="utf-8")
        )
        product = Path(config["product_root"]).resolve()
    else:
        product = parsed.product.resolve()
    try:
        if parsed.adapter == "fake":
            if parsed.script is None:
                raise ValueError("the fake adapter requires --script")
            adapter = FakeAdapter(parsed.script, store)
            judge = None
            planner = None
        else:
            if parsed.script is not None:
                raise ValueError("the roster adapter does not accept --script")
            adapter = RosterAdapter(store, parsed.roster)
            judge = RosterJudge(store, adapter.roster)
            planner = RosterPlanner(store, adapter.roster)
    except (RosterError, ValueError) as error:
        print(f"cannot run: {error}")
        return 1
    plan_path = retained_plan_path(store)
    runtime = Supervisor(
        workspace,
        product,
        run_id=getattr(parsed, "run_id", None),
        isolate_process_group=True,
    )
    try:
        with runtime:
            previous_handlers = install_stop_signal_handlers()
            try:
                runtime.recover(store)
                result = run_loop(
                    store,
                    product,
                    adapter,
                    holder=parsed.holder,
                    profile=parsed.profile,
                    durable_paths=(plan_path,),
                    binding_label=parsed.adapter,
                    lifecycle=runtime,
                    judge=judge,
                    planner=planner,
                )
            except StopSignal:
                runtime.finish("stopped", "driver was stopped")
                print("stopped: driver was stopped during its active task")
                return 1
            finally:
                restore_signal_handlers(previous_handlers)
            terminal_state = {
                "complete": "complete",
                "drained": "drained",
                "blocked": "paused",
                "no-compatible-work": "paused",
                "awaiting-operator": "paused",
                "parked": "paused",
            }.get(result.status, "failed")
            runtime.finish(terminal_state, result.reason)
    except (DriverBusy, SupervisionError) as error:
        print(f"cannot run: {error}")
        return 1
    print(f"{result.status}: {result.reason}")
    return 0 if result.status in {"complete", "drained"} else 1


def _start(parsed: argparse.Namespace) -> int:
    workspace = parsed.workspace.resolve()
    run_id = uuid.uuid4().hex
    command = [
        sys.executable,
        "-m",
        "scaffold",
        "run",
        str(workspace),
        "--adapter",
        parsed.adapter,
        "--holder",
        parsed.holder,
        "--run-id",
        run_id,
        "--supervised-child",
    ]
    if parsed.script is not None:
        command.extend(("--script", str(parsed.script.resolve())))
    if parsed.roster is not None:
        command.extend(("--roster", str(parsed.roster.resolve())))
    if parsed.product is not None:
        command.extend(("--product", str(parsed.product.resolve())))
    if parsed.profile is not None:
        command.extend(("--profile", parsed.profile))
    try:
        pid = start_detached(
            command,
            workspace,
            run_id,
            launch_timeout=parsed.launch_timeout,
            environment=os.environ.copy(),
        )
    except (OSError, SupervisionError) as error:
        print(f"cannot start: {error}")
        return 1
    print(f"started: driver {pid} is detached; you can close this shell")
    return 0


def _bless(workspace: Path, accepted_subject: str | None) -> int:
    if accepted_subject is None:
        print("not accepted: explicit --accept SUBJECT is required")
        return 1
    store = Store(workspace.resolve())
    try:
        state = store.apply(
            {
                "type": "flight-blessed",
                "subject": accepted_subject,
                "accepted_at": time.time(),
            }
        )
    except (InvalidTransition, StoreCorruption, ValueError) as error:
        print(f"not accepted: {error}")
        return 1
    print(
        "accepted: graduated "
        f"{len(state['blessed_demonstrations'])} demonstration(s) at "
        f"{state['presented_head']}"
    )
    return 0


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not slug:
        raise ValueError("goal must contain a letter or digit for its workspace slug")
    return slug


def _exclude_scaffolding(product_root: Path) -> None:
    completed = subprocess.run(
        ["git", "rev-parse", "--git-path", "info/exclude"],
        cwd=product_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ValueError(f"init requires a product Git repository: {detail}")
    exclude_path = Path(completed.stdout.strip())
    if not exclude_path.is_absolute():
        exclude_path = product_root / exclude_path
    exclude_path.parent.mkdir(parents=True, exist_ok=True)
    existing = (
        exclude_path.read_text(encoding="utf-8").splitlines()
        if exclude_path.exists()
        else []
    )
    if ".scaffolding/" not in existing:
        with exclude_path.open("a", encoding="utf-8") as handle:
            if existing and exclude_path.stat().st_size > 0:
                handle.write("\n")
            handle.write(".scaffolding/\n")


def _restore_or_validate_config(path: Path, expected: dict[str, object]) -> None:
    if not path.exists():
        _atomic_write_json(path, expected)
        return
    try:
        observed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"existing workspace config is invalid: {error}") from error
    if observed != expected:
        raise ValueError("existing workspace config does not match this init request")


def _atomic_write_json(path: Path, value: dict[str, object]) -> None:
    payload = (
        json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
