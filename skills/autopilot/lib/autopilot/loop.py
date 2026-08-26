"""The flight loop: pick ready work, dispatch a fresh agent, confirm, repeat.

Three levels of "done" live here. A task is done when the agent says so and
its check (if any) passes. A chunk is done when its tasks are done, its
verification passes, and one review round has run. The flight is done when
every chunk is done, the whole-flight verification passes, and the closer
finds no gap against the requirements.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import time
from typing import Any

from . import dispatch, gitops, prompt, render
from .notify import notify
from .roster import Roster
from .state import Flight
from .supervise import StopSignal, Supervisor


# Consecutive provider failures before the driver pauses, and how long it
# waits each time. Quota windows reset on the order of hours; polling more
# often than this burns nothing but gains nothing either.
INFRA_STREAK_TO_PAUSE = 3
INFRA_WAIT_SECONDS = 900
INFRA_MAX_WAITS = 8


class FlightEnded(Exception):
    """Raised by `_end` so any depth of the loop can finish the flight cleanly."""

    def __init__(self, status: str):
        super().__init__(status)
        self.status = status


class Driver:
    def __init__(
        self,
        flight: Flight,
        roster: Roster,
        *,
        supervisor: Supervisor | None = None,
        max_iterations: int | None = None,
        environment: dict[str, str] | None = None,
    ):
        self.flight = flight
        self.roster = roster
        self.supervisor = supervisor
        self.max_iterations = max_iterations
        self.environment = environment
        self.infra_streak = 0
        self.infra_waits = 0

    # -- entry point -------------------------------------------------------------

    def run(self) -> str:
        flight = self.flight
        root = flight.root
        gitops.ensure_branch(root, flight.data["branch"])
        gitops.exclude(root, ".autopilot/")
        self._recover()
        flight.data["status"] = "running"
        flight.save()
        try:
            self._loop()
        except FlightEnded as ended:
            return ended.status
        except StopSignal:
            return self._finish("stopped", "driver was stopped")
        raise AssertionError("the loop only exits through FlightEnded")

    def _loop(self) -> None:
        flight = self.flight
        while True:
            if self.supervisor is not None and self.supervisor.drain_requested():
                self._end("stopped", "drained after the current iteration")
            limit = self.max_iterations or flight.config["max_iterations"]
            if flight.data["iteration"] >= limit:
                self._end(
                    "exhausted",
                    f"reached the iteration ceiling ({limit}); raise max_iterations to continue",
                )
            capped = [
                task
                for task in flight.tasks
                if task["status"] == "todo" and task["attempts"] >= flight.config["retry_cap"]
            ]
            if capped:
                self._replan(
                    capped[0],
                    f"Task {capped[0]['id']} has been attempted {capped[0]['attempts']} times "
                    f"without completing. Another attempt is not an option.",
                )
                continue
            task = flight.next_task()
            if task is not None:
                self._iterate(task)
                continue
            chunk = next(
                (item for item in flight.chunks if item["status"] == "open" and flight.chunk_complete(item)),
                None,
            )
            if chunk is not None:
                self._complete_chunk(chunk)
                continue
            if flight.open_escalations():
                self._end("escalated", "waiting on the operator")
            if all(item["status"] == "done" for item in flight.chunks):
                self._close_flight()
                continue
            flight.add_escalation(
                None,
                "No task is ready and no chunk can complete. Something depends on a parked "
                "or blocked task; decide whether to unpark, answer, or land as-is.",
            )
            self._end("escalated", "no ready work")

    # -- one iteration -------------------------------------------------------------

    def _iterate(self, task: dict[str, Any]) -> None:
        """Dispatch one agent on `task` and its siblings, then confirm what it claimed."""

        flight = self.flight
        role = flight.task_role(task)
        chunk = flight.chunk(task["chunk"])
        if chunk.get("base") is None:
            chunk["base"] = gitops.head(flight.root)
        ready = flight.ready_tasks(role=role, chunk=chunk["id"])
        before = {item["id"]: (item["status"], item["attempts"]) for item in flight.tasks}
        text = prompt.worker_prompt(flight, role, chunk, ready)
        outcome = self._dispatch(
            role,
            text,
            effort=flight.task_effort(task),
            summary=f"task {task['id']} ({', '.join(str(item['id']) for item in ready[:6])})",
            extra_env={"AUTOPILOT_CHUNK": str(chunk["id"])},
        )
        flight.load()
        if outcome.exit_class == dispatch.EXIT_INFRA:
            self._infra(outcome)
            return
        self.infra_streak = 0
        iteration = flight.data["iteration"]
        for item in flight.tasks:
            if item["status"] == "doing":
                flight.set_status(item, "todo")
                item["attempts"] += 1
                flight.note(item, f"Iteration {iteration} ended with this task still in progress ({outcome.detail}).")
                flight.event(f"iteration {iteration}: task {item['id']} left in progress")
            elif item["status"] == "done" and not item["commit"]:
                self._confirm(item, iteration)
        selected = flight.task(task["id"])
        if selected["status"] == "todo" and before.get(task["id"]) == (selected["status"], selected["attempts"]):
            selected["attempts"] += 1
            flight.note(selected, f"Iteration {iteration} made no progress on this task ({outcome.detail}).")
            flight.event(f"iteration {iteration}: no progress on task {task['id']}")
        flight.save()
        self._commit_leftovers(f"WIP: {task['title']}")

    def _confirm(self, task: dict[str, Any], iteration: int) -> None:
        flight = self.flight
        if task.get("check"):
            passed, output = dispatch.run_check(
                task["check"], cwd=flight.root, timeout=flight.config["check_timeout"]
            )
            if not passed:
                flight.set_status(task, "todo")
                task["attempts"] += 1
                flight.note(task, f"Check failed after iteration {iteration}:\n{output[-1500:]}")
                flight.event(f"iteration {iteration}: task {task['id']} check failed")
                return
        task["commit"] = gitops.head(flight.root)
        flight.event(f"iteration {iteration}: task {task['id']} done — {task['title']}")

    def _dispatch(
        self,
        role: str,
        text: str,
        *,
        effort: str | None = None,
        summary: str,
        extra_env: dict[str, str] | None = None,
    ) -> dispatch.Outcome:
        flight = self.flight
        flight.data["iteration"] += 1
        iteration = flight.data["iteration"]
        flight.save()
        binding = self.roster.resolve(role, effort)
        env = dict(os.environ if self.environment is None else self.environment)
        env["PATH"] = f"{prompt.SCRIPTS_DIR}{os.pathsep}{env.get('PATH', '')}"
        env.update(
            {
                "AUTOPILOT_ROOT": str(flight.root),
                "AUTOPILOT_ROLE": role,
                "AUTOPILOT_ITERATION": str(iteration),
            }
        )
        env.update(extra_env or {})
        log_path = flight.runtime_dir / "logs" / f"{flight.dispatch_count() + 1:03d}-{role}.log"
        flight.event(f"iteration {iteration}: {role} via {binding.label} on {summary}")
        if self.supervisor is not None:
            self.supervisor.set_state("running", f"iteration {iteration}: {role} on {summary}")
        started = time.monotonic()
        outcome = dispatch.run_agent(
            binding,
            text,
            cwd=flight.root,
            log_path=log_path,
            timeout=flight.config["iteration_timeout"],
            environment=env,
        )
        flight.event(f"iteration {iteration}: agent exit {outcome.exit_class} — {outcome.detail}")
        # The agent may have rewritten the state file; reload before recording.
        flight.load()
        flight.record_dispatch(role, binding.label, time.monotonic() - started, outcome.exit_class)
        if outcome.exit_class == dispatch.EXIT_INFRA:
            # The agent never ran, so the iteration is refunded: provider
            # trouble must not eat the flight's ceiling.
            flight.data["iteration"] -= 1
        flight.save()
        return outcome

    # -- chunk and flight completion ---------------------------------------------------

    def _complete_chunk(self, chunk: dict[str, Any]) -> None:
        flight = self.flight
        if chunk.get("check"):
            passed, output = dispatch.run_check(
                chunk["check"], cwd=flight.root, timeout=flight.config["check_timeout"]
            )
            if not passed:
                if chunk["fix_rounds"] < flight.config["retry_cap"]:
                    chunk["fix_rounds"] += 1
                    flight.add_task(
                        f"Make chunk verification pass: {chunk['title']}",
                        chunk=chunk["id"],
                        done_when=f"`{chunk['check']}` exits 0",
                        check=chunk["check"],
                        origin="autopilot",
                        notes=f"Verification output:\n{output[-1500:]}",
                    )
                    flight.event(f"chunk {chunk['id']}: verification failed; filed a fix task")
                else:
                    flight.add_escalation(
                        None,
                        f"Chunk {chunk['id']} ({chunk['title']}) verification `{chunk['check']}` "
                        f"still fails after {chunk['fix_rounds']} fix rounds. Last output:\n{output[-800:]}",
                    )
                    flight.event(f"chunk {chunk['id']}: verification keeps failing; escalated")
                flight.save()
                return
        if chunk.get("review") and not chunk.get("reviewed"):
            chunk["reviewed"] = True
            flight.save()
            base = chunk.get("base") or flight.data["base"]
            ids_before = {task["id"] for task in flight.tasks}
            outcome = self._dispatch(
                "reviewer",
                prompt.reviewer_prompt(flight, chunk, base=base),
                effort=chunk.get("review_effort"),
                summary=f"chunk {chunk['id']} review",
                extra_env={"AUTOPILOT_CHUNK": str(chunk["id"])},
            )
            flight.load()
            chunk = flight.chunk(chunk["id"])
            if outcome.exit_class == dispatch.EXIT_INFRA:
                chunk["reviewed"] = False
                flight.save()
                self._infra(outcome)
                return
            self.infra_streak = 0
            filed = [task for task in flight.tasks if task["id"] not in ids_before]
            flight.event(f"chunk {chunk['id']}: review filed {len(filed)} task(s)")
            flight.save()
            if any(task["status"] == "todo" for task in filed):
                return
        chunk["status"] = "done"
        flight.event(f"chunk {chunk['id']} done — {chunk['title']}")
        flight.save()

    def _close_flight(self) -> None:
        flight = self.flight
        check_result = None
        if flight.config.get("check"):
            passed, output = dispatch.run_check(
                flight.config["check"], cwd=flight.root, timeout=flight.config["check_timeout"]
            )
            check_result = ("passed" if passed else "FAILED") + "\n" + output[-2000:]
            if not passed:
                rounds = flight.data.setdefault("final_fix_rounds", 0)
                last_chunk = flight.chunks[-1]
                if rounds < flight.config["retry_cap"]:
                    flight.data["final_fix_rounds"] = rounds + 1
                    flight.add_task(
                        "Make the whole-flight verification pass",
                        chunk=last_chunk["id"],
                        done_when=f"`{flight.config['check']}` exits 0",
                        check=flight.config["check"],
                        origin="autopilot",
                        notes=f"Verification output:\n{output[-1500:]}",
                    )
                    flight.event("whole-flight verification failed; filed a fix task")
                    flight.save()
                    return
                flight.add_escalation(
                    None,
                    f"Whole-flight verification `{flight.config['check']}` still fails after "
                    f"{rounds} fix rounds. Last output:\n{output[-800:]}",
                )
                flight.save()
                self._end("escalated", "whole-flight verification keeps failing")
                return
        if flight.data["closer_rounds"] >= 2:
            flight.add_escalation(
                None,
                "The closer found gaps against the requirements twice. The plan, not the code, "
                "is probably wrong: decide whether to land as-is, answer with new scope, or stop.",
            )
            flight.save()
            self._end("escalated", "acceptance found gaps twice")
            return
        flight.data["closer_rounds"] += 1
        flight.save()
        ids_before = {task["id"] for task in flight.tasks}
        outcome = self._dispatch(
            "closer",
            prompt.closer_prompt(flight, check_result=check_result),
            summary="acceptance",
        )
        flight.load()
        if outcome.exit_class == dispatch.EXIT_INFRA:
            flight.data["closer_rounds"] -= 1
            flight.save()
            self._infra(outcome)
            return
        self.infra_streak = 0
        gaps = [task for task in flight.tasks if task["id"] not in ids_before and task["status"] == "todo"]
        if gaps:
            flight.event(f"acceptance: closer filed {len(gaps)} gap task(s)")
            flight.save()
            return
        flight.data["status"] = "landed"
        (flight.dir / "wrap-up.html").write_text(render.wrap_up(flight), encoding="utf-8")
        flight.event("flight landed")
        flight.save()
        notify("Autopilot", f"Flight landed: {flight.data['goal'][:80]}")
        raise FlightEnded("landed")

    def _replan(self, task: dict[str, Any], reason: str) -> None:
        flight = self.flight
        fingerprint = _task_fingerprint(task)
        outcome = self._dispatch(
            "planner",
            prompt.replan_prompt(flight, task, reason=reason),
            summary=f"replan of task {task['id']}",
        )
        flight.load()
        if outcome.exit_class == dispatch.EXIT_INFRA:
            self._infra(outcome)
            return
        self.infra_streak = 0
        task = flight.task(task["id"])
        if (
            task["status"] == "todo"
            and task["attempts"] >= flight.config["retry_cap"]
            and _task_fingerprint(task) == fingerprint
        ):
            flight.set_status(task, "parked")
            flight.note(task, "Parked automatically: the planner changed nothing at the retry cap.")
            flight.add_escalation(
                None,
                f"Task {task['id']} ({task['title']}) hit the retry cap and the planner made no "
                f"change. It is parked; decide whether to re-brief it, drop it, or land without it.",
            )
            flight.event(f"task {task['id']} parked after an inconclusive replan")
        flight.save()

    # -- housekeeping -------------------------------------------------------------------

    def _recover(self) -> None:
        flight = self.flight
        for task in flight.tasks:
            if task["status"] == "doing":
                flight.set_status(task, "todo")
                flight.note(task, "The driver restarted while this task was in progress; check the tree before continuing.")
        flight.save()
        self._commit_leftovers("WIP: recover uncommitted work")

    def _commit_leftovers(self, message: str) -> None:
        """Commit product changes an agent left uncommitted so nothing is lost.

        Flight state is untracked, so the only thing that can be dirty here is
        the product; a clean tree commits nothing."""

        if gitops.is_dirty(self.flight.root):
            gitops.commit_all(self.flight.root, message)

    def _infra(self, outcome: dispatch.Outcome) -> None:
        """Provider trouble: never an attempt. Pause after a streak; give up eventually."""

        flight = self.flight
        self.infra_streak += 1
        if self.infra_streak < INFRA_STREAK_TO_PAUSE:
            return
        if self.infra_waits >= INFRA_MAX_WAITS:
            flight.add_escalation(
                None,
                f"The agent CLI kept failing for infrastructure reasons ({outcome.detail}); "
                f"paused {self.infra_waits} times without recovery. Check authentication or quota.",
            )
            flight.save()
            self._end("escalated", "provider unavailable")
        self.infra_waits += 1
        self.infra_streak = 0
        env = os.environ if self.environment is None else self.environment
        wait = int(env.get("AUTOPILOT_INFRA_WAIT", INFRA_WAIT_SECONDS))
        flight.event(f"pausing {wait}s after repeated infrastructure failures ({outcome.detail})")
        if self.supervisor is not None:
            self.supervisor.set_state("paused", f"waiting {wait}s for the provider to recover")
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            if self.supervisor is not None and self.supervisor.drain_requested():
                break
            time.sleep(min(5.0, max(0.0, deadline - time.monotonic())))

    def _end(self, status: str, reason: str) -> None:
        raise FlightEnded(self._finish(status, reason))

    def _finish(self, status: str, reason: str) -> str:
        flight = self.flight
        flight.data["status"] = status
        flight.event(f"flight {status}: {reason}")
        flight.save()
        if status in ("escalated", "exhausted"):
            notify("Autopilot", f"Flight {status}: {reason[:120]}")
        return status


def _task_fingerprint(task: dict[str, Any]) -> str:
    return json.dumps(
        [task["title"], task["done_when"], task["check"], task["role"], task["status"], task["attempts"], task["chunk"]]
    )
