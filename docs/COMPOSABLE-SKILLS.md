# Composable skills: lifecycle and implementation brief

Status: implementation brief based on the aligned direction; not yet
implemented. While the redesign is in progress this document records the
intended cross-skill contracts. When implementation is complete, move each
contract into its owning `SKILL.md`, templates, prompts, and bundled command,
update the operator-surface documentation, then remove this brief so the skills
return to being their own authoritative designs.

## Product promise

The collection should make significant agent work feel like one continuous
conversation:

```text
Explore an idea
      ↓
Decide to build
      ↓
Agree what success means and what the operator wants to see
      ↓
Approve a plan when the work needs one
      ↓
Let the right agent or agents do the work
      ↓
Receive the smallest completion surface that supports a decision
```

The machinery underneath may include requirements records, role resolution,
task state, retries, captures, reviews, and approval digests. That machinery is
for agents. The operator sees only decisions that need their judgment, a plan
when its review is valuable, genuine surprises, and proportionate proof of the
result.

An unattended flight normally has two conversations:

1. The initial conversation explores the idea, confirms acceptance, presents
   the plan, and starts the run.
2. The completion conversation presents the result and any decisions that
   remain.

A mid-run escalation is exceptional. It is not a planned touchpoint.

## First principle: route by need, not by project class

Lifecycle skills control four independent risks. Do not classify all work as
either “simple” or “consequential” and attach a package of ceremony to the
latter. When the operator decides to build, answer four questions separately:

1. **Alignment:** Is a material operator decision still missing?
2. **Execution:** Will the work outlive the current context or need to run
   unattended?
3. **Staffing:** Is the current agent an appropriate implementer, or would one
   bounded specialist or stronger implementer materially improve the result?
4. **Completion:** What is the smallest proof and review surface from which the
   operator can judge the result?

This produces natural paths instead of one mandatory pipeline:

```text
Clear one-sitting work
  → current agent implements
  → ordinary report or compact proof

One-sitting work with material ambiguity
  → align in conversation; use durable Intake only when another context needs it
  → current agent or one bounded implementer dispatch
  → proportionate proof

Multi-context or unattended work
  → durable Intake if acceptance is not already confirmed
  → fresh planner and plan approval
  → Autopilot
  → decision-ready completion page
```

Simple work remains an explicit fast path. A clear, local, reversible change
that fits one context and is easy to judge uses no lifecycle skill. The current
agent makes it, runs a focused check, captures a small screenshot when that is
the natural verification, and reports the result. Ordinary care is not a
Handoff workflow.

## Natural invocation

The current conversational agent is the concierge. Concierge is a role in the
conversation, not another skill. It owns continuity from exploration through
the start of work: it reuses what the operator already said, invokes only the
capabilities needed, presents operator surfaces, routes feedback, and starts or
dispatches execution.

### Exploration invokes no lifecycle

Questions such as these remain ordinary conversation:

- “Would this be feasible?”
- “How does this subsystem work?”
- “What would be risky about adding X?”
- “Can you probe the API before we decide?”

The agent may inspect and probe read-only. It should not force a possible idea
into Intake merely because the operator may later choose to build it.

### Commitment triggers routing

Phrases such as “okay, build it,” “go ahead,” “implement that,” or “let’s do
this” mark a decision to act. They trigger the four routing questions, not an
automatic skill sequence.

For alignment:

- Ask one or two locally resolvable questions directly in conversation.
- Use Intake when several consequential decisions must be reconciled, the
  acceptance bar needs explicit review, or the result must survive into a fresh
  planner, implementer, or unattended run.
- Skip Intake when the existing conversation or tracked work already forms a
  complete, confirmed acceptance contract.

For execution:

- Keep one-sitting work supervised by the concierge.
- Implement directly when the current mind is suitable.
- Dispatch one bounded implementer or specialist through Delegate when a
  stronger or role-specific mind would materially improve the result. This is
  not an Autopilot flight and creates no plan gate merely because it is a
  delegation.
- Use Autopilot when work spans contexts or must run unattended.

For completion:

- Use an ordinary response when the diff and focused checks are sufficient.
- Use compact proof when behavior needs a capture but a page or independent
  review would not change the decision.
