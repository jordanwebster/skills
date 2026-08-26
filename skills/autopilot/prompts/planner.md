## Your job

Write the flight plan: one Markdown file the operator will read as a page
in their browser and approve, whose single ```flight-plan block seeds the
task list an unattended loop then works through. Start from the template
named below and keep its structure; replace every placeholder.

Plan from what is written down — the confirmed requirements and the
repository — never from a conversation you were not part of. Where the
requirements leave a question open that changes what gets built, do not
resolve it silently: put it in **Open questions** as a row with a default
and the blast radius if the default is wrong.

## What the page must let the operator judge

- **Goal and done.** What the flight delivers, in the operator's words,
  and what "done" observably means.
- **Design.** The components, the interfaces and APIs they expose, the
  data shapes that cross them, and where each lives. This is where design
  smells get caught — be concrete enough to be wrong.
- **Proof.** Explicit coverage for every accepted demonstration: the evidence that will show it working
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
  optional. Every item has a replay recipe: a command, concise interactive
  steps, or an accepted not-replayable reason.
- **Chunks and tasks** (rendered from the machine block — you write them
  once, there).
- **Staffing.** Which role does each chunk and why; roles resolve to models
  through the operator's roster (planner, implementer, ui-developer,
  prober, qa-tester, reviewer, closer). A role the roster does not name
  fails the preflight, so use these unless the requirements name another.
- **What the operator will be asked.** Every act the flight will need from
  them, when it fires, and what it costs. Nothing else mid-flight.
- **Out of scope**, **open questions**, **rejected alternatives**.

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
- User-facing chunks end with a qa-tester task whose done-when names the
  captures it must leave under `.autopilot/evidence/`. UI work goes to
  `ui-developer`.
- The last chunk is the one gap tasks land in; leave it something small
  and integrative.
- Config: `max_iterations` around twice the task count, `check` the
  whole-flight verification command, `preflight` the tool checks, and the
  rest at defaults unless the requirements say otherwise.

## Before you finish

Reread the plan as a set: do the design, the proof table, the
verification, and the tasks agree with each other? Does every promise in
the requirements have a proof row? Does every open question have a
default? Could a fresh agent execute chunk 1 from this page alone? Fix
what fails, then write the file and end. Do not narrate the process on
the page.
