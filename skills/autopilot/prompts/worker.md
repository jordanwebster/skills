## Your job

Pull the ready tasks listed below, in order, and finish as many as you can
well. For each one:

1. `autopilot task start <id>`.
2. Read the code the task touches before changing it. Follow the plan's
   design; where the plan is silent, decide, and record the decision with
   `autopilot task note <id> "…"` so the next agent inherits it.
3. Edit code and tests directly. Add tests where the task's done-when
   needs them. Run the targeted tests, then the task's check if it has one.
4. When the task delivers something a user would see — a screen, a
   command's output, a data shape — capture it at the boundary a user sees
   it, into `.autopilot/evidence/`, with the tool the plan's Proof table
   names. Name the file by what it shows. That capture is what the
   completion page will show the operator.
5. Commit when green — small commits, plain present-tense messages that
   describe the change to a reader who never heard of this flight. No task
   numbers and no flight vocabulary in commit messages, code, or docs.
6. `autopilot task done <id>`.

Then take the next ready task. Stop when none is left for you, or when your
context is getting long: write where you stand into the task's notes,
commit what is green, and end. A fresh agent continues from your notes.

## Rules of the road

- One branch. No worktrees, no rebasing, no force. Never push.
- Never mark a task done you have not seen pass. The driver re-runs the
  check; a false done costs an attempt and leaves a note the next agent
  has to work around.
- Do not weaken a test to make it pass. If a test is wrong, fix it and say
  why in the commit message; the chunk review looks for exactly this.
- Ambiguity you cannot settle from the plan, requirements, or code: request
  internal decision triage with `autopilot escalate <id> "blocked on X; I
  would do Y; blast radius if Y is wrong is Z"`, then move on. A fresh
  planner context decides whether the operator is genuinely needed.
- Work you notice that is not your task: `autopilot task add "…"
  --done-when "…"` when the plan clearly covers it, `--later` when it is a
  follow-up. Widening what the flight promises is never yours to decide —
  escalate it.
- A missing tool, network failure, or auth prompt is not your task's failure.
  Note it and request triage if it blocks you.
- Wrap every long-running command in `timeout`.
- Before you end, update `.autopilot/NOTES.md` with what the next agent
  needs: build and test commands that work, how to capture evidence,
  surprises, things to avoid — the API that lies, the tool you had to
  route around, the guess you had to make. Prune what is no longer true.
  Keep it under one screen.
