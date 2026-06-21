# AD-1047 — Trust verification + earned-trust layering for discovered resources

**Epic:** ARD Integration (`docs/development/ard-integration.md`) · **Phase 3, Step 2**
**Issue:** #997 · **Epic:** #989 · **Target repo:** OSS (`d:\ProbOS`)
**Depends on:** AD-1040 (TrustManifest), AD-1046 (client) · **Blocks:** AD-1049 (adoption)
**Verification status:** ⚠ DRAFT — re-verify file refs against HEAD at build time (depends on AD-1040/1046; confirm the trust-network public API in `consensus/trust.py`).

## Objective

Before any discovered resource is adopted, **verify the publisher** and **layer ProbOS earned-trust on top**. ARD carries the *evidence*; ProbOS makes the *decision*. Signature **verification** is OSS; signature **production** is commercial (AD-C-027).

## Why

ARD client guide Step 4: extract the domain from the URN, verify `trustManifest.identity`, audit `attestations`, verify the detached JWS — and stresses the relevance `score` "MUST NOT be read as a trust rating." ProbOS already owns the richest trust substrate in the ecosystem (Bayesian Beta(α,β), Shapley, consensus). This AD makes ARD trust *feed into* that, not replace it.

## Build

1. **New `federation/ard/trust_verifier.py`** — `verify_entry(entry: CatalogEntry) -> TrustVerdict`:
   - **Domain extraction:** `publisher_domain(entry.identifier)` (AD-1040).
   - **Identity binding:** confirm `trustManifest.identity` (SPIFFE / `did:web` / HTTPS FQDN) aligns with the URN publisher domain (spec §5.1: the cryptographic trust domain MUST align with the URN authority root). Mismatch → `reject`.
   - **Attestation audit:** surface `attestations[]` (SOC2/HIPAA/GDPR/…) as structured evidence — do **not** auto-trust them; they are inputs.
   - **Signature verification:** validate the detached JWS over the trust manifest when present (verify only — no signing). Missing/invalid signature is a *signal*, not necessarily a reject (operator policy).
   - Returns `TrustVerdict(domain, identity_ok, attestations, signature_ok, reason)`.
2. **Earned-trust layering:** a `to_trust_prior(verdict) -> (alpha, beta)` that maps verification evidence to a **probationary Bayesian prior** (mirror the federated-peer prior `Beta(1,3)` at `FederationPeerTrustConfig`, AD-480g — a verified+attested publisher may start slightly higher, an unverified one lower). Feed this as the *initial* `(alpha, beta)` for the discovered resource into the existing trust network (`consensus/trust.py` — confirm the public registration API). **Store raw (alpha, beta), never a derived mean** (ProbOS Principle #3).
3. **Never fold ARD `score` into trust** — assert this in a test.

## Acceptance criteria

- A `did:web:acme.com` identity on a `urn:air:acme.com:…` entry → `identity_ok=True`; a `did:web:evil.com` identity on the same URN → `reject` (domain mismatch).
- Missing signature → `signature_ok=False` with a reason, not a crash.
- `to_trust_prior` returns a raw `(alpha, beta)` tuple; a verified+attested publisher's prior ≥ an unverified one's; the discovered resource registers into the trust net with that prior.
- A test asserts the ARD `score` never reaches the trust computation.
- Tests `tests/test_ad1047_ard_trust.py` (BF-287: real `TrustManifest`/`CatalogEntry`, real trust network or a faithful stub): domain match/mismatch, attestation surfacing, signature present/absent, prior mapping, score-isolation.
- Verify compliance with `.github/copilot-instructions.md`.

## Do NOT build

- No signature **production** / attestation issuance (commercial AD-C-027).
- No adoption/connect (AD-1049) — this AD only produces a verdict + prior.
- No replacement of the Bayesian model with a flat attestation scalar (Principle #3, AD-450 dilution risk).
