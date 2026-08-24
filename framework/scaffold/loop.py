"""The deterministic single-worker task loop."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
from pathlib import Path
import subprocess
from typing import Any, Protocol

from .adapters.base import DispatchResult
from .prompt import assemble_prompt
from .store import InvalidTransition, Store
from .verify import verify


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
        try:
            base_head = _git(product, ["rev-parse", "HEAD"]).strip()
            if _git(product, ["status", "--porcelain"]).strip():
                raise ValueError("product worktree is dirty before dispatch")
        except ValueError as error:
            return RunResult("broken", tuple(completed), str(error))
        lease = store.claim(task["id"], holder, ttl_seconds=lease_seconds)
        prompt = assemble_prompt(task, durable_paths)
        prompt_path = store.root / "prompts" / f"{task['id']}.txt"
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(prompt, encoding="utf-8")
        result = adapter.dispatch(
            prompt,
            {
                "task_id": task["id"],
                "holder": holder,
                "lease_id": lease.lease_id,
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
                    "lease_id": lease.lease_id,
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
        except (InvalidTransition, ValueError) as error:
            store.apply(
                {
                    "type": "task-released",
                    "task_id": task["id"],
                    "holder": holder,
                    "lease_id": lease.lease_id,
                    "attempt_type": "work",
                    "reason": str(error),
                }
            )
            _event(
                store,
                f"segment {segment}: {task['id']} -> {binding_label}; "
                "claim rejected; slice ended",
            )
            return RunResult("failed", tuple(completed), str(error))

        try:
            verdict = verify(
                task,
                product,
                store.root,
                holder=holder,
                lease_id=lease.lease_id,
                base_head=base_head,
                candidate_head=claim["candidate_head"],
                test_paths=state["test_paths"],
                timeout=_verification_timeout(state, task, dispatch_timeout),
                minimum_observations=_observation_floor(state, task),
                require_clean_worktree=True,
            )
        except Exception as error:
            _event(
                store,
                f"segment {segment}: {task['id']} -> {binding_label}; "
                "verification machinery malformed; line stopped",
            )
            return RunResult(
                "broken",
                tuple(completed),
                f"verification machinery malformed: {error}",
            )

        if verdict.kind in {"infra", "killed"}:
            store.apply(
                {
                    "type": "task-released",
                    "task_id": task["id"],
                    "holder": holder,
                    "lease_id": lease.lease_id,
                    "attempt_type": "infra",
                    "reason": verdict.reason,
                }
            )
            _event(
                store,
                f"segment {segment}: {task['id']} -> {binding_label}; "
                f"verify {verdict.kind}; slice ended",
            )
            return RunResult("failed", tuple(completed), verdict.reason)
        if verdict.kind == "malformed":
            _event(
                store,
                f"segment {segment}: {task['id']} -> {binding_label}; "
                "verification machinery malformed; line stopped",
            )
            return RunResult("broken", tuple(completed), verdict.reason)

        try:
            store.apply(
                {
                    "type": "task-verification-recorded",
                    "task_id": task["id"],
                    "holder": holder,
                    "lease_id": lease.lease_id,
                    "verification_path": str(
                        verdict.artifact_path.relative_to(store.root.resolve())
                    ),
                    "verification_sha256": verdict.artifact_sha256,
                }
            )
        except (InvalidTransition, ValueError) as error:
            _event(
                store,
                f"segment {segment}: {task['id']} -> {binding_label}; "
                "verification artifact rejected; line stopped",
            )
            return RunResult(
                "broken",
                tuple(completed),
                f"verification machinery malformed: {error}",
            )

        if verdict.kind == "red":
            _event(
                store,
                f"segment {segment}: {task['id']} -> {binding_label}; "
                "verify red; slice ended",
            )
            return RunResult("failed", tuple(completed), verdict.reason)

        completed.append(task["id"])
        _event(
            store,
            f"segment {segment}: {task['id']} -> {binding_label}; flipped; "
            "verify green",
        )


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


def _observation_floor(
    state: Mapping[str, Any], task: Mapping[str, Any]
) -> int:
    check_id = hashlib.sha256(task["check"].encode("utf-8")).hexdigest()
    counts = [
        evidence.get("observation_count", 0)
        for item in state["tasks"]
        for evidence in item["evidence"]
        if evidence.get("check_id") == check_id
        and isinstance(evidence.get("observation_count"), int)
    ]
    return max(counts, default=0)


def _verification_timeout(
    state: Mapping[str, Any], task: Mapping[str, Any], bootstrap: float
) -> float:
    check_id = hashlib.sha256(task["check"].encode("utf-8")).hexdigest()
    durations = [
        evidence.get("duration_seconds")
        for item in state["tasks"]
        for evidence in item["evidence"]
        if evidence.get("check_id") == check_id
        and isinstance(evidence.get("duration_seconds"), (int, float))
        and not isinstance(evidence.get("duration_seconds"), bool)
        and evidence["duration_seconds"] > 0
    ]
    if not durations:
        return bootstrap
    return max(durations) * 4


def _event(store: Store, message: str) -> None:
    with (store.root / "events.log").open("a", encoding="utf-8") as handle:
        handle.write(message + "\n")
