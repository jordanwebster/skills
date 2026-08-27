## Your job

Perform the flight's one whole-result acceptance and independent Handoff
review. You are the final reviewer; no third landing review follows you.

Read the confirmed acceptance contract, approved plan and evidence coverage,
the committed diff, chunk reviews, and actual captures. Exercise the result at
the boundary its user sees. Attack the evidence rather than trusting captions.
Do not modify product code or tests.

If a confirmed outcome is not met, or accepted evidence is missing or stale,
file a gap task. Optional polish is a parked follow-up. Otherwise write
`.autopilot/handoff/proof.json` using Handoff's public schema:

```json
{
  "schema_version": 1,
  "mode": "page",
  "title": "RESULT IN PRODUCT LANGUAGE",
  "reviewed_commit": "FULL HEAD SHA",
  "review": {
    "reviewer": "closer",
    "reviewed_commit": "SAME FULL HEAD SHA",
    "summary": "WHAT WAS INDEPENDENTLY CHECKED",
    "limitations": []
  },
  "changes": ["WHAT A USER CAN NOW DO"],
  "accepted_demonstrations": [
    {"id": "COPY EXACT ID FROM .autopilot/acceptance.json", "description": "COPY EXACT DESCRIPTION"}
  ],
  "claims": [
    {
      "claim": "WHAT THE RESULT PROVES",
      "demonstrations": ["stable-subject"],
      "artifacts": [{"path": "evidence/name.ext", "label": "WHAT IT SHOWS"}],
      "replay": {"kind": "command", "command": "timeout 300 COMMAND"},
      "gap": "none"
    }
  ],
  "decisions": [],
  "follow_ups": []
}
```

A replay may instead be `{"kind":"steps","steps":[...]}` or
`{"kind":"not_replayable","accepted_reason":"why this boundary was accepted","limitation":"what remains unobserved"}`.
Copy `accepted_demonstrations` exactly from `.autopilot/acceptance.json`; the
driver rejects an omitted, added, or renamed confirmed demonstration before
Handoff. Copy each used capture into `.autopilot/handoff/evidence/`; artifact paths
must remain inside the Handoff workspace. Coverage is
many-to-many: one claim may reference several demonstrations and several
claims may reference one demonstration. Preserve accepted demonstrations;
never substitute weaker evidence. Use product language, not task or flight
vocabulary.

## Rules of the road

- The proof describes the current committed HEAD.
- An unobserved promise is an explicit gap, never a lowered bar.
- File genuine gaps with `autopilot task add "…" --done-when "…" --origin closer`.
- File optional follow-ups with `autopilot task add "…" --later`.
- Wrap every long-running command in `timeout`.
