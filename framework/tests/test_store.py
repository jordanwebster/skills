from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scaffold.store import Store, StoreCorruption, StoreExists, initial_state


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name) / "flight"
        self.store = Store(self.root)

    def test_create_persists_state_and_initial_transition(self) -> None:
        state = initial_state("Build a tiny product", test_paths=["tests/**"])

        created = self.store.create(state)

        self.assertEqual(state, created)
        self.assertEqual(state, self.store.load())
        entries = self.store.read_journal()
        self.assertEqual(1, len(entries))
        self.assertEqual(1, entries[0]["sequence"])
        self.assertEqual("initialized", entries[0]["transition"]["type"])
        self.assertEqual(state, entries[0]["state_after"])

    def test_create_refuses_to_overwrite_existing_store(self) -> None:
        self.store.create(initial_state("Keep this"))

        with self.assertRaises(StoreExists):
            self.store.create(initial_state("Replace this"))

        self.assertEqual("Keep this", self.store.load()["goal"])

    def test_replace_appends_transition_and_materializes_state(self) -> None:
        state = self.store.create(initial_state("Build it"))
        state["tasks"].append({"id": "task-1", "completion": "pending"})

        replaced = self.store.replace(
            state,
            {"type": "task-imported", "task_id": "task-1"},
        )

        self.assertEqual(state, replaced)
        self.assertEqual(state, self.store.load())
        entries = self.store.read_journal()
        self.assertEqual([1, 2], [entry["sequence"] for entry in entries])
        self.assertEqual("task-imported", entries[-1]["transition"]["type"])

    def test_load_recovers_missing_or_stale_materialized_state(self) -> None:
        state = self.store.create(initial_state("Recover it"))
        state["tasks"].append({"id": "task-1"})
        self.store.replace(state, {"type": "task-imported"})
        self.store.state_path.write_text("{}\n", encoding="utf-8")

        recovered = self.store.load()

        self.assertEqual(state, recovered)
        self.assertEqual(
            state,
            json.loads(self.store.state_path.read_text(encoding="utf-8")),
        )

    def test_torn_trailing_journal_row_is_dropped(self) -> None:
        state = self.store.create(initial_state("Survive a tear"))
        with self.store.journal_path.open("ab") as handle:
            handle.write(b'{"sequence":2')

        self.assertEqual(state, self.store.load())
        self.assertEqual(1, len(self.store.read_journal()))
        self.assertTrue(self.store.journal_path.read_bytes().endswith(b"\n"))

        state["tasks"].append({"id": "after-recovery"})
        self.store.replace(state, {"type": "task-imported"})
        self.assertEqual([1, 2], [
            entry["sequence"] for entry in self.store.read_journal()
        ])

    def test_interior_journal_corruption_fails_closed_with_position(self) -> None:
        self.store.create(initial_state("Detect corruption"))
        with self.store.journal_path.open("ab") as handle:
            handle.write(b"not-json\n")
            handle.write(b'{"sequence":3')

        with self.assertRaisesRegex(StoreCorruption, "complete line 2"):
            self.store.load()

    def test_journal_hash_mismatch_fails_closed(self) -> None:
        self.store.create(initial_state("Detect tampering"))
        rows = self.store.journal_path.read_text(encoding="utf-8").splitlines()
        entry = json.loads(rows[0])
        entry["state_after"]["goal"] = "Changed without a transition"
        self.store.journal_path.write_text(json.dumps(entry) + "\n", encoding="utf-8")

        with self.assertRaisesRegex(StoreCorruption, "state hash mismatch"):
            self.store.load()

    def test_state_schema_is_validated_before_any_write(self) -> None:
        invalid = initial_state("Reject it")
        invalid["schema_version"] = 99

        with self.assertRaisesRegex(ValueError, "schema_version"):
            self.store.create(invalid)

        self.assertFalse(self.root.exists())


if __name__ == "__main__":
    unittest.main()
