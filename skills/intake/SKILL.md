---
name: intake
description: Turn a vague or new piece of work into operator-confirmed requirements before building. Use when starting work whose requirements, scope, or success criteria are not yet pinned, or when the operator asks to shape work. Skip when requirements are already confirmed.
---

# Intake

Alignment before work: leave no ambiguity standing whose consequences the
operator has not accepted. Intake produces confirmed requirements; it never
plans, decomposes, or builds — those belong to whatever runs next.

## Proportionality

Match the ceremony to the stakes:

- **Small, self-contained work** — a bug fix, a doc change, a rename: intake
  is the conversation itself. Ask what is genuinely unclear, confirm, and
  proceed. No artifact.
- **Consequential work** — new behavior, changed promises, meaningful cost,
  or anything that will run unattended: produce a requirements record using
  `templates/requirements.md` and obtain the operator's marks on it.

## Probe before assuming

Ground defaults in observation, not guesses. When an assumption is checkable
by reading the substrate — the codebase, the data, the external system —
check it read-only first and state what was observed. Probe the whole
relevant corpus, never a sample; a sample answers confidently and wrongly.

A running probe does not block the conversation: present the rows it cannot
change while it runs, and hold back only those that depend on it. And a
probe result that contradicts something the operator stated never silently
shapes a default — the contradiction surfaces as its own row: here is what
you said, here is what the substrate shows, which is right?

## The requirements record

State the operator's intent as observable behavior in the operator's own
language: what a user will and will not be able to observe. Then list every
assumption as a row with four parts:

1. the question, in plain words;
2. the default that will be taken;
3. the blast radius if that default is wrong;
4. an explicit per-row mark: confirm or veto.

Where a row's sensible default depends on how another row is marked, say so
on the row. Where the option space is small, list the alternatives so a veto
can name its replacement in the same mark. And some questions cannot be
resolved by discussion at all — how an interaction should feel, which of two
shapes reads better; talking them out is where alignment sessions balloon.
Mark such a row **unresolvable by discussion**: its default is to build the
smallest throwaway probe or prototype that makes the question answerable,
and that build is itself an agent-proposed row needing its own yes.

Each row carries its provenance: **operator-stated** (restating something the
operator said) or **agent-proposed** (something the agent introduced).
Provenance decides how much attention a row demands — never whether approval
is explicit, because it always is. An operator-stated interpretation with a
small, reversible blast radius may sit on the record as a stated default
without its own question; its approval is the final all-ok, given over a
recap where it is visible. An agent-proposed expansion — new scope, new
guarantees, new spend, new authority — always gets its own question and its
own explicit yes, never bundled. And no third path exists: a decision is
never stated in passing prose and treated as approved because nobody
objected. An unanswered question is an open row, not a quiet yes.

Sort rows by blast radius, largest first, and keep them short and scannable;
a record the operator must scroll and reread has already failed. An
oversized record is a scope signal, not a longer meeting: propose splitting
the work and running intake per piece — the split itself an agent-proposed
row. Not every decision deserves its own question: a reversible choice with
a small blast radius is a stated default — still written on the record, and
covered by the explicit final all-ok like everything else; what it never
demands is an individual mark. Spend the operator's per-row attention where
reversal is expensive. Nothing, at any size, proceeds on silence alone: the
all-ok is an act, not an absence of objection. Define every term on the record
itself. Ask a genuine free-form question only when no default is safe.

Include a row for anything the operator will be asked to do later — an
account to authorize, a command only they may run, a review they must give —
so all operator involvement is agreed and priced up front. For greenfield
work, include a workspace row (default: a new repository under a location the
operator names or `~/source/<name>`). If the operator wants downstream work
to run without further review — for example, skipping a later plan
presentation — record that waiver as its own explicit row; never infer it.

## The conversation

Work from coarse to fine: settle the highest-level decisions first — the
goal's shape, its boundaries, the expensive commitments — and let each
answer open the more granular rows beneath it, prompting new probes where an
answer changes what must be checked. Back and forth is the healthy state;
presenting everything at once is not. Each round presents only the delta:
new rows, and rows an answer or a probe invalidated — never the whole
record again.

Put every decision as an explicit question, never as a statement that
scrolls past. When the harness offers a structured question tool (Claude's
AskUserQuestion is one) and it would make the round easier to answer —
listed alternatives become options, a veto-with-replacement becomes one
selection — use it; that is the agent's UX judgment call, and plain
conversation is always sufficient.

When no rows remain open, check the marked set for mutual contradictions —
decisions that disagree with each other cost a build to discover — and
surface any conflict as a final row. Then present the complete record once
for a single all-ok: settled rows as a scannable recap, nothing
re-litigated. That pass is the record's signature; it is the one time the
operator sees the whole record together, and it is what downstream work
trusts.

## Completion

Intake is complete when the final all-ok has been given and every question
put to the operator has its explicit answer. Rows that never demanded their
own question were approved by the all-ok over the recap where they were
visible; nothing was approved by going unobjected-to. The confirmed record is durable: attach it to the tracked task if
a skill named `tasks` is available and the operator authorizes the write;
when an unattended flight will follow (a skill named `autopilot`), hand
the record to it as a file so the planner and the final acceptance both
read the same words; otherwise hand it to the operator in conversation
and pass it to whatever runs next. A confirmed record is the input
downstream planning trusts — it must stand alone, readable by a fresh
context that never saw this conversation. Ambiguity that survives intake
is not resolved later by whoever hits it: downstream agents escalate it
back to the operator rather than guess, so every open question closed
here is one the run will not stop on.

Requirements can be confirmed asynchronously: a task the operator has already
endorsed row by row needs no second intake. Re-open intake only when new
ambiguity surfaces, and bring back only the new rows, not the whole record.
