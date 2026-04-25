# BF-145: Align Pre-Existing Tests with AD-593 Changes

**Priority:** High
**Issue:** #(TBD)
**Depends on:** AD-593 (complete)

## Problem

AD-593 introduced two changes that broke 6 pre-existing tests:

1. **Similarity floor raised** (`agent_recall_threshold` 0.15 → 0.25): Two tests in `test_ad567b_anchor_recall.py` assert the old default.
2. **Two-tier dream pruning**: Four tests in `test_ad567d_dream_provenance.py` were written for single-tier pruning. AD-593 added an aggressive tier (enabled by default), so `find_low_activation_episodes()` is now called twice and `evict_by_ids()` is called twice with different reasons (`activation_decay` + `activation_decay_aggressive`).

These are test expectation updates — no source code changes required.

## Root Cause Analysis

### Threshold tests (2 failures)

| Test | File:Line | Old Assertion | Fix |
|---|---|---|---|
| `test_agent_recall_threshold_default` | `test_ad567b_anchor_recall.py:535` | `assert em._agent_recall_threshold == 0.15` | Change to `== 0.25` |
| `test_threshold_and_anchor_gate_work_together` | `test_ad567b_anchor_recall.py:594` | `assert cfg.agent_recall_threshold == 0.15` | Change to `== 0.25` |

Both tests verify default values. AD-593 raised the default from 0.15 to 0.25. Update docstrings too (line 532: `"Default agent_recall_threshold is 0.15 (not 0.3)."` → `"Default agent_recall_threshold is 0.25."`).

### Dream Step 12 tests (4 failures)

All in class `TestDreamStep12` in `test_ad567d_dream_provenance.py`.

The test fixture `_make_dreaming_engine()` (line 376) creates a `DreamingConfig` that does NOT set `aggressive_prune_enabled=False`. Since AD-593 defaults `aggressive_prune_enabled=True`, the aggressive tier runs in all tests.

The mock `get_episode_ids_older_than` returns the same IDs for both the standard cutoff (24h) and aggressive cutoff (168h) since time-based filtering happens in the real implementation but the mock just returns whatever was set.

**Fix strategy:** Add `aggressive_prune_enabled=False` to the `_make_dreaming_engine` fixture's `DreamingConfig`. This restores single-tier behavior for existing tests, which specifically test standard-tier pruning logic. AD-593's own test file (`test_ad593_pruning_acceleration.py`) already covers two-tier behavior with 24 dedicated tests.

This is correct because:
- These tests document standard-tier behavior — they should continue to test exactly that
- Adding aggressive-tier awareness to these tests would duplicate AD-593's test coverage
- The fixture change is minimal (one field) and self-documenting

**Affected tests (all fixed by the fixture change):**

| Test | Line | Current Failure | Root Cause |
|---|---|---|---|
| `test_dream_step_12_prunes_low_activation` | 411 | `assert report.activation_pruned == 2` fails (gets 4) | Both tiers prune same candidates × 2 |
| `test_dream_step_12_respects_cap` | 452 | `max_prune_fraction == 0.10` fails (gets 0.25) | Last call is aggressive tier with 0.25 fraction |
| `test_dream_step_12_eviction_audit` | 472 | `evict_by_ids.assert_called_once_with(...)` fails (called 2x) | Standard + aggressive both evict |
| `test_dream_step_12_skips_unknown_episode_ids` | 512 | `evict_by_ids.assert_called_once()` fails (called 2x) | Standard + aggressive both evict ghost ID |

## Implementation

### File 1: `tests/test_ad567b_anchor_recall.py`

**Change 1a — Line 532:** Update docstring.
```python
# BEFORE:
"""Default agent_recall_threshold is 0.15 (not 0.3)."""

# AFTER:
"""Default agent_recall_threshold is 0.25 (AD-593 raised from 0.15)."""
```

**Change 1b — Line 535:** Update assertion.
```python
# BEFORE:
assert em._agent_recall_threshold == 0.15

# AFTER:
assert em._agent_recall_threshold == 0.25
```

**Change 1c — Line 594:** Update assertion.
```python
# BEFORE:
assert cfg.agent_recall_threshold == 0.15

# AFTER:
assert cfg.agent_recall_threshold == 0.25
```

### File 2: `tests/test_ad567d_dream_provenance.py`

**Change 2a — `_make_dreaming_engine` fixture (line 379-383):** Add `aggressive_prune_enabled=False` to DreamingConfig.
```python
# BEFORE:
config = DreamingConfig(
    activation_enabled=activation_enabled,
    activation_prune_threshold=-2.0,
    activation_access_max_age_days=180,
)

# AFTER:
config = DreamingConfig(
    activation_enabled=activation_enabled,
    activation_prune_threshold=-2.0,
    activation_access_max_age_days=180,
    aggressive_prune_enabled=False,  # BF-145: isolate standard-tier tests from AD-593 aggressive tier
)
```

No other changes needed in this file. The fixture change fixes all 4 failing tests.

## Files Modified

| File | Change | Lines |
|---|---|---|
| `tests/test_ad567b_anchor_recall.py` | Update 2 assertions + 1 docstring for new 0.25 default | 532, 535, 594 |
| `tests/test_ad567d_dream_provenance.py` | Add `aggressive_prune_enabled=False` to fixture | 379-383 |

## Files NOT Modified

- **No source files** — this is purely a test alignment fix
- `tests/test_ad593_pruning_acceleration.py` — AD-593's own tests already cover two-tier behavior
- `tests/test_ad590_composite_score_floor.py` — unaffected
- `tests/test_ad591_quality_aware_budget.py` — unaffected

## Testing

### New tests: None
No new tests — this BF updates existing test expectations.

### Verification
```bash
# 1. Verify all 6 previously-failing tests now pass
pytest tests/test_ad567b_anchor_recall.py::TestBF134ThresholdAndFloor::test_agent_recall_threshold_default tests/test_ad567b_anchor_recall.py::TestBF134ThresholdAndFloor::test_threshold_and_anchor_gate_work_together tests/test_ad567d_dream_provenance.py::TestDreamStep12 -v

# 2. Full regression on related test files
pytest tests/test_ad567b_anchor_recall.py tests/test_ad567d_dream_provenance.py tests/test_ad593_pruning_acceleration.py -v

# 3. Broader dreaming regression
pytest tests/test_dreaming.py -v
```

All must pass before committing.

## Tracking

Update these files:
- `PROGRESS.md` — add BF-145 as closed
- `DECISIONS.md` — add BF-145 entry
- `docs/development/roadmap.md` — add BF-145 to Bug Tracker table

## Engineering Principles Compliance

- **No source changes** — test-only fix, zero production risk
- **DRY** — fixture change fixes 4 tests at once rather than patching each test individually
- **Fail Fast** — tests continue to assert specific behavior rather than loosening assertions
- **SOLID (SRP)** — standard-tier tests remain focused on standard-tier behavior; aggressive-tier coverage lives in AD-593's dedicated test file
