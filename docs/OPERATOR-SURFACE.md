# The operator surface

Canonical statement of the bar every operator-facing surface meets, and the
grammar every operator question uses. Each skill restates these rules in its
own words and enforces them through the shape of its templates; none may
reference this file at runtime. This file exists so the restatements have one
source to be checked against when skills are revised.

## The bar

An operator-facing artifact — a requirements readback, a plan, an escalation,
a front page, a wrap-up — is written for a reader who never saw the process
that produced it:

- Plain language. Every term is defined on the surface that uses it. No
  internal identifiers, no machinery vocabulary.
- Defaults stated. Nothing proceeds on an unstated assumption.
- Short, scannable rows. Sign-off quality degrades with scroll; if the
  operator must reread, the surface failed.
- Internal keys (item ids, row ids, revision tags) live in machine-facing
  columns and files only. The surfaced form derives from a plain-language
  field, never the reverse.
- The same bar binds the product's own operator-facing output — an
  installer's messages, a tool's report — not only the process artifacts
  around the work. A product that greets its operator with a wall of text
  fails the bar the same way a readback would.

## The decision-row grammar

Every question the system puts to the operator has one four-part shape,
wherever it appears:

1. **The thing** — what is proposed or blocked, in plain words.
2. **The default** — what happens if the operator does nothing.
3. **The blast radius** — what it costs if the default is wrong.
4. **The mark** — an explicit per-row confirm or veto.

## The provenance doctrine

Every row carries its provenance: **operator-stated** or **agent-proposed**.

- Approval is always an explicit act, given at one of two moments: a row's
  own confirm-or-deny question, or a final all-ok over a recap where every
  undemanding default is visible. There is no third path: a decision stated
  in passing prose and left unobjected-to is an open question, never an
  approval.
- Provenance decides which moment. A default **interpretation** of
  something the operator stated, small and reversible, may wait for the
  all-ok. An **expansion** — agent-proposed scope, new guarantees, new
  spend, new authority — always takes its own explicit yes, never bulk,
  never inferred from an old artifact.
- A one-off act by the operator — an authority granted, an exception made —
  is scoped to that instance and never generalizes into a standing rule.

## Attention placement

- Operator involvement is frontloaded: everything the operator must do during
  a run is agreed, previewed, and priced before the run starts. Mid-run
  contact is reserved for genuine surprises (a scope expansion that could not
  have been pre-signed) and arrives as a durable artifact in the decision-row
  grammar, never a live question the run waits on.
- One operator account per boundary crossing: work is presented to the
  operator once at alignment and once at completion. No surface duplicates
  another's account of the same work.

## Acceptance and proof

Keep four boundaries distinct:

1. The **acceptance contract** records the outcomes, exclusions,
   demonstrations, limitations, and exceptional acts the operator confirmed.
2. The **evidence plan** records how the implementer or planner will cover those
   demonstrations: tools, fixtures, environments, replay recipes, and checks.
3. **Evidence artifacts** are the actual captures at the reviewed commit.
4. The **proof bundle** joins product-language claims to the accepted
   demonstrations, artifacts, replay recipes, and explicit gaps.

Coverage is many-to-many. One capture may cover several demonstrations and one
demonstration may need several captures. The invariant is no uncovered promise,
not one row, task, or artifact per promise. A replay recipe is a command,
concise interaction steps, or an accepted not-replayable reason with its
limitation.

Completion is proportional:

- If a diff and focused checks show the promise, use an ordinary response.
- If behavior needs a demonstration but is easy to judge, show compact proof.
- If work is risky, long, architectural, inbound, or difficult to judge, show
  one decision page with one independent review.

Default completion surfaces contain what changed, proof, material gaps or
decisions, and meaningful follow-ups. Tasks, chunks, dispatches, events,
internal IDs, and manufactured checks or concerns remain in diagnostics.
