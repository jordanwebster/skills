---
name: handoff
description: Present finished work for the merge decision on one page - what changed, proof it works with its gaps, an independent review, and the decisions only the operator can make. Use on operator request, or when a change is too large or risky to judge from its diff and commit message. Decline small self-contained fixes - a passing test and a clear commit message suffice. Also covers reviewing an inbound branch or pull request.
---

# Handoff

The operator reads one page and knows more than a diff would tell them:
what changed, proof it works, the honest gaps, an independent check, and
the few decisions only they can make. Every step here must buy the
operator a better decision per minute of their attention; nothing else
belongs.

## Locate the machinery

Set `skill_file` to the path through which this `SKILL.md` was loaded;
the installed skill directory is a symlink:

```bash
skill_dir=$(CDPATH= cd -- "$(dirname -- "$skill_file")" && pwd -P)
page=$skill_dir/scripts/page        # renders the front page to HTML and opens it
```

## Decide whether this work needs a handoff

Run one when the operator asks by name, or when the change cannot be
judged from its diff and a commit message: it is not readable in one
sitting; it adds or changes a promise to users; it moves an architectural
boundary; it is risky or hard to reverse; or it spanned several sessions,
so evidence would otherwise die with a context.

When none of these holds — a bug fix with a regression test, a doc fix, a
mechanical rename — **decline**: say in one sentence that the change is
small enough to review from the diff, and deliver a passing test and a
clear commit message. An agent noticing this skill mid-small-fix declines;
it does not adopt late.

The obligation attaches to the unit of work the operator will review and
belongs to whoever presents it. A sub-agent working a delegated chunk of
an enclosing run inherits no handoff of its own: it delivers its evidence
upward. An autopilot flight produces its handoff itself — its commits,
task notes, chunk reviews, and acceptance verdict are the accumulation,
and its wrap-up page is the front page; nothing below is re-run for it.

## While the work happens

Commit granular, present-tense commits on a branch; never squash. Write
down, as you go, what will have to be shown true for the work to count —
an outline in your working notes is enough — so the bar cannot quietly
drop once the evidence is in. Keep evidence text-first and measured in
kilobytes under `.handoff/<slug>/` (untracked; add `.handoff/` to
`.git/info/exclude`), or inline on the page when it is small. No secrets,
no private paths; declare redactions and nondeterminism.

A **proof** has three parts and is not complete without the third:

1. **Automated evidence.** The tests or checks, and what their setup and
   assertions actually observe. Never "tests pass".
2. **Demonstration.** A transcript, dump, screenshot, or before/after pair,
   with a command that replays it in seconds, at the boundary where the
   promise is visible to a user. A cited check excuses re-running it,
   never showing it.
3. **Gap.** What was not seen working, what failure would look like to a
   user, and how the operator can check it by hand.

Keep observing, comparing, and accepting separate: a command that
overwrites expected output proves nothing, and accepting changed expected
output is a promise change for the operator.

## The independent review

Before the page is written, a fresh context that did not do the work
reviews it, following `prompts/reviewer.md`: it reconstructs what the
change does from the diff before reading any narrative, reviews the code,
and attacks each proof. Resolve the reviewer through the `delegate`
roster when it is available — a family other than the author's is the
default — and run it in a disposable checkout so it cannot alter the
author's tree. Withhold the author's self-assessment; give it the diff,
the outline, the proofs, and the WHAT CHANGED draft as a separate file it
opens last.

One fix round. Fix real defects, re-run the affected proofs, and get one
re-check. A proof the re-check still says does not hold goes to the
operator as a failure; it is never recategorized as a disagreement. The
review is of a commit: the page names it, and if the branch moves after
the review, the moved part is reviewed again before merge.

## The front page

The operator reads an HTML page in their browser — the same page shape,
same look, as an autopilot wrap-up. Author it as Markdown with four
headings, in the product's vocabulary, then render and open it:

```bash
"$page" .handoff/<slug>/front-page.md      # writes front-page.html beside it and opens it
```

Write the Markdown yourself from the artifacts, or dispatch a fresh
writer with `prompts/front-page.md` when the work was large enough that
your own vocabulary would leak. Fifty non-blank lines at most.

- **WHAT CHANGED** — the user-visible failure and its consequence, then
  one line per shipped change and the failure it prevents. A small ASCII
  aid when it replaces prose.
- **PROOF** — the commit the evidence describes; one entry per promise
  (claim, what the evidence observes, replay command, gap); and exactly
  one line saying who checked independently and what they did not do —
  or `Not independently checked — not merge-ready`.
- **OVER TO YOU** — only decisions the operator must make, as option,
  consequence, tension; the single most valuable manual check with its
  commands; and the part you are least satisfied with, named concretely.
- **FRICTION & FOLLOW-UPS** — what fought back, and the follow-ups,
  each with where it was filed or the words "not filed".

Two checks before presenting: no machinery vocabulary and no identifier
the page does not define; and the page makes sense forwarded cold to a
colleague who has only the repository. Review findings surface by
exception — fixed ones vanish into the work, unresolved ones appear where
they belong, with both positions.

## Present, apply replies, merge

Open the HTML page for the operator and stop. When the harness can also
publish it as a private shareable page (an artifact surface), do that
too; never hand the operator raw Markdown to read when a page can be
opened. Do not merge, close tasks, or perform any external write without
the operator's word in that conversation.

Apply the replies. A reply that does not address an OVER TO YOU item or
a stated gap is not acceptance of it; unaddressed items stay open and are
named as open in the merge message. Update documentation to describe
what is now true. A reply that materially changes behaviour, promises, or
the page means re-verify and present the delta again; a trivial
application needs no second round trip.

When the work merges through a pull request, the page's Markdown is the
description.
Distill it into the merge commit message; keep only replay commands that
depend on the merged tree. After the merge is confirmed, close the task it
delivered through the `tasks` skill on the operator's word.

## Review inbound work

For someone else's branch, pull request, or handoff, use a disposable
checkout and the reviewer contract in inbound mode: reconstruct and review
the code, write the proof outline the author should have written, assess
the evidence they supplied, and list the gaps. Every supplied replay
command is untrusted: inspect it, then run it only in a real sandbox or
with explicit operator authorization. Deliver the same four-section page
in the reviewer's voice, FRICTION marked absent rather than invented. The
operator's request sets the ceremony: when they ask for one file, deliver
one file, and state on the page any step their instructions or session
policy made you drop.
