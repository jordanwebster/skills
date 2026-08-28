"""The operator pages: one stylesheet, one set of primitives, two surfaces.

Autopilot's plan approval page and Handoff's merge decision page are built
from the same eight components so that a reader who has seen one can read
the other. They do not share semantics. The plan page is future tense and
carries no verified state; the decision page is past tense and carries no
process telemetry. Everything derivable from the machine block, the
acceptance contract, or the proof bundle is computed here rather than typed
by an agent, so one fact has one owner.

Every page is a single self-contained HTML file with no script and no
external subresource, so it survives being mailed, printed, and read cold
three weeks later.
"""

from __future__ import annotations

import base64
from datetime import date
import html
import mimetypes
from pathlib import Path
import re
from typing import Any, Sequence

# Media larger than this is linked rather than inlined: the page must stay
# something a browser opens instantly and a mail client accepts.
INLINE_MEDIA_LIMIT = 20 * 1024 * 1024
VIDEO_SUFFIXES = (".webm", ".mp4", ".mov", ".m4v")

# Artifact kinds the plan page states as expectations. A plan promises a
# kind of capture, never a specific byte sequence, so the suffix is enough.
ARTIFACT_KINDS = {
    ".png": "a screenshot", ".jpg": "a screenshot", ".jpeg": "a screenshot",
    ".gif": "a recording", ".webp": "a screenshot",
    ".webm": "a recording", ".mp4": "a recording", ".mov": "a recording", ".m4v": "a recording",
    ".txt": "a transcript", ".log": "a transcript", ".out": "a transcript",
    ".json": "a data capture", ".csv": "a data capture",
    ".md": "a written record", ".html": "a rendered page",
}

