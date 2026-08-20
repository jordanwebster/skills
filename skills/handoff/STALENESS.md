# Freshness

Evidence counts only for the exact tree being merged. The mechanism is one
record and one rule.

The **subject revision** is the Git tree object ID for a commit, with any
tracked top-level `handoffs/` entry removed for compatibility with
repositories that committed evidence historically. `subject-rev.sh` computes
it. New evidence lives untracked under `.handoff/` and never affects the
subject.

The **freshness record** is the single file `.handoff/<slug>/freshness`. Its
first line is `subject=<oid>`, written by `stamp.sh <handoff-dir>` when
evidence assembly completes and rewritten (with `base=<oid>`) when review
completes. Optional `name=value` lines record other inputs — a tool version,
a fixture, a contract fingerprint — for agents to check by hand.

The rule: the handoff is fresh only when the record's `subject=` equals the
current subject revision. `stale.sh <handoff-dir>` checks exactly that and
exits nonzero on stale or missing.

There is no per-artifact bookkeeping: everything the record covers was
verified together, so any change after it is written makes the whole handoff
stale — re-verify the evidence and re-stamp rather than reasoning about
which pieces survived.
