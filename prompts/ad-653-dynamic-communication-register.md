# AD-653: Dynamic Communication Register — "Speak Freely" Protocol

**Status:** Ready for builder
**Depends on:** AD-649 (communication context), AD-651a (billet instructions), AD-632c/d (ANALYZE/COMPOSE chain), AD-504 (self-monitoring)
**Research:** `docs/research/dynamic-communication-register-research.md`

---

## Overview

Agents can currently detect communication context (AD-649: private, bridge, casual, department, ship-wide) and receive context-appropriate framing in COMPOSE. But the register is **top-down only** — the system assigns it, the agent follows it.

AD-653 adds **agent-initiated register shifting**: when ANALYZE detects that the assigned register constrains important output, the agent can request "speak freely" — a temporary, trust-gated override that relaxes format constraints for one compose invocation.

This is **first-of-kind** — no existing multi-agent framework gives agents self-awareness of their communicative constraints or a protocol for escaping them. See research doc for full gap analysis.

---

## Scope

This AD implements Layer 1 only (the "speak freely" protocol). Layers 2 (character-driven register defaults via Big Five) and 3 (pattern analysis / billet fitness) from the research doc are **deferred** — they depend on observing Layer 1 usage patterns first.

**In scope:**
1. Register-constraint detection prompt in ANALYZE (all 3 modes)
2. Trust-gated authorization in COMPOSE (Python, not LLM)
3. "Speak freely" framing injection in COMPOSE (billet instruction pattern)
4. Event emission for observability
5. Counselor subscription for flagged shifts
6. Tests

**Out of scope:**
- Register taxonomy enum/config (premature — start with the protocol, taxonomy later)
- Big Five → default register mapping (Layer 2)
- Shift frequency analytics (Layer 3)
- Modulation Pattern Templates from research §4.2 (premature abstraction)

---

## Implementation

### 1. Event Types — `src/probos/events.py`

Add two new event types after `CONFABULATION_SUPPRESSED` (line ~149):

```python
# Communication register
REGISTER_SHIFT_GRANTED = "register_shift_granted"    # AD-653
REGISTER_SHIFT_DENIED = "register_shift_denied"      # AD-653
```

### 2. ANALYZE Prompt — Register-Constraint Detection

**File:** `src/probos/cognitive/sub_tasks/analyze.py`

#### 2a. Thread Analysis (`_build_thread_analysis_prompt`, line ~170)

After the existing `intended_actions` field (item 6), add a new field 8 (renumber "composition_brief" from 7 to 8 is NOT needed — just add as a new item 8 after the composition_brief):

Actually — simpler approach that doesn't require renumbering: **extend the `intended_actions` instruction** to include `speak_freely` as an option, and add a separate self-assessment field.

In the `_build_thread_analysis_prompt` function, modify the `intended_actions` instruction (currently at lines 170-174). Replace:

```python
f"6. **intended_actions**: Based on your contribution_assessment, what\n"
f"   specific actions will you take? List as a JSON array from:\n"
f"   ward_room_reply, endorse, silent.\n"
f"   If RESPOND: [\"ward_room_reply\"]. If ENDORSE: [\"endorse\"].\n"
f"   If both: [\"ward_room_reply\", \"endorse\"]. If SILENT: [\"silent\"].\n"
```

With:

```python
f"6. **intended_actions**: Based on your contribution_assessment, what\n"
f"   specific actions will you take? List as a JSON array from:\n"
f"   ward_room_reply, endorse, silent, speak_freely.\n"
f"   If RESPOND: [\"ward_room_reply\"]. If ENDORSE: [\"endorse\"].\n"
f"   If both: [\"ward_room_reply\", \"endorse\"]. If SILENT: [\"silent\"].\n"
f"   Add \"speak_freely\" if you have something important to communicate\n"
f"   that the expected format would constrain or dilute — a candid\n"
f"   assessment, a concern that formal structure would flatten, or a\n"
f"   personal insight that matters more than protocol compliance.\n"
f"   speak_freely is additive: [\"ward_room_reply\", \"speak_freely\"].\n"
```

