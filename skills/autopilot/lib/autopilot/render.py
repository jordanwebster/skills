"""The operator pages: one stylesheet, one set of primitives, two surfaces.

Autopilot's plan approval page and Handoff's merge decision page are built
from the same components so that a reader who has seen one can read the
other. They do not share semantics. The plan page is future tense and
carries no verified state; the decision page is past tense and carries no
process telemetry. Everything derivable from the machine block, the
acceptance contract, or the proof bundle is computed here rather than typed
by an agent, so one fact has one owner.

Three things follow from that split and shape every page below.

The reader meets a finding before any detail. The masthead names the kind of
page, the work, and — in the standfirst — the single sentence that has to
land before the rest can mean anything: the objective on a plan, the verdict
on a decision. Both are derived, so no agent writes the title twice.

A section states its fixed name and what it turned out to hold. The name is
what makes the two pages comparable; the headline beside it is counted from
the same material the section renders, so the two cannot disagree, and a
section with nothing derivable to say shows its name alone.

There is one measure and one escape from it. Prose, cards, and rows sit in
`--text`; a derived table or a drawing takes the bleed on each side. Nothing
holds a standing column for material that is usually absent — a card's
qualifiers read with the thing they qualify, so a card with little to say
costs little space.

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

from .fonts import FONT_FACES
from .plan import shape_groups

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

# The shared half of the stylesheet: the faces, the tokens, the measure, and
# every primitive both pages use. Status colour lives in HANDOFF_STYLE and
# route geometry in _STYLE_PLAN, so neither page carries vocabulary that would
# let it be misread as the other.
#
# One measure, one escape. Prose, cards, and rows sit in `--text`; a derived
# table or a drawing takes `--bleed` more on each side. The bleed is a fixed
# length rather than a viewport calculation, and one query switches it off
# below the width that can afford it, so nothing here can push the body
# sideways on a narrow screen or on paper.
#
# Colour is spent, not spread. The accent carries structure — eyebrows, links,
# the route map — and the status hues appear only on the chip that states a
# state and the rule down the side of the decision. A page where everything
# holds is close to monochrome, which is what makes the one page that does not
# hold visible from across a desk.
_STYLE_BASE = FONT_FACES + """
:root{color-scheme:light dark;
--font-display:Newsreader,Georgia,"Times New Roman",serif;
--font-ui:"IBM Plex Sans",ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
--font-mono:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace;

--t-micro:.6875rem;--t-label:.72rem;--t-meta:.82rem;--t-dense:.9rem;
--t-lead:1.14rem;--t-stand:1.28rem;--t-section:1.85rem;
--t-title:clamp(2.4rem,1.6rem + 3.4vw,3.5rem);--t-metric:1.55rem;

--paper:#f7f6f3;--paper-sunk:#efede8;--card:#ffffff;
--rule:#dcd9d1;--rule-strong:#c3bfb4;--ink-hint:#8b9099;
--ink:#1a1c20;--ink-soft:#4b4f57;--ink-faint:#666b74;
--accent:#1f5f73;--accent-soft:#e3eef1;
--good:#3b6b45;--good-soft:#e8f1e9;
--warn:#a2571b;--warn-soft:#f8f1e0;
--crit:#9e2f2f;--crit-soft:#f9eaea;
--shadow:0 1px 2px rgba(26,28,32,.06),0 6px 20px rgba(26,28,32,.05);

--gutter:clamp(1.25rem,4vw,3rem);--text:44rem;--bleed:8rem;
--edge:var(--accent);--edge-soft:var(--accent-soft)}

@media (prefers-color-scheme:dark){:root{
--paper:#16181c;--paper-sunk:#1c1f24;--card:#1e2126;
--rule:#33383f;--rule-strong:#474d56;--ink-hint:#767c85;
--ink:#e8e7e3;--ink-soft:#afb4bc;--ink-faint:#9c9fa2;
--accent:#6fb6c9;--accent-soft:#1f3a42;
--good:#82be90;--good-soft:#18291d;
--warn:#dfa469;--warn-soft:#241c0f;
--crit:#e08585;--crit-soft:#241414;
--shadow:0 1px 2px rgba(0,0,0,.3),0 6px 20px rgba(0,0,0,.25)}}
@media (prefers-contrast:more){:root{--rule:var(--rule-strong);--ink-faint:var(--ink-soft)}}

*,*::before,*::after{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--paper);color:var(--ink);
font:400 16.5px/1.62 var(--font-ui);-webkit-font-smoothing:antialiased;
border-top:3px solid var(--edge)}
header.masthead,main{width:min(100% - 2 * var(--gutter),var(--text));margin-inline:auto}
header.masthead{padding-top:4.5rem}
main{padding-bottom:6rem}

/* Two escapes, because they are read differently. A figure is a self-contained
   object and centres in the bleed; a table or a definition list is still read
   as text, so it keeps the page's left edge and grows to the right — a
   left-aligned block hanging out past its own heading reads as a mistake. */
.wide{margin-inline:calc(-1 * var(--bleed));width:calc(100% + 2 * var(--bleed))}
.widen,.metrics,.decision{width:calc(100% + var(--bleed))}
@media (max-width:66rem){
.wide{margin-inline:0;width:100%}
.widen,.metrics,.decision{width:100%}}

.skip{position:absolute;left:-9999px}
.skip:focus{position:static;display:inline-block;margin:8px 0;padding:8px 12px;
border:1px solid var(--rule-strong);border-radius:6px;background:var(--card)}
.vh{position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;
clip:rect(0 0 0 0);white-space:nowrap;border:0}

/* The title is the reader's entry, so it is sized as one: the standfirst below
   states the claim the page is about, and the derived provenance line sits
   under a rule where it can be found without competing with either. */
h1{margin:1.1rem 0 0;font:600 var(--t-title)/1.05 var(--font-display);
letter-spacing:-.02em;text-wrap:balance}
.standfirst{margin:1.15rem 0 0;max-width:34rem;
font:400 var(--t-stand)/1.5 var(--font-display);color:var(--ink-soft);text-wrap:pretty}
h2{margin:0 0 .5rem;font:600 var(--t-section)/1.15 var(--font-display);
letter-spacing:-.012em;text-wrap:balance}
h3{margin:0 0 .6rem;font:600 1.02rem/1.4 var(--font-ui);letter-spacing:.005em}
h4,h5,h6{margin:1rem 0 .4rem;font:600 1rem/1.4 var(--font-ui)}
p{margin:0 0 1.05rem;max-width:min(var(--text),68ch)}
ul,ol{margin:0 0 1.05rem;padding-left:1.15rem;max-width:min(var(--text),68ch)}
li{margin:0 0 .42rem}
li::marker{color:var(--ink-hint)}
strong{font-weight:600}

.eyebrow{margin:0;font:500 var(--t-label)/1.45 var(--font-mono);letter-spacing:.14em;
text-transform:uppercase;color:var(--accent)}
/* A section's fixed name and its derived headline, in one heading: the name is
   what makes the two pages comparable, the headline is what makes this one
   worth reading. */
.kicker{display:block;margin-bottom:.55rem;font:500 var(--t-label)/1.4 var(--font-mono);
letter-spacing:.1em;text-transform:uppercase;color:var(--accent)}
.meta{margin:1.8rem 0 0;padding-top:.8rem;border-top:1px solid var(--rule);
font:400 var(--t-meta)/1.45 var(--font-mono);color:var(--ink-faint)}
.lab{display:block;font:500 var(--t-micro)/1.45 var(--font-mono);letter-spacing:.1em;
text-transform:uppercase;color:var(--ink-faint)}

