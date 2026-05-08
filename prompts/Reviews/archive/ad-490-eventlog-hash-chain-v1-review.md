# Review: AD-490 v1 — EventLog hash chain (substrate-tier tamper detection)
**Verdict:** ✅ Approved
**Highest-risk prompt in the wave (substrate write path + on-disk migration). Sound design; two Recommended sharpenings to nail down determinism guarantees.**

## Required (must fix before building)
_None._

## Recommended
1. **Determinism contract for `data` JSON serialization is implicit.** The hash payload includes `data: data_json` (a string). The current `log()` already produces `data_json` via `json.dumps`, but its sort_keys behavior is not pinned in the prompt — and any change in upstream serialization would silently break `verify_chain()` on rehash. Spec it explicitly: "`data_json` MUST be produced via `json.dumps(payload_dict, sort_keys=True, default=str)` at the existing call site; if it isn't already, add this in the same commit." Grep `event_log.py` lines 99–131 for the existing `data_json` construction and either confirm or fix in scope.
2. **Test #3 description is muddy.** "identical hashes modulo prev_hash linkage" is hard to read and harder to assert. Rephrase as a direct call to `_compute_row_hash(prev_hash="X", payload=P)` twice with identical args, asserting equality. The intent is "the helper is a pure function" — say that.

## Nits
1. D1 `_SCHEMA` rewrites the entire CREATE TABLE — confirm this matches the existing CREATE statement byte-for-byte except for the two appended columns; otherwise on a brand-new DB the order/defaults of the AD-664 columns might shift.
2. D5's two-clause failure (recomputed-hash mismatch OR `prev_hash` column mismatch) returns the same `(False, row.id)` — it's correct but hides which clause fired. Consider returning the reason as a third tuple element in a v2.
3. AuditLog precedent uses `verify_chain() -> bool`; AD-490 returns `tuple[bool, int | None]`. The richer return is justified by SQL row identification — the prompt notes this. Keep it.
4. No new EventType for chain breaks is the right call. Detection-on-demand is the correct v1 surface.

## Verified
- ✅ AD-456 hash-chain pattern at `security/audit.py:65` (`GENESIS_HASH = "0" * 64`), `:120` (`verify_chain`), `:68` (`prior_hash` lookup).
- ✅ EventLog migration pattern at `event_log.py:60` (`_migrate_ad664`); call site at `:57`.
- ✅ `events` table primary key is `id INTEGER PRIMARY KEY AUTOINCREMENT` — chain order = ascending `id`.
- ✅ Schema is additive; no existing caller of `log()` needs to change (`log()`'s public signature unchanged).
- ✅ All 8 test names cover the boundary surface (genesis row, chain link, idempotent helper, empty table, intact chain, tampered detail, tampered prev_hash, migration).
- ✅ `pytest.mark.asyncio` + `default_factory` test stack matches the AD-664 test precedent.

## Risk
MEDIUM-HIGH. Substrate write path + migration on a hot table. Mitigated by additive-schema discipline (no caller changes), the AD-456 precedent, and the 8-test boundary coverage. The prompt's "do NOT remove AD-664 migration" guardrail is essential.

## Pass 2 Review (2026-05-08)

**Verdict:** ✅ Approved — determinism contract pinned; test #3 is now a direct purity assertion.

### Required / Recommended / Nits
None.

### Verified
- **Recommended #1 landed**: Verified-Against-Codebase flags `event_log.py:120` lacks `sort_keys=True`; D4 step 0 fixes it inline. D3 helper docstring states canonical form. Determinism contract consistent across helper, write path, and verifier.
- **Recommended #2 landed**: Test #3 renamed `test_compute_row_hash_is_pure` with direct purity assertion.
- AuditLog precedent at `security/audit.py:65,68,120,122` confirmed; AD-490 mirrors faithfully with the richer `(bool, int | None)` return.
- 8 tests cover genesis, chaining, purity, empty, intact, tampered detail, tampered prev_hash, migration. Boundary coverage adequate.
- Phantom-API sweep: clean.
