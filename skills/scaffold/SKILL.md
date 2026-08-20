---
name: scaffold
description: Erect durable machinery for work too large for one sitting - an approved plan, a hidden workspace, a machine-checked ledger, a bounded unattended run. Use only when work cannot complete reliably in one context or needs verification infrastructure that outlives one. Decline otherwise.
---

# Scaffold

Machinery for endurance. Use this skill only when the work cannot be done
reliably in one sitting: multi-session scope, or verification infrastructure
— captures, harnesses, fixtures — that must outlive any single context.
Never gate the decision on predicted duration; count contexts and continuity
risks, which are observable before work starts.

Decline this skill when a well-understood task fits one context: execute it
directly and emit no scaffold. Less machinery is the correct result when
continuity is not at risk. Size of change alone never triggers scaffolding —
that question belongs to whoever reviews the finished work, not to how the
work runs.

## Inputs

Scaffolding consumes requirements the operator has already confirmed row by
row — from a shaped task, a prior conversation, or a skill named `intake` if
one is available. If no confirmed requirements exist, obtain them first;
planning against unconfirmed intent builds the wrong thing precisely. Do no
implementation before the plan gate below.

## The workspace

All scaffold artifacts live in one hidden directory at the repository root:
`.scaffolding/<goal-slug>/` (short `[a-z0-9-]` slug; for greenfield work,
create the repository first, at the workspace the requirements named). Hide
it from the product's history: append `.scaffolding/` to `.git/info/exclude`
— never to the tracked `.gitignore` — and run `git init` inside
`.scaffolding/` so the machinery's own history is versioned separately.
Record the product commit each verified state corresponds to in the ledger
(`verified_head`), so machinery state is bound to product state by recorded
hash, not by co-residence.

The product's channels — code, comments, docs, commit messages, tracked
files — carry zero scaffold vocabulary: no item ids, no revision tags, no
plan references. Code comments serve a reader who never saw the plan.
Agent-to-agent communication travels through the ledger and plan, never
through the product. Because the scaffold's namespace is generated, this is
checkable: include a vocabulary lint over product channels as a standard
verification assertion (`scripts/vocab-lint.sh` beside this file is the
starting point).

Copy the skeletons this goal needs from `templates/` beside this file into
the workspace. `plan.md`, `goal-function.md`, `ledger.json`, and
`autonomy-grant.md` are not optional; `wrap-up.md` is owed at the end.

## The plan

Derive `plan.md` in a fresh context with the strongest judgment available,
following `prompts/planner.md` beside this file. The planner reads only the
confirmed requirements and the substrate — never this conversation. The
blindness is the point: a planner without the intake conversation can only
plan from what was written down, so any surviving ambiguity blocks the plan
instead of a later segment; each gap goes back as a requirements row with a
default and blast radius.

The plan is presented to the operator as a readable document — research
phases and preconditions, implementation phases, interfaces, how the work
will be verified and why that way, file layout, the operator acts it needs
and when each fires, and the staffing shape if roles will be dispatched to
different models. Present it and stop; the operator's approval is given in
conversation, explicitly — never inferred. The operator's approval buys the
unattended run; everything the run will ever need from the operator is on
the page before it starts. If the confirmed requirements carry an explicit
"run without plan review" waiver, proceed without presenting — the waiver is
never inferred.

Approval has a stated scope: the plan's declared uncertainty is the
envelope. Revisions within it proceed unattended; a revision that breaks it
— new scope, new guarantees, new spend, a new operator act — is an
expansion needing its own itemized yes, delivered as an escalation. Each
operator act on the page is cheap — a short review plus one command;
anything more belongs to a segment — and carries its rationale, so the
operator can see at sign-off why the act cannot be automated away. The
operator approves the plan's readable sections; the item tables beneath
them are machine-facing columns that must derive from what the readable
sections say.

The goal function and ledger are derived from the approved plan and must
trace to it. Prerequisites — captures to take, fixtures to graduate, harness
gaps to close, any throwaway prototype a requirements row deferred to — are
the plan's first items, verifiable like any other, and independent
prerequisite items run as parallel segments by default.

Plans change only by recorded revision in a fresh planning context, never by
silent mid-segment edits — and revisions are batch events (after probes
land, after captures land, after a batch of operator rulings), not a
ceremony per finding. Fold accumulated findings in one pass; per-finding
revision was measured waste.

## Verification

Complete `goal-function.md`: one executable command whose exit status alone
decides done-and-correct, run from a clean checkout, collecting its own
evidence from artifacts on disk. A transcript or self-report is a claim,
never evidence.

Keep the answer key out of worker reach. The oracle owner is the operator —
this role is not transferable and no run design may route around it. During
build-up, segments write an `oracle-candidate/` from sources other than the
artifact under test; the operator promotes it at an act agreed in the plan.
Keep tests visible but read-only to workers; only a recorded operator
decision may weaken a criterion. Deny rules are defense in depth, not the
control.

Anchor verification to real substrate behavior, three ways:

- **External, uncontrolled substrate**: capture its behavior once — redact
  with a check that fails loudly, record the substrate version — then
  graduate the capture into a committed fixture for free replay. Fixtures
  are regression anchors; never refresh them wholesale as routine.
- **The goal defines its own behavior**: ordinary unit, property, and
  invariant tests. No capture is owed.
- **Substrate exists but cannot be captured**: spec-derived synthetic
  fixtures, flagged in the requirements as a fidelity risk.

