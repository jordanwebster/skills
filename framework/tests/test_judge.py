from __future__ import annotations

import unittest

from scaffold.judge import CLOSED_DECISIONS, normalize_decision


class JudgeContractTests(unittest.TestCase):
    def test_closed_decision_enum_round_trips(self) -> None:
        for decision in CLOSED_DECISIONS:
            with self.subTest(decision=decision):
                value = {
                    "schema_version": 1,
                    "task_id": "task-1",
                    "trigger": "retry-cap",
                    "decision": decision,
                    "reason": "A bounded decision.",
                }
                self.assertEqual(
                    value,
                    normalize_decision(
                        value,
                        task_id="task-1",
                        trigger="retry-cap",
                    ),
                )

    def test_unknown_decision_and_mismatched_trigger_fail_closed(self) -> None:
        value = {
            "schema_version": 1,
            "task_id": "task-1",
            "trigger": "retry-cap",
            "decision": "try-again",
            "reason": "Unbounded retry.",
        }
        with self.assertRaisesRegex(ValueError, "closed decision enum"):
            normalize_decision(value)

        value["decision"] = "park"
        with self.assertRaisesRegex(ValueError, "different trigger"):
            normalize_decision(value, trigger="ambiguity")


if __name__ == "__main__":
    unittest.main()
