---
name: handoff
description: Carry, validate, and present proportionate proof when finished work cannot be judged from an ordinary diff and focused checks, or when reviewing inbound work. Use compact proof for easily judged behavior and a reviewed decision page for risky, long, architectural, or difficult work. Do not impose a page or review on ordinary small changes.
---

# Handoff

Show the operator the smallest honest surface from which they can judge the
result. Handoff consumes already-set acceptance and evidence plans; it does not
retroactively define success or create another approval gate.

## Choose the surface

- When a diff and focused checks show the promise, do not use Handoff.
- When behavior needs demonstration but is easy to judge, use compact proof:
  claim, capture, replay recipe, and explicit gap. It needs no independent
  review by default.
- For risky, long, architectural, inbound, or difficult-to-judge work, use a
  decision page and one independent review.

An Autopilot closer performs that one final review and supplies the bundle; do
not add another landing review. For standalone page work, use a fresh reviewer
with [the reviewer prompt](prompts/reviewer.md). Reviewer judgment stays outside
the command.

## Build and finish the proof

Put evidence under an untracked `.handoff/<slug>/` workspace. Write its
canonical `proof.json` according to [the proof schema](references/proof-schema.md).
Evidence coverage is many-to-many: every accepted demonstration must be
covered, but one capture may support several demonstrations and no dedicated
capture task is required. A replay recipe may be a command, interaction steps,
or an accepted reason that replay is impossible.

Locate the command from the loaded skill:

```bash
skill_dir=$(CDPATH= cd -- "$(dirname -- "$skill_file")" && pwd -P)
handoff=$skill_dir/scripts/handoff
"$handoff" finish .handoff/<slug> --no-open
```

Omit `--no-open` to open a page-mode result. Use `--json` for a stable machine
result. Fix validation errors; never weaken a claim to make the command pass.

## Consumes

- Accepted demonstrations and the planner or implementer's evidence coverage.
- Evidence artifacts captured at the reviewed commit.
- For page mode, one fresh review of that same commit.

## Produces

- `proof.md` for compact proof or `handoff.html` for a decision page.
- A stable result naming the output, commit, evidence size, gaps, and one next
  action.

## Does not own

- Requirements, implementation planning, evidence persuasiveness, or merge
  authority.
- Tasks, chunks, dispatch history, event logs, or another completion receipt.
- A mandatory page, independent review, manual check, concern, or follow-up
  where none changes the operator's decision.

Present the result and stop. Merging, closing tasks, publishing, and other
external writes still require the operator's authority.