/* One chip vocabulary for every state either page names. Colour rides on the
   border and the text, never a fill, so a row of them stays quiet. */
.tag{display:inline-block;padding:.16em .5em;border:1px solid currentColor;border-radius:3px;
font:500 var(--t-micro)/1.5 var(--font-mono);letter-spacing:.06em;
text-transform:uppercase;white-space:nowrap;color:var(--ink-faint)}
.tag--fork,.tag--harness,.tag--accent{color:var(--accent)}

/* The numbers a reader wants before any prose: derived, tabular, and stated
   once at the top so nothing below has to repeat them. */
.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(8rem,1fr));
margin:2.4rem 0 0;border:1px solid var(--rule);border-radius:8px;
background:var(--card);box-shadow:var(--shadow);overflow:hidden}
.metrics > div{padding:.85rem 1.1rem 1rem;border-right:1px solid var(--rule)}
.metrics > div:last-child{border-right:0}
.metrics dt{display:flex;align-items:flex-start;min-height:2.8em;margin:0 0 .3rem;
font:500 var(--t-micro)/1.4 var(--font-mono);letter-spacing:.11em;
text-transform:uppercase;color:var(--ink-faint)}
.metrics dd{margin:0;font:400 var(--t-metric)/1.1 var(--font-mono);
letter-spacing:-.01em;font-variant-numeric:tabular-nums}
.metrics dd span{margin-left:.3em;font:400 var(--t-meta)/1 var(--font-ui);color:var(--ink-faint)}
.metrics [data-tone="ok"]{color:var(--good)}
.metrics [data-tone="caution"]{color:var(--warn)}
.metrics [data-tone="alert"]{color:var(--crit)}
@media (max-width:639px){.metrics > div{border-right:0;border-bottom:1px solid var(--rule)}
.metrics > div:last-child{border-bottom:0}}

.block{margin-top:4rem}
@media (max-width:899px){.block{margin-top:3rem}}
.fields dd,.claim__statement{max-width:min(var(--text),68ch)}

/* A card's derived qualifiers read with the thing they qualify rather than in
   a column of their own, so a card with little to say costs little space. */
.card__head{display:flex;flex-wrap:wrap;align-items:baseline;gap:.4rem 1rem;margin:0 0 .9rem}
.card__head h3{margin:0}
.card__foot{display:flex;flex-wrap:wrap;align-items:center;gap:.2rem 1.25rem;
margin-top:1rem;padding-top:.75rem;border-top:1px solid var(--rule);
font:400 var(--t-meta)/1.5 var(--font-ui);color:var(--ink-soft)}
.card__foot > *{margin:0;max-width:100%;min-width:0}
.card__foot details[open]{flex:1 0 100%}
.card__foot .lab{display:inline;margin-right:.35rem}
.card__foot summary{min-height:auto}
.card__foot a{color:inherit}

/* The decision is the page's one instruction, so it is the one block that
   carries a tint. Its hue is the verdict's, which is why a page that does not
   hold looks different before a word of it is read. */
.decision{margin-top:1.6rem;padding:1.15rem 1.4rem;background:var(--edge-soft);
border-left:2px solid var(--edge);border-radius:0 6px 6px 0}
.decision__lead{font:400 var(--t-lead)/1.5 var(--font-ui)}
.decision__lead > p:first-child:has(.tag){margin-bottom:.6rem}
.decision__lead p{max-width:min(var(--text),68ch)}
.decision__lead p:last-child{margin-bottom:0}
.decision__cells{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));
margin:.85rem 0 0;border-top:1px solid var(--rule)}
.decision__cells > div{padding:.75rem 1.4rem 0 0;border-right:1px solid var(--rule)}
.decision__cells > div:last-child{border-right:0;padding-right:0}
.decision__cells dd{margin:.25rem 0 0;max-width:60ch;text-wrap:pretty}
@media (max-width:639px){
.decision__cells{grid-template-columns:1fr}
.decision__cells > div{padding:.75rem 0;border-right:0;border-bottom:1px solid var(--rule)}
.decision__cells > div:last-child{border-bottom:0}}

.fields{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:.7rem 1rem;margin:0}
.fields > div{display:contents}
.fields dt{padding-top:.2rem;font:500 var(--t-micro)/1.45 var(--font-mono);letter-spacing:.1em;
text-transform:uppercase;color:var(--ink-faint)}
.fields dd{margin:0}
@media (max-width:639px){.fields{grid-template-columns:1fr;gap:.2rem}
.fields dd{margin:0 0 .5rem}}

/* Shape is dense reference material: terms in mono at their own case, so a
   signature reads as a signature, and definitions on a settled left edge. It
   takes the bleed because a signature is as long as it is. */
.defs{margin-top:2rem}
.defs:first-of-type{margin-top:0}
.defs .fields{grid-template-columns:minmax(0,20rem) minmax(0,1fr);gap:.55rem 1.5rem}
.defs .fields dt{padding-top:.1rem;font:500 var(--t-dense)/1.5 var(--font-mono);
letter-spacing:0;text-transform:none;color:var(--ink)}
.defs .fields dd{font-size:var(--t-dense);color:var(--ink-soft)}
/* A code group states its language in the heading line and then gets out of
   the way; the comments inside it are the prose, so they read as prose. */
.defs__head{display:flex;flex-wrap:wrap;align-items:baseline;gap:.4rem .8rem;margin:0 0 .35rem}
.defs__head h3{margin:0;font:600 1.02rem/1.4 var(--font-ui)}
.defs__note{margin:0 0 .7rem;font:400 var(--t-meta)/1.5 var(--font-ui);color:var(--ink-faint);
max-width:min(var(--text),68ch)}
.defs--code .defs__head{margin:0 0 .35rem}
.defs--code pre{margin:0}
pre .c{color:var(--ink-faint);font-style:italic}
@media (max-width:639px){.defs .fields{grid-template-columns:1fr}}

.claims{list-style:none;margin:0;padding:0;max-width:none}
.claim{margin:0 0 .9rem}
.claim__card{padding:1.2rem 1.4rem;border:1px solid var(--rule);border-radius:8px;
background:var(--card);box-shadow:var(--shadow)}
.claim__statement{margin:0 0 .7rem;font:400 var(--t-lead)/1.45 var(--font-ui)}
.claim__card > p{max-width:min(var(--text),68ch)}
.claim__card figure{max-width:none}
.claim__mark{display:flex;flex-wrap:wrap;align-items:center;gap:.35rem .7rem;margin:0 0 .7rem}
.claim__evidence{margin-top:.8rem}
.shows{margin:0 0 .8rem}
.shows ul{margin:.35rem 0 0;padding-left:1.05rem;max-width:min(var(--text),68ch)}
.shows li{margin:0 0 .2rem;font-size:var(--t-dense);color:var(--ink-soft)}
.shows li::marker{color:var(--ink-hint)}
.judgment{margin-top:1.6rem;padding:1rem 1.2rem;background:var(--paper-sunk);
border-radius:6px}
.judgment .lab{margin-bottom:.4rem}
.judgment p:last-child{margin-bottom:0}

