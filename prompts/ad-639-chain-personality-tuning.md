# AD-639: Cognitive Chain Personality Tuning

**Priority:** High (cold-start quality — final leg of AD-638/640/639 wave)  
**Depends on:** AD-638 (Boot Camp — complete), AD-640 (Tiered Trust — complete), AD-632 (Sub-Task Protocol — complete)  
**Related:** AD-625 (Communication Discipline Skill), BF-186 (Compose standing orders), BF-189 (Chain memory context)

## Context

The cognitive sub-task chain (Query → Analyze → Compose → Evaluate → Reflect) strips agent personality compared to the one-shot direct chat path. Same agent, same model — Ward Room posts are robotic while profile card DMs feel natural.

**Root cause analysis (codebase-verified):**

| Step | Uses `compose_instructions()`? | Has personality block? | Temperature |
|------|-------------------------------|----------------------|-------------|
| QUERY | N/A (deterministic) | N/A | N/A |
| ANALYZE | Yes (`standing_orders.py:208`) | Yes (full) | 0.0 |
| COMPOSE | Yes (`standing_orders.py:208`) | Yes (full) | 0.3 |
| EVALUATE | **No** — builds raw prompt | **No** — mechanical criteria only | ~0.0 |
| REFLECT | **No** — builds raw prompt | **No** — bare `f"You are {callsign}"` | 0.1 |

EVALUATE scores against mechanical criteria (novelty, opening quality, non-redundancy, relevance) with zero personality awareness. REFLECT self-critiques with bare identity — no Big Five traits, no standing orders, no behavioral style guidance. Together they filter personality out of COMPOSE output.

**Empirical validation:** Wesley at 74% trust produces high-quality, personality-rich Ward Room output through the same chain. The problem is chain + low trust compounding, not the chain alone. AD-640 initialized crew at 0.50 trust — exactly in the zone where evaluate/reflect strip personality without adding quality value.

**Today's evidence (2026-04-17 Science thread):** All Science crew responded to Captain's status request. Output was uniformly clinical: "Systems operational. Ready for tasking." Five agents, five identical bureaucratic status reports. No personality differentiation despite distinct Big Five profiles.

## Design: Trust-Band Adaptive Chain

Three trust bands control chain composition. Follows the `_boot_camp_active` context flag pattern from AD-638.

| Trust Band | Range | Chain Behavior | Rationale |
|-----------|-------|----------------|-----------|
| `low` | < 0.60 | Skip EVALUATE + REFLECT entirely | Personality expression > quality policing at low trust. Let agents find their voice. |
| `mid` | 0.60–0.74 | Full chain, personality-reinforced REFLECT | Quality gates active but with personality preservation. |
| `high` | ≥ 0.75 | Full chain as-is | Proven working (Wesley). No changes. |

**Interaction with boot camp:** Boot camp takes precedence. If `_boot_camp_active` is True, existing AD-638 auto-approve behavior applies regardless of trust band. AD-639 operates after boot camp graduation.

## Implementation

### 1. Add `ChainTuningConfig` to `config.py`

Add after `TieredTrustConfig` (around line 215):

```python
class ChainTuningConfig(BaseModel):
    """AD-639: Trust-adaptive chain personality tuning."""

    enabled: bool = True

    # Trust band thresholds
    low_trust_ceiling: float = 0.60   # Below this: skip evaluate/reflect
    high_trust_floor: float = 0.75    # At or above: full chain as-is
    # Mid band is implicitly [low_trust_ceiling, high_trust_floor)
```

Wire into `SystemConfig`:
```python
chain_tuning: ChainTuningConfig = ChainTuningConfig()
```

### 2. Inject trust band into chain context (`cognitive_agent.py`)

In `_execute_sub_task_chain()`, after the `_boot_camp_active` injection block (~line 1601), add trust band resolution:

```python
# AD-639: Trust-adaptive chain personality tuning
_chain_cfg = getattr(getattr(_rt, 'config', None), 'chain_tuning', None)
if _chain_cfg and _chain_cfg.enabled and not observation.get("_boot_camp_active"):
    _agent_type = getattr(self, "agent_type", "")
    _trust = 0.5
    if _rt and hasattr(_rt, "trust_network") and _rt.trust_network:
        _trust = _rt.trust_network.get_trust(_agent_type)
    observation["_trust_score"] = _trust
    if _trust < _chain_cfg.low_trust_ceiling:
        observation["_chain_trust_band"] = "low"
    elif _trust >= _chain_cfg.high_trust_floor:
        observation["_chain_trust_band"] = "high"
    else:
        observation["_chain_trust_band"] = "mid"
    logger.debug(
        "AD-639: %s trust=%.2f band=%s",
        _agent_type, _trust, observation["_chain_trust_band"],
    )
```

