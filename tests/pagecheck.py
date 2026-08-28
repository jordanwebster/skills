"""Structural checks shared by the two operator page tests.

The pages are read by a person under time pressure, so these helpers assert
what a person would notice — one first-level heading, no skipped levels,
nothing fetched from the network, machinery kept behind disclosures — rather
than the exact bytes of any component. Anything checked here is a promise the
pages make; wording and styling are free to change beneath it.
"""

from __future__ import annotations

from html.parser import HTMLParser

VOID_TAGS = {"meta", "link", "img", "br", "hr", "input", "source", "area", "col"}


class Page(HTMLParser):
    """A parsed operator page, queried by structure rather than by string."""

    def __init__(self, source: str):
        super().__init__(convert_charrefs=True)
        self.source = source
        self.elements: list[tuple[str, dict[str, str]]] = []
        self.headings: list[tuple[int, str]] = []
        self.styles = 0
        self.scripts = 0
        self.title = ""
        self.style_text: list[str] = []
        self.text: list[str] = []
        self.open_text: list[str] = []
        self.sections: list[tuple[str, list[str]]] = []
        self._details = 0
        self._heading: list[str] | None = None
        self._level = 0
        self._in_style = False
        self._in_title = False
        self._section: list[str] | None = None
        self._section_depth = 0
        self._depth = 0
        self.feed(source)

    # -- parsing ---------------------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name: (value or "") for name, value in attrs}
        self.elements.append((tag, values))
        if tag not in VOID_TAGS:
            self._depth += 1
        if tag == "style":
            self.styles += 1
            self._in_style = True
        elif tag == "script":
            self.scripts += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "details":
            self._details += 1
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._heading = []
            self._level = int(tag[1])
        elif tag == "section" and self._section is None:
            self._section = []
            self._section_depth = self._depth

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag not in VOID_TAGS:
            self._depth -= 1
        if tag == "style":
            self._in_style = False
        elif tag == "title":
            self._in_title = False
        elif tag == "details":
            self._details -= 1
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6") and self._heading is not None:
            self.headings.append((self._level, "".join(self._heading).strip()))
            self._heading = None
        elif tag == "section" and self._section is not None and self._depth < self._section_depth:
            label = self.headings[-1][1] if self.headings else ""
            self.sections.append((label, self._section))
            self._section = None

    def handle_data(self, data: str) -> None:
        if self._in_style:
            self.style_text.append(data)
            return
        if self._in_title:
            self.title += data
            return
        self.text.append(data)
        if not self._details:
            self.open_text.append(data)
        if self._heading is not None:
            self._heading.append(data)
        if self._section is not None:
            self._section.append(data)

    # -- queries ---------------------------------------------------------------

    def all_text(self) -> str:
        return " ".join(self.text)

    def outside_details(self) -> str:
        return " ".join(self.open_text)

    def stylesheet(self) -> str:
        return "".join(self.style_text)

    def tags(self, name: str) -> list[dict[str, str]]:
        return [values for tag, values in self.elements if tag == name]

    def with_class(self, name: str) -> list[dict[str, str]]:
        return [
            values for _, values in self.elements
            if name in values.get("class", "").split()
        ]

    def anchors(self) -> set[str]:
        return {values["id"] for _, values in self.elements if values.get("id")}

    def hrefs(self) -> list[str]:
        return [values["href"] for _, values in self.elements if values.get("href")]

    def sources(self) -> list[str]:
        return [values["src"] for _, values in self.elements if values.get("src")]

    def order_of(self, *labels: str) -> list[int]:
        return [self.source.index(label) for label in labels]


def assert_operator_page(case, source: str) -> Page:
    """The invariants both pages hold, whatever they are about."""

    page = Page(source)
    levels = [level for level, _ in page.headings]
    case.assertEqual(1, levels.count(1), "a page has exactly one first-level heading")
    case.assertEqual(page.title.strip(), page.headings[0][1], "the tab title is the heading")
    for previous, current in zip(levels, levels[1:]):
        case.assertLessEqual(current, previous + 1, f"heading level {current} skips after {previous}")

    case.assertEqual(0, page.scripts, "operator pages carry no script")
    case.assertEqual(1, page.styles, "operator pages carry exactly one stylesheet")
    case.assertNotIn("style=", source, "no element carries an inline style")

    for reference in page.sources():
        case.assertFalse(
            reference.startswith(("http://", "https://")),
            f"subresource {reference[:40]} would be fetched from the network",
        )
    for tag in ("link",):
        case.assertEqual([], page.tags(tag), f"a <{tag}> would fetch a subresource")

    case.assertIn('<html lang="en">', source)
    case.assertIn('name="viewport"', source)
    case.assertIn("@media print", page.stylesheet())
    case.assertIn(":focus-visible", page.stylesheet())
    reduced = page.stylesheet()
    case.assertIn("prefers-reduced-motion", reduced)
    # The caret rotation lives on a pseudo-element, which a bare `*` rule does
    # not reach, so the suppression has to name them.
    case.assertRegex(
        reduced.replace("\n", " "),
        r"prefers-reduced-motion:reduce\)\{\*,\*::before,\*::after",
    )

    case.assertEqual(1, len(page.with_class("decision")), "exactly one decision component")
    for label, body in page.sections:
        case.assertTrue("".join(body).strip(), f"section {label!r} rendered an empty body")

    tables = [tag for tag, _ in page.elements if tag == "table"]
    case.assertEqual(len(tables), source.count("<caption>"), "every table is captioned")
    if tables:
        case.assertEqual(
            source.count("<th"), source.count('<th scope="col"'), "every header cell has a scope"
        )
    return page
