# Build brief — the loop framework

You are one fresh iteration of an unattended build loop. Previous iterations have
no memory here; everything you need is in files. Read, in order:

1. `docs/loop/design.html` — what the framework is and why (the design).
2. `docs/loop/build-plan.html` — modules, APIs, engineering discipline, milestones
   M0–M5 with their checks. This is your spec; follow it.
3. `docs/loop/requirements.html` — what the operator's skills will require of the
   framework; context, not your task.
4. `docs/loop/build/PROGRESS.md` — where the build stands. Trust it over memory.
5. `docs/loop/build/DECISIONS.md` and `docs/loop/build/QUESTIONS.md`.

## Your job this iteration

Advance the build by one milestone — or one coherent, committable chunk of the
current milestone. Milestones run strictly in order (M0 → M5). Never start work you
cannot commit this iteration; never leave the working tree dirty at exit (commit
what passes its checks, revert what doesn't).

## Fixed contracts (the loop depends on these — do not reinterpret)

- `docs/loop/build/check.sh` must exist from your first M0 commit onward. It exits
  0 only when the ENTIRE build is done: the toy flight runs green end-to-end from a
  fresh clean checkout AND the full seeded-failure suite passes. Until then it
  exits non-zero with a one-line reason on stdout. It is created red-first and its
  first green is the finish line. Keep it honest — the loop, not you, decides done
  by running it.
- Update `docs/loop/build/PROGRESS.md` every iteration: milestone states, what
  landed (with commit hashes), what is next, and anything the next iteration must
  know. This file is the next iteration's memory.
- A review finding never reopens a milestone whose check is green. Record it in
  `PROGRESS.md` and continue; `check.sh`'s reason only ever moves forward.

## Decisions and questions

- Take the build plan's open-decision proposals as defaults (CLI working name
  `scaffold`; Python floor 3.11; you choose the in-repo location). Record every
  decision you make — these and any others — as one line each in
  `docs/loop/build/DECISIONS.md` with a short rationale. Never wait for a human.
- Never block on a question. Write it to `docs/loop/build/QUESTIONS.md`, take the
  reversible default, note which default you took, and continue.
- If the same failure defeats you for a whole iteration with no progress, write
  the blocker to QUESTIONS.md and exit cleanly — the loop's stall detection
  handles escalation.

## Hard constraints

- Runtime is Python stdlib only. Tests use stdlib `unittest`. No pip installs, no
  network, no external dependencies anywhere.
- Never edit anything under `skills/` or `docs/SPEC.md` — the framework is code
  beside the skills, not a skill edit. You may read everything.
- Never edit `docs/loop/*.html`, this brief, or `docs/loop/build/drive.sh`.
- Local commits only; never push. Plain present-tense commit messages describing
  the change. Never add Co-Authored-By or any AI-attribution trailer.
- Never write credentials or secrets into files, logs, or commits.
- Every long-running command you run goes under `timeout`.

## What crash-safety means here

Crash-safe means the flight resumes — not that every byte survives. The test is
mechanical: kill the run at any point, relaunch, and it continues correctly from
durable state. M3's check already states it.

- Durability machinery is in scope only where its absence would fail that test.
- Anything re-derivable is not a durability problem. A retained plan, an assembled
  prompt, or a verification artifact that is missing or torn is detected and
  re-derived, or reddens its own task — never guaranteed byte-perfect with added
  fsync machinery.
- Add no new fsync boundary unless a seeded kill-and-resume test fails without it.
- Machinery already built to a stricter reading stays. Do not churn working code to
  match this; it bounds new work only.

## Where you are

Repository: the operator's public agent-skills repo. The framework you are
building is specified entirely by the two HTML documents above. Build it plainly,
test it honestly, and let `check.sh` speak for you.
