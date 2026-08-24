from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scaffold.adapters.fake import FakeAdapter
from scaffold.loop import run_loop
from scaffold.plan import import_plan, retained_plan_path
from scaffold.store import Store, TaskUnavailable, initial_state
from scaffold.verify import Verdict


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

    def test_retry_cap_invokes_typed_judge_and_records_durable_escalation(self) -> None:
        class RetryJudge:
            calls: list[tuple[str, str, str]] = []

            def decide(self, judged_task, trigger, failure):
                self.calls.append((judged_task["id"], trigger, failure))
                return {
                    "schema_version": 1,
                    "task_id": judged_task["id"],
                    "trigger": trigger,
                    "decision": "defer-to-operator",
                    "reason": "The repeated failure needs a changed approach.",
                }

        judge = RetryJudge()
        for attempt in range(3):
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
                holder=f"worker-{attempt}",
                judge=judge,
                work_attempt_limit=3,
                clock=lambda: 123.0,
                id_source=lambda: "retry-cap",
            )

        self.assertEqual("awaiting-operator", result.status)
        self.assertEqual([("first", "retry-cap", "worker-error")], judge.calls)
        restarted = Store(self.store.root).load()
        failed = restarted["tasks"][0]
        self.assertEqual(3, failed["attempts"]["work"])
        self.assertEqual(0, failed["attempts"]["diagnostic"])
        self.assertTrue(failed["parked"])
        self.assertEqual("judge", failed["judgments"][0]["source"])
        self.assertEqual("retry-cap", failed["judgments"][0]["trigger"])
        self.assertEqual("esc-retry-cap", restarted["outbox"][0]["id"])
        self.assertEqual("veto-or-confirm", restarted["outbox"][0]["request"])
        self.assertEqual("open", restarted["outbox"][0]["status"])
        self.assertEqual(
            "task-judged",
            self.store.read_journal()[-1]["transition"]["type"],
        )

    def test_ambiguity_parks_without_retry_and_independent_work_continues(self) -> None:
        plan = Store(self.root / "ambiguity-flight")
        plan.create(initial_state("Build the toy"))
        import_plan(
            plan,
            write_plan(
                self.root / "ambiguity-plan.html",
                [task("unclear"), task("independent")],
            ),
        )
        ambiguity = self.write_script(
            [
                {
                    "task_id": "unclear",
                    "outcome": "ambiguity",
                    "reason": "The plan names two incompatible output formats.",
                }
            ]
        )

        first = run_loop(
            plan,
            self.product,
            FakeAdapter(ambiguity, plan),
            holder="ambiguity-worker",
            clock=lambda: 456.0,
            id_source=lambda: "ambiguity",
        )

        self.assertEqual("awaiting-operator", first.status)
        state = Store(plan.root).load()
        unclear = state["tasks"][0]
        self.assertEqual(
            {"work": 0, "infra": 0, "diagnostic": 1},
            unclear["attempts"],
        )
        self.assertTrue(unclear["parked"])
        self.assertEqual("framework-rule", unclear["judgments"][0]["source"])
        self.assertIn(
            "two incompatible output formats",
            state["outbox"][0]["blocked_on"],
        )
        self.assertEqual(
            ["independent"],
            [item["id"] for item in plan.ready("implementer")],
        )

        independent = self.write_script(
            [
                {
                    "task_id": "independent",
                    "commit_message": "Build independent work",
                    "writes": {"independent.txt": "independent\n"},
                }
            ]
        )
        second = run_loop(
            plan,
            self.product,
            FakeAdapter(independent, plan),
            holder="independent-worker",
        )
        self.assertEqual("awaiting-operator", second.status)
        self.assertEqual("green", plan.load()["tasks"][1]["verdict"])

    def test_malformed_judge_output_downgrades_to_park_and_escalate(self) -> None:
        class MalformedJudge:
            def decide(self, judged_task, trigger, failure):
                return {"decision": "try-again"}

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
            holder="worker",
            judge=MalformedJudge(),
            work_attempt_limit=1,
            clock=lambda: 789.0,
            id_source=lambda: "malformed-judge",
        )

        self.assertEqual("awaiting-operator", result.status)
        state = self.store.load()
        self.assertTrue(state["tasks"][0]["parked"])
        judgment = state["tasks"][0]["judgments"][0]
        self.assertEqual("fallback", judgment["source"])
        self.assertEqual("defer-to-operator", judgment["decision"])
        self.assertIn("wrong fields", judgment["reason"])
        self.assertEqual("esc-malformed-judge", state["outbox"][0]["id"])

    def test_restart_routes_an_already_reached_retry_cap_before_dispatch(self) -> None:
        for attempt in range(3):
            lease = self.store.claim("first", f"worker-{attempt}")
            self.store.apply(
                {
                    "type": "task-released",
                    "task_id": "first",
                    "holder": lease.holder,
                    "lease_id": lease.lease_id,
                    "attempt_type": "work",
                    "reason": "same seeded failure",
                }
            )

        class NoDispatchAdapter:
            def dispatch(self, prompt, binding, sandbox, timeout):
                raise AssertionError("retry-capped work was dispatched")

        class ParkJudge:
            def decide(self, judged_task, trigger, failure):
                self.failure = failure
                return {
                    "schema_version": 1,
                    "task_id": judged_task["id"],
                    "trigger": trigger,
                    "decision": "park",
                    "reason": "Keep the bounded failure parked.",
                }

        judge = ParkJudge()
        result = run_loop(
            Store(self.store.root),
            self.product,
            NoDispatchAdapter(),
            holder="resumed-worker",
            judge=judge,
            work_attempt_limit=3,
        )

        self.assertEqual("parked", result.status)
        self.assertEqual("same seeded failure", judge.failure)
        state = self.store.load()
        self.assertTrue(state["tasks"][0]["parked"])
        self.assertEqual([], state["outbox"])

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
        verified_base = git(self.product, "rev-parse", "HEAD").strip()
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
        self.assertEqual(verified_base, git(self.product, "rev-parse", "HEAD").strip())
        self.assertFalse((self.product / "bad.txt").exists())

        second_script = self.write_script(
            [
                {
                    "task_id": "independent",
                    "commit_message": "Build independent artifact",
                    "writes": {"independent.txt": "independent\n"},
                }
            ]
        )
        second = run_loop(
            plan,
            self.product,
            FakeAdapter(second_script, plan),
            holder="independent-worker",
        )
        self.assertEqual("blocked", second.status)
        self.assertEqual("green", plan.load()["tasks"][1]["verdict"])
        self.assertFalse((self.product / "bad.txt").exists())

    def test_verification_renews_a_short_lease(self) -> None:
        plan = Store(self.root / "short-lease-flight")
        plan.create(initial_state("Build the toy"))
        import_plan(
            plan,
            write_plan(self.root / "short-lease-plan.html", [task("slow")]),
        )
        slow_check = self.product / "checks" / "check_file.py"
        slow_check.write_text(
            slow_check.read_text(encoding="utf-8").replace(
                "target = Path(sys.argv[1])",
                "import time\ntime.sleep(0.15)\ntarget = Path(sys.argv[1])",
            ),
            encoding="utf-8",
        )
        git(self.product, "add", "checks/check_file.py")
        git(self.product, "commit", "--quiet", "-m", "Make base check deliberately slow")
        script = self.write_script(
            [
                {
                    "task_id": "slow",
                    "commit_message": "Build slow checked artifact",
                    "writes": {"slow.txt": "slow\n"},
                }
            ]
        )

        result = run_loop(
            plan,
            self.product,
            FakeAdapter(script, plan),
            holder="short-lease-worker",
            lease_seconds=0.05,
            dispatch_timeout=2,
        )

        self.assertEqual("complete", result.status, result.reason)
        transitions = [
            entry["transition"]["type"] for entry in plan.read_journal()
        ]
        self.assertIn("task-lease-renewed", transitions)

    def test_claim_filing_reserves_lease_before_reclaim_can_run(self) -> None:
        plan = Store(self.root / "claim-reservation-flight")
        plan.create(initial_state("Build the toy"))
        import_plan(
            plan,
            write_plan(
                self.root / "claim-reservation-plan.html",
                [task("reserved")],
            ),
        )
        script = self.write_script(
            [
                {
                    "task_id": "reserved",
                    "commit_message": "Build reserved artifact",
                    "writes": {"reserved.txt": "reserved\n"},
                }
            ]
        )
        inner = FakeAdapter(script, plan)

        class ReclaimAfterClaimAdapter:
            reclaim_status = "not-run"

            def dispatch(self, prompt, binding, sandbox, timeout):
                task_state = plan.load()["tasks"][0]
                original_expiry = task_state["lease"]["expires_at"]
                result = inner.dispatch(prompt, binding, sandbox, timeout)
                try:
                    plan.claim(
                        "reserved",
                        "reclaiming-worker",
                        now=original_expiry + 0.001,
                    )
                except TaskUnavailable:
                    self.reclaim_status = "blocked"
                else:
                    self.reclaim_status = "reclaimed"
                return result

        adapter = ReclaimAfterClaimAdapter()
        result = run_loop(
            plan,
            self.product,
            adapter,
            holder="original-worker",
            lease_seconds=5,
            dispatch_timeout=2,
        )

        self.assertEqual("complete", result.status, result.reason)
        self.assertEqual("blocked", adapter.reclaim_status)
        reserved = plan.load()["tasks"][0]
        self.assertEqual("green", reserved["verdict"])
        self.assertEqual(
            reserved["verified_head"],
            git(self.product, "rev-parse", "HEAD").strip(),
        )

    def test_killed_and_infra_verification_do_not_burn_work_attempts(self) -> None:
        base_head = git(self.product, "rev-parse", "HEAD").strip()
        for kind in ("killed", "infra"):
            with self.subTest(kind=kind):
                plan = Store(self.root / f"{kind}-verification-flight")
                plan.create(initial_state("Build the toy"))
                import_plan(
                    plan,
                    write_plan(
                        self.root / f"{kind}-verification-plan.html",
                        [task(kind)],
                    ),
                )
                script = self.write_script(
                    [
                        {
                            "task_id": kind,
                            "commit_message": f"Build {kind} artifact",
                            "writes": {f"{kind}.txt": f"{kind}\n"},
                        }
                    ]
                )
                verdict = Verdict(
                    kind,
                    f"seeded {kind} verification",
                    plan.root / "seeded-verdict.json",
                    "0" * 64,
                    (),
                )

                with patch("scaffold.loop.verify", return_value=verdict):
                    result = run_loop(
                        plan,
                        self.product,
                        FakeAdapter(script, plan),
                        holder=f"{kind}-worker",
                    )

                self.assertEqual("failed", result.status, result.reason)
                failed = plan.load()["tasks"][0]
                self.assertEqual("pending", failed["completion"])
                self.assertIsNone(failed["lease"])
                self.assertEqual(
                    {"work": 0, "infra": 1, "diagnostic": 0},
                    failed["attempts"],
                )
                self.assertEqual(
                    base_head,
                    git(self.product, "rev-parse", "HEAD").strip(),
                )
                self.assertFalse((self.product / f"{kind}.txt").exists())

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
