from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

import scaffold.verify as verify_module
from scaffold.verify import CLOSED_VERDICTS, verify


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


class VerificationRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.product = self.root / "product"
        self.product.mkdir()
        git(self.product, "init", "--quiet")
        git(self.product, "config", "user.name", "Verifier Test")
        git(self.product, "config", "user.email", "verify@example.invalid")
        checks = self.product / "checks"
        checks.mkdir()
        (checks / "result.py").write_text(
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
                    "id": "target-exists",
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
        (checks / "hang.py").write_text(
            """from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
Path(os.environ["SCAFFOLD_PID_PATH"]).write_text(str(child.pid), encoding="utf-8")
child.wait()
""",
            encoding="utf-8",
        )
        (self.product / "README.md").write_text("# Product\n", encoding="utf-8")
        git(
            self.product,
            "add",
            "README.md",
            "checks/result.py",
            "checks/hang.py",
        )
        git(self.product, "commit", "--quiet", "-m", "Initialize verifier product")
        self.base_head = git(self.product, "rev-parse", "HEAD")
        (self.product / "artifact.txt").write_text("built\n", encoding="utf-8")
        git(self.product, "add", "artifact.txt")
        git(self.product, "commit", "--quiet", "-m", "Build artifact")
        self.candidate_head = git(self.product, "rev-parse", "HEAD")
        self.task = {
            "id": "build",
            "check": "python3 checks/result.py artifact.txt",
            "test_changes": False,
        }

    def run_verify(self, task: dict[str, object] | None = None):
        return verify(
            task or self.task,
            self.product,
            self.root / "flight",
            holder="worker",
            lease_id="lease-1",
            base_head=self.base_head,
            candidate_head=self.candidate_head,
            test_paths=["checks/**", "tests/**"],
            timeout=10,
        )

    def test_green_verdict_is_derived_from_structured_results(self) -> None:
        verdict = self.run_verify()

        self.assertEqual("green", verdict.kind)
        self.assertEqual(CLOSED_VERDICTS, frozenset({
            "green", "red", "infra", "killed", "malformed"
        }))
        artifact = json.loads(verdict.artifact_path.read_text(encoding="utf-8"))
        self.assertEqual(self.candidate_head, artifact["candidate_head"])
        self.assertEqual(
            [{"id": "target-exists", "status": "passed"}],
            artifact["result"]["observations"],
        )
        self.assertTrue(artifact["candidate_tree"])
        self.assertIn("checks/result.py", artifact["protected_hashes"]["base"])
        self.assertEqual([], artifact["protected_changes"])

    def test_check_executes_in_restored_checkout_not_worker_worktree(self) -> None:
        (self.product / "artifact.txt").unlink()

        verdict = self.run_verify()

        self.assertEqual("green", verdict.kind)
        self.assertNotEqual("", git(self.product, "status", "--porcelain"))

    def test_candidate_must_descend_from_the_pre_dispatch_base(self) -> None:
        verdict = verify(
            self.task,
            self.product,
            self.root / "flight",
            holder="worker",
            lease_id="lease-2",
            base_head=self.candidate_head,
            candidate_head=self.candidate_head,
            test_paths=["checks/**"],
            timeout=10,
        )

        self.assertEqual("red", verdict.kind)
        self.assertIn("new commit", verdict.reason)

    def test_filed_candidate_must_be_the_product_head(self) -> None:
        verdict = verify(
            self.task,
            self.product,
            self.root / "flight",
            holder="worker",
            lease_id="lease-wrong-head",
            base_head=self.base_head,
            candidate_head=self.base_head,
            test_paths=["checks/**"],
            timeout=10,
        )

        self.assertEqual("red", verdict.kind)
        self.assertIn("repository HEAD", verdict.reason)

    def test_observation_count_cannot_shrink_without_recorded_scope(self) -> None:
        verdict = verify(
            self.task,
            self.product,
            self.root / "flight",
            holder="worker",
            lease_id="lease-shrunk",
            base_head=self.base_head,
            candidate_head=self.candidate_head,
            test_paths=["checks/**"],
            timeout=10,
            minimum_observations=2,
        )

        self.assertEqual("red", verdict.kind)
        self.assertIn("count shrank", verdict.reason)

    def test_explicit_test_scope_allows_a_protected_edit(self) -> None:
        git(self.product, "reset", "--hard", "--quiet", self.candidate_head)
        (self.product / "checks" / "result.py").write_text(
            (self.product / "checks" / "result.py")
            .read_text(encoding="utf-8")
            .replace('"target-exists"', '"renamed-check"'),
            encoding="utf-8",
        )
        git(self.product, "add", "checks/result.py")
        git(self.product, "commit", "--quiet", "-m", "Rename scoped check")
        scoped_head = git(self.product, "rev-parse", "HEAD")
        scoped_task = dict(self.task, test_changes=True)

        verdict = verify(
            scoped_task,
            self.product,
            self.root / "flight",
            holder="worker",
            lease_id="lease-3",
            base_head=self.candidate_head,
            candidate_head=scoped_head,
            test_paths=["checks/**"],
            timeout=10,
        )

        self.assertEqual("green", verdict.kind)
        self.assertEqual(["checks/result.py"], list(verdict.protected_changes))

    def test_mode_only_protected_edit_is_detected(self) -> None:
        checker = self.product / "checks" / "result.py"
        checker.chmod(checker.stat().st_mode | stat.S_IXUSR)
        git(self.product, "add", "checks/result.py")
        git(self.product, "commit", "--quiet", "-m", "Change checker mode")
        mode_head = git(self.product, "rev-parse", "HEAD")

        verdict = verify(
            self.task,
            self.product,
            self.root / "flight",
            holder="worker",
            lease_id="lease-mode",
            base_head=self.candidate_head,
            candidate_head=mode_head,
            test_paths=["checks/**"],
            timeout=10,
        )

        self.assertEqual("red", verdict.kind)
        self.assertEqual(["checks/result.py"], list(verdict.protected_changes))

    def test_timed_out_check_kills_its_process_group(self) -> None:
        pid_path = self.root / "descendant.pid"
        hanging_task = dict(
            self.task,
            check=f"SCAFFOLD_PID_PATH={pid_path} python3 checks/hang.py",
        )

        verdict = verify(
            hanging_task,
            self.product,
            self.root / "flight",
            holder="worker",
            lease_id="lease-timeout",
            base_head=self.base_head,
            candidate_head=self.candidate_head,
            test_paths=["checks/**"],
            timeout=0.2,
        )

        self.assertEqual("killed", verdict.kind)
        descendant_pid = int(pid_path.read_text(encoding="utf-8"))
        for _ in range(50):
            try:
                os.kill(descendant_pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.01)
        else:
            os.kill(descendant_pid, signal.SIGKILL)
            self.fail("verification descendant survived its process-group timeout")

    def test_verification_directory_hierarchy_is_fsynced(self) -> None:
        store_root = self.root / "durable-flight"
        store_root.mkdir()
        original_fsync = verify_module._fsync_directory
        observed: list[Path] = []

        def record_fsync(path: Path) -> None:
            observed.append(path)
            original_fsync(path)

        with patch("scaffold.verify._fsync_directory", side_effect=record_fsync):
            verdict = verify(
                self.task,
                self.product,
                store_root,
                holder="worker",
                lease_id="lease-durable",
                base_head=self.base_head,
                candidate_head=self.candidate_head,
                test_paths=["checks/**"],
                timeout=10,
            )

        self.assertEqual("green", verdict.kind)
        durable_root = store_root.resolve()
        self.assertTrue(
            {
                durable_root,
                durable_root / "verifications",
                durable_root / "verifications" / "build",
                durable_root / "verifications" / "build" / "lease-durable",
            }.issubset(set(observed))
        )


if __name__ == "__main__":
    unittest.main()
