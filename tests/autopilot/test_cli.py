from __future__ import annotations

import json
import time
import unittest

from autopilot import supervise
from autopilot.state import Flight

from helpers import FlightCase, git, plan_html, task, toy_plan


class CliTests(FlightCase):
    def test_init_plan_start_status_end_to_end(self) -> None:
        init = self.cli("init", "--goal", "Build the toy")
        self.assertEqual(init.returncode, 0, init.stderr)
        self.assertEqual(git(self.root, "rev-parse", "--abbrev-ref", "HEAD").strip(), "autopilot/build-the-toy")
        self.assertIn("Start flight", git(self.root, "log", "--oneline"))
        missing = self.cli("plan", "--no-open")
        self.assertEqual(missing.returncode, 1)
        self.assertIn("no plan", missing.stderr)
        Flight(self.root).plan_path.write_text(plan_html(toy_plan([task(1, "first"), task(2, "second")])))
        self.assertEqual(self.cli("plan", "--no-open").returncode, 0)
        self.assertIn("Add the flight plan", git(self.root, "log", "--oneline"))

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
        self.assertIn("landed", status.stdout)
        self.assertIn("Wrap-up", status.stdout)
        self.assertEqual(self.cli("start").returncode, 1, "a landed flight cannot restart")
        self.assertIn("No driver is running", self.cli("stop").stdout)

        records = self.base / "records"
        env = dict(self.env, AUTOPILOT_RECORDS=str(records))
        landed = self.cli("land", "--no-open", env=env)
        self.assertEqual(landed.returncode, 0, landed.stderr)
        self.assertIn("Flight record kept", landed.stdout)
        self.assertFalse((self.root / ".autopilot").exists())
        self.assertEqual(git(self.root, "status", "--porcelain").strip(), "")
        self.assertIn("Remove flight workspace", git(self.root, "log", "--oneline"))
        kept = list((records / "repo").glob("*/wrap-up.html"))
        self.assertEqual(len(kept), 1)
        self.assertIn("WHAT", kept[0].read_text() + "WHAT")
        after = self.cli("status", env=env)
        self.assertIn("Last landed flight", after.stdout)

    def test_page_renders_markdown(self) -> None:
        source = self.base / "front-page.md"
        source.write_text("# Widget fix\n\n## WHAT CHANGED\n\nThe widget no longer wobbles.\n\n- one\n- two\n")
        rendered = self.cli("page", str(source), "--no-open")
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        html = (self.base / "front-page.html").read_text()
        self.assertIn("<title>Widget fix</title>", html)
        self.assertIn("<h3>WHAT CHANGED</h3>", html)
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

    def test_escalate_and_answer(self) -> None:
        flight = self.seed(toy_plan([task(1, "first")]))
        raised = self.cli("escalate", "1", "blocked on X; I would do Y; blast radius Z")
        self.assertIn("Escalation #1", raised.stdout)
        flight.load()
        self.assertEqual(flight.task(1)["status"], "blocked")
        flight_level = self.cli("escalate", "should we ship?")
        self.assertIn("Escalation #2", flight_level.stdout)
        answered = self.cli("answer", "1", "do Y", "--no-start")
        self.assertEqual(answered.returncode, 0, answered.stderr)
        flight.load()
        self.assertEqual(flight.task(1)["status"], "todo")
        self.assertEqual(len(flight.open_escalations()), 1)
        self.assertIn("Record operator answer", git(self.root, "log", "--oneline"))

    def test_stop_kills_a_running_driver(self) -> None:
        flight = self.seed(toy_plan([task(1, "first")]))
        env = dict(self.env, FAKE_SLEEP="30")
        started = self.cli("start", env=env)
        self.assertEqual(started.returncode, 0, started.stderr)
        self.assertTrue(supervise.read_status(flight.runtime_dir).alive)
        status = self.cli("status")
        self.assertIn("driver alive", status.stdout)
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


if __name__ == "__main__":
    unittest.main()
