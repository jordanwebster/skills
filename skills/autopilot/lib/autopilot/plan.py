"""Read the flight plan's machine block and seed the task list from it.

The plan is one Markdown file the planner writes and the operator reads as
a rendered page. Its prose is for the operator; the single fenced block
opened with ```flight-plan holds the JSON the loop reads. The page renders
that block as tables, so what the operator approved and what the loop
seeds cannot drift apart.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, NamedTuple

from .state import Flight, StateError


PLAN_FENCE = "```flight-plan"

KNOWN_ROLES = ("planner", "implementer", "ui-developer", "prober", "qa-tester", "reviewer", "closer")


class PlanError(ValueError):
    """Raised when the plan has no usable machine block."""


def read_plan(path: str | Path) -> dict[str, Any]:
    """Return the plan's machine block, validated enough to seed a flight."""

    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as error:
        raise PlanError(f"cannot read plan {source}: {error}") from error
    blocks = plan_blocks(text)
    if len(blocks) != 1:
        raise PlanError(
            f"plan must contain exactly one {PLAN_FENCE} block, found {len(blocks)}"
        )
    try:
        plan = json.loads(blocks[0])
    except json.JSONDecodeError as error:
        raise PlanError(f"plan block is not valid JSON: {error}") from error
    validated = _validate(plan)
    validated["_operator"] = _operator_contract(text, validated)
    return validated


def plan_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    buffer: list[str] | None = None
    for line in text.splitlines():
        if buffer is None:
            if line.strip() == PLAN_FENCE:
                buffer = []
        elif line.strip() == "```":
            blocks.append("\n".join(buffer))
            buffer = None
        else:
            buffer.append(line)
    return blocks


def plan_roles(plan: dict[str, Any]) -> list[str]:
    """Every role the plan will dispatch, in first-use order."""

    roles: list[str] = []

    def add(role: str | None) -> None:
        if role and role not in roles:
            roles.append(role)

    add("planner")
    for chunk in plan["chunks"]:
        add(chunk.get("role") or "implementer")
    for task in plan["tasks"]:
        add(task.get("role"))
    if any(chunk.get("review") is not False for chunk in plan["chunks"]):
        add("reviewer")
    add("closer")
    return roles


def plan_bindings(plan: dict[str, Any]) -> list[tuple[str, str | None]]:
    """Every actual role-effort combination a flight may dispatch."""

    combinations: list[tuple[str, str | None]] = []

    def add(role: str, effort: str | None = None) -> None:
        value = (role, effort or None)
        if value not in combinations:
            combinations.append(value)

    add("planner")
    chunks = {chunk["id"]: chunk for chunk in plan["chunks"]}
    for chunk in plan["chunks"]:
        add(chunk.get("role") or "implementer", chunk.get("effort"))
    for task in plan["tasks"]:
        chunk = chunks[task["chunk"]]
        add(task.get("role") or chunk.get("role") or "implementer", task.get("effort") or chunk.get("effort"))
    for chunk in plan["chunks"]:
        if chunk.get("review") is not False:
            add("reviewer", chunk.get("review_effort"))
    add("closer", plan.get("config", {}).get("closer_effort"))
    return combinations


