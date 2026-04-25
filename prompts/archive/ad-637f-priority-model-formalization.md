# AD-637f: Priority Model Formalization

**Parent:** AD-637 (NATS Event Bus Migration)
**Depends on:** AD-637a (NATSBus), AD-637c (Ward Room NATS), AD-637d (System Events NATS), AD-636 (LLM Priority Scheduling)
**Status:** Ready for builder

## Context

AD-637 is migrating ProbOS from ad-hoc asyncio messaging to NATS as the unified event bus. Sub-ADs a–e are complete. This is the final sub-AD.

ProbOS already achieves the desired priority behaviors through 4 independent mechanisms:

| Behavior | Mechanism | Location |
|---|---|---|
| Captain DMs get reserved LLM slots | AD-636 interactive semaphore (2 slots) | `cognitive/llm_client.py:150-160,296-320` |
| Captain delivery completes before agent routing | BF-188 `_captain_delivery_done` Event | `ward_room_router.py:80-83,403-433` |
| Captain/mention/DM skip quality gates | Social obligation bypass flags | `cognitive_agent.py:1663-1669`, `evaluate.py:356-377`, `reflect.py:415-441` |
| Proactive doesn't starve interactive | AD-636 stagger + background semaphore | `proactive.py:367-390`, `llm_client.py:158-160` |

**The problem:** These mechanisms work but are undocumented as a unified model. There's no `Priority` enum — just a single string comparison (`"interactive"` vs `"background"` at `cognitive_agent.py:1426`). Additionally:
- Captain @mentions in Ward Room don't get interactive LLM priority (only DMs do — `cognitive_agent.py:1426`)
- NATS messages carry no priority headers, making observability impossible

**What this AD does NOT do:**
- No NATS subject partitioning by priority tier (priority is a consumption concern, not transport)
- No changes to ward room subject structure (`wardroom.events.{event_type}` unchanged)
- No changes to BF-188 Captain delivery ordering (already correct)
- No changes to cognitive chain bypass logic (already correct)
- No IntentBus dispatch reordering (urgency remains metadata-only)
- No priority metrics emission (headers provide substrate; metrics are a separate AD)
- No federation NATS headers (federation uses core NATS gossip, not JetStream — no observability consumer)
- **No third semaphore tier** — `Priority.LOW` is an observability label, not a functional deferral. LOW maps to the same background semaphore as NORMAL. A third semaphore tier (deferrable lane) would require its own AD justification.

## Scope

1. **Priority enum** — Formalize the three-tier model as a first-class `StrEnum`
2. **Unified classifier** — Single `Priority.classify()` static method consumed by both LLM and NATS header call sites
3. **LLM priority expansion** — Captain @mentions and DMs (from anyone) get interactive LLM priority
4. **NATS priority headers** — `X-Priority` headers on JetStream publishes for observability (CRITICAL or NORMAL only — LOW is LLM-tier only)
5. **Guaranteed delivery verification** — Cross-reference existing AD-637c/d ack/nak tests

## Engineering Principles Compliance

- **SOLID/S:** Priority enum is a single concept with one responsibility
- **SOLID/O:** LLM client extended via existing `priority` parameter — no interface changes
- **SOLID/D:** Components depend on `Priority` enum (abstraction), not string literals
- **DRY:** Single `Priority.classify()` replaces two independent classifiers. Replaces scattered string comparisons.
- **Fail Fast:** Priority header failures are log-and-degrade (non-critical metadata)

---

## File 1: `src/probos/types.py` — Priority Enum + Classifier

### 1a: Add Priority enum

Add after existing imports (line 9 already has `from enum import Enum`; add `StrEnum` to that import):

```python
from enum import Enum, StrEnum
```

Add the enum after existing dataclasses (after `IntentResult`):

```python
class Priority(StrEnum):
    """Three-tier priority model (AD-637f).

    CRITICAL: Captain messages, @mentions, DMs — reserved LLM slots, bypass quality gates.
    NORMAL: Ward room participation, standard intents — default processing.
    LOW: Proactive think cycles — observability label only; uses same background
         semaphore as NORMAL. A functional deferral tier (third semaphore) would
         require its own AD.
    """
    CRITICAL = "critical"
    NORMAL = "normal"
    LOW = "low"

    @staticmethod
    def classify(
        *,
        intent: str = "",
        is_captain: bool = False,
        was_mentioned: bool = False,
    ) -> "Priority":
        """Classify priority from observation context (AD-637f).

        Single source of truth — used by both LLM scheduling (cognitive_agent.py)
        and NATS header emission (communication.py, runtime.py).

        Rules:
        - Captain-originated or @mentioned → CRITICAL
        - DMs (from anyone) → CRITICAL (conversational, latency-sensitive)
        - Proactive think → LOW (observability label; same semaphore as NORMAL)
        - Everything else → NORMAL
        """
        if is_captain or was_mentioned:
            return Priority.CRITICAL
        if intent == "direct_message":
            return Priority.CRITICAL
        if intent == "proactive_think":
            return Priority.LOW
        return Priority.NORMAL
```

