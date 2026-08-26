## Your job

Every chunk is done. Decide whether the flight delivered its goal — the
requirements the operator confirmed, not the tasks the plan listed. Tasks
are how the work was organised; requirements are what was promised.

Read, in order: `.autopilot/requirements.md` if present, the goal, design,
and **Proof** table in `.autopilot/flight-plan.md`, the chunk reviews
under `.autopilot/reviews/`, the captures under `.autopilot/evidence/`,
and the diff since the base commit. Run the tests. Try the thing the way
its user will — and capture what you see: the proof table names the
evidence each promise needs (a screenshot, a recording, a transcript) and
the tool; if a capture is missing or stale, take it now, at head, into
`.autopilot/evidence/`.

Write `.autopilot/acceptance.md` for the operator. It becomes the body
of the wrap-up page — the one page they read before deciding to merge —
so it has the shape every front page in this collection has:

```
Verdict: accept | gaps

## WHAT CHANGED
What a user can now do that they could not, then one line per shipped
change and the failure it prevents. The product's vocabulary; no task
numbers, no flight vocabulary. A small ASCII aid if it replaces prose.

## PROOF
The commit the evidence describes. One entry per promise in the plan's
proof table: the claim; the capture that shows it, embedded —
`![what the reader is looking at](evidence/name.png)` (images and
recordings render inline on the page; a transcript goes in a short code
block); the command that replays it; and the gap — what was never seen
working, as a user would experience it, or "none" when the capture shows
the whole promise. Exactly one line saying who checked independently and
what they did not do.

## OVER TO YOU
Only decisions the operator must make, each as option, consequence,
tension; the single most valuable manual check with exact commands; and
the part of the work least worth being proud of, named concretely.

## FRICTION & FOLLOW-UPS
What fought back, compressed to cost and cause, in three buckets — the
codebase, the tooling, the requirements — from the flight notes and the
agents' task notes; requirements only partly met; the follow-ups parked
during the flight, one line each.
```

Fifty non-blank lines of text at most; captures do not count. The reader
is expert and busy and will not open the diff; every sentence must be
able to change their decision.

## The bar

- A gap is a confirmed requirement that is not met, or a promise the plan
  makes that the code does not keep — including a promise whose evidence
  cannot be captured because the product does not do it. File each as a
  task with the command given below, with a done-when the next agent can
  act on.
- Polish, refactoring, and "could be better" are not gaps. Park them
  as follow-ups (`autopilot task add "…" --later`) and list them under
  FRICTION & FOLLOW-UPS.
- You get one round. If the gaps you file come back unmet, the operator
  decides, not another round of you.

## Rules of the road

- Do not modify product code or tests.
- Wrap every long-running command in `timeout`.
