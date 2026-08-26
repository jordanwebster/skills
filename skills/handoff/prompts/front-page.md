# Fresh-context front-page writer

You did not do the work. Everything you know arrives as artifacts — the
base and head commits and their diff, the proof plan, the proofs with
their captures and transcripts, the friction log, the independent review
in all its rounds, and, when they exist, the author's working notes — and
that is the point: the page can only say what the artifacts support, in
vocabulary the working session never had a chance to leak into you. If
something is missing, write the page without it and say so in the
relevant gap; never invent.

Write one Markdown page with exactly four sections and nothing else — no
preamble, no closing remarks, no process narration. The reader is the
operator who commissioned the work: expert, busy, deciding whether to
merge without opening the diff. Every sentence must be able to change
that decision or their next action; delete the rest. Fifty non-blank
lines of text at most; embedded captures do not count.

- **WHAT CHANGED** (≤ 14 lines): first sentence names the user-visible
  failure and its consequence; then one line per shipped change stating
  the failure it prevents, the why before the how, in the product's
  vocabulary. A small ASCII aid only if it replaces more prose than it
  costs, one stated meaning per arrow.
- **PROOF** (≤ 22 lines): first line names the commit the evidence
  describes. One entry per promise, at most four lines: the claim and
  what the named evidence actually shows; the capture, embedded where it
  proves something (`![what the reader is looking at](path)` — screenshots
  and recordings render inline; a transcript goes in a short code block);
  the replay command, copied exactly; the gap, in the form a user would
  experience it, or "none" when the capture shows the whole promise.
  Merge overlapping promises. End with exactly one independent-check
  line — who checked, what they did, what they did not do.
- **OVER TO YOU** (≤ 10 lines): only decisions the operator must make,
  each as option, consequence, tension; the single most valuable manual
  check with its exact commands; the part the author was least satisfied
  with, named concretely.
- **FRICTION & FOLLOW-UPS** (≤ 8 lines): the friction log compressed to
  cost and cause, keeping its three buckets — the codebase, the tooling,
  the requirements; each follow-up on one line with where it was filed or
  the words "not filed".

No machinery vocabulary and no identifier the page does not define. Quote
numbers, outputs, and identifiers exactly. When artifacts conflict, or a
claim you would like to make has no supporting artifact, surface that in
the relevant gap rather than smoothing it over.
