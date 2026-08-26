from __future__ import annotations

import json
import unittest

from autopilot import approval, prompt
from autopilot.plan import plan_bindings, read_plan
from autopilot.roster import Roster
from autopilot.state import StateError

from helpers import FlightCase, task, toy_plan, write_roster


class ApprovalTests(FlightCase):
    def test_receipt_is_narrow_and_current(self) -> None:
        flight = self.seed(toy_plan([task(1, "a")]))
        receipt = json.loads(flight.approval_path.read_text())
        self.assertEqual(
            set(receipt),
            {"schema_version", "acceptance_digest", "plan_digest", "staffing_digest", "confirmed_at"},
        )
        approval.validate(flight, read_plan(flight.plan_path), self.roster)

    def test_plan_or_acceptance_drift_requires_reapproval(self) -> None:
        flight = self.seed(toy_plan([task(1, "a")]))
        original = flight.plan_path.read_text()
        flight.plan_path.write_text(original + "\nMaterial revision.\n")
        with self.assertRaisesRegex(StateError, "plan digest"):
            approval.validate(flight, read_plan(flight.plan_path), self.roster)

        flight.plan_path.write_text(original)
        flight.requirements_path.write_text(flight.requirements_path.read_text() + "Changed.\n")
        with self.assertRaisesRegex(StateError, "acceptance confirmation is stale"):
            approval.validate(flight, read_plan(flight.plan_path), self.roster)

    def test_acceptance_receipt_must_stay_narrow_and_record_confirmation(self) -> None:
        flight = self.seed(toy_plan([task(1, "a")]))
        receipt = json.loads(flight.acceptance_receipt_path.read_text())
        receipt.pop("confirmed_at")
        flight.acceptance_receipt_path.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(StateError, "acceptance receipt is invalid"):
            approval.validate_acceptance_files(flight.requirements_path, flight.acceptance_receipt_path)

        receipt["confirmed_at"] = "2026-01-01T00:00:00+00:00"
        receipt["extra_receipt"] = True
        flight.acceptance_receipt_path.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(StateError, "acceptance receipt is invalid"):
            approval.validate_acceptance_files(flight.requirements_path, flight.acceptance_receipt_path)

    def test_semantic_staffing_drift_matters_but_transport_path_does_not(self) -> None:
        flight = self.seed(toy_plan([task(1, "a")]))
        alternate = write_roster(self.base / "alternate.toml", cli="/usr/bin/python3")
        path_only = Roster(environment=dict(self.env, DELEGATE_ROSTER=str(alternate)))
        approval.validate(flight, read_plan(flight.plan_path), path_only)

        text = alternate.read_text().replace('model = "fake"', 'model = "different"')
        alternate.write_text(text)
        changed = Roster(environment=dict(self.env, DELEGATE_ROSTER=str(alternate)))
        with self.assertRaisesRegex(StateError, "staffing digest"):
            approval.validate(flight, read_plan(flight.plan_path), changed)

    def test_actual_role_effort_combinations_are_resolved(self) -> None:
        plan = toy_plan(
            [
                {**task(1, "a"), "effort": "high"},
                task(2, "b", role="qa-tester"),
            ],
            chunks=[{"id": 1, "title": "one", "role": "implementer", "effort": "medium"}],
        )
        self.assertEqual(
            plan_bindings(plan),
            [
                ("planner", None),
                ("implementer", "medium"),
                ("implementer", "high"),
                ("qa-tester", "medium"),
                ("reviewer", None),
                ("closer", None),
            ],
        )

    def test_revision_prompt_contains_only_the_explicit_revision_packet(self) -> None:
        flight = self.seed(toy_plan([task(1, "a")]))
        text = prompt.planner_prompt(
            flight,
            feedback="Use the repository boundary.",
            reason="The old boundary was rejected.",
            observations="The adapter already exists.",
        )
        self.assertIn("### Current plan", text)
        self.assertIn("Use the repository boundary.", text)
        self.assertIn("The old boundary was rejected.", text)
        self.assertIn("The adapter already exists.", text)
        self.assertIn("exploratory conversation is intentionally absent", text)


if __name__ == "__main__":
    unittest.main()
