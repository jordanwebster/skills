"""Structural validation and narrow confirmation receipts for Intake."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from . import SCHEMA_VERSION


class ContractError(ValueError):
    """A durable acceptance contract is incomplete or malformed."""

    def __init__(self, code: str, message: str, recovery: str):
        super().__init__(message)
        self.code = code
        self.recovery = recovery


@dataclass
class Item:
    identifier: str
    text: str
    fields: dict[str, str] = field(default_factory=dict)


@dataclass
class Contract:
    path: Path
    content: bytes
    sections: dict[str, list[str]]

    @property
    def digest(self) -> str:
        return f"sha256:{hashlib.sha256(self.content).hexdigest()}"


REQUIRED_SECTIONS = (
    "Goal",
    "Observable expectations",
    "Exclusions",
    "Acceptance scenarios",
    "Material decisions",
    "Accepted gaps",
    "Exceptional operator acts",
    "Waivers",
    "Confirmation",
)
PLACEHOLDER = re.compile(
    r"<[^>\n]+>|\b(?:TODO|TBD|PENDING|expectation-id|scenario-id|decision-id)\b|\[\s*\]",
    re.IGNORECASE,
)
COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
ITEM = re.compile(
    r"^\s*-\s+(.+?)\s+<!--\s*id:\s*([a-z0-9][a-z0-9-]*)"
    r"(?:\s*;\s*covers:\s*([a-z0-9, -]+))?\s*-->\s*$"
)
FIELD = re.compile(r"^\s{2,}-\s+([A-Za-z][A-Za-z ]*):\s*(.*?)\s*$")


def read_contract(path: str | Path) -> Contract:
    selected = Path(path).expanduser().resolve()
    try:
        content = selected.read_bytes()
    except OSError as error:
        raise ContractError(
            "contract_unreadable",
            f"cannot read acceptance contract {selected}: {error}",
            "Provide the path to the confirmed acceptance contract.",
        ) from error
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ContractError(
            "invalid_contract",
            f"acceptance contract {selected} is not UTF-8 text",
            "Save the contract as UTF-8 Markdown and finalize it again.",
        ) from error
    sections = _sections(text)
    _validate(selected, text, sections)
    return Contract(selected, content, sections)


def finalize(path: str | Path) -> tuple[Contract, Path, dict[str, object]]:
    contract = read_contract(path)
    confirmed_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    receipt: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "contract_digest": contract.digest,
        "confirmed_at": confirmed_at,
    }
    receipt_path = contract.path.with_name(contract.path.name + ".acceptance.json")
    _write_json_atomic(receipt_path, receipt)
    return contract, receipt_path, receipt


def _sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            if current in sections:
                raise ContractError(
                    "invalid_contract",
                    f"acceptance contract repeats section {current!r}",
                    "Keep exactly one copy of every required section.",
                )
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return sections


def _validate(path: Path, text: str, sections: dict[str, list[str]]) -> None:
    missing = [name for name in REQUIRED_SECTIONS if name not in sections]
    if missing:
        raise ContractError(
            "invalid_contract",
            f"acceptance contract {path} is missing: {', '.join(missing)}",
            "Start from the bundled requirements.md template and complete every section.",
        )
    placeholder = PLACEHOLDER.search(COMMENT.sub("", text)) or re.search(
        r"\b(?:expectation-id|scenario-id|decision-id)\b", text, re.IGNORECASE
    )
    if placeholder:
        raise ContractError(
            "unfinished_contract",
            f"acceptance contract contains unfinished marker {placeholder.group(0)!r}",
            "Resolve unfinished placeholders and decisions before asking for final confirmation.",
        )
    goal = " ".join(line.strip() for line in sections["Goal"] if line.strip())
    if not goal:
        raise ContractError(
            "invalid_contract", "acceptance contract has no goal", "State the goal in the operator's language."
        )

    expectations = _items(sections["Observable expectations"], "Observable expectations", allow_none=False)
    exclusions = _items(sections["Exclusions"], "Exclusions", allow_none=True)
    scenarios = _items(sections["Acceptance scenarios"], "Acceptance scenarios", allow_none=False)
    decisions = _items(sections["Material decisions"], "Material decisions", allow_none=True)
    gaps = _items(sections["Accepted gaps"], "Accepted gaps", allow_none=True)
    operator_acts = _items(
        sections["Exceptional operator acts"], "Exceptional operator acts", allow_none=True
    )
    _items(sections["Waivers"], "Waivers", allow_none=True)

    all_expectations = expectations + exclusions
    expectation_ids = {item.identifier for item in all_expectations}
    if len(expectation_ids) != len(all_expectations):
        raise ContractError(
            "invalid_contract", "observable expectation IDs are not unique", "Give every expectation a unique ID."
        )

    covered: set[str] = set()
    for scenario in scenarios:
        _require_fields(scenario, "Acceptance scenarios", ("covers", "demonstration", "limitation"))
        covered.update(_coverage(scenario, expectation_ids, "scenario"))
    for gap in gaps:
        _require_fields(gap, "Accepted gaps", ("covers", "limitation"))
        covered.update(_coverage(gap, expectation_ids, "gap"))
    for act in operator_acts:
        _require_fields(act, "Exceptional operator acts", ("trigger", "request", "cost"))
    uncovered = sorted(expectation_ids - covered)
    if uncovered:
        raise ContractError(
            "uncovered_expectations",
            f"acceptance expectations lack a scenario or accepted gap: {', '.join(uncovered)}",
            "Cover each expectation with at least one scenario, or record an explicit accepted gap.",
        )

    for decision in decisions:
        _require_fields(decision, "Material decisions", ("decision", "blast radius", "provenance", "resolution"))
        provenance = decision.fields["provenance"].casefold()
        resolution = decision.fields["resolution"].casefold()
        if provenance not in {"operator-stated", "agent-proposed"}:
            raise ContractError(
                "invalid_contract",
                f"decision {decision.identifier!r} has invalid provenance {provenance!r}",
                "Use operator-stated or agent-proposed provenance.",
            )
        if resolution not in {"confirmed", "vetoed"}:
            raise ContractError(
                "unresolved_decision",
                f"material decision {decision.identifier!r} is not confirmed or vetoed",
                "Record the operator's explicit resolution before finalizing.",
            )
        if provenance == "agent-proposed" and resolution == "vetoed":
            replacement = decision.fields.get("replacement", "").strip()
            if not replacement:
                raise ContractError(
                    "unmarked_expansion",
                    f"vetoed agent proposal {decision.identifier!r} has no replacement",
                    "Remove the expansion or record the operator's replacement.",
                )

    confirmation = " ".join(line.strip() for line in sections["Confirmation"] if line.strip())
    if not re.search(r"\bFinal all-ok:\s*CONFIRMED\b", confirmation, re.IGNORECASE):
        raise ContractError(
            "confirmation_missing",
            "acceptance contract does not record the operator's final all-ok",
            "After the operator confirms the complete recap, set 'Final all-ok: CONFIRMED'.",
        )


def _items(lines: list[str], section: str, *, allow_none: bool) -> list[Item]:
    meaningful = [
        line for line in lines if line.strip() and not line.strip().startswith("<!--")
    ]
    if allow_none and len(meaningful) == 1 and re.match(r"^\s*-\s+None\.?\s*$", meaningful[0], re.IGNORECASE):
        return []
    items: list[Item] = []
    current: Item | None = None
    for line in meaningful:
        match = ITEM.match(line)
        if match:
            fields = {"covers": match.group(3).strip()} if match.group(3) else {}
            current = Item(match.group(2), match.group(1).strip(), fields)
            items.append(current)
            continue
        field_match = FIELD.match(line)
        if field_match and current is not None:
            key = field_match.group(1).strip().casefold()
            if key in current.fields:
                raise ContractError(
                    "invalid_contract",
                    f"{section} item {current.identifier!r} repeats field {key!r}",
                    f"Keep one {key} field on that item.",
                )
            current.fields[key] = field_match.group(2).strip()
            continue
        raise ContractError(
            "invalid_contract",
            f"cannot parse line in {section}: {line.strip()!r}",
            "Use subject bullets with hidden ID metadata and indented fields from the bundled template.",
        )
    if not items:
        raise ContractError(
            "invalid_contract",
            f"{section} must contain {'an item or None' if allow_none else 'at least one item'}",
            "Complete the section using the bundled template.",
        )
    identifiers = [item.identifier for item in items]
    if len(set(identifiers)) != len(identifiers):
        raise ContractError(
            "invalid_contract", f"{section} IDs are not unique", f"Give every {section.lower()} item a unique ID."
        )
    return items


def _require_fields(item: Item, section: str, fields: tuple[str, ...]) -> None:
    missing = [name for name in fields if not item.fields.get(name)]
    if missing:
        raise ContractError(
            "invalid_contract",
            f"{section} item {item.identifier!r} is missing: {', '.join(missing)}",
            "Complete the item using the bundled template.",
        )


def _coverage(item: Item, expectation_ids: set[str], kind: str) -> set[str]:
    referenced = {value.strip() for value in item.fields["covers"].split(",") if value.strip()}
    unknown = sorted(referenced - expectation_ids)
    if not referenced or unknown:
        detail = "no expectation IDs" if not referenced else f"unknown IDs: {', '.join(unknown)}"
        raise ContractError(
            "invalid_coverage",
            f"{kind} {item.identifier!r} covers {detail}",
            "List comma-separated IDs from Observable expectations.",
        )
    return referenced


def _write_json_atomic(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True) + "\n"
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            handle.write(payload)
            temporary = Path(handle.name)
        os.replace(temporary, path)
    except OSError as error:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass
        raise ContractError(
            "receipt_write_failed",
            f"cannot write acceptance receipt {path}: {error}",
            "Make the contract directory writable and finalize again.",
        ) from error
