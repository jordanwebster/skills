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

    def test_expected_dispatch_range_must_fit_the_hard_maximum(self) -> None:
        plan = toy_plan([task(1, "a")], config={"max_iterations": 5})
        plan["config"]["expected_iterations"] = {"min": 3, "max": 6}
        with self.assertRaisesRegex(PlanError, "expected_iterations"):
            read_plan(self.write(plan_markdown(plan)))

        plan["config"]["expected_iterations"] = {"min": 2, "max": 5}
        parsed = read_plan(self.write(plan_markdown(plan)))
        self.assertEqual(parsed["config"]["expected_iterations"], {"min": 2, "max": 5})

    def test_operator_contract_requires_causal_route_and_approval_row(self) -> None:
        source = plan_markdown(toy_plan([task(1, "a")]))
        with self.assertRaisesRegex(PlanError, "Validated By"):
            read_plan(self.write(source.replace("- **Validated by:** A fast deterministic boundary check.\n", "")))
        with self.assertRaisesRegex(PlanError, "Approve this route"):
            read_plan(self.write(source.replace("Approve this route", "Start whenever")))

    def test_a_plan_without_a_shape_is_not_a_design(self) -> None:
        source = plan_markdown(toy_plan([task(1, "a")]))
        shape = source[source.index("## Shape"):source.index("## Human judgment")]
        with self.assertRaisesRegex(PlanError, "needs a ## Shape section"):
            read_plan(self.write(source.replace(shape, "")))

    def test_a_shape_names_components_interfaces_and_data(self) -> None:
        source = plan_markdown(toy_plan([task(1, "a")]))
        with self.assertRaisesRegex(PlanError, r"### Data shapes"):
            read_plan(self.write(source.replace(
                "### Data shapes\n\n- **Result** — the text the toy produced.\n", ""
            )))
        with self.assertRaisesRegex(PlanError, r"### Interfaces and APIs"):
            read_plan(self.write(source.replace(
                "- `toy()` — returns the result, never raises.\n", ""
            )))
        contract = read_plan(self.write(source))["_operator"]
        self.assertIn("### Components", contract["shape"])

    def _two_milestone_source(self, *, first_extra: str = "", second_extra: str = "") -> str:
        plan = toy_plan(
            [task(1, "a"), task(2, "b", chunk=2)],
            chunks=[
                {"id": 1, "title": "Survey", "role": "prober", "review": False},
                {"id": 2, "title": "Build", "role": "implementer", "check": "true"},
            ],
        )
        plan["evidence"][0]["stages"] = [2]
        source = plan_markdown(plan)
        if first_extra:
            source = source.replace(
                "- **Validated by:** A fast deterministic boundary check.\n\n### Milestone 2",
                "- **Validated by:** A fast deterministic boundary check.\n" + first_extra + "\n### Milestone 2",
            )
        if second_extra:
            source = source.replace(
                "- **Validated by:** A fast deterministic boundary check.\n\n## Shape",
                "- **Validated by:** A fast deterministic boundary check.\n" + second_extra + "\n## Shape",
            )
        return source

    def test_a_research_branch_needs_a_question_outcomes_and_one_default(self) -> None:
        good = self._two_milestone_source(first_extra=(
            "- **Branch:** Which encoding is canonical?\n"
            "  - If only the newer one appears → M2 builds one decoder (default)\n"
            "  - If both appear → M2 splits\n"
        ))
        branch = read_plan(self.write(good))["_operator"]["routes"][0]["branch"]
        self.assertEqual("Which encoding is canonical?", branch["question"])
        self.assertEqual([True, False], [item["default"] for item in branch["outcomes"]])

        with self.assertRaisesRegex(PlanError, "as a question"):
            read_plan(self.write(good.replace("Which encoding is canonical?", "The canonical encoding.")))
        with self.assertRaisesRegex(PlanError, "at least two outcomes"):
            read_plan(self.write(good.replace("  - If both appear → M2 splits\n", "")))
        with self.assertRaisesRegex(PlanError, "exactly one outcome marked"):
            read_plan(self.write(good.replace(" (default)", "")))

    def test_a_test_infrastructure_stage_names_later_milestones_and_what_it_buys(self) -> None:
        good = self._two_milestone_source(first_extra=(
            "- **Enables:** M2 — replayed from recorded fixtures, offline and deterministic.\n"
        ))
        enables = read_plan(self.write(good))["_operator"]["routes"][0]["enables"]
        self.assertEqual([2], enables["milestones"])

        with self.assertRaisesRegex(PlanError, "must name the later milestones"):
            read_plan(self.write(good.replace("M2 — replayed", "Later work — replayed")))
        with self.assertRaisesRegex(PlanError, "unknown milestone M7"):
            read_plan(self.write(good.replace("M2 — replayed", "M7 — replayed")))
        with self.assertRaisesRegex(PlanError, "what the capability gives"):
            read_plan(self.write(good.replace("offline and deterministic", "somehow better")))

    def test_a_later_stage_cannot_be_enabled_by_one_that_follows_it(self) -> None:
        source = self._two_milestone_source(second_extra=(
            "- **Enables:** M1 — replayed offline and deterministically.\n"
        ))
        with self.assertRaisesRegex(PlanError, "not a later milestone"):
            read_plan(self.write(source))

    def test_a_milestone_reference_that_names_nothing_is_rejected(self) -> None:
        source = plan_markdown(toy_plan([task(1, "a")]))
        source = source.replace("- **Unlocks:** The next planned boundary.", "- **Unlocks:** M4 decoding.")
        with self.assertRaisesRegex(PlanError, "refers to M4"):
            read_plan(self.write(source))

    def test_the_title_and_stage_fields_stay_within_their_budgets(self) -> None:
        source = plan_markdown(toy_plan([task(1, "a")]))
        long_title = "# " + "T" * 71
        with self.assertRaisesRegex(PlanError, "characters; keep it under 70"):
            read_plan(self.write(source.replace("# Toy plan", long_title)))

        essay = "- **Produces:** " + "word " * 90
        with self.assertRaisesRegex(PlanError, "keep a stage field under 400"):
            read_plan(self.write(source.replace("- **Produces:** The Files result.", essay)))


    def test_evidence_names_every_stage_that_delivers_or_captures_it(self) -> None:
        plan = toy_plan([task(1, "a")])
        del plan["evidence"][0]["stages"]
        with self.assertRaisesRegex(PlanError, "stages"):
            read_plan(self.write(plan_markdown(plan)))

        plan = toy_plan([task(1, "a")])
        plan["evidence"][0]["stages"] = [9]
        with self.assertRaisesRegex(PlanError, "unknown stage"):
            read_plan(self.write(plan_markdown(plan)))


if __name__ == "__main__":
    unittest.main()
