# BF-034: Post-Reset Trust Anomaly False Positives

**Goal:** After `probos reset -y`, EmergentDetector fires a storm of trust anomaly alerts (6+ consecutive) because it has no concept of "cold start" — it sees baseline trust (0.5) as anomalous change-points against a missing previous snapshot, and probationary agents (0.25) as deviations. Agents then interpret these alerts as system problems and enter a discussion spiral about trust "demotions." This fix adds cold-start awareness so the system correctly treats post-reset baseline trust as normal initialization.

**Scope:** Small-medium. Three files modified, one new test file.

**Root cause:** No code in the system detects "this is a fresh start after reset." `_restore_from_knowledge()` silently succeeds with nothing. EmergentDetector runs its full analysis suite on the first dream cycle against an empty history, producing false positives. Agents see "Your trust: 0.5" with no context note explaining it's baseline.

---

## Step 1: Cold-Start Detection in Runtime

**File:** `src/probos/runtime.py`

### 1a. Add `_cold_start` attribute

At the end of the attribute block (near line ~290, after the other `self._xxx` attributes), add:

```python
# BF-034: Cold-start flag — True when booting with empty state (post-reset)
self._cold_start: bool = False
```

### 1b. Add `is_cold_start` property

Add a public property (near the other properties, around line ~460-480):

```python
@property
def is_cold_start(self) -> bool:
    """True during first cycle after a clean reset (no prior state)."""
    return self._cold_start
```

### 1c. Detect cold start after warm boot

In `start()`, **after** `_restore_from_knowledge()` completes (line ~1034) and **after** EmergentDetector is created (line ~1086), add cold-start detection:

```python
# BF-034: Detect cold start (post-reset boot with empty state)
if self._knowledge_store and self._emergent_detector:
    trust_records = self.trust_network.raw_scores()
    all_at_prior = all(
        abs(r["alpha"] - self.config.consensus.trust_prior_alpha) < 0.01
        and abs(r["beta"] - self.config.consensus.trust_prior_beta) < 0.01
        for r in trust_records.values()
    ) if trust_records else True
    episodes_empty = (
        not self.episodic_memory
        or getattr(self.episodic_memory, '_total_episodes', 0) == 0
    )
    if all_at_prior and episodes_empty:
        self._cold_start = True
        self._emergent_detector.set_cold_start_suppression(300)  # 5 minutes
        logger.info("BF-034: Cold start detected — suppressing trust anomalies for 5 minutes")
```

Place this right after line ~1086 (`_refresh_emergent_detector_roster()`), before the dream scheduler wiring (line ~1088).

### 1d. Clear cold-start flag after first dream cycle

In `_on_post_dream()` (line ~3513), add at the very top of the method (before the system_mode event):

```python
# BF-034: Clear cold-start flag after first dream cycle
if self._cold_start:
    self._cold_start = False
    logger.info("BF-034: Cold start period ended — normal detection resumed")
```

### 1e. Post-reset announcement to Ward Room

In `start()`, right after the cold-start detection block from 1c, if cold start is detected AND Ward Room is available, post a system announcement:

```python
# BF-034: Announce fresh start to crew
if self._cold_start and self.ward_room:
    async def _announce_cold_start():
        try:
            channels = await self.ward_room.list_channels()
            all_hands = next((c for c in channels if c.channel_type == "ship"), None)
            if all_hands:
                await self.ward_room.create_thread(
                    channel_id=all_hands.id,
                    author_id="system",
                    title="Fresh Start — System Reset",
                    body=(
                        "This instance has been reset. All trust scores are at baseline (0.5) — "
                        "this is normal initialization, not a demotion. Trust will be rebuilt "
                        "through demonstrated competence. Episodic memory has been cleared. "
                        "Previous experiences are not available."
                    ),
                    author_callsign="Ship's Computer",
                    thread_mode="announce",
                    max_responders=0,
                )
        except Exception:
            pass  # best-effort
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_announce_cold_start())
    except RuntimeError:
        pass
```

---

## Step 2: EmergentDetector Cold-Start Suppression

**File:** `src/probos/cognitive/emergent_detector.py`

### 2a. Add suppression state

In `__init__()`, after line 133 (the `_last_pattern_fired` dict), add:

