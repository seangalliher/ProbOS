# Phase 28b: Proactive Cognitive Loop — Periodic Idle-Think for Crew Agents

## Overview

ProbOS agents currently only think when an intent arrives — they're purely reactive. The Ward Room proved agents can communicate meaningfully, Earned Agency (AD-357) proved trust can gate participation, and Bridge Alerts proved the Ship's Computer can trigger crew response. The missing piece: agents initiating thought on their own.

This implements a periodic "idle think" cycle where crew agents review recent events (episodic memory, bridge alerts, system events) and decide whether anything warrants action — a Ward Room post, or `[NO_RESPONSE]` if nothing is noteworthy.

**Scope:** Full proactive autonomy. 120-second interval. Sequential agent processing (one at a time).

## Think Cycle Flow (per agent, per cycle)

```
1. Check agency: Rank.from_trust(trust) → skip if ENSIGN (reactive only)
2. Check cooldown: skip if agent posted proactively < cooldown_seconds ago
3. Gather context:
   - Recent episodic memories for this agent (recall_for_agent, k=5)
   - Recent bridge alerts (get_recent_alerts, limit=5)
   - Recent system events (event_log.query, limit=10)
4. Send proactive_think intent to agent via handle_intent()
5. Agent's LLM decides: post to WR or [NO_RESPONSE]
6. If agent responds (not [NO_RESPONSE]): create WR thread in agent's department channel
7. Record proactive timestamp for cooldown tracking
```

## Files to Change

### Part 1: Agency Logic — `src/probos/earned_agency.py`

Add after `can_respond_ambient()` (line 49):

```python
def can_think_proactively(rank: Rank) -> bool:
    """Can this agent initiate proactive thought?

    Ensigns are reactive-only — they haven't earned the trust to
    self-initiate. Everyone else can think proactively.
    """
    return rank != Rank.ENSIGN
```

### Part 2: Config — `src/probos/config.py`

Insert after `EarnedAgencyConfig` (line 294):

```python
class ProactiveCognitiveConfig(BaseModel):
    """Proactive Cognitive Loop — periodic idle-think (Phase 28b)."""
    enabled: bool = False
    interval_seconds: float = 120.0
    cooldown_seconds: float = 300.0
```

Add to `SystemConfig` (line 355, after `earned_agency`):

```python
    proactive_cognitive: ProactiveCognitiveConfig = ProactiveCognitiveConfig()
```

### Part 3: Config file — `config/system.yaml`

Insert after the `earned_agency` block (line 243), before `channels`:

```yaml
# --- Proactive Cognitive Loop (Phase 28b) ---
proactive_cognitive:
  enabled: true
  interval_seconds: 120
  cooldown_seconds: 300
```

### Part 4: Core Service — NEW `src/probos/proactive.py`

~120 lines. Follows the InitiativeEngine async loop pattern.

