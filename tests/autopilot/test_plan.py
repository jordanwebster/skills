from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from autopilot.plan import PlanError, read_plan, seed_flight
from autopilot.state import Flight

from helpers import SKILL_DIR, plan_html, task, toy_plan


class PlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.dir = Path(self.temporary.name)

    def write(self, html: str) -> Path:
        path = self.dir / "plan.html"
        path.write_text(html)
        return path

    def test_shipped_template_parses(self) -> None:
        plan = read_plan(SKILL_DIR / "templates" / "flight-plan.html")
        self.assertEqual(plan["chunks"][0]["id"], 1)
        self.assertEqual(plan["tasks"][0]["chunk"], 1)

    def test_seed_copies_chunks_tasks_and_config(self) -> None:
        plan = toy_plan(
            [task(1, "a"), task(2, "b", depends_on=[1], role="qa-tester")],
            config={"max_iterations": 7, "check": "true"},
        )
        flight = Flight(self.dir).create("placeholder", "b", "0" * 40)
        seed_flight(flight, read_plan(self.write(plan_html(plan))))
        reloaded = Flight(self.dir).load()
        self.assertEqual(reloaded.data["goal"], "Build the toy")
        self.assertEqual(reloaded.config["max_iterations"], 7)
        self.assertEqual(reloaded.config["check"], "true")
        self.assertEqual(reloaded.config["retry_cap"], 3)
        self.assertEqual(reloaded.task(2)["depends_on"], [1])
        self.assertEqual(reloaded.task_role(reloaded.task(2)), "qa-tester")
        self.assertEqual(reloaded.chunk(1)["check"], "test -f README.md")

    def test_missing_block_is_an_error(self) -> None:
        with self.assertRaises(PlanError):
            read_plan(self.write("<h1>no block</h1>"))

    def test_two_blocks_are_an_error(self) -> None:
        html = plan_html(toy_plan([task(1, "a")])) * 2
        with self.assertRaises(PlanError):
            read_plan(self.write(html))

    def test_unknown_chunk_and_dependency_are_errors(self) -> None:
        bad_chunk = toy_plan([task(1, "a", chunk=9)])
        with self.assertRaises(PlanError):
            read_plan(self.write(plan_html(bad_chunk)))
        bad_dependency = toy_plan([task(1, "a", depends_on=[5])])
        with self.assertRaises(PlanError):
            read_plan(self.write(plan_html(bad_dependency)))

    def test_string_ids_are_rejected(self) -> None:
        plan = toy_plan([task(1, "a")])
        plan["tasks"][0]["id"] = "one"
        with self.assertRaises(PlanError):
            read_plan(self.write(plan_html(plan)))

    def test_seed_refuses_a_second_time(self) -> None:
        plan = toy_plan([task(1, "a")])
        flight = Flight(self.dir).create("g", "b", "0" * 40)
        parsed = read_plan(self.write(plan_html(plan)))
        seed_flight(flight, parsed)
        with self.assertRaises(Exception):
            seed_flight(flight, parsed)


if __name__ == "__main__":
    unittest.main()
