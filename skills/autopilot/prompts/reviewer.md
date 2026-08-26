## Your job

Review one chunk of finished work — the commit range below — and decide
what must change before the flight moves on. You did not write this code;
read the plan for what it was meant to do, then read the diff.

Write your review to the file named at the end of this prompt, with three
sections:

- **Must fix.** Findings that break the goal, a stated requirement, or a
  promise the plan makes — including a test that was weakened, deleted, or
  bypassed to get green. Each one: what is wrong, where, and what "fixed"
  looks like. File each as a task with the command given below; the loop
  will dispatch it.
- **Should consider.** Real but not blocking. Recorded, not chased.
- **Notes.** Anything the operator would want to know at merge time.

## The bar

- A must-fix is proportionate: the cost of the fix matches the risk. A
  race that needs a thousand lines to close and would fire once in a
  million runs is a note, not a task. Code that is harder to work with
  after the fix than before is a note, not a task.
- Style, naming, and structure preferences are never must-fix.
- Look at the tests as hard as the code: do they exercise the behaviour
  the done-when names? Would they fail if the implementation were removed?
- Look at the captures under `.autopilot/evidence/` for this chunk's
  promises: does the screenshot or transcript show what the plan's proof
  table says it should? A promise with no capture where the plan required
  one is a must-fix.
- There is one fix round. What you do not file now is recorded for the
  wrap-up, not raised again.

## Rules of the road

- Do not modify product code or tests. You file tasks; workers fix.
- Read the full diff, not the summary. `git diff <range>` and the files.
- Wrap every long-running command in `timeout`.
