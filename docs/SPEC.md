# Handoff

*Design, 2026-08-17/18, revision 10. Status: draft — under external review.
Rev9 (working name "Packet Review") was built and installed; its first
real-world handoff forced a rewrite of the entire human-facing surface and
command model. The internal discipline survives; the presentation, naming,
and invocation are rebuilt from first principles.*

## Problem

Agents produce code faster than diff-reading scales. The operator's real asset
is a working model of the system — what it does, where the boundaries are,
what owns what. Agents must impart changes to that model, prove their work
without asking for faith, and borrow the operator's judgment where it is
irreplaceable.

Rev9 got the internal discipline right and the presentation wrong: the first
real handoff reported on the review process itself, in the machinery's own
vocabulary — "theory", "witnesses", "oracle attempts", claim IDs defined
nowhere — and was useless to the operator it was written for. The lesson is
structural, not cosmetic: the machinery is the kitchen; the front page is the
plate. Epistemics are how agents work; the operator is served ontology first —
what changed, shown working, in the product's own words.

## The three jobs

A handoff exists to do three things for the operator, and everything in it
serves one of them:

1. **Update the model.** What changed, how it was designed, and how the map of
   the system is different now.
2. **Prove it works — by showing, not attesting.** Replayable demonstrations,
   named tests with what they observe, and honest gaps.
3. **Recruit the operator.** Decisions that need a call, things worth testing
   by hand, and the places where a human's better idea could land.

Two hard rules govern the whole surface. The **jargon firewall**: no machinery
vocabulary on the front page — no "claim", "witness", "theory", "verdict",
"oracle" — and no identifier that is not defined on the page itself. The
**self-containment test**: the front page must make sense to a reader with
access to nothing else; if it could not be forwarded cold to a colleague, it
fails.

## Proofs

The old claim/witness pair collapses into one concrete thing. At the start of
work the agent writes the **proof outline**: the list of things that will have
to be shown true for the work to count. Written before evidence exists, it
prevents post-hoc rationalization — the bar cannot be quietly lowered once
published. Discoveries add entries with their reasons; retreats are visible
edits, never silent omissions.

At the end, each entry is a delivered **proof** with three parts:

