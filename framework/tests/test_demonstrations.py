from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from scaffold.adapters.fake import FakeAdapter
from scaffold.loop import run_loop
from scaffold.plan import PlanError, import_plan, read_plan, retained_plan_path
from scaffold.store import Store, initial_state


def git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout


class DemonstrationFreshnessTests(unittest.TestCase):
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
exists = target.is_file()
Path(os.environ["SCAFFOLD_RESULT_PATH"]).write_text(
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
        (checks / "show_first.py").write_text(
            """from pathlib import Path

value = Path("first.txt").read_text(encoding="utf-8")
Path("shown.txt").write_text(value, encoding="utf-8")
print(value, end="")
""",
            encoding="utf-8",
        )
        git(self.product, "add", "README.md", "checks")
        git(self.product, "commit", "--quiet", "-m", "Initialize toy product")
        self.store = Store(self.root / "flight")
        self.store.create(initial_state("Build the toy"))

    def write_plan(
        self,
        *,
        command: str = "python3 checks/show_first.py",
        surface_paths: list[str] | None = None,
        artifact_paths: list[str] | None = None,
    ) -> Path:
        machine = {
            "schema_version": 1,
            "goal": "Build the toy",
            "test_paths": ["checks/**"],
            "demonstrations": [
                {
                    "id": "show-first",
                    "title": "Show the first artifact",
                    "command": command,
                    "surface_paths": (
                        ["first.txt"] if surface_paths is None else surface_paths
                    ),
                    "artifact_paths": (
                        ["shown.txt"] if artifact_paths is None else artifact_paths
                    ),
                }
            ],
            "tasks": [
                {
                    "id": "first",
                    "title": "Build first",
                    "role": "implementer",
                    "effort": "small",
                    "check": "python3 checks/check_file.py first.txt",
                    "depends_on": [],
                    "decisions": [],
                },
                {
                    "id": "wrap",
                    "title": "Wrap",
                    "role": "implementer",
                    "effort": "small",
                    "check": "python3 checks/check_file.py wrap.txt",
                    "depends_on": ["first"],
                    "decisions": [],
                },
            ],
        }
        path = self.root / "plan.html"
        path.write_text(
            '<script type="application/json" id="scaffold-plan">\n'
            + json.dumps(machine)
            + "\n</script>\n",
            encoding="utf-8",
        )
        return path

    def write_script(self) -> Path:
        path = self.root / "fake.json"
        path.write_text(
            json.dumps(
                {
                    "steps": [
                        {
                            "task_id": "first",
                            "commit_message": "Build first",
                            "writes": {"first.txt": "first\n"},
                        },
                        {
                            "task_id": "wrap",
                            "commit_message": "Update surface and wrap",
                            "writes": {
                                "first.txt": "updated\n",
                                "wrap.txt": "wrapped\n",
                            },
                        },
                    ]
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return path

    def run_flight(self):
        return run_loop(
            self.store,
            self.product,
            FakeAdapter(self.write_script(), self.store),
            holder="fake-worker",
            durable_paths=(retained_plan_path(self.store),),
        )

    def test_surface_change_invalidates_and_recaptures_at_presented_head(self) -> None:
        import_plan(self.store, self.write_plan())

        result = self.run_flight()

        self.assertEqual("complete", result.status, result.reason)
        state = self.store.load()
        head = git(self.product, "rev-parse", "HEAD").strip()
        self.assertEqual("done-pending-bless", state["phase"])
        self.assertEqual(head, state["presented_head"])
        candidate = state["demonstrations"][0]["candidate"]
        self.assertEqual(head, candidate["verified_head"])
        artifact = self.store.read_demonstration_capture("show-first")
        retained = {
            output["kind"]: self.store.root / output["path"]
            for output in artifact["outputs"]
        }
        self.assertEqual("updated\n", retained["stdout"].read_text(encoding="utf-8"))
        self.assertEqual("updated\n", retained["artifact"].read_text(encoding="utf-8"))
        transitions = [entry["transition"] for entry in self.store.read_journal()]
        self.assertEqual(
            2,
            sum(item["type"] == "demonstration-captured" for item in transitions),
        )
        self.assertEqual(
            1,
            sum(item["type"] == "demonstration-invalidated" for item in transitions),
        )

    def test_missing_retained_output_is_rederived_on_restart(self) -> None:
        import_plan(self.store, self.write_plan())
        first = self.run_flight()
        self.assertEqual("complete", first.status, first.reason)
        artifact = self.store.read_demonstration_capture("show-first")
        stdout_path = self.store.root / next(
            output["path"]
            for output in artifact["outputs"]
            if output["kind"] == "stdout"
        )
        stdout_path.unlink()

        resumed = run_loop(
            self.store,
            self.product,
            FakeAdapter(self.write_script(), self.store),
            holder="fresh-worker",
        )

        self.assertEqual("complete", resumed.status, resumed.reason)
        self.assertTrue(stdout_path.is_file())
        self.assertEqual("done-pending-bless", self.store.load()["phase"])
        transitions = [entry["transition"] for entry in self.store.read_journal()]
        self.assertEqual(
            "retained capture is missing or malformed",
            [
                item["reason"]
                for item in transitions
                if item["type"] == "demonstration-invalidated"
            ][-1],
        )

    def test_failed_final_replay_keeps_flight_out_of_review_state(self) -> None:
        import_plan(
            self.store,
            self.write_plan(
                command="python3 -c 'raise SystemExit(7)'",
                surface_paths=["README.md"],
                artifact_paths=[],
            ),
        )

        result = self.run_flight()

        self.assertEqual("blocked", result.status)
        self.assertIn("demonstration show-first failed", result.reason)
        state = self.store.load()
        self.assertEqual("working", state["phase"])
        self.assertIsNone(state["presented_head"])
        self.assertIsNone(state["demonstrations"][0]["candidate"])
        self.assertTrue(all(task["verdict"] == "green" for task in state["tasks"]))

    def test_failed_refresh_demotes_an_earlier_ready_state(self) -> None:
        import_plan(self.store, self.write_plan())
        first = self.run_flight()
        self.assertEqual("complete", first.status, first.reason)
        (self.product / "first.txt").unlink()
        git(self.product, "add", "--all")
        git(self.product, "commit", "--quiet", "-m", "Remove shown surface")

        resumed = run_loop(
            self.store,
            self.product,
            FakeAdapter(self.write_script(), self.store),
            holder="fresh-worker",
        )

        self.assertEqual("blocked", resumed.status)
        self.assertIn("surface paths matched no files", resumed.reason)
        state = self.store.load()
        self.assertEqual("working", state["phase"])
        self.assertIsNone(state["presented_head"])

    def test_capture_excludes_secret_environment_and_redacts_transcript(self) -> None:
        secret = "sk-fixture-secret-1234567890"
        import_plan(
            self.store,
            self.write_plan(
                command=(
                    "python3 -c 'import os; "
                    'print(os.environ.get("M5_TEST_API_KEY", "missing"))\''
                ),
                surface_paths=["README.md"],
                artifact_paths=[],
            ),
        )

        with patch.dict(os.environ, {"M5_TEST_API_KEY": secret}):
            result = self.run_flight()

        self.assertEqual("complete", result.status, result.reason)
        retained = b"\n".join(
            path.read_bytes()
            for path in (self.store.root / "demonstrations").rglob("*")
            if path.is_file()
        )
        self.assertNotIn(secret.encode(), retained)
        self.assertIn(b"missing", retained)

    def test_sensitive_generated_artifact_is_rejected_without_retention(self) -> None:
        secret = "sk-fixture-secret-1234567890"
        secret_source = self.root / "external-secret.txt"
        secret_source.write_text(secret, encoding="utf-8")
        import_plan(
            self.store,
            self.write_plan(
                command=(
                    "python3 -c 'from pathlib import Path; "
                    f'Path("shown.txt").write_bytes('
                    f'Path("{secret_source}").read_bytes())\''
                ),
                surface_paths=["README.md"],
            ),
        )

        with patch.dict(os.environ, {"M5_TEST_API_KEY": secret}):
            result = self.run_flight()

        self.assertEqual("blocked", result.status)
        self.assertIn("contains a sensitive value", result.reason)
        retained = b"\n".join(
            path.read_bytes()
            for path in (self.store.root / "demonstrations").rglob("*")
            if path.is_file()
        )
        self.assertNotIn(secret.encode(), retained)
        self.assertIsNone(self.store.load()["demonstrations"][0]["candidate"])

    def test_non_regular_generated_artifact_fails_without_hanging(self) -> None:
        import_plan(
            self.store,
            self.write_plan(
                command="python3 -c 'import os; os.mkfifo(\"shown.txt\")'",
                surface_paths=["README.md"],
            ),
        )

        result = self.run_flight()

        self.assertEqual("blocked", result.status)
        self.assertIn("not a regular file", result.reason)
        self.assertEqual("working", self.store.load()["phase"])

    def test_restore_timeout_becomes_a_blocked_capture_result(self) -> None:
        import_plan(self.store, self.write_plan())

        with patch(
            "scaffold.demonstrate._clone_checkout",
            side_effect=subprocess.TimeoutExpired(["git", "clone"], 1),
        ):
            result = self.run_flight()

        self.assertEqual("blocked", result.status)
        self.assertIn("cannot restore demonstration", result.reason)
        self.assertIn("timed out", result.reason)
        self.assertEqual("working", self.store.load()["phase"])

    def test_product_commit_during_final_capture_cannot_leave_ready_state(self) -> None:
        marker = self.root / "capture-started"
        command = (
            "python3 -c 'from pathlib import Path; import time; "
            f'Path("{marker}").write_text("started"); '
            "time.sleep(0.5); print(\"shown\")'"
        )
        import_plan(
            self.store,
            self.write_plan(
                command=command,
                surface_paths=["first.txt"],
                artifact_paths=[],
            ),
        )
        first = self.run_flight()
        self.assertEqual("complete", first.status, first.reason)
        marker.unlink()
        (self.product / "before-race.txt").write_text("before\n", encoding="utf-8")
        git(self.product, "add", "before-race.txt")
        git(self.product, "commit", "--quiet", "-m", "Move presented head")
        thread_errors: list[BaseException] = []

        def commit_during_capture() -> None:
            try:
                deadline = time.monotonic() + 5
                while not marker.is_file():
                    if time.monotonic() >= deadline:
                        raise AssertionError("demonstration did not start")
                    time.sleep(0.01)
                (self.product / "during-race.txt").write_text(
                    "during\n", encoding="utf-8"
                )
                git(self.product, "add", "during-race.txt")
                git(self.product, "commit", "--quiet", "-m", "Race capture")
            except BaseException as error:
                thread_errors.append(error)

        committer = threading.Thread(target=commit_during_capture)
        committer.start()
        result = run_loop(
            self.store,
            self.product,
            FakeAdapter(self.write_script(), self.store),
            holder="fresh-worker",
        )
        committer.join(timeout=10)

        self.assertFalse(committer.is_alive())
        self.assertEqual([], thread_errors)
        self.assertEqual("blocked", result.status)
        self.assertIn("product HEAD changed during capture", result.reason)
        state = self.store.load()
        self.assertEqual("working", state["phase"])
        self.assertIsNone(state["presented_head"])

    def test_plan_rejects_escaping_demonstration_paths(self) -> None:
        plan = self.write_plan(surface_paths=["../secret"])

        with self.assertRaisesRegex(PlanError, "safe relative paths"):
            read_plan(plan)


if __name__ == "__main__":
    unittest.main()