# The shared half of the stylesheet: tokens, typography, the two-track grid,
# and every primitive both pages use. Status colour lives in HANDOFF_STYLE
# and route geometry in _STYLE_PLAN, so neither page carries vocabulary that
# would let it be misread as the other.
_STYLE_BASE = """
:root{color-scheme:light dark;
--font-text:"Iowan Old Style","Charter","Source Serif 4","Palatino Linotype",Palatino,Georgia,serif;
--font-ui:"Avenir Next","Segoe UI Variable Text","Noto Sans",system-ui,sans-serif;
--font-mono:"SF Mono","JetBrains Mono","Cascadia Mono",ui-monospace,Menlo,monospace;
--t-micro:.6875rem;--t-meta:.8125rem;--t-dense:.9375rem;--t-body:1.0625rem;
--t-lead:1.25rem;--t-section:1.5rem;--t-title:clamp(1.75rem,1.2rem + 2vw,2.25rem);
--surface:#faf8f4;--surface-raised:#ffffff;--surface-sunken:#f2efe8;
--ink:#1c1b19;--ink-muted:#5f5b54;--ink-faint:#767168;
--rule:#e2ddd3;--rule-strong:#cdc6b8;--accent:#1d5450;
--gutter:clamp(1.5rem,4vw,4rem);--page:min(100% - 2 * var(--gutter),68rem);
--authored:46rem;--derived:13rem;--edge:var(--accent)}
@media (prefers-color-scheme:dark){:root{
--surface:#141513;--surface-raised:#1c1e1c;--surface-sunken:#101110;
--ink:#eceae4;--ink-muted:#a19c92;--ink-faint:#868278;
--rule:#2e302b;--rule-strong:#43463f;--accent:#7fc4b4}}
@media (prefers-contrast:more){:root{--rule:var(--rule-strong);--ink-muted:var(--ink)}}

*,*::before,*::after{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--surface);color:var(--ink);
font:400 var(--t-body)/1.6 var(--font-text);border-top:3px solid var(--edge)}
header.masthead,main{width:var(--page);margin-inline:auto}
header.masthead{padding-top:48px}
main{padding-bottom:96px}

.skip{position:absolute;left:-9999px}
.skip:focus{position:static;display:inline-block;margin:8px 0;padding:8px 12px;
border:1px solid var(--rule-strong);border-radius:6px;background:var(--surface-raised)}
.vh{position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;
clip:rect(0 0 0 0);white-space:nowrap;border:0}

h1{margin:8px 0 8px;font:650 var(--t-title)/1.15 var(--font-text);letter-spacing:-.01em;max-width:34ch}
h2{margin:0 0 16px;font:650 var(--t-section)/1.15 var(--font-text);letter-spacing:-.01em}
h3{margin:0 0 12px;font:650 var(--t-lead)/1.4 var(--font-text)}
h4,h5,h6{margin:16px 0 8px;font:600 var(--t-body)/1.4 var(--font-ui)}
/* The measure is capped in `ch` as well as in rem: the serif that resolves
   on the reader's machine is unknown, and 46rem of a narrow face runs well
   past the 75 characters a person reads comfortably in one pass. */
p{margin:0 0 12px;max-width:min(var(--authored),60ch)}
ul,ol{max-width:min(var(--authored),60ch)}
li{margin:0 0 8px}
strong{font-weight:650}
.eyebrow{margin:0;font:650 var(--t-micro)/1.45 var(--font-ui);letter-spacing:.09em;
text-transform:uppercase;color:var(--ink-muted)}
.meta{margin:0;font:400 var(--t-meta)/1.45 var(--font-ui);color:var(--ink-muted)}
.lab{display:block;font:650 var(--t-micro)/1.45 var(--font-ui);letter-spacing:.09em;
text-transform:uppercase;color:var(--ink-muted)}
.mark{display:inline-flex;align-items:baseline;gap:6px;font:650 var(--t-micro)/1.45 var(--font-ui);
letter-spacing:.09em;text-transform:uppercase;color:var(--ink-muted)}
.mark--fork,.mark--harness{color:var(--accent)}

.block{margin-top:48px}
@media (max-width:899px){.block{margin-top:32px}}
.tracks{display:grid;grid-template-columns:minmax(0,1fr);gap:12px;align-items:start}
@media (min-width:1180px){
.tracks{grid-template-columns:minmax(0,var(--authored)) var(--derived);gap:48px}
/* Stage and claim cards spend part of their width on a label column and, on
   the route, on the rail. Letting them use the full page keeps the measure of
   what a planner actually wrote comparable to ordinary prose. */
.stage.tracks,.claim.tracks{grid-template-columns:minmax(0,1fr) var(--derived)}}
.fields dd,.claim__statement{max-width:min(var(--authored),60ch)}
.margin{font:400 var(--t-meta)/1.45 var(--font-ui);color:var(--ink-muted)}
.margin p{margin:0 0 12px;max-width:60ch}
.margin .lab{margin-bottom:4px}
.margin a{color:inherit}

.decision{margin-top:32px;padding-left:24px;border-left:2px solid var(--edge)}
.decision__lead{font:400 var(--t-lead)/1.4 var(--font-text)}
.decision__lead p{max-width:min(var(--authored),60ch)}
.decision__lead p:last-child{margin-bottom:0}
.decision__cells{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));
margin:16px 0 0;border-top:1px solid var(--rule)}
.decision__cells > div{padding:12px 24px 0 0;border-right:1px solid var(--rule)}
.decision__cells > div:last-child{border-right:0;padding-right:0}
.decision__cells dd{margin:4px 0 0;max-width:60ch}
@media (max-width:639px){.decision{padding-left:16px}
.decision__cells{grid-template-columns:1fr}
.decision__cells > div{padding:12px 0;border-right:0;border-bottom:1px solid var(--rule)}
.decision__cells > div:last-child{border-bottom:0}}

.fields{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:12px 16px;margin:0}
.fields > div{display:contents}
.fields dt{padding-top:3px;font:650 var(--t-micro)/1.45 var(--font-ui);letter-spacing:.09em;
text-transform:uppercase;color:var(--ink-muted)}
.fields dd{margin:0}
@media (max-width:639px){.fields{grid-template-columns:1fr;gap:4px}
.fields dd{margin:0 0 8px}}

/* Shape is dense reference material: terms in mono at their own case, so a
   signature reads as a signature, and definitions on a settled left edge. */
.defs{margin-top:24px}
.defs:first-child{margin-top:0}
.defs h3{margin:0 0 8px}
.defs .fields{grid-template-columns:minmax(0,14rem) minmax(0,1fr);gap:8px 16px}
.defs .fields dt{padding-top:2px;font:600 var(--t-dense)/1.45 var(--font-mono);
letter-spacing:0;text-transform:none;color:var(--ink)}
.defs .fields dd{font-size:var(--t-dense)}
@media (max-width:639px){.defs .fields{grid-template-columns:1fr}}

.claims{list-style:none;margin:0;padding:0;max-width:none}
.claim{margin:0 0 12px}
.claim__card{padding:20px 24px;border:1px solid var(--rule-strong);border-radius:10px;
background:var(--surface-raised)}
.claim__statement{margin:0 0 12px;font:400 var(--t-lead)/1.4 var(--font-text)}
.claim__card > p{max-width:min(var(--authored),60ch)}
.claim__card figure{max-width:var(--authored)}
.claim__mark{margin:0 0 8px}
.claim__evidence{margin-top:12px}
.judgment{margin-top:24px}

.rows{list-style:none;margin:0;padding:0;max-width:none;border-bottom:1px solid var(--rule)}
.row{margin:0;padding:16px 0;border-top:1px solid var(--rule)}
.rows__caption{margin:0 0 4px;font:650 var(--t-micro)/1.45 var(--font-ui);letter-spacing:.09em;
text-transform:uppercase;color:var(--ink-faint)}
.rows--followup{color:var(--ink-faint)}
.closing{margin-top:48px;padding-left:24px;border-left:2px solid var(--edge)}

details{margin:0}
summary{display:flex;align-items:center;gap:8px;min-height:44px;cursor:pointer;list-style:none;
font:600 var(--t-meta)/1.45 var(--font-ui);color:var(--ink-muted)}
summary::-webkit-details-marker{display:none}
summary::before{content:"\\25B8";display:inline-block;transition:transform 150ms ease}
details[open] > summary::before{transform:rotate(90deg)}
.dis__body{padding:12px 16px;border-left:1px solid var(--rule);border-radius:6px;
background:var(--surface-sunken)}
.dis__body > :last-child{margin-bottom:0}
.dis--block{margin-top:-1px;border-top:1px solid var(--rule);border-bottom:1px solid var(--rule)}
.diagnostics{margin-top:48px}

table{width:100%;border-collapse:collapse;margin:8px 0 16px;
font:400 var(--t-dense)/1.45 var(--font-ui)}
caption{padding-bottom:8px;text-align:left;font:650 var(--t-micro)/1.45 var(--font-ui);
letter-spacing:.09em;text-transform:uppercase;color:var(--ink-muted)}
th,td{padding:8px 12px 8px 0;text-align:left;vertical-align:top;border-bottom:1px solid var(--rule)}
th{font-weight:650;color:var(--ink-muted)}
.scroll{overflow-x:auto}

code{font-family:var(--font-mono);font-size:var(--t-dense)}
pre{margin:8px 0;padding:12px;overflow-x:auto;border:1px solid var(--rule);border-radius:6px;
background:var(--surface-sunken);font:400 var(--t-dense)/1.45 var(--font-mono)}
figure{margin:12px 0;max-width:var(--authored)}
img,video{display:block;max-width:100%;height:auto;border:1px solid var(--rule);border-radius:6px}
audio{width:100%}
figcaption{margin-top:4px;max-width:60ch;font:400 var(--t-meta)/1.45 var(--font-ui);color:var(--ink-muted)}
.missing{margin:8px 0;padding-left:12px;border-left:2px solid var(--rule-strong);
font:400 var(--t-meta)/1.45 var(--font-ui)}

a{color:var(--accent);text-decoration:underline;text-underline-offset:.14em;
text-decoration-thickness:1px;transition:text-decoration-thickness 150ms ease}
a:hover{text-decoration-thickness:2px}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}

@media (prefers-reduced-motion:reduce){*,*::before,*::after{
transition:none !important;animation:none !important}}

@page{margin:16mm}
@media print{
/* Paper carries far more detail per inch than a screen, so the whole scale
   steps down: a printed page has to stay something a person picks up and
   reads through, not a stack. */
html{font-size:13px}
:root{--surface:#ffffff;--surface-raised:#ffffff;--surface-sunken:#f4f2ee;
--ink:#111111;--ink-muted:#4a4a4a;--ink-faint:#5c5c5c;
--rule:#cccccc;--rule-strong:#999999;--accent:#12403c}
body{border-top-width:3px}
header.masthead{padding-top:0}
main{padding-bottom:0}
.block,.closing,.diagnostics{margin-top:24px}
.decision{margin-top:16px}
.stage,.claim{margin-bottom:8px}
.margin p{margin-bottom:4px}
.row{padding:8px 0}
.dis--diagnostics{display:none}
.dis--evidence > summary::before{display:none}
.dis--evidence > .dis__body{display:block !important}
.claim,.stage,figure{break-inside:avoid}
h2{break-after:avoid}
a{text-decoration:none}
}
"""

