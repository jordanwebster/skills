"""Render the wrap-up page: the one page the operator reads when a flight lands."""

from __future__ import annotations

import html
import re
from typing import Any

from .state import Flight


_STYLE = """
:root { color-scheme: light dark; --fg: #1b1b1b; --bg: #fff; --muted: #666; --line: #ddd; --ok: #2a7; --warn: #c73; }
@media (prefers-color-scheme: dark) { :root { --fg: #e6e6e6; --bg: #151515; --muted: #999; --line: #333; } }
body { font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: var(--fg); background: var(--bg); max-width: 60rem; margin: 2rem auto; padding: 0 1rem; }
h1 { font-size: 1.6rem; } h2 { font-size: 1.2rem; margin-top: 2rem; border-bottom: 1px solid var(--line); }
table { border-collapse: collapse; width: 100%; font-size: 0.92rem; } th, td { text-align: left; padding: .35rem .5rem; border-bottom: 1px solid var(--line); vertical-align: top; }
code, pre { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .9em; } pre { overflow-x: auto; padding: .75rem; border: 1px solid var(--line); border-radius: 4px; }
.muted { color: var(--muted); } .done { color: var(--ok); } .open { color: var(--warn); }
"""


def page(title: str, body_markdown: str, *, subtitle: str = "", appendix: str = "") -> str:
    """One styled HTML page: a Markdown body (the front page) and an optional appendix."""

    return "\n".join(
        [
            "<!doctype html>",
            "<html><head><meta charset='utf-8'>",
            f"<title>{html.escape(title)}</title>",
            f"<style>{_STYLE}</style></head><body>",
            f"<h1>{html.escape(title)}</h1>",
            f"<p class='muted'>{subtitle}</p>" if subtitle else "",
            markdown(body_markdown) if body_markdown.strip() else "<p class='muted'>No front page was written.</p>",
            appendix,
            "</body></html>",
        ]
    )


def wrap_up(flight: Flight) -> str:
    acceptance = _read(flight.dir / "acceptance.md")
    subtitle = (
        f"Branch <code>{html.escape(flight.data['branch'])}</code> · "
        f"status <strong>{html.escape(flight.data['status'])}</strong> · "
        f"{flight.data['iteration']} iterations · "
        f"base <code>{html.escape(flight.data['base'][:12])}</code>"
    )
    parts = ["<h2>Chunks and tasks</h2>", _task_table(flight)]
    follow_ups = flight.parked_tasks()
    parts.append("<h2>Follow-ups</h2>")
    if follow_ups:
        parts.append("<ul>")
        for task in follow_ups:
            note = task["notes"].splitlines()[-1] if task["notes"] else ""
            parts.append(f"<li>{html.escape(task['title'])} <span class='muted'>{html.escape(note)}</span></li>")
        parts.append("</ul>")
    else:
        parts.append("<p class='muted'>None recorded.</p>")
    if flight.escalations:
        parts.append("<h2>Questions raised during the flight</h2><table><tr><th>Question</th><th>Answer</th></tr>")
        for item in flight.escalations:
            parts.append(
                f"<tr><td>{html.escape(item['text'])}</td>"
                f"<td>{html.escape(item['answer'] or '(unanswered)')}</td></tr>"
            )
        parts.append("</table>")
    for chunk in flight.chunks:
        text = _read(flight.dir / "reviews" / f"chunk-{chunk['id']}.md")
        if text:
            parts.append(f"<h2>Review — chunk {chunk['id']}: {html.escape(chunk['title'])}</h2>")
            parts.append(markdown(text))
    parts.append("<h2>Event log (last 40)</h2><pre>")
    parts.append(html.escape("\n".join(flight.recent_events(40))))
    parts.append("</pre>")
    return page(flight.data["goal"], acceptance, subtitle=subtitle, appendix="\n".join(parts))


def _task_table(flight: Flight) -> str:
    rows = ["<table><tr><th>#</th><th>Task</th><th>Status</th><th>Origin</th><th>Commit</th></tr>"]
    for chunk in flight.chunks:
        rows.append(
            f"<tr><td colspan='5'><strong>Chunk {chunk['id']} — {html.escape(chunk['title'])}</strong> "
            f"<span class='muted'>({html.escape(chunk['status'])})</span></td></tr>"
        )
        for task in flight.chunk_tasks(chunk["id"]):
            css = "done" if task["status"] == "done" else "open"
            rows.append(
                f"<tr><td>{task['id']}</td><td>{html.escape(task['title'])}</td>"
                f"<td class='{css}'>{html.escape(task['status'])}</td>"
                f"<td class='muted'>{html.escape(task['origin'])}</td>"
                f"<td><code>{html.escape(task['commit'][:10])}</code></td></tr>"
            )
    rows.append("</table>")
    return "\n".join(rows)


def markdown(text: str) -> str:
    """Enough Markdown for agent-written reports: headings, lists, code, paragraphs."""

    out: list[str] = []
    paragraph: list[str] = []
    in_list = False
    in_code = False

    def flush() -> None:
        nonlocal paragraph, in_list
        if paragraph:
            out.append("<p>" + _inline(" ".join(paragraph)) + "</p>")
            paragraph = []
        if in_list:
            out.append("</ul>")
            in_list = False

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
        heading = re.match(r"^(#{1,6})\s+(.*)", line)
        if heading:
            flush()
            level = min(len(heading.group(1)) + 1, 6)
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            continue
        item = re.match(r"^\s*[-*]\s+(.*)", line)
        if item:
            if paragraph:
                flush()
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline(item.group(1))}</li>")
            continue
        if not line.strip():
            flush()
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        paragraph.append(line.strip())
    if in_code:
        out.append("</pre>")
    flush()
    return "\n".join(out)


def _inline(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    return escaped


def _read(path: Any) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""
