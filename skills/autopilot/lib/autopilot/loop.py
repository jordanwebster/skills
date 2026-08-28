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

from . import dispatch, gitops, landing, prompt
from .notify import notify
from .roster import Roster, RosterError
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
        flight.data["failure"] = None
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
            pending = flight.pending_triage()
            if pending:
                if flight.data["iteration"] >= limit:
                    decision = pending[0]
                    flight.promote_escalation(
                        decision["id"],
                        "The flight reached its dispatch ceiling before internal triage could assess this decision: "
                        + decision["text"],
                    )
                    flight.event(f"decision #{decision['id']} promoted because the dispatch ceiling was reached")
                    flight.save()
                    self._end("escalated", "internal decision triage needs operator judgment")
                else:
                    self._triage(pending[0])
                    continue
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
            chunk = next(
                (item for item in flight.chunks if item["status"] == "open" and flight.chunk_complete(item)),
                None,
            )
            if chunk is not None:
                self._complete_chunk(chunk)
                continue
            task = flight.next_task()
            if task is not None:
                self._iterate(task)
                continue
            if flight.open_escalations():
                self._end("escalated", "waiting on the operator")
            if all(item["status"] == "done" for item in flight.chunks):
                self._close_flight()
                continue
            decision = flight.add_escalation(
                None,
                "No task is ready and no chunk can complete. Something depends on a parked "
                "or blocked task. I would repair the task graph when that stays within the approved plan; "
                "the blast radius is execution order and scheduling only.",
                pending_triage=True,
            )
            flight.event(f"decision #{decision['id']} queued after the task graph made no work ready")
            flight.save()

    # -- one iteration -------------------------------------------------------------

    def _iterate(self, task: dict[str, Any]) -> None:
        """Dispatch one agent on `task` and its siblings, then confirm what it claimed."""

        flight = self.flight
        role = flight.task_role(task)
        chunk = flight.chunk(task["chunk"])
        if chunk.get("base") is None:
            chunk["base"] = gitops.head(flight.root)
        ready = flight.ready_tasks(role=role, chunk=chunk["id"])
        task["attempt_head"] = gitops.head(flight.root)
        flight.save()
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
        selected = flight.task(task["id"])
        selected["attempt_advanced"] = bool(
            selected.get("attempt_head") and selected["attempt_head"] != gitops.head(flight.root)
        )
        if outcome.exit_class == dispatch.EXIT_CONFIG:
            self._config(outcome)
            return
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

    def _triage(self, decision: dict[str, Any]) -> None:
        """Give one fresh planner context the chance to settle a flight decision."""

        flight = self.flight
        outcome = self._dispatch(
            "planner",
            prompt.triage_prompt(flight, decision),
            summary=f"decision {decision['id']} triage",
            extra_env={"AUTOPILOT_TRIAGE_ID": str(decision["id"])},
        )
        flight.load()
        if outcome.exit_class == dispatch.EXIT_CONFIG:
            self._config(outcome)
            return
        if outcome.exit_class == dispatch.EXIT_INFRA:
            self._infra(outcome)
            return
        self.infra_streak = 0
        current = flight.escalation(decision["id"])
        if current.get("state") == "pending_triage":
            flight.promote_escalation(
                current["id"],
                "Internal triage did not safely settle this decision in its one bounded pass: "
                + current["text"],
            )
            flight.event(f"decision #{current['id']} promoted after inconclusive internal triage")
            flight.save()

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
        try:
            binding = self.roster.resolve(role, effort)
        except RosterError as error:
            flight.data["iteration"] -= 1
            flight.save()
            return dispatch.Outcome(
                dispatch.EXIT_CONFIG,
                None,
                flight.runtime_dir / "logs" / f"{flight.dispatch_count() + 1:03d}-{role}.log",
                str(error),
                error.recovery,
            )
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
        if outcome.exit_class in (dispatch.EXIT_CONFIG, dispatch.EXIT_INFRA):
            # The agent never ran, so the iteration is refunded: provider
            # trouble must not eat the flight's ceiling.
            flight.data["iteration"] -= 1
        flight.save()
        return outcome

    # -- chunk and flight completion ---------------------------------------------------

    def _complete_chunk(self, chunk: dict[str, Any]) -> None:
        flight = self.flight
        if chunk.get("completion_head") is None:
            chunk["completion_head"] = gitops.head(flight.root)
            flight.save()
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
                    chunk["completion_head"] = None
                    flight.event(f"chunk {chunk['id']}: verification failed; filed a fix task")
                else:
                    decision = flight.add_escalation(
                        None,
                        f"Chunk {chunk['id']} ({chunk['title']}) verification `{chunk['check']}` "
                        f"still fails after {chunk['fix_rounds']} fix rounds. I would reassess the task or "
                        f"verification boundary without changing accepted behavior. Last output:\n{output[-800:]}",
                        pending_triage=True,
                    )
                    flight.event(f"decision #{decision['id']} queued after chunk verification kept failing")
                flight.save()
                return
        if chunk.get("review") and not chunk.get("reviewed"):
            chunk["reviewed"] = True
            flight.save()
            base = chunk.get("base") or flight.data["base"]
            target = chunk.get("completion_head") or gitops.head(flight.root)
            ids_before = {task["id"] for task in flight.tasks}
            outcome = self._dispatch(
                "reviewer",
                prompt.reviewer_prompt(flight, chunk, base=base, target=target),
                effort=chunk.get("review_effort"),
                summary=f"chunk {chunk['id']} review",
                extra_env={"AUTOPILOT_CHUNK": str(chunk["id"])},
            )
            flight.load()
            chunk = flight.chunk(chunk["id"])
            if outcome.exit_class == dispatch.EXIT_CONFIG:
                chunk["reviewed"] = False
                flight.save()
                self._config(outcome)
                return
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
        parked_gaps = [
            flight.task(task_id)
            for audit in flight.data.get("acceptance_audits", [])
            for task_id in audit.get("gap_task_ids", [])
            if flight.task(task_id)["status"] == "parked"
        ]
        if parked_gaps:
            ids = ", ".join(str(task["id"]) for task in parked_gaps)
            decision = flight.add_escalation(
                None,
                f"Acceptance gap task(s) {ids} were parked. Reconsider whether the approved plan "
                "can still meet the confirmed promise; do not silently land with an acceptance gap.",
                pending_triage=True,
            )
            flight.event(f"decision #{decision['id']} queued after acceptance work was parked")
            flight.save()
            return
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
                decision = flight.add_escalation(
                    None,
                    f"Whole-flight verification `{flight.config['check']}` still fails after "
                    f"{rounds} fix rounds. I would reassess the task or verification boundary without "
                    f"changing accepted behavior. Last output:\n{output[-800:]}",
                    pending_triage=True,
                )
                flight.event(f"decision #{decision['id']} queued after whole-flight verification kept failing")
                flight.save()
                return
        audited_head = gitops.head(flight.root)
        ids_before = {task["id"] for task in flight.tasks}
        decisions_before = {item["id"] for item in flight.escalations}
        outcome = self._dispatch(
            "closer",
            prompt.closer_prompt(flight, check_result=check_result),
            summary="acceptance",
        )
        flight.load()
        if outcome.exit_class == dispatch.EXIT_CONFIG:
            self._config(outcome)
            return
        if outcome.exit_class == dispatch.EXIT_INFRA:
            self._infra(outcome)
            return
        self.infra_streak = 0
        gaps = [task for task in flight.tasks if task["id"] not in ids_before and task["status"] == "todo"]
        audit = {
            "number": len(flight.data.setdefault("acceptance_audits", [])) + 1,
            "head": audited_head,
            "gap_task_ids": [task["id"] for task in gaps],
            "decision_ids": [
                item["id"] for item in flight.pending_triage() if item["id"] not in decisions_before
            ],
        }
        flight.data["acceptance_audits"].append(audit)
        if audit["decision_ids"]:
            flight.event(
                f"acceptance audit {audit['number']}: closer referred {len(audit['decision_ids'])} "
                "plan question(s) to internal triage"
            )
            flight.save()
            return
        if gaps:
            flight.event(f"acceptance audit {audit['number']}: closer filed {len(gaps)} gap task(s)")
            flight.save()
            return
        result = landing.finish(
            flight.handoff_dir,
            acceptance_path=flight.acceptance_path,
            environment=self.environment,
        )
        if not result.ok:
            proof_task = flight.add_task(
                "Complete the decision-ready proof bundle",
                chunk=flight.chunks[-1]["id"],
                done_when="Handoff validates the page-mode proof bundle at the current commit",
                origin="closer",
                notes=f"Handoff validation: {result.detail}. {result.recovery or ''}".strip(),
            )
            audit["gap_task_ids"].append(proof_task["id"])
            flight.event(f"acceptance audit {audit['number']}: proof bundle rejected — {result.detail}")
            flight.save()
            return
        flight.data["status"] = "landed"
        flight.data["handoff"] = dict(result.payload or {})
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
        if outcome.exit_class == dispatch.EXIT_CONFIG:
            self._config(outcome)
            return
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
                self._commit_leftovers("WIP: recover uncommitted work")
                if task.get("check"):
                    passed, output = dispatch.run_check(
                        task["check"], cwd=flight.root, timeout=flight.config["check_timeout"]
                    )
                    if passed:
                        flight.set_status(task, "done")
                        task["commit"] = gitops.head(flight.root)
                        task["attempt_advanced"] = bool(task.get("attempt_head") and task["attempt_head"] != task["commit"])
                        flight.note(task, "Recovered after restart: the durable check already passed, so work was not dispatched twice.")
                        continue
                    flight.note(task, f"Restart recovery check did not pass:\n{output[-1000:]}")
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

    def _config(self, outcome: dispatch.Outcome) -> None:
        """A deterministic setup failure stops immediately and consumes no budget."""

        flight = self.flight
        flight.data["failure"] = {
            "class": "config",
            "message": outcome.detail,
            "recovery": outcome.recovery or "Run `delegate doctor`, fix the binding, then restart.",
        }
        flight.save()
        self._end("stopped", f"configuration failure: {outcome.detail}")

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
        [task["title"], task["done_when"], task["check"], task["role"], task["status"], task["attempts"], task["chunk"], task.get("attempt_advanced")]
    )
