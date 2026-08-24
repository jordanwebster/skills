"""Command-line entry point for the scaffold framework."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from . import __version__
from .adapters.fake import FakeAdapter
from .loop import run_loop
from .plan import import_plan, retained_plan_path
from .store import Store, initial_state


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
    run_parser.add_argument("workspace", type=Path)
    run_parser.add_argument("--adapter", choices=("fake",), required=True)
    run_parser.add_argument("--script", type=Path, required=True)
    run_parser.add_argument("--product", type=Path)
    run_parser.add_argument("--holder", default="fake-worker")
    run_parser.add_argument("--profile")

    parsed = parser.parse_args(arguments)
    if parsed.command == "init":
        return _init(parsed.repo, parsed.goal, parsed.slug)
    if parsed.command == "plan-import":
        plan = import_plan(Store(parsed.workspace), parsed.plan)
        print(f"imported {len(plan.tasks)} tasks from canonical plan block")
        return 0
    if parsed.command == "run":
        return _run(parsed)
    parser.error(f"unknown command: {parsed.command}")


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
    store = Store(parsed.workspace)
    if parsed.product is None:
        config = json.loads(
            (parsed.workspace / "config.json").read_text(encoding="utf-8")
        )
        product = Path(config["product_root"])
    else:
        product = parsed.product
    adapter = FakeAdapter(parsed.script, store)
    plan_path = retained_plan_path(store)
    result = run_loop(
        store,
        product,
        adapter,
        holder=parsed.holder,
        profile=parsed.profile,
        durable_paths=(plan_path,),
        binding_label=parsed.adapter,
    )
    print(f"{result.status}: {result.reason}")
    return 0 if result.status == "complete" else 1


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
