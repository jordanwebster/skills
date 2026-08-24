from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from scaffold.adapters.fake import FakeAdapter
from scaffold.loop import run_loop
from scaffold.plan import import_plan
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
    return completed.stdout.strip()


def task(task_id: str, *, depends_on: list[str] | None = None) -> dict[str, object]:
    return {
        "id": task_id,
        "title": f"Do {task_id}",
        "role": "implementer",
        "effort": "small",
        "check": f"python3 checks/check_file.py {task_id}.txt",
        "depends_on": list(depends_on or []),
        "decisions": [f"{task_id} stays in scope"],
    }


class ProposalFoldingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.product = self.root / "product"
        self.product.mkdir()
        git(self.product, "init", "--quiet")
        git(self.product, "config", "user.name", "Proposal Fixture")
        git(self.product, "config", "user.email", "proposal@example.invalid")
        (self.product / "README.md").write_text("# Proposal fixture\n", encoding="utf-8")
        (self.product / "checks").mkdir()
        (self.product / "checks" / "check_file.py").write_text(
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
        git(self.product, "add", "README.md", "checks/check_file.py")
        git(self.product, "commit", "--quiet", "-m", "Initialize proposal fixture")

    def make_store(self, name: str, tasks: list[dict[str, object]]) -> Store:
        store = Store(self.root / name)
        store.create(initial_state("Build the proposal fixture"))
        plan_path = self.root / f"{name}.html"
        plan_path.write_text(
            "<h1>Proposal plan</h1>\n"
            '<script type="application/json" id="scaffold-plan">\n'
            + json.dumps(
                {
                    "schema_version": 1,
                    "goal": "Build the proposal fixture",
                    "test_paths": ["checks/**"],
                    "tasks": tasks,
                }
            )
            + "\n</script>\n",
            encoding="utf-8",
        )
        import_plan(store, plan_path)
        return store

    def script(self, name: str, steps: list[dict[str, object]]) -> Path:
        path = self.root / f"{name}.json"
        path.write_text(json.dumps({"steps": steps}) + "\n", encoding="utf-8")
        return path

    def test_green_claim_folds_all_routes_after_the_frontier_empties(self) -> None:
        store = self.make_store(
            "all-routes",
            [task("source"), task("independent")],
        )

        class RoutingPlanner:
            calls: list[tuple[str, list[str], list[str]]] = []

            def fold(self, state, proposals, batch_id):
                self.calls.append(
                    (
                        batch_id,
                        [item["id"] for item in proposals],
                        [
                            item["id"]
                            for item in state["tasks"]
                            if item["verdict"] == "green"
                        ],
                    )
                )
                return {
                    "schema_version": 1,
                    "batch_id": batch_id,
                    "routes": [
                        {
                            "proposal_id": "build-index",
                            "disposition": "in-envelope",
                            "reason": "The index is part of the current fixture.",
                            "task": {
                                "id": "index",
                                "title": "Build the index",
                                "role": "implementer",
                                "effort": "small",
                                "check": "python3 checks/check_file.py index.txt",
                                "depends_on": ["source", "independent"],
                                "decisions": ["Keep the index text-only."],
                                "test_changes": False,
                            },
                        },
                        {
                            "proposal_id": "future-polish",
                            "disposition": "beyond-flight",
                            "reason": "Polish is useful but outside this fixture.",
                            "task": None,
                        },
                        {
                            "proposal_id": "change-format",
                            "disposition": "envelope-breaking",
                            "reason": "Changing formats alters the approved output.",
                            "task": None,
                        },
                    ],
                }

        planner = RoutingPlanner()
        adapter = FakeAdapter(
            self.script(
                "all-routes",
                [
                    {
                        "task_id": "source",
                        "commit_message": "Build source",
                        "writes": {"source.txt": "source\n"},
                        "proposals": [
                            {
                                "id": "build-index",
                                "title": "Build an index",
                                "rationale": "The source should be discoverable.",
                                "suggested_dependencies": ["source"],
                            },
                            {
                                "id": "future-polish",
                                "title": "Polish the output",
                                "rationale": "The output could be more decorative.",
                                "suggested_dependencies": ["source"],
                            },
                            {
                                "id": "change-format",
                                "title": "Change the output format",
                                "rationale": "A second format might be useful.",
                                "suggested_dependencies": ["source"],
                            },
                        ],
                    },
                    {
                        "task_id": "independent",
                        "commit_message": "Build independent work",
                        "writes": {"independent.txt": "independent\n"},
                    },
                    {
                        "task_id": "index",
                        "commit_message": "Build proposed index",
                        "writes": {"index.txt": "index\n"},
                    },
                ],
            ),
            store,
        )

        result = run_loop(
            store,
            self.product,
            adapter,
            holder="proposal-worker",
            planner=planner,
            clock=lambda: 100.0,
        )

        self.assertEqual("awaiting-operator", result.status, result.reason)
        state = Store(store.root).load()
        self.assertEqual(
            ["source", "independent"],
            planner.calls[0][2],
            "folding must wait for the ready frontier to empty",
        )
        self.assertEqual(
            ["in-envelope", "beyond-flight", "envelope-breaking"],
            [item["routing"]["disposition"] for item in state["proposals"]],
        )
        self.assertEqual("green", next(item for item in state["tasks"] if item["id"] == "index")["verdict"])
        self.assertEqual(["future-polish"], [item["proposal_id"] for item in state["followups"]])
        self.assertEqual("local", state["followups"][0]["status"])
        self.assertEqual("proposal-envelope", state["outbox"][0]["trigger"])
        self.assertEqual(
            ["proposal-batch-folded"],
            [
                row["transition"]["type"]
                for row in store.read_journal()
                if row["transition"]["type"] == "proposal-batch-folded"
            ],
        )

    def test_malformed_planner_parks_batch_once_without_losing_inputs(self) -> None:
        store = self.make_store("malformed", [task("source")])
        adapter = FakeAdapter(
            self.script(
                "malformed",
                [
                    {
                        "task_id": "source",
                        "commit_message": "Build source with proposal",
                        "writes": {"source.txt": "source\n"},
                        "proposals": [
                            {
                                "id": "unsafe-route",
                                "title": "Route this later",
                                "rationale": "The planner must decide.",
                                "suggested_dependencies": ["source"],
                            }
                        ],
                    }
                ],
            ),
            store,
        )

        class MalformedPlanner:
            def fold(self, state, proposals, batch_id):
                return {"routes": []}

        first = run_loop(
            store,
            self.product,
            adapter,
            holder="proposal-worker",
            planner=MalformedPlanner(),
            clock=lambda: 200.0,
            id_source=lambda: "proposal-folding",
        )
        second = run_loop(
            Store(store.root),
            self.product,
            adapter,
            holder="proposal-worker",
            planner=MalformedPlanner(),
            clock=lambda: 201.0,
            id_source=lambda: "must-not-repeat",
        )

        self.assertEqual("awaiting-operator", first.status)
        self.assertEqual("awaiting-operator", second.status)
        state = store.load()
        self.assertEqual("planning-failed", state["proposals"][0]["routing"]["disposition"])
        self.assertIn("wrong fields", state["proposals"][0]["routing"]["reason"])
        self.assertEqual(["esc-proposal-folding"], [item["id"] for item in state["outbox"]])
        self.assertEqual(1, len(state["outbox"]))

    def test_split_judgment_is_folded_into_a_replacement_task(self) -> None:
        store = self.make_store(
            "split",
            [task("stuck"), task("successor", depends_on=["stuck"])],
        )
        for attempt in range(3):
            lease = store.claim("stuck", f"worker-{attempt}")
            store.apply(
                {
                    "type": "task-released",
                    "task_id": "stuck",
                    "holder": lease.holder,
                    "lease_id": lease.lease_id,
                    "attempt_type": "work",
                    "reason": "The task is too broad.",
                }
            )

        class SplitJudge:
            def decide(self, judged_task, trigger, failure):
                return {
                    "schema_version": 1,
                    "task_id": "stuck",
                    "trigger": "retry-cap",
                    "decision": "split",
                    "reason": "Replace the broad task with one checked slice.",
                }

        class ReplacementPlanner:
            def fold(self, state, proposals, batch_id):
                self.proposal = proposals[0]
                return {
                    "schema_version": 1,
                    "batch_id": batch_id,
                    "routes": [
                        {
                            "proposal_id": proposals[0]["id"],
                            "disposition": "in-envelope",
                            "reason": "The smaller slice still serves the goal.",
                            "task": {
                                "id": "stuck-slice",
                                "title": "Build the smaller slice",
                                "role": "implementer",
                                "effort": "small",
                                "check": "python3 checks/check_file.py stuck-slice.txt",
                                "depends_on": [],
                                "decisions": ["Replace the broad task."],
                                "test_changes": False,
                            },
                        }
                    ],
                }

        planner = ReplacementPlanner()

        class NoDispatch:
            def dispatch(self, prompt, binding, sandbox, timeout):
                raise AssertionError("retry-capped work must be planned before dispatch")

        result = run_loop(
            store,
            self.product,
            NoDispatch(),
            holder="resumed-worker",
            judge=SplitJudge(),
            planner=planner,
            clock=lambda: 300.0,
        )

        self.assertEqual("parked", result.status)
        state = store.load()
        stuck = next(item for item in state["tasks"] if item["id"] == "stuck")
        successor = next(item for item in state["tasks"] if item["id"] == "successor")
        self.assertEqual("judgment", planner.proposal["origin"])
        self.assertEqual("stuck-slice", stuck["lineage"]["superseded_by"])
        self.assertEqual(["stuck-slice"], successor["depends_on"])
        self.assertEqual(["stuck-slice"], [item["id"] for item in store.ready()])


if __name__ == "__main__":
    unittest.main()
