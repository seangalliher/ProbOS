# AD-1144 — Standards adoption: RFC 8785 JCS canonicalization + RFC 7515 JWS detached signatures (federation / ARD)

**Issue: #TBD · Nooplex interop track · supersedes the hand-rolled canonicalization in AD-1095.**
**Repo: OSS (`d:\ProbOS`). AD ceiling at drafting: AD-1133 shipped; AD-1134–1137 assigned (#1053–#1056); AD-1138–1143 assigned to the Σ epic (#1057–#1064). Verified next free top-level = **AD-1144**. BF ceiling: BF-677 shipped (#1067) → next free BF is 678; none minted here.**

Replace the hand-rolled canonical-JSON + detached-signature scheme with the two governing internet standards, so any third-party agentic harness can verify a ProbOS ARD manifest using a stock JOSE library. Dual-verify during transition; no wire-envelope change beyond the `signature` field.

---

## Why / context

The Nooplex is an ecosystem, not a protocol — most of what it needs (transport, identity, observability, provenance vocabulary, content addressing) already exists on the internet and must be reused rather than rebuilt. The one place ProbOS currently *diverges* from a standard without cause is signature canonicalization.

`AD-1095` signs with:

```python
payload = {k: v for k, v in manifest.to_dict().items() if k != "signature"}
canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
```
`src/probos/federation/ard/trust_verifier.py:78`

This is *nearly* RFC 8785 (JCS) but not it:

- **Key ordering.** Python `sort_keys=True` sorts by Unicode code point. JCS sorts by **UTF-16 code unit**. These differ for any key containing a non-BMP character (emoji, rare CJK) — the classic surrogate-ordering divergence.
- **Number serialization.** JCS mandates ECMAScript `Number::toString`. Python's `repr` differs for some doubles.
- **Envelope.** The detached signature is a bare base64 blob with no algorithm, key id, or critical-header handling — a hand-rolled JWS.

For ASCII-only keys with no floats the two agree, which is the dangerous case: **it looks interoperable and is not.** A third-party harness cannot verify a ProbOS manifest without reimplementing ProbOS's exact quirks.

This is the single highest-leverage adoptability change available: it costs one small module and makes the whole ARD trust layer verifiable by any stock JOSE implementation.

**Cross-repo contract.** The commercial `AD-C-027` `issue_attestation` reproduces this exact canonicalization to sign. OSS ships **dual-verify first** so the commercial issuer can migrate without a flag day. Do not modify the commercial repo in this AD.

---

## Pinned design decisions

### DD-1 — Adopt RFC 8785 (JCS) as the canonicalization, implemented in-tree
Add `src/probos/federation/ard/jcs.py` implementing RFC 8785: UTF-16-code-unit key sort, ECMAScript number serialization, minimal string escaping, UTF-8 output.

**Implement in-tree rather than adding a dependency.** The ARD package holds an explicit purity invariant — `media_types.py` states *"this module imports NOTHING from the rest of `probos`"*, and 11 of 14 ARD modules have zero `probos` imports. A third-party dependency in the trust path would weaken the "any harness can vendor this" property. JCS is ~80 lines of pure stdlib.

### DD-2 — Adopt RFC 7515 JWS, detached payload (Appendix F)
The `signature` field becomes a JWS compact serialization with the payload segment empty: `BASE64URL(header) || ".." || BASE64URL(sig)`.

Protected header: `{"alg": "EdDSA", "crv": "Ed25519", "kid": "<issuer key id>", "b64": false, "crit": ["b64"]}` per RFC 7797 for unencoded payload, or the simpler detached form with `b64` omitted if the verifier reconstructs from JCS bytes. **FLAG AT BUILD:** pick one and state it in the build report — recommended is plain detached JWS (no `b64`/`crit`), signing input = `BASE64URL(header) || "." || BASE64URL(JCS(manifest-minus-signature))`, which is the most widely supported shape.

Reuse the existing Ed25519 primitives (`substrate/device_pairing.verify_signature`, AD-843b). **No new crypto dependency** — `cryptography>=42` is already core.

### DD-3 — Dual-verify transition, new-format-only issuance
`verify_manifest_signature` accepts **both** forms during the transition:
- Legacy: bare base64 signature over the `json.dumps` canonical form.
- New: JWS detached over the JCS canonical form.

Dispatch on **shape, not a version field** — a JWS compact string contains `.` separators; the legacy form is bare base64 and never does. Self-describing, so **no `specVersion` bump is required** and `AiCatalog.spec_version = "1.0"` (`catalog.py:170`) stays untouched.

### DD-4 — AD-1095 default-inert behaviour is preserved exactly
With no `issuer_public_key_b64` supplied, `verify_manifest_signature` returns `False` and `verify_entry` leaves `signature_verified=False` — byte-identical to today. `test_signature_present_but_always_unverified_v1` and the AD-1047 suite must pass unchanged.

### DD-5 — Preserve the ARD purity invariant
`jcs.py` must have **zero** `probos` imports. `trust_verifier.py` keeps its current single lazy import of `device_pairing.verify_signature`; do not add more.

### DD-6 — Do not touch the commercial repo
`AD-C-027` migration is a separate, follow-on change in the private overlay, unblocked by this AD's dual-verify. State this in the build report; change nothing under the commercial tree.

---

## Build

1. **`src/probos/federation/ard/jcs.py` (NEW)** — pure-stdlib RFC 8785 canonicalizer. Public: `canonicalize(value: object) -> bytes`. Rejects NaN/Infinity (JCS-invalid) with a clear `ValueError`. Full type annotations.
2. **`trust_verifier.py`** — add `_verify_jws_detached(...)`; make `verify_manifest_signature` dispatch legacy-vs-JWS on signature shape; keep the AD-1095 honest-degrade contract (never raises, returns `False`).
3. **Signing helper (verify-side parity)** — a pure `build_signing_input(manifest) -> bytes` used by both verify paths and consumable by an issuer, so OSS and the commercial issuer share one definition of the signing input.
4. **Tests** — `tests/test_ad1144_jcs_jws.py`.

## Acceptance

- **RFC 8785 conformance:** the published JCS test vectors pass, explicitly including (a) a key containing a non-BMP character, proving UTF-16-code-unit ordering differs from `sort_keys=True`, and (b) the number-formatting vectors. A test asserts the JCS output **differs** from `json.dumps(sort_keys=True, separators=(",",":"))` for the non-BMP case — that divergence is the whole point.
- **Dual-verify:** a manifest signed under the legacy scheme still verifies; a manifest signed as detached JWS verifies; a JWS with a tampered header or payload fails.
- **Default-inert:** no key supplied ⇒ `False`; `test_ad1047` and AD-1095's `test_signature_present_but_always_unverified_v1` pass **unchanged**.
- **Purity:** an assertion that `probos/federation/ard/jcs.py` contains zero `probos` imports, and that `trust_verifier.py`'s `probos` import count is unchanged (currently 1).
- **Interop shape:** the emitted `signature` parses as a JWS compact serialization (three dot-separated segments, middle empty for detached) and its protected header decodes to valid JSON with `alg: "EdDSA"`.
- Real Ed25519 fixtures per BF-287 (`generate_keypair` / `sign_challenge`), no mocks in the crypto path.
- Clean-checkout portable; no dependency added to `pyproject.toml`.
- Verify compliance with `.github/copilot-instructions.md`.

## Validation plan

- **Focused coding gate:** `tests/test_ad1144_jcs_jws.py tests/test_ad1095_manifest_signature_verify.py tests/test_ad1047_ard_trust_verify.py -n 0`
- **Adjacent regression gate:** the ARD suite — `tests/test_ad1040*.py tests/test_ad1046*.py tests/test_ad1048*.py tests/test_ad1049*.py tests/test_ad1050*.py tests/test_ad1051*.py -n 0` (verify each path exists at build; skip any that do not).
- **Wave-close gate (after Architect review):** `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 16 --dist=loadfile` with isolated `PROBOS_DATA_DIR` and `PROBOS_EMBEDDINGS=local`.
- **Clean-checkout gate:** CI green on HEAD.
- No UI change ⇒ no Vitest/Playwright/build gate.

## Do NOT build here

❌ PROV-O provenance vocabulary alignment (AD-1145). ❌ OpenTelemetry export or cognitive semantic conventions (AD-1145). ❌ W3C DID node identity. ❌ Any change to the commercial `AD-C-027` issuer. ❌ Any change to `AiCatalog.spec_version` or the catalog envelope shape. ❌ Removing the legacy verify path — dual-verify stays until the commercial issuer has migrated. ❌ Adding a JOSE/JCS third-party dependency. ❌ Touching the Tier 1 sovereign filters or anything in the Σ epic. ❌ A new BF number — none is needed here.

## Files (verify each at build)

- `src/probos/federation/ard/jcs.py` (NEW) — RFC 8785 canonicalizer, pure stdlib.
- `src/probos/federation/ard/trust_verifier.py` — JWS detached verification + shape dispatch + shared signing-input helper.
- `tests/test_ad1144_jcs_jws.py` (NEW) — conformance vectors, dual-verify, tamper, purity, interop shape.

## Done-when

All acceptance green; focused + adjacent gates green; Architect review findings repaired; consolidated wave-close and clean-checkout CI green; AD-1095/AD-1047 suites pass unchanged; ARD purity invariant asserted; full type annotations on new public functions; **verify compliance with `.github/copilot-instructions.md`.**