- Use a Handoff page and one independent review for work that is risky, long,
  architectural, inbound, or otherwise difficult to judge in one sitting.

The concierge should not ask the operator to choose a skill. It explains the
human consequence only when useful: “I have two acceptance questions,” “I’ll
bring you a plan before this runs,” or “I’ll show the completed flow at the
end.”

### Direct entry points

| User intent | Entry point |
| --- | --- |
| Shape significant work or settle several acceptance decisions | Intake |
| Run confirmed work unattended or across contexts | Autopilot; use Intake first only if acceptance is incomplete |
| Review difficult finished work or an inbound change | Handoff |
| Find, file, shape, start, or close tracked work | Tasks |
| Resolve or diagnose model and CLI staffing | Delegate |
| Ask “how is it going?” in a repository with a live flight | `autopilot status`, summarized conversationally |

Explicit invocation by the operator is honored without erasing authority
boundaries. If they explicitly request Autopilot or a Handoff page for work
that would not normally need it, provide it and briefly note the proportional
default.

### Target skill descriptions

Discovery text should encode the natural boundaries:

- **Intake:** Confirm a durable acceptance contract after the operator decides
  to build work whose outcomes, evidence, boundaries, or operator involvement
  require several material decisions or must survive into another context.
  Skip exploration, already confirmed work, and questions that can be resolved
  directly in the current conversation.
- **Autopilot:** Execute confirmed software work on an unattended loop of fresh
  agents when it spans contexts or must continue while the operator is away.
  Require an approved plan; decline work that fits one sitting unless
  explicitly requested.
- **Handoff:** Carry, validate, and present proportionate proof for work whose
  result cannot be judged from an ordinary diff and focused checks, or review an
  inbound change. Consume existing acceptance and evidence plans; do not impose
  a page or independent review on ordinary small work.
- **Tasks:** Read and update tracked work when a tracker or backlog is actually
  part of the request or workflow. Tracker failure never blocks otherwise
  authorized product work.
- **Delegate:** Resolve a requested role and effort to a validated mind and
  dispatch specification. Use when dispatching or diagnosing staffing; never
  select work or create an operator workflow of its own.

## One vocabulary

Use four distinct terms:

1. **Acceptance contract** — operator-confirmed outcomes, boundaries,
   demonstrations, accepted limitations, decisions, and exceptional operator
   acts.
2. **Evidence plan** — the planner's concrete methods for covering those
   demonstrations, including tools, fixtures, recipes, timing, and engineering
   verification.
3. **Evidence artifacts** — the screenshots, recordings, transcripts,
   before/after comparisons, test output, or other observations captured at the
   reviewed commit.
4. **Proof bundle** — claims joined to accepted demonstrations, actual
   artifacts, replay recipes, and explicit gaps.

A **replay recipe** is a command when a command is sufficient, concise steps
when interaction is required, or “not replayable” with the previously accepted
reason and limitation. Do not require a command for evidence whose approved
boundary involves a browser, hardware, external system, or manual validation.

Evidence coverage is many-to-many. One artifact may cover several acceptance
expectations when the coverage is explicit; one expectation may require several
artifacts. Evidence may be produced during implementation, verification, QA,
or final acceptance. It never requires a dedicated capture task merely to
satisfy the framework.

Stable internal IDs may connect records mechanically. Conversation and
operator-facing pages refer to scenarios and promises by subject, never by ID.

## Ownership and durable artifacts

| Boundary | Owner | What the next stage receives |
| --- | --- | --- |
| Intent and acceptance | Intake when durability is needed; otherwise the conversation | Confirmed acceptance contract |
| Architecture and execution design | Fresh Autopilot planner, or the supervised implementer for one-sitting work | Work plan and evidence coverage |
| Staffing resolution | Delegate | Validated dispatch specification |
| Long-running execution | Autopilot driver | Durable result, evidence, reviews, and status |
| Final acceptance and presentation | Handoff contract, performed by the Autopilot closer or a proportional standalone reviewer | Proof bundle and decision surface |
| External work memory | Tasks | Optional task references and write results |

Only two durable lifecycle artifacts require operator review and confirmation:

1. A durable acceptance contract when work must cross contexts.
2. An Autopilot execution plan, including its evidence plan.

Approval data, evidence indexing, review commit, and progress live in existing
machine state. Proof bundles and HTML pages are derived outputs. Agents must not
maintain parallel documents that repeat the same fact.

There are exactly two approval receipts:

1. An acceptance receipt when a durable acceptance contract is confirmed.
2. A plan-approval receipt for Autopilot.

There are no task, chunk, capture, evidence, review, Handoff, or completion
receipts. Receipts contain only a schema version, relevant content digests, and
confirmation time. They are invisible unless approval becomes stale.

Each implemented skill should contain concise **Consumes**, **Produces**, and
**Does not own** sections. Those local contracts become authoritative when
this brief is retired. Do not copy this cross-skill brief into each
`SKILL.md`. A final skill contains only its discriminating discovery boundary,
essential local behavior, artifact contract, non-obvious invariants, and
bundled-command entry points. Conditional schemas and procedures belong in
focused templates, prompts, or references. Once those local sources and the
integrated journeys are authoritative, delete this brief.

## Intake contract

### Purpose

Intake turns an existing conversation into a durable, operator-confirmed
acceptance contract when decisions must be reconciled or handed to another
context. It is not the required answer to every ambiguity. One or two questions
that the current agent can resolve and immediately act on remain conversation.

Intake starts from what is already known. It must not interview the operator
from a blank slate or ask them to reconfirm settled facts.

### Intake owns

- Observable outcomes and exclusions.
- Material boundaries and constraints.
- Acceptance scenarios: what the operator wants to see to judge the result.
- Honest limitations of proposed demonstrations.
- Consequential defaults and their blast radii.
- Exceptional operator acts involving authority, credentials, spend,
  irreversible changes, or necessary manual validation.
- Explicit operator confirmation of the whole contract.

### Intake does not own

- Architecture or decomposition.
- Tests and implementation checks.
- Capture tools, commands, fixtures, or environments.
- Staffing, transports, retries, or run bounds.

### Acceptance scenarios

The operator should not have to invent evidence. The intake agent proposes a
small set of demonstrations at the boundary where a user or operator would
observe the promises. A scenario may cover several related promises. Each
proposal explains any material limitation.

The operator may accept, reject, strengthen, replace, or add demonstrations.
The agent challenges evidence that cannot support its claim: a screenshot does
not establish database preservation, and a unit test does not establish that a
page renders correctly. If the operator knowingly accepts weaker evidence, the
limitation becomes an accepted gap or waiver.

Present the proposed acceptance set in one compact recap. Low-risk,
operator-stated expectations may be confirmed by the final all-ok. Ask
individually only when a demonstration is costly, materially weak, requires an
operator act, or represents an agent-introduced expansion. Do not create a
separate confirmation interaction for every promise.

Keep acceptance evidence separate from engineering verification. The operator
confirms what affects their decision; the planner or implementer autonomously
adds tests, type checks, linters, invariants, and other engineering controls.

### Durable acceptance contract

When durability is warranted, record:

- Goal in the operator's language.
- Observable outcomes and exclusions.
- Acceptance scenarios and their covered promises.
- Material limitations and accepted gaps.
- Consequential decisions, defaults, blast radii, and provenance.
- Exceptional operator acts.
- Explicit waivers, if any.
- One acceptance receipt after the operator's final all-ok.

The recap should normally fit on one screen. Treat that as a UX warning, not a
mechanical failure: compact or split genuinely separable scope rather than
forcing the operator through a larger form.

### Minimal bundled support

Do not build a public multi-verb Intake workflow for symmetry. Start with one
deterministic operation used only for durable handoff:

```text
intake finalize <contract> [--json]
```

It checks structure, unfinished placeholders, unresolved material decisions,
uncovered acceptance expectations, and unmarked expansions. After explicit
operator confirmation it records the narrow acceptance receipt. The skill may
use internal helpers to create or render the artifact, but add public verbs only
after dogfooding shows repeated friction.

The command cannot determine semantic consistency or confer authority. The
concierge invokes finalization only after the operator's explicit all-ok.

## Planning contract