#### 2b. Situation Review (`_build_situation_review_prompt`, line ~364)

Same modification. In the `intended_actions` instruction, replace:

```python
"5. **intended_actions**: What actions will you take? List as a JSON array from:\n"
"   ward_room_post, ward_room_reply, endorse, notebook, leadership_review,\n"
"   proposal, dm, silent. Include ALL that apply.\n"
"   Examples: [\"ward_room_post\", \"notebook\"], [\"endorse\"], [\"silent\"]\n"
```

With:

```python
"5. **intended_actions**: What actions will you take? List as a JSON array from:\n"
"   ward_room_post, ward_room_reply, endorse, notebook, leadership_review,\n"
"   proposal, dm, silent, speak_freely. Include ALL that apply.\n"
"   Examples: [\"ward_room_post\", \"notebook\"], [\"endorse\"], [\"silent\"]\n"
"   Add \"speak_freely\" if you have something important to communicate\n"
"   that the expected format would constrain or dilute — a candid\n"
"   assessment, a concern that formal structure would flatten, or a\n"
"   personal insight that matters more than protocol compliance.\n"
"   speak_freely is additive: [\"ward_room_post\", \"speak_freely\"].\n"
```

#### 2c. DM Comprehension (`_build_dm_comprehension_prompt`)

**No change needed.** DMs are already `private_conversation` register — they already get warm/conversational framing. "Speak freely" is for escaping formality, and DMs aren't formal.

### 3. COMPOSE Handler — Trust-Gated Authorization + Framing Injection

**File:** `src/probos/cognitive/sub_tasks/compose.py`

#### 3a. Add trust-gated speak_freely check

In `_build_proactive_compose_prompt` (lines 186-266), **after** the existing AD-651a proposal check (line ~254), add the speak_freely billet instruction:

```python
    # AD-653: "Speak freely" — trust-gated register override
    if isinstance(intended, list) and "speak_freely" in intended:
        _trust = context.get("_trust_score", 0.5)
        _emit = context.get("_emit_event_fn")
        _agent_id = context.get("_agent_id", "")
        _comm_context = context.get("_communication_context", "department_discussion")

        if _trust >= 0.7:
            # Auto-granted — high trust agents can speak freely
            system_prompt += (
                "\n\n**SPEAK FREELY — GRANTED.** You flagged that formal register "
                "would constrain something important. For this response only, drop "
                "format requirements and speak in your natural voice. Be direct, "
                "candid, and honest. Say what you actually think, not what protocol "
                "demands. This is temporary — your next response returns to normal "
                "register."
            )
            if _emit:
                _emit(EventType.REGISTER_SHIFT_GRANTED, {
                    "agent_id": _agent_id,
                    "trust": _trust,
                    "from_register": _comm_context,
                    "to_register": "speak_freely",
                    "authorization": "auto",
                })
        elif _trust >= 0.4:
            # Granted but flagged to Counselor
            system_prompt += (
                "\n\n**SPEAK FREELY — GRANTED (flagged for review).** You flagged "
                "that formal register would constrain something important. For this "
                "response only, drop format requirements and speak candidly. This "
                "shift has been noted for Counselor review."
            )
            if _emit:
                _emit(EventType.REGISTER_SHIFT_GRANTED, {
                    "agent_id": _agent_id,
                    "trust": _trust,
                    "from_register": _comm_context,
                    "to_register": "speak_freely",
                    "authorization": "flagged",
                })
        else:
            # Denied — low trust agents stay in assigned register
            if _emit:
                _emit(EventType.REGISTER_SHIFT_DENIED, {
                    "agent_id": _agent_id,
                    "trust": _trust,
                    "from_register": _comm_context,
                    "reason": "trust_below_threshold",
                })
            # No prompt modification — agent composes in assigned register
```

**IMPORTANT:** This requires `EventType` import at the top of `compose.py`:

```python
from probos.events import EventType
```