```python
"""Proactive Cognitive Loop — periodic idle-think for crew agents (Phase 28b)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

from probos.crew_profile import Rank
from probos.earned_agency import agency_from_rank, can_think_proactively
from probos.types import IntentMessage

logger = logging.getLogger(__name__)


class ProactiveCognitiveLoop:
    """Periodic idle-think cycle for crew agents.

    Every ``interval`` seconds, iterates crew agents sequentially.
    For each agent with sufficient trust (Lieutenant+), gathers recent
    context (episodic memory, bridge alerts, system events) and sends
    a ``proactive_think`` intent. If the agent's LLM produces a meaningful
    response (not ``[NO_RESPONSE]``), creates a Ward Room thread in the
    agent's department channel.

    Follows the InitiativeEngine pattern: asyncio.create_task, fail-open,
    CancelledError propagation.
    """

    def __init__(
        self,
        *,
        interval: float = 120.0,
        cooldown: float = 300.0,
        on_event: Callable[[dict], Any] | None = None,
    ) -> None:
        self._interval = interval
        self._cooldown = cooldown
        self._on_event = on_event
        self._last_proactive: dict[str, float] = {}  # agent_id -> monotonic timestamp
        self._task: asyncio.Task | None = None
        self._runtime: Any = None  # Set via set_runtime()

    def set_runtime(self, runtime: Any) -> None:
        """Wire the runtime reference (provides registry, trust, WR, memory, etc.)."""
        self._runtime = runtime

    async def start(self) -> None:
        """Start the periodic think loop."""
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._think_loop())

    async def stop(self) -> None:
        """Stop the think loop."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _think_loop(self) -> None:
        """Main loop: iterate agents every interval seconds."""
        while True:
            try:
                await self._run_cycle()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("ProactiveCognitiveLoop cycle failed (fail-open)")
            await asyncio.sleep(self._interval)

    async def _run_cycle(self) -> None:
        """One think cycle: iterate all crew agents sequentially."""
        rt = self._runtime
        if not rt or not rt.ward_room:
            return

        for agent in rt.registry.all():
            if not rt._is_crew_agent(agent):
                continue
            if not agent.is_alive:
                continue

            # Agency gating: Ensigns don't think proactively
            trust_score = rt.trust_network.get_score(agent.id)
            rank = Rank.from_trust(trust_score)
            if not can_think_proactively(rank):
                continue

            # Cooldown: skip if agent posted proactively recently
            last = self._last_proactive.get(agent.id, 0.0)
            if time.monotonic() - last < self._cooldown:
                continue

            try:
                await self._think_for_agent(agent, rank, trust_score)
            except Exception:
                logger.debug(
                    "Proactive think failed for %s (fail-open)", agent.agent_type,
                    exc_info=True,
                )

    async def _think_for_agent(self, agent: Any, rank: Rank, trust_score: float) -> None:
        """Gather context, send proactive_think intent, post result if meaningful."""
        rt = self._runtime
        context_parts = await self._gather_context(agent, trust_score)

        intent = IntentMessage(
            intent="proactive_think",
            params={
                "context_parts": context_parts,
                "trust_score": round(trust_score, 4),
                "agency_level": agency_from_rank(rank).value,
                "agent_type": agent.agent_type,
            },
            target_agent_id=agent.id,
        )

        result = await agent.handle_intent(intent)

        if not result or not result.success or not result.result:
            return

        response_text = str(result.result).strip()
        if not response_text or "[NO_RESPONSE]" in response_text:
            return

        # Post to Ward Room — find agent's department channel
        await self._post_to_ward_room(agent, response_text)
        self._last_proactive[agent.id] = time.monotonic()

        if self._on_event:
            self._on_event({
                "type": "proactive_thought",
                "data": {
                    "agent_id": agent.id,
                    "agent_type": agent.agent_type,
                    "response_length": len(response_text),
                },
            })

        logger.info(
            "Proactive thought from %s (%s): %d chars",
            agent.agent_type, rank.value, len(response_text),
        )

    async def _gather_context(self, agent: Any, trust_score: float) -> dict:
        """Gather recent context for the agent's proactive review."""
        rt = self._runtime
        context: dict[str, Any] = {}

        # 1. Recent episodic memories (sovereign — only this agent's experiences)
        if hasattr(rt, 'episodic_memory') and rt.episodic_memory:
            try:
                episodes = await rt.episodic_memory.recall_for_agent(
                    agent.id, "recent activity", k=5
                )
                if episodes:
                    context["recent_memories"] = [
                        {
                            "input": ep.user_input[:200] if ep.user_input else "",
                            "reflection": ep.reflection[:200] if ep.reflection else "",
                        }
                        for ep in episodes
                    ]
            except Exception:
                logger.debug("Episodic recall failed for %s", agent.id, exc_info=True)

        # 2. Recent bridge alerts
        if hasattr(rt, 'bridge_alerts') and rt.bridge_alerts:
            try:
                alerts = rt.bridge_alerts.get_recent_alerts(limit=5)
                if alerts:
                    context["recent_alerts"] = [
                        {
                            "severity": a.severity.value,
                            "title": a.title,
                            "source": a.source,
                        }
                        for a in alerts
                    ]
            except Exception:
                logger.debug("Bridge alerts fetch failed", exc_info=True)

        # 3. Recent system events
        if hasattr(rt, 'event_log') and rt.event_log:
            try:
                events = await rt.event_log.query(limit=10)
                if events:
                    context["recent_events"] = [
                        {
                            "category": e.get("category", ""),
                            "event": e.get("event", ""),
                            "agent_type": e.get("agent_type", ""),
                        }
                        for e in events[:10]
                    ]
            except Exception:
                logger.debug("Event log query failed", exc_info=True)

        return context

    async def _post_to_ward_room(self, agent: Any, text: str) -> None:
        """Create a Ward Room thread with the agent's proactive observation."""
        rt = self._runtime

        # Find agent's department channel
        from probos.cognitive.standing_orders import get_department
        dept = get_department(agent.agent_type)

        channels = await rt.ward_room.list_channels()
        target_channel = None

        if dept:
            # Prefer department channel
            for ch in channels:
                if ch.channel_type == "department" and ch.department == dept:
                    target_channel = ch
                    break

        if not target_channel:
            # Fallback to All Hands (ship-wide)
            for ch in channels:
                if ch.channel_type == "ship":
                    target_channel = ch
                    break

        if not target_channel:
            logger.debug("No target channel found for proactive post from %s", agent.agent_type)
            return

        # Get callsign
        callsign = ""
        if hasattr(rt, 'callsign_registry'):
            callsign = rt.callsign_registry.get_callsign(agent.agent_type)

        # Truncate to first sentence/line for title, use full text as body
        title_text = text.split('\n')[0][:100]
        if len(title_text) < len(text.split('\n')[0]):
            title_text += "..."

        await rt.ward_room.create_thread(
            channel_id=target_channel.id,
            author_id=agent.id,
            title=f"[Observation] {title_text}",
            body=text,
            author_callsign=callsign or agent.agent_type,
        )
```

