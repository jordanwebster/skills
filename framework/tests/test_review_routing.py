from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from scaffold.adapters.fake import FakeAdapter
from scaffold.loop import run_loop
from scaffold.plan import PlanError, import_plan, read_plan
from scaffold.store import Store, initial_state


def git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()


def derived_id(kind: str, *parts: str) -> str:
    digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{kind}-{digest}"


def finding(
    finding_id: str,
    severity: str,
    summary: str = "A boundary is wrong.",
) -> dict[str, str]:
    return {
        "id": finding_id,
        "severity": severity,
        "summary": summary,
        "evidence": f"Seeded reproduction for {finding_id}.",
    }


class ReviewRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.product = self.root / "product"
        self.product.mkdir()
        git(self.product, "init", "--quiet")
        git(self.product, "config", "user.name", "Review Fixture")
        git(self.product, "config", "user.email", "review@example.invalid")
        checks = self.product / "checks"
        checks.mkdir()
        (checks / "structured.py").write_text(
            """from __future__ import annotations
import json
import os
from pathlib import Path
import sys

required = sys.argv[1] if len(sys.argv) > 1 else None
passed = required is None or Path(required).is_file()
Path(os.environ["SCAFFOLD_RESULT_PATH"]).write_text(
    json.dumps({
        "schema_version": 1,
        "candidate_head": os.environ["SCAFFOLD_CANDIDATE_HEAD"],
        "check_id": os.environ["SCAFFOLD_CHECK_ID"],
        "observations": [{
            "id": "review-routing-check",
            "status": "passed" if passed else "failed",
        }],
    }) + "\\n",
    encoding="utf-8",
)
raise SystemExit(0 if passed else 1)
""",
            encoding="utf-8",
        )
        git(self.product, "add", "checks/structured.py")
        git(self.product, "commit", "--quiet", "-m", "Initialize review product")
        self.base_head = git(self.product, "rev-parse", "HEAD")

    def write_plan(
        self,
        severity_bar: str = "medium",
        *,
        downstream: bool = False,
        remediation_test_changes: bool = False,
        remediation_check: str = "python3 checks/structured.py fixed.txt",
    ) -> Path:
        tasks: list[dict[str, object]] = [
            {
                "id": "review",
                "title": "Review the product",
                "role": "reviewer",
                "effort": "high",
                "check": "python3 checks/structured.py",
                "remediation_role": "implementer",
                "remediation_effort": "high",
                "remediation_check": remediation_check,
                "remediation_test_changes": remediation_test_changes,
                "depends_on": [],
                "decisions": ["Review against the accepted design."],
            }
        ]
        if downstream:
            tasks.append(
                {
                    "id": "downstream",
                    "title": "Use reviewed work",
                    "role": "implementer",
                    "effort": "small",
                    "check": "python3 checks/structured.py downstream.txt",
                    "depends_on": ["review"],
                    "decisions": ["Run only after the review path is clear."],
                }
            )
        machine = {
            "schema_version": 1,
            "goal": "Route review findings",
            "test_paths": ["checks/**"],
            "review_severity_bar": severity_bar,
            "tasks": tasks,
        }
        path = self.root / "plan.html"
        path.write_text(
            '<script type="application/json" id="scaffold-plan">\n'
            + json.dumps(machine)
            + "\n</script>\n",
            encoding="utf-8",
        )
        return path

    def write_script(self, steps: list[dict[str, object]]) -> Path:
        path = self.root / "script.json"
        path.write_text(json.dumps({"steps": steps}) + "\n", encoding="utf-8")
        return path

    def make_store(self, **plan_options: object) -> Store:
        store = Store(self.root / "flight")
        store.create(initial_state("Route review findings"))
        import_plan(store, self.write_plan(**plan_options))
        return store

    def test_above_bar_finding_spawns_remediation_and_one_clean_rereview(self) -> None:
        store = self.make_store()
        remediation_id = derived_id("remediate", "review", "unsafe-boundary")
        rereview_id = derived_id("rereview", "review", "unsafe-boundary")
        script = self.write_script(
            [
                {
                    "task_id": "review",
                    "review": {
                        "findings": [
                            finding("wording", "low"),
                            finding("unsafe-boundary", "medium"),
                        ]
                    },
                },
                {
                    "task_id": remediation_id,
                    "commit_message": "Fix reviewed boundary",
                    "writes": {"fixed.txt": "fixed\n"},
                },
                {
                    "task_id": rereview_id,
                    "review": {"findings": []},
                },
            ]
        )

        result = run_loop(
            store,
            self.product,
            FakeAdapter(script, store),
            holder="review-worker",
        )

        self.assertEqual("complete", result.status, result.reason)
        state = store.load()
        self.assertEqual(
            ["review", remediation_id, rereview_id],
            [task["id"] for task in state["tasks"]],
        )
        self.assertTrue(all(task["verdict"] == "green" for task in state["tasks"]))
        self.assertEqual([], state["outbox"])
        self.assertEqual(
            ["wording", "unsafe-boundary"],
            [item["id"] for item in state["tasks"][0]["review"]["findings"]],
        )
        self.assertEqual(
            [remediation_id],
            state["tasks"][2]["depends_on"],
        )
        self.assertEqual(
            "1",
            git(self.product, "rev-list", "--count", f"{self.base_head}..HEAD"),
        )
        first_review_transition = next(
            entry
            for entry in store.read_journal()
            if entry["transition"].get("type") == "task-verification-recorded"
        )
        self.assertEqual(3, len(first_review_transition["state_after"]["tasks"]))

    def test_findings_surviving_rereview_escalate_without_another_round(self) -> None:
        store = self.make_store()
        remediation_id = derived_id("remediate", "review", "unsafe-boundary")
        rereview_id = derived_id("rereview", "review", "unsafe-boundary")
        script = self.write_script(
            [
                {
                    "task_id": "review",
                    "review": {
                        "findings": [finding("unsafe-boundary", "critical")]
                    },
                },
                {
                    "task_id": remediation_id,
                    "commit_message": "Attempt reviewed boundary fix",
                    "writes": {"fixed.txt": "attempted\n"},
                },
                {
                    "task_id": rereview_id,
                    "review": {
                        "findings": [
                            finding(
                                "unsafe-boundary",
                                "high",
                                "The attempted fix leaves the boundary open.",
                            )
                        ]
                    },
                },
            ]
        )

        result = run_loop(
            store,
            self.product,
            FakeAdapter(script, store),
            holder="review-worker",
            clock=lambda: 42.0,
        )

        self.assertEqual("awaiting-operator", result.status, result.reason)
        state = store.load()
        self.assertEqual(3, len(state["tasks"]))
        self.assertTrue(all(task["verdict"] == "green" for task in state["tasks"]))
        self.assertEqual(1, len(state["outbox"]))
        self.assertEqual("review-findings", state["outbox"][0]["trigger"])
        self.assertEqual(rereview_id, state["outbox"][0]["task_id"])
        self.assertTrue(state["tasks"][2]["parked"])
        self.assertEqual(
            "defer-to-operator",
            state["tasks"][2]["judgments"][-1]["decision"],
        )

    def test_remediation_and_rereview_gate_existing_successors(self) -> None:
        store = self.make_store(downstream=True)
        remediation_id = derived_id("remediate", "review", "unsafe-boundary")
        rereview_id = derived_id("rereview", "review", "unsafe-boundary")
        script = self.write_script(
            [
                {
                    "task_id": "review",
                    "review": {
                        "findings": [finding("unsafe-boundary", "high")]
                    },
                },
                {
                    "task_id": remediation_id,
                    "commit_message": "Fix before downstream work",
                    "writes": {"fixed.txt": "fixed\n"},
                },
                {
                    "task_id": rereview_id,
                    "review": {"findings": []},
                },
                {
                    "task_id": "downstream",
                    "commit_message": "Use reviewed work",
                    "writes": {"downstream.txt": "used\n"},
                },
            ]
        )

        result = run_loop(
            store,
            self.product,
            FakeAdapter(script, store),
            holder="review-worker",
        )

        self.assertEqual("complete", result.status, result.reason)
        self.assertEqual(
            ("review", remediation_id, rereview_id, "downstream"),
            result.completed_task_ids,
        )
        tasks = {task["id"]: task for task in store.load()["tasks"]}
        self.assertEqual([rereview_id], tasks["downstream"]["depends_on"])

    def test_plan_owned_test_scope_reaches_derived_remediation(self) -> None:
        store = self.make_store(
            remediation_test_changes=True,
            remediation_check=(
                "python3 checks/structured.py checks/regression.txt"
            ),
        )
        remediation_id = derived_id("remediate", "review", "regression-gap")
        rereview_id = derived_id("rereview", "review", "regression-gap")
        script = self.write_script(
            [
                {
                    "task_id": "review",
                    "review": {
                        "findings": [finding("regression-gap", "medium")]
                    },
                },
                {
                    "task_id": remediation_id,
                    "commit_message": "Add reviewed regression",
                    "writes": {"checks/regression.txt": "covered\n"},
                },
                {
                    "task_id": rereview_id,
                    "review": {"findings": []},
                },
            ]
        )

        result = run_loop(
            store,
            self.product,
            FakeAdapter(script, store),
            holder="review-worker",
        )

        self.assertEqual("complete", result.status, result.reason)
        tasks = {task["id"]: task for task in store.load()["tasks"]}
        self.assertTrue(tasks[remediation_id]["test_changes"])
        self.assertEqual("green", tasks[remediation_id]["verdict"])

    def test_below_bar_review_completes_without_graph_mutation(self) -> None:
        store = self.make_store()
        script = self.write_script(
            [
                {
                    "task_id": "review",
                    "review": {"findings": [finding("wording", "low")]},
                }
            ]
        )

        result = run_loop(
            store,
            self.product,
            FakeAdapter(script, store),
            holder="review-worker",
        )

        self.assertEqual("complete", result.status, result.reason)
        self.assertEqual(["review"], [task["id"] for task in store.load()["tasks"]])
        self.assertEqual(self.base_head, git(self.product, "rev-parse", "HEAD"))

    def test_legacy_imported_state_migrates_to_medium_review_bar(self) -> None:
        store = self.make_store()
        rows = store.read_journal()
        for row in rows:
            row["state_after"].pop("review_severity_bar", None)
            if row["transition"].get("type") == "plan-imported":
                row["transition"].pop("review_severity_bar", None)
            canonical = json.dumps(
                row["state_after"],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            row["state_hash"] = hashlib.sha256(canonical).hexdigest()
        store.journal_path.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        materialized = json.loads(store.state_path.read_text(encoding="utf-8"))
        materialized.pop("review_severity_bar", None)
        store.state_path.write_text(
            json.dumps(materialized, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        self.assertEqual("medium", store.load()["review_severity_bar"])
        script = self.write_script(
            [{"task_id": "review", "review": {"findings": []}}]
        )
        result = run_loop(
            store,
            self.product,
            FakeAdapter(script, store),
            holder="review-worker",
        )
        self.assertEqual("complete", result.status, result.reason)

    def test_plan_rejects_unknown_review_severity(self) -> None:
        with self.assertRaisesRegex(PlanError, "review_severity_bar"):
            read_plan(self.write_plan("urgent"))

    def test_malformed_review_findings_red_only_the_review_attempt(self) -> None:
        store = self.make_store()
        script = self.write_script(
            [
                {
                    "task_id": "review",
                    "review": {
                        "findings": [
                            {
                                "id": "bad-severity",
                                "severity": "urgent",
                                "summary": "Malformed severity.",
                                "evidence": "Seeded malformed review output.",
                            }
                        ]
                    },
                }
            ]
        )

        result = run_loop(
            store,
            self.product,
            FakeAdapter(script, store),
            holder="review-worker",
        )

        self.assertEqual("failed", result.status, result.reason)
        task = store.load()["tasks"][0]
        self.assertEqual("pending", task["completion"])
        self.assertIsNone(task["verdict"])
        self.assertEqual(1, task["attempts"]["work"])
        self.assertEqual([], store.load()["outbox"])


if __name__ == "__main__":
    unittest.main()