#### 3b. Same pattern in `_build_ward_room_compose_prompt`

After the skill injection (line ~136), before returning, add the same speak_freely check. Extract the intended_actions the same way:

```python
    # AD-653: "Speak freely" — trust-gated register override for thread responses
    analysis = _get_analysis_result(prior_results)
    intended = analysis.get("intended_actions", [])
    if isinstance(intended, list) and "speak_freely" in intended:
        _trust = context.get("_trust_score", 0.5)
        _emit = context.get("_emit_event_fn")
        _agent_id = context.get("_agent_id", "")

        if _trust >= 0.7:
            system_prompt += (
                "\n\n**SPEAK FREELY — GRANTED.** You flagged that the current "
                "register would constrain something important. For this response "
                "only, be direct and candid. Say what you actually think."
            )
            if _emit:
                _emit(EventType.REGISTER_SHIFT_GRANTED, {
                    "agent_id": _agent_id,
                    "trust": _trust,
                    "from_register": context.get("_communication_context", "department_discussion"),
                    "to_register": "speak_freely",
                    "authorization": "auto",
                })
        elif _trust >= 0.4:
            system_prompt += (
                "\n\n**SPEAK FREELY — GRANTED (flagged for review).** For this "
                "response only, be direct and candid. This shift has been noted "
                "for Counselor review."
            )
            if _emit:
                _emit(EventType.REGISTER_SHIFT_GRANTED, {
                    "agent_id": _agent_id,
                    "trust": _trust,
                    "from_register": context.get("_communication_context", "department_discussion"),
                    "to_register": "speak_freely",
                    "authorization": "flagged",
                })
        else:
            if _emit:
                _emit(EventType.REGISTER_SHIFT_DENIED, {
                    "agent_id": _agent_id,
                    "trust": _trust,
                    "from_register": context.get("_communication_context", "department_discussion"),
                    "reason": "trust_below_threshold",
                })
```

**DRY consideration:** The speak_freely logic repeats across two compose builders. This is acceptable for now — extracting a helper is premature until we see if the pattern stabilizes. If Layer 2 adds more register types, extract then.

#### 3c. Wire `_emit_event_fn` and `_agent_id` into context

**File:** `src/probos/cognitive/cognitive_agent.py`

In the `_build_observation_context` for ward_room_notification (around line 1860, after `_trust_score` injection), add:

```python
observation["_emit_event_fn"] = getattr(_rt, '_emit_event', None) if _rt else None
observation["_agent_id"] = getattr(self, 'id', '') or getattr(self, 'agent_type', '')
```

**Also** in the proactive_think observation builder (similar location — search for the proactive equivalent of `_trust_score` injection). The proactive path is in `_build_proactive_observation` or the method that builds context for proactive_think. Find where `_trust_score` is set for proactive observations and add the same two lines.

**Verification step for builder:** `grep -n "_trust_score" src/probos/cognitive/cognitive_agent.py` to find both injection points (ward_room_notification and proactive_think paths).

### 4. Counselor Subscription

**File:** `src/probos/cognitive/counselor.py`

#### 4a. Add event types to subscription list

In the `_add_event_listener_fn` call (lines 581-605), add after `CONFABULATION_SUPPRESSED`:

```python
EventType.REGISTER_SHIFT_GRANTED,   # AD-653
EventType.REGISTER_SHIFT_DENIED,    # AD-653
```

#### 4b. Add dispatcher routing

In `_on_event_async()` dispatcher (lines 785-833), add a case for the new event types. Find the pattern — it's a series of `if event_type == EventType.X:` checks. Add:

```python
if event_type in (EventType.REGISTER_SHIFT_GRANTED, EventType.REGISTER_SHIFT_DENIED):
    await self._on_register_shift(event_data)
    return
```

#### 4c. Add handler method

Add a new method to `CounselorAgent`:

```python
async def _on_register_shift(self, event_data: dict) -> None:
    """AD-653: Log and optionally review register shift events."""
    agent_id = event_data.get("agent_id", "")
    trust = event_data.get("trust", 0.0)
    authorization = event_data.get("authorization", "")
    from_reg = event_data.get("from_register", "")
    to_reg = event_data.get("to_register", "")
    reason = event_data.get("reason", "")

    if authorization == "flagged":
        logger.info(
            "AD-653: Register shift FLAGGED — %s (trust=%.2f) %s→%s",
            agent_id, trust, from_reg, to_reg,
        )
        # Counselor notes the shift for wellness monitoring.
        # Future: could trigger a wellness check if frequency is high.
    elif reason:
        logger.info(
            "AD-653: Register shift DENIED — %s (trust=%.2f) reason=%s",
            agent_id, trust, reason,
        )
    else:
        logger.debug(
            "AD-653: Register shift granted — %s (trust=%.2f) %s→%s",
            agent_id, trust, from_reg, to_reg,
        )
```

Keep the handler simple. Pattern analysis (Layer 3) is deferred.

### 5. Short-Circuit Guard

**File:** `src/probos/cognitive/sub_tasks/compose.py`

In `_should_short_circuit` (lines 32-50), `speak_freely` should NOT trigger short-circuit. The current logic checks `if actions == ["silent"]` — since `speak_freely` is always combined with another action (e.g., `["ward_room_reply", "speak_freely"]`), it won't match `["silent"]`. **No change needed** — existing logic is correct.

Verify: `speak_freely` is always additive (never appears alone), so the short-circuit guard naturally excludes it. The ANALYZE prompt instruction says "speak_freely is additive" to enforce this.

---

## Testing

**File:** `tests/test_ad653_dynamic_register.py`

### Test Categories

#### 1. ANALYZE Prompt Integration (3 tests)

```
test_thread_analysis_prompt_includes_speak_freely_option
  - Call _build_thread_analysis_prompt with mock context
  - Assert "speak_freely" appears in the user_prompt intended_actions instruction

test_situation_review_prompt_includes_speak_freely_option
  - Call _build_situation_review_prompt with mock context
  - Assert "speak_freely" appears in the user_prompt intended_actions instruction

test_dm_comprehension_prompt_does_not_include_speak_freely
  - Call _build_dm_comprehension_prompt with mock context
  - Assert "speak_freely" does NOT appear in the user_prompt
```

#### 2. Trust-Gated Authorization (6 tests)

```
test_speak_freely_auto_granted_high_trust
  - context with _trust_score=0.85, prior ANALYZE result with intended_actions=["ward_room_post", "speak_freely"]
  - Call _build_proactive_compose_prompt
  - Assert "SPEAK FREELY — GRANTED" in system_prompt
  - Assert EventType.REGISTER_SHIFT_GRANTED emitted with authorization="auto"

test_speak_freely_flagged_mid_trust
  - context with _trust_score=0.55
  - Assert "SPEAK FREELY — GRANTED (flagged for review)" in system_prompt
  - Assert EventType.REGISTER_SHIFT_GRANTED emitted with authorization="flagged"

test_speak_freely_denied_low_trust
  - context with _trust_score=0.3
  - Assert "SPEAK FREELY" NOT in system_prompt
  - Assert EventType.REGISTER_SHIFT_DENIED emitted with reason="trust_below_threshold"

test_speak_freely_ward_room_response_high_trust
  - Same as auto_granted but through _build_ward_room_compose_prompt

test_speak_freely_ward_room_response_denied_low_trust
  - Same as denied but through _build_ward_room_compose_prompt

test_no_speak_freely_without_intended_action
  - context with _trust_score=0.9 but intended_actions=["ward_room_post"] (no speak_freely)
  - Assert "SPEAK FREELY" NOT in system_prompt
  - Assert no REGISTER_SHIFT events emitted
```

For trust-gated tests, wire `_emit_event_fn` as a mock that captures calls:

```python
emitted = []
def mock_emit(event_type, data):
    emitted.append((event_type, data))
context["_emit_event_fn"] = mock_emit
```

