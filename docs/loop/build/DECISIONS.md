# Decisions taken during the unattended build

One line per decision, with rationale. For the operator's later review — recorded,
never pre-approved.

- 2026-08-24 — Keep `scaffold` as the CLI and Python package name because the build plan proposes it and retaining the existing operator vocabulary is the reversible default.
- 2026-08-24 — Require Python 3.11 or newer because it is the build plan's proposed floor and permits a modern stdlib-only implementation.
- 2026-08-24 — Put framework code in the top-level `framework/` directory because the brief forbids edits under `skills/` and a sibling directory keeps code separate from skill instructions.
- 2026-08-24 — Make journal rows self-contained with a hashed `state_after` snapshot because append-before-materialize then gives deterministic crash recovery without a second reconstruction format.
- 2026-08-24 — Identify the plan's one canonical machine block as `<script type="application/json" id="scaffold-plan">` because it is inert HTML, exactly selectable with the standard library, and leaves all surrounding prose non-authoritative.
- 2026-08-24 — Preserve plan order as the deterministic tie-breaker within the ready frontier because it makes dispatch reproducible without inventing a second priority field.
- 2026-08-24 — Limit M1 verification to proving that a typed claim names the product repository's clean immutable `HEAD` because artifact-based result judgment belongs to M2 and must not be smuggled in as a trusted exit-code check.
- 2026-08-24 — Add `.scaffolding/` to the product repository's local Git exclude during `init` because flight state must not enter worker product commits and the exclusion must remain machine-local.
- 2026-08-24 — Restrict task IDs to one 1–120 character ASCII path component because M1 uses them in prompt, result, and claim filenames and plan-controlled traversal must be impossible by construction.
- 2026-08-24 — Retain plan sources at digest-addressed immutable paths and derive the active prompt source from stored state because a rejected re-import may leave unused bytes but must never change an accepted graph's instructions.
- 2026-08-24 — Give every lease a fresh opaque generation ID and require it on claims, releases, and verification because holder names can recur and must not make evidence from an earlier attempt current again.
- 2026-08-24 — Make `init` idempotently repair an absent atomically-written config when its durable store already matches the requested goal because interruption between those writes must not require manual workspace surgery.
- 2026-08-24 — Publish retained plan sources with a same-directory fsynced temporary file, an atomic hard-link create, and a directory fsync because digest paths are write-once and must survive a crash without replacement or partial bytes.
- 2026-08-24 — Parse and retain one byte snapshot of each plan source because the accepted prompt text must always contain the machine contract whose digest and task graph were committed.
- 2026-08-24 — Fsync every retained-plan directory boundary on every import, including identical retries, because an existing entry may be the residue of an interrupted publication whose parent fsync never completed.
- 2026-08-24 — Require each task check to write a versioned JSON result at `SCAFFOLD_RESULT_PATH`, bound to the framework-provided candidate and check digests and containing at least one named observation, because a bare exit code cannot prove what ran.
- 2026-08-24 — Add an explicit `test_changes` plan-task boolean that defaults false because protected test/check edits need machine-readable scope and free-form decision prose is not a safe authorization boundary.
- 2026-08-24 — Capture the product head immediately before dispatch, require the claimed commit to descend from it, and verify from a detached local clone while hashing protected files at both commits because verification must not observe worker-shaped worktree bytes.
- 2026-08-24 — Record a completed red verification as terminal for that task while leaving independent frontier tasks runnable because M2 has no judge yet and silently retrying bad evidence would violate the failure-ends-slice rule.
- 2026-08-24 — Bootstrap a check's first verification timeout from the dispatch budget, then use four times its longest retained successful duration because subsequent timeouts must derive from observed run history while the first observation still needs a finite caller-owned bound.
- 2026-08-24 — Fingerprint each protected Git entry as its tree mode plus blob bytes because mode-only test/check edits are behaviorally meaningful and must pass through the same scope gate as content edits.
- 2026-08-24 — Run each task check in a fresh process group and terminate that whole group on completion or timeout because a verifier verdict must not leave descendant processes acting after checkout cleanup.
- 2026-08-24 — Renew a claimed task's lease before verification for the original lease allowance plus twice the derived check timeout because valid long checks must remain single-owner through artifact application.
- 2026-08-24 — Restore the product branch to its clean pre-dispatch commit before recording or releasing any non-green outcome because later independent work must never inherit an unverified candidate.
- 2026-08-24 — Create and fsync every verification-artifact directory boundary before writing a verdict because the journal must never make a terminal transition durable before its cited evidence path is durable.
- 2026-08-24 — Cover dispatch with its configured timeout plus lease grace, then persist the typed claim and its check-bound lease reservation in one locked journal transition because no reclaimer may enter between candidate filing and framework verification.
- 2026-08-24 — Make an OS-released nonblocking `flock` the one-driver safety boundary and treat heartbeat freshness only as operator-facing liveness because machine sleep may stale time-based signals without releasing ownership.
- 2026-08-24 — Durably record the task, lease generation, product path, and clean pre-dispatch commit immediately before worker mutation because restart can then keep an already-green commit or restore the exact base and release interrupted work as infrastructure without guessing.
- 2026-08-24 — Bind each drain request to the currently locked run and make detached launch wait for a matching heartbeat because stale control files and stillborn children must never be mistaken for a live instruction or successful start.
- 2026-08-24 — Require the locked owner record and heartbeat to agree before process-group stop, and deny the fake worker access to `.scaffolding`, because the kill target and recovery receipts must stay outside the current worker adapter's write authority; real-adapter sandbox enforcement remains M4 work.
- 2026-08-24 — Linearize a drain request with the next task lease under a short-lived boundary `flock` because a request that wins that boundary must prevent new work, while a lease that wins it defines the task the driver is allowed to finish.
- 2026-08-24 — Enforce fake-worker control-state exclusion using both case-folded path components and resolved containment because case-insensitive aliases and symlinks must not bypass the adapter boundary.
