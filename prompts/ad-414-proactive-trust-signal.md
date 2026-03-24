# AD-414: Proactive Loop Trust Signal — Build Prompt

## Context

After a `probos reset`, all trust scores start at 0.5 (Bayesian prior, alpha=2.0, beta=2.0). The proactive cognitive loop (Phase 28b) is now the primary source of agent activity, but `_think_for_agent()` in `proactive.py` calls `agent.handle_intent()` directly — bypassing consensus, routing, and the trust update pipeline. Only user-initiated work (via `process_natural_language()`) or QA cycles generate trust signals through `trust_network.record_outcome()`. If the proactive loop dominates activity (which it does post-reset), trust scores stagnate at priors indefinitely because the primary activity channel produces no trust signal.

**Goal:** The proactive loop should emit an attenuated trust signal — small enough that proactive thinks don't dominate trust (they're self-directed, not externally validated), but large enough that agents can slowly build trust through consistent, high-quality participation.

## Part 1: Add trust weight config fields to ProactiveCognitiveConfig

**File:** `src/probos/config.py`

Add three new fields to `ProactiveCognitiveConfig` (currently at line ~312):

```python
class ProactiveCognitiveConfig(BaseModel):
    """Proactive Cognitive Loop — periodic idle-think (Phase 28b)."""
    enabled: bool = False
    interval_seconds: float = 120.0
    cooldown_seconds: float = 300.0
    duty_schedule: DutyScheduleConfig = DutyScheduleConfig()
    # AD-414: Trust signal weights for proactive thinks
    trust_reward_weight: float = 0.1        # Trust signal for successful proactive think (posted to Ward Room)
    trust_no_response_weight: float = 0.0   # Trust signal for [NO_RESPONSE] (0 = no signal, silence is fine)
    trust_duty_bonus: float = 0.1           # Additional trust weight when completing a scheduled duty
```

**Key design decisions:**
- `trust_reward_weight = 0.1` — An agent that posts 10 successful proactive thoughts moves trust as much as 1 verified user task. This is intentional — proactive thinks are supplementary, not primary.
- `trust_no_response_weight = 0.0` — Silence is professionalism (AD-419). We don't punish or reward `[NO_RESPONSE]`. Set to 0 by default but configurable if the Captain wants to reward discipline.
- `trust_duty_bonus = 0.1` — Completing a scheduled duty gets an extra 0.1 on top of the base reward (total 0.2 for duty completion vs 0.1 for free-form). Duty compliance is valued higher than initiative.

## Part 2: Emit trust signal in `_think_for_agent()`

**File:** `src/probos/proactive.py`

Modify `_think_for_agent()` to emit trust signals at the appropriate points. The proactive loop needs access to `trust_network` — it should already be accessible via `self._runtime.trust_network`.

### 2a: After successful proactive think (posts to Ward Room)

After the existing `self._post_to_ward_room(agent, response_text)` call (~line 176), add:

```python
# AD-414: Emit attenuated trust signal for successful proactive think
trust_weight = self._config.trust_reward_weight
if duty:
    trust_weight += self._config.trust_duty_bonus  # Duty completion bonus
if trust_weight > 0:
    new_score = self._runtime.trust_network.record_outcome(
        agent.id,
        success=True,
        weight=trust_weight,
        intent_type="proactive_think",
    )
    # Emit trust_update event for HXI
    self._runtime.event_log.emit(
        "trust_update",
        agent_id=agent.id,
        agent_type=getattr(agent, "agent_type", "unknown"),
        new_score=new_score,
        weight=trust_weight,
        source="proactive",
        duty_id=duty.get("duty_id") if duty else None,
    )
```

### 2b: After [NO_RESPONSE] (silence)

In the `[NO_RESPONSE]` exit path (~line 169-173), add:

```python
# AD-414: Optional trust signal for disciplined silence
no_response_weight = self._config.trust_no_response_weight
if no_response_weight > 0:
    self._runtime.trust_network.record_outcome(
        agent.id,
        success=True,
        weight=no_response_weight,
        intent_type="proactive_no_response",
    )
```

