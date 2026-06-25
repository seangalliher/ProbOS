# AD-1045 — POST /explore (facets) + GET /agents (list) — conformant discovery service

**Epic:** ARD Integration (`docs/development/ard-integration.md`) · **Phase 2, Step 2**
**Issue:** #995 · **Epic:** #989 · **Target repo:** OSS (`d:\ProbOS`)
**Depends on:** AD-1044 (search service) · **Blocks:** nothing (completes the discovery-service surface)
**Verification status:** ⚠ DRAFT — re-verify file refs against HEAD at build time (depends on AD-1044's `ArdSearchService` + `routers/ard.py`).

## Objective

Add the two **optional** ARD endpoints so the ship is a fully conformant discovery service: `POST /explore` (facet aggregation) and `GET /agents` (deterministic listing). Both operate over the in-memory projected catalog — cheap, since the inventory is already resident.

## Why

ARD §7.3/§7.4: `/explore` lets clients introspect a registry ("which media types are available?") via facet breakdowns; `/agents` is deterministic, highly cacheable browsing for developer portals. Implementing them makes ProbOS pass the full conformance suite and gives operators a portal-friendly view of the ship's catalog.

## Build

1. **`/explore` (spec §7.3)** in `ArdSearchService.explore(text=None, filter=None, facets=[...]) -> dict`:
   - Both `text` and `filter` optional; absent → aggregate the whole catalog.
   - `resultType.facets[]` with `field` (dot-path), optional `limit` (default 20), `minCount`. Compute buckets `{value, count}` + `otherCount` over the **full matched set** (apply the same relevance cutoff as search when `text` present).
   - Common facet fields: `type`, `publisher` (URN-derived), tier/`tags`.
   - `/explore` does **not** federate (spec §7.3). If disabled, return `501`.
2. **`GET /agents` (spec §7.4)** — EBNF-ish filter (`displayName`, `type`, `publisherId`, `createdAfter`, `updatedAfter`), `orderBy`, `pageSize`/`pageToken`. Strict DB-style filtering, no relevance sort. Highly cacheable.
3. **Routes** in `routers/ard.py`, gated on `federation.ard.enabled` (404 off); `/explore` returns `501` when explicitly unimplemented (it is implemented here, so 501 only if a future flag disables it).

## Acceptance criteria

- `POST /explore {"resultType":{"facets":[{"field":"type"}]}}` → bucket counts per media type + `otherCount`.
- `/explore` with `text` applies the same relevance cutoff as `/search`.
- `GET /agents?type=application/ai-skill&orderBy=name` → deterministic, filtered, paginated list (no scores).
- Conformance tester registry mode passes for `/agents` (status, paging, entry structure).
- Disabled → 404; `/explore` unimplemented path → 501 (documented).
- Tests `tests/test_ad1045_ard_explore_list.py` (BF-287): facet counts, text-narrowed facets, `/agents` filter+order+page, 404/501.
- Verify compliance with `.github/copilot-instructions.md`.

## Do NOT build

- No federation in `/explore` (spec-forbidden). No relevance sort in `/agents`.
- No new ranking. Default-OFF; `config/system.yaml` untouched.
