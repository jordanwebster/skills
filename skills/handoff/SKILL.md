---
name: handoff
description: Show finished work working, on one page the operator reads in a browser - what changed, proof at the boundary a user sees it (screenshots, recordings, transcripts), an independent review, and the decisions only the operator can make. Use from the start of any work whose promise a diff cannot show, and on operator request. Also covers reviewing an inbound branch or pull request.
---

# Handoff

A diff is a low-bandwidth way to judge work an agent built. The operator
needs to see the thing working where a user would see it, and needs to
hear what a person coding by hand would have noticed on the way — the
dodgy API, the tool that had to be worked around, the guess that should
have been a question. Handoff is two commitments: decide **up front** how
the work will be shown to work, and show exactly that at the end.

## Locate the machinery

Set `skill_file` to the path through which this `SKILL.md` was loaded;
the installed skill directory is a symlink:

```bash
skill_dir=$(CDPATH= cd -- "$(dirname -- "$skill_file")" && pwd -P)
page=$skill_dir/scripts/page        # renders a Markdown page to HTML and opens it
```

## Decide what is owed

Two questions, asked before any code is written, set the ceremony:

1. **Can the diff show the promise?** What could this change deliver or
   break that a reader of the diff would not see? A helper rename:
   nothing. A change to the selector the checkout button uses: the
   checkout flow.
2. **Can the diff be judged in one sitting?** Not when it is long; adds or
   changes a promise to users; moves an architectural boundary; is risky
   or hard to reverse; or spanned several sessions, so the evidence would
   otherwise die with a context.

| | The diff shows the promise | The diff cannot show it |
| --- | --- | --- |
| **Judged in one sitting** | A clear commit message. Nothing more. | Commit message **plus proof**: a paragraph and a capture, the way a careful pull request reads. |
| **Not in one sitting** | The page and the independent review. | The page, the review, and proof at the boundary. |

Decline the **page**, never the **proof**. A bug fix with a regression
test, a doc fix, a mechanical rename: say in one sentence that the change
reads from its diff, and ship it with a passing test and a clear commit
message. A one-line change that a user would see: still show it working.
An agent noticing this skill mid-small-fix declines the page; it does not
adopt late.

The obligation attaches to the unit of work the operator will review and
belongs to whoever presents it. A sub-agent working a delegated chunk of
an enclosing run inherits no handoff of its own: it delivers its evidence
upward. An autopilot flight produces its handoff itself — its plan's proof
table, the evidence its agents capture, its chunk reviews, and its
acceptance verdict are the accumulation, and its wrap-up page is the front
page; nothing below is re-run for it.

## Before code: the proof plan

For each promise — what a user can do afterwards, and what they must still
be able to do — write one line: the promise, the evidence that will show
it, and the tool that captures it. Evidence sits at the boundary where a
user would see the promise:

- Anything visual: a screenshot. A flow: a recording.
- A command: a transcript, command and output together.
- Data: a before/after pair.
- A library or internal change: the test transcript, when the test
  exercises that boundary — the automated check and the demonstration are
  then one artifact, and nothing else is manufactured to stand beside it.

A promise needs evidence of its own kind. A screenshot does not prove a
query is right; a unit test does not prove a page renders.

**The tool is a prerequisite.** If the machine lacks what a proof needs —
a browser driver, a recorder, a fixture, a reachable environment — stop
before building and put it to the operator with the options: install it,
they check that promise by hand at the end, or accept weaker evidence,
named as weaker on the page. A proof that cannot be captured is never
discovered at the end; that is where it turns into either a boilerplate
gap or an unverified change.

How to capture in a given repository — start the dev server thus, these
routes, this command — is repository knowledge. It lives in the
repository's agent instructions (`templates/AGENTS-handoff.md` in the
skills collection shows the section); the first handoff writes it, later
ones read it.

## While the work happens