Autopilot planning uses one fresh strong planner. It reads the confirmed
acceptance contract and repository, not the exploratory conversation, and
produces a plan concrete enough for the operator to reject.

### Planner owns

- Material architecture, components, interfaces, and data shapes.
- Chunks, tasks, dependencies, and done-when criteria in the machine plan.
- Engineering verification.
- The evidence plan: coverage, tools, fixtures, environments, replay recipes,
  capture timing, and artifact expectations.
- Role and effort requests.
- Expected dispatch shape and bounded maximum exposure.
- Preflight requirements.
- Exceptional operator acts the run may require.

### Planner constraints

- Every accepted expectation has sufficient evidence coverage or an explicit
  gap returned before approval.
- One evidence-plan item may cover several expectations when the mapping is
  clear; an expectation may use several items.
- Evidence capture may be part of implementation, verification, QA, or closer
  work. A dedicated capture task is optional.
- The planner may add stronger or additional evidence without returning to
  Intake.
- It may change tools or recipes while preserving the accepted demonstration.
- It may not narrow, substitute, or weaken an accepted demonstration.
- A gap that changes the product promise or acceptance bar returns to the
  concierge, which reopens Intake only for that delta and then redispatches the
  planner.
- A purely architectural question is the planner's job. The plan makes a
  material decision visible for approval; it does not bounce ordinary design
  judgment back to Intake.

Substantive plan feedback always returns to a fresh planner-role context. The
concierge may repair formatting defects but must not silently rewrite
architecture, evidence, decomposition, or staffing decisions.

A revision dispatch receives the confirmed acceptance contract, the current
plan, the operator's feedback verbatim, relevant new repository observations,
and the reason the previous plan was rejected. It excludes the exploratory
conversation. Fresh context means revising the existing plan without inheriting
its author's assumptions, not planning again from nothing. New observations may
inform the revision but cannot silently change accepted outcomes or evidence;
contradictions reopen Intake only for the affected delta.

Do not add a separate plan reviewer initially. The fresh planner and explicit
operator review are the first gate. Incremental review and final acceptance
remain later gates.

### Operator plan page

Show only what can change the operator's approval:

- Outcome and observable done state.
- Material design decisions and boundaries.
- Acceptance-evidence coverage and material limitations.
- Resolved roles, models, efforts, constraints, and expected dispatch range.
- Bounded maximum exposure without invented dollar precision.
- Exceptional operator acts.
- Material risks and rejected alternatives.

Detailed task graphs, IDs, commands, and checks stay in the machine plan or
collapsed diagnostics. Ordinary plan approval and reading the completion page
are not “operator acts” to list and price.

### Plan approval receipt

Plan approval is durable but invisible:

```text
autopilot approve
```

The receipt records the acceptance-contract digest, plan digest, semantically
approved staffing digest, schema version, and approval time. Staffing includes
role, model, effort, cost or availability constraints, and sandbox or authority
implications. It excludes executable paths, adapter details, unrelated roster
contents, and transient availability.

`autopilot start` refuses to run without a current receipt. Reapproval is
required when requirements, product behavior, material design, evidence bar,
model, effort, cost envelope, sandbox, or authority changes. Harmless CLI-path,
adapter, or equivalent-transport changes require preflight again but not
operator reapproval.

## Delegate contract

Delegate converts a role and optional effort into a validated dispatch
specification. It is infrastructure, not an operator workflow.

Delegate owns the roster, role and effort resolution, unavailable bindings,
vendor command construction, local command-shape validation, and preferred and
fallback transport descriptions. It does not choose work, assign roles, author
prompts, own retries, or change a binding during a run.

Keep the initial public interface small:

```text
delegate resolve <role> [--effort E] [--json]
delegate doctor [--role <role> --effort E]
```

`resolve --json` includes the constructed fallback command, so a separate
`command` verb is unnecessary. Move Claude, Codex, and generic construction out
of Autopilot and into Delegate adapters. Unknown roles and
`unavailable = "reason"` are hard configuration failures. `doctor` is local
and deterministic; it spends no provider call.

The caller owns prompt assembly, process lifetime, timeout, redaction, and
outcome classification. Native subagents remain harness actions. The caller
records whether the actual transport was native, CLI, or another configured
channel and any requested property that transport could not honor.

