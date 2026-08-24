from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scaffold.plan import PlanError, import_plan, read_plan
from scaffold.store import (
    InvalidTransition,
    Store,
    TaskUnavailable,
    initial_state,
)


def write_plan(path: Path, tasks: list[dict[str, object]]) -> Path:
    machine = {
        "schema_version": 1,
        "goal": "Build the toy",
        "test_paths": ["tests/**"],
        "tasks": tasks,
    }
    path.write_text(
        "<h1>Readable plan</h1>\n"
        '<script type="application/json" id="scaffold-plan">\n'
        + json.dumps(machine)
        + "\n</script>\n"
        "<p>Prose after the machine block is ignored.</p>\n",
        encoding="utf-8",
    )
    return path


def task(
    task_id: str,
    *,
    role: str = "implementer",
    depends_on: list[str] | None = None,
) -> dict[str, object]:
    return {
        "id": task_id,
        "title": f"Do {task_id}",
        "role": role,
        "effort": "small",
        "check": f"check-{task_id}",
        "depends_on": list(depends_on or []),
        "decisions": [f"{task_id} stays in scope"],
    }


class PlanAndFrontierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.store = Store(self.root / "flight")
        self.store.create(initial_state("Build the toy"))

    def import_tasks(self, tasks: list[dict[str, object]]) -> None:
        import_plan(self.store, write_plan(self.root / "plan.html", tasks))

    def test_plan_import_reads_machine_block_and_materializes_full_tasks(self) -> None:
        self.import_tasks([task("first"), task("second", depends_on=["first"])])

        state = self.store.load()

        self.assertEqual(["first", "second"], [item["id"] for item in state["tasks"]])
        self.assertEqual("pending", state["tasks"][0]["completion"])
        self.assertIsNone(state["tasks"][0]["verdict"])
        self.assertEqual(
            "plan-imported",
            self.store.read_journal()[-1]["transition"]["type"],
        )
        self.assertEqual(
            (self.store.root / "inputs" / "plan.html").read_text(encoding="utf-8"),
            (self.root / "plan.html").read_text(encoding="utf-8"),
        )

    def test_plan_requires_exactly_one_typed_machine_block(self) -> None:
        invalid = self.root / "invalid.html"
        invalid.write_text("<p>Only readable prose</p>\n", encoding="utf-8")

        with self.assertRaisesRegex(PlanError, "exactly one"):
            read_plan(invalid)

    def test_invalid_dependency_graph_fails_before_a_transition_is_written(self) -> None:
        plan = write_plan(
            self.root / "cyclic.html",
            [task("first", depends_on=["second"]), task("second", depends_on=["first"])],
        )

        with self.assertRaisesRegex(ValueError, "cycle"):
            import_plan(self.store, plan)

        self.assertEqual(1, len(self.store.read_journal()))
        self.assertEqual([], self.store.load()["tasks"])

    def test_frontier_is_in_plan_order_dependency_aware_and_profile_filtered(self) -> None:
        self.import_tasks(
            [
                task("first"),
                task("review", role="reviewer"),
                task("second", depends_on=["first"]),
            ]
        )

        self.assertEqual(
            ["first", "review"],
            [item["id"] for item in self.store.ready(now=10)],
        )
        self.assertEqual(
            ["first"],
            [item["id"] for item in self.store.ready("implementer", now=10)],
        )
        self.assertEqual(
            ["review"],
            [item["id"] for item in self.store.ready("reviewer", now=10)],
        )

    def test_live_lease_blocks_a_second_worker_and_expiry_requeues(self) -> None:
        self.import_tasks([task("first"), task("other")])

        lease = self.store.claim("first", "worker-a", ttl_seconds=10, now=100)

        self.assertEqual(110, lease.expires_at)
        with self.assertRaisesRegex(TaskUnavailable, "active lease"):
            self.store.claim("other", "worker-b", now=105)
        self.assertEqual(
            ["first", "other"],
            [item["id"] for item in self.store.ready(now=111)],
        )
        reclaimed = self.store.claim("first", "worker-b", now=111)
        self.assertEqual("worker-b", reclaimed.holder)
        self.assertTrue(self.store.read_journal()[-1]["transition"]["reclaimed"])

    def test_typed_claim_does_not_flip_until_framework_apply(self) -> None:
        self.import_tasks([task("first"), task("second", depends_on=["first"])])
        self.store.claim("first", "worker-a")
        source = self.root / "claim.json"
        source.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "task_id": "first",
                    "holder": "worker-a",
                    "claim": "passes",
                    "candidate_head": "abc123",
                    "artifacts": ["first.txt"],
                }
            ),
            encoding="utf-8",
        )

        self.store.file_claim("first", source)

        self.assertEqual("pending", self.store.load()["tasks"][0]["completion"])
        self.assertEqual([], self.store.ready("implementer", now=101))
        self.store.apply(
            {
                "type": "task-verified",
                "task_id": "first",
                "holder": "worker-a",
                "verified_head": "abc123",
            }
        )
        state = self.store.load()
        self.assertEqual("complete", state["tasks"][0]["completion"])
        self.assertEqual("green", state["tasks"][0]["verdict"])
        self.assertEqual(
            ["second"],
            [item["id"] for item in self.store.ready("implementer", now=101)],
        )

    def test_expired_holder_cannot_file_a_claim(self) -> None:
        self.import_tasks([task("first")])
        self.store.claim("first", "worker-a", ttl_seconds=10, now=100)
        source = self.root / "late-claim.json"
        source.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "task_id": "first",
                    "holder": "worker-a",
                    "claim": "passes",
                    "candidate_head": "abc123",
                    "artifacts": ["first.txt"],
                }
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(InvalidTransition, "expired"):
            self.store.file_claim("first", source, now=111)

    def test_apply_rejects_verification_without_a_matching_claim(self) -> None:
        self.import_tasks([task("first")])
        self.store.claim("first", "worker-a")

        with self.assertRaisesRegex(InvalidTransition, "no filed claim"):
            self.store.apply(
                {
                    "type": "task-verified",
                    "task_id": "first",
                    "holder": "worker-a",
                    "verified_head": "abc123",
                }
            )

        self.assertEqual("pending", self.store.load()["tasks"][0]["completion"])


if __name__ == "__main__":
    unittest.main()
