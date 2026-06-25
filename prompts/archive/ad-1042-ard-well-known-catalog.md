# AD-1042 — Serve GET /.well-known/ai-catalog.json (the ship publishes its ARD catalog)

**Epic:** ARD Integration (`docs/development/ard-integration.md`) · **Phase 1, Step 3**
**Issue:** #992 · **Epic:** #989 · **Target repo:** OSS (`d:\ProbOS`)
**Depends on:** AD-1040, AD-1041 · **Blocks:** AD-1050 (referrals target), AD-1051 (publish)
**Verification status:** ✅ verified against HEAD (the A2A well-known precedent exists)

## Objective

Expose the projected catalog at the ARD standard discovery location `GET /.well-known/ai-catalog.json`, so other clients (and other ProbOS ships) can discover this ship's capabilities. **Read-only**, gated on `federation.ard.enabled`, 404 when off.

## Why

ARD's primary discovery mechanism is the well-known URI (spec §6.1). ProbOS already serves the A2A card at `/.well-known/agent.json` ([agent_card.py](src/probos/federation/a2a/agent_card.py), AD-480) — this AD adds the *catalog* sibling. The catalog `data`/`url`-references the A2A card as one entry, so the two compose.

## Build

1. **New route** serving `GET {federation.ard.well_known_path}` (default `/.well-known/ai-catalog.json`). Follow the A2A server pattern in [federation/a2a/server.py](src/probos/federation/a2a/server.py) — verify at build time whether the well-known route belongs on the **main API app** (so it sits next to other public endpoints) or the **federation A2A server**. ARD's well-known URI should be on the same host that serves the ship's public surface; prefer the main app router (a new `routers/ard.py`) unless the A2A server is the canonical public host.
2. **Handler:** build `HostInfo` from ship identity (vessel_name + ship_did via `runtime.identity_registry`, mirroring `AgentCard.from_runtime`), resolve `publisher_domain` (config `publisher_namespace_domain` or derive from `ship_did`), call `build_capability_inventory(runtime)` (AD-1041) → `project_catalog(...)` → `to_dict()`. Return `200 application/json`.
3. **Gating:** `federation.ard.enabled is False` (default) → `404` (mirror the AD-1015 `management_enabled` 404-when-off pattern). Honest-degrade: any projection failure → `500` with a logged reason, never a partial/garbage manifest.
4. **Caching:** set `Cache-Control` per ARD's "cacheable" intent (spec §6) — a short max-age is fine; the inventory is cheap to rebuild.

## Acceptance criteria

- With `federation.ard.enabled=True`: `GET /.well-known/ai-catalog.json` → `200`, body validates against the ARD `ai-catalog.schema.json` shape (specVersion, host, entries[]).
- With `federation.ard.enabled=False` (default): `404`.
- The manifest passes the ARD conformance tester in **manifest mode** (`conformance-test manifest <url>`) — URN format, value-or-reference, representativeQueries sizing (empty is allowed pre-AD-1043).
- Tests `tests/test_ad1042_well_known_catalog.py` (BF-287: real `TestClient`, real runtime stub with identity): 200-when-on, 404-when-off, body shape, the A2A card appears as an entry.
- Default-OFF ⇒ byte-identical (route returns 404, nothing else changes).
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Do NOT build

- No `POST /search` (AD-1044). No `representativeQueries` (AD-1043). No publication-to-registry (AD-1051).
- No trust-manifest signing (AD-C-027).
- Do **not** enable by default; `config/system.yaml` untouched.