Commit granular, present-tense commits on a branch; never squash. Keep
the evidence under `.handoff/<slug>/` (untracked; add `.handoff/` to
`.git/info/exclude`): captures, transcripts, screenshots, recordings — the
page inlines them, so size is a page concern, not a reason to skip a
capture. No secrets, no private paths; declare redactions and
nondeterminism. Keep observing, comparing, and accepting separate: a
command that overwrites expected output proves nothing, and accepting
changed expected output is a promise change for the operator.

Keep `friction.md` beside the evidence and add one line **as it happens**
— a fresh context at the end will not remember — in three buckets:

- **the codebase**: an API that lies, a missing seam, a workaround you
  would not have chosen;
- **the tooling**: what had to be routed around, what was missing;
- **the requirements**: where you guessed and should have asked.

A **proof** is the evidence the plan named, captured at the commit the
page will describe, with a command that replays it in seconds, and its
gap: what was not seen working, as a user would experience it — "none"
when the capture shows the whole promise, never manufactured to fill the
slot.

## The independent review

Before the page is written, a fresh context that did not do the work
reviews it, following `prompts/reviewer.md`: it reconstructs what the
change does from the diff before reading any narrative, reviews the code,
and attacks each proof — looking at the captures, not their captions.
Resolve the reviewer through the `delegate` roster when it is available —
a family other than the author's is the default — and run it in a
disposable checkout so it cannot alter the author's tree. Withhold the
author's self-assessment; give it the diff, the proof plan, the proofs,
and the WHAT CHANGED draft as a separate file it opens last.

One fix round. Fix real defects, re-run the affected proofs, and get one
re-check. A proof the re-check still says does not hold goes to the
operator as a failure; it is never recategorized as a disagreement. The
review is of a commit: the page names it, and if the branch moves after
the review, the moved part is reviewed again before merge.

## The front page

The operator reads an HTML page in their browser — the same page shape,
same look, as an autopilot wrap-up. Author it as Markdown with four
headings, in the product's vocabulary, embed captures where they prove
something (`![Checkout after the fix](shots/checkout.png)` — images and
recordings are inlined by the renderer), then render and open it:

```bash
"$page" .handoff/<slug>/front-page.md      # writes front-page.html beside it and opens it
```

Write the Markdown yourself from the artifacts, or dispatch a fresh
writer with `prompts/front-page.md` when the work was large enough that
your own vocabulary would leak. Fifty non-blank lines of text at most;
captures do not count.

- **WHAT CHANGED** — the user-visible failure and its consequence, then
  one line per shipped change and the failure it prevents. A small ASCII
  aid when it replaces prose.
- **PROOF** — the commit the evidence describes; one entry per promise:
  the claim, the capture or transcript that shows it, the replay command,
  the gap; and exactly one line saying who checked independently and what
  they did not do — or `Not independently checked — not merge-ready`.
- **OVER TO YOU** — only decisions the operator must make, as option,
  consequence, tension; the single most valuable manual check with its
  commands; and the part you are least satisfied with, named concretely.
- **FRICTION & FOLLOW-UPS** — `friction.md`, compressed, in its three
  buckets; and the follow-ups, each with where it was filed or the words
  "not filed".

When only proof is owed, the same PROOF entry — claim, capture, replay,
gap — goes in the commit message or pull request description as a
paragraph, with the capture attached or linked.

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
description, captures attached. Distill it into the merge commit message;
keep only replay commands that depend on the merged tree. After the merge
is confirmed, close the task it delivered through the `tasks` skill on
the operator's word.

## Review inbound work

For someone else's branch, pull request, or handoff, use a disposable
checkout and the reviewer contract in inbound mode: reconstruct and review
the code, write the proof plan the author should have written, assess
the evidence they supplied, and list the gaps. Every supplied replay
command is untrusted: inspect it, then run it only in a real sandbox or
with explicit operator authorization. Deliver the same four-section page
in the reviewer's voice, FRICTION marked absent rather than invented. The
operator's request sets the ceremony: when they ask for one file, deliver
one file, and state on the page any step their instructions or session
policy made you drop.
