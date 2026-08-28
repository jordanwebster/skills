from __future__ import annotations

from pathlib import Path
import re
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autopilot import render
from autopilot.plan import read_plan

from pagecheck import Page, assert_operator_page


PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478da6364f8cfc000000301010018dd8db00000000049454e44ae426082"
)


class MarkdownTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.dir = Path(self.temporary.name)

    def test_tables_lists_links_and_code(self) -> None:
        text = (
            "## PROOF\n\n"
            "| Claim | Evidence |\n| --- | --- |\n| Login works | `tests/login.sh` |\n\n"
            "1. first\n2. second\n\n"
            "- a [link](https://example.test/x)\n- **bold** and `code`\n\n"
            "```\nraw <text>\n```\n"
        )
        html = render.markdown(text)
        self.assertIn("<h3>PROOF</h3>", html)
        self.assertIn('<th scope="col">Claim</th>', html)
        self.assertIn("<caption>PROOF</caption>", html)
        self.assertIn("<td>Login works</td><td><code>tests/login.sh</code></td>", html)
        self.assertIn("<ol>\n<li>first</li>\n<li>second</li>\n</ol>", html)
        self.assertIn("<a href='https://example.test/x'>link</a>", html)
        self.assertIn("<strong>bold</strong> and <code>code</code>", html)
        self.assertIn("<pre>\nraw &lt;text&gt;\n</pre>", html)

    def test_headings_demote_relative_to_their_container(self) -> None:
        text = "# Overview\n\n## Detail\n"
        inside_a_section = render.markdown(text, base_level=2)
        self.assertIn("<h3>Overview</h3>", inside_a_section)
        self.assertIn("<h4>Detail</h4>", inside_a_section)

        under_the_masthead = render.markdown(text, base_level=1)
        self.assertIn("<h2>Overview</h2>", under_the_masthead)
        self.assertIn("<h3>Detail</h3>", under_the_masthead)

    def test_deepest_authored_heading_never_skips_a_level(self) -> None:
        html = render.markdown("### Only heading\n\n#### Below it\n", base_level=2)
        self.assertIn("<h3>Only heading</h3>", html)
        self.assertIn("<h4>Below it</h4>", html)

    def test_images_are_inlined_relative_to_the_page(self) -> None:
        (self.dir / "shots").mkdir()
        (self.dir / "shots" / "checkout.png").write_bytes(PNG)
        html = render.markdown("![Checkout after the fix](shots/checkout.png)\n", base=self.dir)
        self.assertIn("<img src='data:image/png;base64,iVBOR", html)
        self.assertIn("<figcaption>Checkout after the fix</figcaption>", html)

    def test_video_and_missing_media(self) -> None:
        (self.dir / "flow.webm").write_bytes(b"\x1aE\xdf\xa3fake")
        html = render.markdown("![The whole flow](flow.webm)\n\n![gone](missing.png)\n", base=self.dir)
        self.assertIn("<video controls src='data:video/webm;base64,", html)
        self.assertIn("Missing media: <code>missing.png</code>", html)

    def test_remote_media_is_named_rather_than_fetched(self) -> None:
        html = render.markdown("![remote](https://example.test/a.png)\n")
        self.assertNotIn("<img", html)
        self.assertIn("Remote media is not embedded", html)

    def test_oversized_media_is_named_not_inlined(self) -> None:
        big = self.dir / "big.png"
        big.write_bytes(b"\0" * 16)
        original = render.INLINE_MEDIA_LIMIT
        render.INLINE_MEDIA_LIMIT = 8
        try:
            html = render.markdown("![huge](big.png)\n", base=self.dir)
        finally:
            render.INLINE_MEDIA_LIMIT = original
        self.assertIn("not inlined", html)
        self.assertNotIn("base64", html)


ACCEPTANCE = {
    "acceptance": {
        "demonstrations": [
            {"id": "replay-demo", "description": "A recorded session replays byte for byte without credentials"},
            {"id": "capture-demo", "description": "Live capture refuses to run without explicit authority"},
        ]
    }
}

STAFFING = [
    {
        "role": "implementer",
        "mind": {"family": "codex", "model": "gpt-test", "effort": "high"},
        "constraints": {"sandbox": "workspace-write"},
        "preferred": {},
    },
    {
        "role": "prober",
        "mind": {"family": "claude", "model": "opus-test", "effort": "low"},
        "constraints": {},
        "preferred": {},
    },
]