#### 3. Short-Circuit Guard (2 tests)

```
test_speak_freely_does_not_trigger_short_circuit
  - Create SubTaskResult with intended_actions=["ward_room_reply", "speak_freely"]
  - Assert _should_short_circuit returns False

test_silent_still_short_circuits
  - Create SubTaskResult with intended_actions=["silent"]
  - Assert _should_short_circuit returns True (regression guard)
```

#### 4. Event Types (1 test)

```
test_register_shift_event_types_exist
  - Assert EventType.REGISTER_SHIFT_GRANTED exists
  - Assert EventType.REGISTER_SHIFT_DENIED exists
  - Assert their .value matches expected strings
```

#### 5. Counselor Subscription (2 tests)

```
test_counselor_subscribes_to_register_shift_events
  - Instantiate CounselorAgent with mock _add_event_listener_fn
  - Assert REGISTER_SHIFT_GRANTED and REGISTER_SHIFT_DENIED in subscribed event_types

test_counselor_handles_register_shift_event
  - Call _on_register_shift with mock event_data (authorization="flagged")
  - Assert no exceptions (handler is log-only for now)
```

**Total: 14 tests**

---

## Files Modified

| File | Change |
|------|--------|
| `src/probos/events.py` | Add `REGISTER_SHIFT_GRANTED`, `REGISTER_SHIFT_DENIED` |
| `src/probos/cognitive/sub_tasks/analyze.py` | Extend `intended_actions` in thread_analysis + situation_review prompts |
| `src/probos/cognitive/sub_tasks/compose.py` | Add trust-gated speak_freely injection in proactive + ward_room builders; add `EventType` import |
| `src/probos/cognitive/cognitive_agent.py` | Wire `_emit_event_fn` + `_agent_id` into observation context |
| `src/probos/cognitive/counselor.py` | Subscribe to new events, add `_on_register_shift` handler |
| `tests/test_ad653_dynamic_register.py` | 14 new tests |

---

## Engineering Principles Compliance

- **SRP**: Detection (ANALYZE) / Authorization (COMPOSE) / Observability (Events+Counselor) — separate concerns in separate locations
- **Open/Closed**: Extends existing intended_actions vocabulary, event types, and Counselor subscriptions — all additive, no existing behavior changed
- **DRY**: Reuses existing `_trust_score` from context, existing `_communication_context`, existing AD-651a billet injection pattern. Two similar speak_freely blocks in two compose builders is acceptable — premature extraction before the pattern stabilizes would violate YAGNI
- **Law of Demeter**: Trust accessed via `context.get("_trust_score")`, event emission via `context.get("_emit_event_fn")` — no reaching through object chains
- **Dependency Inversion**: Counselor subscribes to events, doesn't reach into chain internals
- **Billet Instruction Principle**: "Speak freely" framing injected only when ANALYZE requests it — conditional billet instruction, exactly matching AD-651a's proposal pattern
- **Dual-Mode Operation**: This is the bridge between structured (duty) and emergent (social) — agents can signal when structure constrains important output
- **Unified Pipeline** (AD-652): No parallel pipeline. Same chain, contextual modulation via intended_actions

---

## Verification Checklist (for builder)

Before committing:
1. `grep -n "speak_freely" src/probos/cognitive/sub_tasks/analyze.py` — appears in thread_analysis AND situation_review, NOT in dm_comprehension
2. `grep -n "REGISTER_SHIFT" src/probos/events.py` — both GRANTED and DENIED exist
3. `grep -n "speak_freely" src/probos/cognitive/sub_tasks/compose.py` — appears in proactive AND ward_room builders
4. `grep -n "REGISTER_SHIFT" src/probos/cognitive/counselor.py` — both in subscription list AND dispatcher
5. `grep -n "_emit_event_fn" src/probos/cognitive/cognitive_agent.py` — wired in both observation paths
6. Run: `python -m pytest tests/test_ad653_dynamic_register.py -v`
7. Run: `python -m pytest tests/ -x --timeout=30` — full suite passes