### 2c: Do NOT emit negative trust for proactive failures

If `handle_intent()` fails or returns no result, do NOT record a negative trust signal. Proactive failures could be caused by LLM timeouts, context issues, or transient errors — penalizing agents for infrastructure problems is unfair. Only successful outcomes generate positive signals. Trust only goes up through proactive activity, never down. The existing user-task and QA pipelines handle negative signals.

## Part 3: Add trust signal to default system.yaml

**File:** `config/system.yaml`

Add the trust weight fields under the existing `proactive_cognitive:` section, after `duty_schedule:`:

```yaml
proactive_cognitive:
  enabled: true
  interval_seconds: 120
  cooldown_seconds: 300
  # AD-414: Trust signal weights
  trust_reward_weight: 0.1
  trust_no_response_weight: 0.0
  trust_duty_bonus: 0.1
  duty_schedule:
    # ... existing duty schedule config
```

**Important:** The trust weight fields go BEFORE `duty_schedule:` in the YAML since `duty_schedule:` is a nested block. Place them right after `cooldown_seconds:`.

## Part 4: Tests

**File:** `tests/test_proactive.py` (add to existing file)

Add a new test class `TestProactiveTrustSignal` with these tests:

### Test 1: `test_successful_think_emits_trust_signal`
- Set up a proactive loop with `trust_reward_weight=0.1`
- Simulate a successful proactive think (mock agent returns a Ward Room post)
- Assert `trust_network.record_outcome()` was called with `success=True, weight=0.1, intent_type="proactive_think"`

### Test 2: `test_duty_completion_adds_bonus`
- Set up with `trust_reward_weight=0.1, trust_duty_bonus=0.1`
- Simulate a successful proactive think WITH a duty (pass duty in params)
- Assert `record_outcome()` was called with `weight=0.2` (0.1 base + 0.1 duty bonus)

### Test 3: `test_no_response_no_trust_signal_by_default`
- Set up with `trust_no_response_weight=0.0` (default)
- Simulate agent returning `[NO_RESPONSE]`
- Assert `record_outcome()` was NOT called

### Test 4: `test_no_response_emits_signal_when_configured`
- Set up with `trust_no_response_weight=0.05`
- Simulate agent returning `[NO_RESPONSE]`
- Assert `record_outcome()` was called with `success=True, weight=0.05, intent_type="proactive_no_response"`

### Test 5: `test_failed_think_no_negative_trust`
- Simulate `handle_intent()` returning `None` or `result.success=False`
- Assert `record_outcome()` was NOT called (no penalty for failures)

### Test 6: `test_trust_update_event_emitted`
- Simulate a successful proactive think
- Assert `event_log.emit("trust_update", ...)` was called with `source="proactive"`

### Test 7: `test_zero_weight_skips_record`
- Set up with `trust_reward_weight=0.0`
- Simulate a successful proactive think
- Assert `record_outcome()` was NOT called (zero weight = disabled)

## Verification

After implementation:
1. Run `uv run pytest tests/test_proactive.py -x -v` — all tests pass (existing + 7 new)
2. Run `uv run pytest tests/test_duty_schedule.py -x -v` — no regressions (13 existing)
3. Run `uv run pytest tests/ -x -q` — full suite clean

## Summary

| Part | File | Change |
|------|------|--------|
| 1 | config.py | 3 new config fields on ProactiveCognitiveConfig |
| 2 | proactive.py | Trust signals after successful think + [NO_RESPONSE] |
| 3 | system.yaml | Default trust weight values |
| 4 | test_proactive.py | 7 new tests in TestProactiveTrustSignal |

**After this AD:** Agents will slowly build trust through proactive participation. An agent posting proactive thoughts every 2 minutes with 50% post rate will earn ~0.3 trust units per hour from base proactive alone (3 posts × 0.1 weight). With duty completion bonuses, scheduled duties contribute 0.2 each. Post-reset, an agent should reach Lieutenant (0.5→0.6) within the first day of operation. Commander (0.7) within a few days. This is intentionally slow — trust is earned, not given.
