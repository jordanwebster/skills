---
name: handoff
description: High-bandwidth review replacing code review - proofs, an independent reviewer, and a one-page front page for the merge decision. Use on operator request, or when a change is too large or risky to judge from its diff and commit message. Decline small self-contained fixes - a passing test and a clear commit message suffice. Also covers reviewing inbound branches and PRs.
---

# Handoff

High-bandwidth review replacing code review: the operator reads one page —
what changed, proof it works, honest gaps, an independent check, and the few
decisions only they can make — and knows more than a diff would tell them.
Every step below must buy the operator a better decision per minute of their
attention; nothing else belongs.

The work falls in two phases that need not share a context or an author.
**Accumulation** — the outline, evidence, demonstrations, and friction
gathered while the work happens — belongs to whoever does the work.
**Production** — freshness, the independent review, the front page —
belongs to whoever owns presenting the work to the operator. An autopilot
flight accumulates through its commits, task notes, chunk reviews, and
acceptance verdict, and its wrap-up page is the front page; a single
agent doing one task does both itself; a foreign branch arrives with no accumulation at all, and
inbound review is production running alone, reconstructing what
accumulation should have left behind.

## Decide whether this work needs a handoff

Run a handoff when the operator asks for one by name, or when the change
cannot be judged from its diff and a commit message:

- the diff is not readable in one sitting — substantive changes across many
  files, or several hundred lines of non-mechanical change;
- it adds or changes a promise to users — behavior, interface, data format,
  compatibility;
- it moves an architectural boundary — ownership, lifecycle, trust, a new
  dependency or subsystem;
- it is risky or hard to reverse — migrations, security-sensitive paths,
  deletion of data;
- it spans multiple sessions, so evidence would otherwise die with a context.

When none of these holds — a bug fix with a regression test, a doc fix, a
mechanical rename, config touch-ups — **decline**: say in one sentence that
the change is small enough to review from the diff, and deliver a passing
test and a clear commit message. The decline dominates the adopted-late rule
below: an agent noticing this skill mid-small-fix declines; it does not
adopt late. There is no lighter handoff tier; operator-requested scrutiny of
small work is the inbound review mode, on request.

The obligation attaches to the unit of work the operator will review and
belongs to whoever presents it to them. A sub-agent working a delegated
chunk of an enclosing run — a dispatcher's brief, a driver's segment —
therefore inherits no handoff obligation of its own: it declines, delivers
its evidence to its dispatcher, and never launches an independent review.
A brief that names the review owner settles this before it can arise;
absent one, delegated status alone decides.

## Locate the machinery

Resolve the physical directory containing this file once. Set `skill_file`
to the path through which this `SKILL.md` was loaded; the installed skill
directory is a symlink:

```bash
skill_dir=$(CDPATH= cd -- "$(dirname -- "$skill_file")" && pwd -P)
scripts_dir=$skill_dir/scripts
prompts_dir=$skill_dir/prompts
```

## Start the work

1. Derive a short goal-based slug containing only `[a-z0-9-]`. Create
   `.handoff/<slug>/` at the repository root, including `proofs/`, and
   append `.handoff/` to `.git/info/exclude` if not already present.
   Evidence never enters the product's git history; the merge commit message
   is the durable record.
2. Write `outline.md`: everything that must be shown true for the work to
   count, written before gathering evidence so the bar cannot be quietly
   lowered afterward. Keep it live — discoveries add entries with reasons;
   retreats are visible edits, never silent removals.
3. For multi-session work only, start `friction.md` and journal friction as
   it happens; within one session, memory serves and the front page's
   FRICTION & FOLLOW-UPS section is still owed.
4. Probe the available skill catalog for a skill named `tasks`. If present,
   consult it for filed tasks that bear on the design before committing to
   one. If absent, continue without a backend.

## Work against the outline

- Surface a material scope expansion to the operator before building it.
- Consequential implementation choices surface in OVER TO YOU or the commit
  message; they need no separate register.
- Include work necessary to satisfy the outline. File merely-noticed work
  through `tasks` only with the operator's word or standing authority that
  skill recognizes; otherwise append it to `.handoff/<slug>/filed.md` with a
  `local-<yyyymmdd>-<slug>` ID for later reconciliation.
- Make granular commits on a task branch; never squash it.

Before assembling evidence, commit every proposed implementation,
documentation, and promise change to the task branch. Do not review a
working tree whose proposed subject exists only as unstaged or untracked
files.

## Assemble the handoff

