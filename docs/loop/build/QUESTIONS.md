# Questions for the operator

Written by build iterations instead of blocking. Each entry: the question, the
reversible default taken, and what it would affect if the default is wrong.

- 2026-08-24 — Should focused milestone re-checks require the roster's cross-family reviewer when that CLI is unauthenticated? Default taken: use a fresh read-only same-family reviewer in an isolated checkout and record the binding shortfall. If wrong, M1 has independent-context review but lacks model-family diversity and should be re-checked by the roster reviewer when authentication is available.
- 2026-08-24 — When the roster-selected reviewer CLI is unauthenticated and the installed fallback CLI is too old for its roster model, should review move to the compatible native agent channel? Default taken: use a fresh read-only native `gpt-5.6-sol` reviewer at the roster's xhigh effort. If wrong, M1's final check is independent and uses the intended same-family model but did not travel through the roster's configured CLI or provide cross-family diversity.
