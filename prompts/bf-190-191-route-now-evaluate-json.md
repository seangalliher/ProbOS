# BF-190/BF-191: Route `now` NameError + Evaluate Raw JSON Pass-Through

## Overview

Two bugs discovered 2026-04-16:

1. **BF-190:** `NameError: name 'now' is not defined` in `_route_to_agents()`. BF-188 extracted the agent routing loop into `_route_to_agents()` but didn't bring the `now = time.time()` variable. Crash prevents all Ward Room routing after the first event.

2. **BF-191:** Evaluate step scores raw intent JSON (`{"intents": []}`) as `pass=True, score=1.00`. The LLM judge evaluates 15 chars of JSON as a high-quality post. Reflect then "revises" it (still JSON). BF-172's guard in `proactive.py` catches it, but the chain should reject it at Evaluate — defense in depth. Affected agents: builder, architect, counselor (all during `proactive_think`).

## Root Causes

### BF-190
`route_event()` (line 365) computed `now = time.time()` before calling `_route_to_agents()`. After BF-188 extracted `_route_to_agents()` as a separate method, `now` is no longer in scope. The cooldown check at line 460 (`if now - last_response < cooldown`) crashes.

### BF-191
Compose step sometimes produces raw JSON (`{"intents": [...]}`) instead of natural language — LLM mode confusion from the decomposer/dispatcher prompt format contaminating `proactive_think`. Evaluate's LLM judge doesn't have a criterion for "response must be natural language". With 15 chars of input, the LLM has nothing meaningful to score against, so it defaults to `pass=True, score=1.00`.

## Fixes

### Part 1: BF-190 — Add `now` to `_route_to_agents()` (ward_room_router.py)

**Already applied** — add `import time as _time` and `now = _time.time()` at top of `_route_to_agents()`.

Also clean up dead code: remove `now = time.time()` at line 365 in `route_event()` (no longer used after extraction).

**Files:** `src/probos/ward_room_router.py`

### Part 2: BF-191 — Deterministic JSON rejection in Evaluate (evaluate.py)

Add a pre-LLM format validation check in `EvaluateHandler.__call__()`, after social obligation bypass but before the LLM judge call.

Check the compose output for raw JSON patterns:
```python
# BF-191: Deterministic JSON rejection — compose output must be natural language
compose_output = _get_compose_output(prior_results)
stripped = compose_output.strip()
if stripped.startswith("{") and ('"intents"' in stripped[:200] or '"intent"' in stripped[:200]):
    logger.warning(
        "BF-191: Evaluate rejected raw intent JSON from %s (%d chars)",
        callsign, len(compose_output),
    )
    return SubTaskResult(
        sub_task_type=SubTaskType.EVALUATE,
        name=spec.name,
        result={
            "pass": False,
            "score": 0.0,
            "criteria": {"format": {"pass": False, "reason": "Raw JSON instead of natural language"}},
            "recommendation": "suppress",
            "rejection_reason": "raw_json_output",
        },
        tokens_used=0,
        duration_ms=int((time.monotonic() - start) * 1000),
        success=True,
        tier_used="",
    )
```

**Location:** In `EvaluateHandler.__call__()`, after the social obligation bypass block (after line 270) and before the builder dispatch (line 272 `system_prompt, user_prompt = builder(...)`).

**Design rationale:**
- **Defense in depth:** BF-172 in proactive.py is the last-resort guard. Evaluate should catch this first — 0 wasted LLM tokens on reflect.
- **Deterministic, not LLM:** Pattern match, not LLM judgment. Avoids the problem of LLMs scoring garbage charitably.
- **Fail fast:** Returns `success=True` (the evaluate step itself succeeded) with `pass=False` (the draft failed). This triggers the suppress path in the existing chain flow.
- **No false positives:** Only catches responses starting with `{` containing `"intents"` — same pattern as BF-172. Normal JSON-in-prose won't match.

**Files:** `src/probos/cognitive/sub_tasks/evaluate.py`

### Part 3: Tests

**File:** `tests/test_bf190_bf191_route_evaluate.py`

#### BF-190 Tests (3 tests)

1. `test_route_to_agents_now_defined` — Call `_route_to_agents()` with a mock agent that has an expired cooldown. Verify no NameError and agent receives intent.

2. `test_route_to_agents_cooldown_enforced` — Call `_route_to_agents()` with a fresh cooldown entry. Verify agent is skipped (not called).

3. `test_route_event_no_dead_now` — Verify `route_event()` does not define unused `now` variable (grep/AST check or just verify it still works end-to-end).

#### BF-191 Tests (5 tests)

4. `test_evaluate_rejects_raw_intent_json` — Compose output is `{"intents": []}`. Evaluate returns `pass=False, score=0.0, recommendation="suppress"`.

5. `test_evaluate_rejects_intent_json_with_content` — Compose output is `{"intents": [{"intent": "ward_room_notification", ...}]}`. Rejected.

6. `test_evaluate_passes_normal_text` — Compose output is "I've observed unusual latency in the EPS conduits." Evaluate proceeds to LLM judge (not rejected by format check).

7. `test_evaluate_passes_json_in_prose` — Compose output is "The analysis shows `{"status": "ok"}` in the logs." Not rejected (doesn't start with `{`).

8. `test_evaluate_json_rejection_zero_tokens` — Verify JSON rejection uses 0 tokens (no LLM call).

## Engineering Principles

- **Defense in Depth:** JSON rejection at Evaluate (deterministic) + BF-172 at proactive.py (last resort). Two independent checks.
- **Fail Fast:** Reject immediately on pattern match, don't send to LLM judge.
- **DRY:** Same detection pattern as BF-172 (`startswith("{") and '"intents"' in`). Could extract to shared util but only 2 call sites — premature abstraction.
- **Single Responsibility:** Evaluate judges quality. Format validation is a precondition to quality judgment.
- **Open/Closed:** New check is an early-return before existing LLM flow — no modification to the LLM judge logic.

## Implementation Order

Part 1 (BF-190, already applied) → Part 2 (BF-191 evaluate guard) → Part 3 (tests)

## Verification

```bash
python -m pytest tests/test_bf190_bf191_route_evaluate.py -v
```
