# Build progress

State file for the unattended framework build. Updated by every iteration; the
next iteration trusts this file over anything else.

## Milestones (from docs/loop/build-plan.html — strictly in order)

- [x] M0 — Skeleton: package layout, store read/write/journal, toy-flight goal
      function created and red. Check: check.sh exists, executes, and fails for
      the right reason.
- [x] M1 — Loop on fake adapter: selection, leasing, prompt assembly, apply.
      Check: the toy flight runs green end-to-end unattended; retained-plan
      publication is crash-durable across fresh-directory creation and identical
      retries.
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
- 2026-08-24 — M1 implementation advanced in `667c589` (`Implement M1 fake-adapter build
  loop`), with the independently replayable loop-test fix in `b93fd52` (`Make M1
  loop test independently replayable`) and cross-process lease proof in `347e176`
  (`Prove M1 lease contention across processes`). The single independent-review fix
  round landed in `53a0e1b` (`Close M1 state and lease boundary gaps`), removing the
  unchecked state-replacement API, containing task IDs, binding claims to lease
  generations, making retained plans digest-addressed, migrating M0 state, and making
  interrupted initialization recoverable. Landed canonical HTML plan-block
  import, strict dependency-graph state, deterministic profile-filtered frontier
  selection, atomic single-worker leases with expiry, typed claims separate from
  framework-owned transitions, durable prompt assembly, a scripted fake adapter,
  candidate-commit identity checks, and the `init` / `plan-import` / foreground
  `run` CLI slice. The fresh-repository toy flight now lands two dependency-ordered
  product commits and wraps green through the CLI. Twenty-six stdlib unit tests and the
  full repository suite pass. Independent review found six boundary defects;
  `53a0e1b` addressed all six named cases, but the one allowed
  re-check showed that the plan-source fix was incomplete: changing only readable HTML
  prose preserves the canonical machine digest and overwrites the active retained plan
  before the second import is rejected. Per Handoff's bounded review rule, no second
  automatic fix round was taken this iteration, so M1 remains in progress. The
  whole-build check honestly exits 1 with `build incomplete: M1 retained plan can
  change after rejected import`.
- 2026-08-24 — M1 plan-source correction advanced in `c5e66b5` (`Make retained
  plans immutable`) and `ba304ad` (`Harden retained plan publication`). Retained
  digest paths are now atomic create-once files; changed prose around an identical
  machine block cannot replace the accepted prompt source, identical bytes leave the
  existing file untouched, and parsing plus retention use one byte snapshot. Thirty
  stdlib framework tests and the full repository suite pass. The roster-selected
  cross-family reviewer could not start because the local Claude CLI is unauthenticated,
  so the reversible default and its reduced model-family diversity are recorded in
  `QUESTIONS.md`; two fresh same-family review contexts were used in isolated
  checkouts. The first found a two-read source race and missing leaf-directory fsync,
  both fixed in `ba304ad`. The one bounded final re-check confirmed those source
  immutability cases but found a remaining medium crash-durability gap: creation of
  `inputs/plans/` does not fsync every new parent directory, and an identical-file
  retry after a failed fsync skips the leaf-directory fsync before state can commit.
  Per Handoff's stop bar, no second automatic fix loop was taken. The whole-build
  check honestly exits 1 with `build incomplete: M1 retained plan directory hierarchy
  is not crash-durable`.
- 2026-08-24 — M1 completed in `f982b00` (`Make retained plan directories
  crash-durable`). Retained-plan import now creates each directory one level at a
  time and fsyncs its parent before advancing, repeats those fsyncs on recovery, and
  fsyncs the leaf directory for both a new hard link and an identical existing file
  before committing the store transition. Regressions inject the former leaf-fsync
  failure and prove an identical retry cannot apply state before the directory is
  durable. Thirty-one stdlib framework tests and the full repository suite pass.
  The roster-selected Claude reviewer remained unauthenticated, and the installed
  Codex CLI was too old for its roster model; the recorded reversible default used a
  fresh read-only native `gpt-5.6-sol` reviewer at xhigh effort. That reviewer found
  no medium-or-higher issue; the low residual concern is that durability is proved by
  injected fsync ordering rather than a real power-loss/filesystem recovery test.
  The whole-build check now honestly exits 1 with `build incomplete: M2
  seeded-failure suite is not implemented`.

## Next

- Build M2 only: add the verification runner's restore-and-hash isolation, closed
  verdict artifacts, test-glob diff gating, artifact-based judgment, and the
  malformed-evidence boundary that reddens only its task. Seed the lying-worker and
  bad-paperwork failures while keeping the M1 toy flight green.
- Replace M1's deliberately narrow `candidate-is-clean-head` identity check in
  `framework/scaffold/loop.py` with the M2 runner result. Task `check` commands are
  imported and prompted now but intentionally are not trusted or executed by M1.
- Extend the same fake-adapter script and temporary product repository rather than
  creating a second toy path. The fake script schema is `{"steps": [...]}` with one
  ordered task id, commit message, write map, and optional artifact list per step.
- Keep `check.sh` non-zero after M2 because supervision, real-adapter, and M5 seeded
  failures will still be absent; change its one-line reason only to the first genuine
  unfinished whole-build requirement.
- Imports currently use `PYTHONPATH=framework`; installation and the stable executable
  surface remain future milestone work.
