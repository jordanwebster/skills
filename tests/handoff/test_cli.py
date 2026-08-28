from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
HANDOFF = ROOT / "skills" / "handoff" / "scripts" / "handoff"

sys.path.insert(0, str(ROOT / "tests"))

from pagecheck import Page, assert_operator_page

# Autopilot's process vocabulary. A merge decision is made from the result and
# its review; how the work was scheduled is not the operator's business here.
PROCESS_WORDS = (
    "milestone", "chunk", "task", "dispatch", "iteration", "reviewer round", ".autopilot",
)


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

    def page_for(self, bundle: dict) -> str:
        completed = self.run_handoff(bundle)
        self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)
        return (self.workspace / "handoff.html").read_text(encoding="utf-8")

    def test_page_requires_and_renders_fresh_review(self) -> None:
        page = self.page_for(self.bundle("page"))
        assert_operator_page(self, page)
        self.assertIn("Handoff · merge decision", page)
        self.assertIn("Independent review", page)
        self.assertIn("The implementation and supplied proof hold.", page)
        self.assertIn("A timed-out checkout can be retried", page)
        self.assertIn("request succeeded once", page)
        self.assertIn(self.commit[:7], page)

        stale = self.bundle("page")
        stale["review"]["reviewed_commit"] = "0" * 40
        failed = self.run_handoff(stale)
        self.assertEqual(1, failed.returncode)
        error = json.loads(failed.stdout)
        self.assertEqual("invalid_work", error["error"]["class"])
        self.assertIn("stale", error["error"]["message"])
        self.assertIn("run handoff finish again", error["error"]["recovery"])

    def test_the_verdict_and_the_ask_are_derived_from_the_evidence(self) -> None:
        holds = Page(self.page_for(self.bundle("page")))
        self.assertIn('data-verdict="holds"', holds.source)
        self.assertIn("Merge this work.", holds.source)
        self.assertIn("0 gaps · 0 review limitations", holds.source)
        self.assertIn("The review reports no limitation.", holds.source)

        limited = self.bundle("page")
        limited["review"]["limitations"] = ["the Windows path"]
        page = self.page_for(limited)
        self.assertIn('data-verdict="holds-with-limits"', page)
        self.assertIn("Every claim has supporting evidence", page)
        self.assertNotIn("Everything promised is shown", page)
        self.assertIn("Merge knowing: the Windows path.", page)
        self.assertIn("The review did not cover: the Windows path.", page)
        self.assertIn("0 gaps · 1 review limitation", page)

        blocked = self.bundle("page")
        blocked["claims"][0]["artifacts"] = []
        blocked["claims"][0]["gap"] = "The retry was never run against a real timeout"
        page = self.page_for(blocked)
        self.assertIn('data-verdict="not-decidable"', page)
        self.assertIn("Do not merge yet: The retry was never run against a real timeout.", page)
        self.assertIn("No merge, no publication", page)

    def test_every_claim_carries_a_coverage_state_and_an_explicit_gap(self) -> None:
        bundle = self.bundle("page")
        bundle["claims"].append({
            "claim": "The retry remains available after the timeout.",
            "demonstrations": ["retry"],
            "artifacts": bundle["claims"][0]["artifacts"],
            "replay": {"kind": "steps", "steps": ["Open checkout", "Choose Retry"]},
            "gap": "Only the supplied fixture was exercised",
        })
        page = Page(self.page_for(bundle))
        claims = page.with_class("claim")
        self.assertEqual(["proved", "limited"], [item["data-coverage"] for item in claims])
        self.assertIn("Proved with limits", page.source)
        self.assertIn("No gap.", page.source)
        self.assertIn("Only the supplied fixture was exercised", page.source)
        self.assertLess(
            page.source.index("Only the supplied fixture"),
            page.source.index("Open checkout"),
            "the gap is read before the evidence, not after it",
        )

    def test_unlabelled_image_evidence_has_a_filename_alt(self) -> None:
        image = self.workspace / "captures" / "result.png"
        image.write_bytes(b"not a real png")
        bundle = self.bundle("page")
        bundle["claims"][0]["artifacts"] = [{"path": "captures/result.png"}]
        page = self.page_for(bundle)
        self.assertIn('alt="result.png"', page)

    def test_a_not_replayable_capture_holds_with_limits_without_a_gap(self) -> None:
        bundle = self.bundle("page")
        bundle["claims"][0]["replay"] = {
            "kind": "not_replayable",
            "accepted_reason": "The operator accepted a production-only observation.",
            "limitation": "It cannot be recreated locally.",
        }
        page = Page(self.page_for(bundle))
        self.assertEqual(["limited"], [item["data-coverage"] for item in page.with_class("claim")])
        self.assertIn("Merge knowing: It cannot be recreated locally.", page.source)
        self.assertIn("0 gaps · 0 review limitations", page.source)

    def test_follow_ups_are_visibly_outside_the_decision(self) -> None:
        bundle = self.bundle("page")
        bundle["decisions"] = [{
            "decision": "Unknown responses surface as a typed unknown result.",
            "instead_of": "dropping them",
            "cost": "one additional public variant",
        }]
        bundle["follow_ups"] = ["Record a Windows fixture set."]
        page = Page(self.page_for(bundle))
        self.assertIn("Decisions taken", page.source)
        self.assertIn("Chosen over dropping them · costs one additional public variant", page.source)
        self.assertIn("Does not affect this decision", page.source)
        self.assertLess(
            page.source.index("Decisions taken"), page.source.index("Follow-ups")
        )
        taken = page.source[page.source.index('rows rows--taken'):]
        self.assertNotIn("Record a Windows fixture set.", taken.split("</ul>")[0])

    def test_a_page_with_nothing_optional_omits_those_sections(self) -> None:
        page = self.page_for(self.bundle("page"))
        self.assertNotIn("Decisions taken", page)
        self.assertNotIn("Follow-ups", page)
        self.assertNotIn("Evidence appendix", page)
        self.assertNotIn("No further product decision remains", page)

    def test_the_page_says_nothing_about_how_the_work_was_run(self) -> None:
        bundle = self.bundle("page")
        bundle["decisions"] = ["Kept the existing retry window."]
        bundle["follow_ups"] = ["Record a Windows fixture set."]
        page = self.page_for(bundle).casefold()
        for word in PROCESS_WORDS:
            self.assertNotIn(word, page, word)

    def test_the_first_change_is_stated_once(self) -> None:
        page = self.page_for(self.bundle("page"))
        self.assertEqual(1, page.count("Timed-out checkout attempts can now be retried safely."))

    def test_a_claim_may_name_a_real_generic_type(self) -> None:
        bundle = self.bundle()
        bundle["claims"][0]["claim"] = "A retry returns Result<Charge, RetryError> once."
        self.assertEqual(0, self.run_handoff(bundle).returncode)

        bundle["claims"][0]["claim"] = "A retry returns <result> once."
        failed = self.run_handoff(bundle)
        self.assertEqual(1, failed.returncode)
        self.assertIn("placeholder", json.loads(failed.stdout)["error"]["message"])

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
