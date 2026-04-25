# BF-208 Build Prompt: Scout Duty-Triggered Perceive Fix

**Issue:** #286
**Priority:** Medium — scout duty reports always return 0 findings
**Scope:** 1 file modified, 1 test file created

## Context

The Scout agent's duty schedule fires `proactive_think` with
`params.duty.duty_id == "scout_report"`. The `act()` method already
handles this (BF-177, line 354), but `perceive()` does not. The bug:

```
perceive() receives intent_name == "proactive_think"
→ line 282: not "scout_report", skip
→ line 287: not "scout_search", RETURN EARLY
→ GitHub search never runs
→ act() receives empty context
→ "No new findings to report."
```

The crew has noticed — Wesley (Scout) reports 0 findings every cycle.
Ward Room thread discussing the issue.

## Root Cause

`perceive()` (line 277) only recognizes two intents: `scout_search`
(interactive command) and `scout_report` (show cached report). The duty
scheduler sends `proactive_think` with duty params — a third path that
`perceive()` doesn't handle.

## Fix

**Approach:** After the `scout_report` cache check (line 285) and
before the `scout_search` guard (line 287), add a duty-trigger check
that falls through to the GitHub search pipeline.

## Change 1: `src/probos/cognitive/scout.py` — `perceive()` method

**Location:** Between line 285 (`return result`) and line 287
(`if intent_name != "scout_search":`).

**Insert this block after line 285:**

```python
        # BF-208: Duty-triggered proactive_think should run GitHub search.
        # The duty scheduler sends proactive_think with params.duty.duty_id
        # == "scout_report". perceive() must recognize this as a search trigger,
        # not just scout_search from interactive commands.
        _duty = result.get("params", {}).get("duty")
        if intent_name == "proactive_think" and _duty and _duty.get("duty_id") == "scout_report":
            intent_name = "scout_search"  # Fall through to search pipeline below
```

This reassigns `intent_name` so the existing `if intent_name != "scout_search":` guard passes through, and the entire GitHub search pipeline (lines 290-348) executes normally.

**Why reassign `intent_name` instead of duplicating the pipeline?**
- DRY: the search pipeline is 60 lines. Duplicating it creates divergence risk.
- The pipeline doesn't use `intent_name` after line 287. Reassigning is safe.
- `act()` already reads duty from `decision.get("duty", {})` independently (BF-177).

**The complete `perceive()` method after the fix should read:**

```python
    async def perceive(self, intent: dict[str, Any]) -> dict[str, Any]:
        """Search GitHub for recent AI agent repositories."""
        result = await super().perceive(intent)
        intent_name = result.get("intent", "")

        if intent_name == "scout_report":
            report_text = self._load_latest_report()
            result["context"] = report_text or "No scout reports found yet. Run /scout to generate one."
            return result

        # BF-208: Duty-triggered proactive_think should run GitHub search.
        # The duty scheduler sends proactive_think with params.duty.duty_id
        # == "scout_report". perceive() must recognize this as a search trigger,
        # not just scout_search from interactive commands.
        _duty = result.get("params", {}).get("duty")
        if intent_name == "proactive_think" and _duty and _duty.get("duty_id") == "scout_report":
            intent_name = "scout_search"  # Fall through to search pipeline below

        if intent_name != "scout_search":
            return result

        seven_days_ago = ...  # rest unchanged
```

---

## Change 2: Test File — `tests/test_bf208_scout_duty_perceive.py`

Create a new test file with these tests:

### Test 1: `test_duty_triggered_perceive_runs_search`
- Create a ScoutAgent instance
- Mock `super().perceive()` to return `{"intent": "proactive_think", "params": {"duty": {"duty_id": "scout_report", "description": "..."}}, "context": ""}`
- Mock `_search_github` to return a sample repo item list (at least 1 item)
- Mock `_load_seen` to return empty dict, `_save_seen` to no-op
- Call `await scout.perceive(intent)`
- Assert result["context"] contains "Classify these" (search ran)
- Assert result["context"] contains the repo full_name

### Test 2: `test_non_scout_duty_does_not_trigger_search`
- Same setup but with `params.duty.duty_id == "watch_report"` (not scout_report)
- Call `await scout.perceive(intent)`
- Assert result["context"] is empty or does NOT contain "Classify these"
- Verifies the guard only matches `scout_report` duty

### Test 3: `test_proactive_think_without_duty_stays_silent`
- `intent_name == "proactive_think"`, `params.duty` is `None`
- Call perceive
- Assert early return (no search triggered)

### Test 4: `test_interactive_scout_search_still_works`
- `intent_name == "scout_search"`, no duty params
- Mock `_search_github` to return items
- Call perceive
- Assert search pipeline runs (result contains "Classify these")
- Verifies we didn't break the interactive path

### Test 5: `test_scout_report_cache_still_works`
- `intent_name == "scout_report"`, no duty params
- Mock `_load_latest_report` to return a digest string
- Call perceive
- Assert result["context"] contains the cached report text
- Verifies we didn't break the cache path

### Import pattern:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from probos.cognitive.scout import ScoutAgent, _load_seen, _save_seen
```

### Mocking pattern for `super().perceive()`:

```python
# Patch CognitiveAgent.perceive to return the test observation
with patch("probos.cognitive.cognitive_agent.CognitiveAgent.perceive", new_callable=AsyncMock) as mock_perceive:
    mock_perceive.return_value = {
        "intent": "proactive_think",
        "params": {"duty": {"duty_id": "scout_report", "description": "..."}},
        "context": "",
    }
    result = await scout.perceive(intent_msg)
```

### ScoutAgent construction:

```python
scout = ScoutAgent(agent_id="test-scout")
scout.callsign = "Wesley"  # class attribute, not constructor param
```

`callsign` is a class attribute on `BaseAgent` (line 31 of `substrate/agent.py`),
not a constructor kwarg. Set it directly after construction. `pool` defaults to
`"scout"` in `ScoutAgent.__init__`.

---

## What NOT to change

- **Do NOT modify `act()`** — BF-177 already handles duty-triggered proactive_think
- **Do NOT modify the search pipeline** (lines 290-348) — it works correctly
- **Do NOT modify the `_search_github` method** — the HTTP/GitHub layer is fine
- **Do NOT add new intents to `_handled_intents`** — `proactive_think` is handled by CognitiveAgent, not Scout-specific
- **Do NOT modify `intent_descriptors`** — these are for the intent router, not duty scheduling

## Validation

```bash
python -m pytest tests/test_bf208_scout_duty_perceive.py -v
python -m pytest tests/ -k "scout" --timeout=30 -x
```

## Files Modified

| File | Change |
|------|--------|
| `src/probos/cognitive/scout.py` | 5-line duty-trigger check in `perceive()` |
| `tests/test_bf208_scout_duty_perceive.py` | 5 new tests |