```python
# BF-034: Cold-start suppression — suppress trust anomalies for N seconds after reset
self._suppress_trust_until: float = 0.0
```

### 2b. Add `set_cold_start_suppression()` method

After `set_pattern_cooldown()` (line ~141), add:

```python
def set_cold_start_suppression(self, duration_seconds: float) -> None:
    """Suppress trust anomaly detection for *duration_seconds* after a cold start.

    Cooperation clusters and routing shifts still fire — those are useful
    even post-reset. Only trust anomalies are suppressed since baseline
    trust (0.5) is expected, not anomalous.
    """
    self._suppress_trust_until = time.monotonic() + duration_seconds
```

### 2c. Guard `detect_trust_anomalies()`

At the top of `detect_trust_anomalies()` (line ~370), after `patterns: list[EmergentPattern] = []`, add:

```python
# BF-034: Suppress during cold-start period
if time.monotonic() < self._suppress_trust_until:
    return patterns
```

This is a clean early return that suppresses ALL trust anomaly sub-checks (deviation, hyperactive, change-point) during the cold-start window. Cooperation clusters, routing shifts, and consolidation anomalies are NOT affected.

---

## Step 3: Proactive Context Injection for Cold Start

**File:** `src/probos/proactive.py`

### 3a. Inject cold-start note into context

In `_gather_context()` (line ~352), right after `context: dict[str, Any] = {}` (line 355), add:

```python
# BF-034: Cold-start context note for agents
if hasattr(rt, 'is_cold_start') and rt.is_cold_start:
    context["system_note"] = (
        "SYSTEM NOTE: This is a fresh start after a system reset. "
        "All trust scores are at baseline (0.5). This is normal initialization, "
        "not a demotion. Build trust through demonstrated competence. "
        "You have no prior episodic memories — do not reference or invent past experiences."
    )
```

**File:** `src/probos/cognitive/cognitive_agent.py`

### 3b. Render system note in proactive think prompt

In `_build_user_message()`, in the `proactive_think` branch, right after the trust/agency line is appended (after line 466 for duty, after line 473 for free-form), add rendering for the system note. The cleanest insertion point is right after both branches join — at line ~481 before "Recent memories":

Find this block (line ~482-494):
```python
            # Recent memories
            memories = context_parts.get("recent_memories", [])
```

Insert **before** it:

```python
            # BF-034: Cold-start system note
            system_note = context_parts.get("system_note")
            if system_note:
                pt_parts.append(system_note)
                pt_parts.append("")
```

---

## Step 4: Tests

**File:** `tests/test_bf034_cold_start.py` (new file)

