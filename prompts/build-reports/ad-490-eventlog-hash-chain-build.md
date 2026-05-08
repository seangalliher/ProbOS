# AD-490 EventLog Hash Chain Build Report

**Title:** EventLog hash chain (substrate-tier tamper detection)
**Prompt:** `prompts/ad-490-eventlog-hash-chain-v1.md`
**Builder:** Builder agent (continuous-build, Wave 129)
**Date:** 2026-05-08
**Status:** SHIPPED

> Note: An earlier AD-490 ("Agent Wiring Security Logs") shipped 2026-04-30 with build report at `ad-490-build.md`. This Wave-129 prompt reuses the AD number (per architect dispatch) for a different deliverable on the substrate EventLog. New report saved as `ad-490-eventlog-hash-chain-build.md` to avoid collision.

## Files Changed

- `src/probos/substrate/event_log.py` — additive: import `hashlib`, `_compute_row_hash()` helper, `GENESIS_HASH` class constant, `_migrate_ad490()` migration, hash chain in `log()` (with `sort_keys=True` determinism fix on `data_json`), new `verify_chain()` method.
- `tests/test_ad490_eventlog_hash_chain.py` — new (8 tests).

## Sections Implemented

- **D1** Schema additions: `prev_hash` and `row_hash` columns added to `_SCHEMA`. ✅
- **D2** `_migrate_ad490()` migration mirroring AD-664; called from `start()` after `_migrate_ad664()`. ✅
- **D3** `_compute_row_hash()` module-level pure helper (SHA-256 over `prev_hash || canonical_json(payload)`). ✅
- **D4** `log()` write path: determinism fix (`sort_keys=True`), prev-hash lookup, payload assembly, INSERT now includes both new columns. Public signature unchanged. ✅
- **D5** `verify_chain() -> tuple[bool, int | None]` walker. Empty table -> `(True, None)`. Detects tampered detail and tampered prev_hash. ✅
- **D6** 8 tests in new file: genesis, chain, purity, empty, intact, tampered row, tampered prev_hash, legacy migration. ✅

## Post-Build Section Audit

Every D# section maps to implemented code. No omissions.

## Test Results

- Focused: `pytest tests/test_ad490_eventlog_hash_chain.py -v -n 0` → **8/8 pass** in 0.48s.
- Adjacent regression: `pytest tests/test_ad664_eventlog_diagnostic.py -q -n 0` → **17/17 pass** in 0.57s.
- Full gate: `pytest tests/ -q -n 8 --dist=loadfile` → **12738 passed, 16 skipped** in 8m21s. Test count up by 8 (baseline 12730 passed → 12738).

## Deviations

None. Prompt implemented as written.
