from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from autopilot.plan import PlanError, plan_roles, read_plan, seed_flight
from autopilot.state import Flight

from helpers import SKILL_DIR, plan_markdown, task, toy_plan


class PlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.dir = Path(self.temporary.name)

    def write(self, text: str) -> Path:
        path = self.dir / "plan.md"
        path.write_text(text)
        return path

    def test_shipped_template_parses(self) -> None:
        plan = read_plan(SKILL_DIR / "templates" / "flight-plan.md")
        self.assertEqual(plan["chunks"][0]["id"], 1)
        self.assertEqual(plan["tasks"][0]["chunk"], 1)
        self.assertEqual(plan["config"]["preflight"], ["timeout 60 npx playwright --version"])

    def test_plan_roles_cover_chunks_tasks_review_and_closer(self) -> None:
        plan = toy_plan(
            [task(1, "a", role="prober"), task(2, "b")],
            chunks=[{"id": 1, "title": "one", "role": "ui-developer"}],
        )
        self.assertEqual(plan_roles(plan), ["planner", "ui-developer", "prober", "reviewer", "closer"])
        plan["chunks"][0]["review"] = False
        self.assertNotIn("reviewer", plan_roles(plan))

    def test_other_json_blocks_are_ignored(self) -> None:
        text = "```json\n{\"shape\": 1}\n```\n" + plan_markdown(toy_plan([task(1, "a")]))
        self.assertEqual(read_plan(self.write(text))["goal"], "Build the toy")

    def test_seed_copies_chunks_tasks_and_config(self) -> None:
        plan = toy_plan(
            [task(1, "a"), task(2, "b", depends_on=[1], role="qa-tester")],
            config={"max_iterations": 7, "check": "true"},
        )
        flight = Flight(self.dir).create("placeholder", "b", "0" * 40)
        seed_flight(flight, read_plan(self.write(plan_markdown(plan))))
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
            read_plan(self.write("# no block\n"))

    def test_two_blocks_are_an_error(self) -> None:
        text = plan_markdown(toy_plan([task(1, "a")])) * 2
        with self.assertRaises(PlanError):
            read_plan(self.write(text))

    def test_unknown_chunk_and_dependency_are_errors(self) -> None:
        bad_chunk = toy_plan([task(1, "a", chunk=9)])
        with self.assertRaises(PlanError):
            read_plan(self.write(plan_markdown(bad_chunk)))
        bad_dependency = toy_plan([task(1, "a", depends_on=[5])])
        with self.assertRaises(PlanError):
            read_plan(self.write(plan_markdown(bad_dependency)))

    def test_string_ids_are_rejected(self) -> None:
        plan = toy_plan([task(1, "a")])
        plan["tasks"][0]["id"] = "one"
        with self.assertRaises(PlanError):
            read_plan(self.write(plan_markdown(plan)))

    def test_seed_refuses_a_second_time(self) -> None:
        plan = toy_plan([task(1, "a")])
        flight = Flight(self.dir).create("g", "b", "0" * 40)
        parsed = read_plan(self.write(plan_markdown(plan)))
        seed_flight(flight, parsed)
        with self.assertRaises(Exception):
            seed_flight(flight, parsed)

    def test_not_replayable_recipe_records_the_accepted_boundary(self) -> None:
        plan = toy_plan([task(1, "a")])
        plan["evidence"][0]["replay"] = {
            "kind": "not_replayable",
            "accepted_reason": "The observation is production-only.",
            "limitation": "It cannot be recreated locally.",
        }
        read_plan(self.write(plan_markdown(plan)))

        plan["evidence"][0]["replay"] = {
            "kind": "not_replayable",
            "reason": "Legacy ambiguous reason.",
        }
        with self.assertRaisesRegex(PlanError, "accepted_reason and limitation"):
            read_plan(self.write(plan_markdown(plan)))


if __name__ == "__main__":
    unittest.main()