.rows{list-style:none;margin:0;padding:0;max-width:none;border-bottom:1px solid var(--rule)}
.row{margin:0;padding:.9rem 0;border-top:1px solid var(--rule)}
.rows__caption{margin:0 0 .5rem;font:500 var(--t-micro)/1.45 var(--font-mono);letter-spacing:.1em;
text-transform:uppercase;color:var(--ink-faint)}
.row__note{display:block;margin-top:.25rem;font:400 var(--t-meta)/1.5 var(--font-ui);
color:var(--ink-faint)}
.rows--followup{color:var(--ink-soft)}
.closing{margin-top:4rem;padding:1.15rem 1.4rem;background:var(--paper-sunk);
border-left:2px solid var(--edge);border-radius:0 6px 6px 0}

details{margin:0}
summary{display:flex;align-items:center;gap:.5rem;min-height:44px;cursor:pointer;list-style:none;
font:500 var(--t-meta)/1.45 var(--font-ui);color:var(--ink-soft)}
summary::-webkit-details-marker{display:none}
summary::before{content:"\\25B8";display:inline-block;color:var(--ink-faint);
transition:transform 150ms ease}
details[open] > summary::before{transform:rotate(90deg)}
.dis__body{max-width:100%;padding:.8rem 1rem;border:1px solid var(--rule);
border-radius:6px;background:var(--paper-sunk)}
.dis__body > :last-child{margin-bottom:0}
.dis--block{margin-top:-1px;border-top:1px solid var(--rule);border-bottom:1px solid var(--rule)}
/* A disclosure whose body must survive printing keeps that body beside the
   control rather than inside it; the control's own open state reveals it. */
.dis--static > .dis__body{display:none}
.dis--static > details[open] ~ .dis__body{display:block}
.diagnostics{margin-top:4rem}

table{width:100%;border-collapse:collapse;margin:.5rem 0 1rem;
font:400 var(--t-dense)/1.5 var(--font-ui);font-variant-numeric:tabular-nums}
caption{padding-bottom:.5rem;text-align:left;font:500 var(--t-micro)/1.45 var(--font-mono);
letter-spacing:.1em;text-transform:uppercase;color:var(--ink-faint)}
th{text-align:left;font:600 var(--t-micro)/1.45 var(--font-mono);letter-spacing:.1em;
text-transform:uppercase;color:var(--ink-faint);white-space:nowrap;
padding:0 1rem .55rem 0;border-bottom:1px solid var(--rule)}
td{padding:.65rem 1rem .65rem 0;vertical-align:top;color:var(--ink-soft);
border-bottom:1px solid var(--rule)}
td:first-child{color:var(--ink);font-weight:500}
.scroll{overflow-x:auto}
/* Narrow, a comparison table stops being one: the columns are too thin to read
   across and the scroll that would fix it is invisible until you find it. Each
   row becomes a record instead, every cell still labelled by the column it
   answers to, so the semantics survive even though the geometry does not. */
@media screen and (max-width:639px){
.scroll{overflow-x:visible}
.scroll table,.scroll tbody,.scroll tr,.scroll td{display:block;width:100%}
.scroll thead,.scroll th{position:absolute;width:1px;height:1px;margin:-1px;
overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.scroll tr{padding:.85rem 0;border-top:1px solid var(--rule)}
.scroll tr:first-of-type{border-top:0}
.scroll td{padding:0 0 .4rem;border-bottom:0}
.scroll td:last-child{padding-bottom:0}
.scroll td:empty{display:none}
.scroll td::before{content:attr(data-label);display:block;margin-bottom:.1rem;
font:500 var(--t-micro)/1.45 var(--font-mono);letter-spacing:.1em;
text-transform:uppercase;color:var(--ink-faint)}
.scroll td:first-child::before{display:none}
.scroll td:first-child{font:500 1rem/1.5 var(--font-ui);color:var(--ink)}}

code{font-family:var(--font-mono);font-size:.855em;background:var(--paper-sunk);
padding:.1em .34em;border-radius:3px}
pre{max-width:100%;margin:.5rem 0;padding:.9rem 1.05rem;overflow-x:auto;border:1px solid var(--rule);
border-radius:6px;background:var(--card);box-shadow:var(--shadow);
font:400 .8rem/1.62 var(--font-mono);color:var(--ink-soft)}
pre code{background:none;padding:0;font-size:inherit}
figure{margin:1.6rem 0}
img,video{display:block;max-width:100%;height:auto;border:1px solid var(--rule);border-radius:6px}
audio{width:100%}
figcaption{margin-top:.7rem;max-width:68ch;color:var(--ink-faint);
font:italic 400 var(--t-meta)/1.5 var(--font-display)}
.missing{margin:.5rem 0;padding-left:.75rem;border-left:2px solid var(--crit);
font:400 var(--t-meta)/1.5 var(--font-ui);color:var(--crit)}

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
body{font-size:11.5pt}
:root{--paper:#ffffff;--paper-sunk:#f4f2ee;--card:#ffffff;
--ink:#111111;--ink-soft:#3f3f3f;--ink-faint:#5c5c5c;
--rule:#cbcbcb;--rule-strong:#999999;--accent:#14495a;
--good:#2c5335;--warn:#7d430f;--crit:#7d2222;
--accent-soft:#eef4f6;--good-soft:#eef3ef;--warn-soft:#f8f2e6;--crit-soft:#f9eded;
--shadow:none}
header.masthead{padding-top:0}
main{padding-bottom:0}
h1{font-size:2rem}
.standfirst{font-size:1.15rem}
.meta{margin-top:1rem}
.block,.closing,.diagnostics{margin-top:1.6rem}
.decision{margin-top:1rem}
.metrics{margin-top:1.2rem}
.stage,.claim{margin-bottom:.5rem}
/* Paper has no viewport to bleed into: everything returns to one column. */
.wide,.widen,.metrics,.decision{margin-inline:0;width:100%}
.card__foot{gap:.1rem 1rem}
.row{padding:.5rem 0}
.dis--diagnostics{display:none}
/* Printed, a disclosure is not a control: its label stays as a heading for the
   body below it, and the body is always there. */
.dis--static summary{cursor:default}
.dis--static summary::before{display:none}
.dis--static > .dis__body{display:block}
.claim,.stage,figure,.map,.metrics{break-inside:avoid}
h2{break-after:avoid}
a{text-decoration:none}
}
"""

# Route geometry: the map, the rail, its nodes, and the research fork block.
# Only the plan page has a sequence, so only the plan page carries these rules.
_STYLE_PLAN = """
.map{margin-block:0 2.4rem}
@media screen and (max-width:719px){.map{display:none}}
.map svg{display:block;width:100%;height:auto}
.map__node{fill:var(--card);stroke:var(--rule-strong);stroke-width:1.2}
.map__id{fill:var(--accent);font-family:var(--font-mono);font-size:11px;letter-spacing:.08em}
.map__name{fill:currentColor;font-family:var(--font-ui);font-size:11.5px}
.map__flow{fill:none;stroke:var(--ink-faint);stroke-width:1.3}
.map__enables{fill:none;stroke:var(--accent);stroke-width:1.4}
.map__branch{fill:none;stroke:var(--ink-faint);stroke-width:1.3;stroke-dasharray:4 3}
.map__edge{fill:var(--ink-faint);font-family:var(--font-mono);font-size:9.5px;
letter-spacing:.04em}
.map__edge--enables{fill:var(--accent)}
.map__head{fill:var(--ink-faint)}
.map__head--enables{fill:var(--accent)}