# Route geometry: the rail, its nodes, and the research fork block. Only the
# plan page has a sequence, so only the plan page carries these rules.
_STYLE_PLAN = """
.route{list-style:none;margin:0;padding:0;max-width:none}
.stage{margin:0 0 12px}
.stage__main{position:relative;padding-left:40px}
.stage__main::before{content:"";position:absolute;left:12px;top:0;bottom:-12px;width:1px;
background:var(--rule-strong)}
.stage:last-child .stage__main::before{bottom:auto;height:27px}
.stage[data-enabled="yes"] .stage__main::before{width:2px;left:11px;background:var(--accent)}
.stage__node{position:absolute;left:0;top:14px;display:grid;place-items:center;
width:25px;height:25px;border-radius:50%;background:var(--surface);
font:650 var(--t-micro)/1 var(--font-ui);color:var(--accent)}
.stage__node::before{content:"";position:absolute;inset:0;border:1.5px solid var(--accent);
border-radius:50%}
.stage[data-variant~="research"] .stage__node::before{border-radius:0;transform:rotate(45deg)}
.stage[data-variant~="harness"] .stage__node::before{border-radius:2px}
.stage__card{padding:20px 24px;border:1px solid var(--rule-strong);border-radius:10px;
background:var(--surface-raised)}
.fork{margin-top:12px;padding-top:8px;border-top:1px solid var(--rule)}
.fork__question{margin:0 0 8px}
.fork__outcomes{list-style:none;margin:0;padding:0;max-width:none}
.fork__outcome{display:grid;grid-template-columns:minmax(0,1fr) max-content;gap:16px;
margin:0;padding:8px 0 8px 16px;border-top:1px solid var(--rule)}
.fork__default{font:650 var(--t-micro)/1.45 var(--font-ui);letter-spacing:.09em;
text-transform:uppercase;color:var(--ink-muted);align-self:center}
.fork__note{margin:8px 0 0;font:400 var(--t-meta)/1.45 var(--font-ui);color:var(--ink-muted);
max-width:60ch}
@media (max-width:899px){
.stage__node{display:none}
.stage__main{padding-left:16px}
.stage__main::before{left:0;width:2px}
.stage[data-enabled="yes"] .stage__main::before{left:0}}
@media (max-width:639px){
.stage__main{padding-left:12px}
.stage__card{padding:16px}}
"""

# Coverage and verdict colour. Only the decision page has anything to be
# green, amber, or red about; keeping these here is what makes "nothing on
# the plan page may look verified" a checkable property of the file.
HANDOFF_STYLE = """
:root{--ok:#2a6b4f;--caution:#8a5a12;--alert:#98302c}
@media (prefers-color-scheme:dark){:root{--ok:#6fbe95;--caution:#e0a95f;--alert:#e8867f}}
@media print{:root{--ok:#1d5238;--caution:#6b4409;--alert:#7d2320}}
body[data-verdict="holds"]{--edge:var(--ok)}
body[data-verdict="holds-with-limits"]{--edge:var(--caution)}
body[data-verdict="not-decidable"]{--edge:var(--alert)}
.mark--ok{color:var(--ok)}
.mark--caution{color:var(--caution)}
.mark--alert{color:var(--alert)}
.claim[data-coverage="proved"] .claim__card{border-left:2px solid var(--ok)}
.claim[data-coverage="limited"] .claim__card{border-left:2px solid var(--caution)}
.claim[data-coverage="unproved"] .claim__card{border-left:2px solid var(--alert)}
.claim__gap{margin:0 0 12px}
.claim__gap .lab{margin-bottom:4px}
.verdict__by{font:400 var(--t-meta)/1.45 var(--font-ui);color:var(--ink-muted);max-width:60ch}
.limits{list-style:none;margin:12px 0 0;padding:0;border-bottom:1px solid var(--rule)}
.limits li{margin:0;padding:12px 0;border-top:1px solid var(--rule)}
.missing{color:var(--alert);border-left-color:var(--alert)}
"""


# -- the document shell ----------------------------------------------------------------


def document(
    title: str,
    content: str,
    *,
    surface: str = "",
    meta: str = "",
    style: str = "",
    verdict: str = "",
) -> str:
    """One self-contained page: masthead, main, and exactly one stylesheet."""

    attributes = f' data-verdict="{html.escape(verdict, quote=True)}"' if verdict else ""
    return "".join([
        "<!doctype html>\n",
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n',
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n',
        f"<title>{html.escape(title)}</title>\n",
        f"<style>{_STYLE_BASE}{style}</style>\n</head>\n",
        f"<body{attributes}>\n",
        '<a class="skip" href="#decision">Skip to the decision</a>\n',
        '<header class="masthead">',
        f'<p class="eyebrow">{html.escape(surface)}</p>' if surface else "",
        f"<h1>{html.escape(title)}</h1>",
        f'<p class="meta">{html.escape(meta)}</p>' if meta else "",
        "</header>\n<main>\n",
        content,
        "\n</main>\n</body>\n</html>\n",
    ])


