---
name: autopilot
description: Fly work too large for one sitting on an unattended loop of fresh agents - a plan the operator approves in a browser, a task list agents pull from and add to, a review per chunk, and a final acceptance against the requirements. Use when work spans many contexts or must run while the operator is away. Decline for work that fits one sitting.
---

# Autopilot

An autopilot flies the routine stretches and hands back to the pilot when
something is outside its envelope. This skill does that for software work
too large for one context: fresh agents take off one after another on a
single branch, each pulling the next ready tasks, committing what passes,
and writing down what the next one needs. The operator sees two things — a
plan before takeoff and a wrap-up page after landing — plus any question
the flight genuinely cannot answer itself.

Use it when the work will outlive one context window or must run while
the operator is away. Decline it when the work fits one sitting: do the
work, and say in a sentence that it was small enough not to need a flight.

## Locate the machinery

Set `skill_file` to the path through which this `SKILL.md` was loaded;
the installed skill directory is a symlink:

```bash
skill_dir=$(CDPATH= cd -- "$(dirname -- "$skill_file")" && pwd -P)
autopilot=$skill_dir/scripts/autopilot      # the one command everyone uses
```

`autopilot --help` lists every verb. Dispatched agents get it on their
PATH; the chat agent calls it by path.

## The flight, end to end

1. **Requirements.** A flight starts from requirements the operator has
   confirmed — from a skill named `intake` if one is available, or from
   the conversation, written down. Never plan against unconfirmed intent.
2. **`autopilot init --goal "…" [--requirements file]`** at the repository
   root. Creates the flight branch and `.autopilot/`, and copies the
   requirements in. Everything under `.autopilot/` is committed on the
   branch, so state and code stay consistent and any agent can read it.
3. **The plan.** Dispatch the `planner` role — through the operator's
   roster (`autopilot plan --dispatch`) or natively as a subagent bound to
   the model the roster names, with the prompt `autopilot plan --prompt`
   prints. The planner reads only the requirements and the repository and
   writes `.autopilot/flight-plan.html` from `templates/flight-plan.html`.
4. **Approval.** `autopilot plan` opens the page in the operator's
   browser. The operator reads the goal, the design (components, APIs,
   data shapes — where design smells get caught), the verification, the
   chunks and tasks, the staffing, and everything they will be asked. They
   approve **in conversation, explicitly**. Approval is never inferred
   from silence, and a plan the operator has not seen is never flown
   unless the requirements carry an explicit "fly without plan review"
   row.
5. **`autopilot start`.** Seeds the task list from the plan's machine
   block and launches the driver detached. The operator may close the
   chat; the driver has its own heartbeat and log.
6. **The loop** (below) runs until the flight lands or needs the operator.
7. **Landing.** The closer judges the result against the requirements
   and writes the front page — what changed, proof, over to you, friction
   and follow-ups — which becomes `.autopilot/wrap-up.html`, the one page
   the operator reads. `autopilot status --open` shows it. It is the
   flight's handoff, produced by the flight rather than reconstructed
   afterwards; the `handoff` skill's page has the same shape and renderer.
8. **`autopilot land`.** Once landed: keeps the record (wrap-up, plan,
   acceptance, notes, reviews) under `~/.local/state/autopilot/<repo>/`,
   removes `.autopilot/` from the branch in one commit so the product's
   history carries no flight vocabulary, opens the wrap-up, and prints the
   parked follow-ups as `tasks add … --later` lines to file on the
   operator's word. Merge is the operator's act; after it, close the task
   the flight delivered through `tasks`.

Any agent, any time: **`autopilot status`** answers "how is it going?"
from the state on disk — chunk progress, the task in hand, open
questions, recent events, and whether the driver is alive. After
`autopilot land`, it points at the kept record instead.

## The loop

The driver is a script; it never authors or decides. Each iteration:

- **Pick.** The first ready task in plan order (its dependencies done,
  its attempts under the cap). Its role — from the task, else its chunk —
  resolves to a model through the operator's roster (the `delegate` skill
  owns that file; an unknown role uses `default` and is logged).
- **Dispatch** one fresh agent with a small prompt: the goal, the role's
  contract from `prompts/`, the ready tasks for that role in that chunk,
  and `.autopilot/NOTES.md`. The agent pulls those tasks greedily while
  its context is warm, edits code and tests directly, commits what
  passes, marks tasks done, and files what it notices.
- **Confirm.** The driver re-runs each finished task's `check`. A red
  check un-does the task, records the failure in its notes, and counts an
  attempt — as does a task left in progress or untouched. Provider
  failures (rate limits, auth, outages) count nothing and pause the
  driver instead.
- **Chunk done** — every task done or parked — runs the chunk's
  verification, then one **review** by the `reviewer` role against the
  plan's must-fix bar: findings that break the goal or a requirement
  become tasks; proportionality is part of the bar; there is one fix
  round and no re-review. Anything else is recorded for the wrap-up.
- **Retry cap** hands the task to the `planner` to split, re-brief,
  rebind, park, or escalate — never to try again.
- **Escalation** writes a question in a fixed shape — blocked on X; I
  would do Y; the blast radius if Y is wrong is Z — notifies the
  operator, and the flight continues on independent work. It stops only
  when nothing independent remains. `autopilot answer <id> "…"` records
  the ruling and relaunches.
- **Flight done** — every chunk done — runs the whole-flight check, then
  the `closer`: accept, or file the gaps. Gaps twice means the plan was
  wrong, and that is the operator's call.

Bounds live in the plan's config, shown on the page the operator
approved: an iteration ceiling, the retry cap, the per-agent timeout, the
check timeout. Nothing else predicts run size.

## Tasks

Tasks are integers in `.autopilot/flight.json`, each with a title, an
observable `done_when`, an optional `check` command, a chunk, a role,
dependencies, attempts, notes, and an `origin` (plan, review, closer,
autopilot, or the role that filed it). Agents shape the list as they
learn:

```
autopilot task list | show | start | done | note | add | edit | park | unpark | reset
autopilot escalate [task] "…"
```

Filing a task the plan clearly covers is ordinary work. Widening what the
flight promises is not — that is an escalation. `--later` records a
follow-up without scheduling it; parked and later tasks surface on the
wrap-up page.

## Notes

Two memories, two scopes. A task's notes belong to that task: the last
failure, where a partial attempt stopped, a decision made for it. The
flight notes (`.autopilot/NOTES.md`) belong to everyone: how to build and
test, what surprised an agent, what to avoid. Agents keep the notes file
under a screen and prune what is stale.

## What is enforced and what is advisory

Enforced by the driver: fresh context per iteration; checks re-run by the
driver, never taken on the agent's word; attempts, the retry cap, the
iteration ceiling, and timeouts; one driver per flight; commits of
whatever an iteration leaves behind so nothing is lost. Advisory, and
written into the role prompts: don't weaken tests, don't guess at
ambiguity, keep flight vocabulary out of the product, keep notes short.
The chunk review and the closer are where advisory rules get checked.

## Roles

`planner`, `implementer`, `ui-developer`, `prober`, `qa-tester`,
`reviewer`, `closer` have contracts under `prompts/`; the planner assigns
them per chunk or per task. Any role the roster names can be used — an
unknown one gets the worker contract and the roster's default model.
Which model plays which role is the operator's decision in the roster,
never the flight's.
