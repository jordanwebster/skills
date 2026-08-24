"""M3 goal function: a supervised fake-worker flight verifies to green."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main() -> int:
    with tempfile.TemporaryDirectory() as temporary_directory:
        root = Path(temporary_directory)
        product = root / "product"
        product.mkdir()
        _git(product, "init", "--quiet")
        _git(product, "config", "user.name", "Toy Worker")
        _git(product, "config", "user.email", "toy@example.invalid")
        (product / "README.md").write_text("# Toy flight\n", encoding="utf-8")
        checks = product / "checks"
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
        _git(product, "add", "README.md", "checks/check_file.py")
        _git(product, "commit", "--quiet", "-m", "Initialize toy product")

        plan = root / "plan.html"
        machine = {
            "schema_version": 1,
            "goal": "Build and wrap a toy product",
            "test_paths": ["checks/**", "tests/**"],
            "tasks": [
                {
                    "id": "build",
                    "title": "Build the toy artifact",
                    "role": "implementer",
                    "effort": "small",
                    "check": "python3 checks/check_file.py artifact.txt",
                    "depends_on": [],
                    "decisions": ["Write the artifact at artifact.txt"],
                },
                {
                    "id": "wrap",
                    "title": "Wrap the toy flight",
                    "role": "implementer",
                    "effort": "small",
                    "check": "python3 checks/check_file.py wrapped.txt",
                    "depends_on": ["build"],
                    "decisions": ["Write the wrap marker at wrapped.txt"],
                },
            ],
        }
        plan.write_text(
            "<h1>Toy flight plan</h1>\n"
            '<script type="application/json" id="scaffold-plan">\n'
            + json.dumps(machine)
            + "\n</script>\n",
            encoding="utf-8",
        )
        fake_script = root / "fake.json"
        fake_script.write_text(
            json.dumps(
                {
                    "steps": [
                        {
                            "task_id": "build",
                            "commit_message": "Build toy artifact",
                            "writes": {"artifact.txt": "built\n"},
                        },
                        {
                            "task_id": "wrap",
                            "commit_message": "Wrap toy flight",
                            "writes": {"wrapped.txt": "wrapped\n"},
                        },
                    ]
                }
            )
            + "\n",
            encoding="utf-8",
        )

        init = _scaffold("init", "--repo", str(product), "--goal", machine["goal"])
        workspace = Path(init.stdout.strip())
        _scaffold("plan-import", str(workspace), str(plan))
        _scaffold(
            "run",
            str(workspace),
            "--adapter",
            "fake",
            "--script",
            str(fake_script),
        )

        state = json.loads((workspace / "tasks.json").read_text(encoding="utf-8"))
        if [task["id"] for task in state["tasks"]] != ["build", "wrap"]:
            raise AssertionError("plan order was not preserved")
        if not all(
            task["completion"] == "complete" and task["verdict"] == "green"
            for task in state["tasks"]
        ):
            raise AssertionError("toy flight did not wrap with every task green")
        if _git(product, "status", "--porcelain").strip():
            raise AssertionError("toy product is dirty after the wrapped flight")
        if _git(product, "rev-list", "--count", "HEAD").strip() != "3":
            raise AssertionError("toy flight did not land one commit per task")
        if not (product / "artifact.txt").is_file() or not (
            product / "wrapped.txt"
        ).is_file():
            raise AssertionError("toy flight omitted a demonstrated artifact")

    print("toy flight M3 green")
    return 0


def _scaffold(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "scaffold", *arguments],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
        env=os.environ.copy(),
    )


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout


if __name__ == "__main__":
    raise SystemExit(main())
