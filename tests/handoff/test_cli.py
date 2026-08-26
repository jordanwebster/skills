from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
HANDOFF = ROOT / "skills" / "handoff" / "scripts" / "handoff"


class HandoffCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary.name) / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "Handoff Test"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.email", "handoff@example.invalid"], check=True)
        (self.repo / "app.txt").write_text("working\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "app.txt"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-q", "-m", "working result"], check=True)
        self.commit = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        self.workspace = self.repo / ".handoff" / "result"
        (self.workspace / "captures").mkdir(parents=True)
        (self.workspace / "captures" / "result.txt").write_text("request succeeded once\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def bundle(self, mode: str = "compact") -> dict:
        value = {
            "schema_version": 1,
            "mode": mode,
            "title": "Retry completes without a duplicate charge",
            "reviewed_commit": self.commit,
            "accepted_demonstrations": [
                {"id": "retry", "description": "A timed-out checkout can be retried"},
                {"id": "single", "description": "The retry produces one charge"},
            ],
            "changes": ["Timed-out checkout attempts can now be retried safely."],
            "claims": [{
                "claim": "One retry completes with one charge.",
                "demonstrations": ["retry", "single"],
                "artifacts": [{
                    "path": "captures/result.txt",
                    "kind": "transcript",
                    "label": "Checkout transcript",
                }],
                "replay": {"kind": "command", "command": "timeout 30 tests/retry.sh"},
                "gap": "none",
            }],
            "decisions": [],
            "follow_ups": [],
        }
        if mode == "page":
            value["review"] = {
                "reviewer": "Fresh reviewer",
                "reviewed_commit": self.commit,
                "summary": "The implementation and supplied proof hold.",
                "limitations": [],
            }
        return value

    def run_handoff(self, bundle: dict, *arguments: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        (self.workspace / "proof.json").write_text(json.dumps(bundle), encoding="utf-8")
        return subprocess.run(
            [str(HANDOFF), "finish", str(self.workspace), "--json", "--no-open", *arguments],
            capture_output=True,
            text=True,
            env=env,
            timeout=15,
            check=False,
        )

    def test_compact_proof_supports_many_to_many_coverage_without_review(self) -> None:
        bundle = self.bundle()
        bundle["claims"].append({
            "claim": "The retry remains available after the timeout.",
            "demonstrations": ["retry"],
            "artifacts": bundle["claims"][0]["artifacts"],
            "replay": {"kind": "steps", "steps": ["Open checkout", "Choose Retry"]},
            "gap": "none",
        })
        completed = self.run_handoff(bundle)
        self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)
        result = json.loads(completed.stdout)
        self.assertEqual("ready", result["status"])
        self.assertEqual("compact", result["mode"])
        self.assertEqual("proof.md", Path(result["output"]).name)
        self.assertEqual((self.workspace / "captures" / "result.txt").stat().st_size, result["media_bytes"])
        proof = (self.workspace / "proof.md").read_text(encoding="utf-8")
        self.assertIn("One retry completes with one charge", proof)
        self.assertIn("[Checkout transcript](captures/result.txt)", proof)
        self.assertNotIn("retry, single", proof)

    def test_page_requires_and_renders_fresh_review(self) -> None:
        completed = self.run_handoff(self.bundle("page"))
        self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)
        page = (self.workspace / "handoff.html").read_text(encoding="utf-8")
        self.assertIn("Independent review", page)
        self.assertIn("A timed-out checkout can be retried", page)
        self.assertIn("request succeeded once", page)
        self.assertNotIn("dispatch logs", page)

        stale = self.bundle("page")
        stale["review"]["reviewed_commit"] = "0" * 40
        failed = self.run_handoff(stale)
        self.assertEqual(1, failed.returncode)
        error = json.loads(failed.stdout)
        self.assertEqual("invalid_work", error["error"]["class"])
        self.assertIn("stale", error["error"]["message"])
        self.assertIn("run handoff finish again", error["error"]["recovery"])

    def test_rejects_uncovered_acceptance_and_unknown_ids(self) -> None:
        bundle = self.bundle()
        bundle["claims"][0]["demonstrations"] = ["retry"]
        failed = self.run_handoff(bundle)
        self.assertEqual(1, failed.returncode)
        self.assertIn("lack proof coverage", json.loads(failed.stdout)["error"]["message"])

        bundle = self.bundle()
        bundle["claims"][0]["demonstrations"].append("unknown")
        failed = self.run_handoff(bundle)
        self.assertEqual(1, failed.returncode)
        self.assertIn("unknown demonstration", json.loads(failed.stdout)["error"]["message"])

    def test_validates_commit_paths_placeholders_and_media_budget(self) -> None:
        stale = self.bundle()
        stale["reviewed_commit"] = "0" * 40
        self.assertIn("current commit", json.loads(self.run_handoff(stale).stdout)["error"]["message"])

        escaped = self.bundle()
        escaped["claims"][0]["artifacts"][0]["path"] = "../app.txt"
        self.assertIn("inside", json.loads(self.run_handoff(escaped).stdout)["error"]["message"])

        placeholder = self.bundle()
        placeholder["changes"] = ["TODO explain this"]
        self.assertIn("placeholder", json.loads(self.run_handoff(placeholder).stdout)["error"]["message"])

        internal = self.bundle()
        internal["changes"] = ["Stored a dispatch ID for the operator."]
        self.assertIn("internal workflow", json.loads(self.run_handoff(internal).stdout)["error"]["message"])

        environment = dict(os.environ, HANDOFF_MEDIA_BUDGET_BYTES="4")
        over = self.run_handoff(self.bundle(), env=environment)
        self.assertIn("media budget", json.loads(over.stdout)["error"]["message"])

    def test_supports_steps_and_accepted_non_replayable_recipes(self) -> None:
        bundle = self.bundle()
        bundle["claims"][0]["replay"] = {"kind": "steps", "steps": ["Open checkout", "Choose Retry"]}
        self.assertEqual(0, self.run_handoff(bundle).returncode)

        bundle["claims"][0]["replay"] = {
            "kind": "not_replayable",
            "accepted_reason": "The operator accepted a production-only observation.",
            "limitation": "It cannot be recreated locally.",
        }
        self.assertEqual(0, self.run_handoff(bundle).returncode)


if __name__ == "__main__":
    unittest.main()
