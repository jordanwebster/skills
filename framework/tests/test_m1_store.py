from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scaffold.plan import PlanError, import_plan, read_plan, retained_plan_path
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
            retained_plan_path(self.store).read_text(encoding="utf-8"),
            (self.root / "plan.html").read_text(encoding="utf-8"),
        )

    def test_rejected_reimport_cannot_replace_the_active_plan_source(self) -> None:
        first_path = write_plan(self.root / "first.html", [task("first")])
        self.import_tasks([task("first")])
        active_path = retained_plan_path(self.store)
        active_source = active_path.read_text(encoding="utf-8")
        second_path = write_plan(self.root / "second.html", [task("replacement")])

        with self.assertRaisesRegex(InvalidTransition, "already"):
            import_plan(self.store, second_path)

        self.assertEqual(active_path, retained_plan_path(self.store))
        self.assertEqual(active_source, active_path.read_text(encoding="utf-8"))
        self.assertNotEqual(
            first_path.read_text(encoding="utf-8"),
            second_path.read_text(encoding="utf-8"),
        )

    def test_reimport_same_machine_block_cannot_change_retained_prose(self) -> None:
        first_path = write_plan(self.root / "first.html", [task("first")])
        import_plan(self.store, first_path)
        active_path = retained_plan_path(self.store)
        active_source = active_path.read_bytes()
        second_path = write_plan(self.root / "second.html", [task("first")])
        second_path.write_text(
            second_path.read_text(encoding="utf-8").replace(
                "<h1>Readable plan</h1>",
                "<h1>Changed readable plan</h1>",
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(PlanError, "different bytes"):
            import_plan(self.store, second_path)

        self.assertEqual(active_source, active_path.read_bytes())
        self.assertNotEqual(active_source, second_path.read_bytes())

    def test_reimport_identical_source_leaves_retained_file_untouched(self) -> None:
        plan_path = write_plan(self.root / "plan.html", [task("first")])
        import_plan(self.store, plan_path)
        active_path = retained_plan_path(self.store)
        active_stat = active_path.stat()

        with self.assertRaisesRegex(InvalidTransition, "already"):
            import_plan(self.store, plan_path)

        unchanged_stat = active_path.stat()
        self.assertEqual(active_stat.st_ino, unchanged_stat.st_ino)
        self.assertEqual(active_stat.st_mtime_ns, unchanged_stat.st_mtime_ns)

    def test_task_id_cannot_escape_workspace_paths(self) -> None:
        plan = write_plan(self.root / "traversal.html", [task("../escape")])

        with self.assertRaisesRegex(ValueError, "task id"):
            import_plan(self.store, plan)

        self.assertFalse((self.root / "escape.json").exists())
        self.assertEqual([], self.store.load()["tasks"])

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

    def test_two_processes_contending_for_the_store_get_one_lease(self) -> None:
        self.import_tasks([task("first"), task("other")])
        barrier = self.root / "start-workers"
        worker = """
import pathlib
import sys
import time
from scaffold.store import Store, TaskUnavailable

store_root, task_id, barrier_path = sys.argv[1:]
barrier = pathlib.Path(barrier_path)
while not barrier.exists():
    time.sleep(0.001)
try:
    Store(store_root).claim(task_id, task_id + '-worker', ttl_seconds=30)
except TaskUnavailable:
    print('unavailable')
else:
    print('claimed')
"""
        environment = os.environ.copy()
        framework_root = str(Path(__file__).parents[1])
        environment["PYTHONPATH"] = framework_root
        processes = [
            subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    worker,
                    str(self.store.root),
                    task_id,
                    str(barrier),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )
            for task_id in ("first", "other")
        ]
        barrier.touch()
        outputs = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=10)
            self.assertEqual(0, process.returncode, stderr)
            outputs.append(stdout.strip())

        self.assertEqual(["claimed", "unavailable"], sorted(outputs))
        live_leases = [
            item for item in self.store.load()["tasks"] if item["lease"] is not None
        ]
        self.assertEqual(1, len(live_leases))

    def test_typed_claim_does_not_flip_until_framework_apply(self) -> None:
        self.import_tasks([task("first"), task("second", depends_on=["first"])])
        lease = self.store.claim("first", "worker-a")
        source = self.root / "claim.json"
        source.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "task_id": "first",
                    "holder": "worker-a",
                    "lease_id": lease.lease_id,
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
                "lease_id": lease.lease_id,
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
        lease = self.store.claim("first", "worker-a", ttl_seconds=10, now=100)
        source = self.root / "late-claim.json"
        source.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "task_id": "first",
                    "holder": "worker-a",
                    "lease_id": lease.lease_id,
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
        lease = self.store.claim("first", "worker-a")

        with self.assertRaisesRegex(InvalidTransition, "no filed claim"):
            self.store.apply(
                {
                    "type": "task-verified",
                    "task_id": "first",
                    "holder": "worker-a",
                    "lease_id": lease.lease_id,
                    "verified_head": "abc123",
                }
            )

        self.assertEqual("pending", self.store.load()["tasks"][0]["completion"])

    def test_claim_from_an_earlier_lease_cannot_complete_a_later_lease(self) -> None:
        self.import_tasks([task("first")])
        first_lease = self.store.claim("first", "same-worker")
        source = self.root / "first-claim.json"
        source.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "task_id": "first",
                    "holder": "same-worker",
                    "lease_id": first_lease.lease_id,
                    "claim": "passes",
                    "candidate_head": "abc123",
                    "artifacts": ["first.txt"],
                }
            ),
            encoding="utf-8",
        )
        self.store.file_claim("first", source)
        self.store.apply(
            {
                "type": "task-released",
                "task_id": "first",
                "holder": "same-worker",
                "lease_id": first_lease.lease_id,
                "attempt_type": "work",
            }
        )
        second_lease = self.store.claim("first", "same-worker")

        self.assertNotEqual(first_lease.lease_id, second_lease.lease_id)
        with self.assertRaisesRegex(InvalidTransition, "filed claim"):
            self.store.apply(
                {
                    "type": "task-verified",
                    "task_id": "first",
                    "holder": "same-worker",
                    "lease_id": second_lease.lease_id,
                    "verified_head": "abc123",
                }
            )

    def test_m0_state_without_plan_digest_migrates_and_imports(self) -> None:
        legacy_root = self.root / "legacy-flight"
        legacy_root.mkdir()
        legacy_state = initial_state("Build the toy")
        legacy_state.pop("plan_digest")
        canonical = json.dumps(
            legacy_state,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        entry = {
            "sequence": 1,
            "transition": {"type": "initialized"},
            "state_hash": hashlib.sha256(canonical).hexdigest(),
            "state_after": legacy_state,
        }
        (legacy_root / "journal.jsonl").write_text(
            json.dumps(entry) + "\n", encoding="utf-8"
        )
        (legacy_root / "tasks.json").write_text(
            json.dumps(legacy_state) + "\n", encoding="utf-8"
        )
        legacy_store = Store(legacy_root)

        self.assertIsNone(legacy_store.load()["plan_digest"])
        import_plan(
            legacy_store,
            write_plan(self.root / "legacy-plan.html", [task("first")]),
        )
        self.assertEqual(["first"], [item["id"] for item in legacy_store.ready()])

    def test_unchecked_state_replacement_is_not_a_public_store_api(self) -> None:
        self.assertFalse(hasattr(self.store, "replace"))


if __name__ == "__main__":
    unittest.main()
