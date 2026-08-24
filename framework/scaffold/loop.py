"""The deterministic single-worker task loop."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Any, Protocol

from .adapters.base import DispatchResult
from .prompt import assemble_prompt
from .store import InvalidTransition, Store


class Adapter(Protocol):
    def dispatch(
        self,
        prompt: str,
        binding: Mapping[str, Any],
        sandbox: str,
        timeout: float,
    ) -> DispatchResult: ...


@dataclass(frozen=True)
class RunResult:
    """The mechanical outcome of one worker slice."""

    status: str
    completed_task_ids: tuple[str, ...]
    reason: str


def run_loop(
    store: Store,
    product_root: str | Path,
    adapter: Adapter,
    *,
    holder: str,
    profile: str | None = None,
    lease_seconds: float = 300,
    dispatch_timeout: float = 60,
    durable_paths: Sequence[str | Path] = (),
    binding_label: str = "worker",
) -> RunResult:
    """Pull and complete frontier tasks until done, blocked, or one failure."""

    product = Path(product_root).resolve()
    completed: list[str] = []
    segment = 0
    while True:
        state = store.load()
        if state["tasks"] and all(
            task["completion"] == "complete" and task["verdict"] == "green"
            for task in state["tasks"]
        ):
            return RunResult("complete", tuple(completed), "all tasks are green")

        frontier = store.ready(profile)
        if not frontier:
            any_frontier = store.ready(None)
            if any_frontier and profile is not None:
                return RunResult(
                    "no-compatible-work",
                    tuple(completed),
                    f"frontier has no task for profile {profile}",
                )
            return RunResult(
                "blocked",
                tuple(completed),
                "unfinished graph has no ready task",
            )

        task = frontier[0]
        segment += 1
        store.claim(task["id"], holder, ttl_seconds=lease_seconds)
        prompt = assemble_prompt(task, durable_paths)
        prompt_path = store.root / "prompts" / f"{task['id']}.txt"
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(prompt, encoding="utf-8")
        result = adapter.dispatch(
            prompt,
            {
                "task_id": task["id"],
                "holder": holder,
                "product_root": str(product),
            },
            "workspace-write",
            dispatch_timeout,
        )
        if result.exit_class != "success":
            store.apply(
                {
                    "type": "task-released",
                    "task_id": task["id"],
                    "holder": holder,
                    "attempt_type": "work",
                    "reason": result.exit_class,
                }
            )
            _event(
                store,
                f"segment {segment}: {task['id']} -> {binding_label}; worker "
                f"{result.exit_class}; slice ended",
            )
            return RunResult(
                "failed",
                tuple(completed),
                f"worker returned {result.exit_class} for {task['id']}",
            )

        try:
            claim = store.read_claim(task["id"])
            _verify_candidate_identity(product, claim["candidate_head"])
            store.apply(
                {
                    "type": "task-verified",
                    "task_id": task["id"],
                    "holder": holder,
                    "verified_head": claim["candidate_head"],
                    "verification": "candidate-is-clean-head",
                }
            )
        except (InvalidTransition, ValueError) as error:
            store.apply(
                {
                    "type": "task-released",
                    "task_id": task["id"],
                    "holder": holder,
                    "attempt_type": "work",
                    "reason": str(error),
                }
            )
            _event(
                store,
                f"segment {segment}: {task['id']} -> {binding_label}; "
                "candidate rejected; "
                "slice ended",
            )
            return RunResult("failed", tuple(completed), str(error))

        completed.append(task["id"])
        _event(
            store,
            f"segment {segment}: {task['id']} -> {binding_label}; flipped; "
            "verify candidate-is-clean-head",
        )


def _verify_candidate_identity(product_root: Path, candidate_head: str) -> None:
    """M1 boundary: establish immutable candidate identity; M2 judges artifacts."""

    head = _git(product_root, ["rev-parse", "HEAD"]).strip()
    if head != candidate_head:
        raise ValueError("filed candidate is not the product repository HEAD")
    _git(product_root, ["cat-file", "-e", f"{candidate_head}^{{commit}}"])
    if _git(product_root, ["status", "--porcelain"]).strip():
        raise ValueError("product worktree contains uncommitted worker changes")


def _git(root: Path, arguments: list[str]) -> str:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError(f"cannot inspect candidate commit: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ValueError(f"cannot inspect candidate commit: {detail}")
    return completed.stdout


def _event(store: Store, message: str) -> None:
    with (store.root / "events.log").open("a", encoding="utf-8") as handle:
        handle.write(message + "\n")