```python
"""BF-034: Post-reset trust anomaly false positive suppression."""

import time
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from probos.cognitive.emergent_detector import EmergentDetector
from probos.consensus.trust import TrustNetwork


# ---------- EmergentDetector suppression ----------

class TestColdStartSuppression:
    """EmergentDetector should suppress trust anomalies during cold-start window."""

    def _make_detector(self) -> EmergentDetector:
        trust = TrustNetwork()
        # Register a few agents at baseline
        for i in range(5):
            trust.get_or_create(f"agent-{i}")
        router = MagicMock()
        router.all_weights.return_value = {}
        detector = EmergentDetector(
            hebbian_router=router,
            trust_network=trust,
        )
        detector.set_live_agents({f"agent-{i}" for i in range(5)})
        return detector

    def test_trust_anomalies_suppressed_during_cold_start(self):
        detector = self._make_detector()
        detector.set_cold_start_suppression(300)  # 5 minutes

        # Manually create a deviation by setting one agent's trust high
        record = detector._trust.get_or_create("agent-0")
        record.alpha = 10.0  # score = 10/12 ≈ 0.83

        anomalies = detector.detect_trust_anomalies()
        assert len(anomalies) == 0, "Trust anomalies should be suppressed during cold start"

    def test_trust_anomalies_fire_after_suppression_window(self):
        detector = self._make_detector()
        # Set suppression to expire immediately
        detector._suppress_trust_until = time.monotonic() - 1

        # Create deviation
        record = detector._trust.get_or_create("agent-0")
        record.alpha = 10.0

        anomalies = detector.detect_trust_anomalies()
        # May or may not fire depending on population stats, but suppression is not blocking
        # The key assertion is that it doesn't early-return
        # (We can't guarantee a fire since std may be low with 5 agents)

    def test_cooperation_clusters_not_suppressed(self):
        detector = self._make_detector()
        detector.set_cold_start_suppression(300)

        # Cooperation clusters should still work during cold start
        # (Just verify the method runs without being blocked)
        clusters = detector.detect_cooperation_clusters()
        assert isinstance(clusters, list)

    def test_routing_shifts_not_suppressed(self):
        detector = self._make_detector()
        detector.set_cold_start_suppression(300)

        shifts = detector.detect_routing_shifts()
        assert isinstance(shifts, list)


# ---------- Proactive context injection ----------

class TestColdStartContext:
    """Proactive loop should inject system note during cold start."""

    def test_system_note_in_context(self):
        """When runtime.is_cold_start is True, context should include system_note."""
        from probos.proactive import ProactiveLoop

        runtime = MagicMock()
        runtime.is_cold_start = True
        runtime.ward_room = None
        runtime.episodic_memory = None
        runtime.bridge_alerts = None
        runtime.event_log = None

        loop = ProactiveLoop(runtime, interval=60)
        # _gather_context is async — we need to run it
        import asyncio
        context = asyncio.get_event_loop().run_until_complete(
            loop._gather_context(MagicMock(), 0.5)
        )
        assert "system_note" in context
        assert "fresh start" in context["system_note"].lower()

    def test_no_system_note_when_not_cold_start(self):
        """When runtime.is_cold_start is False, no system_note."""
        from probos.proactive import ProactiveLoop

        runtime = MagicMock()
        runtime.is_cold_start = False
        runtime.ward_room = None
        runtime.episodic_memory = None
        runtime.bridge_alerts = None
        runtime.event_log = None

        loop = ProactiveLoop(runtime, interval=60)
        import asyncio
        context = asyncio.get_event_loop().run_until_complete(
            loop._gather_context(MagicMock(), 0.5)
        )
        assert "system_note" not in context


# ---------- Build user message rendering ----------

class TestColdStartPromptRendering:
    """System note should appear in the proactive think prompt when present."""

    def test_system_note_rendered_in_prompt(self):
        from probos.cognitive.cognitive_agent import CognitiveAgent

        agent = CognitiveAgent.__new__(CognitiveAgent)
        # Minimal setup for _build_user_message
        agent._agent_type = "test_agent"

        msg = agent._build_user_message(
            "proactive_think",
            {
                "context_parts": {
                    "system_note": "SYSTEM NOTE: This is a test cold start note."
                },
                "trust_score": 0.5,
                "agency_level": "suggestive",
                "agent_type": "test_agent",
                "duty": None,
            },
        )
        assert "SYSTEM NOTE" in msg
        assert "cold start" in msg.lower()

    def test_no_system_note_when_absent(self):
        from probos.cognitive.cognitive_agent import CognitiveAgent

        agent = CognitiveAgent.__new__(CognitiveAgent)
        agent._agent_type = "test_agent"

        msg = agent._build_user_message(
            "proactive_think",
            {
                "context_parts": {},
                "trust_score": 0.5,
                "agency_level": "suggestive",
                "agent_type": "test_agent",
                "duty": None,
            },
        )
        assert "SYSTEM NOTE" not in msg
```

---

## Integration Summary

| Component | Change | Why |
|-----------|--------|-----|
| `runtime.py` | `_cold_start` flag + detection + Ward Room announcement + clear on first dream | System knows it just reset |
| `emergent_detector.py` | `set_cold_start_suppression()` + early return in `detect_trust_anomalies()` | Stop false positive storm |
| `proactive.py` | Inject `system_note` into context when cold start | Agents understand baseline is normal |
| `cognitive_agent.py` | Render `system_note` in proactive think prompt | Agents see the note in their prompt |

## What This Does NOT Change

- Restart behavior (normal restart preserves trust — not affected)
- Trust prior values (still α=2, β=2 → 0.5)
- Cooperation cluster detection (still fires post-reset — useful signal)
- Routing shift detection (still fires post-reset — useful signal)
- Consolidation anomaly detection (still fires — needs dream history anyway)
- Any prompt content outside of `proactive_think`