### Part 5: CognitiveAgent — `src/probos/cognitive/cognitive_agent.py`

**5a. `handle_intent()`** (line 222): Add `"proactive_think"` to the `is_direct` check:

```python
        is_direct = (
            intent.intent in ("direct_message", "ward_room_notification", "proactive_think")
            and intent.target_agent_id == self.id
        )
```

**5b. `decide()`** (line 132): Add `"proactive_think"` to the `is_conversation` check:

```python
        is_conversation = observation.get("intent") in ("direct_message", "ward_room_notification", "proactive_think")
```

Then add an `elif` branch after the `ward_room_notification` system prompt block (after line 151, before the `else:` on line 152):

```python
            elif observation.get("intent") == "proactive_think":
                composed += (
                    "\n\nYou are reviewing recent ship activity during a quiet moment. "
                    "If you notice something noteworthy — a pattern, a concern, an insight "
                    "related to your expertise — compose a brief observation (2-4 sentences). "
                    "This will be posted to the Ward Room as a new thread. "
                    "Speak in your natural voice. Be specific and actionable. "
                    "If nothing warrants attention right now, respond with exactly: [NO_RESPONSE]"
                )
```

**5c. `_build_user_message()`** (after line 335, before the generic fallback block at line 337): Add a new branch for `proactive_think`:

```python
        # Phase 28b: proactive_think — idle review cycle
        if intent_name == "proactive_think":
            context_parts = params.get("context_parts", {})
            trust_score = params.get("trust_score", 0.5)
            agency_level = params.get("agency_level", "suggestive")

            pt_parts: list[str] = []
            pt_parts.append("[Proactive Review Cycle]")
            pt_parts.append(f"Your trust: {trust_score} | Agency: {agency_level}")
            pt_parts.append("")

            # Recent memories
            memories = context_parts.get("recent_memories", [])
            if memories:
                pt_parts.append("Recent memories (your experiences):")
                for m in memories:
                    if m.get("reflection"):
                        pt_parts.append(f"  - {m['reflection']}")
                    elif m.get("input"):
                        pt_parts.append(f"  - Handled: {m['input']}")
                pt_parts.append("")

            # Recent alerts
            alerts = context_parts.get("recent_alerts", [])
            if alerts:
                pt_parts.append("Recent bridge alerts:")
                for a in alerts:
                    pt_parts.append(f"  - [{a.get('severity', '?')}] {a.get('title', '?')} (from {a.get('source', '?')})")
                pt_parts.append("")

            # Recent events
            events = context_parts.get("recent_events", [])
            if events:
                pt_parts.append("Recent system events:")
                for e in events:
                    pt_parts.append(f"  - [{e.get('category', '?')}] {e.get('event', '?')}")
                pt_parts.append("")

            pt_parts.append("Based on this review, decide if anything warrants an observation or insight.")
            pt_parts.append("If something is noteworthy, compose a brief Ward Room post (2-4 sentences).")
            pt_parts.append("If nothing warrants attention, respond with exactly: [NO_RESPONSE]")
            return "\n".join(pt_parts)
```

