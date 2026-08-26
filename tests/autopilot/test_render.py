from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from autopilot import render
from autopilot.state import Flight


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
        self.assertIn("<tr><th>Claim</th><th>Evidence</th></tr>", html)
        self.assertIn("<td>Login works</td><td><code>tests/login.sh</code></td>", html)
        self.assertIn("<ol>\n<li>first</li>\n<li>second</li>\n</ol>", html)
        self.assertIn("<a href='https://example.test/x'>link</a>", html)
        self.assertIn("<strong>bold</strong> and <code>code</code>", html)
        self.assertIn("<pre>\nraw &lt;text&gt;\n</pre>", html)

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

    def test_oversized_media_is_linked_not_inlined(self) -> None:
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


class PlanPageTests(unittest.TestCase):
    def test_plan_block_becomes_tables(self) -> None:
        plan = {
            "goal": "Build it",
            "config": {"max_iterations": 9, "check": "make test", "preflight": ["npx playwright --version"]},
            "chunks": [{"id": 1, "title": "Core", "role": "implementer", "check": "make unit"}],
            "tasks": [{"id": 1, "chunk": 1, "title": "Add the thing", "done_when": "it exists", "role": "ui-developer"}],
        }
        text = "## Goal\n\nBuild it.\n\n## Chunks and tasks\n\n```flight-plan\n{\"ignored\": true}\n```\n\n## Out of scope\n\n- nothing\n"
        html = render.flight_plan(text, plan, title="Flight plan: Build it")
        self.assertIn("<h3>Goal</h3>", html)
        self.assertIn("<h3>Chunk 1 — Core</h3>", html)
        self.assertIn("<td>Add the thing</td>", html)
        self.assertIn("<td>ui-developer</td>", html)
        self.assertIn("Ceiling 9 iterations", html)
        self.assertIn("npx playwright --version", html)
        self.assertNotIn("ignored", html)
        self.assertLess(html.index("Chunk 1"), html.index("Out of scope"), "tables render where the block was")


class WrapUpTests(unittest.TestCase):
    def test_wrap_up_inlines_evidence_and_dispatches(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            flight = Flight(temporary).create("Ship the widget", "autopilot/widget", "0" * 40)
            flight.add_chunk("Core")
            flight.add_task("Do it", chunk=1)
            flight.record_dispatch("implementer", "claude/opus/high", 61, "ok")
            flight.record_dispatch("implementer", "claude/opus/high", 30, "error")
            flight.record_dispatch("reviewer", "codex/gpt/high", 10, "ok")
            (flight.dir / "evidence").mkdir()
            (flight.dir / "evidence" / "widget.png").write_bytes(PNG)
            (flight.dir / "acceptance.md").write_text(
                "Verdict: accept\n\n## PROOF\n\n![Widget on screen](evidence/widget.png)\n"
            )
            html = render.wrap_up(flight)
            self.assertIn("<title>Ship the widget</title>", html)
            self.assertIn("data:image/png;base64", html)
            self.assertIn("<td>implementer</td><td><code>claude/opus/high</code></td><td>2</td><td>1m31s</td><td>1</td>", html)
            self.assertIn("<td>reviewer</td>", html)
            summary = flight.dispatch_summary()
            self.assertEqual([row["count"] for row in summary], [2, 1])


if __name__ == "__main__":
    unittest.main()