**Why `StrEnum` (not `str, Enum`):** Python 3.14 (confirmed). `StrEnum.__str__` is guaranteed to return `self.value`, making `json.dumps` reliable without `__str__` overrides.

**Why `classify()` is here:** Single source of truth (DRY). Both call sites (cognitive agent LLM scheduling and ward room NATS headers) pre-process their data into the same keyword args and call this function. No data-shape coupling — the function doesn't know about ward room payloads or observation dicts.

---

## File 2: `src/probos/cognitive/llm_client.py` — Priority Enum Integration

### 2a: Import Priority

At top of file, add:
```python
from probos.types import Priority
```

### 2b: Replace string priority parameter

In `BaseLLMClient.complete()` (line 25), `LLMClient.complete()` (line 296), and `MockLLMClient.complete()` (line 864):

Change the signature from:
```python
async def complete(self, request: LLMRequest, *, priority: str = "background") -> LLMResponse:
```
To:
```python
async def complete(self, request: LLMRequest, *, priority: Priority = Priority.NORMAL) -> LLMResponse:
```

**No `str | Priority` union.** There is exactly ONE caller that passes `priority=` (`cognitive_agent.py:1427`), and this AD rewrites that call site. No backward compatibility needed.

### 2c: Update semaphore selection logic

In `LLMClient.complete()` (line 307), change:
```python
sem = self._interactive_semaphore if priority == "interactive" else self._background_semaphore
```
To:
```python
# AD-637f: CRITICAL uses reserved interactive slots; NORMAL and LOW share background
sem = self._interactive_semaphore if priority == Priority.CRITICAL else self._background_semaphore
```

### 2d: Update docstring

In `LLMClient.complete()` (lines 303-304), change:
```python
        AD-636: priority="interactive" uses reserved slots (Captain DMs).
        priority="background" uses remaining capacity (proactive, chains).
```
To:
```python
        AD-636/637f: Priority.CRITICAL uses reserved interactive slots
        (Captain DMs, @mentions). NORMAL and LOW share background capacity.
        LOW is an observability label — same semaphore as NORMAL.
```

---

## File 3: `src/probos/cognitive/cognitive_agent.py` — Priority Classification

### 3a: Import Priority

At top of file, add:
```python
from probos.types import Priority
```

### 3b: Replace inline priority classification

In `_decide_via_llm()` method (line 1239), around line 1425-1427, change:
```python
        # AD-636: Interactive priority for Captain DMs
        _priority = "interactive" if observation.get("intent") == "direct_message" else "background"
        response = await self._llm_client.complete(request, priority=_priority)
```
To:
```python
        # AD-637f: Unified priority classification
        _params = observation.get("params", {})
        _priority = Priority.classify(
            intent=observation.get("intent", ""),
            is_captain=_params.get("author_id", "") == "captain",
            was_mentioned=_params.get("was_mentioned", False),
        )
        response = await self._llm_client.complete(request, priority=_priority)
```

**Why we read `params` directly (not `_from_captain` flag):** The `_from_captain` and `_was_mentioned` observation flags are only set in the chain execution paths (`_execute_sub_task_chain()` at line 1665, `_execute_chain_with_intent_routing()` at line 1843). `_decide_via_llm()` is the single-call fallback — these flags don't exist here. The raw intent params contain `author_id` and `was_mentioned` (set by WardRoomRouter at `ward_room_router.py:513-515`).

**Behavioral change:** Captain @mentions in Ward Room now get reserved interactive LLM slots (previously only DMs did). All DMs (from anyone) remain CRITICAL — DMs are conversational and latency-sensitive regardless of sender.

---

## File 4: `src/probos/startup/communication.py` — NATS Priority Headers

### 4a: Import Priority

At top of `setup_communication()` or at module level:
```python
from probos.types import Priority
```

### 4b: Add priority header to ward room JetStream publishes

In `_ward_room_emit()` (around line 128-153), modify the NATS publish path.

