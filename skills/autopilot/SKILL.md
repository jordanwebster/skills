---
name: autopilot
description: Execute confirmed software work on an unattended loop of fresh agents when it spans contexts or must continue while the operator is away. Requires an approved plan; decline work that fits one sitting unless explicitly requested.
---

# Autopilot

Use Autopilot only for work that must outlive the current context or run while
the operator is away. The conversational agent remains the concierge: it
brings the operator one plan to review, records explicit approval, starts the
flight, and can later summarize durable status. Ordinary one-sitting work does
not need a flight.

## Command

Resolve this skill directory from the `SKILL.md` path, then use its single
entrypoint:

```bash
autopilot="$skill_dir/scripts/autopilot"
```

`$autopilot --help` lists the operational and task verbs. Prefer `--json` when
another agent will consume output.

## Consumes

- A confirmed acceptance contract and its adjacent compatible acceptance
  receipt, normalized through Intake's public `inspect --json` boundary. It may
  come from Intake or another compatible durable source; do not repeat
  alignment when the existing contract is already confirmed.
- A plan from one fresh planner-role context, including design, evidence
  coverage, staffing requests, bounds, chunks, and machine tasks.
- Explicit operator confirmation of the rendered plan.
- Delegate's public `resolve --json` result for every role-effort combination.
- Handoff's public `proof.json` contract at landing.

Planning reads the confirmed contract and repository, never exploratory chat.
Substantive feedback goes to a fresh planner context with the confirmed
contract, current plan, feedback verbatim, relevant new repository
observations, and why the plan was rejected. New observations may inform a
revision but cannot silently change accepted outcomes or demonstrations.

## Produces

- An approved plan receipt containing only acceptance, plan, and semantic
  staffing digests plus confirmation time.
- Durable untracked flight state under `.autopilot/` that any fresh agent can
  read with `autopilot status --json`.
- Committed implementation, checks, incremental milestone reviews, evidence, and
  one closer-authored Handoff proof bundle and decision page.

## Does not own

- Requirements or acceptance confirmation; Intake owns the durable contract.
- Model roster policy or vendor argv construction; Delegate owns both.
- Final proof schema or rendering; Handoff owns both. The closer is Handoff's
  single independent reviewer for a flight, so no third landing review runs.
- External task tracking; Tasks is optional memory and cannot block the flight.

## Start a flight

1. Run `autopilot init --goal "…" --requirements CONTRACT`. The contract must
   already have a current compatible acceptance sidecar. When confirmed intent
   exists but no receipt does, `intake finalize` can record it without repeating
   the Intake conversation.
2. Dispatch a fresh planner with `autopilot plan --dispatch`, or print its
   prompt with `autopilot plan --prompt` for native dispatch. Render with
   `autopilot plan`.
3. Route substantive feedback back through the planner:

   ```bash
   autopilot plan --dispatch --feedback "VERBATIM" --reason "WHY REJECTED" \
     [--observations FILE]
   ```

4. After explicit operator approval, run `autopilot approve`, then
   `autopilot start`. Start always performs deterministic preflight. There is
   no paid smoke launch and no ordinary bypass flag; the first real dispatch
   is the connectivity test.

The operator may close the original chat. Another agent answers “how is it
going?” from `autopilot status --json`, summarizing goal, meaningful progress,
current work, driver health, genuine questions, and its one next action.

## Flight invariants

- The driver dispatches fresh agents and never authors product decisions.
- It re-runs task and chunk checks itself, records state atomically, and seeds
  a plan only once.
- When a milestone's tasks finish, its bounded check, review, repairs, and
  recheck run before dependent implementation. A milestone is dependent when
  its tasks rest, directly or through other tasks, on the reviewed one's, so
  an unfinished must-fix holds exactly that work and nothing else. A blocked
  milestone does not prevent dependency-safe later work.
- Restart recovers durable in-progress work and accepts a task whose check
  already passes instead of dispatching it twice.
- Configuration failures stop immediately with one recovery action and consume
  no attempt or iteration. Transient infrastructure failures use bounded
  pause-and-retry and consume no work budget. Work failures consume attempts.
- A retry-capped planner sees whether prior attempts advanced the branch.
- A worker's `autopilot escalate` request first receives one bounded internal
  triage through the approved planner binding. Reversible, in-scope changes to
  implementation details, task dependencies, checks, or capture mechanics are
  resolved and recorded without interrupting the operator. Triage promotes
  only changes to accepted promises or material design, new authority or
  external consequences, meaningful spend or staffing changes, destructive
  acts, and genuinely ambiguous product trade-offs. An inconclusive pass is
  promoted rather than repeated.
- Evidence coverage is many-to-many. Capture may happen during implementation,
  verification, QA, or closing; no dedicated capture task is required.
- Every completed claim names accepted demonstrations, current artifacts, a
  replay recipe (command, steps, or accepted not-replayable reason), and an
  explicit gap or complete coverage.
- The closer performs bounded acceptance against the confirmed promise and
  current evidence, not an open-ended code review. Genuine gaps become tracked
  repair work and are audited again after completion; optional quality work is
  parked. A discovery that invalidates a planning assumption goes through one
  planner triage, which may reshape implementation work but must promote any
  change to accepted outcomes or material design. The approved iteration
  ceiling, rather than an audit-round counter, bounds convergence.

Workers use `autopilot task list | show | start | done | note | add | edit |
park | unpark | reset`. They request decision triage with `autopilot
escalate`; the dispatched planner alone resolves or promotes it with
`autopilot triage`. Only promoted questions appear to the operator, whose
answer is recorded with `autopilot answer`.

At landing, `autopilot status --open` opens Handoff's decision page. After the
operator has read it, `autopilot land` moves the final proof bundle, evidence,
and decision page to `.handoff/<flight>-<commit>/`, removes the remaining
untracked flight machinery, and prints parked follow-ups for optional filing.
Merge remains the operator's act.
