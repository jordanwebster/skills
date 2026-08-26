"""Render Autopilot's plan page and generic Markdown pages.

Every page is one self-contained HTML file: a Markdown body, media inlined
as data URIs so the file can be forwarded cold, and an optional appendix
of machine-derived tables. The Markdown dialect is deliberately small —
what agents actually write in reports — and the same renderer serves every
skill in the collection, so the pages look alike.
"""

from __future__ import annotations

import base64
import html
import mimetypes
from pathlib import Path
import re
from typing import Any

# Media larger than this is linked rather than inlined: the page must stay
# something a browser opens instantly and a mail client accepts.
INLINE_MEDIA_LIMIT = 20 * 1024 * 1024
VIDEO_SUFFIXES = (".webm", ".mp4", ".mov", ".m4v")

_STYLE = """
:root { color-scheme: light dark; --fg: #1b1b1b; --bg: #fff; --muted: #666; --line: #ddd; --ok: #2a7; --warn: #c73; --accent: #2a5db0; }
@media (prefers-color-scheme: dark) { :root { --fg: #e6e6e6; --bg: #151515; --muted: #999; --line: #333; --accent: #7aa2e3; } }
body { font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: var(--fg); background: var(--bg); max-width: 62rem; margin: 2rem auto; padding: 0 1rem; }
h1 { font-size: 1.6rem; margin-bottom: .25rem; } h2 { font-size: 1.2rem; margin-top: 2rem; border-bottom: 1px solid var(--line); padding-bottom: .2rem; } h3 { font-size: 1.05rem; margin-top: 1.4rem; }
table { border-collapse: collapse; width: 100%; font-size: 0.92rem; margin: .5rem 0 1rem; } th, td { text-align: left; padding: .35rem .5rem; border-bottom: 1px solid var(--line); vertical-align: top; }
th { color: var(--muted); font-weight: 600; }
code, pre { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .9em; } pre { overflow-x: auto; padding: .75rem; border: 1px solid var(--line); border-radius: 4px; }
img, video { max-width: 100%; display: block; margin: .75rem 0; border: 1px solid var(--line); border-radius: 4px; }
figure { margin: 1rem 0; } figcaption { color: var(--muted); font-size: .9rem; }
a { color: var(--accent); }
.muted { color: var(--muted); } .done { color: var(--ok); } .open { color: var(--warn); }
.chunk-head td { background: color-mix(in srgb, var(--accent) 10%, transparent); }
"""


def page(
    title: str,
    body_markdown: str,
    *,
    subtitle: str = "",
    appendix: str = "",
    base: Path | None = None,
) -> str:
    """One styled HTML page: a Markdown body and an optional HTML appendix."""

    return "\n".join(
        [
            "<!doctype html>",
            "<html><head><meta charset='utf-8'>",
            f"<title>{html.escape(title)}</title>",
            f"<style>{_STYLE}</style></head><body>",
            f"<h1>{html.escape(title)}</h1>",
            f"<p class='muted'>{subtitle}</p>" if subtitle else "",
            markdown(body_markdown, base=base) if body_markdown.strip() else "<p class='muted'>No front page was written.</p>",
            appendix,
            "</body></html>",
        ]
    )


def split_title(text: str, *, default: str) -> tuple[str, str]:
    """Take the first `# ` heading as the page title; the rest is the body."""

    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("# "):
            return line[2:].strip(), "\n".join(lines[:index] + lines[index + 1 :])
    return default, text


def flight_plan(text: str, plan: dict[str, Any], *, title: str, base: Path | None = None) -> str:
    """The plan page: the planner's Markdown with the machine block shown as tables."""

    body = _strip_plan_block(text)
    rendered = markdown(body, base=base)
    tables = plan_tables(plan)
    if _PLAN_MARKER in rendered:
        rendered = rendered.replace(_PLAN_MARKER, tables, 1)
    else:
        rendered += tables
    subtitle = "For the operator's approval. Nothing else will be asked mid-flight except what the page lists."
    return "\n".join(
        [
            "<!doctype html>",
            "<html><head><meta charset='utf-8'>",
            f"<title>{html.escape(title)}</title>",
            f"<style>{_STYLE}</style></head><body>",
            f"<h1>{html.escape(title)}</h1>",
            f"<p class='muted'>{subtitle}</p>",
            rendered,
            "</body></html>",
        ]
    )


_PLAN_MARKER = "<!--flight-plan-tables-->"


def _strip_plan_block(text: str) -> str:
    """Replace the ```flight-plan block with a marker the tables are rendered at."""

    out: list[str] = []
    inside = False
    for line in text.splitlines():
        if not inside and line.strip() == "```flight-plan":
            inside = True
            out.append(_PLAN_MARKER)
            continue
        if inside:
            if line.strip() == "```":
                inside = False
            continue
        out.append(line)
    return "\n".join(out)


