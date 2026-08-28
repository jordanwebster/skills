"""The ``handoff`` command: validate and render a proof bundle."""

from __future__ import annotations

import argparse
import base64
import html
import json
import mimetypes
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any
import webbrowser

from autopilot import render as operator_page


SCHEMA_VERSION = 1
DEFAULT_MEDIA_BUDGET = 25 * 1024 * 1024
PLACEHOLDER_PATTERNS = (
    re.compile(r"\b(?:TODO|TBD|FIXME|XXX)\b", re.IGNORECASE),
    re.compile(r"\{\{[^}]+\}\}"),
    re.compile(r"\?\?+"),
    re.compile(r"\blorem ipsum\b", re.IGNORECASE),
)
# An unfilled `<placeholder>` is one lowercase word in angle brackets. Anything
# wider caught real prose: a claim may legitimately name Vec<Frame> or
# Result<T, E>, and code spans are exempt outright.
ANGLE_PLACEHOLDER = re.compile(r"<[a-z][a-z0-9_-]*>")
CODE_SPAN = re.compile(r"`[^`]*`")
# How the work was run is never a product fact, so a proof bundle may not carry
# it. Each pattern names a construction that has no ordinary product reading:
# the words themselves stay usable, because a product may well have milestones,
# chunks, tasks, roles, and reviewers of its own.
INTERNAL_PATTERNS = (
    re.compile(r"\b(?:task|chunk|dispatch|event|acceptance|evidence)[-_ ]?id\b", re.IGNORECASE),
    re.compile(r"\b(?:dispatch|event) logs?\b", re.IGNORECASE),
    re.compile(r"\.autopilot(?:/|\b)", re.IGNORECASE),
    # A numbered milestone or chunk is a position in a flight, not a result.
    re.compile(r"\b(?:milestone|chunk)s?\s+#?\d+\b", re.IGNORECASE),
    # These units have no ordinary product reading. Ambiguous counts such as
    # "three tasks" or "three iterations" remain valid product language unless
    # another pattern supplies unmistakable flight context.
    re.compile(r"\b(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|all)\s+"
               r"(?:dispatches|review rounds|fix rounds)\b", re.IGNORECASE),
    re.compile(r"\b(?:dispatches|review rounds|fix rounds)\s+(?:remain|remaining|completed)\b", re.IGNORECASE),
    # Who was staffed on it, and on what.
    re.compile(r"\b(?:planner|implementer|prober|closer|qa[- ]?tester|ui[- ]?developer)\s+"
               r"(?:role|agent|model|persona)s?\b", re.IGNORECASE),
    re.compile(r"\b(?:role|agent|model)\s+(?:signed off|was staffed|staffing)\b", re.IGNORECASE),
)


class HandoffError(RuntimeError):
    """A proof bundle that cannot be safely presented."""


def _required_text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HandoffError(f"{where} must be non-empty text")
    text = value.strip()
    for pattern in PLACEHOLDER_PATTERNS:
        if pattern.search(text):
            raise HandoffError(f"{where} contains an unfinished placeholder")
    if ANGLE_PLACEHOLDER.search(CODE_SPAN.sub(" ", text)):
        raise HandoffError(f"{where} contains an unfinished placeholder")
    return text


def _product_text(value: Any, where: str) -> str:
    text = _required_text(value, where)
    for pattern in INTERNAL_PATTERNS:
        if pattern.search(text):
            raise HandoffError(f"{where} exposes internal workflow vocabulary")
    return text


