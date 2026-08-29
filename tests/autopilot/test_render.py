from __future__ import annotations

from pathlib import Path
import re
import sys
import tempfile
from typing import Any
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autopilot import render
from autopilot.plan import read_plan, shape_groups

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
        self.assertIn('<td data-label="Claim">Login works</td>'
                      '<td data-label="Evidence"><code>tests/login.sh</code></td>', html,
                      "a cell names the column it answers to, for the narrow layout")
        self.assertIn("<ol>\n<li>first</li>\n<li>second</li>\n</ol>", html)
        self.assertIn("<a href='https://example.test/x'>link</a>", html)
        self.assertIn("<strong>bold</strong> and <code>code</code>", html)
        self.assertIn("<pre>\nraw &lt;text&gt;\n</pre>", html)

    def test_a_link_that_would_execute_is_shown_but_never_active(self) -> None:
        html = render.markdown("[open](javascript:location='https://example.test')\n")
        self.assertNotIn("<a ", html)
        self.assertNotIn("href", html)
        self.assertIn("open", html)
        self.assertIn("<code>javascript:location=", html, "the reader still sees what it was")

        image = render.markdown("![shot](javascript:alert(1))\n")
        self.assertNotIn("<img", image)
        self.assertIn("not a kind the page embeds", image)

    def test_milestone_references_never_rewrite_a_destination_or_nest_a_link(self) -> None:
        html = render.markdown("- [spec](docs/M1.md) explains M1 before M2\n")
        self.assertIn("<a href='docs/M1.md'>spec</a>", html)
        self.assertIn('explains <a href="#m1">M1</a> before <a href="#m2">M2</a>', html)
        self.assertEqual(1, html.count("docs/M1.md"))

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

## Interfaces

### FrameDecoder — owns frame to event translation; lives in `src/decode/`

```rust
// Identity, start time and frames; produced by the recorder.
struct Session {
    id: SessionId,
    frames: Vec<Frame>,
}

// never drops an unknown frame; surfaces it with its payload
fn decode(bytes: &[u8]) -> Result<Event, DecodeError>;
```

### ReplayRunner — owns fixture selection

