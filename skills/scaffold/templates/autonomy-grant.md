# Purpose: bound an unattended run and name every condition that ends it.

Driver: a script, never an agent. Each cycle: select the next ready phase by
the ledger's rule; resolve its role to a binding (roster default on no
match, logged); assemble the segment prompt by concatenating the role
contract, plan, ledger, and previous segment's ledger notes; dispatch under
the hang guard; run the verification command; flip what passed and record
`verified_head`. On a trigger — retry cap, stall, revision batch due —
dispatch an ephemeral judgment context (strongest available model) that
reads artifacts, decides, records, and ends.

Driver command: `<the loop script>`
Stall allowance: <consecutive segments with no ledger change, evidence artifact, or working-tree delta>
Retry cap per item: <full fresh-context attempts before the forced choice: split, re-brief, re-dispatch one tier up, or park and escalate — never another attempt>
Per-segment hang guard: `timeout <generous duration>` around the segment command
Derived ceiling, not granted: <items> × <retry cap> segments, computed from the ledger

Success exit: `<named action>`
Impossible exit: `<named action that records the verdict and clears the run>`
Escalate exit: `<named action that writes: blocked on X; I would do Y; blast radius if Y is wrong is Z; veto or confirm — and forwards it where the operator reads; the run continues on independent items>`

Stop-the-line triggers:

- Outside-workspace real data or machine state would be touched: `<firing mechanism>`
- Criterion weakened without a recorded operator decision: `<firing mechanism>`
- Verification command broken: `<firing mechanism>`
- Quota or capacity exhausted: `<firing mechanism; pause until reset>`

Staffing log: `<path; one row per dispatch: phase, role, binding, tokens, wall clock, outcome, retries>`

Resume protocol (canonical — used by fresh segments, judgment contexts, and
anyone attaching to the run): read every file in the scaffold workspace
including `ledger.json`; run `git log --oneline -20`; if the ledger's
harness item passes, run the verification command from a clean checkout and
fix a broken tree before new work; then resume at the mechanically selected
item. Never re-plan and never reconstruct from summaries.
