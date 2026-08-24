#!/usr/bin/env python3
"""Print a human-readable boundary dump for M5 review routing."""

from __future__ import annotations

import json

from scaffold.adapters.fake import FakeAdapter
from scaffold.loop import run_loop
from test_review_routing import ReviewRoutingTests, derived_id, finding


def clean_gate() -> dict[str, object]:
    case = ReviewRoutingTests()
    case.setUp()
    try:
        store = case.make_store(downstream=True)
        remediation_id = derived_id("remediate", "review", "unsafe-boundary")
        rereview_id = derived_id("rereview", "review", "unsafe-boundary")
        script = case.write_script(
            [
                {
                    "task_id": "review",
                    "review": {
                        "findings": [finding("unsafe-boundary", "medium")]
                    },
                },
                {
                    "task_id": remediation_id,
                    "commit_message": "Fix before downstream work",
                    "writes": {"fixed.txt": "fixed\n"},
                },
                {"task_id": rereview_id, "review": {"findings": []}},
                {
                    "task_id": "downstream",
                    "commit_message": "Use reviewed work",
                    "writes": {"downstream.txt": "used\n"},
                },
            ]
        )
        result = run_loop(
            store,
            case.product,
            FakeAdapter(script, store),
            holder="demo-reviewer",
        )
        tasks = {task["id"]: task for task in store.load()["tasks"]}
        return {
            "scenario": "finding fixed by the bounded review path",
            "status": result.status,
            "execution_order": list(result.completed_task_ids),
            "downstream_depends_on": tasks["downstream"]["depends_on"],
            "review_verdict": tasks["review"]["verdict"],
            "rereview_verdict": tasks[rereview_id]["verdict"],
            "open_questions": store.load()["outbox"],
        }
    finally:
        case.doCleanups()


def surviving_finding() -> dict[str, object]:
    case = ReviewRoutingTests()
    case.setUp()
    try:
        store = case.make_store()
        remediation_id = derived_id("remediate", "review", "unsafe-boundary")
        rereview_id = derived_id("rereview", "review", "unsafe-boundary")
        script = case.write_script(
            [
                {
                    "task_id": "review",
                    "review": {
                        "findings": [finding("unsafe-boundary", "critical")]
                    },
                },
                {
                    "task_id": remediation_id,
                    "commit_message": "Attempt reviewed fix",
                    "writes": {"fixed.txt": "attempted\n"},
                },
                {
                    "task_id": rereview_id,
                    "review": {
                        "findings": [finding("unsafe-boundary", "high")]
                    },
                },
            ]
        )
        result = run_loop(
            store,
            case.product,
            FakeAdapter(script, store),
            holder="demo-reviewer",
            clock=lambda: 42.0,
        )
        state = store.load()
        return {
            "scenario": "finding survives the only re-review",
            "status": result.status,
            "task_count": len(state["tasks"]),
            "task_verdicts": {
                task["id"]: task["verdict"] for task in state["tasks"]
            },
            "open_question_trigger": state["outbox"][0]["trigger"],
            "open_question_task": state["outbox"][0]["task_id"],
        }
    finally:
        case.doCleanups()


if __name__ == "__main__":
    print(json.dumps([clean_gate(), surviving_finding()], indent=2, sort_keys=True))
