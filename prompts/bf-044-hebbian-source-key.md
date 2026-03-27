# BF-044: Hebbian Routing Source Key Bug

## Problem

`runtime.py` records Hebbian interactions with `source=msg.id` — a unique UUID per intent message. This means every interaction creates a brand-new weight key that is never reinforced by subsequent interactions. Hebbian learning never accumulates. The correct pattern is in `feedback.py` (line 80) which uses `source=intent` — the intent name string, so repeated routing of the same intent type to the same agent strengthens the connection over time.

Secondary effect: the HXI renders Hebbian curves using the source key to find the source agent's position. A UUID doesn't match any agent → falls back to the target's pool center → curve goes from pool center to the agent (nearly the same point) → "goes nowhere."

## Files to Modify

1. `src/probos/runtime.py` — 2 methods, 4 line changes total
2. `tests/test_consensus_integration.py` — add/update tests to verify intent name is used as source

## Fix 1: `submit_intent()` — lines 1761-1771

**Current code (line 1761-1771):**
```python
        for result in results:
            self.hebbian_router.record_interaction(
                source=msg.id,  # intent as source
                target=result.agent_id,
                success=result.success,
            )

            # Emit hebbian_update for HXI (AD-254)
            self._emit_event("hebbian_update", {
                "source": msg.id,
                "target": result.agent_id,
                "weight": round(self.hebbian_router.get_weight(msg.id, result.agent_id), 4),
                "rel_type": "intent",
            })
```

**Change to:**
```python
        for result in results:
            self.hebbian_router.record_interaction(
                source=intent,  # intent name, not msg UUID — enables reinforcement
                target=result.agent_id,
                success=result.success,
            )

            # Emit hebbian_update for HXI (AD-254)
            self._emit_event("hebbian_update", {
                "source": intent,
                "target": result.agent_id,
                "weight": round(self.hebbian_router.get_weight(intent, result.agent_id), 4),
                "rel_type": "intent",
            })
```

The variable `intent` is the string parameter of `submit_intent(self, intent: str, ...)` — already in scope.

## Fix 2: `submit_intent_with_consensus()` — lines 1821-1833

**Current code (lines 1821-1833):**
```python
        for result in results:
            self.hebbian_router.record_interaction(
                source=msg.id,
                target=result.agent_id,
                success=result.success,
            )

            # Emit hebbian_update for HXI (AD-254)
            self._emit_event("hebbian_update", {
                "source": msg.id,
                "target": result.agent_id,
                "weight": round(self.hebbian_router.get_weight(msg.id, result.agent_id), 4),
                "rel_type": "intent",
            })
```

**Change to:**
```python
        for result in results:
            self.hebbian_router.record_interaction(
                source=intent,
                target=result.agent_id,
                success=result.success,
            )

            # Emit hebbian_update for HXI (AD-254)
            self._emit_event("hebbian_update", {
                "source": intent,
                "target": result.agent_id,
                "weight": round(self.hebbian_router.get_weight(intent, result.agent_id), 4),
                "rel_type": "intent",
            })
```

Same pattern — `intent` is the string parameter of `submit_intent_with_consensus(self, intent: str, ...)`.

## Fix 3: Tests

Add tests in `tests/test_consensus_integration.py` (or a new `tests/test_hebbian_source_key.py` if cleaner) that verify:

1. **`test_hebbian_uses_intent_name_as_source`** — Call `submit_intent("run_diagnostic", ...)`. Check that `hebbian_router.get_weight("run_diagnostic", agent_id)` returns a non-zero value. Verify `get_weight(msg.id, agent_id)` is NOT set (i.e., the UUID was not used).

2. **`test_hebbian_reinforcement_across_calls`** — Call `submit_intent("run_diagnostic", ...)` twice with the same intent name. Verify the weight for `("run_diagnostic", agent_id)` is higher after the second call than after the first (reinforcement works).

3. **`test_hebbian_consensus_uses_intent_name`** — Same as test 1 but for `submit_intent_with_consensus()`.

4. **`test_hebbian_event_emits_intent_name`** — Verify the `hebbian_update` event payload contains `"source": "run_diagnostic"` (the intent name string), not a UUID pattern.

## Constraints

- Do NOT modify `feedback.py` — it already uses the correct pattern
- Do NOT change the HebbianRouter API — only change what `source` value is passed
- The `msg.id` is still used correctly in the event_log lines (1778, etc.) — leave those unchanged
- Run tests with `uv run pytest -n auto` to verify. Target: all green.

## Reference

- Correct pattern: `src/probos/cognitive/feedback.py` line 80-85 (`source=intent`)
- HebbianRouter API: `record_interaction(source, target, success, rel_type)`
- HXI connection rendering: `ui/src/components/connections.tsx` (uses source key to find agent position)