### Part 6: Runtime Wiring — `src/probos/runtime.py`

**6a. Init** — Find where `self.proactive_loop` or similar service attributes are initialized (near `self.initiative = None`), add:

```python
        self.proactive_loop = None
```

**6b. `start()`** — Insert after Bridge Alerts (after line 1214, before `self._started = True` at line 1216):

```python
        # --- Proactive Cognitive Loop (Phase 28b) ---
        if self.config.proactive_cognitive.enabled and self.ward_room:
            from probos.proactive import ProactiveCognitiveLoop
            self.proactive_loop = ProactiveCognitiveLoop(
                interval=self.config.proactive_cognitive.interval_seconds,
                cooldown=self.config.proactive_cognitive.cooldown_seconds,
                on_event=lambda evt: self._emit_event(evt.get("type", ""), evt.get("data", {})),
            )
            self.proactive_loop.set_runtime(self)
            await self.proactive_loop.start()
            logger.info("proactive-cognitive-loop started (interval=%ss)", self.config.proactive_cognitive.interval_seconds)
```

**6c. `stop()`** — Insert after InitiativeEngine stop (after line 1249, before build dispatcher stop at line 1251):

```python
        # Stop Proactive Cognitive Loop (Phase 28b)
        if self.proactive_loop:
            await self.proactive_loop.stop()
            self.proactive_loop = None
```

### Part 7: Tests — NEW `tests/test_proactive.py`

~20 tests:

