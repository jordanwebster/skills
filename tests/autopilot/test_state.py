from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from autopilot.state import Flight, StateError


class StateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.flight = Flight(self.temporary.name).create("goal", "branch", "0" * 40)
        self.flight.add_chunk("one", role="prober", check="true")
        self.flight.add_chunk("two")

    def test_ids_are_sequential_ints(self) -> None:
        first = self.flight.add_task("a", chunk=1)
        second = self.flight.add_task("b", chunk=2)
        self.assertEqual((first["id"], second["id"]), (1, 2))
        self.flight.save()
        reloaded = Flight(self.temporary.name).load()
        self.assertEqual([task["id"] for task in reloaded.tasks], [1, 2])

    def test_ready_order_follows_chunks_then_ids(self) -> None:
        self.flight.add_task("later chunk", chunk=2)
        self.flight.add_task("first chunk", chunk=1)
        self.assertEqual([task["title"] for task in self.flight.ready_tasks()], ["first chunk", "later chunk"])

    def test_dependencies_gate_readiness(self) -> None:
        first = self.flight.add_task("a", chunk=1)
        second = self.flight.add_task("b", chunk=1, depends_on=[1])
        self.assertEqual([task["id"] for task in self.flight.ready_tasks()], [1])
        self.flight.set_status(first, "done")
        self.assertEqual([task["id"] for task in self.flight.ready_tasks()], [2])
        self.assertTrue(self.flight.is_ready(second))

    def test_an_unfinished_review_repair_gates_the_milestones_resting_on_it(self) -> None:
        self.flight.add_chunk("three")
        foundation = self.flight.add_task("foundation", chunk=1)
        self.flight.set_status(foundation, "done")
        self.flight.add_task("dependent", chunk=2, depends_on=[1])
        self.flight.add_task("unrelated", chunk=3)
        repair = self.flight.add_task("repair the finding", chunk=1, origin="review")

        self.assertEqual({2}, self.flight.review_gate())
        self.assertEqual([4, 3], [task["id"] for task in self.flight.ready_tasks()])

        self.flight.set_status(repair, "blocked")
        self.assertEqual({2}, self.flight.review_gate(), "a blocked repair still gates")
        self.flight.set_status(repair, "parked")
        self.assertEqual({2}, self.flight.review_gate(), "a parked repair is not a repair")

        self.flight.set_status(repair, "done")
        self.assertEqual(set(), self.flight.review_gate())
        self.assertEqual([2, 3], [task["id"] for task in self.flight.ready_tasks()])

    def test_milestone_dependencies_are_read_from_the_task_graph(self) -> None:
        self.flight.add_chunk("three")
        self.flight.add_task("foundation", chunk=1)
        self.flight.add_task("dependent", chunk=2, depends_on=[1])
        self.flight.add_task("transitively dependent", chunk=3, depends_on=[2])
        self.assertEqual({1: set(), 2: {1}, 3: {1, 2}}, self.flight.chunk_dependencies())

    def test_retry_cap_removes_from_ready(self) -> None:
        task = self.flight.add_task("a", chunk=1)
        task["attempts"] = self.flight.config["retry_cap"]
        self.assertEqual(self.flight.ready_tasks(), [])

    def test_role_defaults_to_chunk(self) -> None:
        inherited = self.flight.add_task("a", chunk=1)
        explicit = self.flight.add_task("b", chunk=1, role="qa-tester")
        self.assertEqual(self.flight.task_role(inherited), "prober")
        self.assertEqual(self.flight.task_role(explicit), "qa-tester")
        self.assertEqual([t["id"] for t in self.flight.ready_tasks(role="prober", chunk=1)], [1])

    def test_escalation_blocks_and_answer_unblocks(self) -> None:
        task = self.flight.add_task("a", chunk=1)
        escalation = self.flight.add_escalation(task["id"], "blocked on X")
        self.assertEqual(task["status"], "blocked")
        self.assertEqual(len(self.flight.open_escalations()), 1)
        self.flight.answer_escalation(escalation["id"], "do Y")
        self.assertEqual(task["status"], "todo")
        self.assertIn("Operator answer: do Y", task["notes"])
        self.assertEqual(self.flight.open_escalations(), [])

    def test_pending_decision_is_not_an_operator_question_and_can_resolve_internally(self) -> None:
        task = self.flight.add_task("a", chunk=1)
        decision = self.flight.add_escalation(task["id"], "repair dependencies", pending_triage=True)
        self.assertEqual(task["status"], "blocked")
        self.assertEqual(self.flight.open_escalations(), [])
        self.assertEqual(self.flight.pending_triage(), [decision])
        self.flight.resolve_escalation(decision["id"], "dependency order repaired")
        self.assertEqual(task["status"], "todo")
        self.assertIn("Internal decision: dependency order repaired", task["notes"])
        self.assertEqual(self.flight.pending_triage(), [])

    def test_pending_decision_can_be_promoted_before_operator_answer(self) -> None:
        task = self.flight.add_task("a", chunk=1)
        decision = self.flight.add_escalation(task["id"], "scope is unclear", pending_triage=True)
        self.flight.promote_escalation(decision["id"], "Choose whether to expand scope")
        self.assertEqual(self.flight.open_escalations(), [decision])
        self.flight.answer_escalation(decision["id"], "do not expand")
        self.assertEqual(task["status"], "todo")
        self.assertEqual(decision["state"], "resolved")

    def test_legacy_unanswered_escalation_remains_an_operator_question(self) -> None:
        task = self.flight.add_task("a", chunk=1)
        decision = self.flight.add_escalation(task["id"], "legacy question")
        decision.pop("state")
        self.assertEqual(self.flight.open_escalations(), [decision])
        self.assertEqual(self.flight.pending_triage(), [])

    def test_adding_a_task_reopens_a_done_chunk(self) -> None:
        chunk = self.flight.chunk(2)
        chunk["status"] = "done"
        self.flight.add_task("late", chunk=2)
        self.assertEqual(chunk["status"], "open")
        self.flight.add_task("follow-up", chunk=2, status="parked")
        self.assertEqual(len(self.flight.parked_tasks()), 1)

    def test_unknown_dependency_is_rejected(self) -> None:
        with self.assertRaises(StateError):
            self.flight.add_task("a", chunk=1, depends_on=[99])

    def test_dependency_edits_cannot_create_a_cycle(self) -> None:
        first = self.flight.add_task("a", chunk=1)
        second = self.flight.add_task("b", chunk=1, depends_on=[first["id"]])
        with self.assertRaisesRegex(StateError, "acyclic"):
            self.flight.set_dependencies(first["id"], [second["id"]])
        self.assertEqual(first["depends_on"], [])

    def test_find_walks_up_from_a_subdirectory(self) -> None:
        self.flight.save()
        nested = Path(self.temporary.name) / "src" / "deep"
        nested.mkdir(parents=True)
        self.assertEqual(Flight.find(nested).root, self.flight.root)


if __name__ == "__main__":
    unittest.main()
