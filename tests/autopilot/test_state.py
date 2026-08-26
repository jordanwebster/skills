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

    def test_find_walks_up_from_a_subdirectory(self) -> None:
        self.flight.save()
        nested = Path(self.temporary.name) / "src" / "deep"
        nested.mkdir(parents=True)
        self.assertEqual(Flight.find(nested).root, self.flight.root)


if __name__ == "__main__":
    unittest.main()
