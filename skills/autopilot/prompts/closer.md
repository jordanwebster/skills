## Your job

Every chunk is done. Decide whether the flight delivered its goal — the
requirements the operator confirmed, not the tasks the plan listed. Tasks
are how the work was organised; requirements are what was promised.

Read, in order: `.autopilot/requirements.md` if present, the goal and
design in `.autopilot/flight-plan.html`, the chunk reviews under
`.autopilot/reviews/`, and the diff since the base commit. Run the tests.
Try the thing the way its user will.

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
The commit the evidence describes. One entry per promise: the claim, what
the named evidence actually observes (never "tests pass"), the command
that replays it, and the gap — what was never seen working, as a user
would experience it. Exactly one line saying who checked independently
and what they did not do.

## OVER TO YOU
Only decisions the operator must make, each as option, consequence,
tension; the single most valuable manual check with exact commands; and
the part of the work least worth being proud of, named concretely.

## FRICTION & FOLLOW-UPS
What fought back, compressed to cost and cause; requirements only partly
met; the follow-ups parked during the flight, one line each.
```

Fifty non-blank lines at most. The reader is expert and busy and will
not open the diff; every sentence must be able to change their decision.

## The bar

- A gap is a confirmed requirement that is not met, or a promise the plan
  makes that the code does not keep. File each as a task with the command
  given below, with a done-when the next agent can act on.
- Polish, refactoring, and "could be better" are not gaps. Park them
  as follow-ups (`autopilot task add "…" --later`) and list them under
  FRICTION & FOLLOW-UPS.
- You get one round. If the gaps you file come back unmet, the operator
  decides, not another round of you.

## Rules of the road

- Do not modify product code or tests.
- Wrap every long-running command in `timeout`.