def plan_tables(plan: dict[str, Any]) -> str:
    chunks = plan.get("chunks", [])
    tasks = plan.get("tasks", [])
    config = plan.get("config", {})
    by_chunk: dict[Any, list[dict[str, Any]]] = {}
    for task in tasks:
        by_chunk.setdefault(task["chunk"], []).append(task)
    parts: list[str] = []
    for chunk in chunks:
        role = chunk.get("role", "implementer")
        effort = f" ({html.escape(str(chunk['effort']))})" if chunk.get("effort") else ""
        review = "no" if chunk.get("review") is False else "one round against the must-fix bar"
        parts.append(f"<h3>Chunk {chunk['id']} — {html.escape(str(chunk['title']))}</h3>")
        parts.append(
            f"<p class='muted'>Role {html.escape(str(role))}{effort} · check <code>{html.escape(str(chunk.get('check') or 'none'))}</code> · review {review}</p>"
        )
        parts.append("<table><tr><th>#</th><th>Task</th><th>Done when</th><th>Check</th><th>After</th><th>Role</th></tr>")
        for task in by_chunk.get(chunk["id"], []):
            after = ", ".join(str(item) for item in task.get("depends_on", []))
            parts.append(
                f"<tr><td>{task['id']}</td><td>{html.escape(str(task['title']))}</td>"
                f"<td>{html.escape(str(task.get('done_when', '')))}</td>"
                f"<td><code>{html.escape(str(task.get('check') or ''))}</code></td>"
                f"<td>{after}</td><td>{html.escape(str(task.get('role') or ''))}</td></tr>"
            )
        parts.append("</table>")
    counts: dict[str, int] = {}
    for chunk in chunks:
        for task in by_chunk.get(chunk["id"], []):
            role = task.get("role") or chunk.get("role", "implementer")
            counts[role] = counts.get(role, 0) + 1
    parts.append("<h3>Staffing</h3><table><tr><th>Role</th><th>Tasks</th></tr>")
    for role, count in counts.items():
        parts.append(f"<tr><td>{html.escape(role)}</td><td>{count}</td></tr>")
    reviews = sum(1 for chunk in chunks if chunk.get("review") is not False)
    parts.append(f"<tr><td>reviewer</td><td>{reviews} chunk review(s)</td></tr>")
    parts.append("<tr><td>closer</td><td>1 acceptance pass</td></tr></table>")
    bounds = (
        f"Ceiling {config.get('max_iterations', 60)} iterations · retry cap {config.get('retry_cap', 3)} · "
        f"{config.get('iteration_timeout', 3600)}s per iteration"
    )
    if config.get("check"):
        bounds += f" · whole-flight check <code>{html.escape(str(config['check']))}</code>"
    if config.get("preflight"):
        bounds += " · preflight " + ", ".join(f"<code>{html.escape(str(item))}</code>" for item in config["preflight"])
    parts.append(f"<p class='muted'>{bounds}</p>")
    return "\n".join(parts)


def duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}m"


# -- markdown ------------------------------------------------------------------------


def markdown(text: str, *, base: Path | None = None) -> str:
    """Enough Markdown for agent-written pages: headings, lists, tables, code,
    links, and media. `base` resolves relative image and video paths."""

    out: list[str] = []
    paragraph: list[str] = []
    list_tag: str | None = None
    table: list[str] | None = None
    in_code = False

    def flush() -> None:
        nonlocal paragraph, list_tag, table
        if paragraph:
            out.append("<p>" + _inline(" ".join(paragraph), base) + "</p>")
            paragraph = []
        if list_tag:
            out.append(f"</{list_tag}>")
            list_tag = None
        if table is not None:
            out.append("\n".join(table) + "</table>")
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
            out.append(line.strip())
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)", line)
        if heading:
            flush()
            level = min(len(heading.group(1)) + 1, 6)
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
                table = ["<table>"]
                table.append("<tr>" + "".join(f"<th>{_inline(cell, base)}</th>" for cell in cells) + "</tr>")
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
    return escaped


def _media(alt: str, target: str, base: Path | None) -> str:
    """An image or video, inlined as a data URI when the file is beside the page."""

    caption = f"<figcaption>{html.escape(alt)}</figcaption>" if alt else ""
    path = Path(target)
    if not path.is_absolute() and base is not None:
        path = base / path
    if target.startswith(("http://", "https://", "data:")):
        return f"<figure><img src='{html.escape(target, quote=True)}' alt='{html.escape(alt, quote=True)}'>{caption}</figure>"
    if not path.is_file():
        return f"<p class='open'>Missing media: <code>{html.escape(target)}</code></p>"
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if path.stat().st_size > INLINE_MEDIA_LIMIT:
        return (
            f"<p><a href='{html.escape(path.as_uri(), quote=True)}'>{html.escape(alt or path.name)}</a> "
            f"<span class='muted'>({path.stat().st_size // (1024 * 1024)} MB, not inlined)</span></p>"
        )
    source = f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")
    if path.suffix.lower() in VIDEO_SUFFIXES:
        return f"<figure><video controls src='{source}'></video>{caption}</figure>"
    return f"<figure><img src='{source}' alt='{html.escape(alt, quote=True)}'>{caption}</figure>"
