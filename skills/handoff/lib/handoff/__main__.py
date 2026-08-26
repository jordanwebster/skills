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


SCHEMA_VERSION = 1
DEFAULT_MEDIA_BUDGET = 25 * 1024 * 1024
PLACEHOLDER_PATTERNS = (
    re.compile(r"\b(?:TODO|TBD|FIXME|XXX)\b", re.IGNORECASE),
    re.compile(r"\{\{[^}]+\}\}"),
    re.compile(r"<[^>\n]+>"),
    re.compile(r"\?\?+"),
    re.compile(r"\blorem ipsum\b", re.IGNORECASE),
)
INTERNAL_PATTERNS = (
    re.compile(r"\b(?:task|chunk|dispatch|event|acceptance|evidence)[-_ ]?id\b", re.IGNORECASE),
    re.compile(r"\b(?:dispatch|event) logs?\b", re.IGNORECASE),
    re.compile(r"\.autopilot(?:/|\b)", re.IGNORECASE),
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
    _text_list(bundle.get("decisions", []), "decisions")
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
        lines.extend(f"- {item}" for item in bundle["decisions"])
    output = workspace / "proof.md"
    _atomic_write(output, "\n".join(lines) + "\n")
    return output


def _artifact_html(workspace: Path, artifact: dict[str, Any]) -> str:
    path = workspace / artifact["path"]
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    label = html.escape(artifact.get("label") or path.name)
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    source = f"data:{mime};base64,{encoded}"
    if mime.startswith("image/"):
        return f'<figure><img src="{source}" alt="{label}"><figcaption>{label}</figcaption></figure>'
    if mime.startswith("video/"):
        return f'<figure><video controls src="{source}"></video><figcaption>{label}</figcaption></figure>'
    if mime.startswith("audio/"):
        return f'<figure><audio controls src="{source}"></audio><figcaption>{label}</figcaption></figure>'
    if mime.startswith("text/") or path.suffix.lower() in (".log", ".txt", ".md"):
        content = path.read_text(encoding="utf-8", errors="replace")
        return f"<details><summary>{label}</summary><pre>{html.escape(content)}</pre></details>"
    return f'<p><a download="{html.escape(path.name)}" href="{source}">{label}</a></p>'


def render_page(bundle: dict[str, Any], workspace: Path) -> Path:
    changes = "".join(f"<li>{html.escape(item)}</li>" for item in bundle["changes"])
    proofs: list[str] = []
    descriptions = {item["id"]: item["description"] for item in bundle["accepted_demonstrations"]}
    for claim in bundle["claims"]:
        artifacts = "".join(_artifact_html(workspace, item) for item in claim["artifacts"])
        demonstrations = ", ".join(html.escape(descriptions[item]) for item in claim["demonstrations"])
        proofs.append(
            f"<article><h3>{html.escape(claim['claim'])}</h3>"
            f"<p class=promise>Shows: {demonstrations}</p>{artifacts}"
            f"<p>{html.escape(_replay_text(claim['replay']))}</p>"
            f"<p><strong>Gap:</strong> {html.escape(claim['gap'])}</p></article>"
        )
    review = bundle["review"]
    limitations = review.get("limitations") or []
    review_html = f"<p>{html.escape(review['summary'])}</p><p>Checked by {html.escape(review['reviewer'])}.</p>"
    if limitations:
        review_html += "<p><strong>Review limits:</strong> " + "; ".join(html.escape(item) for item in limitations) + "</p>"
    decisions = bundle.get("decisions") or []
    decisions_html = "".join(f"<li>{html.escape(item)}</li>" for item in decisions) or "<li>No operator decision remains.</li>"
    follow_ups = bundle.get("follow_ups") or []
    follow_html = ""
    if follow_ups:
        follow_html = "<section><h2>Follow-ups</h2><ul>" + "".join(f"<li>{html.escape(item)}</li>" for item in follow_ups) + "</ul></section>"
    document = f"""<!doctype html>
<html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>{html.escape(bundle['title'])}</title><style>
:root{{--ink:#1d2520;--muted:#59665d;--paper:#f5f1e8;--card:#fffdfa;--accent:#155e4a;--line:#d8d1c3}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:17px/1.55 ui-sans-serif,system-ui,sans-serif}}
main{{max-width:920px;margin:auto;padding:64px 28px 96px}}header{{border-bottom:3px solid var(--accent);padding-bottom:24px;margin-bottom:38px}}
h1{{font:700 clamp(2rem,5vw,4rem)/1.02 ui-serif,Georgia,serif;margin:0 0 12px}}h2{{font:700 1.5rem ui-serif,Georgia,serif;margin-top:42px}}
h3{{margin:.1rem 0 .5rem}}.commit,.promise{{color:var(--muted)}}article{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:22px;margin:18px 0;box-shadow:0 5px 18px #423a2d10}}
img,video{{display:block;max-width:100%;max-height:620px;margin:16px auto;border-radius:8px}}audio{{width:100%}}figcaption{{color:var(--muted);font-size:.9rem;text-align:center}}
pre{{overflow:auto;background:#17211c;color:#e7f3eb;padding:16px;border-radius:8px;font-size:.86rem}}code{{font-size:.9em}}li{{margin:.45rem 0}}@media(max-width:600px){{main{{padding:36px 18px 64px}}}}
</style></head><body><main><header><h1>{html.escape(bundle['title'])}</h1><div class=commit>Proof captured at {html.escape(bundle['reviewed_commit'])}</div></header>
<section><h2>What changed</h2><ul>{changes}</ul></section>
<section><h2>Proof</h2>{''.join(proofs)}</section>
<section><h2>Independent review</h2>{review_html}</section>
<section><h2>Over to you</h2><ul>{decisions_html}</ul></section>{follow_html}
</main></body></html>"""
    output = workspace / "handoff.html"
    _atomic_write(output, document)
    return output


def finish(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).expanduser().resolve()
    if not workspace.is_dir():
        raise HandoffError(f"workspace is not a directory: {workspace}")
    bundle, media_bytes = validate(workspace)
    output = render_compact(bundle, workspace) if bundle["mode"] == "compact" else render_page(bundle, workspace)
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
