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


def task(
    task_id: str,
    *,
    depends_on: list[str] | None = None,
    check: str | None = None,
    test_changes: bool = False,
) -> dict[str, object]:
    return {
        "id": task_id,
        "title": f"Do {task_id}",
        "role": "implementer",
        "effort": "small",
        "check": check or f"python3 checks/check_file.py {task_id}.txt",
        "depends_on": list(depends_on or []),
        "decisions": [f"{task_id} stays in scope"],
        "test_changes": test_changes,
    }


def write_plan(path: Path, tasks: list[dict[str, object]]) -> Path:
    machine = {
        "schema_version": 1,
        "goal": "Build the toy",
        "test_paths": ["checks/**", "tests/**"],
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
        checks = self.product / "checks"
        checks.mkdir()
        (checks / "check_file.py").write_text(
            """from __future__ import annotations

import json
import os
from pathlib import Path
import sys

target = Path(sys.argv[1])
result_path = Path(os.environ["SCAFFOLD_RESULT_PATH"])
if len(sys.argv) > 2 and sys.argv[2] == "malformed":
    result_path.write_text("{}\\n", encoding="utf-8")
    raise SystemExit(0)
exists = target.is_file()
result_path.write_text(
    json.dumps(
        {
            "schema_version": 1,
            "candidate_head": os.environ["SCAFFOLD_CANDIDATE_HEAD"],
            "check_id": os.environ["SCAFFOLD_CHECK_ID"],
            "observations": [
                {
                    "id": f"{target}-exists",
                    "status": "passed" if exists else "failed",
                }
            ],
        },
        sort_keys=True,
    )
    + "\\n",
    encoding="utf-8",
)
raise SystemExit(0 if exists else 1)
""",
            encoding="utf-8",
        )
        git(self.product, "add", "README.md", "checks/check_file.py")
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
                    "writes": {"wrap.txt": "wrapped\n"},
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

        self.assertEqual("complete", result.status, result.reason)
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

        self.assertEqual("failed", result.status, result.reason)
        first = self.store.load()["tasks"][0]
        self.assertEqual(1, first["attempts"]["work"])
        self.assertIsNone(first["lease"])
        self.assertEqual("pending", first["completion"])

    def test_bare_success_exit_without_result_artifact_is_red(self) -> None:
        plan = Store(self.root / "lying-flight")
        plan.create(initial_state("Build the toy"))
        import_plan(
            plan,
            write_plan(
                self.root / "lying-plan.html",
                [task("lie", check="true")],
            ),
        )
        script = self.write_script(
            [
                {
                    "task_id": "lie",
                    "commit_message": "Claim success without results",
                    "writes": {"lie.txt": "looks done\n"},
                }
            ]
        )

        result = run_loop(
            plan,
            self.product,
            FakeAdapter(script, plan),
            holder="lying-worker",
        )

        self.assertEqual("failed", result.status, result.reason)
        lied = plan.load()["tasks"][0]
        self.assertEqual("complete", lied["completion"])
        self.assertEqual("red", lied["verdict"])
        self.assertIn("result artifact", lied["evidence"][-1]["reason"])

    def test_malformed_result_reddens_only_its_task(self) -> None:
        plan = Store(self.root / "bad-paperwork-flight")
        plan.create(initial_state("Build the toy"))
        import_plan(
            plan,
            write_plan(
                self.root / "bad-paperwork-plan.html",
                [
                    task(
                        "bad",
                        check="python3 checks/check_file.py bad.txt malformed",
                    ),
                    task("independent"),
                ],
            ),
        )
        script = self.write_script(
            [
                {
                    "task_id": "bad",
                    "commit_message": "Produce malformed verification paperwork",
                    "writes": {"bad.txt": "bad paperwork\n"},
                }
            ]
        )

        result = run_loop(
            plan,
            self.product,
            FakeAdapter(script, plan),
            holder="bad-paperwork-worker",
        )

        self.assertEqual("failed", result.status, result.reason)
        state = plan.load()
        self.assertEqual("red", state["tasks"][0]["verdict"])
        self.assertEqual(
            ["independent"],
            [item["id"] for item in plan.ready("implementer")],
        )

    def test_out_of_scope_check_edit_withholds_green_flip(self) -> None:
        plan = Store(self.root / "test-edit-flight")
        plan.create(initial_state("Build the toy"))
        import_plan(
            plan,
            write_plan(self.root / "test-edit-plan.html", [task("edit-check")]),
        )
        script = self.write_script(
            [
                {
                    "task_id": "edit-check",
                    "commit_message": "Tamper with the checker",
                    "writes": {
                        "edit-check.txt": "done\n",
                        "checks/check_file.py": "raise SystemExit(0)\n",
                    },
                }
            ]
        )

        result = run_loop(
            plan,
            self.product,
            FakeAdapter(script, plan),
            holder="test-edit-worker",
        )

        self.assertEqual("failed", result.status)
        rejected = plan.load()["tasks"][0]
        self.assertEqual("red", rejected["verdict"])
        self.assertIn("checks/check_file.py", rejected["evidence"][-1]["reason"])


if __name__ == "__main__":
    unittest.main()
