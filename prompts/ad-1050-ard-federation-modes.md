# AD-1050 — Federation modes (auto / referrals / none) — ship-to-ship discovery

**Epic:** ARD Integration (`docs/development/ard-integration.md`) · **Phase 4, Step 1**
**Issue:** #1000 · **Epic:** #989 · **Target repo:** OSS (`d:\ProbOS`)
**Depends on:** AD-1044 (search), AD-1046 (client) · **Blocks:** AD-1051
**Verification status:** ⚠ DRAFT — re-verify file refs against HEAD at build time. Projects **existing** `FederationRouter` ([federation/router.py](src/probos/federation/router.py)) — confirm `select_peers` + peer-model APIs at build time.

## Objective

Implement the ARD `federation` query parameter (`auto` / `referrals` / `none`) over the existing `FederationRouter`, so a ship's `POST /search` can merge or refer to peer ships. This is the ProbOS-ship-to-ProbOS-ship discovery path the user asked for.

## Why

ARD §8: federation is a simple HTTP operation because the REST API is the floor. `FederationRouter.select_peers` already does trust-weighted, capability-aware, Hebbian-tie-broken peer selection — ARD's three modes are a thin projection over it. Peer ships' `/.well-known/ai-catalog.json` (AD-1042) become referral targets.

## Build

1. **Extend `ArdSearchService.search`** (AD-1044) to honor `federation`:
   - `none` → local index only (AD-1044 behavior, unchanged).
   - `referrals` → local results **plus** a `referrals[]` array of peer registry entries (`application/ai-registry+json`) for the peers `FederationRouter.select_peers(intent≈text)` returns. The client decides which to follow.
   - `auto` → the ship itself queries the selected peers' `/search` (via `ArdClient`, AD-1046), merges their results with its own (de-dupe by `identifier`, keep best `score`), and returns one set. Bounded fan-out + per-peer honest-degrade + the federation `forward_timeout_ms` (existing config).
2. **Peer registry discovery:** a peer ship's ARD registry endpoint is derived from its base URL + `well_known_path`; cache peer catalog endpoints from gossip / `outbound_peers`.
3. **Trust on merge:** when merging `auto` results, carry each peer's federated trust (AD-480g) so downstream AD-1047 verification + AD-1049 adoption see provenance. **Do not** let a peer's relevance `score` substitute for trust.
4. **Loop/fan-out safety:** cap federation depth (no transitive auto-of-auto storms); respect the IntentBus fan-out lesson (no N× amplification).

## Acceptance criteria

- `federation:"none"` → local only (byte-identical to AD-1044).
- `federation:"referrals"` → local results + `referrals[]` of selected peers; client not auto-queried.
- `federation:"auto"` → merged local+peer results, de-duped by identifier, best score kept; one peer down → its results dropped, others returned.
- Depth-capped (no infinite auto recursion); per-peer timeout honored.
- Peer trust provenance preserved on merged entries.
- Tests `tests/test_ad1050_ard_federation.py` (BF-287: real `FederationRouter` + real `ArdSearchService` + fake peer HTTP): none/referrals/auto, merge+dedupe, peer-degrade, depth cap, trust provenance.
- Default-OFF / no peers ⇒ byte-identical (federation never engaged).
- Verify compliance with `.github/copilot-instructions.md`.

## Do NOT build

- No new peer-selection algorithm — reuse `FederationRouter.select_peers`.
- No central registry (AD-1051 / commercial AD-C-025).
- No trust derived from `score`. No unbounded fan-out.
