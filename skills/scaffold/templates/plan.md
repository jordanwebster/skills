# Purpose: route the approach and decomposition to every fresh segment so none replans from memory, and show the operator up front what the run will do and need.

Approach: <technical approach derived from the confirmed requirements>

Layout: <where product code, tests, and executables live; nothing under
`.scaffolding/` is product and nothing imports from it>

Interfaces: <the seams the work will create or change, in one screen>

Verification strategy: <how the work is checked and why that way is the
strongest available>

Operator acts — everything the run needs from the operator, agreed before it
starts:

| Act | When it fires | What is asked | Rough cost |
| --- | --- | --- | --- |
| <act or none> | <trigger> | <plain-words request and commands> | <minutes> |

Staffing shape: <roles this run dispatches and any binding constraints, or
"single context">

Phases and items — items cut at verification seams, grouped into context
phases that one fresh segment sweeps:

| Phase | Role | Effort | Item | Rationale for this cut | Depends on |
| --- | --- | --- | --- | --- | --- |
| <phase> | <role> | <roster default, or a tag for a hard phase> | item-001 <title> | <why this is one independently checkable increment> | <ids or none> |

Open unknowns: <research items, the probe that settles each, and the items
provisional on them>

Rejected alternatives: <approach and why not, so dead ideas stay dead>

Decision register: <path; reversible choices logged for later review,
irreversible ones parked>

Read first: <files a fresh segment must read before touching anything>

Revisions — batch events only, recorded by fresh planning contexts:

| Revision | Trigger batch | What changed and why |
| --- | --- | --- |