def meta_line(*parts: Any) -> str:
    """The derived masthead line: repository, branch, commit, date."""

    return " · ".join(str(part) for part in parts if part)


def today() -> str:
    stamp = date.today()
    return f"{stamp.day} {stamp:%b %Y}"


# -- primitives ------------------------------------------------------------------------


def decision(
    lead_html: str,
    *,
    ask_label: str,
    ask: str,
    default: str,
    exposure: str,
    variant: str = "approve",
) -> str:
    """The one thing being asked, in decision-row grammar, before anything else."""

    cells = [(ask_label, ask), ("If you do nothing", default), ("Exposure", exposure)]
    body = "".join(
        f'<div><dt class="lab">{html.escape(label)}</dt><dd>{html.escape(value)}</dd></div>'
        for label, value in cells
    )
    return (
        f'<section class="decision decision--{html.escape(variant, quote=True)}" id="decision"'
        ' aria-labelledby="decision-heading">'
        '<h2 class="vh" id="decision-heading">Decision</h2>'
        f'<div class="decision__lead">{lead_html}</div>'
        f'<dl class="decision__cells">{body}</dl>'
        "</section>"
    )


def disclosure(summary: str, body: str, *, variant: str = "inline") -> str:
    """Trusted machinery, reachable and off the surface. Never a decision input."""

    return (
        f'<details class="dis dis--{html.escape(variant, quote=True)}">'
        f"<summary>{html.escape(summary)}</summary>"
        f'<div class="dis__body">{body}</div></details>'
    )


def marker(glyph: str, word: str, *, role: str) -> str:
    """One-word state, carried by glyph and text, never by colour alone."""

    return (
        f'<span class="mark mark--{html.escape(role, quote=True)}">'
        f'<span aria-hidden="true">{html.escape(glyph)}</span> {html.escape(word)}</span>'
    )


def decision_rows(rows: Sequence[dict[str, str]], *, variant: str = "ask", caption: str = "") -> str:
    """The four-part operator grammar wherever a question or a decision appears."""

    if not rows:
        return ""
    items: list[str] = []
    for row in rows:
        derived = [item for item in (row.get("default"), row.get("blast_radius")) if item]
        margin = (
            '<div class="margin"><p>' + html.escape(" · ".join(derived)) + "</p></div>"
            if derived else ""
        )
        items.append(
            '<li class="row tracks"><div>'
            f'{_inline(str(row.get("thing", "")))}</div>{margin}</li>'
        )
    heading = f'<p class="rows__caption">{html.escape(caption)}</p>' if caption else ""
    return (
        heading
        + f'<ul class="rows rows--{html.escape(variant, quote=True)}">' + "".join(items) + "</ul>"
    )


def stage_cards(stages: Sequence[dict[str, Any]]) -> str:
    """The causal sequence and the testing architecture, one card per milestone."""

    items: list[str] = []
    for stage in stages:
        variants = " ".join(stage.get("variants") or ["build"])
        fields = "".join(
            f"<div><dt>{html.escape(label)}</dt><dd>{value}</dd></div>"
            for label, value in stage["fields"]
        )
        margin = "".join(stage.get("margin") or [])
        enabled = ' data-enabled="yes"' if stage.get("enabled") else ""
        items.append(
            f'<li class="stage tracks" id="m{stage["id"]}" data-milestone="{stage["id"]}"'
            f' data-variant="{html.escape(variants, quote=True)}"{enabled}>'
            '<div class="stage__main">'
            f'<span class="stage__node" aria-hidden="true">{stage["id"]}</span>'
            f'<article class="stage__card"><h3>Milestone {stage["id"]} — '
            f'{html.escape(str(stage["title"]))}</h3>'
            f'<dl class="fields">{fields}</dl>{stage.get("fork") or ""}</article></div>'
            f'<div class="margin">{margin}</div></li>'
        )
    return '<ol class="route">' + "".join(items) + "</ol>"


def claim_cards(rows: Sequence[dict[str, Any]]) -> str:
    """A promise joined to the thing that shows it — intended, or proved."""

    items: list[str] = []
    for row in rows:
        card: list[str] = []
        if row.get("mark"):
            card.append(f'<p class="claim__mark">{row["mark"]}</p>')
        card.append(f'<p class="claim__statement">{_inline(str(row["claim"]))}</p>')
        if row.get("gap_html"):
            card.append(row["gap_html"])
        if row.get("fields"):
            card.append(
                '<dl class="fields">'
                + "".join(
                    f"<div><dt>{html.escape(label)}</dt><dd>{value}</dd></div>"
                    for label, value in row["fields"]
                )
                + "</dl>"
            )
        if row.get("evidence_html"):
            card.append(f'<div class="claim__evidence">{row["evidence_html"]}</div>')
        coverage = f' data-coverage="{html.escape(row["coverage"], quote=True)}"' if row.get("coverage") else ""
        margin = "".join(row.get("margin") or [])
        items.append(
            f'<li class="claim tracks"{coverage}>'
            f'<article class="claim__card">{"".join(card)}</article>'
            + (f'<div class="margin">{margin}</div>' if margin else "")
            + "</li>"
        )
    return '<ul class="claims">' + "".join(items) + "</ul>"


def definition_block(groups: Sequence[tuple[str, Sequence[tuple[str, str]]]]) -> str:
    """Shape: components, interfaces, and data shapes, dense enough to smell wrong."""

    parts: list[str] = []
    for name, entries in groups:
        if not entries:
            continue
        body = "".join(
            f"<div><dt>{_inline(term)}</dt><dd>{_inline(definition)}</dd></div>"
            for term, definition in entries
        )
        parts.append(
            f'<div class="defs"><h3 class="lab">{html.escape(name)}</h3>'
            f'<dl class="fields">{body}</dl></div>'
        )
    return "".join(parts)


