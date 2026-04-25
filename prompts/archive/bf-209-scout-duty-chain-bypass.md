# BF-209: Scout Duty Report Bypassed by Communication Chain — Build Prompt

**BF:** 209  
**Issue:** #290  
**Scope:** ~10 lines in 1 file. Zero new modules.

---

## Problem

Scout's duty-triggered `proactive_think` (duty_id=scout_report) routes through the cognitive communication chain (QUERY → ANALYZE → COMPOSE) because `proactive_think` is in `_CHAIN_ELIGIBLE_INTENTS`. The chain produces a natural language Ward Room post but **never calls `act()`** — so `parse_scout_reports()` never runs, findings are never stored, and the scout report is always empty.

The scout report is a data pipeline process (search → classify → store → notify), not a communication task. It needs `decide() → act()`, not QUERY → ANALYZE → COMPOSE.

---

## Fix

Override `_should_activate_chain()` in `ScoutAgent` (in `src/probos/cognitive/scout.py`).

Add this method to the `ScoutAgent` class, before the `perceive()` method (around line 246):

```python
def _should_activate_chain(self, observation: dict) -> bool:
    """BF-209: Scout report duty is a structured process, not a communication task.

    The scout report pipeline (parse → enrich → filter → store → notify)
    lives in act(). The communication chain bypasses act() entirely.
    Duty-triggered proactive_think must route through decide() → act().

    Ward room notifications still use the chain (communication task).
    """
    intent = observation.get("intent", "")
    if intent == "proactive_think":
        params = observation.get("params", {})
        duty = params.get("duty", {})
        if duty.get("duty_id") == "scout_report":
            return False
    return super()._should_activate_chain(observation)
```

**Key details:**
- Only `proactive_think` with `duty_id=scout_report` is excluded
- `ward_room_notification` still goes through the chain (communication task — correct behavior)
- Non-duty `proactive_think` still goes through the chain (idle review — correct behavior)
- `super()._should_activate_chain()` preserves all other gating logic (executor readiness, intent eligibility)

---

## What NOT To Change

- **`_CHAIN_ELIGIBLE_INTENTS`** — `proactive_think` should remain chain-eligible globally. This is a per-agent override, not a global change.
- **`act()`** — The structured pipeline is correct. No changes needed.
- **`perceive()`** — BF-208 fix is correct. No changes needed.
- **`cognitive_agent.py`** — No changes to the base class.

---

## Tests

Create `tests/test_bf209_scout_chain_bypass.py`.

### Test 1: Duty-triggered proactive_think bypasses chain

```
Given: A ScoutAgent with sub_task_executor enabled
When: _should_activate_chain(observation) is called with intent="proactive_think", params.duty.duty_id="scout_report"
Then: Returns False
```

### Test 2: Ward room notification still uses chain

```
Given: A ScoutAgent with sub_task_executor enabled
When: _should_activate_chain(observation) is called with intent="ward_room_notification"
Then: Returns True (delegates to super())
```

### Test 3: Non-duty proactive_think still uses chain

```
Given: A ScoutAgent with sub_task_executor enabled
When: _should_activate_chain(observation) is called with intent="proactive_think", no duty
Then: Returns True (delegates to super())
```

### Test 4: Chain disabled entirely returns False

```
Given: A ScoutAgent with no sub_task_executor
When: _should_activate_chain(observation) is called with intent="ward_room_notification"
Then: Returns False (super() gate fails)
```

---

## Verification Checklist

- [ ] Scout duty report generates findings (non-empty report file)
- [ ] Scout Ward Room notifications still work (communication chain)
- [ ] Non-scout agents unaffected
- [ ] `pytest tests/test_bf209_scout_chain_bypass.py -v` green
- [ ] `pytest tests/ -x -q` — no regressions