## One-sitting execution and bounded delegation

One-sitting work remains supervised by the concierge. It does not acquire a
flight plan merely because a different agent implements it. Simple work and
questions resolved locally stay with the current conversational agent.

When durable Intake was necessary, dispatch the configured `implementer` by
default unless the current session is explicitly known to satisfy that role's
binding. A specialist role overrides the general implementer when the work
materially requires it. If the current binding is unknown, dispatch. The
operator may explicitly ask the current agent to continue. This is a staffing
default, not another operator gate and not a comparison of model-name strings.

The dispatch receives the confirmed conversation or durable acceptance
contract and the relevant repository context. It returns code, checks, and
evidence upward. The concierge verifies the result and owns the completion
surface. This staffing decision is not another operator gate.

## Autopilot execution contract

Autopilot executes an approved plan on a durable unattended loop. It composes
Intake, planning, Delegate, and Handoff without taking over their judgments.

### Required inputs and preflight

Autopilot requires a confirmed durable acceptance contract, a valid execution
plan, a current plan-approval receipt, and resolvable staffing.

Preflight checks:

- Every actual `(role, effort)` combination that may be dispatched.
- Every required CLI through Delegate.
- Every evidence and verification prerequisite in the plan.
- Every command shape required by the plan.
- Approval digests and approval-relevant staffing drift.

Remove paid smoke launches, `--no-smoke`, and the ordinary
`--no-preflight` escape hatch. The first real dispatch is the connectivity
test.

### Failure classes

- **Config:** invalid flag, missing executable, unavailable model,
  authentication required, invalid roster, or approval-relevant drift. Stop
  immediately, consume no attempt or iteration, notify once, and give one
  recovery action.
- **Infrastructure:** rate limit, capacity, quota window, or transient network
  failure. Consume no attempt or iteration; use bounded pause-and-retry.
- **Work:** the agent ran but did not complete valid work. Consume an attempt
  and use task retry and replanning policy.

Record whether each work attempt advanced the branch. A retry-capped planner
must know how many attempts produced commits so it can distinguish progressive
partial work from a dead approach.

### Review and landing

Chunk reviewers perform incremental implementation checks against the fixed
must-fix bar. At landing, one fresh closer performs whole-result acceptance and
the Handoff independent-review contract: it reviews the committed diff,
attacks the evidence rather than its captions, judges against the acceptance
contract, records gaps, and authors the decision-ready result.

The closer is the Handoff reviewer for an Autopilot flight. Handoff validates
and renders its output; it never dispatches a third review layer at landing.

### Status

Any fresh agent in the repository can run `autopilot status --json` and answer
“how is it going?” without the original chat. Human output contains the goal,
progress by meaningful milestone, current work, driver health, genuine
questions, and exactly one next action:

- `Next: nothing needed.`
- `Next: answer “Which payment environment?”`
- `Next: fix the reviewer binding, then restart.`
- `Next: read the completion page.`

Task IDs, dispatch logs, and event history stay in JSON or diagnostics. They do
not appear on the default operator surface.

## Handoff contract

Handoff carries an evidence obligation through the work, then turns the result
into the smallest proof and review surface that supports the operator's
decision. It consumes acceptance and evidence plans; it does not retroactively
define success or add another approval gate before implementation.

### Proportional modes

| Need | Result |
| --- | --- |
| Diff and focused checks are sufficient | No Handoff |
| Behavior needs demonstration but is easy to judge | Compact proof: claim, capture, replay recipe, limitation |
| Work is risky, long, architectural, inbound, or difficult to judge | Decision page plus one independent review |

An Autopilot worker never creates a separate Handoff. It captures assigned
evidence into the flight. The closer supplies the single final review and
Handoff content at landing.

For standalone page-sized work, a fresh context reviews the committed diff and
attacks the evidence. Review the existing clean tree read-only by default. Use
a disposable checkout when review must mutate the tree or for inbound untrusted
work. Fix above-bar defects and recheck affected claims; do not run another full
review unless material unreviewed changes or unresolved above-bar findings make
it necessary.

### Proof bundle

A proof bundle contains:

- Claims in product language.
- The accepted demonstrations they cover.
- Evidence artifacts captured at the reviewed commit.
- Replay recipes.
- Explicit gaps: what was not observed, or `none` when coverage is complete.

One bundle entry may cover several claims when the relationship is clear.
Additional evidence is welcome. Weaker substitution is not. Missing or stale
accepted evidence is a gap, never a reason to lower the bar at completion.

### Minimal bundled support

Start with one happy-path operation:

```text
handoff finish <workspace> [--json] [--no-open]
```

It validates structural honesty, applies the cumulative media budget, renders
the appropriate compact proof or page, opens a page when one is warranted, and
ends with the next action. Internal helpers may create workspaces, generate
review prompts, or render pages. Add public verbs only after the vertical slice
shows a repeated need.

Validation checks coverage, artifact existence, replay recipes, commit and
review freshness when applicable, cumulative media size, unfinished
placeholders, and obvious internal vocabulary. It does not decide whether
evidence is persuasive; that remains reviewer or closer judgment.

Handoff owns the proof-bundle contract and decision-page renderer. Autopilot
consumes it at landing rather than Handoff depending on Autopilot. Default
pages contain only what changed, proof, material gaps or decisions, and
meaningful follow-ups. They omit tasks, chunks, dispatches, event logs, and
manufactured manual checks, concerns, gaps, or friction.

## Tasks contract

Tasks is optional durable memory. It may supply a confirmed acceptance
contract, receive one, and receive follow-ups. It never owns requirements,
planning, scheduling, or execution. Use it only when tracked work is present or
requested. A tracker failure stops the tracker operation, not otherwise
authorized product work.

Complete the existing command with `tasks doctor`. It reports config, backend,
reachability, authentication, and repository label. Default list output always
includes one compact lifecycle count. `add` preserves exact idempotence and
offers non-blocking near-duplicate hints. Every backend failure gives one
recovery action.

Do not run `tasks doctor` before every normal operation. It is for explicit
diagnosis and actionable recovery after configuration or connectivity failure.

## Common command experience

Do not add a public command merely because sibling skills have one. Bundle code
only when deterministic execution avoids repeated reinvention or protects a
real invariant.

Commands that do exist share these properties:

- Concise human output by default; stable `--json` for composition.
- One recovery action on failure.
- One next action on status-like output.
- Atomic state writes.
- No paid model call during diagnosis or preflight.
- No command grants authority merely by existing.
- Internal IDs in machine output; subject names in human output.
- Failure classes distinguish configuration, transient infrastructure, invalid
  work, and operator decisions where applicable.

Keep each skill self-contained under the open agent-skills layout. Compose
through durable artifacts and stable command interfaces rather than another
skill's private Python modules. Autopilot has two genuine dependencies:
Delegate for dispatch resolution and Handoff for landing. Installation and
preflight verify them.

Bundled Python is 3.11+ standard library only. Shell entrypoints use
`#!/usr/bin/env bash` and remain compatible with Bash 3.2.

## User journeys

### 1. Exploration that never becomes work

The operator asks whether local-first sync is feasible. The agent probes the
storage layer and discusses options. The operator does not decide to build it.

Expected: no lifecycle skill, artifact, task, or implied commitment.

### 2. A simple change after “go ahead”

The operator asks why a label is misspelled, then says “go ahead and fix it.”
The current agent edits it, runs a focused check under a timeout, and reports
the result.

Expected: no Intake, Autopilot, Handoff, Delegate, or Tasks ceremony.

### 3. A small visible fix

The operator asks to correct a button's disabled color. The intended state is
clear. The current agent changes it, runs the focused UI check, and captures a
small screenshot because that is the natural verification.

Expected: no lifecycle skill. The screenshot is ordinary proof, not a page.

### 4. One or two local questions

The operator asks for a clear one-sitting change but one behavior is ambiguous.
The concierge asks the question directly, receives the answer, implements, and
reports the result.

Expected: no durable Intake merely because a question was asked.

### 5. Significant one-sitting work

After exploring checkout behavior, the operator says “build the retry flow.”
Several acceptance decisions remain, so Intake proposes compact scenarios for
successful retry, terminal failure, and the limitation of the test payment
environment. The operator confirms one recap.

