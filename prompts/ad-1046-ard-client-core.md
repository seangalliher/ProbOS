# AD-1046 — ARD client core (consume external catalogs registered with the ship)

**Epic:** ARD Integration (`docs/development/ard-integration.md`) · **Phase 3, Step 1**
**Issue:** #996 · **Epic:** #989 · **Target repo:** OSS (`d:\ProbOS`)
**Depends on:** AD-1040 (types) · **Blocks:** AD-1047, AD-1048, AD-1049, AD-1050
**Verification status:** ⚠ DRAFT — re-verify file refs against HEAD at build time (depends on AD-1040 `federation/ard/` package; confirm the resident `httpx`/mesh-fetch pattern).

## Objective

The **read-only ARD client**: a configured list of discovery-service endpoints *registered with the ship* (`federation.ard.discovery_endpoints`), with `search → read response`. Holds no execution — discovery only. This is "what catalogs can this ship see?"

## Why

A client never invents where to look (client guide Step 1). ProbOS keeps a configured allow-list of ARD discovery services (the `agent-finders.json` pattern) — public, vendor, or the future central ProbOS registry — and the operator decides what is trusted.

## Build

1. **New `federation/ard/client.py`** — `ArdClient`:
   - Constructor-injected `endpoints: list[str]` (from `config.federation.ard.discovery_endpoints`) + an injected HTTP caller (reuse the resident transport; **do not** add a new pooled client — confirm the existing `httpx`/mesh-fetch pattern at build time; respect the BF-612 empty-200 lesson if a long-lived client is reused).
   - `async search(text, *, filter=None, federation="none", page_size=10) -> list[CatalogEntry]` — POST the ARD query model to each configured endpoint, parse results into `CatalogEntry` objects, tag each with its `source` registry. Honest-degrade per endpoint (one bad registry never sinks the rest).
   - `async fetch_artifact(entry) -> dict` — resolve `entry.url` (or return inline `entry.data`) to the full artifact document (MCP server card / A2A card / skill). Does **not** connect/execute — just fetches the descriptor.
2. **Config-driven only** — no hardcoded endpoints. Empty list (default) → `search` returns `[]` immediately (default-OFF behavior).
3. **Surface a read-only API** `GET /api/ard/registries` (the configured endpoints) + `POST /api/ard/search` (proxy to `ArdClient.search`) for the HXI/operator, gated on `federation.ard.enabled` (404 off). **Discovery only — no adoption here (AD-1049).**

## Acceptance criteria

- `ArdClient(endpoints=[...]).search("create a github issue")` → merged `CatalogEntry` results across endpoints, each `source`-tagged.
- One endpoint 500s → its results dropped, others returned (honest-degrade).
- Empty endpoints / disabled → `[]` / `404`.
- `fetch_artifact` resolves `url` and returns inline `data` without connecting.
- Tests `tests/test_ad1046_ard_client.py` (BF-287: real `ArdClient` + a fake HTTP caller returning spec-shaped responses): merge, per-endpoint degrade, filter passthrough, inline-data vs url, disabled.
- Default-OFF (empty endpoints) ⇒ byte-identical.
- Verify compliance with `.github/copilot-instructions.md`.

## Do NOT build

- No trust verification (AD-1047) — `search` returns raw results; trust is the next AD.
- No permission gate (AD-1048), no adoption/connect (AD-1049), no federation merge logic beyond passing `federation` through (AD-1050).
- No new pooled HTTP client without the empty-200 recycle guard (BF-612).
