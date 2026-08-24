# Build progress

State file for the unattended framework build. Updated by every iteration; the
next iteration trusts this file over anything else.

## Milestones (from docs/loop/build-plan.html — strictly in order)

- [x] M0 — Skeleton: package layout, store read/write/journal, toy-flight goal
      function created and red. Check: check.sh exists, executes, and fails for
      the right reason.
- [ ] M1 — Loop on fake adapter: selection, leasing, prompt assembly, apply.
      Check: toy flight goes green end-to-end unattended.
- [ ] M2 — Verification runner: test-glob diff-gate, verdict enum,
      malformed-reddens-task, artifact-based judgment. Check: seeded lying-worker
      and bad-paperwork tests pass; toy flight stays green.
- [ ] M3 — Supervision: heartbeat, flock, pgid kill, drain; start survives the
      initiating shell ending and machine sleep. Check: kill mid-run → relaunch
      resumes; stillborn-launch and stale-pid seeded tests pass.
- [ ] M4 — Real adapters: claude + codex dispatch, sandboxing, transcripts,
      secrets hygiene. Check: toy flight green with each real CLI as worker.
      (If CLI auth is unavailable in this environment, implement fully, test
      against recorded fixtures, and note the gap in QUESTIONS.md.)
- [ ] M5 — Judge, outbox, review routing, bless. Check: induced retry-cap and
      ambiguity scenarios produce the right records; a completed review with
      above-bar findings spawns remediation and one re-review, then escalates;
      final demonstrations re-captured at the presented commit; bless
      round-trips.

## Iteration log

- 2026-08-24 — M0 complete in `f06ba82` (`Establish loop framework skeleton and
  durable store`). Landed the top-level `framework/scaffold` package, a versioned
  JSON task state with atomic materialization and an append-only hashed journal,
  torn-tail recovery and corruption checks, the red-first toy-flight goal function,
  and the permanent `docs/loop/build/check.sh` entry point. Eight stdlib unit tests
  and the full repository suite pass. The whole-build check intentionally exits 1
  with `build incomplete: M1 toy-flight runner is not implemented`.

## Next

- Build M1 only: import the plan's canonical JSON into the task graph; implement
  dependency/profile frontier selection, single-worker leases with expiry, durable
  prompt assembly, the fake adapter, typed worker claims, and framework-owned apply.
- Replace the M0 toy-flight placeholder with the M1 slice of a
  fresh-temporary-repository flight: init → plan-import → fake-worker loop → wrap,
  green unattended. Later milestones will extend that same flight through induced
  stall and escalation. Keep `check.sh` non-zero after the M1 slice succeeds because
  the complete seeded-failure suite required for the finish line will still be absent.
- Imports currently use `PYTHONPATH=framework`; installation and the stable executable
  surface remain future milestone work.