.route{list-style:none;margin:0;padding:0;max-width:none}
.stage{margin:0 0 .9rem}
.stage__main{position:relative;padding-left:2.5rem}
.stage__main::before{content:"";position:absolute;left:12px;top:0;bottom:-.9rem;width:1px;
background:var(--rule-strong)}
.stage:last-child .stage__main::before{bottom:auto;height:28px}
.stage[data-enabled="yes"] .stage__main::before{width:2px;left:11px;background:var(--accent)}
.stage__node{position:absolute;left:0;top:15px;display:grid;place-items:center;
width:25px;height:25px;border-radius:50%;background:var(--paper);
font:500 var(--t-micro)/1 var(--font-mono);color:var(--accent)}
.stage__node::before{content:"";position:absolute;inset:0;border:1.5px solid var(--accent);
border-radius:50%}
.stage[data-variant~="research"] .stage__node::before{border-radius:0;transform:rotate(45deg)}
.stage[data-variant~="harness"] .stage__node::before{border-radius:2px}
.stage__card{padding:1.2rem 1.4rem;border:1px solid var(--rule);border-radius:8px;
background:var(--card);box-shadow:var(--shadow)}
.fork{margin-top:.9rem;padding-top:.6rem;border-top:1px solid var(--rule)}
.fork__question{margin:0 0 .5rem;font-weight:500}
.fork__outcomes{list-style:none;margin:0;padding:0;max-width:none}
.fork__outcome{display:grid;grid-template-columns:minmax(0,1fr) max-content;gap:1rem;
margin:0;padding:.5rem 0 .5rem 1rem;border-top:1px solid var(--rule)}
.fork__default{align-self:center;font:500 var(--t-micro)/1.5 var(--font-mono);
letter-spacing:.08em;text-transform:uppercase;color:var(--accent)}
.fork__note{margin:.6rem 0 0;font:400 var(--t-meta)/1.5 var(--font-ui);color:var(--ink-faint);
max-width:60ch}
@media (max-width:899px){
.stage__node{display:none}
.stage__main{padding-left:1rem}
.stage__main::before{left:0;width:2px}
.stage[data-enabled="yes"] .stage__main::before{left:0}}
@media (max-width:639px){
.stage__main{padding-left:.75rem}
.stage__card{padding:1rem}}
"""

# Verdict colour. Only the decision page has anything to be sure, cautious, or
# alarmed about; keeping these here is what makes "nothing on the plan page may
# look verified" a checkable property of the file. The verdict tints exactly
# two things — the rule down the page's top edge and the decision block behind
# it — and every other state on the page is a chip.
HANDOFF_STYLE = """
.tag--ok{color:var(--good)}
.tag--caution{color:var(--warn)}
.tag--alert{color:var(--crit)}
body[data-verdict="holds"]{--edge:var(--accent);--edge-soft:var(--accent-soft)}
body[data-verdict="holds-with-limits"]{--edge:var(--warn);--edge-soft:var(--warn-soft)}
body[data-verdict="not-decidable"]{--edge:var(--crit);--edge-soft:var(--crit-soft)}
.claim__gap{font:400 var(--t-meta)/1.5 var(--font-ui);color:var(--ink-faint)}
.claim[data-coverage="limited"] .claim__gap,
.claim[data-coverage="unproved"] .claim__gap{color:var(--ink-soft)}
.verdict__by{font:400 var(--t-meta)/1.5 var(--font-ui);color:var(--ink-faint);max-width:68ch}
.limits{list-style:none;margin:.9rem 0 0;padding:0;border-bottom:1px solid var(--rule)}
.limits li{margin:0;padding:.75rem 0;border-top:1px solid var(--rule)}
"""


# -- the document shell ----------------------------------------------------------------


def document(
    title: str,
    content: str,
    *,
    surface: str = "",
    standfirst: str = "",
    meta: str = "",
    summary: str = "",
    style: str = "",
    verdict: str = "",
) -> str:
    """One self-contained page: masthead, main, and exactly one stylesheet.

    The masthead states what kind of page this is, what it is called, and — in
    the standfirst — the one sentence a reader needs before any of the detail
    below can mean anything. Both pages derive that sentence rather than
    letting an agent write a second one alongside the title."""

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
        f'<p class="standfirst">{standfirst}</p>' if standfirst else "",
        f'<p class="meta">{html.escape(meta)}</p>' if meta else "",
        summary,
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


def disclosure(summary: str, body: str, *, variant: str = "inline", static_print: bool = False) -> str:
    """Trusted machinery, reachable and off the surface. Never a decision input.

    `static_print` keeps the body out of the `<details>` element and reveals it
    with a sibling rule instead. A closed `<details>` does not render its
    children at all, so no stylesheet can bring them back for print; content
    that must survive being printed cannot live inside one. On screen the
    behaviour is identical: closed until the summary is opened."""

    if static_print:
        return (
            f'<div class="dis dis--{html.escape(variant, quote=True)} dis--static">'
            f'<details><summary>{html.escape(summary)}</summary></details>'
            f'<div class="dis__body">{body}</div></div>'
        )
    return (
        f'<details class="dis dis--{html.escape(variant, quote=True)}">'
        f"<summary>{html.escape(summary)}</summary>"
        f'<div class="dis__body">{body}</div></details>'
    )


def chip(word: str, *, role: str = "") -> str:
    """One state, as a word in a bordered chip.

    The word is the whole of it: colour rides on the border and the text and
    can be lost entirely — to a monochrome printer, to a reader who cannot
    separate the hues — without the chip stopping saying what it says."""

    variant = f" tag--{html.escape(role, quote=True)}" if role else ""
    return f'<span class="tag{variant}">{html.escape(word)}</span>'


def metrics(cells: Sequence[tuple[str, str, str, str]]) -> str:
    """The numbers a reader wants before the prose: name, value, unit, tone.

    Everything here is counted from the same material the sections below
    render, so the strip can never disagree with them. It is the one place on
    either page where a figure is allowed to be large."""

    if not cells:
        return ""
    body = []
    for label, value, unit, tone in cells:
        attribute = f' data-tone="{html.escape(tone, quote=True)}"' if tone else ""
        suffix = f"<span>{html.escape(unit)}</span>" if unit else ""
        body.append(
            f"<div><dt>{html.escape(label)}</dt>"
            f"<dd{attribute}>{html.escape(value)}{suffix}</dd></div>"
        )
    return '<dl class="metrics">' + "".join(body) + "</dl>"


def decision_rows(
    rows: Sequence[dict[str, Any]],
    *,
    variant: str = "ask",
    label: str = "",
    note: str = "",
    columns: Sequence[str] = (),
) -> str:
    """The four-part operator grammar wherever a question or a decision appears.

    A row that carries qualifiers — when it happens, what happens by default,
    what it would cost — is comparative material, and comparative material is
    read down columns. With `columns` the qualifiers become the columns they
    already were; without any, the rows stay a plain list. Either way the
    separator that used to stand in for a column boundary is gone.

    `label` names the table for a reader who cannot see the heading above it;
    `note` is a visible qualification of the whole set."""

    if not rows:
        return ""
    heading = f'<p class="rows__caption">{html.escape(note)}</p>' if note else ""
    if columns:
        header = "".join(f'<th scope="col">{html.escape(name)}</th>' for name in columns)
        body: list[str] = []
        for row in rows:
            parts = row.get("parts") or {}
            cells = [
                f'<td data-label="{html.escape(columns[0], quote=True)}">'
                f'{_inline(str(row.get("thing", "")))}</td>'
            ]
            cells.extend(
                f'<td data-label="{html.escape(name, quote=True)}">'
                f'{_inline(str(parts.get(name, "")))}</td>'
                for name in columns[1:]
            )
            body.append("<tr>" + "".join(cells) + "</tr>")
        return (
            heading
            + f'<div class="scroll widen rows--{html.escape(variant, quote=True)}"><table>'
            f'<caption class="vh">{html.escape(label or columns[0])}</caption>'
            f"<tr>{header}</tr>" + "".join(body) + "</table></div>"
        )
    items = []
    for row in rows:
        tail = (
            f'<span class="row__note">{_inline(str(row["note"]))}</span>'
            if row.get("note") else ""
        )
        items.append(f'<li class="row">{_inline(str(row.get("thing", "")))}{tail}</li>')
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
        marks = "".join(stage.get("marks") or [])
        foot = "".join(stage.get("foot") or [])
        enabled = ' data-enabled="yes"' if stage.get("enabled") else ""
        items.append(
            f'<li class="stage" id="m{stage["id"]}" data-milestone="{stage["id"]}"'
            f' data-variant="{html.escape(variants, quote=True)}"{enabled}>'
            '<div class="stage__main">'
            f'<span class="stage__node" aria-hidden="true">{stage["id"]}</span>'
            '<article class="stage__card">'
            f'<div class="card__head"><h3>Milestone {stage["id"]} — '
            f'{html.escape(str(stage["title"]))}</h3>{marks}</div>'
            f'<dl class="fields">{fields}</dl>{stage.get("fork") or ""}'
            + (f'<div class="card__foot">{foot}</div>' if foot else "")
            + "</article></div></li>"
        )
    return '<ol class="route">' + "".join(items) + "</ol>"


def claim_cards(rows: Sequence[dict[str, Any]]) -> str:
    """A promise joined to the thing that shows it — intended, or proved."""

    items: list[str] = []
    for row in rows:
        card: list[str] = []
        if row.get("mark"):
            # State and gap are one fact about the evidence, so they are one
            # line. A claim with nothing missing says so in three words rather
            # than in a labelled paragraph repeated down the page.
            card.append(
                f'<p class="claim__mark">{row["mark"]}{row.get("gap_html") or ""}</p>'
            )
        card.append(f'<p class="claim__statement">{_inline(str(row["claim"]))}</p>')
        if row.get("shows_html"):
            card.append(row["shows_html"])
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
        foot = "".join(row.get("foot") or [])
        if foot:
            card.append(f'<div class="card__foot">{foot}</div>')
        coverage = f' data-coverage="{html.escape(row["coverage"], quote=True)}"' if row.get("coverage") else ""
        items.append(
            f'<li class="claim"{coverage}>'
            f'<article class="claim__card">{"".join(card)}</article></li>'
        )
    return '<ul class="claims">' + "".join(items) + "</ul>"


def shows_list(label: str, items: Sequence[str], *, quoted: bool = False) -> str:
    """What a claim answers to, one line per thing.

    These are separate accepted demonstrations, and a list joined by a
    separator is still a list: run together into one line, the sentences read
    as a single garbled claim and their count stops being visible."""

    if not items:
        return ""
    quote = '“{}”' if quoted else "{}"
    body = "".join(f"<li>{quote.format(html.escape(item))}</li>" for item in items)
    return (
        f'<div class="shows"><span class="lab">{html.escape(label)}</span>'
        f"<ul>{body}</ul></div>"
    )


# Where a line comment starts, per language. A signature list is mostly
# declarations and the sentences that qualify them, and telling those two apart
# is the whole of the highlighting worth doing without a parser: `#` is a
# comment in Python and an attribute in Rust, so the language has to say.
COMMENT_MARKERS = {
    "": ("//", "#"),
    "c": ("//",), "cpp": ("//",), "c++": ("//",), "cs": ("//",), "csharp": ("//",),
    "dart": ("//",), "go": ("//",), "java": ("//",), "javascript": ("//",),
    "js": ("//",), "jsx": ("//",), "kotlin": ("//",), "php": ("//",),
    "rust": ("//",), "scala": ("//",), "swift": ("//",), "ts": ("//",),
    "tsx": ("//",), "typescript": ("//",), "zig": ("//",),
    "bash": ("#",), "elixir": ("#",), "julia": ("#",), "nix": ("#",),
    "perl": ("#",), "python": ("#",), "py": ("#",), "r": ("#",), "ruby": ("#",),
    "rb": ("#",), "sh": ("#",), "shell": ("#",), "toml": ("#",), "yaml": ("#",),
    "yml": ("#",), "zsh": ("#",),
    "elm": ("--",), "haskell": ("--",), "hs": ("--",), "lua": ("--",), "sql": ("--",),
}


def _comment_start(line: str, markers: Sequence[str]) -> int:
    """Where a line's trailing comment begins, or -1.

    A marker counts only at the start of the line or after whitespace, so a
    `//` inside a URL and a `#` inside a fragment stay code. Block comments are
    left alone: they render unstyled rather than half-styled."""

    best = -1
    for marker in markers:
        position = line.find(marker)
        while position != -1:
            if position == 0 or line[position - 1].isspace():
                if best == -1 or position < best:
                    best = position
                break
            position = line.find(marker, position + 1)
    return best


def code_block(source: str, *, language: str = "") -> str:
    """A block of code, with its comments told apart from its declarations.

    There is no highlighter here and no script to run one: the page has to open
    with nothing available to it. What a reader actually needs from a list of
    signatures is to see which lines are the contract and which are the prose
    about it, and that much can be found without parsing anything."""

    markers = COMMENT_MARKERS.get(language.casefold(), COMMENT_MARKERS[""])
    lines: list[str] = []
    for line in source.rstrip().splitlines():
        cut = _comment_start(line, markers)
        if cut == -1:
            lines.append(html.escape(line))
            continue
        lines.append(
            html.escape(line[:cut])
            + f'<span class="c">{html.escape(line[cut:])}</span>'
        )
    return "<pre><code>" + "\n".join(lines) + "</code></pre>"


def definition_block(groups: Sequence[Any]) -> str:
    """One component per block: what it owns, and the surface it exposes.

    A group written as code is shown as code. A signature rewritten as a
    term-and-definition row stops looking like the thing it describes, and the
    reader has to reassemble the call from prose. Keeping each component's
    types and functions together is what stops one surface being spread across
    three lists the reader has to join up."""

    parts: list[str] = []
    for group in groups:
        note = f'<p class="defs__note">{_inline(group.note)}</p>' if group.note else ""
        head = (
            '<div class="defs__head">'
            f'<h3>{html.escape(group.name)}</h3>'
            + (chip(group.language, role="accent") if group.language else "")
            + "</div>" + note
        )
        if group.code:
            parts.append(
                f'<section class="defs defs--code widen">{head}'
                + code_block(group.code, language=group.language)
                + "</section>"
            )
            continue
        if not group.entries:
            continue
        body = "".join(
            f"<div><dt>{_inline(term)}</dt><dd>{_inline(definition)}</dd></div>"
            for term, definition in group.entries
        )
        parts.append(
            f'<section class="defs widen">{head}<dl class="fields">{body}</dl></section>'
        )
    return "".join(parts)


def verdict_panel(*, summary: str, attribution: str, limitations: Sequence[str]) -> str:
    """The independent reader's judgment, and the boundaries of it.

    An absence is worth one clause, not a paragraph: a review that found
    nothing uncovered says so on the same line that says who reviewed it, and
    only a review with real boundaries spends a list on them."""

    if limitations:
        body = '<ul class="limits">' + "".join(
            "<li>The review did not cover: "
            + html.escape(item if item.rstrip().endswith((".", "!", "?")) else item.rstrip() + ".")
            + "</li>"
            for item in limitations
        ) + "</ul>"
        tail = ""
    else:
        body = ""
        tail = " The review reports no limitation."
    return (
        f'<div class="verdict"><p>{html.escape(summary)}</p>'
        f'<p class="verdict__by">{html.escape(attribution + tail)}</p>{body}</div>'
    )


def section(heading: str, body: str, *, anchor: str, extra: str = "", headline: str = "") -> str:
    """A titled region. A region with no body is not rendered at all.

    `heading` is the section's fixed name — the thing that lets a reader who
    has seen one of these pages find their way around the other. `headline` is
    what this particular section turned out to contain, derived from the same
    material the section renders, so the two never disagree. Without one, the
    name stands alone."""

    if not body.strip():
        return ""
    classes = f"block {extra}".strip()
    title = (
        f'<span class="kicker">{html.escape(heading)}</span>{html.escape(headline)}'
        if headline else html.escape(heading)
    )
    return (
        f'<section class="{classes}" aria-labelledby="{anchor}">'
        f'<h2 id="{anchor}">{title}</h2>{body}</section>'
    )


# -- the plan approval page ------------------------------------------------------------


GATE_STATEMENTS = {
    (False, False): "task completion",
    (True, False): "check",
    (False, True): "task completion + independent review",
    (True, True): "check + independent review",
}

# Above this the map stops being a picture and becomes a chart nobody reads:
# the nodes narrow past their labels and the arcs start crossing. A longer
# route keeps the rail, which stays legible at any length.
MAP_LIMIT = 6
_MAP = {"pad": 22, "node_w": 132, "gap": 40, "node_h": 58, "spine": 128, "below": 78}


def _map_lines(text: str, width: int, limit: int = 2) -> list[str]:
    """A node label broken to the node's width, and truncated rather than
    overset: a name that will not fit is still recognisable from its start."""

    words, lines, current = str(text).split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= width or not current:
            current = candidate
            continue
        lines.append(current)
        current = word
        if len(lines) == limit:
            break
    if current and len(lines) < limit:
        lines.append(current)
    if len(lines) == limit and len(" ".join(lines)) < len(text.strip()):
        lines[-1] += "…"
    # A single word wider than the node was placed whole to avoid an empty
    # line; clip it here so nothing is drawn outside the box it belongs to.
    return [line if len(line) <= width else line[: width - 1].rstrip() + "…" for line in lines]


def _arc(x1: int, x2: int, y: int, lift: int) -> str:
    """A cubic from one node edge to another, bowed clear of the spine."""

    return f"M {x1} {y} C {x1} {y + lift}, {x2} {y + lift}, {x2} {y}"


def route_map(routes: Sequence[dict[str, Any]], chunks: dict[Any, dict[str, Any]]) -> str:
    """The route as a graph, when the route is small enough to be seen as one.

    The cards below state each milestone's causal claims in sentences; the
    dependencies between them are a shape, and a reader should not have to
    rebuild that shape by holding four cards in mind at once. Build order runs
    left to right along the spine. An arc below names the milestone a harness
    makes testable; a dashed arc above names one whose shape is still waiting
    on a research outcome."""

    if not 2 <= len(routes) <= MAP_LIMIT:
        return ""
    order = {route["id"]: index for index, route in enumerate(routes)}
    enables: list[tuple[int, int]] = []
    branches: list[tuple[int, int]] = []
    for route in routes:
        for target in (route.get("enables") or {}).get("milestones", []):
            if target in order:
                enables.append((route["id"], target))
        for outcome in (route.get("branch") or {}).get("outcomes", []):
            if outcome["default"]:
                continue
            for reference in _MILESTONE_REFERENCE.findall(outcome["text"]):
                target = int(reference)
                if target in order and target != route["id"] and (route["id"], target) not in branches:
                    branches.append((route["id"], target))
    if not enables and not branches:
        return ""

    # Arcs out of one node are stacked rather than drawn at a single depth:
    # two edges from the same milestone have midpoints close enough that one
    # label would sit on the other.
    def stack(edges: list[tuple[int, int]]) -> dict[tuple[int, int], int]:
        depths, seen = {}, {}
        for source, target in edges:
            index = seen.get(source, 0)
            seen[source] = index + 1
            depths[(source, target)] = 46 + index * 24
        return depths

    enable_depth, branch_depth = stack(enables), stack(branches)
    pad, node_w, gap = _MAP["pad"], _MAP["node_w"], _MAP["gap"]
    node_h = _MAP["node_h"]
    width = 2 * pad + len(routes) * node_w + (len(routes) - 1) * gap
    # The spine sits low enough for the deepest arc above it and the drawing
    # ends below the deepest arc under it, so no edge is ever clipped.
    above = max(branch_depth.values(), default=0)
    below = max(enable_depth.values(), default=0)
    spine = max(_MAP["spine"], node_h // 2 + int(above * 0.75) + 26)
    height = spine + node_h // 2 + max(_MAP["below"], int(below * 0.75) + 26)
    top, bottom = spine - node_h // 2, spine + node_h // 2

    def left(identifier: int) -> int:
        return pad + order[identifier] * (node_w + gap)

    def centre(identifier: int) -> int:
        return left(identifier) + node_w // 2

    parts: list[str] = [
        '<defs>'
        '<marker id="mh" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6.5" markerHeight="6.5"'
        ' orient="auto-start-reverse">'
        '<path class="map__head" d="M 0 0 L 10 5 L 0 10 z"></path></marker>'
        '<marker id="mh-e" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6.5" markerHeight="6.5"'
        ' orient="auto-start-reverse">'
        '<path class="map__head map__head--enables" d="M 0 0 L 10 5 L 0 10 z"></path></marker>'
        "</defs>"
    ]
    for route in routes[:-1]:
        start = left(route["id"]) + node_w
        parts.append(
            f'<line class="map__flow" x1="{start}" y1="{spine}"'
            f' x2="{start + gap - 7}" y2="{spine}" marker-end="url(#mh)"></line>'
        )
    for route in routes:
        x, title = left(route["id"]), chunks.get(route["id"], {}).get("title", "")
        lines = _map_lines(title, 21)
        parts.append(
            f'<rect class="map__node" x="{x}" y="{top}" width="{node_w}" height="{node_h}"'
            ' rx="7"></rect>'
        )
        parts.append(
            f'<text class="map__id" x="{x + node_w // 2}" y="{top + 18}"'
            f' text-anchor="middle">M{route["id"]}</text>'
        )
        for offset, line in enumerate(lines):
            parts.append(
                f'<text class="map__name" x="{x + node_w // 2}" y="{top + 34 + offset * 14}"'
                f' text-anchor="middle">{html.escape(line)}</text>'
            )
    # One label per source, on its outermost arc: the relation is the same
    # along every edge leaving a node, so repeating the words per edge would
    # say nothing extra and crowd what it sits on.
    def label_at(edges: list[tuple[int, int]], depths: dict[tuple[int, int], int]) -> dict[int, tuple[int, int]]:
        placed: dict[int, tuple[int, int]] = {}
        for source, target in edges:
            depth = depths[(source, target)]
            if source not in placed or depth > placed[source][1]:
                placed[source] = ((centre(source) + centre(target)) // 2, depth)
        return placed

    for source, target in enables:
        depth = enable_depth[(source, target)]
        parts.append(
            f'<path class="map__enables" d="{_arc(centre(source), centre(target), bottom, depth)}"'
            ' marker-end="url(#mh-e)"></path>'
        )
    for source, (x, depth) in label_at(enables, enable_depth).items():
        parts.append(
            f'<text class="map__edge map__edge--enables" x="{x}"'
            f' y="{bottom + int(depth * 0.75) + 13}" text-anchor="middle">makes testable</text>'
        )
    for source, target in branches:
        depth = branch_depth[(source, target)]
        parts.append(
            f'<path class="map__branch" d="{_arc(centre(source), centre(target), top, -depth)}"'
            ' marker-end="url(#mh)"></path>'
        )
    for source, (x, depth) in label_at(branches, branch_depth).items():
        parts.append(
            f'<text class="map__edge" x="{x}" y="{top - int(depth * 0.75) - 7}"'
            ' text-anchor="middle">shape depends on the outcome</text>'
        )

    told: list[str] = ["The build order runs left to right."]
    if enables:
        told.append("An arc below names the milestone a harness makes testable.")
    if branches:
        told.append(
            "A dashed arc above names a milestone whose shape is still waiting "
            "on a research outcome."
        )
    claim = " ".join(told)
    return (
        '<figure class="map wide">'
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(claim, quote=True)}">'
        + "".join(parts)
        + f"</svg><figcaption>{html.escape(claim)}</figcaption></figure>"
    )


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

    # The objective's opening sentence is what the plan is for; everything the
    # planner wrote after it qualifies that sentence and belongs beside the
    # ask. Splitting here is what gives the masthead a standfirst without
    # asking an agent to write the same thing twice.
    goal = operator.get("goal") or plan.get("goal", "")
    standfirst, remainder = split_lead(goal)

    content = [
        decision(
            markdown(remainder, base=base, base_level=2),
            ask_label="You approve",
            ask="This route",
            default="Nothing starts",
            exposure=exposure,
            variant="approve",
        )
    ]
    routes = operator.get("routes", [])
    content.append(section(
        "Route",
        _route(operator, chunks, tasks_by_chunk, base),
        anchor="route",
        headline=_route_headline(routes),
    ))
    content.append(section(
        "Interfaces",
        _shape(operator.get("shape", ""), base),
        anchor="shape",
        headline=_shape_headline(operator.get("shape", "")),
    ))
    content.append(section(
        "Intended proof",
        _intended_proof(plan, operator, acceptance, base),
        anchor="proof",
        headline=_proof_headline(plan.get("evidence", [])),
    ))
    ask_columns, ask_rows = _authored_rows(operator.get("asks", ""))
    content.append(
        section(
            "What you will be asked",
            decision_rows(
                ask_rows, variant="ask", columns=ask_columns, label="What you will be asked"
            ),
            anchor="asks",
        )
    )
    question_columns, question_rows = _authored_rows(operator.get("open_questions", ""))
    content.append(
        section(
            "Open questions",
            decision_rows(
                question_rows, variant="question", columns=question_columns, label="Open questions"
            ),
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
            [{"thing": "You approve this route.", "note": "Default: nothing starts."}],
            variant="ask",
        )
        + "</section>"
    )
    return document(
        title,
        "\n".join(part for part in content if part),
        surface="Autopilot · plan approval",
        standfirst=_inline(standfirst, base),
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
            markers.append(chip("Research fork", role="fork"))
        if route.get("enables"):
            variants.append("harness")
            markers.append(chip("Enables testing", role="harness"))
        if index == len(routes) - 1:
            variants.append("landing")
        fields = [
            ("Produces", _inline(route["produces"], base)),
            ("Unlocks", _inline(route["unlocks"], base)),
        ]
        if route.get("enables"):
            fields.append(("Enables", _inline(route["enables"]["text"], base)))
        fields.append(("Validated by", _inline(route["validated by"], base)))

        foot: list[str] = []
        gate = GATE_STATEMENTS[(bool(chunk.get("check")), chunk.get("review") is not False)]
        foot.append(f'<p><span class="lab">Gate</span>{html.escape(gate)}</p>')
        for source in sorted(enabled_by.get(route["id"], [])):
            foot.append(
                f'<p>Testable because of <a href="#m{source}">Milestone {source}</a>.</p>'
            )
        for source in sorted(conditional.get(route["id"], [])):
            foot.append(
                f'<p>Conditional on <a href="#m{source}">Milestone {source}</a>.</p>'
            )
        if chunk.get("check"):
            foot.append(
                disclosure(
                    "Exact gate command",
                    f"<pre>{html.escape(str(chunk['check']))}</pre>",
                    variant="inline dis--diagnostics",
                )
            )
        chunk_tasks = tasks_by_chunk.get(route["id"], [])
        if chunk_tasks:
            listed = "".join(f"<li>{html.escape(str(item['title']))}</li>" for item in chunk_tasks)
            foot.append(
                disclosure(
                    f"{len(chunk_tasks)} {'task' if len(chunk_tasks) == 1 else 'tasks'}",
                    f"<ul>{listed}</ul>",
                    variant="inline dis--diagnostics",
                )
            )

        stages.append({
            "id": route["id"],
            "title": chunk["title"],
            "variants": variants,
            "fields": fields,
            "fork": _fork(route.get("branch")),
            "marks": markers,
            "foot": foot,
            "enabled": route["id"] in spans,
        })
    return route_map(routes, chunks) + stage_cards(stages)


def split_lead(text: str) -> tuple[str, str]:
    """The first paragraph, and everything after it.

    A paragraph rather than a sentence: an objective's opening statement often
    runs to two clauses across a line break, and cutting at the first full stop
    would strand half of it."""

    blocks = [block.strip() for block in re.split(r"\n\s*\n", text.strip()) if block.strip()]
    if not blocks:
        return "", ""
    lead = " ".join(line.strip() for line in blocks[0].splitlines())
    return lead, "\n\n".join(blocks[1:])


def _count(number: int, singular: str, plural: str | None = None) -> str:
    word = singular if number == 1 else (plural or singular + "s")
    return f"{number} {word}"


def _route_headline(routes: Sequence[dict[str, Any]]) -> str:
    """What the route turned out to be, counted from the route itself."""

    if not routes:
        return ""
    parts = [_count(len(routes), "milestone")]
    forks = sum(1 for route in routes if route.get("branch"))
    harnesses = sum(1 for route in routes if route.get("enables"))
    if forks:
        parts.append(_count(forks, "research fork"))
    if harnesses:
        parts.append(_count(harnesses, "testing stage"))
    return _join(parts)


def _declarations(code: str, language: str) -> int:
    """How many things a code group declares, for the section headline.

    Only unindented lines count. Indentation is what every language we expect
    here uses to say "this is part of the thing above", so a struct with five
    fields is one data shape rather than six — which is what a reader counting
    the section would say."""

    markers = COMMENT_MARKERS.get(language.casefold(), COMMENT_MARKERS[""])
    total = 0
    for line in code.splitlines():
        if not line[:1].strip():
            continue
        stripped = line.strip()
        if stripped in ("}", ")", "]", "};", ");", "],", "end"):
            continue
        if _comment_start(stripped, markers) == 0:
            continue
        total += 1
    return total


def _shape_headline(source: str) -> str:
    """How much surface the design exposes, and across how many components."""

    groups = [group for group in shape_groups(source) if group]
    if not groups:
        return ""
    total = sum(
        _declarations(group.code, group.language) if group.code else len(group.entries)
        for group in groups
    )
    return f"{_count(len(groups), 'component')}, {_count(total, 'declaration')}"


def _proof_headline(evidence: Sequence[dict[str, Any]]) -> str:
    if not evidence:
        return ""
    captures = sum(len(item.get("artifacts") or []) for item in evidence)
    headline = _count(len(evidence), "claim")
    if captures:
        headline += f", {_count(captures, 'capture')} expected"
    return headline


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
    """Shape as definition lists. The plan contract requires the typed groups,
    so untyped prose only ever reaches here from an older rendered page."""

    groups = shape_groups(source)
    if groups:
        return definition_block(groups)
    return markdown(source, base=base, base_level=2, caption="Interfaces")


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
        foot: list[str] = []
        shown = [
            descriptions[str(value)]
            for value in item.get("demonstrations", [])
            if str(value) in descriptions
        ]
        stages = [
            f'<a href="#m{stage}">Milestone {stage}</a>'
            for stage in item.get("stages", [])
            if stage in chunks
        ]
        if stages:
            foot.append(
                '<p><span class="lab">Delivered by</span>' + ", ".join(stages) + "</p>"
            )
        replay = _replay_summary(item.get("replay", {}))
        if replay:
            foot.append(disclosure("Replay", f"<pre>{html.escape(replay)}</pre>"))
        rows.append({
            "claim": item["claim"],
            "shows_html": shows_list("Will show", shown, quoted=True),
            "fields": [("Expected", html.escape(_join(kinds)))] if kinds else [],
            "foot": foot,
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


def _authored_rows(source: str) -> tuple[list[str], list[dict[str, Any]]]:
    """An authored table as its own columns.

    The planner already wrote these as a table with headings; flattening the
    qualifiers into one line only to separate them with a dot threw away the
    structure the author supplied. The headings come back as the columns."""

    records = _table_records(source)
    if not records:
        return [], []
    columns = [name for name in records[0] if name]
    rows = [
        {
            "thing": record.get(columns[0], ""),
            "parts": {name: record.get(name, "") for name in columns[1:]},
        }
        for record in records
    ]
    return columns, rows


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
            rows.append(_record({
                "Role": str(binding.get("role") or ""),
                "Model": f"{family}/{model}" if family else model,
                "Effort": str(mind.get("effort") or "default"),
                "Material constraints":
                    ", ".join(f"{key}={value}" for key, value in sorted(material.items())) or "none",
            }))
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
            rows.append(_record({
                "#": str(task["id"]),
                "Task": str(task["title"]),
                "Done when": str(task.get("done_when", "")),
                "Check": f"<code>{html.escape(check)}</code>" if check else "",
                "After": after,
                "Role": str(task.get("role") or chunk.get("role") or "implementer"),
            }, raw={"Check"}))
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


def _record(cells: dict[str, str], *, raw: set[str] = frozenset()) -> str:
    """One table row whose cells each name the column they answer to.

    The label is what lets a narrow screen turn the row back into a record
    without a script: the stylesheet reads it out of the attribute."""

    return "<tr>" + "".join(
        f'<td data-label="{html.escape(name, quote=True)}">'
        + (value if name in raw else html.escape(value))
        + "</td>"
        for name, value in cells.items()
    ) + "</tr>"


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
    headers: list[str] = []
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
                headers = [re.sub(r"[*`]", "", cell).strip() for cell in cells]
                table = ['<div class="scroll"><table>', f"<caption>{html.escape(label)}</caption>"]
                table.append(
                    "<tr>" + "".join(f'<th scope="col">{_inline(cell, base)}</th>' for cell in cells) + "</tr>"
                )
            else:
                table.append("<tr>" + "".join(
                    f'<td data-label="{html.escape(headers[index] if index < len(headers) else "", quote=True)}">'
                    f"{_inline(cell, base)}</td>"
                    for index, cell in enumerate(cells)
                ) + "</tr>")
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
# A code span or a link, matched together so each is recognised in the authored
# text rather than in generated markup: a destination is never prose, and prose
# is never re-read as markup once it has become a tag.
_INLINE_SPAN = re.compile(r"`[^`]+`|!?\[[^\]]*\]\([^)\s]+\)")
_LINK = re.compile(r"^(!?)\[([^\]]*)\]\(([^)\s]+)\)$")
# Anything before a colon that a browser would read as a scheme. A relative
# path never matches, because a path separator cannot appear in a scheme.
_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*):")
# Schemes a page may link to. `javascript:` and its relatives execute, and a
# page that is mailed, printed, and read cold is exactly where a link nobody
# audited must not be able to act, so an unlisted scheme is shown, not linked.
LINK_SCHEMES = ("http", "https", "mailto")
# Media the page can embed and still be self-contained: a remote source is
# named rather than fetched, and a data URI is already inert bytes.
MEDIA_SCHEMES = ("http", "https", "data")


def _scheme(target: str) -> str | None:
    match = _SCHEME.match(target.strip())
    return match.group(1).casefold() if match else None


def _linkable(target: str) -> bool:
    """A relative path, a fragment, or a scheme that cannot execute."""

    scheme = _scheme(target)
    return scheme is None or scheme in LINK_SCHEMES


def _prose(text: str) -> str:
    """Authored words: escaped, emphasised, and cross-referenced."""

    escaped = html.escape(text, quote=False)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    return _MILESTONE_REFERENCE.sub(
        lambda match: f'<a href="#m{match.group(1)}">M{match.group(1)}</a>', escaped
    )


def _label(text: str) -> str:
    """A link's own words. A milestone reference inside one would nest an
    anchor in an anchor, so cross-referencing stops at the boundary."""

    return re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", html.escape(text, quote=False))


def _inline(text: str, base: Path | None = None) -> str:
    out: list[str] = []
    position = 0
    for span in _INLINE_SPAN.finditer(text):
        out.append(_prose(text[position:span.start()]))
        position = span.end()
        source = span.group(0)
        link = _LINK.match(source)
        if link is None:
            out.append(f"<code>{html.escape(source[1:-1], quote=False)}</code>")
            continue
        bang, label, target = link.group(1), link.group(2), link.group(3)
        if bang:
            out.append(_media(label, target, base))
        elif _linkable(target):
            out.append(f"<a href='{html.escape(target, quote=True)}'>{_label(label)}</a>")
        else:
            out.append(f"{_label(label)} <code>{html.escape(target, quote=False)}</code>")
    out.append(_prose(text[position:]))
    return "".join(out)


def _media(alt: str, target: str, base: Path | None) -> str:
    """An image or video, inlined as a data URI so the page ships alone."""

    caption = f"<figcaption>{html.escape(alt)}</figcaption>" if alt else ""
    scheme = _scheme(target)
    if scheme is not None and scheme not in MEDIA_SCHEMES:
        return (
            f'<p class="missing">Media source is not a kind the page embeds: '
            f"<code>{html.escape(target)}</code></p>"
        )
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
