from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from scaffold.__main__ import _init
from scaffold.adapters.fake import FakeAdapter, _safe_product_path
from scaffold.loop import run_loop
from scaffold.plan import import_plan
from scaffold.store import Store
from scaffold.supervise import (
    DriverBusy,
    DriverLock,
    LaunchError,
    Supervisor,
    read_status,
    request_drain,
    start_detached,
    stop_driver,
)


def git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()


def wait_until(predicate, reason: str, timeout: float = 8.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError(reason)


class SupervisionUnitTests(unittest.TestCase):
    def test_driver_lock_refuses_a_second_process(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            command = [
                sys.executable,
                "-c",
                (
                    "from scaffold.supervise import DriverLock; import sys,time; "
                    "lock=DriverLock(sys.argv[1], 'holder'); lock.acquire(); "
                    "print('locked', flush=True); time.sleep(30)"
                ),
                str(workspace),
            ]
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
                env=os.environ.copy(),
            )
            self.addCleanup(self._kill_process_group, process)
            self.assertEqual("locked", process.stdout.readline().strip())

            with self.assertRaisesRegex(DriverBusy, "already owns"):
                DriverLock(workspace, "contender").acquire()

    def test_stale_pid_is_not_treated_as_liveness(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            runtime = workspace / "runtime"
            runtime.mkdir()
            (runtime / "heartbeat.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "run_id": "old-run",
                        "pid": 999999,
                        "pgid": 999999,
                        "state": "running",
                        "reason": "driver is working",
                        "started_at": 10.0,
                        "updated_at": 20.0,
                        "active_task_id": None,
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            status = read_status(workspace, stale_after=5, now=100)

            self.assertEqual("paused", status.state)
            self.assertIn("stale", status.reason)

    def test_stillborn_launch_is_reported_from_missing_heartbeat(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            with self.assertRaisesRegex(LaunchError, "before publishing"):
                start_detached(
                    [sys.executable, "-c", "raise SystemExit(7)"],
                    temporary_directory,
                    "stillborn",
                    launch_timeout=1,
                    environment=os.environ.copy(),
                )

    def test_stop_signals_the_driver_process_group(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            tick_path = workspace / "descendant-ticks.txt"
            child_program = (
                "from pathlib import Path; import sys,time; p=Path(sys.argv[1]); "
                "[(p.write_text(str(i)), time.sleep(.02)) for i in range(1500)]"
            )
            driver_program = (
                "from scaffold.supervise import Supervisor; "
                "import subprocess,sys,time; "
                "runtime=Supervisor(sys.argv[1], sys.argv[1], run_id='group-stop'); "
                "runtime.__enter__(); "
                "subprocess.Popen([sys.executable, '-c', sys.argv[3], sys.argv[2]]); "
                "time.sleep(30)"
            )
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    driver_program,
                    str(workspace),
                    str(tick_path),
                    child_program,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                env=os.environ.copy(),
            )
            self.addCleanup(self._kill_process_group, process)
            wait_until(
                lambda: tick_path.is_file()
                and (workspace / "runtime" / "heartbeat.json").is_file(),
                "driver descendant did not start",
            )

            stop_driver(workspace, timeout=2)
            stopped_value = tick_path.read_text(encoding="utf-8")
            time.sleep(0.15)

            self.assertEqual(stopped_value, tick_path.read_text(encoding="utf-8"))

    @staticmethod
    def _kill_process_group(process: subprocess.Popen[str]) -> None:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()


class SupervisedFlightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.product = self.root / "product"
        self.product.mkdir()
        git(self.product, "init", "--quiet")
        git(self.product, "config", "user.name", "Supervision Test")
        git(self.product, "config", "user.email", "supervise@example.invalid")
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
                {"id": f"{target}-exists", "status": "passed" if exists else "failed"}
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
        (self.product / "README.md").write_text("# Product\n", encoding="utf-8")
        git(self.product, "add", "README.md", "checks/check_file.py")
        git(self.product, "commit", "--quiet", "-m", "Initialize product")
        self.base_head = git(self.product, "rev-parse", "HEAD")
        with redirect_stdout(io.StringIO()):
            _init(self.product, "Supervised toy", "supervised-toy")
        self.workspace = self.product / ".scaffolding" / "supervised-toy"
        self.plan_path = self.root / "plan.html"
        self._write_plan([self._task("build")])
        import_plan(Store(self.workspace), self.plan_path)
        self.addCleanup(self._stop_active_driver)

    def test_detached_start_outlives_launcher_and_finishes(self) -> None:
        script = self._write_script(
            "detached.json",
            [self._step("build", pause_seconds=0.4)],
        )

        launched = self._scaffold(
            "start",
            str(self.workspace),
            "--adapter",
            "fake",
            "--script",
            str(script),
        )

        self.assertIn("you can close this shell", launched.stdout)
        wait_until(
            lambda: read_status(self.workspace).state == "complete",
            "detached driver did not finish after its launcher exited",
        )
        status = read_status(self.workspace)
        self.assertEqual("complete", status.state)
        self.assertEqual("2", git(self.product, "rev-list", "--count", "HEAD"))

    def test_sigkill_driver_and_relaunch_restores_candidate(self) -> None:
        interrupted = self._write_script(
            "interrupted.json",
            [self._step("build", pause_seconds=30)],
        )
        resume = self._write_script("resume.json", [self._step("build")])
        self._scaffold(
            "start",
            str(self.workspace),
            "--adapter",
            "fake",
            "--script",
            str(interrupted),
        )
        wait_until(
            lambda: (self.workspace / "runtime" / "active-task.json").is_file()
            and git(self.product, "rev-parse", "HEAD") != self.base_head,
            "driver never reached the seeded mid-task pause",
        )

        contender = self._scaffold(
            "run",
            str(self.workspace),
            "--adapter",
            "fake",
            "--script",
            str(resume),
            check=False,
        )
        self.assertNotEqual(0, contender.returncode)
        self.assertIn("another driver already owns", contender.stdout)

        heartbeat = json.loads(
            (self.workspace / "runtime" / "heartbeat.json").read_text(
                encoding="utf-8"
            )
        )
        os.killpg(heartbeat["pgid"], signal.SIGKILL)
        wait_until(
            self._driver_lock_is_free,
            "SIGKILL did not release the driver lock",
        )
        self.assertTrue((self.workspace / "runtime" / "active-task.json").is_file())

        relaunched = self._scaffold(
            "run",
            str(self.workspace),
            "--adapter",
            "fake",
            "--script",
            str(resume),
        )

        self.assertIn("complete: ready for review", relaunched.stdout)
        task = Store(self.workspace).load()["tasks"][0]
        self.assertEqual("green", task["verdict"])
        self.assertEqual(1, task["attempts"]["infra"])
        self.assertEqual(0, task["attempts"]["work"])
        self.assertFalse((self.workspace / "runtime" / "active-task.json").exists())
        self.assertEqual("2", git(self.product, "rev-list", "--count", "HEAD"))
        self.assertEqual("", git(self.product, "status", "--porcelain"))

    def test_fake_worker_cannot_alias_framework_control_state(self) -> None:
        alias = self.product / "control-alias"
        alias.symlink_to(self.product / ".scaffolding", target_is_directory=True)

        for relative_name in (
            ".SCAFFOLDING/supervised-toy/runtime/heartbeat.json",
            "control-alias/supervised-toy/runtime/heartbeat.json",
        ):
            with self.subTest(relative_name=relative_name):
                with self.assertRaisesRegex(ValueError, "control state"):
                    _safe_product_path(self.product.resolve(), relative_name)

    def test_drain_before_claim_does_not_dispatch_task(self) -> None:
        script = self._write_script("never-dispatched.json", [self._step("build")])
        store = Store(self.workspace)
        original_ready = store.ready
        requested = False

        def ready_then_drain(profile=None, **kwargs):
            nonlocal requested
            frontier = original_ready(profile, **kwargs)
            if frontier and not requested:
                requested = True
                request_drain(self.workspace)
            return frontier

        runtime = Supervisor(
            self.workspace,
            self.product,
            heartbeat_interval=0.05,
            isolate_process_group=False,
        )
        with runtime:
            with patch.object(store, "ready", side_effect=ready_then_drain):
                result = run_loop(
                    store,
                    self.product,
                    FakeAdapter(script, store),
                    holder="boundary-worker",
                    lifecycle=runtime,
                )
            runtime.finish("drained", result.reason)

        self.assertEqual("drained", result.status)
        task = store.load()["tasks"][0]
        self.assertEqual("pending", task["completion"])
        self.assertIsNone(task["lease"])
        self.assertEqual(self.base_head, git(self.product, "rev-parse", "HEAD"))

    def test_drain_stops_at_task_boundary_and_next_run_continues(self) -> None:
        self._replace_plan([self._task("first"), self._task("wrap", ["first"])])
        first_script = self._write_script(
            "drain.json",
            [
                self._step("first", pause_seconds=0.4),
                self._step("wrap"),
            ],
        )
        wrap_script = self._write_script("wrap.json", [self._step("wrap")])
        self._scaffold(
            "start",
            str(self.workspace),
            "--adapter",
            "fake",
            "--script",
            str(first_script),
        )
        wait_until(
            lambda: (self.workspace / "runtime" / "active-task.json").is_file(),
            "first task did not begin before drain request",
        )

        self._scaffold("drain", str(self.workspace))
        wait_until(
            lambda: read_status(self.workspace).state == "drained",
            "driver did not drain at the next task boundary",
        )

        tasks = Store(self.workspace).load()["tasks"]
        self.assertEqual("green", tasks[0]["verdict"])
        self.assertEqual("pending", tasks[1]["completion"])
        self._scaffold(
            "run",
            str(self.workspace),
            "--adapter",
            "fake",
            "--script",
            str(wrap_script),
        )
        self.assertTrue(
            all(task["verdict"] == "green" for task in Store(self.workspace).load()["tasks"])
        )

    def _replace_plan(self, tasks: list[dict[str, object]]) -> None:
        workspace = self.workspace
        self._stop_active_driver()
        for path in workspace.iterdir():
            if path.name in {"config.json", "driver.lock", "runtime"}:
                continue
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        runtime = workspace / "runtime"
        if runtime.exists():
            for path in runtime.iterdir():
                path.unlink()
        Store(workspace).create({
            "schema_version": 1,
            "goal": "Supervised toy",
            "test_paths": [],
            "plan_digest": None,
            "tasks": [],
        })
        self._write_plan(tasks)
        import_plan(Store(workspace), self.plan_path)

    def _write_plan(self, tasks: list[dict[str, object]]) -> None:
        machine = {
            "schema_version": 1,
            "goal": "Supervised toy",
            "test_paths": ["checks/**"],
            "tasks": tasks,
        }
        self.plan_path.write_text(
            "<h1>Supervised plan</h1>\n"
            '<script type="application/json" id="scaffold-plan">\n'
            + json.dumps(machine)
            + "\n</script>\n",
            encoding="utf-8",
        )

    @staticmethod
    def _task(task_id: str, depends_on: list[str] | None = None) -> dict[str, object]:
        return {
            "id": task_id,
            "title": f"Build {task_id}",
            "role": "implementer",
            "effort": "small",
            "check": f"python3 checks/check_file.py {task_id}.txt",
            "depends_on": list(depends_on or []),
            "decisions": [f"Write {task_id}.txt"],
        }

    @staticmethod
    def _step(task_id: str, *, pause_seconds: float = 0) -> dict[str, object]:
        return {
            "task_id": task_id,
            "commit_message": f"Build {task_id}",
            "writes": {f"{task_id}.txt": f"{task_id}\n"},
            "pause_seconds": pause_seconds,
        }

    def _write_script(self, name: str, steps: list[dict[str, object]]) -> Path:
        path = self.root / name
        path.write_text(json.dumps({"steps": steps}) + "\n", encoding="utf-8")
        return path

    def _scaffold(self, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "scaffold", *arguments],
            check=check,
            capture_output=True,
            text=True,
            timeout=15,
            env=os.environ.copy(),
        )

    def _stop_active_driver(self) -> None:
        try:
            stop_driver(self.workspace, timeout=1)
        except (FileNotFoundError, OSError, RuntimeError):
            pass

    def _driver_lock_is_free(self) -> bool:
        lock = DriverLock(self.workspace, "recovery-probe")
        try:
            lock.acquire()
        except DriverBusy:
            return False
        lock.release()
        return True


if __name__ == "__main__":
    unittest.main()
