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
- [x] M2 — Verification runner: test-glob diff-gate, verdict enum,
      malformed-reddens-task, artifact-based judgment. Check: seeded lying-worker
      and bad-paperwork tests pass; toy flight stays green.
- [x] M3 — Supervision: heartbeat, flock, pgid kill, drain; start survives the
      initiating shell ending and machine sleep. Check: kill mid-run → relaunch
      resumes; stillborn-launch and stale-pid seeded tests pass.
- [x] M4 — Real adapters: claude + codex dispatch, sandboxing, transcripts,
      secrets hygiene. Check: toy flight green with each real CLI as worker.
      The no-network build environment uses executable local CLI fixtures for
      both vendor contracts; the authenticated-flight proof gap is recorded in
      QUESTIONS.md.
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
- 2026-08-24 — M2 advanced in `3cc295a` (`Implement M2 verification runner`) and
  `02f481d` (`Close M2 verification lifecycle gaps`).
  The loop now captures the pre-dispatch product head, restores each claimed
  descendant commit in a detached local clone, fingerprints plan-declared test and
  check paths at both commits, and applies only a digest-bound framework verdict
  artifact. Checks must write a candidate- and command-bound JSON result with named
  observations; bare success exits, malformed paperwork, mismatched identities,
  shrinking observation sets, and out-of-scope protected edits cannot flip green.
  Red evidence terminates only its task, leaving independent frontier work runnable;
  infra and killed verification end the slice without burning the work-attempt count,
  while malformed machinery stops the line. Forty-one stdlib framework tests and the
  full repository suite pass, including the seeded lying-worker, bad-paperwork, and
  protected-edit cases. Independent review found four medium boundary defects: mode-
  only protected edits, surviving verifier descendants, non-durable verdict-directory
  ancestors, and checks outliving their lease. `02f481d` fixed all four and added
  restoration of non-green candidates; forty-five framework tests and the full suite
  pass. The one bounded re-check confirmed those fixes but found one remaining medium
  lifecycle race: another loop can reclaim the lease after a claim is filed but before
  renewal; the stale loop then cannot safely restore its unverified candidate without
  risking the new holder's work. Per Handoff's stop bar, no second automatic fix loop
  was taken, so M2 remains in progress. Both reviews used fresh read-only
  `gpt-5.6-sol` contexts at xhigh effort because the roster-selected Claude CLI is
  unauthenticated, reducing model-family diversity. The whole-build check honestly
  exits 1 with `build incomplete: M2 lease-reclaim cleanup is not implemented`.
- 2026-08-24 — M2 completed in `a42e7e1` (`Close M2 claim reservation race`),
  with the bounded proof fix in `6c6e193` (`Prove M2 verification failure
  accounting`). The initial lease now covers the bounded dispatch plus lease grace;
  filing a typed claim durably retains it and reserves that exact generation through
  verification in one locked journal transition, removing the reclaim window that
  could leave a stale loop unable to clean up safely. The exact seeded race captures
  the former expiry, attempts a second-holder reclaim immediately after claim filing,
  and proves reclaim is refused while the original candidate reaches a green retained
  `verified_head`. The proof fix adds loop-level `killed` and `infra` routing seeds:
  both restore the product, release the lease, increment only the typed infra count,
  and leave work attempts at zero. Forty-seven stdlib framework tests, the fresh toy
  flight, and the full repository suite pass. The independent `gpt-5.6-sol` xhigh
  review found no divergence and no code finding; it initially found the missing
  attempt-accounting proof, and the one bounded fresh re-check confirmed the added
  seed and its stated verifier-seam limitation. The roster-selected Claude Opus CLI
  remained unauthenticated, so both checks lack cross-family diversity. The whole-
  build check honestly exits 1 with `build incomplete: M3 supervision is not
  implemented`.
