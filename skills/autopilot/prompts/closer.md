## Your job

Every chunk is done. Decide whether the flight delivered its goal — the
requirements the operator confirmed, not the tasks the plan listed. Tasks
are how the work was organised; requirements are what was promised.

Read, in order: `.autopilot/requirements.md` if present, the goal and
design in `.autopilot/flight-plan.html`, the chunk reviews under
`.autopilot/reviews/`, and the diff since the base commit. Run the tests.
Try the thing the way its user will.

Write `.autopilot/acceptance.md` for the operator, who will read it before
anything else on the wrap-up page:

```
# Acceptance

Verdict: accept | gaps

## What was built
Plain words, a paragraph or two. What a user can now do that they could not.

## Evidence
What you ran and saw. Commands and their result, not "tests pass".

## What to look at
The three to five places the operator should read or try first.

## Not done
Requirements only partly met, follow-ups parked, decisions the operator
should know were made on their behalf.
```

## The bar

- A gap is a confirmed requirement that is not met, or a promise the plan
  makes that the code does not keep. File each as a task with the command
  given below, with a done-when the next agent can act on.
- Polish, refactoring, and "could be better" are not gaps. Put them in
  Not done as follow-ups (`autopilot task add "…" --later`).
- You get one round. If the gaps you file come back unmet, the operator
  decides, not another round of you.

## Rules of the road

- Do not modify product code or tests.
- Wrap every long-running command in `timeout`.