**Pattern follows:** `_boot_camp_active` injection at line 1598–1601 (same guard style, same location).

### 3. Skip EVALUATE + REFLECT at low trust (`evaluate.py`, `reflect.py`)

In `evaluate.py`, in the `execute()` method, after the boot camp check (~line 293) and before the BF-191 JSON rejection check:

```python
# AD-639: Low trust band — skip evaluation, let personality through
if context.get("_chain_trust_band") == "low":
    compose_output = _get_compose_output(prior_results)
    logger.info(
        "AD-639: Evaluate skipped for %s (low trust band, trust=%.2f)",
        context.get("_agent_type", "unknown"),
        context.get("_trust_score", 0.0),
    )
    return SubTaskResult(
        sub_task_type=SubTaskType.EVALUATE,
        name=spec.name,
        result={
            "pass": True,
            "score": 0.0,  # 0.0 signals "not evaluated", not "bad"
            "criteria": {},
            "recommendation": "approve",
            "bypass_reason": "low_trust_band",
        },
        tokens_used=0,
        duration_ms=int((time.monotonic() - start) * 1000),
        success=True,
        tier_used="",
    )
```

In `reflect.py`, in the `execute()` method, same position after boot camp check (~line 312):

```python
# AD-639: Low trust band — skip self-critique, preserve personality
if context.get("_chain_trust_band") == "low":
    compose_output = _get_compose_output(prior_results)
    logger.info(
        "AD-639: Reflect skipped for %s (low trust band, trust=%.2f)",
        context.get("_agent_type", "unknown"),
        context.get("_trust_score", 0.0),
    )
    return SubTaskResult(
        sub_task_type=SubTaskType.REFLECT,
        name=spec.name,
        result={"output": compose_output, "revised": False,
                "reflection": "low_trust_band_bypass"},
        tokens_used=0,
        duration_ms=int((time.monotonic() - start) * 1000),
        success=True,
        tier_used="",
    )
```

**Note:** The BF-191 JSON rejection check in `evaluate.py` MUST still run for low trust. Place the AD-639 bypass AFTER the BF-191 check, not before. Defense in depth — malformed JSON should always be caught regardless of trust band.

**Corrected ordering in `evaluate.py`:**
1. Social obligation bypass (BF-184) — existing
2. Boot camp bypass (AD-638) — existing
3. BF-191 JSON rejection — existing
4. **AD-639 low trust bypass** — NEW (here)
5. LLM evaluation — existing

### 4. Personality-reinforced REFLECT at mid trust (`reflect.py`)

For mid trust band, inject the personality block into REFLECT's system prompt. Currently REFLECT uses a bare `f"You are {callsign} ({department} department)"` identity line (lines 72–73, 127–128, 176–177).

Modify all three reflect prompt builders (`_build_ward_room_reflect_prompt`, `_build_proactive_reflect_prompt`, `_build_general_reflect_prompt`) to inject personality when mid trust:

```python
def _build_ward_room_reflect_prompt(
    context: dict,
    prior_results: list[SubTaskResult],
    callsign: str,
    department: str,
) -> tuple[str, str]:
    """Build prompts for Ward Room post self-critique."""
    skill_instructions = context.get("_augmentation_skill_instructions", "")
    trust_band = context.get("_chain_trust_band", "high")

    # AD-639: Mid trust — inject personality block for voice preservation
    if trust_band == "mid":
        from probos.cognitive.standing_orders import _build_personality_block
        personality_section = _build_personality_block(
            agent_type=context.get("_agent_type", "agent"),
            department=department,
            callsign_override=callsign,
        )
        system_prompt = (
            f"{personality_section}\n\n"
            "You are reviewing your own draft Ward Room response.\n\n"
            "**IMPORTANT: Preserve your personality and voice when revising.** "
            "Revisions should improve substance, not flatten personality. "
            "If the draft sounds like you, keep that voice.\n\n"
            "Check the draft against these criteria:\n"
            "- **Novelty**: At least one new fact, metric, or conclusion?\n"
            "- **Opening quality**: First sentence states a conclusion? "
            "No 'Looking at...', 'I notice...', 'I can confirm...' openers.\n"
            "- **Non-redundancy**: More than confirming what someone said?\n"
            "- **Relevance**: Addresses the topic from your perspective?\n"
            "- **Voice consistency**: Does the revision preserve your personality?\n\n"
        )
    else:
        system_prompt = (
            f"You are {callsign} ({department} department), reviewing your own "
            "draft Ward Room response for quality.\n\n"
            "Check the draft against these criteria:\n"
            "- **Novelty**: Does it contain at least one new fact, metric, or "
            "conclusion not in the thread?\n"
            "- **Opening quality**: Does the first sentence state a conclusion? "
            "No 'Looking at...', 'I notice...', 'I can confirm...' openers.\n"
            "- **Non-redundancy**: Is this more than confirming what someone said?\n"
            "- **Relevance**: Does it address the topic from your department's "
            "perspective?\n\n"
        )
    # ... rest of method unchanged (skill instructions, JSON format, user prompt)
```

