# AD-1051 — Catalog publication / registration client (register the ship with a registry)

**Epic:** ARD Integration (`docs/development/ard-integration.md`) · **Phase 4, Step 2**
**Issue:** #1001 · **Epic:** #989 · **Target repo:** OSS (`d:\ProbOS`)
**Depends on:** AD-1041 (projection), AD-1042 (well-known) · **Blocks:** AD-C-025 (central registry consumes this)
**Verification status:** ⚠ DRAFT — re-verify file refs against HEAD at build time (depends on AD-1041/1042; confirm the resident HTTP/auth pattern).

## Objective

The **registration extension point**: push this ship's `ai-catalog.json` (or its well-known URL) to a configured external registry endpoint (`federation.ard.registry_url`), so the ship becomes discoverable in a wider directory. The registry **service itself is out of OSS scope** — it is the commercial central ProbOS registry (AD-C-025). This AD is only the *client half*.

## Why

ARD ingestion (spec §6.2) supports registries indexing published catalogs. ProbOS ships should be able to *register* with a directory (the future central ProbOS registry, or any ARD registry) without that directory living in OSS. The boundary answer: **OSS gets the registration extension point; the central registry/marketplace is commercial.**

## Build

1. **New `federation/ard/publisher_client.py`** — `ArdPublisherClient`:
   - `async register(registry_url, *, mode="url") -> RegisterResult` — submit either the ship's well-known catalog **URL** (preferred; the registry crawls it) or the full **manifest** (for registries that accept push). Use the resident HTTP transport; auth via the existing credential pattern if the registry requires it (confirm at build time — reuse the AD-1017 MCP-auth / credential-vault pattern; **never** log or echo secrets).
   - `async deregister(registry_url) -> bool`.
   - Honest-degrade: a registry that's down → `RegisterResult(ok=False, reason=...)`, never crash boot.
2. **Optional startup hook:** when `federation.ard.enabled` **and** `registry_url` is set, register once at startup (after the catalog surface is up) — fire-and-forget with a stored task reference (Principle: hold the task ref), failure logged not fatal.
3. **Operator surface:** `POST /api/ard/register` (manual trigger) + `GET /api/ard/registration-status`, gated on `federation.ard.enabled`.

## Acceptance criteria

- `register(url_mode)` submits the ship's well-known catalog URL to the configured registry; `register(manifest_mode)` submits the projected manifest.
- No `registry_url` configured → registration is a no-op (default).
- Registry down → `ok=False` with reason; boot continues.
- Secrets never logged/echoed (assert credential value absent from logs + responses).
- Startup hook holds its task reference; failure is non-fatal.
- Tests `tests/test_ad1051_ard_publication.py` (BF-287: real client + fake registry HTTP): url vs manifest mode, no-url no-op, registry-down degrade, secret-absence, dereg.
- Default-OFF (no `registry_url`) ⇒ byte-identical.
- Verify compliance with `.github/copilot-instructions.md`.

## Do NOT build

- **No registry service** — that's commercial AD-C-025. This is the client/push half only.
- No marketplace logic (commercial AD-C-026). No attestation signing (commercial AD-C-027).
- No commercial endpoint URLs hardcoded — `registry_url` is operator-configured (AD-450: no commercial coupling in OSS).
