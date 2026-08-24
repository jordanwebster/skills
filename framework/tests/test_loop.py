from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from scaffold.adapters.fake import FakeAdapter
from scaffold.loop import run_loop
from scaffold.plan import import_plan, retained_plan_path
from scaffold.store import Store, initial_state


def git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return completed.stdout


def task(task_id: str, *, depends_on: list[str] | None = None) -> dict[str, object]:
    return {
        "id": task_id,
        "title": f"Do {task_id}",
        "role": "implementer",
        "effort": "small",
        "check": f"check-{task_id}",
        "depends_on": list(depends_on or []),
        "decisions": [f"{task_id} stays in scope"],
    }


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
        + "\n</script>\n",
        encoding="utf-8",
    )
    return path


class LoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.product = self.root / "product"
        self.product.mkdir()
        git(self.product, "init", "--quiet")
        git(self.product, "config", "user.name", "Toy Worker")
        git(self.product, "config", "user.email", "toy@example.invalid")
        (self.product / "README.md").write_text("# Toy\n", encoding="utf-8")
        git(self.product, "add", "README.md")
        git(self.product, "commit", "--quiet", "-m", "Initialize toy product")
        self.store = Store(self.root / "flight")
        self.store.create(initial_state("Build the toy"))
        self.plan_path = write_plan(
            self.root / "plan.html",
            [task("first"), task("wrap", depends_on=["first"])],
        )
        import_plan(self.store, self.plan_path)

    def write_script(self, steps: list[dict[str, object]]) -> Path:
        path = self.root / "fake.json"
        path.write_text(json.dumps({"steps": steps}) + "\n", encoding="utf-8")
        return path

    def test_fake_loop_runs_dependency_graph_to_green(self) -> None:
        script = self.write_script(
            [
                {
                    "task_id": "first",
                    "commit_message": "Build first artifact",
                    "writes": {"first.txt": "first\n"},
                },
                {
                    "task_id": "wrap",
                    "commit_message": "Wrap toy product",
                    "writes": {"wrapped.txt": "wrapped\n"},
                },
            ]
        )

        result = run_loop(
            self.store,
            self.product,
            FakeAdapter(script, self.store),
            holder="fake-worker",
            durable_paths=(retained_plan_path(self.store),),
        )

        self.assertEqual("complete", result.status)
        self.assertEqual(("first", "wrap"), result.completed_task_ids)
        state = self.store.load()
        self.assertTrue(all(item["verdict"] == "green" for item in state["tasks"]))
        self.assertEqual("3", git(self.product, "rev-list", "--count", "HEAD").strip())
        self.assertEqual("", git(self.product, "status", "--porcelain"))
        events = (self.store.root / "events.log").read_text(encoding="utf-8")
        self.assertIn("segment 1: first", events)
        self.assertIn("segment 2: wrap", events)
        prompt = (self.store.root / "prompts" / "wrap.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn('"id": "wrap"', prompt)
        self.assertIn("Readable plan", prompt)

    def test_worker_failure_releases_lease_and_ends_slice(self) -> None:
        script = self.write_script(
            [
                {
                    "task_id": "wrong-task",
                    "commit_message": "Never reached",
                    "writes": {"wrong.txt": "wrong\n"},
                }
            ]
        )

        result = run_loop(
            self.store,
            self.product,
            FakeAdapter(script, self.store),
            holder="fake-worker",
        )

        self.assertEqual("failed", result.status)
        first = self.store.load()["tasks"][0]
        self.assertEqual(1, first["attempts"]["work"])
        self.assertIsNone(first["lease"])
        self.assertEqual("pending", first["completion"])


if __name__ == "__main__":
    unittest.main()