- **replay** — reads only from versioned fixtures, never from the network.

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

    @property
    def body(self) -> str:
        """The document without its stylesheet.

        The sheet names every class the page can use, so searching the whole
        source for a class finds the rule that defines it rather than the
        element that carries it — and prints a megabyte of embedded font on
        failure."""

        return self.html[self.html.index("</style>"):]

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

    def test_the_masthead_carries_the_objective_and_the_decision_the_rest(self) -> None:
        masthead = self.html[self.html.index('class="masthead"'):self.html.index("<main>")]
        self.assertIn("Anyone can replay a recorded session offline", masthead)
        self.assertNotIn("Done means", masthead, "the qualification belongs beside the ask")
        decision = self.html[self.html.index('class="decision'):self.html.index("</section>")]
        self.assertIn("Done means", decision)
        self.assertEqual(1, self.html.count("Anyone can replay a recorded session"))

    def test_the_plan_leads_with_the_route_not_with_counts(self) -> None:
        # Milestone, fork and claim counts are already the Route and Intended
        # proof headlines. A strip repeating them costs the operator the first
        # screen, which is where the route itself has to be.
        self.assertNotIn('class="metrics"', self.body,
                         "the plan states its counts in the headings that own them")
        masthead = self.body[:self.body.index("<main>")]
        for word in ("Milestones", "Research forks", "Ceiling"):
            self.assertNotIn(word, masthead, word)
        self.assertLess(self.body.index('id="route"'), self.body.index('id="shape"'))

    def test_the_page_carries_its_faces_and_fetches_nothing(self) -> None:
        sheet = self.page.stylesheet()
        for family in ("Newsreader", "IBM Plex Sans", "IBM Plex Mono"):
            self.assertIn(f"font-family:'{family}'", sheet, family)
        self.assertNotIn("https://", sheet.replace("data:font/woff2", ""))
        self.assertIn("src:url(data:font/woff2;base64,", sheet)

    def test_a_state_is_a_word_in_a_chip_not_a_colour(self) -> None:
        self.assertIn('<span class="tag tag--fork">Research fork</span>', self.body)
        self.assertIn('<span class="tag tag--harness">Enables testing</span>', self.body)
        # Colour rides on the border and the text, so a chip survives a
        # monochrome printer and a reader who cannot separate the hues.
        self.assertIn(".tag{display:inline-block;padding:.16em .5em;border:1px solid currentColor",
                      self.page.stylesheet())

    def test_a_section_names_itself_and_says_what_it_holds(self) -> None:
        for name, headline in (
            ("Route", "3 milestones, 1 research fork and 1 testing stage"),
            ("Interfaces", "2 components, 3 declarations"),
            ("Intended proof", "2 claims, 2 captures expected"),
        ):
            self.assertIn(f'<span class="kicker">{name}</span>{headline}</h2>', self.body, name)

    def test_an_interface_group_is_rendered_as_code(self) -> None:
        block = self.body[self.body.index('defs--code'):]
        block = block[:block.index("</div>", block.index("</pre>"))]
        self.assertIn('<span class="tag tag--accent">rust</span>', block,
                      "the group names the language it is written in")
        self.assertIn("owns frame to event translation", block,
                      "the heading says what the component owns")
        self.assertIn("fn decode(bytes: &amp;[u8]) -&gt; Result&lt;Event, DecodeError&gt;;", block)
        # The comment is the prose about the contract, so it is set apart from
        # the contract without a highlighter or a script to run one.
        self.assertIn('<span class="c">// never drops an unknown frame; '
                      'surfaces it with its payload</span>', block)
        self.assertIn("pre .c{color:var(--ink-faint);font-style:italic}", self.page.stylesheet())

    def test_interfaces_are_grouped_one_block_per_component(self) -> None:
        self.assertEqual(2, self.body.count('<section class="defs'))

    def test_a_heading_inside_a_fence_is_code_not_a_new_group(self) -> None:
        # A `###` at the start of a line is a heading everywhere except inside
        # a fence, where it is a comment in half the languages we expect.
        groups = shape_groups(
            "### Interfaces and APIs\n\n```python\n"
            "### how many retries before giving up\n"
            "def send(body: bytes, retries: int = 3) -> Receipt: ...\n"
            "```\n\n### Data shapes\n\n- **Receipt** — what came back.\n"
        )
        self.assertEqual(["Interfaces and APIs", "Data shapes"], [g.name for g in groups])
        self.assertIn("### how many retries", groups[0].code)
        self.assertEqual("python", groups[0].language)
        # A `#` comment counts as prose in Python, so it is not a declaration.
        self.assertEqual(1, render._declarations(groups[0].code, "python"))

    def test_entry_groups_and_code_groups_both_still_render(self) -> None:
        self.assertIn("<h3>FrameDecoder</h3>", self.body, "a code group")
        self.assertIn("<h3>ReplayRunner</h3>", self.body, "an entry group")
        self.assertIn("<dt><strong>replay</strong></dt>", self.body)
        self.assertIn("<pre><code>", self.body)

    def test_the_route_is_drawn_as_a_graph_with_its_edges_named(self) -> None:
        self.assertIn('<figure class="map wide">', self.body)
        self.assertIn("makes testable", self.html, "a harness edge says what it does")
        self.assertIn("shape depends on the outcome", self.html, "a branch edge says what it does")
        figure = self.body[self.body.index('class="map wide"'):]
        figure = figure[:figure.index("</figure>")]
        for milestone in ("M1", "M2", "M3"):
            self.assertIn(f">{milestone}</text>", figure)
        self.assertIn('role="img"', figure)
        self.assertIn("aria-label=", figure, "the claim reaches a reader who cannot see it")
        self.assertNotIn("<style", figure)

    def test_the_map_is_drawn_only_when_it_shows_more_than_the_rail(self) -> None:
        def routes(count: int, **extra: Any) -> list[dict[str, Any]]:
            built = [{"id": index} for index in range(1, count + 1)]
            for index, value in extra.items():
                built[int(index[1:]) - 1].update(value)
            return built

        chunks = {index: {"id": index, "title": f"Stage {index}"} for index in range(1, 9)}
        harness = {"enables": {"text": "t", "milestones": [3]}}
        self.assertEqual("", render.route_map(routes(4), chunks),
                         "a plain sequence is already the rail")
        self.assertEqual("", render.route_map(routes(1, m1=harness), chunks),
                         "one milestone is not a graph")
        self.assertEqual("", render.route_map(routes(7, m2=harness), chunks),
                         "past the limit the nodes are narrower than their names")
        self.assertIn("<svg", render.route_map(routes(3, m2=harness), chunks))

    def test_a_node_label_never_runs_outside_its_node(self) -> None:
        self.assertEqual(["Wire format survey"], render._map_lines("Wire format survey", 21))
        for line in render._map_lines("Antidisestablishmentarianism recalibration", 21):
            self.assertLessEqual(len(line), 21, line)

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
        # The status vocabulary is defined on the decision page's stylesheet,
        # so the plan cannot even name it; a hyphen never occurs in base64, so
        # these are safe to look for in the source itself.
        for token in ("--ok", "--caution", "--alert", "tag--ok", "data-verdict"):
            self.assertNotIn(token, self.html, token)
        for word in ("Proved", "Verified", "Complete."):
            self.assertNotIn(word, self.page.readable(), word)

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
            'id="decision"', ">Route<", ">Interfaces<", ">Intended proof<",
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
