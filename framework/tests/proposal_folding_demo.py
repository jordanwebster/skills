from __future__ import annotations

import json

from scaffold.adapters.fake import FakeAdapter
from scaffold.loop import run_loop
from test_proposals import ProposalFoldingTests, task


class DemoPlanner:
    def fold(self, state, proposals, batch_id):
        return {
            "schema_version": 1,
            "batch_id": batch_id,
            "routes": [
                {
                    "proposal_id": "build-index",
                    "disposition": "in-envelope",
                    "reason": "The index directly serves the fixture goal.",
                    "task": {
                        "id": "index",
                        "title": "Build the index",
                        "template": "text-artifact",
                        "depends_on": ["source"],
                        "decisions": ["Keep the index text-only."],
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


def main() -> int:
    fixture = ProposalFoldingTests(methodName="runTest")
    fixture.setUp()
    try:
        store = fixture.make_store(
            "demo",
            [task("source")],
            proposal_templates={
                "text-artifact": {
                    "role": "implementer",
                    "effort": "small",
                    "check": "python3 checks/check_file.py {task_id}.txt",
                    "test_changes": False,
                }
            },
        )
        adapter = FakeAdapter(
            fixture.script(
                "demo",
                [
                    {
                        "task_id": "source",
                        "commit_message": "Build source",
                        "writes": {"source.txt": "source\n"},
                        "proposals": [
                            {
                                "id": "build-index",
                                "title": "Build an index",
                                "rationale": "Make the source discoverable.",
                                "suggested_dependencies": ["source"],
                            },
                            {
                                "id": "future-polish",
                                "title": "Polish the output",
                                "rationale": "Add decorative output later.",
                                "suggested_dependencies": ["source"],
                            },
                            {
                                "id": "change-format",
                                "title": "Change the output format",
                                "rationale": "Consider a second format.",
                                "suggested_dependencies": ["source"],
                            },
                        ],
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
            fixture.product,
            adapter,
            holder="demo-worker",
            planner=DemoPlanner(),
            clock=lambda: 100.0,
        )
        state = store.load()
        print(
            json.dumps(
                {
                    "run_status": result.status,
                    "tasks": [
                        {
                            "id": item["id"],
                            "depends_on": item["depends_on"],
                            "verdict": item["verdict"],
                        }
                        for item in state["tasks"]
                    ],
                    "proposal_routes": {
                        item["id"]: item["routing"]["disposition"]
                        for item in state["proposals"]
                    },
                    "local_followups": [
                        item["proposal_id"] for item in state["followups"]
                    ],
                    "operator_questions": [
                        {
                            "trigger": item["trigger"],
                            "request": item["request"],
                        }
                        for item in state["outbox"]
                    ],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    finally:
        fixture.doCleanups()


if __name__ == "__main__":
    raise SystemExit(main())