def verdict_panel(*, summary: str, attribution: str, limitations: Sequence[str]) -> str:
    """The independent reader's judgment, and the boundaries of it."""

    if limitations:
        body = '<ul class="limits">' + "".join(
            "<li>The review did not cover: "
            + html.escape(item if item.rstrip().endswith((".", "!", "?")) else item.rstrip() + ".")
            + "</li>"
            for item in limitations
        ) + "</ul>"
    else:
        body = '<p class="verdict__none">The review reports no limitation.</p>'
    return (
        f'<div class="verdict"><p>{html.escape(summary)}</p>'
        f'<p class="verdict__by">{html.escape(attribution)}</p>{body}</div>'
    )


def section(heading: str, body: str, *, anchor: str, extra: str = "") -> str:
    """A titled region. A region with no body is not rendered at all."""

    if not body.strip():
        return ""
    classes = f"block {extra}".strip()
    return (
        f'<section class="{classes}" aria-labelledby="{anchor}">'
        f'<h2 id="{anchor}">{html.escape(heading)}</h2>{body}</section>'
    )


# -- the plan approval page ------------------------------------------------------------


GATE_STATEMENTS = {
    (False, False): "task completion",
    (True, False): "check",
    (False, True): "task completion + independent review",
    (True, True): "check + independent review",
}


def flight_plan(
    text: str,
    plan: dict[str, Any],
    *,
    title: str,
    base: Path | None = None,
    staffing: list[dict[str, Any]] | None = None,
    acceptance: dict[str, Any] | None = None,
    meta: str = "",
) -> str:
    """Render the typed plan as the operator's approval surface."""

    operator = plan.get("_operator") or {}
    chunks = {chunk["id"]: chunk for chunk in plan.get("chunks", [])}
    tasks_by_chunk: dict[Any, list[dict[str, Any]]] = {}
    for task in plan.get("tasks", []):
        tasks_by_chunk.setdefault(task["chunk"], []).append(task)
    config = plan.get("config", {})
    expected = config.get("expected_iterations", {})
    exposure = (
        f"{expected.get('min')}–{expected.get('max')} expected calls · "
        f"ceiling {config.get('max_iterations')}"
    )

    content = [
        decision(
            markdown(operator.get("goal") or plan.get("goal", ""), base=base, base_level=2),
            ask_label="You approve",
            ask="This route",
            default="Nothing starts",
            exposure=exposure,
            variant="approve",
        )
    ]
    content.append(section("Route", _route(operator, chunks, tasks_by_chunk, base), anchor="route"))
    content.append(section("Shape", _shape(operator.get("shape", ""), base), anchor="shape"))
    content.append(
        section("Intended proof", _intended_proof(plan, operator, acceptance, base), anchor="proof")
    )
    content.append(
        section(
            "What you will be asked",
            decision_rows(_ask_rows(operator.get("asks", "")), variant="ask"),
            anchor="asks",
        )
    )
    content.append(
        section(
            "Open questions",
            decision_rows(_question_rows(operator.get("open_questions", "")), variant="question"),
            anchor="questions",
        )
    )
    content.append(_scope(operator, base))
    for index, (heading, body) in enumerate(operator.get("extras", [])):
        content.append(
            section(
                heading[:1].upper() + heading[1:],
                markdown(body, base=base, base_level=2, caption=heading),
                anchor=f"extra-{index + 1}",
            )
        )
    content.append(_diagnostics(plan, staffing or [], tasks_by_chunk))
    content.append(
        '<section class="closing" aria-labelledby="closing-heading">'
        '<h2 class="vh" id="closing-heading">The ask</h2>'
        + decision_rows(
            [{"thing": "You approve this route.", "default": "Default: nothing starts."}],
            variant="ask",
        )
        + "</section>"
    )
    return document(
        title,
        "\n".join(part for part in content if part),
        surface="Autopilot · plan approval",
        meta=meta,
        style=_STYLE_PLAN,
    )


def _route(
    operator: dict[str, Any],
    chunks: dict[Any, dict[str, Any]],
    tasks_by_chunk: dict[Any, list[dict[str, Any]]],
    base: Path | None,
) -> str:
    routes = operator.get("routes", [])
    enabled_by: dict[int, list[int]] = {}
    for route in routes:
        for target in (route.get("enables") or {}).get("milestones", []):
            enabled_by.setdefault(target, []).append(route["id"])
    spans: set[int] = set()
    for route in routes:
        targets = (route.get("enables") or {}).get("milestones", [])
        if targets:
            for identifier in range(route["id"], max(targets)):
                spans.add(identifier)
    # A milestone named only by a non-default outcome is contingent on how the
    # research turns out; its own card says so, because the task list beneath
    # it assumes the default.
    conditional: dict[int, list[int]] = {}
    for route in routes:
        for outcome in (route.get("branch") or {}).get("outcomes", []):
            if outcome["default"]:
                continue
            for reference in _MILESTONE_REFERENCE.findall(outcome["text"]):
                target = int(reference)
                if target != route["id"] and route["id"] not in conditional.get(target, []):
                    conditional.setdefault(target, []).append(route["id"])

    stages: list[dict[str, Any]] = []
    for index, route in enumerate(routes):
        chunk = chunks[route["id"]]
        variants = ["build"]
        markers: list[str] = []
        if route.get("branch"):
            variants.append("research")
            markers.append(marker("⑂", "Research fork", role="fork"))
        if route.get("enables"):
            variants.append("harness")
            markers.append(marker("⊞", "Enables testing", role="harness"))
        if index == len(routes) - 1:
            variants.append("landing")
        fields = [
            ("Produces", _inline(route["produces"], base)),
            ("Unlocks", _inline(route["unlocks"], base)),
        ]
        if route.get("enables"):
            fields.append(("Enables", _inline(route["enables"]["text"], base)))
        fields.append(("Validated by", _inline(route["validated by"], base)))

        margin: list[str] = []
        if markers:
            margin.append("<p>" + " ".join(markers) + "</p>")
        gate = GATE_STATEMENTS[(bool(chunk.get("check")), chunk.get("review") is not False)]
        margin.append(f'<p><span class="lab">Gate</span>{html.escape(gate)}</p>')
        if chunk.get("check"):
            margin.append(
                disclosure(
                    "Exact gate command",
                    f"<pre>{html.escape(str(chunk['check']))}</pre>",
                    variant="inline dis--diagnostics",
                )
            )
        chunk_tasks = tasks_by_chunk.get(route["id"], [])
        if chunk_tasks:
            listed = "".join(f"<li>{html.escape(str(item['title']))}</li>" for item in chunk_tasks)
            margin.append(
                disclosure(
                    f"{len(chunk_tasks)} {'task' if len(chunk_tasks) == 1 else 'tasks'}",
                    f"<ul>{listed}</ul>",
                    variant="inline dis--diagnostics",
                )
            )
        for source in sorted(enabled_by.get(route["id"], [])):
            margin.append(
                f'<p>Testable because of <a href="#m{source}">Milestone {source}</a>.</p>'
            )
        for source in sorted(conditional.get(route["id"], [])):
            margin.append(
                f'<p>Conditional on <a href="#m{source}">Milestone {source}</a>.</p>'
            )

        stages.append({
            "id": route["id"],
            "title": chunk["title"],
            "variants": variants,
            "fields": fields,
            "fork": _fork(route.get("branch")),
            "margin": margin,
            "enabled": route["id"] in spans,
        })
    return stage_cards(stages)


