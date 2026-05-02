# AD-528 Build Report

**Date:** 2026-05-01
**Builder:** Wave 7 continuous-build (3 of 5)

## Sections Implemented

| Section | File | Status |
|---|---|---|
| Section 0+3: EventTypes | `src/probos/events.py` | ✅ Added `VERIFICATION_PASSED`, `VERIFICATION_FAILED` after AD-456 events |
| Section 1: GroundTruthVerifier + GroundTruthResult | `src/probos/cognitive/ground_truth.py` (new) | ✅ |
| Section 2: VerificationEpisodeWriter | `src/probos/cognitive/ground_truth.py` (continued) | ✅ Constructs typed `Episode` per `types.py:411`; uses `MemorySource.DIRECT.value` |
| Section 4: GroundTruthConfig | `src/probos/config.py` | ✅ Added Pydantic class + field on `SystemConfig` |
| Section 5: finalize.py wiring | `src/probos/startup/finalize.py` | ✅ Wires `runtime.ground_truth_verifier` + `runtime.verification_episode_writer` (always-wired with `None` when disabled) |
| Section 6: ALLOWED_EXCEPTIONS entry | `tests/test_layer_boundaries.py` | ✅ Mirrors AD-451 / BF-085 precedent |
| Tests | `tests/test_ad528_ground_truth.py` (new) | ✅ 14/14 pass at `-n 0` |
| Tracking | `PROGRESS.md`, `docs/development/roadmap.md:6489` | ✅ Updated |

## Test Results

- Focused gate: `pytest tests/test_ad528_ground_truth.py tests/test_layer_boundaries.py -v -n 0` → **16/16 passed in 0.97s** (14 AD-528 + 2 layer-boundary)
- Full parallel gate: **10,434 passed (+14 vs AD-456 baseline 10,420), 14 skipped, 151 warnings in 348.41s**

## Notes / Decisions

- **Live attribute discrepancy fix:** the prompt's Section 1 used `getattr(rt, "workforce", ...)` but `runtime.workforce` does not exist; the real public attribute is `runtime.work_item_store` (verified at `runtime.py:212` / `421` / `1532`; `WorkItemStore` is the class with `get_booking_journal`). Implementation uses `runtime.work_item_store`; the ALLOWED_EXCEPTIONS comment and tests both reflect this. The `BookingJournal` class is still imported under TYPE_CHECKING from `probos.workforce` (the module exists at workforce.py:738) — only the runtime-attribute access path was wrong in the draft prompt.
- Episode is a typed dataclass (per Wave 7 R#1) — no `dict` payload. `MemorySource.DIRECT.value` matches AD-541 "agent personally experienced this." `importance=7` for failed verifications, `4` for passed (failed = audit-relevant per AD-598).
- 600-second `event_window_seconds` is intentional — AD-528b active rejection should tighten.
- `claimed_summary` truncated to 1000 chars in `Episode.user_input` (long summaries reconstructable via booking_id).
- Active rejection / quarantine wholesale-deferred to AD-528b; trust-network feedback to AD-528c; ReconciliationEscalator integration is orthogonal in v1 (AD-451 covers verifier-vs-verifier disagreement; AD-528 covers did-it-happen-at-all).

## Pre-Commit Sanity Check

7 files changed, ~430 insertions, 1 deletion (roadmap status flip). Max per-file deletion: 1 line. Well under 200-line threshold.
