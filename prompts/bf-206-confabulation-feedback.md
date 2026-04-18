# BF-206: Enforce Evaluate Suppress + Confabulation Feedback Loop

## Overview

Fix the broken suppress enforcement in the cognitive chain and add a reinforcement learning feedback loop so agents learn from confabulation. Currently, BF-204's grounding check detects fabricated content and returns `recommendation: "suppress"`, but the suppress is never enforced for low-trust agents. The agent posts fabricated content without knowing it confabulated.

## Root Cause

The chain spec defines Evaluate and Reflect with `depends_on=("compose-reply",)` — both depend only on Compose, not on each other. The `SubTaskExecutor` at `sub_task.py:378` detects them as independent and runs them **in parallel** via `asyncio.gather()`. Reflect's `_should_suppress()` at `reflect.py:51` checks for Evaluate's result in `prior_results`, but because they run concurrently, Evaluate's result isn't in the snapshot yet.

For mid/high trust bands this is masked — Reflect's LLM call takes longer, and by the time it finishes, the suppress would typically be visible in a sequential flow. But for low-trust agents, AD-639 skips Reflect entirely (line 421), so even if Evaluate returned suppress, there's no downstream check.

**The fix has two parts:**
1. Make Reflect depend on Evaluate so suppress is enforced at all trust bands
2. Add confabulation feedback (event, Counselor DM, trust impact)

## Part 1: Fix Chain Dependency

### Change Reflect `depends_on` to include Evaluate

In `cognitive_agent.py`, both ward_room_notification (line 1516) and proactive_think (line 1552) chain specs have:

```python
SubTaskSpec(
    sub_task_type=SubTaskType.REFLECT,
    name="reflect-reply",  # or "reflect-observation"
    prompt_template="ward_room_reflection",  # or "proactive_reflection"
    required=False,
    depends_on=("compose-reply",),  # ← BUG: Missing evaluate dependency
)
```

Change to:

```python
depends_on=("compose-reply", "evaluate-reply"),  # or "evaluate-observation" for proactive
```