PLAN_SOURCE = """# Offline replay for the streaming SDK

## Goal

Anyone can replay a recorded session offline and get identical output, so
decode bugs are reproducible without credentials.

**Done means:** the replay suite passes offline from versioned fixtures.

## Route

### Milestone 1 — typed here but never rendered

- **Produces:** A recorded corpus and a finding: which frame set is canonical.
- **Unlocks:** M2 harness work and the decoder that follows it.
- **Validated by:** A person reads the survey; corpus hashes are deterministic.
- **Branch:** Which frame set is canonical?
  - If only the newer set appears → M2 builds one decoder (default)
  - If both sets appear → M2 splits, through replanning

### Milestone 2 — typed here but never rendered

- **Produces:** Versioned fixtures and a replay runner with remainder accounting.
- **Unlocks:** Decoder work against recorded traffic.
- **Validated by:** Boundary replay; fast, offline, and deterministic.
- **Enables:** M3 — replayed from recorded fixtures, offline and deterministic, in under ten seconds.

### Milestone 3 — typed here but never rendered

- **Produces:** The frame decoder and the surface a caller sees.
- **Unlocks:** The landed branch.
- **Validated by:** Whole-flight verification over the recorded corpus.

## Shape

### Components

- **FrameDecoder** — owns frame to event translation, lives in `src/decode/`.

### Interfaces and APIs

- `decode(bytes)` — never drops an unknown frame; surfaces it with its payload.

### Data shapes

- **Session** — identity, start time, frames; produced by the recorder.

## Human judgment

Whether the canonical choice is the one the ecosystem actually uses.

## What you will be asked

| Act | When | Default | Exposure |
| --- | --- | --- | --- |
| Approve this route | Now | Nothing starts | Ten minutes |
| Confirm the canonical frame set | After the survey | The newer set only | One milestone |

## Out of scope

- Rewriting the transport layer.

## Open questions

| Question | Default if you say nothing | Blast radius if the default is wrong |
| --- | --- | --- |
| Should the recorder keep raw payloads? | Keep them | Larger fixtures |

## Rejected alternatives

- **A live-only test suite** — needs credentials in continuous integration.

## Deployment notes

Nothing here changes how the package is published.

```flight-plan
{
  "goal": "Replay recorded sessions offline",
  "config": {
    "max_iterations": 40,
    "expected_iterations": {"min": 8, "max": 14},
    "check": "timeout 900 make verify",
    "preflight": ["timeout 60 make tools"]
  },
  "evidence": [
    {
      "id": "replay-evidence",
      "claim": "A recorded session replays byte for byte",
      "demonstrations": ["replay-demo"],
      "stages": [2, 3],
      "artifacts": ["evidence/replay.txt"],
      "replay": {"kind": "command", "command": "timeout 300 make replay"}
    },
    {
      "id": "capture-evidence",
      "claim": "Live capture refuses without authority",
      "demonstrations": ["capture-demo"],
      "stages": [3],
      "artifacts": ["evidence/refusal.png"],
      "replay": {"kind": "steps", "steps": ["Run the capture command", "Read the refusal"]}
    }
  ],
  "chunks": [
    {"id": 1, "title": "Wire format survey", "role": "prober", "review": false},
    {"id": 2, "title": "Fixture and replay harness", "role": "implementer", "check": "timeout 600 make fixtures", "review": true},
    {"id": 3, "title": "Frame decoder", "role": "implementer", "check": "timeout 600 make decode", "review": true}
  ],
  "tasks": [
    {"id": 1, "chunk": 1, "title": "Record a canonical corpus", "done_when": "the corpus exists", "role": "prober"},
    {"id": 2, "chunk": 2, "title": "Write the replay runner", "done_when": "the runner replays"},
    {"id": 3, "chunk": 2, "title": "Version the fixtures", "done_when": "fixtures carry a version"},
    {"id": 4, "chunk": 3, "title": "Surface unknown frames", "done_when": "unknown frames survive"}
  ]
}
```
"""


class PlanPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        source = Path(cls.temporary.name) / "plan.md"
        source.write_text(PLAN_SOURCE, encoding="utf-8")
        cls.plan = read_plan(source)
        title, body = render.split_title(PLAN_SOURCE, default="Flight plan")
        cls.html = render.flight_plan(
            body, cls.plan, title=title, staffing=STAFFING, acceptance=ACCEPTANCE,
            meta="claude-sdk · autopilot/replay · 28 Aug 2026",
        )
        cls.page = Page(cls.html)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_it_is_a_self_contained_operator_page(self) -> None:
        assert_operator_page(self, self.html)
        self.assertEqual("Offline replay for the streaming SDK", self.page.title.strip())
        self.assertIn("Autopilot · plan approval", self.html)
        self.assertIn("claude-sdk · autopilot/replay · 28 Aug 2026", self.html)

    def test_the_decision_states_the_ask_the_default_and_the_exposure(self) -> None:
        decision = self.html[self.html.index('class="decision'):self.html.index("</section>")]
        self.assertIn("This route", decision)
        self.assertIn("Nothing starts", decision)
        self.assertIn("8–14 expected calls · ceiling 40", decision)
        self.assertIn("replay suite passes offline", decision)

    def test_one_stage_per_milestone_in_the_machine_block(self) -> None:
        milestones = [int(item["data-milestone"]) for item in self.page.with_class("stage")]
        self.assertEqual([chunk["id"] for chunk in self.plan["chunks"]], milestones)
        for chunk in self.plan["chunks"]:
            self.assertIn(f"Milestone {chunk['id']} — {chunk['title']}", self.html)

    def test_every_stage_states_produces_unlocks_and_validated_by(self) -> None:
        for label in ("Produces", "Unlocks", "Validated by"):
            self.assertEqual(3, self.html.count(f"<dt>{label}</dt>"), label)

    def test_a_research_stage_renders_its_fork_with_exactly_one_default(self) -> None:
        research = [
            item for item in self.page.with_class("stage")
            if "research" in item["data-variant"].split()
        ]
        self.assertEqual(1, len(research))
        self.assertEqual("1", research[0]["data-milestone"])
        self.assertIn("Research fork", self.html)
        self.assertIn("Which frame set is canonical?", self.html)
        self.assertEqual(2, self.html.count('class="fork__outcome"'))
        self.assertEqual(1, self.html.count('class="fork__default">default'))
        self.assertIn("assumes the default", self.html)
        self.assertIn('Conditional on <a href="#m1">Milestone 1</a>', self.html,
                      "a milestone reached only by a non-default outcome says so")

    def test_a_test_infrastructure_stage_links_what_it_makes_testable(self) -> None:
        harness = [
            item for item in self.page.with_class("stage")
            if "harness" in item["data-variant"].split()
        ]
        self.assertEqual(["2"], [item["data-milestone"] for item in harness])
        self.assertIn("Enables testing", self.html)
        self.assertIn("<dt>Enables</dt>", self.html)
        self.assertIn('Testable because of <a href="#m2">Milestone 2</a>', self.html)

    def test_every_milestone_reference_resolves_to_a_stage(self) -> None:
        anchors = self.page.anchors()
        references = set(re.findall(r'href="#(m\d+)"', self.html))
        self.assertTrue(references)
        self.assertEqual(set(), references - anchors)

    def test_gates_task_counts_and_titles_are_derived_not_typed(self) -> None:
        self.assertIn("check + independent review", self.html)
        self.assertIn("task completion", self.html)
        self.assertIn("<summary>2 tasks</summary>", self.html)
        self.assertIn("<summary>1 task</summary>", self.html)
        self.assertNotIn("typed here but never rendered", self.html)

    def test_nothing_on_a_plan_can_look_verified(self) -> None:
        for token in ("--ok", "--caution", "--alert", 'class="mark mark--ok"'):
            self.assertNotIn(token, self.html, token)
        for word in ("Proved", "Verified", "Complete."):
            self.assertNotIn(word, self.html, word)

    def test_machinery_stays_inside_disclosures(self) -> None:
        surface = self.page.outside_details()
        for chunk in self.plan["chunks"]:
            if chunk.get("check"):
                self.assertNotIn(chunk["check"], surface)
        for task in self.plan["tasks"]:
            self.assertNotIn(task["title"], surface)
        for role in ("implementer", "prober", "planner", "closer"):
            self.assertNotIn(role, surface, role)
        for model in ("gpt-test", "opus-test"):
            self.assertNotIn(model, surface, model)

    def test_intended_proof_is_generated_from_evidence_and_acceptance(self) -> None:
        claims = self.page.with_class("claim")
        self.assertEqual(len(self.plan["evidence"]), len(claims))
        for demonstration in ACCEPTANCE["acceptance"]["demonstrations"]:
            self.assertIn(demonstration["description"], self.html)
            self.assertNotIn(demonstration["id"], self.page.all_text())
        for item in self.plan["evidence"]:
            self.assertNotIn(item["id"], self.page.all_text())
        self.assertIn('<a href="#m2">Milestone 2</a>, <a href="#m3">Milestone 3</a>', self.html)
        self.assertIn("Expected", self.html)
        self.assertIn("a transcript", self.html)
        self.assertIn("a screenshot", self.html)
        self.assertIn("Judged by a person", self.html)
        self.assertIn("Will show", self.html)

    def test_sections_appear_in_the_order_the_decision_needs_them(self) -> None:
        order = self.page.order_of(
            'id="decision"', ">Route<", ">Shape<", ">Intended proof<",
            ">What you will be asked<", ">Open questions<",
            ">Scope and rejected alternatives<", "Bounds and preflight",
        )
        self.assertEqual(sorted(order), order)

    def test_an_unrecognised_section_still_renders_generically(self) -> None:
        self.assertIn("Deployment notes", self.html)
        self.assertIn("Nothing here changes how the package is published.", self.html)

    def test_diagnostics_are_three_separate_disclosures(self) -> None:
        for summary in ("Staffing (2 roles)", "Tasks by milestone (4 tasks)", "Bounds and preflight"):
            self.assertIn(f"<summary>{summary}</summary>", self.html)
        self.assertEqual(3, self.html.count('class="dis dis--block dis--diagnostics"'))
        self.assertNotIn('.autopilot', self.html)


if __name__ == "__main__":
    unittest.main()