Probes obey the same discipline: probe the whole corpus, never a sample; tag
findings as historical (an on-disk corpus) or live (freshly generated on the
current version) and never let the first stand in for the second; wire probe
re-runs into verification so findings stay verified rather than
verified-once, and assert monotone properties against a growing corpus so
re-runs stay meaningful.

## The ledger

`ledger.json` is the progress record and the only one. An **item** is the
smallest increment the checker can pass or fail on its own — never sized in
predicted time. A **context phase** groups items that share files and
concepts; the planner assigns phases and roles at plan time. A **segment**
is one fresh-context run dispatched with one phase; it sweeps every
non-blocked item in that phase, flipping each as the checker passes it, and
ends when the phase is done or continuing would rely on anything not yet in
durable files — write it down or it dies with the context.

Every item starts `"passes": false` so missing evidence defaults to failure.
The worker may flip only that field, only after the checker records
evidence. Items may be `blocked_on` (typed: a gap, an escalation, an
operator act — each naming what clears it) or `parked`; selection skips
both and parking consumes no retry budget. Selection is mechanical, by the
rule recorded in the ledger — the worker never chooses its own item. Encode
phase transitions (a simplification pass, a final review) as ledger items
gated on dependencies. At each flip, record the verified product commit as
`verified_head`.

Until the item that builds the verification harness passes, the
run-verification steps of the resume ritual are inactive; the ledger marks
where they switch on.

## The run

An unattended run has a **driver: a script, not an agent**. Nothing in the
loop authors or decides anything; all prose in every prompt was written
upstream into durable artifacts. Each cycle:

1. select the next ready phase by the ledger's rule;
2. resolve the phase's role to a model binding — through a skill named
   `delegate` if available, else whatever launched the run; an unmatched
   role uses the roster's default binding and the mismatch is logged;
3. assemble the segment prompt by concatenation: role contract, plan,
   ledger, and the previous segment's ledger notes;
4. dispatch the segment as its own bounded process under a generous
   `timeout` (a firing hang guard is a hang to diagnose, never a slow
   segment);
5. run the verification command; flip what passed; record `verified_head`;
6. when the segment landed new tests or fixtures, trigger the oracle re-pin
   per the policy in the goal function — an operator act unless that policy
   says the pin reads across the boundary on its own.

The item-to-code trace lives in the ledger's `verified_head` entries and
nowhere else — never reconstructed through commit messages or comments,
which the channel fence keeps clean.

Judgment never lives in the loop. On a trigger — an item at its retry cap, a
stall, a revision batch due — the driver dispatches an ephemeral judgment
context with the strongest available model; it reads the artifacts, decides,
writes the decision down, and ends. At the retry cap the one forbidden
choice is another attempt: split the item at a seam the red evidence shows,
re-brief it in the plan where failures exposed ambiguity, re-dispatch one
tier up when the staffing evidence says the binding was too weak, or park
and escalate. A failure is a full fresh-context attempt ending with its item
still red; failing checks inside a segment count for nothing and should run
as often as they teach.

A stall is a segment that changed nothing measurable — no ledger change, no
new evidence, no working-tree delta, all checkable by hashing. Consecutive
stalls at the granted allowance end autonomy.

Escalations are delivered, not waited on: the escalate exit writes a durable
message in exactly this shape — blocked on X; I would do Y; the blast radius
if Y is wrong is Z; veto or confirm — and the driver forwards it wherever
the operator reads while the run continues on independent items. The
operator's ruling is folded by a fresh judgment context. Never wait on the
operator mid-run; for decisions they would care about, take and log the
reversible option in the plan's decision register and park the
irreversible one.

Complete `autonomy-grant.md` before any unattended run: the stall allowance,
the retry cap, the hang guard, the exits (`success`, `impossible`,
`escalate`), and the stop-the-line triggers. Grant no bound that predicts
run size; the ledger already bounds the run structurally at items times the
retry cap. Stop the line when work would touch real data or machine state
outside the workspace, a criterion weakened without a recorded operator
decision, the verification command is broken, or quota is exhausted —
quota exhaustion pauses and resumes after reset, and infrastructure failure
never turns a ledger entry green or red.

## Attach and resume

The run has no standing mind; its identity lives in the artifacts. Anyone —
the operator asking how it's going, a fresh context after a loss — attaches
by reading the workspace: the resume protocol in `autonomy-grant.md` is the
canonical ritual. Do not re-plan and do not reconstruct from summaries; both
carry contamination that the canonical files avoid.

## Wrap up

Complete `wrap-up.md` from the ledger and evidence: items completed with
their proof commands, deviations, parked items, spend against the grant,
triggers fired — for a reader who was absent, every term defined. When an
end-of-work reporting convention encloses this goal, the wrap-up is machine
input to that report rather than a second operator-facing account: one
account per crossing.

## Rules that apply everywhere

Each control states its purpose beside its rule so a downstream context can
tell protection from theater:

- Every prohibition becomes a firing mechanism — written instructions alone
  are not controls.
- Every test and long command runs under `timeout` — a hang must fire, not
  linger.
- All evidence lives in durable files, reconstructible from a clean
  checkout — anything else dies with a context.
- An operator-run step transfers agency, not labor: the command must act,
  reversibly and tersely, never stage work for the operator to finish or
  print a wall of text — a step that needs an essay belongs to a segment.