This makes Reflect wait for Evaluate to complete. The executor will run Query → Analyze → Compose sequentially, then Evaluate sequentially, then Reflect sequentially. No parallelism loss — Evaluate and Reflect were never meaningfully parallel (Reflect needs Evaluate's verdict).

### Add suppress check in `_execute_sub_task_chain()`

Even with the dependency fix, add a defense-in-depth check in `_execute_sub_task_chain()` at `cognitive_agent.py:1662`. Before extracting compose/reflect output, check if any Evaluate result recommended suppress:

```python
# BF-206: Defense-in-depth — check Evaluate suppress before extracting output
from probos.cognitive.sub_task import SubTaskType
evaluate_results = [
    r for r in results
    if r.sub_task_type == SubTaskType.EVALUATE and r.success and r.result
]
for eval_r in evaluate_results:
    if eval_r.result.get("recommendation") == "suppress":
        rejection = eval_r.result.get("rejection_reason", "quality_gate")
        logger.info(
            "BF-206: Chain output suppressed — Evaluate recommended suppress (%s)",
            rejection,
        )
        return {
            "action": "execute",
            "llm_output": "[NO_RESPONSE]",
            "tier_used": "",
            "sub_task_chain": True,
            "chain_source": chain.source,
            "chain_steps": len(chain.steps),
            "_suppressed": True,
            "_suppression_reason": rejection,
        }
```

Insert this BEFORE the existing result extraction at line 1662 ("Construct decision from chain results").

## Part 2: Confabulation Feedback

### New Event: `CONFABULATION_SUPPRESSED`

Add to `events.py` after `CONTENT_QUARANTINE_RECOMMENDED` (line 148):

```python
CONFABULATION_SUPPRESSED = "confabulation_suppressed"  # BF-206
```

### Emit Event from `_execute_sub_task_chain()`

When suppress is enforced (the new code from Part 1), emit an event if `_emit_event` is available:

```python
# BF-206: Emit confabulation suppressed event
_rt = getattr(self, '_runtime', None)
if _rt and hasattr(_rt, '_emit_event') and _rt._emit_event:
    from probos.events import EventType
    _rt._emit_event(EventType.CONFABULATION_SUPPRESSED, {
        "agent_id": self.id,
        "agent_type": self.agent_type,
        "callsign": getattr(self, 'callsign', self.agent_type),
        "rejection_reason": rejection,
        "intent": observation.get("intent", ""),
        "trust_score": observation.get("_trust_score", 0.5),
        "chain_trust_band": observation.get("_chain_trust_band", "unknown"),
    })
```

Note: `observation` is available in scope — it's the parameter to `_execute_sub_task_chain()`.

### Counselor Handler: `_on_confabulation_suppressed()`

Add event routing in `_on_event_async()` at `counselor.py:815`, after the existing `CASCADE_CONFABULATION_DETECTED` handler:

```python
elif event_type == EventType.CONFABULATION_SUPPRESSED.value:
    await self._on_confabulation_suppressed(data)
```

New handler method, following the `_on_cascade_confabulation()` pattern at `counselor.py:1261`:

```python
async def _on_confabulation_suppressed(self, data: dict[str, Any]) -> None:
    """BF-206: Handle confabulation suppression events.

    First offense in window: warning DM only (no trust penalty).
    Repeat offenses: trust penalty + DM.
    """
    agent_id = data.get("agent_id", "")
    callsign = data.get("callsign", "")
    rejection_reason = data.get("rejection_reason", "")
    trust_score = data.get("trust_score", 0.5)

    logger.info(
        "BF-206: Confabulation suppressed for %s (reason=%s, trust=%.2f)",
        callsign, rejection_reason, trust_score,
    )

    # Track confabulation count in cognitive profile
    profile = await self._get_or_create_profile(agent_id)
    # Increment confabulation count
    profile.confabulation_count = getattr(profile, 'confabulation_count', 0) + 1

    # Graduated response: check recent confabulation history
    # Use existing _dm_cooldowns pattern for windowed counting
    _confab_key = f"confab:{agent_id}"
    now = __import__('time').time()
    if not hasattr(self, '_confab_history'):
        self._confab_history: dict[str, list[float]] = {}
    history = self._confab_history.setdefault(agent_id, [])
    history.append(now)
    # Prune outside 1h window
    cutoff = now - 3600.0
    self._confab_history[agent_id] = [t for t in history if t > cutoff]
    count = len(self._confab_history[agent_id])

    # Trust penalty on repeat offenses (2+ in window)
    if count >= 2 and hasattr(self, '_trust_network') and self._trust_network:
        self._trust_network.record_outcome(
            agent_id=agent_id,
            success=False,
            weight=0.5,  # Half weight — confabulation at low trust is expected
            intent_type="confabulation_suppressed",
            source="confabulation",
        )
        logger.info(
            "BF-206: Trust penalty for %s — %d confabulations in window",
            callsign, count,
        )

    # Always send therapeutic DM (rate-limited by existing _send_therapeutic_dm)
    if count == 1:
        message = (
            "I noticed your recent response was held back because it contained "
            "details that couldn't be verified against available context. This is "
            "completely normal during early development — try grounding your "
            "observations in what you can directly observe rather than inferring "
            "specific identifiers or metrics."
        )
    else:
        message = (
            f"I've noticed this is the {count}{'nd' if count == 2 else 'rd' if count == 3 else 'th'} "
            "time your response contained unverifiable details within the past hour. "
            "I'd encourage you to focus on what you can directly observe — the crew "
            "benefits most from grounded analysis. Your trust rating has been adjusted "
            "to reflect this pattern."
        )

    await self._send_therapeutic_dm(agent_id, callsign, message)
    await self._save_profile(agent_id, profile)
```

### Trust Recovery

No special mechanism needed. Clean Ward Room posts already flow through the trust system:
- Endorsements record `success=True` with `weight=0.05` (`ward_room_router.py:1010`)
- Proactive duty completion records `success=True` with duty bonus (`proactive.py:793`)
- The trust system's Bayesian update (alpha/beta) naturally recovers with positive outcomes

The `weight=0.5` penalty for confabulation is moderate — 10 successful endorsements (10 × 0.05 = 0.5 weight) or 5 duty completions will offset it. This makes recovery achievable but not trivial.

## Files

- **Modify:** `src/probos/cognitive/cognitive_agent.py` — Fix Reflect `depends_on` in both chain specs (ward_room + proactive), add suppress check in `_execute_sub_task_chain()`
- **Modify:** `src/probos/events.py` — Add `CONFABULATION_SUPPRESSED` event type
- **Modify:** `src/probos/cognitive/counselor.py` — Add event routing + `_on_confabulation_suppressed()` handler
- **New:** `tests/test_bf206_confab_feedback.py` — All tests

## Tests (20+)

### Chain Suppress Enforcement (6 tests)
1. Reflect `depends_on` includes evaluate step name (ward_room chain)
2. Reflect `depends_on` includes evaluate step name (proactive chain)
3. `_execute_sub_task_chain()` returns `[NO_RESPONSE]` when Evaluate recommends suppress
4. `_execute_sub_task_chain()` returns compose output when Evaluate recommends approve
5. `_execute_sub_task_chain()` returns compose output when Evaluate has no recommendation (skipped)
6. `_suppressed` and `_suppression_reason` set in decision dict on suppress

### Event Emission (4 tests)
7. `CONFABULATION_SUPPRESSED` event emitted when suppress enforced
8. Event data includes agent_id, callsign, rejection_reason, trust_score, chain_trust_band
9. No event emitted when Evaluate approves
10. No event emitted when Evaluate is skipped (no recommendation)

### Counselor Feedback (6 tests)
11. Counselor routes `CONFABULATION_SUPPRESSED` to `_on_confabulation_suppressed()`
12. First offense in window → therapeutic DM sent (warning tone)
13. Second offense in window → therapeutic DM sent (escalated tone) + trust penalty
14. Trust penalty uses `weight=0.5` and `source="confabulation"`
15. Offenses outside 1h window don't count toward repeat threshold
16. `confabulation_count` incremented in cognitive profile

### Integration (4 tests)
17. BF-204 grounding check → suppress → `[NO_RESPONSE]` → post not created (full chain)
18. BF-204 grounding check → suppress → event emitted → Counselor DM sent (full flow)
19. Low-trust agent confabulation: Evaluate catches, chain returns `[NO_RESPONSE]` (the original bug scenario)
20. Mid-trust agent confabulation: Evaluate catches, Reflect honors suppress, chain returns `[NO_RESPONSE]` (existing path still works)

## Prior Art to Preserve

- **BF-204:** Grounding criterion in Evaluate (`evaluate.py:316`). BF-206 enforces its suppress recommendation. BF-204's deterministic hex ID check is unchanged.
- **AD-639:** Trust-band adaptive chain (`cognitive_agent.py:1604`). Low trust skips Evaluate LLM (but BF-204 deterministic check still runs at line 316 — "Runs at ALL trust bands"). Low trust skips Reflect (line 421), but dependency fix means Reflect now waits for Evaluate.
- **BF-191:** Raw JSON rejection in Evaluate (`evaluate.py:300`). Also returns suppress — BF-206's chain-level check catches this too.
- **BF-184/185/187:** Social obligation bypasses in Evaluate and Reflect. Safety suppress (BF-204) already runs BEFORE obligation in both handlers. BF-206's chain-level check is an additional defense.
- **AD-567f:** Cascade confabulation detection (`social_verification.py:280`). Post-hoc multi-agent detection. BF-206 is per-agent pre-posting detection. Different layers of defense.
- **AD-529:** Content contagion firewall (`content_firewall.py`). Posting boundary scan. BF-206 is chain-internal enforcement. AD-529 catches what BF-206 misses (e.g., content that passes BF-204's deterministic check but contains other fabrication signals). Complementary layers.
- **AD-558:** Trust cascade dampening (`trust.py:224`). `record_outcome()` uses existing dampening — BF-206's trust penalty naturally benefits from progressive dampening protection.
- **AD-640:** Tiered trust initialization. Cold-start agents at 0.50 trust are expected to confabulate. Graduated response (warning first) is cold-start safe.
- **AD-638:** Boot camp. Boot camp agents are enrolled but still run through the chain. Confabulation feedback during boot camp is valuable — it's part of learning.
- **Counselor DM pattern:** `_send_therapeutic_dm()` at `counselor.py:1839`. Rate-limited. BF-206 reuses this exact pattern.
- **Counselor event routing:** `_on_event_async()` at `counselor.py:784`. New `elif` branch for `CONFABULATION_SUPPRESSED`. Open/Closed principle.

## Prior Art to NOT Duplicate

- **AD-506b (Peer Repetition Detection):** Different concern — self-repetition vs confabulation.
- **AD-583f (Observable State Verification):** Post-hoc claim verification vs pre-posting suppress.
- **Circuit Breaker (AD-506a):** Velocity/similarity-based agent throttling. Different mechanism — BF-206 is content-specific, not activity-rate-based.

## Engineering Principles

- **Single Responsibility:** Chain spec fixes the dependency. `_execute_sub_task_chain()` enforces suppress. Counselor provides feedback. Each has one job.
- **Open/Closed:** New `elif` branch in Counselor event routing. No rewriting existing handlers. New event type extends enum.
- **Defense in Depth:** Four layers now all connected: (1) AD-592 instructions in compose, (2) BF-204 grounding in evaluate, (3) BF-206 enforce suppress in chain extraction, (4) AD-529 firewall at posting boundary, (5) AD-567f cascade detection post-hoc.
- **Fail Fast:** If event emission fails, suppress still enforced (log-and-degrade). If Counselor DM fails, trust penalty still recorded. Each component degrades independently.
- **DRY:** Reuses `_send_therapeutic_dm()`, `record_outcome()`, `_on_event_async()` routing pattern. No new infrastructure.
- **Interface Segregation:** Counselor accesses `_trust_network.record_outcome()` — narrow interface, not full trust API.
- **Dependency Inversion:** Event-based decoupling — chain emits event, Counselor subscribes. No direct import.
- **Law of Demeter:** Chain uses `self._runtime._emit_event` — existing pattern used throughout codebase (e.g., `content_firewall.py`). No new private member access.
- **Westworld Principle:** Agent is told WHY their post was suppressed. Therapeutic DM explains the reason. No silent failure.