```python
"""Tests for Proactive Cognitive Loop (Phase 28b)."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.crew_profile import Rank
from probos.earned_agency import can_think_proactively, agency_from_rank, AgencyLevel
from probos.proactive import ProactiveCognitiveLoop
from probos.types import IntentMessage, IntentResult


class TestCanThinkProactively:
    """can_think_proactively() — agency gating for proactive thought."""

    def test_ensign_cannot_think_proactively(self):
        assert can_think_proactively(Rank.ENSIGN) is False

    def test_lieutenant_can_think_proactively(self):
        assert can_think_proactively(Rank.LIEUTENANT) is True

    def test_commander_can_think_proactively(self):
        assert can_think_proactively(Rank.COMMANDER) is True

    def test_senior_can_think_proactively(self):
        assert can_think_proactively(Rank.SENIOR) is True


class TestProactiveCognitiveLoopLifecycle:
    """Start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_creates_task(self):
        loop = ProactiveCognitiveLoop()
        loop.set_runtime(MagicMock())
        await loop.start()
        assert loop._task is not None
        await loop.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self):
        loop = ProactiveCognitiveLoop()
        loop.set_runtime(MagicMock())
        await loop.start()
        await loop.stop()
        assert loop._task is None

    @pytest.mark.asyncio
    async def test_double_start_is_idempotent(self):
        loop = ProactiveCognitiveLoop()
        loop.set_runtime(MagicMock())
        await loop.start()
        task1 = loop._task
        await loop.start()
        assert loop._task is task1
        await loop.stop()


def _make_mock_agent(agent_type="architect", agent_id="a1", alive=True):
    """Create a mock crew agent."""
    agent = MagicMock()
    agent.agent_type = agent_type
    agent.id = agent_id
    agent.is_alive = alive
    agent.handle_intent = AsyncMock()
    agent.callsign = agent_type.title()
    return agent


def _make_mock_runtime(agents=None, trust_scores=None, ward_room=True):
    """Create a mock runtime with agents and services."""
    rt = MagicMock()

    if agents is None:
        agents = [_make_mock_agent()]
    rt.registry.all.return_value = agents

    # Trust scores: default 0.7 (Commander)
    if trust_scores is None:
        trust_scores = {a.id: 0.7 for a in agents}
    rt.trust_network.get_score = MagicMock(side_effect=lambda aid: trust_scores.get(aid, 0.5))

    # _is_crew_agent: True for all
    rt._is_crew_agent = MagicMock(return_value=True)

    # Ward Room
    if ward_room:
        rt.ward_room = MagicMock()
        rt.ward_room.list_channels = AsyncMock(return_value=[
            MagicMock(id="ch1", channel_type="department", department="science", name="Science"),
            MagicMock(id="ch2", channel_type="ship", department="", name="All Hands"),
        ])
        rt.ward_room.create_thread = AsyncMock()
    else:
        rt.ward_room = None

    # Callsign registry
    rt.callsign_registry.get_callsign = MagicMock(return_value="Number One")

    # Episodic memory
    rt.episodic_memory = MagicMock()
    rt.episodic_memory.recall_for_agent = AsyncMock(return_value=[])

    # Bridge alerts
    rt.bridge_alerts = MagicMock()
    rt.bridge_alerts.get_recent_alerts = MagicMock(return_value=[])

    # Event log
    rt.event_log = MagicMock()
    rt.event_log.query = AsyncMock(return_value=[])

    return rt


class TestProactiveCognitiveLoopCycle:
    """_run_cycle() — agent iteration and filtering."""

    @pytest.mark.asyncio
    async def test_skips_non_crew_agents(self):
        agent = _make_mock_agent()
        rt = _make_mock_runtime(agents=[agent])
        rt._is_crew_agent.return_value = False

        loop = ProactiveCognitiveLoop()
        loop.set_runtime(rt)
        await loop._run_cycle()

        agent.handle_intent.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_dead_agents(self):
        agent = _make_mock_agent(alive=False)
        rt = _make_mock_runtime(agents=[agent])

        loop = ProactiveCognitiveLoop()
        loop.set_runtime(rt)
        await loop._run_cycle()

        agent.handle_intent.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_ensign_agents(self):
        """Trust < 0.5 → Ensign → no proactive thought."""
        agent = _make_mock_agent()
        rt = _make_mock_runtime(agents=[agent], trust_scores={agent.id: 0.3})

        loop = ProactiveCognitiveLoop()
        loop.set_runtime(rt)
        await loop._run_cycle()

        agent.handle_intent.assert_not_called()

    @pytest.mark.asyncio
    async def test_sends_intent_to_lieutenant(self):
        """Trust 0.5 → Lieutenant → proactive thought allowed."""
        agent = _make_mock_agent()
        agent.handle_intent.return_value = IntentResult(
            intent_id="x", agent_id=agent.id, success=True, result="[NO_RESPONSE]"
        )
        rt = _make_mock_runtime(agents=[agent], trust_scores={agent.id: 0.55})

        loop = ProactiveCognitiveLoop()
        loop.set_runtime(rt)
        await loop._run_cycle()

        agent.handle_intent.assert_called_once()
        call_args = agent.handle_intent.call_args[0][0]
        assert call_args.intent == "proactive_think"
        assert call_args.target_agent_id == agent.id

    @pytest.mark.asyncio
    async def test_respects_cooldown(self):
        """Agent in cooldown → skipped."""
        agent = _make_mock_agent()
        rt = _make_mock_runtime(agents=[agent])

        loop = ProactiveCognitiveLoop(cooldown=300.0)
        loop.set_runtime(rt)
        loop._last_proactive[agent.id] = time.monotonic()  # Just posted

        await loop._run_cycle()
        agent.handle_intent.assert_not_called()

    @pytest.mark.asyncio
    async def test_cooldown_expired_allows_think(self):
        """Cooldown expired → agent can think again."""
        agent = _make_mock_agent()
        agent.handle_intent.return_value = IntentResult(
            intent_id="x", agent_id=agent.id, success=True, result="[NO_RESPONSE]"
        )
        rt = _make_mock_runtime(agents=[agent])

        loop = ProactiveCognitiveLoop(cooldown=1.0)
        loop.set_runtime(rt)
        loop._last_proactive[agent.id] = time.monotonic() - 2.0  # Expired

        await loop._run_cycle()
        agent.handle_intent.assert_called_once()


class TestProactiveNoResponse:
    """[NO_RESPONSE] filtering — no WR post created."""

    @pytest.mark.asyncio
    async def test_no_response_skips_posting(self):
        agent = _make_mock_agent()
        agent.handle_intent.return_value = IntentResult(
            intent_id="x", agent_id=agent.id, success=True, result="[NO_RESPONSE]"
        )
        rt = _make_mock_runtime(agents=[agent])

        loop = ProactiveCognitiveLoop()
        loop.set_runtime(rt)
        await loop._run_cycle()

        rt.ward_room.create_thread.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_response_skips_posting(self):
        agent = _make_mock_agent()
        agent.handle_intent.return_value = IntentResult(
            intent_id="x", agent_id=agent.id, success=True, result=""
        )
        rt = _make_mock_runtime(agents=[agent])

        loop = ProactiveCognitiveLoop()
        loop.set_runtime(rt)
        await loop._run_cycle()

        rt.ward_room.create_thread.assert_not_called()

    @pytest.mark.asyncio
    async def test_failed_result_skips_posting(self):
        agent = _make_mock_agent()
        agent.handle_intent.return_value = IntentResult(
            intent_id="x", agent_id=agent.id, success=False, result="error"
        )
        rt = _make_mock_runtime(agents=[agent])

        loop = ProactiveCognitiveLoop()
        loop.set_runtime(rt)
        await loop._run_cycle()

        rt.ward_room.create_thread.assert_not_called()


class TestProactiveWardRoomPosting:
    """Meaningful responses → WR thread creation."""

    @pytest.mark.asyncio
    async def test_meaningful_response_creates_thread(self):
        agent = _make_mock_agent(agent_type="architect")
        agent.handle_intent.return_value = IntentResult(
            intent_id="x", agent_id=agent.id, success=True,
            result="I notice the builder's trust has been climbing steadily. Good sign."
        )
        rt = _make_mock_runtime(agents=[agent])

        loop = ProactiveCognitiveLoop()
        loop.set_runtime(rt)
        await loop._run_cycle()

        rt.ward_room.create_thread.assert_called_once()
        call_kwargs = rt.ward_room.create_thread.call_args[1]
        assert "[Observation]" in call_kwargs["title"]
        assert call_kwargs["author_id"] == agent.id

    @pytest.mark.asyncio
    async def test_posts_to_department_channel(self):
        """Architect → science department channel."""
        agent = _make_mock_agent(agent_type="architect")
        agent.handle_intent.return_value = IntentResult(
            intent_id="x", agent_id=agent.id, success=True,
            result="Interesting pattern in recent code analysis."
        )
        rt = _make_mock_runtime(agents=[agent])

        loop = ProactiveCognitiveLoop()
        loop.set_runtime(rt)

        with patch("probos.proactive.get_department", return_value="science"):
            await loop._run_cycle()

        call_kwargs = rt.ward_room.create_thread.call_args[1]
        assert call_kwargs["channel_id"] == "ch1"  # Science channel

    @pytest.mark.asyncio
    async def test_records_cooldown_after_post(self):
        agent = _make_mock_agent()
        agent.handle_intent.return_value = IntentResult(
            intent_id="x", agent_id=agent.id, success=True,
            result="Something noteworthy happened."
        )
        rt = _make_mock_runtime(agents=[agent])

        loop = ProactiveCognitiveLoop()
        loop.set_runtime(rt)
        await loop._run_cycle()

        assert agent.id in loop._last_proactive
        assert time.monotonic() - loop._last_proactive[agent.id] < 2.0

    @pytest.mark.asyncio
    async def test_no_ward_room_skips_cycle(self):
        """Ward Room disabled → entire cycle skipped."""
        agent = _make_mock_agent()
        rt = _make_mock_runtime(agents=[agent], ward_room=False)

        loop = ProactiveCognitiveLoop()
        loop.set_runtime(rt)
        await loop._run_cycle()

        agent.handle_intent.assert_not_called()


class TestProactiveContextGathering:
    """Context assembly from system services."""

    @pytest.mark.asyncio
    async def test_gathers_episodic_memories(self):
        from probos.types import Episode
        agent = _make_mock_agent()
        rt = _make_mock_runtime(agents=[agent])
        ep = Episode(user_input="test task", reflection="Handled successfully")
        rt.episodic_memory.recall_for_agent.return_value = [ep]

        loop = ProactiveCognitiveLoop()
        loop.set_runtime(rt)
        context = await loop._gather_context(agent, 0.7)

        assert "recent_memories" in context
        assert len(context["recent_memories"]) == 1
        assert context["recent_memories"][0]["reflection"] == "Handled successfully"

    @pytest.mark.asyncio
    async def test_gathers_bridge_alerts(self):
        agent = _make_mock_agent()
        rt = _make_mock_runtime(agents=[agent])
        alert = MagicMock()
        alert.severity.value = "advisory"
        alert.title = "Trust drop"
        alert.source = "vitals_monitor"
        rt.bridge_alerts.get_recent_alerts.return_value = [alert]

        loop = ProactiveCognitiveLoop()
        loop.set_runtime(rt)
        context = await loop._gather_context(agent, 0.7)

        assert "recent_alerts" in context
        assert len(context["recent_alerts"]) == 1

    @pytest.mark.asyncio
    async def test_gathers_system_events(self):
        agent = _make_mock_agent()
        rt = _make_mock_runtime(agents=[agent])
        rt.event_log.query.return_value = [
            {"category": "system", "event": "started", "agent_type": ""},
        ]

        loop = ProactiveCognitiveLoop()
        loop.set_runtime(rt)
        context = await loop._gather_context(agent, 0.7)

        assert "recent_events" in context
        assert len(context["recent_events"]) == 1

    @pytest.mark.asyncio
    async def test_handles_missing_services_gracefully(self):
        """If episodic_memory/bridge_alerts/event_log are None, context is empty."""
        agent = _make_mock_agent()
        rt = _make_mock_runtime(agents=[agent])
        rt.episodic_memory = None
        rt.bridge_alerts = None
        rt.event_log = None

        loop = ProactiveCognitiveLoop()
        loop.set_runtime(rt)
        context = await loop._gather_context(agent, 0.7)

        assert context == {}


class TestProactiveConfig:
    """ProactiveCognitiveConfig defaults."""

    def test_defaults(self):
        from probos.config import ProactiveCognitiveConfig
        cfg = ProactiveCognitiveConfig()
        assert cfg.enabled is False
        assert cfg.interval_seconds == 120.0
        assert cfg.cooldown_seconds == 300.0

    def test_system_config_has_proactive_cognitive(self):
        from probos.config import SystemConfig
        cfg = SystemConfig()
        assert hasattr(cfg, "proactive_cognitive")
        assert cfg.proactive_cognitive.enabled is False
```

## Test & Verify

```bash
uv run pytest tests/test_proactive.py -x -v                # targeted
uv run pytest tests/test_earned_agency.py -x -v             # earned agency regression
uv run pytest tests/test_ward_room.py -x -v                 # WR regression
uv run pytest tests/test_ward_room_agents.py -x -v          # WR agent routing
uv run pytest tests/ --tb=short -q                           # full Python regression
cd ui && npx vitest run --reporter=verbose 2>&1 | head -100  # Vitest
```

## What This Does NOT Change

- Agent cognitive lifecycle (perceive/decide/act/report — we're a caller, not modifier)
- Trust calculation or Earned Agency rules (only adds `can_think_proactively()`)
- Ward Room data model or thread/post schema
- Bridge Alerts
- DreamScheduler or dream consolidation
- InitiativeEngine (complementary — Initiative watches health signals, Proactive Loop enables agent-initiated thought)
- @mention routing or existing WR posting flow
- Standing Orders or system prompts
