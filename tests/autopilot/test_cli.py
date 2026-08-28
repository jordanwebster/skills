from __future__ import annotations

import json
import subprocess
import time
import unittest

from autopilot import supervise
from autopilot.state import Flight

from helpers import FlightCase, SKILL_DIR, git, plan_markdown, task, toy_plan


class CliTests(FlightCase):
    def test_init_plan_start_status_end_to_end(self) -> None:
        contract = self.base / "acceptance.md"
        contract.write_text(
            """# Acceptance contract

## Goal

Build the toy result.

## Observable expectations

- The toy result is visible. <!-- id: toy-expectation -->

## Exclusions

- None.

## Acceptance scenarios

- The toy result is visible. <!-- id: toy-result; covers: toy-expectation -->
  - Demonstration: A transcript contains the completed result.
  - Limitation: None.

## Material decisions

- None.

## Accepted gaps

- None.

## Exceptional operator acts

- None.

## Waivers

- None.

## Confirmation

Final all-ok: CONFIRMED
"""
        )
        finalized = subprocess.run(
            [str(SKILL_DIR.parent / "intake" / "scripts" / "intake"), "finalize", str(contract), "--json"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(finalized.returncode, 0, finalized.stderr)
        self.assertTrue(json.loads(finalized.stdout)["ok"])
        init = self.cli("init", "--goal", "Build the toy", "--requirements", str(contract))
        self.assertEqual(init.returncode, 0, init.stderr)
        self.assertEqual(git(self.root, "rev-parse", "--abbrev-ref", "HEAD").strip(), "autopilot/build-the-toy")
        self.assertEqual(git(self.root, "status", "--porcelain").strip(), "", "flight state is untracked")
        self.assertNotIn("flight", git(self.root, "log", "--oneline").casefold())
        needs_plan = json.loads(self.cli("status", "--json").stdout)
        self.assertEqual(needs_plan["readiness"]["state"], "needs_plan")
        self.assertEqual(needs_plan["next_action"]["kind"], "write_plan")
        missing = self.cli("plan", "--no-open")
        self.assertEqual(missing.returncode, 1)
        self.assertIn("no plan", missing.stderr)
        flight = Flight(self.root)
        original_plan = plan_markdown(toy_plan([task(1, "first"), task(2, "second")]))
        flight.plan_path.write_text(original_plan)
        planned = self.cli("plan", "--no-open")
        self.assertEqual(planned.returncode, 0, planned.stderr)
        page = (self.root / ".autopilot" / "flight-plan.html").read_text()
        self.assertIn("<title>Toy plan</title>", page)
        self.assertIn("Autopilot · plan approval", page)
        self.assertIn("autopilot/build-the-toy", page, "the masthead names the branch it plans")
        self.assertIn('<h2 id="route">Route</h2>', page)
        self.assertIn("A fast deterministic boundary check", page)
        self.assertIn("Intended proof", page)
        self.assertIn("<summary>Staffing (4 roles)</summary>", page)
        self.assertIn("generic/fake", page)
        self.assertIn("<summary>Tasks by milestone (2 tasks)</summary>", page)
        self.assertIn("<td>first</td>", page, "task detail remains available only in diagnostics")
        needs_approval = json.loads(self.cli("status", "--json").stdout)
        self.assertEqual(needs_approval["readiness"]["state"], "needs_approval")

        approved = self.cli("approve", "--json")
        self.assertEqual(approved.returncode, 0, approved.stderr)
        self.assertEqual(json.loads(approved.stdout)["status"], "approved")
        ready = json.loads(self.cli("status", "--json").stdout)
        self.assertEqual(ready["readiness"]["state"], "ready_to_start")
        flight.plan_path.write_text(original_plan + "\nMaterial change.\n")
        stale = json.loads(self.cli("status", "--json").stdout)
        self.assertEqual(stale["readiness"]["state"], "stale_approval")
        self.assertEqual(stale["next_action"]["kind"], "reapprove")
        flight.plan_path.write_text(original_plan)
        self.assertEqual(self.cli("approve").returncode, 0)

        started = self.cli("start")
        self.assertEqual(started.returncode, 0, started.stderr)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            flight = Flight(self.root).load()
            if flight.data["status"] == "landed":
                break
            time.sleep(0.5)
        self.assertEqual(flight.data["status"], "landed")
        status = self.cli("status")
        self.assertIn("proof ready", status.stdout)
        self.assertIn("Next: read the completion page.", status.stdout)
        self.assertEqual(status.stdout.count("Next:"), 1)
        status_json = json.loads(self.cli("status", "--json").stdout)
        self.assertEqual(status_json["phase"], "proof ready")
        self.assertEqual(status_json["next_action"]["kind"], "read_completion")
        self.assertEqual(self.cli("start").returncode, 1, "a landed flight cannot restart")
        self.assertIn("No driver is running", self.cli("stop").stdout)

        landed = self.cli("land")
        self.assertEqual(landed.returncode, 0, landed.stderr)
        self.assertIn("Final Handoff preserved", landed.stdout)
        self.assertIn("Flight machinery deleted", landed.stdout)
        self.assertFalse((self.root / ".autopilot").exists())
        exports = list((self.root / ".handoff").iterdir())
        self.assertEqual(len(exports), 1)
        self.assertTrue((exports[0] / "proof.json").is_file())
        self.assertTrue((exports[0] / "handoff.html").is_file())
        self.assertEqual(git(self.root, "status", "--porcelain").strip(), "")
        self.assertNotIn("flight", git(self.root, "log", "--oneline").casefold())
        after = self.cli("status")
        self.assertEqual(after.returncode, 1)
        self.assertIn("no flight found", after.stderr)

    def test_page_renders_markdown(self) -> None:
        source = self.base / "front-page.md"
        source.write_text("# Widget fix\n\n## WHAT CHANGED\n\nThe widget no longer wobbles.\n\n- one\n- two\n")
        rendered = self.cli("page", str(source), "--no-open")
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        html = (self.base / "front-page.html").read_text()
        self.assertIn("<title>Widget fix</title>", html)
        self.assertIn("<h2>WHAT CHANGED</h2>", html)
        self.assertIn("<li>two</li>", html)

    def test_task_verbs(self) -> None:
        flight = self.seed(toy_plan([task(1, "first"), task(2, "second", depends_on=[1])]))
        listing = self.cli("task", "list")
        self.assertIn("first", listing.stdout)
        self.assertNotIn("second", listing.stdout)
        self.assertEqual(self.cli("task", "start", "2").returncode, 1)
        self.assertEqual(self.cli("task", "start", "1").returncode, 0)
        self.assertEqual(self.cli("task", "note", "1", "halfway").returncode, 0)
        self.assertEqual(self.cli("task", "done", "1").returncode, 0)
        added = self.cli("task", "add", "third", "--done-when", "3.txt exists", "--after", "2", "--check", "true")
        self.assertIn("Task 3 filed", added.stdout)
        later = self.cli("task", "add", "someday", "--later")
        self.assertIn("Task 4 filed", later.stdout)
        self.assertEqual(self.cli("task", "park", "2", "not now").returncode, 0)
        flight.load()
        self.assertEqual(flight.task(1)["status"], "done")
        self.assertIn("halfway", flight.task(1)["notes"])
        self.assertEqual(flight.task(3)["depends_on"], [2])
        self.assertEqual(flight.task(4)["status"], "parked")
        self.assertEqual(flight.task(2)["status"], "parked")
        shown = self.cli("task", "show", "2")
        self.assertIn("Parked: not now", shown.stdout)
        self.assertEqual(self.cli("task", "unpark", "2").returncode, 0)
        edited = self.cli("task", "edit", "3", "--title", "third, renamed", "--after", "1")
        self.assertEqual(edited.returncode, 0)
        flight.load()
        self.assertEqual(flight.task(3)["title"], "third, renamed")
        self.assertEqual(flight.task(3)["depends_on"], [1])
        as_json = json.loads(self.cli("task", "list", "--all", "--json").stdout)
        self.assertEqual(len(as_json), 4)

    def test_role_scoped_listing_from_environment(self) -> None:
        self.seed(toy_plan([task(1, "prober work", role="prober"), task(2, "build")]))
        env = dict(self.env, AUTOPILOT_ROLE="prober", AUTOPILOT_CHUNK="1")
        listing = self.cli("task", "list", env=env)
        self.assertIn("prober work", listing.stdout)
        self.assertNotIn("build", listing.stdout)

    def test_decision_triage_resolves_or_promotes_before_operator_answer(self) -> None:
        flight = self.seed(toy_plan([task(1, "first")]))
        raised = self.cli("escalate", "1", "blocked on X; I would do Y; blast radius Z")
        self.assertIn("Decision #1 queued for internal triage", raised.stdout)
        flight.load()
        self.assertEqual(flight.task(1)["status"], "blocked")
        self.assertEqual(len(flight.pending_triage()), 1)
        status = json.loads(self.cli("status", "--json").stdout)
        self.assertEqual(status["questions"], [])
        self.assertEqual(status["diagnostics"]["pending_triage"][0]["id"], 1)
        flight_level = self.cli("escalate", "should we ship?")
        self.assertIn("Decision #2 queued for internal triage", flight_level.stdout)

        unauthorized = self.cli("triage", "1", "--resolve", "do Y")
        self.assertEqual(unauthorized.returncode, 1)
        self.assertIn("dispatched planner", unauthorized.stderr)
        triage_one = dict(self.env, AUTOPILOT_ROLE="planner", AUTOPILOT_TRIAGE_ID="1")
        staffing_edit = self.cli("task", "edit", "1", "--role", "reviewer", env=triage_one)
        self.assertEqual(staffing_edit.returncode, 1)
        self.assertIn("approved semantic staffing", staffing_edit.stderr)
        staffing_add = self.cli(
            "task",
            "add",
            "specialist work",
            "--done-when",
            "done",
            "--role",
            "reviewer",
            env=triage_one,
        )
        self.assertEqual(staffing_add.returncode, 1)
        self.assertIn("unapproved semantic staffing", staffing_add.stderr)
        resolved = self.cli("triage", "1", "--resolve", "do Y", env=triage_one)
        self.assertEqual(resolved.returncode, 0, resolved.stderr)
        triage_two = dict(self.env, AUTOPILOT_ROLE="planner", AUTOPILOT_TRIAGE_ID="2")
        promoted = self.cli(
            "triage",
            "2",
            "--operator",
            "Choose whether to ship; this changes the accepted release decision.",
            env=triage_two,
        )
        self.assertEqual(promoted.returncode, 0, promoted.stderr)
        answered = self.cli("answer", "2", "do not ship", "--no-start")
        self.assertEqual(answered.returncode, 0, answered.stderr)
        flight.load()
        self.assertEqual(flight.task(1)["status"], "todo")
        self.assertEqual(flight.open_escalations(), [])
        self.assertIn("Internal decision: do Y", flight.task(1)["notes"])

    def test_stop_kills_a_running_driver(self) -> None:
        flight = self.seed(toy_plan([task(1, "first")]))
        env = dict(self.env, FAKE_SLEEP="30")
        started = self.cli("start", env=env)
        self.assertEqual(started.returncode, 0, started.stderr)
        self.assertTrue(supervise.read_status(flight.runtime_dir).alive)
        status = self.cli("status")
        self.assertIn("Driver: alive", status.stdout)
        stopped = self.cli("stop")
        self.assertIn("Driver stopped", stopped.stdout)
        self.assertFalse(supervise.read_status(flight.runtime_dir).alive)
        self.assertIsNone(supervise.locked_owner(flight.runtime_dir))
        self.assertEqual(self.cli("start", env=env).returncode, 0, "a stopped flight restarts")
        self.assertIn("Driver stopped", self.cli("stop").stdout)

    def test_drain_stops_after_the_iteration(self) -> None:
        flight = self.seed(toy_plan([task(1, "first"), task(2, "second", chunk=1)]))
        env = dict(self.env, FAKE_SLEEP="2")
        self.assertEqual(self.cli("start", env=env).returncode, 0)
        self.assertIn("after the current iteration", self.cli("drain").stdout)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and supervise.locked_owner(flight.runtime_dir):
            time.sleep(0.2)
        self.assertIsNone(supervise.locked_owner(flight.runtime_dir))
        flight.load()
        self.assertEqual(flight.data["status"], "stopped")
        self.assertLessEqual(flight.data["iteration"], 2)



class StatusPhaseTests(FlightCase):
    """The status line reports what the flight is actually doing, and only
    offers actions a command implements."""

    def phase(self, flight, **state) -> str:
        from autopilot.__main__ import _flight_phase

        return _flight_phase(
            flight,
            active=state.get("active", []),
            questions=state.get("questions", []),
            readiness=state.get("readiness", {"state": "ready_to_start"}),
        )

    def test_the_phase_follows_durable_state(self) -> None:
        plan = toy_plan(
            [task(1, "first"), task(2, "second", chunk=2)],
            chunks=[
                {"id": 1, "title": "Files", "check": "true", "review": True},
                {"id": 2, "title": "More", "review": False},
            ],
        )
        flight = self.seed(plan)
        self.assertEqual(self.phase(flight), "ready to start", "before takeoff, readiness is the phase")

        flight.data["status"] = "running"
        self.assertEqual(self.phase(flight, active=[flight.task(1)]), "implementing")

        flight.set_status(flight.task(1), "done")
        self.assertEqual(self.phase(flight), "reviewing milestone 1")

        repair = flight.add_task("Fix a review finding", chunk=1, origin="review")
        self.assertEqual(self.phase(flight), "repairing milestone 1")
        flight.set_status(repair, "done")

        flight.chunk(1)["reviewed"] = True
        for chunk in flight.chunks:
            chunk["status"] = "done"
        self.assertEqual(self.phase(flight), "acceptance audit")

        gap = flight.add_task("Close the acceptance gap", chunk=2, origin="closer")
        self.assertEqual(self.phase(flight), "repairing acceptance")
        flight.set_status(gap, "done")

        flight.data["status"] = "landed"
        self.assertEqual(self.phase(flight), "proof ready")

        flight.data["status"] = "running"
        self.assertEqual(
            self.phase(flight, questions=[{"id": 1}]), "needs operator"
        )

    def test_every_offered_action_names_a_command_that_exists(self) -> None:
        """An escalation that recommends an action no verb implements leaves the
        operator editing state by hand, which is how the last flight ended."""

        import inspect
        import re

        from autopilot.__main__ import _status_payload, build_parser

        autopilot_verbs = {
            choice
            for action in build_parser()._subparsers._group_actions
            for choice in action.choices
        }
        delegate = subprocess.run(
            [str(SKILL_DIR.parent / "delegate" / "scripts" / "delegate"), "--help"],
            capture_output=True, text=True, check=True, timeout=30,
        ).stdout
        offered = re.findall(
            r'"command": f?"(autopilot|delegate) ([a-z-]+)', inspect.getsource(_status_payload)
        )
        self.assertGreaterEqual(len(offered), 8, "every branch offers one next action")
        for command, verb in offered:
            if command == "autopilot":
                self.assertIn(verb, autopilot_verbs, f"{command} {verb}")
            else:
                self.assertIn(verb, delegate, f"{command} {verb}")


if __name__ == "__main__":
    unittest.main()
