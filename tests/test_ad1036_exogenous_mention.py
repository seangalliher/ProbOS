"""AD-1036: tests for the live exogenous @mention arousal pilot (mention pilot, epic #983).

BF-287 discipline: real objects at the substrate boundary — a real ``CognitiveAgent`` (via
the AD-1028 golden builder), a real ``AttentionFaculty`` composed on its spine, and a real
``SystemConfig``/``AttentionConfig``; NO ``MagicMock`` where an attribute typo could pass.

asyncio_mode="auto" (pyproject.toml): async tests carry NO ``@pytest.mark.asyncio``
marker and no ``asyncio.run`` is used.

The wiring under test is Pattern B (layer-safe): the agent SELF-AROUSES at its OWN
``perceive`` intake — a between-turns @mention (``params["was_mentioned"]``, set per-agent
at ``ward_room_router.py``) raises the agent's faculty-local arousal zone for the next turn.
No lower layer (router/bridge/consensus/gossip) reaches into the agent. The insert is
double-gated default-OFF: guarded by ``was_mentioned`` AND ``on_exogenous_event`` itself
no-ops unless ``attention.enabled`` ∧ ``arousal_enabled`` (both default-OFF).

Coverage maps to the AD-1036 design decisions (DD-1..DD-6):
* DD-1 default-OFF byte-identical ⇒ arousal OFF + was_mentioned ⇒ zone stays GREEN;
* DD-2 mention arouses ON ⇒ arousal ON + was_mentioned ⇒ zone == AMBER (mention→AMBER);
* DD-3 not-mentioned no-op ⇒ arousal ON + NOT mentioned ⇒ zone stays GREEN;
* DD-4 single-fire ⇒ one ``perceive`` ⇒ exactly one ``on_exogenous_event("mention")``;
* DD-5 non-mention intent ⇒ an intent with no ``was_mentioned`` param ⇒ no arousal;
* DD-6 source guard ⇒ ``perceive`` contains the was_mentioned-guarded mention call.
"""
from __future__ import annotations

import inspect
from typing import Any

from probos.cognitive.attention_faculty import AttentionFaculty
from probos.cognitive.circuit_breaker import CognitiveZone
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.config import SystemConfig
from probos.types import IntentMessage
from tests.fixtures.ad1028_golden._capture_golden import make_dm_agent


# ---------------------------------------------------------------------------
# Test doubles + helpers (real small objects — BF-287)
# ---------------------------------------------------------------------------


class _Rt:
    """Minimal real runtime stand-in exposing a real ``SystemConfig`` (mirrors AD-1035)."""

    def __init__(self, config: SystemConfig) -> None:
        self.config = config


