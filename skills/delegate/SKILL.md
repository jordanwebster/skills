---
name: delegate
description: Staffing policy - resolves role tags (planner, implementer, prober, reviewer, judge, ui-developer, qa-tester) to model bindings via an operator-owned roster, with escalation rules. Use when dispatching work to agents by role.
---

# Delegate

Which mind runs which piece of work, decided by policy instead of by
whatever happened to launch the run. Delegate owns two things: the role
contracts below and the shape of the operator's roster file. It owns no
performance record — the operator's own reading of results, and the
consuming run's ledger, are the evidence bindings change on. It owns no judgment loop: a
dispatcher consulting delegate is a lookup, and everything the operator ever
decides about staffing is decided in the roster file or at a plan gate —
delegate has no mid-run operator surface, structurally.

## The roster

Concrete bindings live only in the operator-owned roster file, resolved in
order: `$DELEGATE_ROSTER` if set, else `~/.config/delegate/roster.toml`.
Copy `templates/roster.toml` there to start. Each entry binds a role to a
CLI invocation, model, and effort; an entry may also record `effort_arg`,
the exact flag or config key its CLI accepts effort through (codex:
`-c model_reasoning_effort=<effort>`), so a dispatcher never needs per-CLI
knowledge. The roster always carries a `default`
binding: a role tag that matches no entry dispatches on `default` and the
mismatch is noted in the consuming run's records, so runs and roster can
version independently.

Agents propose roster changes as rows for the operator's explicit yes —
each row its own yes, never inferred from one successful flight. The roster
schema has no oracle or answer-key role and never will: verification
authority belongs to the operator personally and is not a staffing
question.

## The roles

| Role | Contract | Binding guidance |
| --- | --- | --- |
| `planner` | Fresh context; reads only confirmed requirements and the substrate; produces the plan | Strongest available; never economize here |
| `implementer` | Sweeps a context phase of ledger items against a recorded plan | Strong by default; the natural first candidate for cheaper-tier experiments |
| `prober` | Read-only reconnaissance: substrate probes, captures, corpus sweeps; parallelizable | Mid-tier; volume over brilliance |
| `reviewer` | Independent review of finished work; never the author; a cross-family check additionally requires a different model family than the author's | High floor |
| `judge` | Ephemeral forced choice on a trigger (retry cap, stall, revision batch); reads artifacts, decides, records, ends | Strongest available; contexts are tiny |
| `ui-developer` | User-interface implementation | Family-constrained in practice; record the constraint in the roster, not in prose |
| `qa-tester` | Pokes at the product like a human: common flows, naive usage; reports what broke and what tooling gaps blocked further testing | Cheap on purpose — a too-clever agent works around rough edges instead of reporting them |

qa-tester runs when a change is user-facing; when in doubt, run it — it is
cheap. Its findings become citable evidence in whatever end-of-work report
encloses the change, or a short note to the operator when none does; the
tooling gaps it hits are filed as inert task entries through a skill named
`tasks` when available and authorized, else an outbox row.

## Dispatch

A driver or dispatcher consuming delegate does exactly this per dispatch:
read the work item's role tag; look it up in the roster (falling back to
`default`, noted); launch the bound mind with the prompt its own machinery
assembled. Delegate never authors prompts and never selects work.

A brief dispatched into a repository whose own instructions trigger a
review skill states who owns that review — a sub-agent must never have to
infer its position in the run. The review skill's own rule (delegated
chunks decline and report evidence upward) is the backstop when a brief
forgets.

Effort resolves in the same mechanical order as the role: a phase's effort
tag from the plan if one exists (assigned by the planner, visible in the
staffing shape the operator approved), else the roster's default for the
role; an unknown value falls back to the roster default and is noted. A
worker never sets its own effort — effort is always assigned from outside,
by roster, plan, or a judgment context.

A binding names the **mind** — family, model, effort — not how to reach it.
Transport is the dispatcher's richest available channel for that mind: a
native subagent when dispatching from inside a harness of the same family
(a Claude session dispatches claude-bound roles as subagents, a Codex
session likewise for its own); the roster's CLI invocation when crossing
families or dispatching from a script; a shared agent bus when one is
configured — that slot is reserved for amux and empty until it exists. Same
mind, same prompt, whichever channel carries it. A native channel may
honor only part of a binding — Claude's subagents take a model override
but no effort setting; dispatch anyway and note the shortfall in the
consuming run's records, never silently rebind.

## Escalation

When a dispatch fails at its retry cap and the failure pattern says the
binding was too weak — mid-task judgment errors, not typos — the judgment
context escalates in two rungs: first raise effort one step on the same
model (the cheaper remedy, when the failure smells like too little
deliberation rather than an incapable mind), then re-dispatch one model
tier up, each used once and each recorded like any other judgment decision
in the consuming run's records. Repeated escalations on a role are a
roster proposal, put to the operator as a row; they are never a silent
rebinding.

## Deliberately absent

Delegate reads role tags from the artifacts of whatever run consults it. It
does not read task backlogs, pick up ready work, or start runs — that
orchestrator, if it ever exists, is a separate decision the operator makes
explicitly. Absence here is design, not omission.