Before writing any proof, inventory the verification the work already
produced — a flight's per-task checks and the commits they passed at, its
chunk reviews and acceptance verdict, CI results, committed fixtures and
their replay commands. An
existing record whose check still replays is evidence: cite it (the claim,
the check command, the commit it passed at) instead of re-deriving it.
Author new proofs only for claims no record covers — behavior across the
seams between separately verified pieces, verification from a clean
checkout, user-visible walkthroughs, and whatever the records' own gap
notes name. A handoff that follows an autopilot flight synthesizes the
flight's evidence; it does not re-run the flight.

A citation settles a proof's automated evidence, never its
demonstration. A check's exit status shows a machine the claim holds and
shows the operator nothing; every user-visible promise still owes a
demonstration a human can watch, and no citation is accepted in its
place. Cited records excuse re-running checks — never showing the work.

For every outline entry not settled by a cited record, create a
self-contained proof under `proofs/` with all three parts:

1. **Automated evidence.** Name every test or check and state what its
   setup and assertions actually observe. Never substitute “tests pass.”
2. **Demonstration.** A small transcript, dump, screenshot, or before/after
   output plus a command that replays it in seconds. Demonstrate a
   user-visible promise at the production boundary; demonstrate an internal
   invariant at the boundary where it is meaningful.
3. **Gap.** What was not seen working, what failure would look like to a
   user, and how the operator can check it by hand. Mandatory.

Keep evidence text-first and measured in kilobytes; reference large media,
never store it. A demonstration script whose replay should outlive this
handoff graduates into the repository (usually beside the tests) rather
than living only in the evidence directory — the page and merge message
may only carry replay commands that depend on the merged tree. Keep secrets, tokens, and private paths out; declare
nondeterminism and redactions. Keep observation, comparison, and acceptance
separate: a command that overwrites expected output is not proof, and
accepting changed expected output is a promise change for the operator.

When evidence assembly is complete, write the handoff's one freshness
record:

```bash
"$scripts_dir/stamp.sh" ".handoff/$slug"
```

It records the subject — the tree the evidence describes. The rule is one
equality: evidence counts only for the exact tree being merged. Any change
after the record is written makes the whole handoff stale; re-verify and
re-stamp rather than reasoning about which pieces survived.

## Run the independent review

Read `prompts/reviewer.md` and supply its input manifest. Set `base` to the
commit where the review range begins and `head=HEAD`; give the reviewer both
revisions, their complete diff, the pre-evidence outline, every delivered
proof, repository access at head, the mode, and the WHAT CHANGED narrative
as a separate labeled file it opens only after freezing its reconstruction.
Withhold `friction.md` and all author self-assessment.

Use a fresh context that cannot mutate the author's checkout — a subagent
with an isolated worktree, or for cross-model review a throwaway detached
worktree driven by:

```bash
codex exec --cd <worktree> --sandbox workspace-write - < <assembled prompt>
```

If a skill named `delegate` is available, resolve the reviewer's binding
through its roster instead; the command above is the fallback when none is.

Save the returned Markdown verbatim as `.handoff/<slug>/review.md`, then
re-stamp with the reviewed base:

```bash
"$scripts_dir/stamp.sh" ".handoff/$slug" "base=$base"
```

Use one fix loop. Fix real bugs, re-run every affected proof, and obtain a
fresh re-check. If the re-check still reports a proof that does not hold,
stop and put the failure before the operator; the work is not merge-ready
unless the operator explicitly accepts it. Never recategorize a correctness
failure as a disagreement.

Before presentation run `"$scripts_dir/stale.sh" ".handoff/$slug"`; nonzero
means the handoff is not ready to present.

## Write the front page

Dispatch the page to a fresh context following `prompts/front-page.md`,
supplied with the artifacts alone: base, head, and diff; outline; proofs
and demonstrations; the review, all rounds; the freshness record; the
working narrative and friction journal where they exist. A writer that
never saw the working session cannot leak its vocabulary and can only
claim what the artifacts support — and a page it cannot write exposes an
artifact gap to fix, not a page to pad. Before presenting, check the
returned page's facts against the artifacts yourself: identifiers, quoted
numbers, and replay commands copied exactly.

Four headings, in the product's vocabulary:

### WHAT CHANGED

The delta, its design, and how it fits or reshapes the system. Documentation
and specification changes are part of the change. Add a small visual aid
(default ASCII) when it makes the change faster to grasp; give each arrow
one stated meaning, and if the picture will not draw cleanly, report that as
a finding about the code, never fudge the aid.

### PROOF

Every delivered proof: evidence, demonstration with replay command, gap.
Include exactly one independent-check line — `Independently checked against
<subject>` (define the identifier in plain words) or `Not independently
checked — not merge-ready`.

