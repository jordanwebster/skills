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
claim. A claim with no artifact must name the actual gap.

A `decisions` entry is either the decision itself as a sentence, or the whole
operator grammar:

```json
{"decision": "Unknown responses surface as a typed unknown result.",
 "instead_of": "dropping them", "cost": "one additional public variant"}
```

`follow_ups` are optional work nobody promised. They never affect the verdict
and the page says so; anything inside the confirmed contract is a claim's gap,
not a follow-up.

The decision page derives each claim's coverage and the page's verdict from
this bundle; neither is authored:

| Claim | Coverage |
| --- | --- |
| Artifacts present, `gap` is `none`, replay is a command or steps | Proved |
| Artifacts present, but a real `gap` or an accepted not-replayable reason | Proved with limits |
| No artifact | Not proved |

| Page | Verdict | Ask |
| --- | --- | --- |
| Every claim proved and no review limitation | Holds | Merge this work. |
| Every claim proved, with a limitation or a limited claim | Holds with limits | Merge knowing the strongest limit. |
| Any claim not proved | Not decidable from this evidence | Do not merge yet. |

The default is always no merge and no publication, and `handoff finish --json`
reports the derived verdict for a page.

`handoff finish` checks structure, coverage, safe artifact paths, media size,
current Git commit, page-review freshness, unfinished placeholders, and obvious
internal workflow vocabulary. It does not judge whether the evidence is
persuasive. A `<placeholder>` is one lowercase word in angle brackets, so a
claim may name a real generic type such as `Result<T, E>`.