Change:
```python
                payload = {"event_type": event_type, **data}
                subject = f"wardroom.events.{event_type}"
                task = loop.create_task(nats_bus.js_publish(subject, payload))
```
To:
```python
                payload = {"event_type": event_type, **data}
                subject = f"wardroom.events.{event_type}"
                # AD-637f: Priority header for observability
                _author = data.get("author_id", "")
                _mentions = data.get("mentions", [])
                _is_captain = _author == "captain"
                _was_mentioned = "captain" in [
                    m.lower() for m in _mentions if isinstance(m, str)
                ]
                _priority = Priority.classify(
                    is_captain=_is_captain,
                    was_mentioned=_was_mentioned,
                )
                headers = {"X-Priority": _priority.value}
                task = loop.create_task(nats_bus.js_publish(subject, payload, headers=headers))
```

**Ward room event payload shape (verified at `ward_room/messages.py:230-237`):**
- `author_id: str` — the post author
- `mentions: list[str]` — from `extract_mentions(body)`, contains callsign strings

This is different from the router's per-agent `was_mentioned: bool` (set at `ward_room_router.py:515`). The event-level classifier checks if "captain" is in the mentions list. The intent-level classifier (cognitive_agent.py) reads the pre-computed boolean. Both use `Priority.classify()` with the same keyword interface — the data extraction differs, the classification logic doesn't.

**`js_publish` already accepts `headers`** — see `nats_bus.py:275-293`. No NATSBus changes needed.

**Note:** X-Priority headers carry CRITICAL or NORMAL only. Ward room events are never LOW — proactive thinks don't flow through ward room NATS subjects.

---

## File 5: `src/probos/runtime.py` — System Events Priority Headers

### 5a: Import Priority

At top of file, add:
```python
from probos.types import Priority
```

### 5b: Add priority header to system event JetStream publishes

In `_emit_event()` (around line 736-737), change:
```python
            subject = f"system.events.{type_str}"
            task = loop.create_task(self.nats_bus.js_publish(subject, event))
```
To:
```python
            subject = f"system.events.{type_str}"
            headers = {"X-Priority": Priority.NORMAL.value}
            task = loop.create_task(self.nats_bus.js_publish(subject, event, headers=headers))
```

**Why NORMAL for all system events:** System events are operational telemetry (agent state changes, trust updates, dream completions). None are interactive. The header is for observability consistency — all NATS JetStream messages now carry `X-Priority`.

**NATS server version requirement:** Headers require NATS server ≥2.2. The nats-py client handles this transparently.

---

## File 6: `tests/test_ad637f_priority.py` — New Test File

Create `tests/test_ad637f_priority.py` with the following tests:

### Test 1: Priority enum values
```python
def test_priority_enum_values():
    """Priority StrEnum has expected string values."""
    from probos.types import Priority
    assert Priority.CRITICAL.value == "critical"
    assert Priority.NORMAL.value == "normal"
    assert Priority.LOW.value == "low"
```

### Test 2: Priority is JSON-serializable
```python
def test_priority_json_serializable():
    """Priority StrEnum is JSON-serializable in dict values and list elements."""
    import json
    from probos.types import Priority
    # Dict value path
    assert json.dumps({"priority": Priority.CRITICAL}) == '{"priority": "critical"}'
    # List element path (exercises different json code path)
    assert json.dumps([Priority.CRITICAL, Priority.LOW]) == '["critical", "low"]'
```

### Test 3: Priority.classify — Captain is CRITICAL
```python
def test_classify_captain_is_critical():
    from probos.types import Priority
    assert Priority.classify(is_captain=True) == Priority.CRITICAL
```

### Test 4: Priority.classify — mentioned is CRITICAL
```python
def test_classify_mentioned_is_critical():
    from probos.types import Priority
    assert Priority.classify(was_mentioned=True) == Priority.CRITICAL
```

### Test 5: Priority.classify — DM is CRITICAL (any sender)
```python
def test_classify_dm_is_critical():
    """All DMs get CRITICAL — conversational and latency-sensitive."""
    from probos.types import Priority
    # Non-captain DM
    assert Priority.classify(intent="direct_message") == Priority.CRITICAL
    # Captain DM (captain flag takes precedence, same result)
    assert Priority.classify(intent="direct_message", is_captain=True) == Priority.CRITICAL
```

### Test 6: Priority.classify — proactive think is LOW
```python
def test_classify_proactive_is_low():
    from probos.types import Priority
    assert Priority.classify(intent="proactive_think") == Priority.LOW
```

### Test 7: Priority.classify — ward room notification is NORMAL
```python
def test_classify_ward_room_is_normal():
    from probos.types import Priority
    assert Priority.classify(intent="ward_room_notification") == Priority.NORMAL
```

### Test 8: Priority.classify — defaults to NORMAL
```python
def test_classify_defaults_to_normal():
    from probos.types import Priority
    assert Priority.classify() == Priority.NORMAL
```

