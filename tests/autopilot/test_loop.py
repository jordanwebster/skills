from __future__ import annotations

import unittest

from autopilot.loop import Driver
from autopilot.state import Flight

from helpers import FlightCase, git, task, toy_plan


class LoopTests(FlightCase):
    def drive(self, flight: Flight, **overrides) -> str:
        env = dict(self.env)
        env.update(overrides)
        return Driver(flight, self.roster, environment=env).run()

    def test_toy_flight_lands(self) -> None:
        plan = toy_plan(
            [task(1, "first"), task(2, "second", depends_on=[1]), task(3, "third", chunk=2)],
            chunks=[
                {"id": 1, "title": "Files", "check": "test -f 1.txt && test -f 2.txt"},
                {"id": 2, "title": "More files", "review": False},
            ],
            config={"max_iterations": 20, "check": "test -f 3.txt"},
        )
        flight = self.seed(plan)
        self.assertEqual(self.drive(flight), "landed")
        flight.load()
        self.assertTrue(all(t["status"] == "done" and t["commit"] for t in flight.tasks))
        self.assertTrue(all(c["status"] == "done" for c in flight.chunks))
        self.assertTrue((flight.dir / "reviews" / "chunk-1.md").exists())
        self.assertFalse((flight.dir / "reviews" / "chunk-2.md").exists())
        self.assertTrue((flight.handoff_dir / "proof.json").exists())
        self.assertTrue((flight.handoff_dir / "handoff.html").exists())
        self.assertEqual(git(self.root, "status", "--porcelain").strip(), "")
        self.assertEqual(git(self.root, "rev-parse", "--abbrev-ref", "HEAD").strip(), "autopilot/toy")
        log = git(self.root, "log", "--oneline")
        self.assertIn("Add 1.txt", log)
        self.assertNotIn("flight", log.casefold(), "flight state never enters the product's history")
        # Both tasks in chunk 1 share a role, so one agent pulled them together.
        self.assertLessEqual(flight.data["iteration"], 5)

    def test_unfinished_and_failed_checks_consume_attempts_then_replan(self) -> None:
        plan = toy_plan([task(1, "[fail-once] first"), task(2, "[badcheck] second")])
        flight = self.seed(plan)
        self.assertEqual(self.drive(flight), "landed")
        flight.load()
        first, second = flight.task(1), flight.task(2)
        self.assertEqual(first["status"], "done")
        self.assertIn("still in progress", first["notes"])
        self.assertEqual(second["status"], "done")
        self.assertTrue(second["title"].startswith("Re-briefed"))
        self.assertIn("Check failed", second["notes"])
        events = "\n".join(flight.recent_events(100))
        self.assertIn("planner", events)
        self.assertIn("check failed", events)

    def test_reversible_worker_decision_is_triaged_and_resolved_internally(self) -> None:
        plan = toy_plan([task(1, "[escalate] first"), task(2, "second")])
        flight = self.seed(plan)
        self.assertEqual(self.drive(flight), "landed")
        flight.load()
        decision = flight.escalation(1)
        self.assertEqual(decision["state"], "resolved")
        self.assertIsNone(decision["answer"])
        self.assertEqual(flight.open_escalations(), [])
        self.assertIn("Internal decision", flight.task(1)["notes"])
        self.assertTrue(all(task["status"] == "done" for task in flight.tasks))
        self.assertIn("planner", [item["role"] for item in flight.data["dispatches"]])

    def test_internal_triage_repairs_an_inverted_dependency(self) -> None:
        plan = toy_plan([task(1, "[dependency] capture"), task(2, "companion", depends_on=[1])])
        flight = self.seed(plan)
        self.assertEqual(self.drive(flight), "landed")
        flight.load()
        self.assertEqual(flight.task(1)["depends_on"], [2])
        self.assertEqual(flight.task(2)["depends_on"], [])
        self.assertEqual(flight.escalation(1)["state"], "resolved")
        self.assertTrue(all(task["status"] == "done" for task in flight.tasks))

    def test_triage_promotes_a_genuine_operator_decision_then_answer_resumes(self) -> None:
        plan = toy_plan([task(1, "[escalate] first"), task(2, "second")])
        flight = self.seed(plan)
        self.assertEqual(self.drive(flight, FAKE_TRIAGE_OPERATOR="1"), "escalated")
        flight.load()
        self.assertEqual(flight.task(1)["status"], "blocked")
        self.assertEqual(flight.task(2)["status"], "done", "independent work continues after promotion")
        escalation = flight.open_escalations()[0]
        self.assertEqual(escalation["state"], "operator")
        self.assertIn("only the operator", escalation["operator_question"])
        flight.answer_escalation(escalation["id"], "keep the accepted promise")
        flight.save()
        self.assertEqual(self.drive(flight), "landed")
        flight.load()
        self.assertIn("Operator answer", flight.task(1)["notes"])

    def test_inconclusive_triage_is_promoted_after_one_pass(self) -> None:
        flight = self.seed(toy_plan([task(1, "[escalate] first")]))
        self.assertEqual(self.drive(flight, FAKE_TRIAGE_STALL="1"), "escalated")
        flight.load()
        escalation = flight.open_escalations()[0]
        self.assertEqual(escalation["state"], "operator")
        self.assertIn("one bounded pass", escalation["operator_question"])
        planner_dispatches = [item for item in flight.data["dispatches"] if item["role"] == "planner"]
        self.assertEqual(len(planner_dispatches), 1)

    def test_driver_routes_a_no_ready_deadlock_through_triage(self) -> None:
        flight = self.seed(toy_plan([task(1, "parked prerequisite"), task(2, "waiting", depends_on=[1])]))
        flight.set_status(flight.task(1), "parked")
        flight.save()
        self.assertEqual(self.drive(flight), "escalated")
        flight.load()
        escalation = flight.open_escalations()[0]
        self.assertIsNone(escalation["task"])
        self.assertIn("only the operator", escalation["operator_question"])
        planner_dispatches = [item for item in flight.data["dispatches"] if item["role"] == "planner"]
        self.assertEqual(len(planner_dispatches), 1)

    def test_review_and_closer_can_file_work(self) -> None:
        plan = toy_plan([task(1, "first")], config={"max_iterations": 20})
        flight = self.seed(plan)
        self.assertEqual(self.drive(flight, FAKE_REVIEW_FINDINGS="1", FAKE_CLOSER_GAPS="1"), "landed")
        flight.load()
        origins = sorted(t["origin"] for t in flight.tasks)
        self.assertEqual(origins, ["closer", "plan", "review"])
        self.assertTrue(all(t["status"] == "done" for t in flight.tasks))
        self.assertEqual(flight.data["closer_rounds"], 2)

    def test_no_progress_hits_cap_then_replans(self) -> None:
        plan = toy_plan([task(1, "[stall] first")])
        flight = self.seed(plan)
        self.assertEqual(self.drive(flight), "landed")
        flight.load()
        self.assertEqual(flight.task(1)["status"], "done")
        self.assertIn("no progress", "\n".join(flight.recent_events(100)))

    def test_infra_failures_consume_no_attempts(self) -> None:
        plan = toy_plan([task(1, "first")])
        flight = self.seed(plan)
        self.assertEqual(self.drive(flight, FAKE_INFRA="1"), "escalated")
        flight.load()
        self.assertEqual(flight.task(1)["attempts"], 0)
        self.assertIn("infrastructure", flight.open_escalations()[0]["text"])

    def test_config_failure_stops_without_consuming_work_budget(self) -> None:
        flight = self.seed(toy_plan([task(1, "first")]))
        self.assertEqual(self.drive(flight, FAKE_CONFIG="1"), "stopped")
        flight.load()
        self.assertEqual(flight.data["iteration"], 0)
        self.assertEqual(flight.task(1)["attempts"], 0)
        self.assertEqual(flight.data["failure"]["class"], "config")
        self.assertIn("delegate doctor", flight.data["failure"]["recovery"])

    def test_iteration_ceiling(self) -> None:
        plan = toy_plan([task(1, "first"), task(2, "second", chunk=1)])
        flight = self.seed(plan)
        self.assertEqual(Driver(flight, self.roster, max_iterations=1, environment=self.env).run(), "exhausted")

    def test_chunk_check_failure_files_a_fix_task(self) -> None:
        plan = toy_plan(
            [task(1, "first")],
            chunks=[{"id": 1, "title": "Files", "check": "test -f 2.txt", "review": False}],
        )
        flight = self.seed(plan)
        self.assertEqual(self.drive(flight), "landed")
        flight.load()
        fix = [t for t in flight.tasks if t["origin"] == "autopilot"]
        self.assertEqual(len(fix), 1)
        self.assertEqual(fix[0]["status"], "done")

    def test_restart_recovers_in_progress_tasks(self) -> None:
        plan = toy_plan([task(1, "first")])
        flight = self.seed(plan)
        flight.set_status(flight.task(1), "doing")
        (self.root / "leftover.txt").write_text("partial\n")
        flight.save()
        self.assertEqual(self.drive(flight), "landed")
        flight.load()
        self.assertIn("restarted", flight.task(1)["notes"])
        self.assertIn("recover uncommitted work", git(self.root, "log", "--oneline"))

    def test_restart_does_not_redispatch_completed_durable_work(self) -> None:
        plan = toy_plan([task(1, "first")], chunks=[{"id": 1, "title": "Files", "review": False}])
        flight = self.seed(plan)
        (self.root / "1.txt").write_text("ok\n")
        git(self.root, "add", "1.txt")
        git(self.root, "commit", "-m", "Complete first result")
        flight.set_status(flight.task(1), "doing")
        flight.task(1)["attempt_head"] = flight.data["base"]
        flight.save()
        self.assertEqual(self.drive(flight), "landed")
        flight.load()
        self.assertIn("not dispatched twice", flight.task(1)["notes"])
        self.assertFalse(any(item["role"] == "implementer" for item in flight.data["dispatches"]))


if __name__ == "__main__":
    unittest.main()