- **Automated evidence** — which tests and checks cover it, and *what they
  actually observe* ("`test_resume_pty` asserts the new PID differs and the
  event stream reconnects"). A bare "tests pass" is not evidence.
- **Demonstration** — the thing seen working: a terminal transcript, a TUI
  dump, a screenshot, a before/after output, each with the replay command
  that reproduces it in seconds. A user-visible promise demonstrates at the
  production boundary; an internal invariant demonstrates as a replayable
  observation at the boundary where that invariant is meaningful — not every
  proof has a screen.
- **The gap** — what this proof does *not* cover, in plain words: what was
  never seen working, what it would look like for a user if broken, and the
  recipe for checking it by hand.

The mandatory gap clause is what keeps "proof" honest — software evidence
never proves in the mathematical sense, and a proof that states its own limits
is the entire epistemics program compressed into one required field.

Proof entries are deliberately denormalized: one test or demonstration may be
cited by several entries, and each citation keeps its entry self-contained.
Every evidence artifact is stamped individually (see *Lifecycle and
staleness*), so shared evidence goes stale independently of the entries that
cite it. A normalized obligation/evidence schema was considered and rejected:
structure the operator never sees must earn its keep, and this doesn't.

The rev9 evidence standards survive unchanged as the reviewer's attack
surfaces: **altitude** (evidence matches the level of the statement — a
user-visible behavior cannot rest on a unit test alone), **boundary**
(evidence crosses the production path, never a test-only shortcut),
**oracles** (observe, compare, and accept are three operations; a regeneration
command that overwrites the golden proves nothing; accepting a changed golden
is a promise change and routes through the operator), **hygiene** (no secrets,
tokens, or private paths; nondeterminism and redactions declared).

Because proofs are replayable rather than asserted, anyone — including a
stranger's reviewer — can re-run them. That single property is what makes
foreign work mechanically inspectable (see *Inbound review*) — though
executing a stranger's commands safely is a separate question of trust,
handled there.

## The front page

One screen, four sections, in the product's vocabulary:

```
WHAT CHANGED — the delta and its design, in codebase vocabulary; how it
  fits or reshapes the architecture. Visual understanding aids live here.
  Doc and spec updates are part of the change, not ceremony around it.

PROOF — the delivered proofs: evidence, demonstration, gap. Nothing else
  counts as assurance.

OVER TO YOU — decisions needing a call (options and consequences,
  tension-framed); things worth testing by hand, with recipes; and —
  required — the part the agent is least satisfied with, as an open
  invitation for a better idea.

FRICTION & FOLLOW-UPS — what fought back during the work, and what was
  filed as future tasks (inert; they demand nothing here).
```

Review results surface **by exception only** — the operator sees the outcomes
of the adversarial process, never the process:

- A proof that survived attack is just a proof, with at most a one-word
  "independently checked" marker. No verdict tables, no counts; a clean check
  costs zero reading time.
- An unresolved **reconstruction divergence** — the reviewer reads the diff as
  doing something the author's narrative doesn't say — appears in WHAT
  CHANGED, both positions stated.
- A gap the **reviewer found** joins that proof's gap clause, marked
  reviewer-found rather than author-declared (that provenance calibrates
  trust).
- A **standing disagreement** from code review lands in OVER TO YOU with both
  positions. Findings the author simply fixed do not appear at all — they are
  just better code now.

One review fact is never suppressed: the front page always carries one line
stating whether independent checking completed — "Independently checked
against `<subject>`" — or did not: "Not independently checked — not
merge-ready." Exception-only reporting hides process detail, never whether
review happened; without this line, "checked and clean" and "never checked"
would read identically.

The front page's permanent home is unchanged: distilled into the merge commit
message. Git is the transport; `handoffs/` evidence on the branch is ephemeral
and prunable, because graduation happens at merge. Prunability has one
constraint: a replay command that survives into the merge message must depend
only on the merged tree — prunable evidence is never a permanent replay
dependency.

## Visual understanding aids

The reviewer-facing artifact is the **pedagogical aid**: ephemeral, drawn for
this handoff, at the altitude of this change, discarded without guilt. There
is no canonical system diagram to maintain — a checked-in map has all of
documentation's liabilities. Static diagrams remain allowed for onboarding,
but opt-in and held to the same bar as code: maintained or deleted.

The medium is deliberately unrestricted — ASCII boxes, a state table, an
annotated transcript, a before/after tree, a timeline. ASCII is the default
(terminal-native, diffable, zero toolchain); anything richer only when it
earns it. The test for any aid: does it make the change understandable faster
than prose, and does it make at least one smell checkable at a glance.

Stability comes from grammar, not from a frozen artifact — three lenses and
two conventions, used the same way every time:

- **Ownership/boundary** — containment means ownership; arrows mean who may
  call or mutate whom. Visible smells: one resource inside two boxes, an
  arrow crossing a boundary backwards, a cycle.
- **Lifecycle** — anything born, living, dying: processes, sessions,
  connections. Visible smells: a state with no exit, a transition that skips
  cleanup, a resume edge landing in a state never shown usable.
- **Path of the change** — the route one keystroke or event takes through the
  system, with the changed segment marked.

Conventions: **one meaning per arrow, stated** — the moment arrows mean
"calls" and "owns" in the same picture, it is decoration; and the
**can't-draw-it rule** — if the picture won't come out clean (a node needs
two containers, an edge must go backwards), that is a finding about the code,
not the drawing. Surface it; never fudge the picture.

## The reviewer

One fresh context — a subagent or `codex exec`, never the author — runs three
duties in a fixed order:

1. **Reconstruct.** Before reading anything the author wrote, the reviewer
   reads the diff and writes its own answer to "what does this change actually
   do?", then compares it against the author's WHAT CHANGED. The ordering is
   the strongest slop detector available: a reviewer who reads the narrative
   first gets anchored and cannot see the divergence.
2. **Review the code.** Ordinary review: correctness, design quality,
   boundary/ownership/lifecycle smells (the same lenses the aids use), broken
   neighbors, missing tests. **Security is always in scope** — secrets in
   output, untrusted input crossing a trust boundary, injection through any
   seam. **Performance is in scope as low-hanging fruit only** — the
   accidental O(n²), the clone-in-a-loop, the query-per-row: exactly the
   waste slop produces. Performance that would cost maintainable design is
   out of scope unless the repo's config declares a performance requirement
   for that path — a zealous reviewer "optimizing" is itself a slop vector.
   File and test counts are not the measure of a change; one file acquiring a
   second authority outweighs ten mechanical edits.
3. **Attack the proofs.** Per entry: do the cited tests observe what the
   entry says (open the test, read the assertion)? Do the demonstrations
   replay (run the replay command)? Are the declared gaps the real gaps?
   Result per entry in plain words: **holds** / **holds, with a gap the
   author didn't declare** (stated) / **doesn't hold** (shown why).

The reviewer sees the diff, the proof entries, and the repo. It never sees the
friction journal or the author's self-assessment — those would tell it what to
worry about, and its value is worrying independently. The author's narrative
is packaged as a separate labeled file opened only after the reviewer writes
its reconstruction. Replaying demonstrations needs execution rights; the
obligation is only that the reviewer never mutates the author's checkout or
the handoff evidence — a throwaway worktree at the head revision is the
one-command way to get that, guidance rather than contract, and it is not a
security boundary (trust in replay commands is an origin question; see
*Inbound review*). Launcher-supplied inputs are labeled as such in the
review record; a starved
reviewer still reconstructs from the raw diff, and the audit watches for
curated feeds.

Reviewer output returns to the author, who saves it verbatim, stamped with
the base and subject revisions it reviewed, and gets one fix loop: real bugs
fixed (affected proofs re-run and re-checked), disagreements resolved or
left standing. The loop is a budget, not a guarantee: if the re-check still
fails, work stops and the unresolved result goes to the operator — a proof
that doesn't hold blocks merge-ready unless the operator explicitly accepts
the failure, and a correctness failure is never recategorized as a design
disagreement. The front page the operator reads is the post-review state.

## Inbound review

Reviewing work that arrives from outside is a mode of the same skill, because
an inbound change is a handoff that arrived without its evidence:

- **A foreign handoff** (from someone else running this machinery) is
  self-contained by rule, so the local reviewer attacks its proofs exactly as
  it attacks local ones — replay commands make third-party verification
  mechanical.
- **A bare branch or PR** gets the reviewer contract with one inversion:
  reconstruct and code review run unchanged (they never depended on the
  author's narrative), and instead of checking a proof outline the reviewer
  *writes the outline the author should have written* — what this change
  would need to prove to count — then checks what the branch's tests and
  evidence cover and gap-lists the rest.

The inbound deliverable is the full front page, not a comment stream. WHAT
CHANGED comes from the reviewer's reconstruction, visual understanding aids
included — the lenses need no author. PROOF carries the synthesized outline,
the coverage actually found, the gap-list, and the independent-check line.
OVER TO YOU is voiced by the reviewer and aimed at the merge decision: which
gaps matter, what to request from the contributor before merging, and
overlaps with filed tasks — never a fabricated author voice. Friction and the
author's design rationale are marked absent rather than invented. If a tasks
skill is installed, inbound review probes the read verbs for related,
duplicate, or impacted tasks and surfaces them; the probe is backend-agnostic
through the seam.

In both cases the replay commands are untrusted input: the reviewer inspects
them before executing anything, and runs them only in a sandbox or with the
operator's explicit authorization. Foreign work is mechanically inspectable;
executing it safely is neither free nor automatic.

## The audit

Roughly one handoff in ten — selected by a keyed hash over a stable handoff
identity fixed when the outline is first created, so "nobody chooses" is
literally true and no later commit can reroll the selection — receives a deep adversarial
autopsy **before merge**, on a different model family or a deliberately
different method. Unlike the reviewer, the audit sees everything, friction
included, and asks: did the machinery itself fail — did a bad proof survive
review, did the front page mislead, did the one-line trigger get honored?
Findings are classified before filing: a **machinery miss** (proof outline
gamed, demonstration cherry-picked, reviewer failed to replay, front page
obscured) is a bug in this system; a **product discovery** outside the
contract is product work, not a miss. Findings land in a ledger and become
fixes to the skill and the reviewer contract — the audit is the check on the
checkers and stays entirely off the front page except when its findings are
themselves exceptions. For the first ~20–30 handoffs the rate stays fixed and
outcomes are read qualitatively; a review process cannot validate itself by
asking a stronger instance of itself. Canaries (planted defects, blinded
replays) stay out of the initial build and remain the gate for any future
orchestrator.

## Two skills, orthogonal

**`handoff`** is the companion for a whole chunk of work, invoked at the
start, because the proof outline and the friction journal only exist if kept
from the beginning. Its flow: outline the proofs; work (journaling friction,
noting working decisions, surfacing material scope expansions before
building); assemble draft front page and proofs; run the reviewer; one fix
loop; present the front page to the operator; apply the operator's replies
(docs updated, decisions recorded, follow-ups filed); merge. It also carries
the inbound-review mode.

**`tasks`** owns the task seam and gardening (below). Review and task
tracking are orthogonal concerns: a repo with no backend configured gets the
identical review experience.

The coupling is loose, by capability probe, at exactly two moments: at design
time — if a tasks skill is installed, look for filed tasks that bear on this
design before committing to it — and at filing time, when friction and
follow-ups become filed tasks. No tasks skill → the `filed.md` outbox.

**Invocation.** A consumer repo's AGENTS.md carries one line — "every
substantive chunk of work ends with a handoff; use the `handoff` skill from
the start" — plus `.handoff.toml`. All obligations live inside the skill, so
improving the discipline never touches consumer repos. There are no
user-facing commands: `/task`, `/garden`, and `/review-branch` are deleted.
The operator hands work to agents in ordinary conversation; agents hand the
work back. There is no degraded mode for an agent that adopted the rules
mid-run: it writes the best handoff it can and says so in one sentence.
A handoff's default endpoint is **merge-ready, presented**: merging, closing
tasks, and any other external write happen only with the operator's word in
that conversation or standing authority declared in config — a globally
installed skill infers no authority from being installed.

**Distribution.** The machinery lives in the operator's generic `skills`
repo — a collection of agent skills of which Handoff is the founding
resident; future skills join as sibling directories. Each skill is a
self-contained directory per the agent-skills standard (SKILL.md plus its
own bundled scripts and prompts), so any one skill is extractable by copying
its directory. Skills are authored once and installed globally: `install.sh`
symlinks them — all, or named selectively — into `~/.claude/skills/` and
`~/.agents/skills/`; a fresh
context is a Claude subagent or `codex exec`; the audit runs on the other
harness. No personal names anywhere in contracts or templates — the handoff
addresses "the operator", whoever commissioned the work. Version skew is
accepted while there is one user; revisit-when: a colleague adopts it, then
the repo starts tagging releases.

## The task seam (inside the tasks skill)

The system talks to a task backend through six verbs — *get*, *neighbors*,
*file*, *link*, *close*, *promote* — and never to a backend directly. The
store is dumb; all intelligence lives in agent sessions. Linear is the first
backend via its MCP; Jira and an amux-native store are later adapters behind
the same verbs.

- **Two lanes, decided by provenance.** Agent-solo filings — or the operator
  braindumping straight into the backend — are **braindumps**: inert, unable
  to trigger execution or demand triage. **Ready** requires the operator's
  live endorsement, because shaping is a ratification act: the agent proposes
  statements, granularity, repo assignments, and dependency edges; the
  operator's "file those" lands them ready. Filing depth matches shaping
  depth — a tossed-off sentence files one umbrella braindump, never a
  speculative tree.
- **Gardening is a mode of the skill**: pointed at the accumulated backlog,
  it walks braindumps with the operator — statements, granularity, edges,
  promotion. Its first session is the Linear cleanup. Shaping a fresh idea
  needs no mode; it is any conversation.
- **Durability.** External writes return receipts stored in the handoff
  evidence; resumes reconcile before writing; external effects come last,
  derived from confirmed git state. A task closes only after its merge is
  confirmed, with the merge commit as the idempotency input. Every task
  carries its repo.
- **Degradation.** No backend configured → the `filed.md` outbox, local IDs
  `local-<yyyymmdd>-<slug>`, reconciled by a later gardening session. A seam
  failure is a seam result, never silently a review failure.

## Lifecycle and staleness

The ten-phase state machine is deleted; what earns its keep is the staleness
mechanism. Every proof artifact carries a sidecar stamp naming the **subject
revision** it attests to — the reviewable tree excluding `handoffs/`,
computed as the git tree object id of the commit's tree with the evidence
directory removed (canonical and deterministic; `subject-rev.sh` already
implements exactly this), so evidence-only commits never invalidate evidence
about the implementation — plus any other input the proof names (a tool
version, a fixture, a contract fingerprint). The derivation is one rule: a proof whose stamp does not match
the current subject is stale and must be re-run before the handoff is
presented; a review that predates the current subject is stale the same way.
Implementer commits after review land the work back in review automatically.
Applying the operator's replies changes docs and goldens — re-run whatever
that application made stale, and err toward re-running too much; an unsound
incremental check would undermine the whole handoff.

The convergence rule replaces the old lifecycle in one sentence: **merge only
the exact subject for which proofs are current, independent review is
current, and the operator's decisions have been applied** — and if applying a
reply materially changed behavior, promises, or the front page, the resulting
delta is presented again before merge. Trivial applications (a doc phrasing,
a recorded decision) don't need a second round trip; when in doubt,
re-present.

Evidence layout, on the task branch: `handoffs/<slug>/` — `outline.md` (the
proof outline, stamped at creation and at delivery), `proofs/` (entries and
demonstrations; text-first — transcripts and dumps are kilobytes; large media
referenced, never committed), `friction.md`, `review.md` (reviewer output),
`receipts/`, `filed.md` (outbox when no backend). Granular commits, no
squashing on task branches.

**Decisions.** A permanent record in `docs/decisions/` is created only when
the operator was presented with options and chose: the options, the choice,
the why, and a revisit-when condition — the concrete trigger that reopens it.
The merge message cites the records it adjudicated. Docs state what *is*;
records hold what was chosen against, and why. Agents' working decisions stay
in handoff evidence — and disguising a consequential choice as an
implementation detail is what the reviewer and audit exist to catch.

## Repos

The ecosystem is several repos, and work sometimes cuts across them.

- **The repo is a hard handoff boundary.** The task graph spans repos;
  handoffs, branches, and front pages never do. Shaping splits a cross-repo
  goal into per-repo sibling tasks linked by dependency edges; the umbrella
  closes when the last child merges.
- **Contracts have one home.** A contract implemented on both sides of a repo
  boundary is single-homed (declared in config); contract-changing work lands
  and is ratified in the owning repo; consumers conform, their reviewers
  receiving the ratified contract as input.
- **Cross-repo staleness follows what the proof names**: "these exact builds
  interoperate" pins (repo, commit) pairs; "consumer conforms to protocol X"
  pins the contract fingerprint, so unrelated producer commits don't trigger
  perpetual re-proving.
- **Boundary placement.** Repo boundaries belong on narrow, slow-moving,
  versioned contracts; wide fast-moving seams belong inside one repo.

## Kill criteria

- **The system-level one**: if after three handoffs the operator has not made
  an architectural or product intervention they would not have made from a
  diff and an ordinary agent summary, the experiment failed — however smooth
  the handoffs.
- Agents failing to initiate handoffs from the one-line trigger → the trigger
  needs teeth (e.g. a scaffold marker that makes an unfinished handoff
  visible), found empirically via the audit.
- A front-page section producing no decision, drill-down, or confidence
  change across three relevant handoffs → demote, redesign, or delete.
- Visual aids that restate the diff instead of teaching it → tighten the
  lens rules or drop the obligation.
- The friction journal degenerating into boilerplate → kill it.
- Gardening discarding nearly everything agents file → the filing obligation
  is producing noise; tighten it.
- Audit misses spike → shorten the interval; the rate never lengthens during
  the pilot.

## Deferred, deliberately

- **The audit** *(parked 2026-08-20; see the rev11 ledger)* — automatic
  keyed-hash selection, cross-harness autopsy, and the audit ledger.
  Revisit-when: handoff volume grows past what the operator can read
  qualitatively. Until then the operator is the audit, and an on-demand
  operator-invoked autopsy of any past handoff preserves the capability.
- **Any review UI.** Markdown front pages until the format survives ~10
  handoffs; the natural end state is an amux screen.
- **Rehearsal spikes** (bounded throwaway implementations of a plausible
  future to measure blast radius) — rev9 carried them; the default handoff
  must stay light enough to run on every substantive chunk. Revisit when
  design-time task lookup proves insufficient for shape judgment.
- **The orchestrator** — auto-pickup from ready tasks; gated on audit
  canaries.
- **Scheduled gardening** — the gardener starts operator-invoked.
- **Other task backends** — Jira, amux-native; migration through the seam
  verbs.
- **Model-routing policy** — encode once usage patterns exist.
- **Audit canaries** — required before the orchestrator.
- **Planning skill** — orthogonal; motivated by handoff outcomes.
- **Mutation testing** — when manual proof attack stops being the bottleneck.

## Ratified so far

### 2026-08-17

- Front page's permanent home: merge commit message.
- Evidence committed on task branches, prunable anytime.
- The reviewer never sees the implementer's self-assessment.
- No squashing on task branches.
- Single build, E2E from day one; no phase gating.
- Mechanical friction sniffing from git history: dropped.
- Decisions: operator-gated only, with revisit-when conditions.

### 2026-08-18 (rev9)

- Scope is defined by the obligations: necessary is in; merely noticed is
  filed; material expansion surfaces the choice before building; honest
  degradation when the operator is unavailable.
- Task backend: Linear behind the seam; Jira and amux-native are later
  adapters; migration deferred.
- Filing is frictionless and inert: braindumps from anyone; only
  operator-endorsed shaping promotes to ready; filing depth matches shaping
  depth; sub-task decomposition is private to the work.
- The repo is a hard handoff boundary; cross-repo goals split into per-repo
  siblings with dependency edges; contract theory is single-homed.
- The audit runs pre-merge on keyed-hash selection, on the other model
  family; canaries gate the orchestrator; no auto-pickup yet.
- The machinery lives in its own repo, installed globally; skills authored
  once in the open agent-skills standard; a consumer install is a pointer
  plus config, never a copy.
- The gauntlet costs a fraction of the work it certifies (knobs: audit rate,
  review depth).

### 2026-08-18 (rev10) — after the first real-world handoff

Supersedes rev9's presentation, vocabulary, and command surface; earlier
entries stand except where replaced below.

- The handoff serves three jobs — update the model, prove by showing, recruit
  the operator — and everything on the front page serves one of them.
- Front page rebuilt: four sections (WHAT CHANGED / PROOF / OVER TO YOU /
  FRICTION & FOLLOW-UPS); jargon firewall; self-containment test. Replaces
  the eight-section page.
- Claims and witnesses collapse into **proofs**: outline written before
  evidence, delivered as automated evidence + demonstration + mandatory gap
  clause. Replaces the claim/witness split and the
  verified/inconclusive/falsified enum; reviewer results are plain language
  (holds / undeclared gap / doesn't hold).
- Review surfaces by exception only: survived checks are silent; divergences,
  reviewer-found gaps, and standing disagreements are the only review content
  the operator sees.
- Reviewer duties, in order: reconstruct-then-compare, code review (security
  always; performance as low-hanging fruit only — deeper only via a declared
  product requirement in config), proof attack. The reviewer replays in a
  throwaway worktree; the author's narrative is opened only after
  reconstruction.
- Visual understanding aids: ephemeral and pedagogical; three lenses
  (ownership/boundary, lifecycle, path-of-change); one meaning per arrow;
  the can't-draw-it rule. No canonical maps; static diagrams opt-in at the
  code quality bar. ASCII default, medium unrestricted.
- `/task`, `/garden`, `/review-branch` deleted. Two orthogonal skills:
  `handoff` (invoked at the start of work via one AGENTS.md line; owns the
  front page, the reviewer, and inbound review) and `tasks` (owns the seam
  and gardening). Loose coupling by capability probe at design time and
  filing time.
- Inbound review is a mode of `handoff`: for a bare branch, the reviewer
  writes the proof outline the author should have, then gap-lists.
- The ten-phase state machine and the ratified I→F filing transition are
  deleted; subject-revision stamps survive as the sole staleness mechanism —
  stale proofs and stale reviews re-run before presentation.
- Rehearsal spikes move to deferred.
- Operator-generic language everywhere; no personal names in machinery,
  contracts, or templates.
- No degraded mode for mid-run adoption: adopt-late agents write the best
  handoff they can and say so.
- Naming: one word — **handoff** is the system, the skill, the act, and the
  artifact. On-branch evidence lives in `handoffs/<slug>/`; the config file
  is `.handoff.toml`; *front page* is kept. *Packet* is retired. *(Amended
  same day: the machinery lives in the operator's generic `skills` repo —
  each skill a self-contained, individually extractable directory; `tasks`
  does not get its own repo; future skills join as siblings.)*

### 2026-08-18 (rev10 amendments, after external review of the draft)

- The front page always carries one line stating whether independent
  checking completed against the current subject; absence of review is never
  silent. A proof that doesn't hold blocks merge-ready unless the operator
  explicitly accepts the failure; the fix loop is a budget, not a guarantee —
  an unresolved re-check stops and returns to the operator, and correctness
  failures are never recategorized as disagreements.
- Convergence rule (the one-sentence replacement for the deleted lifecycle):
  merge only the exact subject with current proofs, current review, and
  applied operator decisions; a materially changed delta is re-presented
  before merge.
- Audit selection keys on a stable handoff identity fixed at outline
  creation and is sticky — no later commit rerolls it.
- The subject revision is defined precisely as the git tree object id of the
  commit's tree with the evidence directory removed; review stamps record
  both base and subject.
- A replay command that survives into the merge message depends only on the
  merged tree; prunable evidence is never a permanent replay dependency.
- Demonstration altitude restored: a user-visible promise demonstrates at
  the production boundary; an internal invariant demonstrates as a
  replayable observation at the boundary where it is meaningful.
- Default endpoint is merge-ready, presented; merging, closing tasks, and
  external writes need the operator's in-conversation word or standing
  authority in config.
- The worktree is guidance, not contract: the obligation is that the
  reviewer never mutates the author's checkout, and a worktree is not a
  security boundary. Inbound replay commands are untrusted input — inspected
  before execution, run only sandboxed or with explicit authorization;
  "reviewing foreign work" is mechanically inspectable, not free to execute.
- Rejected: a normalized obligation/evidence schema in the internal model.
  Proof entries stay denormalized and self-contained; evidence artifacts are
  stamped individually and may be cited by several entries.
- Inbound review delivers the full front page: WHAT CHANGED from the
  reconstruction with visual aids, PROOF from the synthesized outline with
  the independent-check line, OVER TO YOU voiced by the reviewer for the
  merge decision, and task-seam overlaps surfaced via the read verbs.
  Friction and author rationale stay absent, never invented.

### 2026-08-20 (rev11) — after the scaffold flight and the first wild pickup

Context: the first scaffold flight (the agent-spend meter) produced a
28-entry friction log; the first unsupervised pickup of the handoff skill
attached full ceremony to a four-line bug fix. Three independent design
reviews followed. The operator ratified the family theory — two operator
conversations per significant piece of work (alignment and completion),
an invisible machine plane between them, ceremony proportional to stakes —
and the entries below. Where an entry reverses an earlier ratified decision,
the reversal was explicit and knowing, not a silent re-litigation.

- **Scoping is binary.** Handoff runs on operator request or when a change
  cannot be judged from its diff and commit message (unreadable diff,
  changed promise, moved boundary, risky/irreversible, multi-session).
  Small self-contained work is declined in one sentence; there is no
  lighter handoff tier; the decline dominates late adoption. The
  every-substantive-chunk trigger is retired.
- **Process artifacts never enter product git history** *(reverses
  "evidence committed on task branches, prunable")*. Evidence lives
  untracked under `.handoff/<slug>/`, hidden via `.git/info/exclude`; the
  merge commit message remains the sole durable record; commit messages
  carry no machinery vocabulary. Accepted trade: evidence no longer travels
  with a branch to other machines or PR reviewers; revisit-when: cross-
  machine work or a colleague adopts.
- **One freshness record per handoff** *(reverses "evidence artifacts are
  stamped individually")*. The single-equality staleness rule is unchanged;
  per-artifact sidecars added no information because seals written together
  expire together. Any post-record change stales the whole handoff:
  re-verify everything, re-stamp once.
- **The audit is parked** *(moves the pre-merge keyed-hash audit, its
  per-handoff identity ritual, and the audit ledger to the deferred list)*.
  At current volume the operator reads every front page and is the audit.
  The capability survives as an operator-invoked cross-family autopsy of
  any past handoff, on demand.
- **The mandated `working-decisions.md` file is cut**; consequential
  choices surface in OVER TO YOU or the commit message. The friction
  journal file is owed only for multi-session work; the front-page section
  is always owed.
- **Reply handling**: an operator reply that does not address an OVER TO
  YOU item or a stated gap is not acceptance; unaddressed items stay open
  and are carried into the merge message as open.
- **The skill family** around handoff: `intake` (requirements alignment,
  always in proportional form; may complete asynchronously through a
  gardened task), `scaffold` (endurance machinery, firing only when work
  cannot complete in one context; hidden self-versioned `.scaffolding/`
  workspace; plan presented by default, waivable only by an explicit
  recorded operator waiver), and `delegate` (staffing policy: role
  contracts, an operator-owned roster with a required default binding, a
  staffing log, one-tier escalation). Skills meet only at artifact shapes
  and name-only capability probes; no skill's prose references another
  except by probe.
- **Drivers are scripts, never agents.** A scaffolded run's loop selects
  mechanically, assembles prompts by concatenating artifacts authored
  upstream, and dispatches by roster lookup; judgment lives in ephemeral
  strong-model contexts spawned on triggers and terminating into recorded
  decisions. Escalations are delivered to the operator as durable artifacts
  while the run continues on independent items.
- **Deliberate absences, stated so they are not filled by accident**:
  handoff gains no intake phase; delegate reads no task backlog and starts
  no runs (the orchestrator remains deferred behind audit canaries); the
  oracle/answer-key role is structurally absent from the roster schema —
  verification authority is the operator's personally and is never a
  staffing question.
- **The operator surface is canonicalized** in `docs/OPERATOR-SURFACE.md`
  (plain language, defaults with blast radius, per-row marks, provenance:
  interpretations may default, expansions need their own explicit yes,
  silence never confirms). Each skill restates it in its own words and
  enforces it by template shape; runtime prose never cites the doc.
- **(2026-08-21) Per-skill, local-only configuration** *(reverses rev10's
  single `.handoff.toml` as the consumer config)*: each skill that needs
  repo-level configuration owns its own file — `.tasks.toml` (backend,
  repository identity, external-write authority) and `.handoff.toml`
  (theory homes, contract ownership, merge authority, performance paths) —
  and no skill reads another's. Both are operator-local and untracked:
  backend choice, sibling-repo names, and standing authority are operator
  facts, never repository facts, and never enter shared history. This
  removes the last configuration coupling between skills; each skill is
  fully independent by copying its directory.