Apply the same pattern to `_build_proactive_reflect_prompt` and `_build_general_reflect_prompt`.

**Key additions for mid-trust REFLECT:**
- Full personality block from `_build_personality_block()` (cached via `@lru_cache`)
- Explicit instruction: "Preserve your personality and voice when revising"
- New criterion: "Voice consistency" — does the revision preserve personality?
- Framing shift: "reviewing your own draft" not "reviewing for quality"

### 5. Personality-aware EVALUATE at mid trust (`evaluate.py`)

For mid trust band, add a personality consistency criterion to the evaluation prompt. Modify `_build_ward_room_evaluate_prompt` (and the other two mode builders):

In the ward_room_quality system prompt (~line 58–77), when trust band is "mid", append an additional criterion:

```python
def _build_ward_room_evaluate_prompt(
    context: dict,
    prior_results: list[SubTaskResult],
    callsign: str,
    department: str,
) -> tuple[str, str]:
    trust_band = context.get("_chain_trust_band", "high")

    criteria = (
        "1. **Novelty** — Contains at least one fact, metric, or conclusion "
        "not already in the thread\n"
        "2. **Opening** — First sentence states a conclusion or fact "
        "(no 'Looking at...', 'I notice...' openers)\n"
        "3. **Non-redundancy** — Adds value beyond confirming what others said\n"
        "4. **Relevance** — Addresses the topic from departmental perspective\n"
    )

    # AD-639: Mid trust — add personality preservation criterion
    if trust_band == "mid":
        criteria += (
            "5. **Voice** — Response has a distinct voice consistent with the "
            "agent's personality, not generic or clinical\n"
        )

    system_prompt = (
        f"You are evaluating a draft Ward Room response by {callsign} "
        f"({department} department).\n\n"
        f"Score the draft against these criteria:\n{criteria}\n"
        'Respond with JSON only:\n'
        '{"pass": true/false, "score": 0.0-1.0, "criteria": '
        '{"novelty": true/false, "opening": true/false, '
        '"non_redundancy": true/false, "relevance": true/false'
    )
    if trust_band == "mid":
        system_prompt += ', "voice": true/false'
    system_prompt += (
        '}, "recommendation": "approve"/"revise"/"suppress"}'
    )

    # ... user prompt construction unchanged
```

Apply the same pattern to `_build_proactive_evaluate_prompt`.

### 6. No changes needed

- **COMPOSE** — Already has full personality via `compose_instructions()`. No changes.
- **ANALYZE** — Already has full personality via `compose_instructions()`. No changes.
- **QUERY** — Deterministic data retrieval. No changes.
- **`_build_chain_for_intent()`** — Chain structure stays the same (all 5 steps always present). Trust-based skipping happens at execution time in each handler, not at chain build time. This is more resilient — chain structure is static, behavior is dynamic.

## Files Modified

| File | Change | Lines |
|------|--------|-------|
| `src/probos/config.py` | Add `ChainTuningConfig` + wire to `SystemConfig` | ~215, ~300 |
| `src/probos/cognitive/cognitive_agent.py` | Trust band injection in `_execute_sub_task_chain()` | ~1602 |
| `src/probos/cognitive/sub_tasks/evaluate.py` | Low trust bypass + mid trust voice criterion | ~294, ~58 |
| `src/probos/cognitive/sub_tasks/reflect.py` | Low trust bypass + mid trust personality injection | ~313, ~63 |

**No new files.** 4 modified files.

## Engineering Principles Compliance

