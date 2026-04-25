# BF-217: Post-Batch Test Regressions + DRY Cleanup

**Status:** Ready for builder
**Scope:** Fix 3 test regressions introduced by AD-644/645/646 batch, extract 2 DRY violations, delete 1 dead test file.

---

## Overview

The AD-644 through AD-651a batch changed production code (analyze max_tokens, prompt field counts, communication context logic) without updating all pre-existing tests. Additionally, two constants/functions are duplicated between production and test code. And `test_bf194_department_gate_scope.py` tests a method (`check_and_increment_reply_cap`) that was removed by BF-201 — it's 371 lines of dead tests producing 9 failures.

---

## Fixes

### 1. Fix `test_max_tokens_1024` regression

**File:** `tests/test_ad632c_analyze_handler.py`
**Line:** 290

Production code (`src/probos/cognitive/sub_tasks/analyze.py:555`) now uses `max_tokens=1536`. Test still expects 1024.

**Fix:** Change:
```python
assert handler._llm_client.last_request.max_tokens == 1024
```
To:
```python
assert handler._llm_client.last_request.max_tokens == 1536
```

Also rename the test method from `test_max_tokens_1024` to `test_max_tokens_1536` to match.

### 2. Fix `test_thread_analysis_says_6_keys` regression

**File:** `tests/test_ad643a_intent_routing.py`
**Line:** 522-528

Production code (`src/probos/cognitive/sub_tasks/analyze.py:201`) now says "7 keys" (composition_brief was added as field 7, making the total 7). Test expects "6 keys".

**Fix:** Change:
```python
def test_thread_analysis_says_6_keys(self):
    """Thread analysis prompt says '6 keys'."""
    ...
    assert "6 keys" in user
```
To:
```python
def test_thread_analysis_says_7_keys(self):
    """Thread analysis prompt says '7 keys'."""
    ...
    assert "7 keys" in user
```

### 3. Fix `test_situation_review_says_5_keys` regression

**File:** `tests/test_ad643a_intent_routing.py`
**Line:** 514-520

Production code (`src/probos/cognitive/sub_tasks/analyze.py:402`) now says "6 keys". Test expects "5 keys".

**Fix:** Change:
```python
def test_situation_review_says_5_keys(self):
    """Situation review prompt says '5 keys'."""
    ...
    assert "5 keys" in user
```
To:
```python
def test_situation_review_says_6_keys(self):
    """Situation review prompt says '6 keys'."""
    ...
    assert "6 keys" in user
```

### 4. DRY: Extract `_AD646B_DEDICATED_KEYS` constant

**Currently duplicated in:**
- `src/probos/cognitive/sub_tasks/analyze.py:73`
- `src/probos/cognitive/sub_tasks/compose.py:355`

**Fix:** Define the constant once in `src/probos/cognitive/sub_tasks/__init__.py`:

```python
"""Shared constants for cognitive sub-task handlers."""

# AD-646b: Keys with dedicated rendering sections — excluded from
# generic "Prior Data" rendering to prevent double-display.
AD646B_DEDICATED_KEYS: frozenset[str] = frozenset({
    "self_monitoring",
    "introspective_telemetry",
})
```

