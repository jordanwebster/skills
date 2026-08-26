# Proof bundle schema

`handoff finish <workspace>` reads exactly `<workspace>/proof.json`. Paths in
the bundle are relative to that workspace. The command writes `proof.md` for
compact mode or `handoff.html` for page mode; both are derived outputs.

```json
{
  "schema_version": 1,
  "mode": "compact",
  "title": "Checkout retry works without duplicate charges",
  "reviewed_commit": "<full Git commit>",
  "accepted_demonstrations": [
    {"id": "demo-retry", "description": "A timed-out checkout can be retried once"}
  ],
  "changes": ["Timed-out checkout attempts can now be retried safely."],
  "claims": [
    {
      "claim": "A retry completes once and creates one charge.",
      "demonstrations": ["demo-retry"],
      "artifacts": [
        {"path": "captures/retry.txt", "kind": "transcript", "label": "Retry transcript"}
      ],
      "replay": {"kind": "command", "command": "timeout 30 tests/retry.sh"},
      "gap": "none"
    }
  ],
  "decisions": [],
  "follow_ups": []
}
```

`mode` is `compact` or `page`. Page mode additionally requires:

```json
"review": {
  "reviewer": "fresh reviewer using the configured reviewer role",
  "reviewed_commit": "<same full Git commit>",
  "summary": "The behavior and supplied evidence hold.",
  "limitations": []
}
```

Claims and accepted demonstrations have many-to-many coverage. Every accepted
demonstration ID must be named by at least one claim; a claim may name several.
IDs are only join keys and never render on the operator surface.

Each artifact has a relative `path` and may have `kind` and a product-language
`label`. An artifact must exist and resolve inside the workspace. Total unique
artifact bytes may not exceed `HANDOFF_MEDIA_BUDGET_BYTES` (25 MiB by default).

A replay recipe has exactly one of these shapes:

```json
{"kind": "command", "command": "timeout 30 tests/retry.sh"}
{"kind": "steps", "steps": ["Open checkout", "Submit the supplied timeout fixture", "Choose Retry"]}
{"kind": "not_replayable", "accepted_reason": "The operator accepted a production-only observation", "limitation": "The capture cannot be recreated locally"}
```

`gap` is always explicit. Use `"none"` only when the artifacts show the whole
claim. A claim with no artifact must name the actual gap. `handoff finish`
checks structure, coverage, safe artifact paths, media size, current Git commit,
page-review freshness, unfinished placeholders, and obvious internal workflow
vocabulary. It does not judge whether the evidence is persuasive.