def _fork(branch: dict[str, Any] | None) -> str:
    if not branch:
        return ""
    outcomes: list[str] = []
    for outcome in branch["outcomes"]:
        label = (
            '<span class="fork__default">default</span>' if outcome["default"]
            else '<span class="fork__default"></span>'
        )
        outcomes.append(
            f'<li class="fork__outcome"><span>{_inline(outcome["text"])}</span>{label}</li>'
        )
    return (
        '<div class="fork">'
        f'<p class="fork__question">{_inline(branch["question"])}</p>'
        f'<ul class="fork__outcomes">{"".join(outcomes)}</ul>'
        '<p class="fork__note">The task list below assumes the default; another outcome '
        "revises the plan before work continues.</p></div>"
    )


def _shape(source: str, base: Path | None) -> str:
    """Shape as definition lists, falling back to plain Markdown when untyped."""

    groups = _shape_groups(source)
    if groups:
        return definition_block(groups)
    return markdown(source, base=base, base_level=2, caption="Shape")


_SHAPE_GROUP = re.compile(r"^#{3,6}\s+(.+?)\s*$", re.MULTILINE)
_SHAPE_ENTRY = re.compile(r"^\s*[-*]\s+(.*)$")
_SHAPE_SPLIT = re.compile(r"\s+(?:—|–|--)\s+")