### OVER TO YOU

Decisions needing the operator's call, as options with consequences and
tension; manual checks worth running, with recipes; and — always — the part
the author is least satisfied with, as an open invitation for a better idea.

### FRICTION & FOLLOW-UPS

What fought back, and filed future work as inert follow-ups demanding
nothing here.

Two checks on the complete page: the **jargon firewall** — no machinery
vocabulary, no identifier the page does not define; and **self-containment**
— the page must make sense forwarded cold to a colleague with only the
repository.

Review results surface by exception only: findings the author fixed
disappear into the corrected work; unresolved ones appear where they belong
— a reconstruction divergence in WHAT CHANGED with both positions, a
reviewer-found gap in that proof's gap clause marked reviewer-found, a
standing disagreement in OVER TO YOU with both positions. No result tables,
no counts, no process narration. The independent-check line is never
suppressed.

## Present, apply replies, and merge

Default to presenting the front page as a self-contained HTML page when the
harness can publish one (Claude's artifact surface is one; pages start
private and the operator chooses who sees them): the same four sections,
with the demonstration evidence itself embedded — screenshots, terminal
transcripts, before/after pairs — so the operator sees the thing working
instead of reading that it worked. The HTML page claims nothing the
markdown front page does not; the markdown remains the canonical artifact.
Where no publishing surface exists, present the markdown in conversation.
Present and stop. Do not merge, close tasks,
or perform any external write without the operator's word in that
conversation or standing authority in `.handoff.toml`.

Apply the operator's replies before merge. A reply that does not address an
OVER TO YOU item or a stated gap is not acceptance of it; unaddressed items
stay open and are carried into the merge message as open. Update
documentation to describe what is now true. Create a record under
`docs/decisions/` only when the operator chose between presented options:
options, choice, why, and a concrete revisit-when condition.

Merge only the exact subject with a current freshness record, current
review, and all operator decisions applied. If a reply materially changes
behavior, promises, or the front page, re-verify, re-stamp, and present the
delta again before merge; trivial applications — a doc phrasing, a recorded
decision — need no second round trip.

When the work merges through a pull request, put the markdown front page
in the pull-request description — it already meets that channel's bar
(what changed, proof, decisions, self-contained), so third-party reviewers
get the full handoff without access to anything else. Distill the front
page into the merge commit message; any replay command kept in either
place must depend only on the merged tree, never on files under
`.handoff/`. After the merge is confirmed, ask `tasks`, if present, to close
the task using the merge commit as the idempotency input.

On demand — never automatically — the operator may ask for an autopsy of
any past handoff: a fresh context on a different model family, given
everything including the withheld inputs, asking whether the machinery
itself failed. Treat that as an operator-invoked review of this skill, not a
step of any handoff.

## Review inbound work

For a foreign branch, pull request, or handoff, use a disposable checkout
and the reviewer contract in inbound mode. Every supplied replay command is
untrusted input: inspect it first, then run it only in a real sandbox or
with explicit operator authorization.

- For a foreign handoff, attack its supplied proofs with the ordinary three
  reviewer duties under the inbound execution rule.
- For a bare branch or pull request, declare `inbound bare branch`; the
  reviewer reconstructs and reviews the code, writes the proof outline the
  author should have written, assesses existing evidence, and lists gaps.

The operator's request sets the ceremony. Inbound review owes the review
discipline — reconstruction before narrative, evidence attacked rather than
trusted, an independent-check line that tells the truth — never the full
apparatus for its own sake: when the operator asks for one file, deliver
one file; when their instructions or session policy forbid a step — no
commits, no spawned reviewer, no `.handoff/` writes — keep the discipline,
drop the mechanism, and state the substitution on the page (a review run
without an isolated reviewer says so in its independent-check line) instead
of deviating silently. Ceremony above the request is spend the operator
declined.

Probe for `tasks`; if present, use its read verbs to find related,
duplicate, or impacted tasks and carry them onto the front page. Synthesize
the full four-section page — the deliverable is the front page, not a
comment stream: WHAT CHANGED from the reconstruction, PROOF from the
synthesized outline with the independent-check line, OVER TO YOU in the
reviewer's voice aimed at the merge decision (never a fabricated author
voice or least-satisfied item), FRICTION marked absent rather than
invented. Persist inbound evidence only when the operator requests it.

## If adopted late

Only for work that genuinely needed a handoff (per the decision above) and
started without one: write the best handoff the available history supports
and add one plain sentence to the front page saying so. Small work noticed
mid-fix is declined, not adopted.