Because durable Intake was necessary, the concierge dispatches one bounded
configured implementer through Delegate unless the current session is
explicitly known to satisfy that binding. A specialist overrides it when the
work materially requires one. The concierge verifies the result. A compact
proof is enough unless the risk or review difficulty warrants a page and one
reviewer.

Expected operator surfaces: one acceptance recap and one proportionate
completion account; no flight plan.

### 6. A full unattended flight

After feasibility discussion, the operator says “build the sync engine while I
am away.” Intake turns unsettled acceptance decisions into one confirmed
contract. The concierge dispatches a fresh planner through Delegate. The
planner writes the design, evidence coverage, tasks, staffing, and bounds. The
operator reviews the compact plan page.

Substantive feedback returns to a fresh planner-role context. An acceptance gap
returns to Intake only for that delta. After approval, the concierge records
the plan receipt and starts the driver. The operator may close the chat. Chunk
reviewers check increments; the closer performs final acceptance and Handoff
review once, then produces the completion page.

Expected operator surfaces: acceptance recap, plan page, genuine escalation
only if needed, and one completion page.

### 7. Requirements already exist

The operator selects tracked work containing a confirmed acceptance contract.

Expected: do not repeat Intake. Validate the existing confirmation, decide
execution, staffing, and completion needs independently, and continue at the
first missing boundary.

### 8. Plan feedback

The operator says the plan's storage boundary is wrong.

Expected: the concierge returns the feedback to a fresh planner-role context
and presents the revision. It does not rewrite the design itself. If the change
affects product promises, reopen only the affected Intake decisions first.

### 9. A fresh agent answers “how is it going?”

The original chat is closed. Another agent opens in the repository and the
operator asks for progress.

Expected: it reads `autopilot status --json` and answers with goal, meaningful
progress, current activity, whether anything is needed, and one next action.

### 10. A stale binding

The first real dispatch rejects an obsolete effort flag.

Expected: config failure stops immediately, consumes no task attempt or
iteration, and gives one notification and recovery action. It does not enter
the transient-provider wait loop.

### 11. Inbound review

The operator asks to review another branch or pull request.

Expected: Handoff enters inbound mode directly, reconstructs the claimed
acceptance contract, reviews the diff under appropriate isolation, assesses
the evidence, and presents one decision page. It invokes neither Intake nor
Autopilot unless the operator separately asks to implement changes.

### 12. Backlog work

The operator asks to file an idea or garden tasks.

Expected: Tasks is the entry point. Intake is offered only when significant
work is being shaped across decisions or contexts. A backend outage does not
block unrelated work.

## Implementation strategy: prove the vertical slice first

Do not build a polished distributed workflow framework before exercising the
experience. Implement the smallest complete unattended journey, dogfood it,
then add auxiliary commands only where observed friction warrants them.

### Slice 1: contracts and the happy path

1. Rewrite the five `SKILL.md` descriptions and contracts around independent
   routing, shared vocabulary, and the ownership in this brief.
2. Add the minimum durable acceptance format and `intake finalize` support.
3. Add minimum Delegate resolution and vendor command adapters.
4. Add semantic plan approval, config failure classification, deterministic
   preflight, and remove paid smoke launches and bypass flags.
5. Make the closer perform final acceptance and the Handoff review contract;
   render a minimal decision page without operational appendices.
6. Exercise the complete journey:

   ```text
   conversation
   → acceptance contract
   → fresh planner
   → plan approval
   → driver
   → status from a fresh agent
   → closer/Handoff page
   ```

Run this journey after each boundary becomes usable rather than waiting for all
commands to be complete.

### Slice 2: harden what the journey exposed

- Fix observed artifact, prompt, or routing friction.
- Validate every actual role-effort combination.
- Record partial-progress commits for replanning.
- Add approval-relevant staffing display and drift behavior.
- Add restart-without-duplication coverage.
- Finish config versus transient-infrastructure recovery.

Run the full journey again.

### Slice 3: proportional standalone paths

- Add bounded one-sitting Delegate dispatch.
- Add compact and page-sized standalone Handoff paths.
- Switch standalone review to clean-tree read-only by default.
- Add the cumulative media budget.
- Add only the public helper verbs demonstrated necessary by use.