Use `frozenset` (immutable, can't accidentally mutate).

Then update both files to import:
```python
from probos.cognitive.sub_tasks import AD646B_DEDICATED_KEYS
```

And replace the local `_AD646B_DEDICATED_KEYS` references with `AD646B_DEDICATED_KEYS`.

**In `analyze.py`** (line ~73): Remove the local definition, import from `__init__`, update references at line ~79.

**In `compose.py`** (line ~355): Remove the local definition, import from `__init__`, update references at line ~358.

### 5. DRY: Extract `derive_communication_context()`

**Currently:** Logic lives inline in `cognitive_agent.py` (lines 1831-1844) and is copy-pasted in `tests/test_ad649_communication_context.py` (lines 46-60).

**Fix:** Extract to a module-level function in `cognitive_agent.py`:

```python
def derive_communication_context(
    channel_name: str,
    is_dm_channel: bool = False,
) -> str:
    """AD-649: Derive communication register context from channel metadata."""
    if is_dm_channel or channel_name.startswith("dm-"):
        return "private_conversation"
    if channel_name == "bridge":
        return "bridge_briefing"
    if channel_name == "recreation":
        return "casual_social"
    if channel_name in ("general", "all-hands"):
        return "ship_wide"
    return "department_discussion"
```

Place it near the top of `cognitive_agent.py`, after imports, before the class definition. It's a pure function with no dependencies — just string mapping.

**Then update the inline usage** (lines 1831-1844). Replace the if/elif ladder with:

```python
observation["_communication_context"] = derive_communication_context(
    _channel_name, _is_dm_channel,
)
```

The proactive path also sets `_communication_context`. Search for `_communication_context` in `cognitive_agent.py` to find the proactive equivalent — it should use the same function call.

**Then update the test** (`tests/test_ad649_communication_context.py`). Replace the local `_derive_communication_context` helper (lines 46-60) with an import:

```python
from probos.cognitive.cognitive_agent import derive_communication_context
```

And update all test calls from `_derive_communication_context(obs)` to:
```python
derive_communication_context(
    channel_name=obs["params"]["channel_name"],
    is_dm_channel=obs["params"].get("is_dm_channel", False),
)
```

The test's `_make_observation` helper (lines 33-43) can stay — it's still useful for building observation dicts for other tests in the file. Only the `_derive_communication_context` function should be removed and replaced with the import.

### 6. Delete dead test file

**File to delete:** `tests/test_bf194_department_gate_scope.py`

This file (371 lines, 9 tests) tests `WardRoomRouter.check_and_increment_reply_cap()` which was removed by BF-201. `test_bf201_thread_post_cap.py::TestRemoval::test_no_check_and_increment_reply_cap` explicitly asserts the method no longer exists. The BF-194 tests are dead code producing 9 test failures.

**Just delete the file.** No replacement needed — BF-201 has its own tests covering the replacement behavior.

---

## Verification Checklist

1. `python -m pytest tests/test_ad632c_analyze_handler.py -v` — all pass, including renamed `test_max_tokens_1536`
2. `python -m pytest tests/test_ad643a_intent_routing.py -v` — all pass, including renamed key-count tests
3. `python -m pytest tests/test_ad649_communication_context.py -v` — all pass with imported function
4. `python -m pytest tests/test_ad645_composition_briefs.py tests/test_ad646b_chain_parity.py tests/test_ad651a_compose_billet.py -v` — regression check for compose/analyze changes
5. `grep -rn "_AD646B_DEDICATED_KEYS" src/` — should appear ONLY in `sub_tasks/__init__.py`
6. `grep -rn "derive_communication_context" src/ tests/` — production function in `cognitive_agent.py`, import in test
7. `ls tests/test_bf194_department_gate_scope.py` — should not exist
8. Full suite: `python -m pytest tests/ -x` — no new failures introduced

---

## Files Modified

| File | Change |
|------|--------|
| `tests/test_ad632c_analyze_handler.py` | Fix max_tokens assertion (1024 → 1536) |
| `tests/test_ad643a_intent_routing.py` | Fix key count assertions (6→7, 5→6) |
| `src/probos/cognitive/sub_tasks/__init__.py` | Add `AD646B_DEDICATED_KEYS` constant |
| `src/probos/cognitive/sub_tasks/analyze.py` | Import shared constant, remove local |
| `src/probos/cognitive/sub_tasks/compose.py` | Import shared constant, remove local |
| `src/probos/cognitive/cognitive_agent.py` | Extract `derive_communication_context()` function |
| `tests/test_ad649_communication_context.py` | Import production function, remove copy |
| `tests/test_bf194_department_gate_scope.py` | **DELETE** |

## Engineering Principles

- **DRY**: Two duplications eliminated (dedicated keys constant, communication context derivation)
- **SRP**: `derive_communication_context` extracted as a pure function — single responsibility, independently testable
- **Open/Closed**: Shared constant uses `frozenset` (immutable) — consumers can't modify
- **Test quality**: Tests now verify production logic directly, not reimplementations