def _validate(plan: Any) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise PlanError("plan block must be a JSON object")
    goal = plan.get("goal")
    if not isinstance(goal, str) or not goal.strip():
        raise PlanError("plan needs a non-empty goal")
    chunks = plan.get("chunks")
    tasks = plan.get("tasks")
    if not isinstance(chunks, list) or not chunks:
        raise PlanError("plan needs at least one chunk")
    if not isinstance(tasks, list) or not tasks:
        raise PlanError("plan needs at least one task")
    config = plan.get("config", {})
    if not isinstance(config, dict):
        raise PlanError("plan config must be an object")
    ceiling = config.get("max_iterations")
    expected = config.get("expected_iterations")
    if not isinstance(ceiling, int) or isinstance(ceiling, bool) or ceiling < 1:
        raise PlanError("plan config.max_iterations must be a positive integer")
    if (
        not isinstance(expected, dict)
        or set(expected) != {"min", "max"}
        or any(not isinstance(expected.get(key), int) or isinstance(expected.get(key), bool) for key in ("min", "max"))
        or expected["min"] < 1
        or expected["min"] > expected["max"]
        or expected["max"] > ceiling
    ):
        raise PlanError(
            "plan config.expected_iterations must be {min,max} with 1 <= min <= max <= max_iterations"
        )
    preflight = config.get("preflight", [])
    if not isinstance(preflight, list) or any(not isinstance(item, str) for item in preflight):
        raise PlanError("plan config.preflight must be a list of shell commands")
    evidence = plan.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise PlanError("plan needs at least one evidence item")
    evidence_ids: set[str] = set()
    for item in evidence:
        _require_fields(item, "evidence item", ("id", "claim", "demonstrations", "artifacts", "replay", "stages"))
        if not isinstance(item["id"], str) or not item["id"].strip() or item["id"] in evidence_ids:
            raise PlanError("evidence ids must be unique non-empty strings")
        evidence_ids.add(item["id"])
        if (
            not isinstance(item["stages"], list)
            or not item["stages"]
            or any(not isinstance(value, int) or isinstance(value, bool) for value in item["stages"])
        ):
            raise PlanError(f"evidence item {item['id']!r} stages must be a non-empty integer list")
        for field in ("demonstrations", "artifacts"):
            if not isinstance(item[field], list) or not item[field] or any(not isinstance(value, str) or not value for value in item[field]):
                raise PlanError(f"evidence item {item['id']!r} {field} must be a non-empty string list")
        replay = item["replay"]
        if not isinstance(replay, dict) or replay.get("kind") not in ("command", "steps", "not_replayable"):
            raise PlanError(f"evidence item {item['id']!r} has an invalid replay recipe")
        if replay["kind"] == "command" and not isinstance(replay.get("command"), str):
            raise PlanError(f"evidence item {item['id']!r} command replay needs command")
        if replay["kind"] == "steps" and (not isinstance(replay.get("steps"), list) or not replay["steps"]):
            raise PlanError(f"evidence item {item['id']!r} steps replay needs steps")
        if replay["kind"] == "not_replayable" and (
            not isinstance(replay.get("accepted_reason"), str)
            or not replay["accepted_reason"].strip()
            or not isinstance(replay.get("limitation"), str)
            or not replay["limitation"].strip()
        ):
            raise PlanError(
                f"evidence item {item['id']!r} not_replayable needs accepted_reason and limitation"
            )

    chunk_ids: set[int] = set()
    for chunk in chunks:
        _require_fields(chunk, "chunk", ("id", "title"))
        if not isinstance(chunk["id"], int) or chunk["id"] in chunk_ids:
            raise PlanError(f"chunk ids must be unique integers (chunk {chunk.get('id')!r})")
        chunk_ids.add(chunk["id"])
    task_ids: set[int] = set()
    for task in tasks:
        _require_fields(task, "task", ("id", "chunk", "title"))
        if not isinstance(task["id"], int) or task["id"] in task_ids:
            raise PlanError(f"task ids must be unique integers (task {task.get('id')!r})")
        if task["chunk"] not in chunk_ids:
            raise PlanError(f"task {task['id']} names unknown chunk {task['chunk']}")
        task_ids.add(task["id"])
    for task in tasks:
        for dependency in task.get("depends_on", []):
            if dependency not in task_ids:
                raise PlanError(f"task {task['id']} depends on unknown task {dependency}")
    for item in evidence:
        unknown = [stage for stage in item["stages"] if stage not in chunk_ids]
        if unknown:
            raise PlanError(f"evidence item {item['id']!r} names unknown stage {unknown[0]}")
    return plan


_SECTION = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_TITLE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_ROUTE = re.compile(r"^###\s+(?:Milestone|Stage)\s+(\d+)(?:\s*[\u2014:\u2013-]\s*(.+?))?\s*$", re.MULTILINE)
_ROUTE_FIELD = re.compile(
    r"^[-*]\s+\*\*(Produces|Unlocks|Validated by|Branch|Enables):\*\*\s*(.*)$",
    re.IGNORECASE,
)
_SUB_BULLET = re.compile(r"^\s+[-*]\s+(.*?)\s*$")
_OUTCOME = re.compile(r"^(?:If\s+)?(?P<text>.+?)\s*(?:\u2192|->)\s*(?P<then>.+?)\s*$", re.IGNORECASE)
_DEFAULT_SUFFIX = re.compile(r"\s*\((?:the\s+)?default\)\s*$", re.IGNORECASE)
_MILESTONE_REFERENCE = re.compile(r"\bM(\d+)\b")
_DEFINITION_SPLIT = re.compile(r"\s+(?:\u2014|\u2013|--)\s+")