class _SpyAgent(CognitiveAgent):
    """A real ``CognitiveAgent`` subclass that records each ``on_exogenous_event`` call.

    A real subclass (NOT a ``MagicMock``) so the override delegates to the genuine
    gated boundary — the counter proves the call shape (event_type + arity), and the
    super() call preserves the real default-OFF / faculty-forward behavior.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.exogenous_calls: list[str] = []

    def on_exogenous_event(
        self, event_type: str, *, severity: str | None = None, **payload: Any
    ) -> None:
        self.exogenous_calls.append(event_type)
        super().on_exogenous_event(event_type, severity=severity, **payload)


def _config(*, arousal_enabled: bool) -> SystemConfig:
    """A real ``SystemConfig`` with attention ON (faculty composes) + the arousal flag."""
    cfg = SystemConfig()
    cfg.memory.attention.enabled = True
    cfg.memory.attention.arousal_enabled = arousal_enabled
    return cfg


def _aroused_agent(*, arousal_enabled: bool) -> CognitiveAgent:
    """Real golden ``CognitiveAgent`` with a real ``AttentionFaculty`` composed on its spine."""
    agent = make_dm_agent()
    agent._runtime = _Rt(_config(arousal_enabled=arousal_enabled))
    agent._compose_organs()  # composes the AttentionFaculty (attention.enabled=True)
    return agent


def _spy_agent(*, arousal_enabled: bool) -> _SpyAgent:
    """A real ``_SpyAgent`` built like the golden DM agent, with the faculty composed."""
    agent = _SpyAgent(agent_id="ad1036-spy", instructions="test")
    agent.callsign = "Tester"
    agent.agent_type = "tester"
    agent._working_memory = None
    agent._runtime = _Rt(_config(arousal_enabled=arousal_enabled))
    agent._compose_organs()
    return agent


def _mention_intent(*, was_mentioned: bool = True) -> IntentMessage:
    """A real ward-room intent carrying the per-agent ``was_mentioned`` param."""
    return IntentMessage(
        intent="ward_room_notification",
        params={"was_mentioned": was_mentioned, "text": "Scotty, status?"},
    )


def _faculty(agent: CognitiveAgent) -> AttentionFaculty:
    """The composed ``AttentionFaculty`` (real object) — fails loudly if not composed."""
    organ = agent._spine.get_organ("attention")
    assert isinstance(organ, AttentionFaculty)
    return organ


# ---------------------------------------------------------------------------
# DD-1: default-OFF byte-identical — arousal OFF + was_mentioned ⇒ zone stays GREEN
# ---------------------------------------------------------------------------


async def test_dd1_arousal_off_mention_stays_green() -> None:
    # Faculty IS composed (attention.enabled), but arousal is OFF: even a mention must
    # NOT reconfigure the zone — proving the second gate (arousal_enabled) holds.
    agent = _aroused_agent(arousal_enabled=False)
    faculty = _faculty(agent)
    assert faculty.arousal_zone == CognitiveZone.GREEN
    await agent.perceive(_mention_intent(was_mentioned=True))
    assert faculty.arousal_zone == CognitiveZone.GREEN


def test_dd1_systemconfig_default_arousal_is_off() -> None:
    assert SystemConfig().memory.attention.arousal_enabled is False


# ---------------------------------------------------------------------------
# DD-2: mention arouses ON — arousal ON + was_mentioned ⇒ zone == AMBER
# ---------------------------------------------------------------------------


async def test_dd2_mention_arouses_to_amber_when_on() -> None:
    agent = _aroused_agent(arousal_enabled=True)
    faculty = _faculty(agent)
    assert faculty.arousal_zone == CognitiveZone.GREEN
    await agent.perceive(_mention_intent(was_mentioned=True))
    assert faculty.arousal_zone == CognitiveZone.AMBER


# ---------------------------------------------------------------------------
# DD-3: not-mentioned no-op — arousal ON + NOT mentioned ⇒ zone stays GREEN
# ---------------------------------------------------------------------------


async def test_dd3_not_mentioned_no_arousal() -> None:
    agent = _aroused_agent(arousal_enabled=True)
    faculty = _faculty(agent)
    await agent.perceive(_mention_intent(was_mentioned=False))
    assert faculty.arousal_zone == CognitiveZone.GREEN


# ---------------------------------------------------------------------------
# DD-4: single-fire — one perceive ⇒ exactly one on_exogenous_event("mention")
# ---------------------------------------------------------------------------


async def test_dd4_single_perceive_fires_exactly_one_mention() -> None:
    agent = _spy_agent(arousal_enabled=True)
    await agent.perceive(_mention_intent(was_mentioned=True))
    assert agent.exogenous_calls == ["mention"]
    # And the real boundary still aroused (super() ran, not just the counter).
    assert _faculty(agent).arousal_zone == CognitiveZone.AMBER


async def test_dd4_not_mentioned_fires_zero() -> None:
    agent = _spy_agent(arousal_enabled=True)
    await agent.perceive(_mention_intent(was_mentioned=False))
    assert agent.exogenous_calls == []


# ---------------------------------------------------------------------------
# DD-5: non-mention intent — an intent with no was_mentioned param ⇒ no arousal
# ---------------------------------------------------------------------------


async def test_dd5_non_mention_intent_no_arousal() -> None:
    agent = _aroused_agent(arousal_enabled=True)
    faculty = _faculty(agent)
    await agent.perceive(IntentMessage(intent="proactive_think", params={}))
    assert faculty.arousal_zone == CognitiveZone.GREEN


# ---------------------------------------------------------------------------
# DD-6: source guard — perceive contains the was_mentioned-guarded mention call
# ---------------------------------------------------------------------------


def test_dd6_perceive_source_has_guarded_mention_call() -> None:
    src = inspect.getsource(CognitiveAgent.perceive)
    assert 'on_exogenous_event("mention")' in src
    # The call is GUARDED by the was_mentioned check (not unconditional).
    assert 'observation.get("params", {}).get("was_mentioned", False)' in src