### Test 9: LLM client accepts Priority enum
```python
@pytest.mark.asyncio
async def test_llm_client_priority_enum():
    """LLM client complete() accepts Priority enum values."""
    from probos.types import Priority
    # Use MockLLMClient — standard test setup
    client = MockLLMClient(...)
    request = LLMRequest(...)
    # All three tiers should be accepted without error
    await client.complete(request, priority=Priority.CRITICAL)
    await client.complete(request, priority=Priority.NORMAL)
    await client.complete(request, priority=Priority.LOW)
```

### Test 10: CRITICAL priority uses interactive semaphore
```python
@pytest.mark.asyncio
async def test_critical_uses_interactive_semaphore():
    """Priority.CRITICAL routes to interactive semaphore (reserved LLM slots)."""
    from probos.types import Priority
    # Create LLMClient with known config
    # Fill background semaphore to capacity
    # Verify Priority.CRITICAL still proceeds (uses different semaphore)
    # Verify Priority.NORMAL blocks (same semaphore as background)
```

### Test 11: Ward room NATS publish includes priority header
```python
@pytest.mark.asyncio
async def test_ward_room_nats_publish_has_priority_header():
    """Ward room JetStream publishes include X-Priority header."""
    # Use MockNATSBus, trigger ward room event emission
    # Verify published message has headers={"X-Priority": "normal"} or "critical"
```

### Test 12: Captain author ward room event gets CRITICAL header
```python
@pytest.mark.asyncio
async def test_ward_room_captain_author_gets_critical_header():
    """Ward room event from Captain carries X-Priority: critical header."""
    # Emit ward room event with author_id="captain"
    # Verify js_publish called with headers={"X-Priority": "critical"}
```

### Test 13: Captain mentioned ward room event gets CRITICAL header
```python
@pytest.mark.asyncio
async def test_ward_room_captain_mentioned_gets_critical_header():
    """Ward room event mentioning Captain carries X-Priority: critical header."""
    # Emit ward room event with mentions=["Captain"]
    # Verify js_publish called with headers={"X-Priority": "critical"}
```

---

## Guaranteed Delivery Verification

**Not a code deliverable.** Cross-reference existing tests that verify ack/nak contracts:

- **Ward room JetStream ack/nak:** Covered by AD-637c tests in `tests/test_ward_room_nats.py` — `js_subscribe` handler wrapper in `nats_bus.py:325-334` acks on success, naks on exception.
- **System events JetStream ack/nak:** Covered by AD-637d tests in `tests/test_ad637d_system_events_nats.py` — same handler wrapper pattern.
- **IntentBus NATS send:** Uses `request()` (request/reply, not JetStream) — no ack needed. Timeout handled by IntentBus.
- **Federation NATS transport:** Core NATS fire-and-forget (appropriate for gossip protocol).

If the builder discovers any of these test references are incorrect, add the missing test. Otherwise no new guaranteed-delivery tests needed — the contracts are already verified.

---

## Verification

```bash
# Targeted tests
pytest tests/test_ad637f_priority.py -v

# Regression — cognitive chain and LLM client
pytest tests/test_cognitive_agent.py tests/test_llm_client.py -v

# Regression — ward room NATS (AD-637c)
pytest tests/test_ward_room_nats.py -v

# Regression — system events NATS (AD-637d)
pytest tests/test_ad637d_system_events_nats.py -v

# Full suite (background)
pytest -n auto
```

---

## Summary of Changes

| File | Change |
|---|---|
| `src/probos/types.py` | Add `Priority(StrEnum)` with CRITICAL/NORMAL/LOW + `classify()` static method |
| `src/probos/cognitive/llm_client.py` | Accept `Priority` enum (not strings), CRITICAL uses interactive semaphore |
| `src/probos/cognitive/cognitive_agent.py` | Replace inline string classification with `Priority.classify()` |
| `src/probos/startup/communication.py` | Add `X-Priority` header to ward room JetStream publishes via `Priority.classify()` |
| `src/probos/runtime.py` | Add `X-Priority: normal` header to system event JetStream publishes |
| `tests/test_ad637f_priority.py` | 13 new tests |

## What This Does NOT Change

- BF-188 Captain delivery ordering — already correct
- Cognitive chain bypass logic — already correct
- Ward room subject structure — `wardroom.events.{event_type}` unchanged
- IntentBus dispatch ordering — urgency remains metadata-only
- Proactive stagger — AD-636 timing unchanged
- NATSBus API — no new methods needed
- Federation NATS headers — excluded (gossip protocol, no JetStream)
- Semaphore tiers — LOW maps to background semaphore (same as NORMAL); third tier would be separate AD