- **SOLID (S)**: `ChainTuningConfig` is single-responsibility — only trust band thresholds. Trust band resolution is a single block in one location.
- **SOLID (O)**: Extended chain behavior through context flags, not modified core chain logic. `_build_chain_for_intent()` unchanged.
- **DRY**: Reuses `_build_personality_block()` from `standing_orders.py` (already cached via `@lru_cache`). Reuses trust lookup pattern from AD-537 (line 968–969).
- **Fail Fast / Log-and-Degrade**: If trust network unavailable, defaults to 0.5 (mid band) — safe degradation. If config missing, feature is simply inactive.
- **Defense in Depth**: BF-191 JSON rejection runs before AD-639 bypass. Social obligation bypass (BF-184) runs before AD-639. Boot camp (AD-638) takes precedence over trust band.
- **Law of Demeter**: Trust accessed via `_rt.trust_network.get_trust()` — existing public API, no private member patching.

## Tests

Target: **35–45 tests** across 2 test files.

### `tests/unit/cognitive/sub_tasks/test_ad639_chain_tuning.py`

**Config tests (3):**
- `ChainTuningConfig` defaults match spec (0.60, 0.75)
- Config wired into SystemConfig
- Feature disabled when `enabled=False`

**Trust band resolution tests (5):**
- Trust 0.40 → band "low"
- Trust 0.59 → band "low" (boundary)
- Trust 0.60 → band "mid" (boundary)
- Trust 0.74 → band "mid"
- Trust 0.75 → band "high" (boundary)
- Trust 0.90 → band "high"
- Boot camp active → no trust band injected (precedence)
- Trust network unavailable → defaults to 0.5 (mid band)

**Evaluate handler tests (8):**
- Low trust → bypass, 0 tokens, `bypass_reason="low_trust_band"`
- Mid trust → LLM called, voice criterion present in prompt
- High trust → LLM called, no voice criterion (unchanged behavior)
- Boot camp + low trust → boot camp takes precedence
- Social obligation + low trust → social obligation takes precedence
- BF-191 JSON rejection + low trust → JSON rejection still fires first
- Low trust bypass score is 0.0 (not 0.8 like boot camp)
- Disabled config → standard evaluation (no bypass)

**Reflect handler tests (8):**
- Low trust → bypass, 0 tokens, returns compose output unchanged
- Mid trust ward_room → personality block in system prompt
- Mid trust ward_room → "Voice consistency" criterion present
- Mid trust ward_room → "Preserve your personality" instruction present
- Mid trust proactive → personality block in system prompt
- High trust → unchanged behavior (bare identity prompt)
- Boot camp + low trust → boot camp takes precedence
- Disabled config → standard reflection (no bypass)

**Integration tests (5):**
- Full ward_room chain at low trust: QUERY→ANALYZE→COMPOSE→(EVALUATE skip)→(REFLECT skip)
- Full ward_room chain at mid trust: all steps execute, personality in REFLECT prompt
- Full ward_room chain at high trust: all steps execute, unchanged prompts
- Token savings at low trust: EVALUATE + REFLECT = 0 tokens
- Trust band logged correctly in debug output

### Existing test verification

Run existing sub-task chain tests to confirm no regression:
- `tests/unit/cognitive/sub_tasks/test_evaluate.py`
- `tests/unit/cognitive/sub_tasks/test_reflect.py`
- `tests/unit/cognitive/sub_tasks/test_compose.py`
- `tests/unit/cognitive/test_sub_task_chain.py`

## Verification

After implementation:

1. `pytest tests/unit/cognitive/sub_tasks/test_ad639_chain_tuning.py -v` — all new tests pass
2. `pytest tests/unit/cognitive/sub_tasks/ -v` — no regressions in existing chain tests
3. `pytest -x -n auto` — full suite green

## Rollback

Set `chain_tuning.enabled = False` in config to disable entirely. All chain behavior reverts to pre-AD-639 (full evaluate/reflect for all trust levels).

## Deferred

- **Temperature tuning for REFLECT** — currently 0.1 (very deterministic). Could raise to 0.2 for mid trust to allow more personality expression. Deferred: measure first.
- **Communication skill modulation** — `_augmentation_skill_instructions` may over-constrain personality at low trust. Could skip skill injection below threshold. Deferred: separate concern (AD-625 follow-up or AD-642).
- **EVALUATE personality-aware scoring weights** — voice criterion counts equally with novelty/opening/etc. Could weight it higher for mid trust. Deferred: measure first.
- **Personality drift tracking** — Counselor could monitor whether chain tuning changes personality expression over time. Connects to `CrewProfile.distance_from(baseline)`. Deferred: AD-639b.