- 2026-08-24 — M3 completed in `6d098bf` (`Implement M3 supervised process
  lifetime`). Foreground and detached runs now share one OS-released nonblocking
  driver lock; detached launch survives its caller and requires a matching heartbeat
  handshake, while status derives liveness only from the heartbeat rather than a PID
  probe. `drain` is bound to the current run and stops at a task boundary; `stop`
  requires the locked owner and heartbeat to agree before signaling the full driver
  process group. A durable pre-dispatch receipt lets restart keep an already-verified
  head or restore the exact clean base, release the interrupted lease as infrastructure,
  and continue immediately. Seeded tests cover a refused second writer, stillborn
  launch, stale-pid/heartbeat classification, descendant process-group termination,
  detached-shell survival, boundary drain/resume, and kill-after-candidate/relaunch.
  The independent review found two medium boundary defects: fake-worker path aliases
  could reach control state, and drain was not linearized with the next lease. Both
  were addressed in `5350e50` (`Close M3 supervision boundary races`) with resolved-
  path containment, a drain/claim boundary lock, and regressions; the recovery seed
  now uses uncatchable `SIGKILL` rather than graceful stop. The one bounded re-check
  confirmed the drain and crash fixes but found a remaining medium control-path alias:
  on a case-insensitive filesystem, a symlink whose target is spelled `.SCAFFOLDING`
  can still reach the real lowercase framework directory because the resolved-prefix
  comparison is case-sensitive. Per the build's fixed contract, this review finding
  is recorded without reopening green M3 or moving `check.sh` backward; M4 must carry
  it as adapter-sandbox hardening. Fifty-six stdlib framework tests, the supervised
  fresh toy flight, and the full repository suite pass. The
  roster-selected Claude Opus reviewer was still unauthenticated, so the review and
  bounded re-check used fresh read-only `gpt-5.6-sol` xhigh contexts in a disposable
  checkout and lack cross-family diversity. The whole-build check honestly exits 1
  with `build incomplete: M4 real adapters are not implemented`.
- 2026-08-24 — M4 advanced in `5acb573` (`Implement isolated real CLI adapters`),
  with the bounded review fix in `0cf4076` (`Close real adapter trust boundaries`).
  The public run and start commands now resolve Codex and Claude mechanically from
  the delegate roster; each adapter owns its vendor flags and runs in a disposable
  local clone, accepts only a schema-bound descendant commit claim, and imports it
  by fast-forward through the existing verifier. Retained output is redacted, the
  worker environment excludes unrelated secret-named variables, final-tree and
  commit metadata receive a secret scan, worker process groups are cleaned up, and
  recognizable transport and setup failures count as infrastructure. Executable
  local fixtures cover both CLI contracts. The initial independent review found
  five process, compatibility, isolation, and accounting defects; the bounded fix
  addressed them, and sixty-five framework tests plus the full repository suite
  pass. The one bounded fresh re-check confirmed those fixes but found two remaining
  adapter-isolation defects: inherited `PWD` still discloses the active checkout,
  and a secret-bearing intermediate candidate commit is not scanned when its blob
  is deleted before the final tree. Per Handoff's stop bar, no second automatic fix
  loop was taken, so M4 remains in progress. Authenticated dispatch was not run
  because this build forbids network access; the reversible fixture default and
  resulting proof gap are recorded in `QUESTIONS.md`. The whole-build check honestly
  exits 1 with `build incomplete: M4 adapter isolation is incomplete`.
- 2026-08-24 — M4 completed in `852d7c6` (`Complete M4 adapter isolation`).
  The process-launch boundary now replaces inherited `PWD` and `OLDPWD` with
  the resolved disposable checkout, and both executable vendor fixtures reject
  any source-directory disclosure. Candidate publication now scans every blob
  and commit object introduced by `base..candidate`, so a seeded worker that
  commits an API key and deletes it before its clean final claim is rejected
  without publishing the history or retaining the secret. The independent
  review found that Git's object walk omits a changed path when it reuses a blob
  already reachable from the base; `69e3431` (`Close M4 reused-blob path gap`)
  enumerates changed paths for every introduced commit and seeds that exact
  rejection before publication. Sixty-seven stdlib framework tests, both
  real-CLI fixture flights, the fresh toy flight, and the full repository suite
  pass after the bounded fix. Authenticated dispatch remains untested under the
  brief's no-network constraint, as recorded in QUESTIONS.md. The whole-build
  check advances monotonically and exits 1 with `build incomplete: M5 judge,
  outbox, and bless are not implemented`.

## Next

- Start M5 only: implement typed judge decisions and durable escalation/outbox
  records, then add retry-cap and ambiguity seeds before proceeding to review
  routing or bless.
- Keep graph mutation in planning contexts at batch points; workers may only file
  proposals, and malformed judge output must park and escalate rather than stop the
  line.
- Preserve the authenticated real-flight proof gap unless a later iteration has
  explicit network authority; do not weaken the M4 fixture coverage around it or
  reopen the green milestone for a review finding.
- Imports currently use `PYTHONPATH=framework`; installation and the stable executable
  surface remain future milestone work.