Run the relevant one-sitting and inbound journeys.

### Slice 4: optional ecosystem polish

- Add `tasks doctor`, near-duplicate hints, lifecycle counts, and recovery
  actions.
- Improve diagnostic surfaces without expanding the default operator page.
- Update `install.sh`, installation tests, and installation documentation for
  the final command set and declared dependencies.
- Move the canonical evidence ladder into `docs/OPERATOR-SURFACE.md` and check
  every restatement.

Once the skills and user documentation are authoritative, remove this brief.

## Acceptance criteria

### Routing

Forward-test behavior with fresh agents rather than matching prompt wording:

| Prompt | Expected route |
| --- | --- |
| “Would offline sync be feasible here?” | Explore; no lifecycle skill |
| “Okay, fix that typo.” | Implement normally; no lifecycle skill |
| “The behavior is clear; build this small endpoint.” | One-sitting execution; no automatic Intake or Autopilot |
| “Build the checkout retry flow; we still need to settle failure behavior.” | Direct questions or Intake by decision/context count; then supervised execution |
| “Implement this confirmed work while I am away.” | Skip repeated Intake; fresh plan and Autopilot |
| “How is the flight going?” | Autopilot status and one next action |
| “Review this pull request and show whether it works.” | Handoff inbound mode |
| “File this idea for later.” | Tasks |
| “Why can’t the reviewer role launch?” | Delegate doctor |

### Artifact and approval invariants

- An unattended flight cannot start without confirmed durable acceptance and a
  current plan approval.
- Every accepted expectation has explicit sufficient evidence coverage or a
  visible gap; coverage may be many-to-many.
- Evidence does not require a dedicated task or one artifact per promise.
- Only acceptance and plan approval create receipts.
- Approval drift follows operator-relevant semantics rather than file paths or
  transient transport details.
- Every completed claim has current evidence, a replay recipe, and an explicit
  gap or complete coverage.
- Internal IDs never appear on normal operator surfaces.
- No default completion page contains task, chunk, dispatch, review, or event
  appendices.

### Review and failure invariants

- Autopilot has incremental chunk review and one closer/Handoff final review,
  never a third landing review.
- Standalone compact proof does not automatically require an independent
  reviewer.
- A stale flag or expired authentication fails on first dispatch with one
  recovery action, no pause, and no consumed work budget.
- A transient provider outage uses bounded waiting and consumes no work budget.
- A failed attempt is distinguished from progressive partial work.
- Killing and restarting the driver loses no completed work and duplicates no
  task.
- A tracker outage does not block unrelated authorized work.

### Operator experience

- Simple work creates no lifecycle artifact or skill ceremony.
- One or two local questions do not create durable Intake by themselves.
- Durable Intake normally fits on one screen and does not ask for tools.
- One-sitting delegation creates no plan gate or extra operator surface.
- The plan page shows only approval-relevant design, evidence, staffing,
  bounds, risks, and exceptional acts.
- Status can be understood by a fresh agent and ends with one next action.
- Completion uses an ordinary response, compact proof, or full page according
  to what changes the operator's decision.
- No surface manufactures a manual check, concern, gap, or friction entry.

### Test discipline

- Wrap every test invocation in `timeout`.
- Unit-test deterministic validation, digests, adapters, classification,
  rendering, and state transitions.
- Use fake agents for unattended loop and recovery scenarios.
- Keep real Claude and Codex provider checks opt-in under integration tests.
- Test semantic invariants and observable behavior, not exact prose or heading
  regexes.
- Run the full vertical journey after each major boundary is usable.

## Definition of done

The redesign is complete when a fresh agent can start from any natural entry
point, invoke only the capabilities needed, cross context boundaries through
the two minimal authored artifacts, and finish at the smallest useful operator
surface without this document or the original conversation.

At that point:

- Each `SKILL.md` is again authoritative.
- Bundled code protects demonstrated deterministic invariants rather than
  enforcing symmetry.
- Cross-skill dependencies are explicit and checked.
- The vertical and proportional user journeys pass.
- This transitional brief is deleted.
