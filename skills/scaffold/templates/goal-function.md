# Purpose: define one worker-independent command whose exit status decides done-and-correct.

Verification command: `timeout <seconds> <command>`
Oracle owner: the operator — this role is never delegated or transferred
Oracle location outside worker reach: <path or service boundary>
Oracle bootstrap: <how `oracle-candidate/` is built from sources other than the artifact under test, and the agreed act at which the operator promotes it>
Re-pin policy: <when the oracle's pin is refreshed after new tests or fixtures land, and by whom — an operator act agreed in the plan, unless the pin reads across the boundary on its own>
Read-only tests: <paths and enforcing mechanism>
Clean-checkout mechanism: <command or fence>
Evidence artifacts emitted: <paths>
Product-channel lint: <vocab-lint invocation over code, docs, and commit messages>

Loose assertions excluded from done until tightened:

- <discovery-only assertion>

Weakening rule: only a recorded operator decision may weaken a criterion; direct edits fail verification.