# The title is the page's h1 and the operator's only handle on the flight
# three weeks later, so it stays one readable line.
TITLE_BUDGET = 70
# A stage field longer than this has stopped being a causal statement and
# has become an essay; the template asks for 220 characters.
STAGE_FIELD_LIMIT = 400
# The vocabulary a test-infrastructure milestone must use to say what its
# capability is worth. Without one of these, "Enables" says nothing.
CAPABILITY_WORDS = ("fast", "offline", "deterministic", "isolated")
REQUIRED_STAGE_FIELDS = ("produces", "unlocks", "validated by")


_SHAPE_GROUP = re.compile(r"^#{3,6}[ \t]+([^\n]+?)[ \t]*$", re.MULTILINE)
_SHAPE_ENTRY = re.compile(r"^\s*[-*]\s+(.*)$")
_SHAPE_SPLIT = re.compile(r"\s+(?:—|–|--)\s+")
_SHAPE_CODE = re.compile(r"^```([\w+#.-]*)[^\n]*\n(.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL)
_SHAPE_NOTE = re.compile(r"\s+(?:—|–|--)\s+")


class ShapeGroup(NamedTuple):
    """One component's surface: its name, what it owns, and what it exposes."""

    name: str
    note: str
    entries: list[tuple[str, str]]
    language: str
    code: str

    def __bool__(self) -> bool:
        return bool(self.entries or self.code)


def _mask_fences(source: str) -> str:
    """The source with fenced code blanked out, keeping every offset.

    A group heading is found on the masked copy so that a `### ` inside a code
    block — a comment in a shell or Python signature — is read as code rather
    than as a new group."""

    masked = list(source)
    for match in _SHAPE_CODE.finditer(source):
        for index in range(match.start(), match.end()):
            if masked[index] != "\n":
                masked[index] = "x"
    return "".join(masked)


def shape_groups(source: str) -> list[ShapeGroup]:
    """The Shape section as named groups.

    A group is a sub-heading. Its body is either bullets — each split on an em
    dash into the thing and what it is — or a fenced code block, which is how
    an interface is written: a signature is code, and prose that describes a
    signature instead of showing it is prose the reader has to compile. Groups
    with neither are not groups."""

    masked = _mask_fences(source)
    matches = list(_SHAPE_GROUP.finditer(masked))
    if not matches:
        return []
    groups: list[ShapeGroup] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(source)
        body = source[match.end():end]
        name = match.group(1).strip()

        fence = _SHAPE_CODE.search(body)
        if fence is not None:
            code = fence.group(2).rstrip()
            if code.strip():
                groups.append(ShapeGroup(*_split_note(name), [], fence.group(1).strip().casefold(), code))
                continue

        entries: list[tuple[str, str]] = []
        for line in body.splitlines():
            entry = _SHAPE_ENTRY.match(line)
            if not entry:
                continue
            parts = _SHAPE_SPLIT.split(entry.group(1), maxsplit=1)
            if len(parts) == 2:
                entries.append((parts[0].strip(), parts[1].strip()))
            else:
                entries.append((entry.group(1).strip(), ""))
        if entries:
            groups.append(ShapeGroup(*_split_note(name), entries, "", ""))
    return groups


def _split_note(heading: str) -> tuple[str, str]:
    """A group heading is `Name — what it owns and where it lives`."""

    parts = _SHAPE_NOTE.split(heading, maxsplit=1)
    return (parts[0].strip(), parts[1].strip()) if len(parts) == 2 else (heading.strip(), "")


def _shape(source: str | None) -> str:
    """Validate the Interfaces section.

    One group per component, each headed `Name — what it owns`, each carrying
    that component's surface. The old three-group split (components, then
    interfaces, then data shapes) made a reader assemble one component from
    three places; a signature written in the target language already names the
    types that cross it, so the split bought nothing the code does not say.

    At least one group must be code: a design described only in prose has not
    named a surface anyone can disagree with."""

    if source is None or not source.strip():
        raise PlanError(
            "plan needs an ## Interfaces section with one `### Name — what it owns` "
            "group per component"
        )
    groups = [group for group in shape_groups(source) if group]
    if not groups:
        raise PlanError(
            "## Interfaces needs at least one `### Name — what it owns` group, "
            "each carrying that component's surface"
        )
    if not any(group.code for group in groups):
        raise PlanError(
            "## Interfaces needs at least one group written as a fenced code block: "
            "state the surface in the language being built, not in prose about it"
        )
    return source


def _section_map(text: str) -> dict[str, str]:
    matches = list(_SECTION.finditer(text))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[match.group(1).strip().casefold()] = text[match.end():end].strip()
    return sections


def _without_plan_block(text: str) -> str:
    output: list[str] = []
    inside = False
    for line in text.splitlines():
        if not inside and line.strip() == PLAN_FENCE:
            inside = True
            continue
        if inside:
            if line.strip() == "```":
                inside = False
            continue
        output.append(line)
    return "\n".join(output)


def _route_fields(body: str) -> dict[str, dict[str, Any]]:
    """Each labelled line of a Route card, with any indented sub-bullets."""

    fields: dict[str, dict[str, Any]] = {}
    current: dict[str, Any] | None = None
    for line in body.splitlines():
        match = _ROUTE_FIELD.match(line)
        if match:
            current = {"head": match.group(2).strip(), "subs": []}
            fields[match.group(1).casefold()] = current
            continue
        if current is None:
            continue
        sub = _SUB_BULLET.match(line)
        if sub:
            current["subs"].append(sub.group(1))
        elif line.strip() and not line.startswith(("-", "*", "#")):
            if current["subs"]:
                current["subs"][-1] += " " + line.strip()
            else:
                current["head"] += " " + line.strip()
        else:
            current = None
    return fields


def _branch(field: dict[str, Any], milestone: int) -> dict[str, Any]:
    """A real research fork: one question, at least two outcomes, one default."""

    question = field["head"]
    if "?" not in question:
        raise PlanError(
            f"Route milestone {milestone} Branch must ask what is being found out, as a question"
        )
    outcomes: list[dict[str, Any]] = []
    for raw in field["subs"]:
        is_default = bool(_DEFAULT_SUFFIX.search(raw))
        text = _DEFAULT_SUFFIX.sub("", raw).strip()
        if not _OUTCOME.match(text):
            raise PlanError(
                f"Route milestone {milestone} Branch outcome {raw!r} needs the shape "
                "'If OUTCOME -> WHAT HAPPENS NEXT'"
            )
        outcomes.append({"text": text, "default": is_default})
    if len(outcomes) < 2:
        raise PlanError(f"Route milestone {milestone} Branch needs at least two outcomes")
    defaults = [item for item in outcomes if item["default"]]
    if len(defaults) != 1:
        raise PlanError(
            f"Route milestone {milestone} Branch needs exactly one outcome marked (default)"
        )
    return {"question": question, "outcomes": outcomes}


def _enables(field: dict[str, Any], milestone: int, chunk_ids: list[int]) -> dict[str, Any]:
    """A test-infrastructure milestone: which later stages, and what it buys them."""

    text = " ".join([field["head"], *field["subs"]]).strip()
    parts = _DEFINITION_SPLIT.split(text, maxsplit=1)
    named = [int(value) for value in _MILESTONE_REFERENCE.findall(parts[0])]
    if not named:
        raise PlanError(
            f"Route milestone {milestone} Enables must name the later milestones it makes testable"
        )
    for target in named:
        if target not in chunk_ids:
            raise PlanError(f"Route milestone {milestone} Enables names unknown milestone M{target}")
        if target <= milestone:
            raise PlanError(
                f"Route milestone {milestone} Enables names M{target}, which is not a later milestone"
            )
    capability = parts[1] if len(parts) == 2 else ""
    if not any(word in capability.casefold() for word in CAPABILITY_WORDS):
        raise PlanError(
            f"Route milestone {milestone} Enables must say what the capability gives later stages "
            "(" + ", ".join(CAPABILITY_WORDS) + ")"
        )
    return {"milestones": named, "text": text}


def _operator_contract(text: str, plan: dict[str, Any]) -> dict[str, Any]:
    """Validate and retain the small semantic surface the approval page renders."""

    body = _without_plan_block(text)
    title = _TITLE.search(body)
    if title and len(title.group(1)) > TITLE_BUDGET:
        raise PlanError(
            f"the plan title is {len(title.group(1))} characters; keep it under {TITLE_BUDGET}"
        )
    sections = _section_map(body)
    route_source = sections.get("route")
    if route_source is None:
        raise PlanError("plan needs a ## Route section with one card per milestone")
    chunk_ids = [item["id"] for item in plan["chunks"]]
    matches = list(_ROUTE.finditer(route_source))
    routes: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(route_source)
        milestone = int(match.group(1))
        fields = _route_fields(route_source[match.end():end])
        missing = [name for name in REQUIRED_STAGE_FIELDS if not fields.get(name, {}).get("head")]
        if missing:
            raise PlanError(
                f"Route milestone {milestone} needs " + ", ".join(name.title() for name in missing)
            )
        route: dict[str, Any] = {"id": milestone, "title": (match.group(2) or "").strip()}
        for name in REQUIRED_STAGE_FIELDS:
            value = fields[name]["head"]
            if len(value) > STAGE_FIELD_LIMIT:
                raise PlanError(
                    f"Route milestone {milestone} {name.title()} is {len(value)} characters; "
                    f"keep a stage field under {STAGE_FIELD_LIMIT}"
                )
            route[name] = value
        if "branch" in fields:
            route["branch"] = _branch(fields["branch"], milestone)
        if "enables" in fields:
            route["enables"] = _enables(fields["enables"], milestone, chunk_ids)
        for field in fields.values():
            for line in [field["head"], *field["subs"]]:
                for reference in _MILESTONE_REFERENCE.findall(line):
                    if int(reference) not in chunk_ids:
                        raise PlanError(
                            f"Route milestone {milestone} refers to M{reference}, which no milestone defines"
                        )
        routes.append(route)
    if [item["id"] for item in routes] != chunk_ids:
        raise PlanError(
            "Route cards must appear once in milestone order for chunks "
            + ", ".join(str(item) for item in chunk_ids)
        )
    asks = sections.get("what you will be asked", "")
    if "approve this" not in asks.casefold():
        raise PlanError("What you will be asked needs an Approve this route row")
    known = {
        "goal", "route", "shape", "interfaces", "human judgment", "what you will be asked",
        "out of scope", "open questions", "rejected alternatives",
    }
    return {
        "goal": sections.get("goal", ""),
        "routes": routes,
        "shape": _shape(sections.get("interfaces") or sections.get("shape")),
        "human_judgment": sections.get("human judgment", ""),
        "asks": asks,
        "out_of_scope": sections.get("out of scope", ""),
        "open_questions": sections.get("open questions", ""),
        "rejected_alternatives": sections.get("rejected alternatives", ""),
        "extras": [(heading, value) for heading, value in sections.items() if heading not in known],
    }


def _require_fields(value: Any, kind: str, fields: tuple[str, ...]) -> None:
    if not isinstance(value, dict):
        raise PlanError(f"each {kind} must be an object")
    for field in fields:
        if field not in value:
            raise PlanError(f"{kind} is missing required field {field!r}")


def seed_flight(flight: Flight, plan: dict[str, Any]) -> None:
    """Load chunks, tasks, and config from the plan into an unseeded flight."""

    if flight.tasks:
        raise StateError("flight already has tasks; the plan seeds only once")
    flight.data["goal"] = plan["goal"].strip()
    config = dict(flight.data.get("config", {}))
    config.update(plan.get("config", {}))
    flight.data["config"] = config
    for chunk in plan["chunks"]:
        flight.add_chunk(
            chunk["title"],
            role=chunk.get("role", "implementer"),
            check=chunk.get("check"),
            review=chunk.get("review", True),
            effort=chunk.get("effort"),
            chunk_id=chunk["id"],
        )
    for task in sorted(plan["tasks"], key=lambda item: item["id"]):
        flight.add_task(
            task["title"],
            chunk=task["chunk"],
            done_when=task.get("done_when", ""),
            check=task.get("check"),
            role=task.get("role"),
            effort=task.get("effort"),
            depends_on=[],
            task_id=task["id"],
        )
    for task in plan["tasks"]:
        flight.task(task["id"])["depends_on"] = sorted(
            {int(item) for item in task.get("depends_on", [])}
        )
    flight.save()