def _shape_groups(source: str) -> list[tuple[str, list[tuple[str, str]]]]:
    matches = list(_SHAPE_GROUP.finditer(source))
    if not matches:
        return []
    groups: list[tuple[str, list[tuple[str, str]]]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(source)
        entries: list[tuple[str, str]] = []
        for line in source[match.end():end].splitlines():
            entry = _SHAPE_ENTRY.match(line)
            if not entry:
                continue
            parts = _SHAPE_SPLIT.split(entry.group(1), maxsplit=1)
            if len(parts) == 2:
                entries.append((parts[0].strip(), parts[1].strip()))
            else:
                entries.append((entry.group(1).strip(), ""))
        if entries:
            groups.append((match.group(1).strip(), entries))
    return groups


def _intended_proof(
    plan: dict[str, Any],
    operator: dict[str, Any],
    acceptance: dict[str, Any] | None,
    base: Path | None,
) -> str:
    descriptions: dict[str, str] = {}
    try:
        for item in acceptance["acceptance"]["demonstrations"] if acceptance else []:
            descriptions[str(item["id"])] = str(item["description"])
    except (KeyError, TypeError):
        descriptions = {}
    chunks = {chunk["id"]: chunk["title"] for chunk in plan.get("chunks", [])}
    rows: list[dict[str, Any]] = []
    for item in plan.get("evidence", []):
        kinds: list[str] = []
        for artifact in item.get("artifacts", []):
            kind = ARTIFACT_KINDS.get(Path(str(artifact)).suffix.lower(), "a capture")
            if kind not in kinds:
                kinds.append(kind)
        margin: list[str] = []
        shown = [
            descriptions[str(value)]
            for value in item.get("demonstrations", [])
            if str(value) in descriptions
        ]
        if shown:
            margin.append(
                '<p><span class="lab">Will show</span>'
                + "; ".join(f"“{html.escape(value)}”" for value in shown)
                + "</p>"
            )
        stages = [
            f'<a href="#m{stage}">Milestone {stage}</a>'
            for stage in item.get("stages", [])
            if stage in chunks
        ]
        if stages:
            margin.append(
                '<p><span class="lab">Delivered by</span>' + ", ".join(stages) + "</p>"
            )
        replay = _replay_summary(item.get("replay", {}))
        if replay:
            margin.append(disclosure("Replay", f"<pre>{html.escape(replay)}</pre>"))
        rows.append({
            "claim": item["claim"],
            "fields": [("Expected", html.escape(_join(kinds)))] if kinds else [],
            "margin": margin,
        })
    body = claim_cards(rows) if rows else ""
    if operator.get("human_judgment"):
        body += (
            '<div class="judgment"><p class="lab">Judged by a person</p>'
            + markdown(operator["human_judgment"], base=base, base_level=2, caption="Judged by a person")
            + "</div>"
        )
    return body


def _scope(operator: dict[str, Any], base: Path | None) -> str:
    parts: list[str] = []
    if operator.get("out_of_scope"):
        parts.append("<h3>Out of scope</h3>")
        parts.append(markdown(operator["out_of_scope"], base=base, base_level=3, caption="Out of scope"))
    if operator.get("rejected_alternatives"):
        parts.append("<h3>Rejected alternatives</h3>")
        parts.append(
            markdown(operator["rejected_alternatives"], base=base, base_level=3, caption="Rejected alternatives")
        )
    if not parts:
        return ""
    return (
        '<div class="block">'
        + disclosure("Scope and rejected alternatives", "".join(parts), variant="block")
        + "</div>"
    )


def _ask_rows(source: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for record in _table_records(source):
        derived = [record.get("When"), record.get("Default"), record.get("Exposure")]
        rows.append({
            "thing": record.get("Act", ""),
            "default": " · ".join(item for item in derived if item),
        })
    return rows


def _question_rows(source: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for record in _table_records(source):
        values = list(record.values())
        rows.append({
            "thing": values[0] if values else "",
            "default": " · ".join(item for item in values[1:] if item),
        })
    return rows


def _diagnostics(
    plan: dict[str, Any],
    staffing: list[dict[str, Any]],
    tasks_by_chunk: dict[Any, list[dict[str, Any]]],
) -> str:
    config = plan.get("config", {})
    chunks = plan.get("chunks", [])
    parts: list[str] = []

    if staffing:
        rows = []
        for binding in staffing:
            mind = binding.get("mind") if isinstance(binding.get("mind"), dict) else {}
            constraints = binding.get("constraints") if isinstance(binding.get("constraints"), dict) else {}
            preferred = binding.get("preferred") if isinstance(binding.get("preferred"), dict) else {}
            material = {**constraints, **preferred}
            family = str(mind.get("family") or "")
            model = str(mind.get("model") or "")
            rows.append(
                f"<tr><td>{html.escape(str(binding.get('role') or ''))}</td>"
                f"<td>{html.escape(f'{family}/{model}' if family else model)}</td>"
                f"<td>{html.escape(str(mind.get('effort') or 'default'))}</td>"
                f"<td>{html.escape(', '.join(f'{key}={value}' for key, value in sorted(material.items())) or 'none')}</td></tr>"
            )
        table = (
            '<div class="scroll"><table><caption>Resolved staffing</caption>'
            '<tr><th scope="col">Role</th><th scope="col">Model</th>'
            '<th scope="col">Effort</th><th scope="col">Material constraints</th></tr>'
            + "".join(rows) + "</table></div>"
        )
        parts.append(
            disclosure(
                f"Staffing ({len(staffing)} {'role' if len(staffing) == 1 else 'roles'})",
                table,
                variant="block dis--diagnostics",
            )
        )

    tables: list[str] = []
    total = sum(len(items) for items in tasks_by_chunk.values())
    for chunk in chunks:
        items = tasks_by_chunk.get(chunk["id"], [])
        if not items:
            continue
        rows = []
        for task in items:
            after = ", ".join(str(item) for item in task.get("depends_on", []))
            check = str(task.get("check") or "")
            rows.append(
                f"<tr><td>{task['id']}</td><td>{html.escape(str(task['title']))}</td>"
                f"<td>{html.escape(str(task.get('done_when', '')))}</td>"
                f"<td>{f'<code>{html.escape(check)}</code>' if check else ''}</td>"
                f"<td>{html.escape(after)}</td>"
                f"<td>{html.escape(str(task.get('role') or chunk.get('role') or 'implementer'))}</td></tr>"
            )
        tables.append(
            '<div class="scroll"><table><caption>Milestone '
            f"{chunk['id']} — {html.escape(str(chunk['title']))}</caption>"
            '<tr><th scope="col">#</th><th scope="col">Task</th><th scope="col">Done when</th>'
            '<th scope="col">Check</th><th scope="col">After</th><th scope="col">Role</th></tr>'
            + "".join(rows) + "</table></div>"
        )
    if tables:
        parts.append(
            disclosure(
                f"Tasks by milestone ({total} {'task' if total == 1 else 'tasks'})",
                "".join(tables),
                variant="block dis--diagnostics",
            )
        )

    expected = config.get("expected_iterations", {})
    bounds = [
        f"<li>Expected {expected.get('min')}–{expected.get('max')} calls, "
        f"hard ceiling {config.get('max_iterations')}.</li>",
        f"<li>Retry cap {config.get('retry_cap', 3)}; "
        f"{config.get('iteration_timeout', 3600)}s per call.</li>",
    ]
    if config.get("check"):
        bounds.append(
            f"<li>Whole-flight check <code>{html.escape(str(config['check']))}</code>.</li>"
        )
    for item in config.get("preflight", []):
        bounds.append(f"<li>Preflight <code>{html.escape(str(item))}</code>.</li>")
    parts.append(
        disclosure("Bounds and preflight", "<ul>" + "".join(bounds) + "</ul>", variant="block dis--diagnostics")
    )
    return '<div class="diagnostics">' + "".join(parts) + "</div>"


def _replay_summary(replay: dict[str, Any]) -> str:
    if replay.get("kind") == "command":
        return str(replay.get("command") or "")
    if replay.get("kind") == "steps":
        return " → ".join(str(item) for item in replay.get("steps", []))
    if replay.get("kind") == "not_replayable":
        return f"Not replayable — {replay.get('accepted_reason') or ''}".strip()
    return ""


def _join(values: Sequence[str]) -> str:
    items = list(values)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _table_records(source: str) -> list[dict[str, str]]:
    lines = [line.strip() for line in source.splitlines() if line.strip().startswith("|")]
    if len(lines) < 3:
        return []
    rows = [[cell.strip() for cell in line.strip("|").split("|")] for line in lines]
    headers = rows[0]
    return [dict(zip(headers, row)) for row in rows[2:] if len(row) == len(headers)]


# -- generic pages ---------------------------------------------------------------------


def page(title: str, body_markdown: str, *, base: Path | None = None) -> str:
    """One styled page for ordinary agent-written Markdown."""

    content = (
        markdown(body_markdown, base=base, base_level=1, caption=title)
        if body_markdown.strip()
        else "<p>No front page was written.</p>"
    )
    return document(title, content)


def split_title(text: str, *, default: str) -> tuple[str, str]:
    """Take the first `# ` heading as the page title; the rest is the body."""

    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("# "):
            return line[2:].strip(), "\n".join(lines[:index] + lines[index + 1:])
    return default, text


def duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}m"


# -- markdown --------------------------------------------------------------------------


_HEADING = re.compile(r"^(#{1,6})\s+(.*)")


def markdown(
    text: str,
    *,
    base: Path | None = None,
    base_level: int = 2,
    caption: str = "",
) -> str:
    """Enough Markdown for agent-written prose: headings, lists, tables, code,
    links, and media. Authored headings are demoted relative to the component
    that contains them — `base_level` — rather than shifted globally, so the
    document outline stays correct wherever the prose is embedded."""

    levels = [len(match.group(1)) for match in (_HEADING.match(line) for line in text.splitlines()) if match]
    shallowest = min(levels) if levels else 1

    out: list[str] = []
    paragraph: list[str] = []
    list_tag: str | None = None
    table: list[str] | None = None
    in_code = False
    last_heading = caption

    def flush() -> None:
        nonlocal paragraph, list_tag, table
        if paragraph:
            out.append("<p>" + _inline(" ".join(paragraph), base) + "</p>")
            paragraph = []
        if list_tag:
            out.append(f"</{list_tag}>")
            list_tag = None
        if table is not None:
            out.append("\n".join(table) + "</table></div>")
            table = None

    for line in text.splitlines():
        if line.startswith("```"):
            if in_code:
                out.append("</pre>")
                in_code = False
            else:
                flush()
                out.append("<pre>")
                in_code = True
            continue
        if in_code:
            out.append(html.escape(line))
            continue
        if line.strip().startswith("<!--") and line.strip().endswith("-->"):
            flush()
            continue
        heading = _HEADING.match(line)
        if heading:
            flush()
            level = min(base_level + (len(heading.group(1)) - shallowest) + 1, 6)
            last_heading = re.sub(r"[*`]", "", heading.group(2)).strip()
            out.append(f"<h{level}>{_inline(heading.group(2), base)}</h{level}>")
            continue
        media = re.match(r"^\s*!\[([^\]]*)\]\(([^)\s]+)\)\s*$", line)
        if media:
            flush()
            out.append(_media(media.group(1), media.group(2), base))
            continue
        if line.strip().startswith("|") and line.strip().endswith("|"):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
                continue
            if table is None:
                if paragraph or list_tag:
                    flush()
                label = last_heading or caption or "Table"
                table = ['<div class="scroll"><table>', f"<caption>{html.escape(label)}</caption>"]
                table.append(
                    "<tr>" + "".join(f'<th scope="col">{_inline(cell, base)}</th>' for cell in cells) + "</tr>"
                )
            else:
                table.append("<tr>" + "".join(f"<td>{_inline(cell, base)}</td>" for cell in cells) + "</tr>")
            continue
        if table is not None:
            flush()
        item = re.match(r"^\s*(?:[-*]|\d+[.)])\s+(.*)", line)
        if item:
            if paragraph:
                flush()
            wanted = "ol" if re.match(r"^\s*\d", line) else "ul"
            if list_tag != wanted:
                if list_tag:
                    out.append(f"</{list_tag}>")
                out.append(f"<{wanted}>")
                list_tag = wanted
            out.append(f"<li>{_inline(item.group(1), base)}</li>")
            continue
        if not line.strip():
            flush()
            continue
        if list_tag:
            out.append(f"</{list_tag}>")
            list_tag = None
        paragraph.append(line.strip())
    if in_code:
        out.append("</pre>")
    flush()
    return "\n".join(out)


_MILESTONE_REFERENCE = re.compile(r"\bM(\d+)\b")


def _inline(text: str, base: Path | None = None) -> str:
    escaped = html.escape(text, quote=False)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(
        r"!\[([^\]]*)\]\(([^)\s]+)\)",
        lambda match: _media(match.group(1), match.group(2), base),
        escaped,
    )
    escaped = re.sub(
        r"\[([^\]]+)\]\(([^)\s]+)\)",
        lambda match: f"<a href='{html.escape(match.group(2), quote=True)}'>{match.group(1)}</a>",
        escaped,
    )
    return _MILESTONE_REFERENCE.sub(
        lambda match: f'<a href="#m{match.group(1)}">M{match.group(1)}</a>', escaped
    )


def _media(alt: str, target: str, base: Path | None) -> str:
    """An image or video, inlined as a data URI so the page ships alone."""

    caption = f"<figcaption>{html.escape(alt)}</figcaption>" if alt else ""
    path = Path(target)
    if not path.is_absolute() and base is not None:
        path = base / path
    if target.startswith(("http://", "https://")):
        return (
            f'<p class="missing">Remote media is not embedded: '
            f"<code>{html.escape(target)}</code></p>"
        )
    if target.startswith("data:"):
        return f"<figure><img src='{html.escape(target, quote=True)}' alt='{html.escape(alt, quote=True)}'>{caption}</figure>"
    if not path.is_file():
        return f'<p class="missing">Missing media: <code>{html.escape(target)}</code></p>'
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if path.stat().st_size > INLINE_MEDIA_LIMIT:
        return (
            f'<p class="missing">{html.escape(alt or path.name)} is '
            f"{path.stat().st_size // (1024 * 1024)} MB and was not inlined.</p>"
        )
    source = f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")
    if path.suffix.lower() in VIDEO_SUFFIXES:
        return f"<figure><video controls src='{source}'></video>{caption}</figure>"
    return f"<figure><img src='{source}' alt='{html.escape(alt, quote=True)}'>{caption}</figure>"