def _text_list(value: Any, where: str, *, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        suffix = " with at least one item" if not allow_empty else ""
        raise HandoffError(f"{where} must be a list{suffix}")
    return [_product_text(item, f"{where}[{index}]") for index, item in enumerate(value)]


def _decisions(value: Any, where: str) -> list[Any]:
    """A material decision is either its statement or the whole grammar:
    what was chosen, what it was chosen over, and what it cost."""

    if not isinstance(value, list):
        raise HandoffError(f"{where} must be a list")
    for index, item in enumerate(value):
        place = f"{where}[{index}]"
        if isinstance(item, str):
            _product_text(item, place)
            continue
        if not isinstance(item, dict):
            raise HandoffError(f"{place} must be text or an object")
        _product_text(item.get("decision"), f"{place}.decision")
        for field in ("instead_of", "cost"):
            if item.get(field) is not None:
                _product_text(item[field], f"{place}.{field}")
    return value


def _git_head(workspace: Path) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(workspace), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def _artifact_path(workspace: Path, raw: Any, where: str) -> Path:
    relative = Path(_required_text(raw, where))
    if relative.is_absolute() or ".." in relative.parts:
        raise HandoffError(f"{where} must stay inside the proof workspace")
    candidate = workspace / relative
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as error:
        raise HandoffError(f"{where} does not exist: {relative}") from error
    try:
        resolved.relative_to(workspace.resolve())
    except ValueError as error:
        raise HandoffError(f"{where} resolves outside the proof workspace") from error
    if not resolved.is_file():
        raise HandoffError(f"{where} is not a file: {relative}")
    return resolved


def _validate_replay(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise HandoffError(f"{where} must be an object")
    kind = value.get("kind")
    if kind == "command":
        return {"kind": kind, "command": _required_text(value.get("command"), f"{where}.command")}
    if kind == "steps":
        return {"kind": kind, "steps": _text_list(value.get("steps"), f"{where}.steps", allow_empty=False)}
    if kind == "not_replayable":
        return {
            "kind": kind,
            "accepted_reason": _product_text(value.get("accepted_reason"), f"{where}.accepted_reason"),
            "limitation": _product_text(value.get("limitation"), f"{where}.limitation"),
        }
    raise HandoffError(f"{where}.kind must be command, steps, or not_replayable")


def validate(workspace: Path) -> tuple[dict[str, Any], int]:
    source = workspace / "proof.json"
    try:
        bundle = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise HandoffError(f"no proof.json found in {workspace}") from error
    except (OSError, json.JSONDecodeError) as error:
        raise HandoffError(f"cannot read {source}: {error}") from error
    if not isinstance(bundle, dict):
        raise HandoffError("proof.json must contain an object")
    if bundle.get("schema_version") != SCHEMA_VERSION:
        raise HandoffError(f"schema_version must be {SCHEMA_VERSION}")
    mode = bundle.get("mode")
    if mode not in ("compact", "page"):
        raise HandoffError("mode must be compact or page")
    _product_text(bundle.get("title"), "title")
    commit = _required_text(bundle.get("reviewed_commit"), "reviewed_commit")
    head = _git_head(workspace)
    if head and commit != head:
        raise HandoffError(f"proof is for {commit}, but the current commit is {head}")

    accepted = bundle.get("accepted_demonstrations")
    if not isinstance(accepted, list) or not accepted:
        raise HandoffError("accepted_demonstrations must contain at least one item")
    demonstration_ids: set[str] = set()
    for index, demonstration in enumerate(accepted):
        where = f"accepted_demonstrations[{index}]"
        if not isinstance(demonstration, dict):
            raise HandoffError(f"{where} must be an object")
        identifier = _required_text(demonstration.get("id"), f"{where}.id")
        if identifier in demonstration_ids:
            raise HandoffError(f"duplicate accepted demonstration id: {identifier}")
        demonstration_ids.add(identifier)
        _product_text(demonstration.get("description"), f"{where}.description")

    claims = bundle.get("claims")
    if not isinstance(claims, list) or not claims:
        raise HandoffError("claims must contain at least one item")
    covered: set[str] = set()
    media_bytes = 0
    counted_artifacts: set[Path] = set()
    for index, claim in enumerate(claims):
        where = f"claims[{index}]"
        if not isinstance(claim, dict):
            raise HandoffError(f"{where} must be an object")
        _product_text(claim.get("claim"), f"{where}.claim")
        references = claim.get("demonstrations")
        if not isinstance(references, list) or not references:
            raise HandoffError(f"{where}.demonstrations must contain at least one id")
        for item in references:
            identifier = _required_text(item, f"{where}.demonstrations")
            if identifier not in demonstration_ids:
                raise HandoffError(f"{where} references unknown demonstration {identifier!r}")
            covered.add(identifier)
        artifacts = claim.get("artifacts")
        if not isinstance(artifacts, list):
            raise HandoffError(f"{where}.artifacts must be a list")
        for artifact_index, artifact in enumerate(artifacts):
            artifact_where = f"{where}.artifacts[{artifact_index}]"
            if not isinstance(artifact, dict):
                raise HandoffError(f"{artifact_where} must be an object")
            path = _artifact_path(workspace, artifact.get("path"), f"{artifact_where}.path")
            if path not in counted_artifacts:
                counted_artifacts.add(path)
                media_bytes += path.stat().st_size
            if artifact.get("kind") is not None:
                _required_text(artifact["kind"], f"{artifact_where}.kind")
            if artifact.get("label") is not None:
                _product_text(artifact["label"], f"{artifact_where}.label")
        gap = _product_text(claim.get("gap"), f"{where}.gap")
        if not artifacts and gap.casefold() == "none":
            raise HandoffError(f"{where} claims complete coverage but has no artifact")
        _validate_replay(claim.get("replay"), f"{where}.replay")

    missing = demonstration_ids - covered
    if missing:
        descriptions = {item["id"]: item["description"] for item in accepted if isinstance(item, dict)}
        names = ", ".join(descriptions.get(identifier, identifier) for identifier in sorted(missing))
        raise HandoffError(f"accepted demonstrations lack proof coverage: {names}")

    _text_list(bundle.get("changes"), "changes", allow_empty=False)
    _decisions(bundle.get("decisions", []), "decisions")
    _text_list(bundle.get("follow_ups", []), "follow_ups")

    if mode == "page":
        review = bundle.get("review")
        if not isinstance(review, dict):
            raise HandoffError("page mode requires review")
        _product_text(review.get("reviewer"), "review.reviewer")
        review_commit = _required_text(review.get("reviewed_commit"), "review.reviewed_commit")
        if review_commit != commit:
            raise HandoffError("independent review is stale for the proof commit")
        _product_text(review.get("summary"), "review.summary")
        _text_list(review.get("limitations", []), "review.limitations")

    try:
        budget = int(os.environ.get("HANDOFF_MEDIA_BUDGET_BYTES", DEFAULT_MEDIA_BUDGET))
    except ValueError as error:
        raise HandoffError("HANDOFF_MEDIA_BUDGET_BYTES must be an integer") from error
    if media_bytes > budget:
        raise HandoffError(f"evidence uses {media_bytes} bytes; cumulative media budget is {budget}")
    return bundle, media_bytes


def _atomic_write(path: Path, content: str) -> None:
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _replay_text(replay: dict[str, Any]) -> str:
    kind = replay["kind"]
    if kind == "command":
        return f"Replay: `{replay['command']}`"
    if kind == "steps":
        return "Replay: " + " → ".join(replay["steps"])
    return f"Not replayable: {replay['accepted_reason']} Limitation: {replay['limitation']}"


def _artifact_markdown(artifact: dict[str, Any]) -> str:
    path = artifact["path"]
    label = artifact.get("label") or Path(path).name
    mime = mimetypes.guess_type(path)[0] or ""
    if mime.startswith("image/"):
        return f"![{label}]({path})"
    return f"[{label}]({path})"


def render_compact(bundle: dict[str, Any], workspace: Path) -> Path:
    lines = [f"# {bundle['title']}", "", "## What changed", ""]
    lines.extend(f"- {change}" for change in bundle["changes"])
    lines.extend(["", "## Proof", ""])
    for claim in bundle["claims"]:
        lines.append(f"- **{claim['claim']}**")
        captures = [_artifact_markdown(artifact) for artifact in claim["artifacts"]]
        lines.append(f"  Evidence: {', '.join(captures) if captures else 'none captured'}")
        lines.append(f"  {_replay_text(claim['replay'])}")
        lines.append(f"  Gap: {claim['gap']}")
    if bundle.get("decisions"):
        lines.extend(["", "## Decisions", ""])
        lines.extend(
            f"- {item if isinstance(item, str) else item['decision']}"
            for item in bundle["decisions"]
        )
    output = workspace / "proof.md"
    _atomic_write(output, "\n".join(lines) + "\n")
    return output


def _git_context(workspace: Path) -> tuple[str, str]:
    """Repository name and branch for the masthead's derived line."""

    def run(*arguments: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(workspace), *arguments],
            capture_output=True, text=True, check=False,
        )
        return completed.stdout.strip() if completed.returncode == 0 else ""

    toplevel = run("rev-parse", "--show-toplevel")
    return (Path(toplevel).name if toplevel else "", run("rev-parse", "--abbrev-ref", "HEAD"))


TEXT_SUFFIXES = (".log", ".txt", ".md", ".diff", ".patch", ".out")
# A transcript longer than this is machinery to consult, not evidence to read
# on the way to a decision, so it goes behind a disclosure.
INLINE_TEXT_LINES = 20


def _artifact_view(workspace: Path, artifact: dict[str, Any]) -> dict[str, Any]:
    """One captured artifact, classified by how the operator should meet it."""

    path = workspace / artifact["path"]
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    label = artifact.get("label") or ""
    caption = html.escape(label or path.name)
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    source = f"data:{mime};base64,{encoded}"
    if mime.startswith("image/"):
        alt = html.escape(label or path.name, quote=True)
        return {"placement": "card", "html": (
            f'<figure><img src="{source}" alt="{alt}"><figcaption>{caption}</figcaption></figure>'
        )}
    if mime.startswith("video/"):
        return {"placement": "card", "html": (
            f'<figure><video controls src="{source}"></video><figcaption>{caption}</figcaption></figure>'
        )}
    if mime.startswith("audio/"):
        return {"placement": "card", "html": (
            f'<figure><audio controls src="{source}"></audio><figcaption>{caption}</figcaption></figure>'
        )}
    if mime.startswith("text/") or path.suffix.lower() in TEXT_SUFFIXES:
        content = path.read_text(encoding="utf-8", errors="replace")
        lines = content.count("\n") + 1
        body = f"<pre>{html.escape(content)}</pre>"
        if lines <= INLINE_TEXT_LINES:
            return {"placement": "card", "html": f"<figure>{body}<figcaption>{caption}</figcaption></figure>"}
        return {"placement": "card", "html": operator_page.disclosure(
            f"{label or path.name} ({lines} lines)", body,
            variant="inline dis--evidence", static_print=True,
        )}
    return {
        "placement": "appendix",
        "bytes": path.stat().st_size,
        "html": (
            f'<p><a download="{html.escape(path.name)}" href="{source}">{caption}</a> '
            f"({path.stat().st_size // 1024} KB)</p>"
        ),
    }


COVERAGE_MARKS = {
    "proved": ("\u25cf", "Proved", "ok"),
    "limited": ("\u25d0", "Proved with limits", "caution"),
    "unproved": ("\u25cb", "Not proved", "alert"),
}


def _coverage(claim: dict[str, Any]) -> str:
    """What the evidence actually establishes about one claim."""

    if not claim["artifacts"]:
        return "unproved"
    if claim["gap"].strip().casefold() != "none":
        return "limited"
    if claim["replay"]["kind"] == "not_replayable":
        return "limited"
    return "proved"


def _clause(text: str) -> str:
    return text.strip().rstrip(".")


def _join_clauses(parts: list[str]) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return singular if count == 1 else (plural or singular + "s")


def verdict_of(bundle: dict[str, Any]) -> dict[str, Any]:
    """Derive the verdict, the ask, and the exposure. Nobody authors a slogan."""

    claims = bundle["claims"]
    states = [_coverage(claim) for claim in claims]
    limitations = (bundle.get("review") or {}).get("limitations") or []
    gaps = [claim for claim in claims if claim["gap"].strip().casefold() != "none"]
    unreplayable = [
        claim for claim, state in zip(claims, states)
        if state == "limited" and claim["replay"]["kind"] == "not_replayable"
        and claim["gap"].strip().casefold() == "none"
    ]

    if "unproved" in states:
        missing = states.count("unproved")
        first = next(claim for claim, state in zip(claims, states) if state == "unproved")
        key, word = "not-decidable", "Not decidable from this evidence"
        ask = f"Do not merge yet: {_clause(first['gap'])}."
        lead = (
            f"{missing} of {len(claims)} {_plural(len(claims), 'claim')} "
            f"{_plural(missing, 'is', 'are')} not shown by the evidence supplied."
        )
    elif gaps or unreplayable or limitations:
        key, word = "holds-with-limits", "Holds with limits"
        if gaps:
            strongest = _clause(gaps[0]["gap"])
        elif unreplayable:
            strongest = _clause(unreplayable[0]["replay"]["limitation"])
        else:
            strongest = _clause(limitations[0])
        ask = f"Merge knowing: {strongest}."
        lead = "Every claim has supporting evidence."
    else:
        key, word = "holds", "Holds"
        ask = "Merge this work."
        lead = "Everything promised is shown, and the review reports no limitation."

    qualifiers: list[str] = []
    if gaps:
        qualifiers.append(
            f"{len(gaps)} {_plural(len(gaps), 'claim')} "
            f"{_plural(len(gaps), 'carries', 'carry')} a stated gap"
        )
    if unreplayable:
        qualifiers.append(
            f"{len(unreplayable)} {_plural(len(unreplayable), 'capture')} cannot be replayed locally"
        )
    if limitations:
        qualifiers.append(
            f"the review did not cover {len(limitations)} {_plural(len(limitations), 'area')}"
        )
    if qualifiers:
        lead = _clause(lead) + ", but " + _join_clauses(qualifiers) + "."

    short = bundle["reviewed_commit"][:7]
    exposure = (
        f"{len(gaps)} {_plural(len(gaps), 'gap')} · "
        f"{len(limitations)} review {_plural(len(limitations), 'limitation')} · "
        f"reviewed at {short}"
    )
    glyph, _, role = COVERAGE_MARKS[
        "proved" if key == "holds" else ("limited" if key == "holds-with-limits" else "unproved")
    ]
    return {
        "key": key, "word": word, "glyph": glyph, "role": role,
        "ask": ask, "lead": lead, "exposure": exposure, "states": states,
        "gaps": len(gaps), "limitations": len(limitations),
    }


def _decision_row(item: Any) -> dict[str, str]:
    if isinstance(item, str):
        return {"thing": item}
    derived = []
    if item.get("instead_of"):
        derived.append("Chosen over " + _clause(item["instead_of"]))
    if item.get("cost"):
        derived.append("costs " + _clause(item["cost"]))
    return {"thing": item["decision"], "default": " · ".join(derived)}


def render_page(bundle: dict[str, Any], workspace: Path) -> Path:
    descriptions = {item["id"]: item["description"] for item in bundle["accepted_demonstrations"]}
    review = bundle["review"]
    limitations = review.get("limitations") or []
    verdict = verdict_of(bundle)

    rows: list[dict[str, Any]] = []
    appendix: list[dict[str, Any]] = []
    for claim, state in zip(bundle["claims"], verdict["states"]):
        glyph, word, role = COVERAGE_MARKS[state]
        card_evidence: list[str] = []
        for artifact in claim["artifacts"]:
            view = _artifact_view(workspace, artifact)
            if view["placement"] == "card":
                card_evidence.append(view["html"])
            else:
                appendix.append(view)
        gap = claim["gap"].strip()
        stated = "No gap." if gap.casefold() == "none" else gap
        margin = ['<p><span class="lab">Shows</span>' + "; ".join(
            html.escape(descriptions[item]) for item in claim["demonstrations"]
        ) + "</p>"]
        replay = claim["replay"]
        if replay["kind"] == "not_replayable":
            margin.append(
                "<p>Not replayable — " + html.escape(_clause(replay["accepted_reason"])) + ".</p>"
            )
        else:
            margin.append(operator_page.disclosure(
                "Replay", f"<pre>{html.escape(_replay_recipe(replay))}</pre>",
            ))
        rows.append({
            "claim": claim["claim"],
            "coverage": state,
            "mark": operator_page.marker(glyph, word, role=role),
            "gap_html": (
                '<p class="claim__gap"><span class="lab">Gap</span>'
                + html.escape(stated) + "</p>"
            ),
            "evidence_html": "".join(card_evidence),
            "margin": margin,
        })

    name, branch = _git_context(workspace)
    content = [operator_page.decision(
        f'<p>{operator_page.marker(verdict["glyph"], verdict["word"], role=verdict["role"])}</p>'
        f'<p>{html.escape(verdict["lead"])}</p>',
        ask_label="You decide",
        ask=verdict["ask"],
        default="No merge, no publication",
        exposure=verdict["exposure"],
        variant="accept",
    )]
    content.append(operator_page.section(
        "What changed",
        "<ul>" + "".join(f"<li>{html.escape(item)}</li>" for item in bundle["changes"]) + "</ul>",
        anchor="changed",
    ))
    content.append(operator_page.section(
        "Independent review",
        operator_page.verdict_panel(
            summary=review["summary"],
            attribution=f"Reviewed at {bundle['reviewed_commit'][:7]} by {review['reviewer']}.",
            limitations=limitations,
        ),
        anchor="review",
    ))
    content.append(operator_page.section("Proof", operator_page.claim_cards(rows), anchor="proof"))
    content.append(operator_page.section(
        "Decisions taken",
        operator_page.decision_rows(
            [_decision_row(item) for item in bundle.get("decisions") or []], variant="taken"
        ),
        anchor="decisions",
    ))
    content.append(operator_page.section(
        "Follow-ups",
        operator_page.decision_rows(
            [{"thing": item} for item in bundle.get("follow_ups") or []],
            variant="followup",
            caption="Does not affect this decision",
        ),
        anchor="follow-ups",
    ))
    if appendix:
        total = sum(item["bytes"] for item in appendix)
        content.append(
            '<div class="diagnostics">' + operator_page.disclosure(
                f"Evidence appendix ({len(appendix)} "
                f"{_plural(len(appendix), 'file')}, {total // 1024} KB)",
                "".join(item["html"] for item in appendix),
                variant="block dis--evidence", static_print=True,
            ) + "</div>"
        )
    content.append(
        '<section class="closing" aria-labelledby="closing-heading">'
        '<h2 class="vh" id="closing-heading">The ask</h2>'
        + operator_page.decision_rows(
            [{"thing": verdict["ask"], "default": "Default: no merge, no publication."}],
            variant="taken",
        )
        + "</section>"
    )

    document = operator_page.document(
        bundle["title"],
        "\n".join(part for part in content if part),
        surface="Handoff · merge decision",
        meta=operator_page.meta_line(
            name, branch, bundle["reviewed_commit"][:7], operator_page.today()
        ),
        style=operator_page.HANDOFF_STYLE,
        verdict=verdict["key"],
    )
    output = workspace / "handoff.html"
    _atomic_write(output, document)
    return output


def _replay_recipe(replay: dict[str, Any]) -> str:
    if replay["kind"] == "command":
        return replay["command"]
    return " → ".join(replay["steps"])


def finish(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).expanduser().resolve()
    if not workspace.is_dir():
        raise HandoffError(f"workspace is not a directory: {workspace}")
    bundle, media_bytes = validate(workspace)
    output = render_compact(bundle, workspace) if bundle["mode"] == "compact" else render_page(bundle, workspace)
    if bundle["mode"] == "page":
        result_verdict = verdict_of(bundle)["key"]
    if bundle["mode"] == "page" and not args.no_open:
        webbrowser.open(output.as_uri())
    gaps = sum(1 for claim in bundle["claims"] if claim["gap"].strip().casefold() != "none")
    next_action = "Review the proof and decide whether to accept the result."
    result = {
        "schema_version": SCHEMA_VERSION,
        "status": "ready",
        "mode": bundle["mode"],
        "workspace": str(workspace),
        "output": str(output),
        "reviewed_commit": bundle["reviewed_commit"],
        "media_bytes": media_bytes,
        "gaps": gaps,
        "next_action": next_action,
    }
    if bundle["mode"] == "page":
        result["verdict"] = result_verdict
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        label = "Decision page" if bundle["mode"] == "page" else "Compact proof"
        print(f"{label}: {output}")
        print(f"Evidence: {len(bundle['claims'])} claims, {gaps} gaps, {media_bytes} bytes")
        print(f"Next: {next_action}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="handoff", description="Validate and present proof of finished work.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    parser_finish = subparsers.add_parser("finish", help="validate proof.json and render its operator surface")
    parser_finish.add_argument("workspace", help="directory containing proof.json and its evidence")
    parser_finish.add_argument("--json", action="store_true", help="machine-readable result")
    parser_finish.add_argument("--no-open", action="store_true", help="do not open a rendered decision page")
    parser_finish.set_defaults(handler=finish)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except HandoffError as error:
        recovery = "Correct proof.json or its referenced artifacts, then run handoff finish again."
        if getattr(args, "json", False):
            print(json.dumps({
                "schema_version": SCHEMA_VERSION,
                "status": "error",
                "error": {"class": "invalid_work", "message": str(error), "recovery": recovery},
            }, indent=2, sort_keys=True))
        else:
            print(f"handoff: {error}", file=sys.stderr)
            print(f"Recovery: {recovery}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
