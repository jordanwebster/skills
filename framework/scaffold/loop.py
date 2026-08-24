"""The deterministic single-worker task loop."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
from pathlib import Path
import subprocess
import time
from typing import Any, Callable, Protocol
import uuid

from .adapters.base import DispatchResult
from .judge import Judge, normalize_decision
from .prompt import assemble_prompt
from .store import InvalidTransition, Lease, Store
from .verify import verify


class Adapter(Protocol):
    def dispatch(
        self,
        prompt: str,
        binding: Mapping[str, Any],
        sandbox: str,
        timeout: float,
    ) -> DispatchResult: ...


class Lifecycle(Protocol):
    """Supervision callbacks around the worker-mutation boundary."""

    def task_started(
        self,
        task: Mapping[str, Any],
        lease: Any,
        base_head: str,
    ) -> None: ...

    def task_finished(self) -> None: ...

    def should_drain(self) -> bool: ...

    def claim_task(
        self,
        store: Store,
        task_id: str,
        holder: str,
        ttl_seconds: float,
    ) -> Lease | None: ...


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
    lifecycle: Lifecycle | None = None,
    judge: Judge | None = None,
    work_attempt_limit: int = 3,
    clock: Callable[[], float] | None = None,
    id_source: Callable[[], str] | None = None,
) -> RunResult:
    """Pull and complete frontier tasks until done, blocked, or one failure."""

    if isinstance(work_attempt_limit, bool) or not isinstance(
        work_attempt_limit, int
    ) or work_attempt_limit <= 0:
        raise ValueError("work_attempt_limit must be a positive integer")
    observed_time = clock or time.time
    next_id = id_source or (lambda: uuid.uuid4().hex)

    product = Path(product_root).resolve()
    completed: list[str] = []
    segment = 0
    while True:
        state = store.load()
        open_escalations = [
            item for item in state["outbox"] if item["status"] == "open"
        ]
        if not open_escalations and state["tasks"] and all(
            task["completion"] == "complete" and task["verdict"] == "green"
            for task in state["tasks"]
        ):
            return RunResult("complete", tuple(completed), "all tasks are green")
        if lifecycle is not None and lifecycle.should_drain():
            return RunResult(
                "drained",
                tuple(completed),
                "drain requested at a task boundary",
            )

        frontier = store.ready(profile)
        if not frontier:
            any_frontier = store.ready(None)
            if any_frontier and profile is not None:
                return RunResult(
                    "no-compatible-work",
                    tuple(completed),
                    f"frontier has no task for profile {profile}",
                )
            if open_escalations:
                return RunResult(
                    "awaiting-operator",
                    tuple(completed),
                    f"{len(open_escalations)} operator answer(s) are needed",
                )
            return RunResult(
                "blocked",
                tuple(completed),
                "unfinished graph has no ready task",
            )

        task = frontier[0]
        if task["attempts"]["work"] >= work_attempt_limit:
            return _route_judgment(
                store,
                task,
                trigger="retry-cap",
                failure=_latest_failure_reason(store, task["id"]),
                completed=completed,
                judge=judge,
                clock=observed_time,
                id_source=next_id,
            )
        segment += 1
        try:
            base_head = _git(product, ["rev-parse", "HEAD"]).strip()
            if _git(product, ["status", "--porcelain"]).strip():
                raise ValueError("product worktree is dirty before dispatch")
        except ValueError as error:
            return RunResult("broken", tuple(completed), str(error))
        verification_timeout = _verification_timeout(
            state, task, dispatch_timeout
        )
        claim_ttl = lease_seconds + dispatch_timeout
        if lifecycle is None:
            lease = store.claim(task["id"], holder, ttl_seconds=claim_ttl)
        else:
            lease = lifecycle.claim_task(
                store,
                task["id"],
                holder,
                claim_ttl,
            )
            if lease is None:
                return RunResult(
                    "drained",
                    tuple(completed),
                    "drain requested before the next task was leased",
                )
        if lifecycle is not None:
            lifecycle.task_started(task, lease, base_head)
        prompt = assemble_prompt(task, durable_paths)
        prompt_path = store.root / "prompts" / f"{task['id']}.txt"
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(prompt, encoding="utf-8")
        result = adapter.dispatch(
            prompt,
            {
                "task_id": task["id"],
                "role": task["role"],
                "effort": task["effort"],
                "holder": holder,
                "lease_id": lease.lease_id,
                "product_root": str(product),
                "base_head": base_head,
                "claim_reservation_seconds": (
                    lease_seconds + (2 * verification_timeout)
                ),
            },
            "read-only" if task["role"] == "reviewer" else "workspace-write",
            dispatch_timeout,
        )
        active_binding = result.binding_label or binding_label
        if result.exit_class != "success":
            try:
                _restore_product(product, base_head)
            except ValueError as error:
                return RunResult("broken", tuple(completed), str(error))
            attempt_type = (
                "diagnostic"
                if result.exit_class == "ambiguity"
                else (
                    "infra"
                    if result.exit_class in {"infra", "killed"}
                    else "work"
                )
            )
            released_state = store.apply(
                {
                    "type": "task-released",
                    "task_id": task["id"],
                    "holder": holder,
                    "lease_id": lease.lease_id,
                    "attempt_type": attempt_type,
                    "reason": result.failure_reason or result.exit_class,
                }
            )
            if lifecycle is not None:
                lifecycle.task_finished()
            _event(
                store,
                f"segment {segment}: {task['id']} -> {active_binding}; worker "
                f"{result.exit_class}; slice ended",
            )
            released_task = next(
                item
                for item in released_state["tasks"]
                if item["id"] == task["id"]
            )
            trigger = None
            if result.exit_class == "ambiguity":
                trigger = "ambiguity"
            else:
                if released_task["attempts"]["work"] >= work_attempt_limit:
                    trigger = "retry-cap"
            if trigger is not None:
                return _route_judgment(
                    store,
                    released_task,
                    trigger=trigger,
                    failure=result.failure_reason or result.exit_class,
                    completed=completed,
                    judge=judge,
                    clock=observed_time,
                    id_source=next_id,
                )
            return RunResult(
                "failed",
                tuple(completed),
                f"worker returned {result.exit_class} for {task['id']}",
            )

        try:
            claim = store.read_claim(task["id"])
        except (InvalidTransition, ValueError) as error:
            try:
                _restore_product(product, base_head)
            except ValueError as restore_error:
                return RunResult("broken", tuple(completed), str(restore_error))
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
            if lifecycle is not None:
                lifecycle.task_finished()
            _event(
                store,
                f"segment {segment}: {task['id']} -> {active_binding}; "
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
                timeout=verification_timeout,
                minimum_observations=_observation_floor(state, task),
                require_clean_worktree=True,
            )
        except Exception as error:
            try:
                _restore_product(product, base_head)
            except ValueError as restore_error:
                return RunResult("broken", tuple(completed), str(restore_error))
            _event(
                store,
                f"segment {segment}: {task['id']} -> {active_binding}; "
                "verification machinery malformed; line stopped",
            )
            return RunResult(
                "broken",
                tuple(completed),
                f"verification machinery malformed: {error}",
            )

        if verdict.kind in {"infra", "killed"}:
            try:
                _restore_product(product, base_head)
            except ValueError as error:
                return RunResult("broken", tuple(completed), str(error))
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
            if lifecycle is not None:
                lifecycle.task_finished()
            _event(
                store,
                f"segment {segment}: {task['id']} -> {active_binding}; "
                f"verify {verdict.kind}; slice ended",
            )
            return RunResult("failed", tuple(completed), verdict.reason)
        if verdict.kind == "malformed":
            try:
                _restore_product(product, base_head)
            except ValueError as error:
                return RunResult("broken", tuple(completed), str(error))
            _event(
                store,
                f"segment {segment}: {task['id']} -> {active_binding}; "
                "verification machinery malformed; line stopped",
            )
            return RunResult("broken", tuple(completed), verdict.reason)

        if verdict.kind == "red":
            try:
                _restore_product(product, base_head)
            except ValueError as error:
                return RunResult("broken", tuple(completed), str(error))

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
                f"segment {segment}: {task['id']} -> {active_binding}; "
                "verification artifact rejected; line stopped",
            )
            return RunResult(
                "broken",
                tuple(completed),
                f"verification machinery malformed: {error}",
            )

        if lifecycle is not None:
            lifecycle.task_finished()

        if verdict.kind == "red":
            _event(
                store,
                f"segment {segment}: {task['id']} -> {active_binding}; "
                "verify red; slice ended",
            )
            return RunResult("failed", tuple(completed), verdict.reason)

        completed.append(task["id"])
        _event(
            store,
            f"segment {segment}: {task['id']} -> {active_binding}; flipped; "
            "verify green",
        )


def _route_judgment(
    store: Store,
    task: Mapping[str, Any],
    *,
    trigger: str,
    failure: str,
    completed: list[str],
    judge: Judge | None,
    clock: Callable[[], float],
    id_source: Callable[[], str],
) -> RunResult:
    if trigger == "ambiguity":
        source = "framework-rule"
        decision = {
            "schema_version": 1,
            "task_id": task["id"],
            "trigger": trigger,
            "decision": "defer-to-operator",
            "reason": "The requirement is ambiguous, so another attempt is unsafe.",
        }
    else:
        try:
            if judge is None:
                raise ValueError("no judge is configured")
            decision = normalize_decision(
                judge.decide(task, trigger, failure),
                task_id=task["id"],
                trigger=trigger,
            )
            source = "judge"
        except Exception as error:
            source = "fallback"
            decision = {
                "schema_version": 1,
                "task_id": task["id"],
                "trigger": trigger,
                "decision": "defer-to-operator",
                "reason": f"The automatic decision was unavailable: {error}",
            }

    observed_at = float(clock())
    transition: dict[str, Any] = {
        "type": "task-judged",
        "task_id": task["id"],
        "source": source,
        "observed_at": observed_at,
        "decision": decision,
    }
    if decision["decision"] == "defer-to-operator":
        raw_id = id_source()
        if not isinstance(raw_id, str):
            raise ValueError("escalation id source must return text")
        escalation_id = "esc-" + raw_id.casefold()
        transition["escalation"] = {
            "id": escalation_id,
            "task_id": task["id"],
            "trigger": trigger,
            "blocked_on": (
                f"Work on {task['title']} stopped because {failure}."
            ),
            "proposed_action": (
                "Return the conflicting requirement for clarification and keep "
                "this work paused meanwhile."
                if trigger == "ambiguity"
                else "Return this work to planning for a revised approach and keep "
                "it paused until that revision is confirmed."
            ),
            "effect": (
                "This work stays paused; other independent work can continue."
            ),
            "request": "veto-or-confirm",
            "status": "open",
            "created_at": observed_at,
        }
    store.apply(transition)
    _event(
        store,
        f"{task['id']}: {trigger} -> {decision['decision']}; task parked",
    )
    if decision["decision"] == "defer-to-operator":
        return RunResult(
            "awaiting-operator",
            tuple(completed),
            f"operator answer needed for {task['title']}",
        )
    return RunResult(
        "parked",
        tuple(completed),
        f"{task['title']} was parked after {trigger}",
    )


def _latest_failure_reason(store: Store, task_id: str) -> str:
    for entry in reversed(store.read_journal()):
        transition = entry["transition"]
        if (
            transition.get("type") == "task-released"
            and transition.get("task_id") == task_id
        ):
            reason = transition.get("reason")
            if isinstance(reason, str) and reason:
                return reason
    return "the work attempt limit was reached"


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


def _restore_product(product_root: Path, base_head: str) -> None:
    _git(product_root, ["reset", "--hard", base_head])
    _git(product_root, ["clean", "-fd"])
    restored_head = _git(product_root, ["rev-parse", "HEAD"]).strip()
    if restored_head != base_head or _git(
        product_root, ["status", "--porcelain"]
    ).strip():
        raise ValueError("cannot restore product to its pre-dispatch commit")


def _event(store: Store, message: str) -> None:
    with (store.root / "events.log").open("a", encoding="utf-8") as handle:
        handle.write(message + "\n")
