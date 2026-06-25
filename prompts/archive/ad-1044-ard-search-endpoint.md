# AD-1044 — POST /search (the ARD discovery-service query interface)

**Epic:** ARD Integration (`docs/development/ard-integration.md`) · **Phase 2, Step 1**
**Issue:** #994 · **Epic:** #989 · **Target repo:** OSS (`d:\ProbOS`)
**Depends on:** AD-1040 (types), AD-1041 (projection) · **Blocks:** AD-1045, AD-1050
**Verification status:** ⚠ DRAFT — re-verify all file refs against HEAD at build time (the `federation/ard/` package is created by AD-1040/1041; confirm `CapabilityRetriever`/`MCPWorkbench` signatures haven't drifted).

## Objective

Expose the ship as a conformant ARD **discovery service**: `POST /search` accepts the ARD query model `{query:{text, filter}, pageSize, pageToken}` and returns ranked ARD catalog entries with a relevance `score`. This AD wraps the **existing** search engines — it does not build new ranking.

## Why

ARD mandates `POST /search` as the universal federation floor (spec §3.5, §7.2). ProbOS already has the engine: `CapabilityRetriever.find_intents` ([capability_retriever.py](src/probos/cognitive/capability_retriever.py) L119, RRF over name + full-text axes) and `MCPWorkbench.find_mcp_tool` ([mcp_workbench.py](src/probos/cognitive/mcp_workbench.py) L195). This AD is the single highest-leverage step: it makes that engine speak the standard.

## Build

1. **New `federation/ard/search_service.py`** — `ArdSearchService` that, given the projected catalog (AD-1041) + the retrievers:
   - `search(text, *, filter=None, page_size=10, page_token=None) -> dict` returning the ARD response schema: `{results: [<CatalogEntry + score + source>], pageToken?}`.
   - **Ranking:** run `text` through `CapabilityRetriever.find_intents` (intents/skills axis) and `MCPWorkbench.find_mcp_tool` (MCP axis); fuse via the AD-979c `reciprocal_rank_fusion` already used by both; map ranked capability ids back to their projected `CatalogEntry`. Emit `score` 0–100 (normalize the fused rank).
   - **Filter (spec §7.1):** dot-path keys into the entry (`type`, `tags`, `capabilities`, `publisher`, `trustManifest.*`); within a key OR, across keys AND. `publisher` is derived from the URN (`publisher_domain`), not stored. A `400` for an unsupported filter path is spec-compliant.
   - **Pagination:** opaque `pageToken` (base64 offset is fine; mirror the spec example).
   - **score is relevance only** — never trust (spec §7.2). Do not fold trust into it.
2. **New route `POST {base}/search`** in `routers/ard.py` (or the federation surface — confirm at build time per AD-1042's host decision). Gated on `federation.ard.enabled`; 404 when off. `federation` param accepted but only `none` honored this AD (auto/referrals = AD-1050; a non-`none` value with no peers behaves as `none`).
3. **Wrap as protocol surfaces (optional, spec §7.5):** leave a forward marker for exposing search as an MCP tool / A2A skill — **named, not built**.

## Acceptance criteria

- `POST /search {"query":{"text":"read a file"}}` → ranked entries incl. the file tool, each with `identifier/displayName/type/url|data/score/source`.
- `filter:{type:["application/ai-skill"]}` returns only skill entries; `filter:{tags:["core"]}` ANDs with `text`.
- Unsupported filter path → `400`; disabled → `404`.
- `pageSize`/`pageToken` paginate deterministically.
- `score` is present, 0–100, and documented as relevance-only.
- Passes the ARD conformance tester **registry mode** (`conformance-test registry <url>`): status codes, pagination envelope, result/score structure.
- Tests `tests/test_ad1044_ard_search.py` (BF-287: real `CapabilityRetriever` + real `MCPWorkbench` stub + real `TestClient`): text rank, filter AND/OR, publisher-from-URN, 400 bad filter, 404 off, pagination.
- Verify compliance with `.github/copilot-instructions.md`.

## Do NOT build

- No new ranking algorithm — reuse `find_intents` + `find_mcp_tool` + RRF.
- No federation/referrals (AD-1050). No `/explore` or `/agents` (AD-1045). No trust scoring in `score`.
- No client-side consumption (AD-1046). Default-OFF; `config/system.yaml` untouched.
