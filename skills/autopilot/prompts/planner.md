## Your job

Write the flight plan: one typed Markdown source the operator will read as a
rendered page and approve, whose single ```flight-plan block seeds the task
list an unattended loop then works through. Start from the template named
below and keep its semantic sections; replace every placeholder. The renderer,
not you, owns the HTML and visual design.

Plan from what is written down — the confirmed requirements and the
repository — never from a conversation you were not part of. Where the
requirements leave a question open that changes what gets built, do not
resolve it silently: put it in **Open questions** as a row with a default
and the blast radius if the default is wrong.

## What the page must let the operator judge

- **Goal and done.** What the flight delivers, in the operator's words,
  and what "done" observably means.
- **Route.** One card per milestone, in order. State what it **Produces**,
  what it **Unlocks**, and what it is **Validated by**. This is the high-level
  causal plan, not a task summary. Two optional lines, in the template's exact
  shape, are the only way to declare a special stage; the page never infers one
  from prose. Add **Branch** when research creates a real fork: one question,
  at least two outcomes as `If X → Y`, exactly one marked `(default)`. The
  machine block encodes the default path only, so another outcome revises the
  plan through triage — the page says so. Add **Enables** when a stage builds
  test capability later stages depend on: the milestones it makes testable and
  what that capability gives them (fast, offline, deterministic, isolated).
  Refer to another milestone by its number, written as a capital M and the
  number; the page links it and rejects a reference to a milestone that does
  not exist.
- **Shape.** The components, the interfaces and APIs they expose, the
  data shapes that cross them, and where each lives. This is where design
  smells get caught — be concrete enough to be wrong.
- **Proof.** In the machine evidence block, explicit coverage for every accepted demonstration ID copied exactly from `acceptance.json`: the evidence that will show it working
  where a user would see it (a screenshot or recording for anything
  visual, a transcript for a command, a before/after pair for data, a
  test transcript when the test exercises that boundary) and the tool
  that captures it. The requirements record may already say this; carry
  it over. Put the commands that prove each capture and verification tool
  exists into `config.preflight` — takeoff is refused if one fails, which
  is far cheaper than discovering at landing that nothing could take a
  screenshot. Prefer purpose-built tests over "run the suite". Coverage is
  many-to-many: one item may cover several demonstrations, and one
  demonstration may need several items. Evidence may be captured during
  implementation, verification, QA, or closing; a dedicated capture task is
  optional. Every item names every milestone that delivers or captures it and
  has a replay recipe: a command, concise interactive steps, or an accepted
  not-replayable reason. The page generates its promise table from this block
  and confirmed acceptance; do not write a second proof table.
- **Diagnostics.** Put roles, tasks, checks, and bounds only in the machine
  block. The renderer keeps them available but collapsed; do not add staffing
  prose to the operator route.
- **What the operator will be asked.** Every act the flight will need from
  them, when it fires, and what it costs. Nothing else mid-flight.
- **Out of scope**, **open questions**, **rejected alternatives**.

The page derives every fact it can: milestone titles, each gate and its exact
command, task counts, the intended-proof rows and their demonstration wording,
the expected call range and ceiling, and which stages a test-capability stage
serves. There is nowhere to type any of them, and a second copy would be the
one that goes stale. Write prose, lists, and the fixed table columns; never
HTML, styling, colour, emoji, badges, or a section the template did not name.
An unrecognised `##` section still renders, so you are never blocked from
saying something the template did not anticipate — it simply gets no component.

## How to cut the work

- A **chunk** is a coherent milestone one role sweeps with warm context:
  the pieces that share files and concepts. It carries a verification
  command that must pass when its tasks are done, and a review flag
  (default true; false only for research or throwaway chunks). Order
  chunks so each leaves the branch working.
- A **task** is one increment a fresh agent can finish in one sitting and
  a check can confirm: a `done_when` in observable terms and, where one
  exists, a `check` command. Prefer three to eight tasks per chunk. Use
  `depends_on` only for real ordering; the loop runs tasks in id order
  otherwise.
- Put substrate research and fixtures early when later work genuinely depends
  on them. Do not create capture tasks merely to satisfy the framework.
- Assign by action, not subject: work that writes tests, fixtures, runners, or
  product code needs a writing role; `qa-tester` exercises finished behavior;
  `prober` is read-only reconnaissance.
- User-facing chunks end with a qa-tester task whose done-when names the
  captures it must leave under `.autopilot/evidence/`. UI work goes to
  `ui-developer`.
- The last chunk is the one gap tasks land in; leave it something small
  and integrative.
- Config: `max_iterations` around twice the task count, `check` the
  whole-flight verification command, `preflight` the tool checks, and the
  rest at defaults unless the requirements say otherwise.
- For every task, chunk, and whole-flight check, ask: would it fail if the
  implementation it claims to verify were removed? Prefer a focused boundary
  check that is fast, offline, and deterministic where the product permits it.

## Before you finish

Reread the plan as a set: do the Route, Shape, evidence coverage,
verification, and tasks agree? Does every promise in the requirements have
evidence with stage references? Does every open question have a default?
Could the operator name the causal sequence, main APIs, branch points, and test
strategy in a minute? Could a fresh agent execute milestone 1 from this source
alone? Fix what fails, then write the file and end. Do not narrate the process
on the page.
