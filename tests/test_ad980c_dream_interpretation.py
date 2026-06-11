"""AD-980c (Agent self-interpretation epic, #912): the dream-interpretation loop.

The novel sleep->dream->wake->interpret loop. AD-980b gives a dream a dreamer
(per-agent reflection episodes); AD-980c lets the agent interpret ITS OWN dream
and store the interpretation as an agent-owned episode that feeds its self-model.
``CognitiveAgent.interpret_own_dream`` gathers the agent's recent
MemorySource.REFLECTION episodes (the dreams) and runs the AD-980a interpretation
engine over them.

Honesty-bounded (AD-592): no dreams -> nothing to interpret -> None. Opt-in:
None unless ``communications.dream_interpretation_enabled``.

BF-287 discipline: real ``CommunicationsConfig`` + a real-but-fake episodic stub
exposing ``recent_for_agent`` / ``store`` + a scripted fake LLM (NOT MagicMock).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.config import CommunicationsConfig
from probos.types import Episode, MemorySource


class _FakeLLMResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class _ScriptedLLM:
    def __init__(self, content: str = "I see I keep returning to crew wellness.") -> None:
        self._content = content
        self.requests: list = []

    async def complete(self, request, priority=None):
        self.requests.append(request)
        return _FakeLLMResponse(self._content)


class _DreamEpisodic:
    """Real-but-fake episodic store: returns a scripted recency window from
    recent_for_agent and records stored episodes."""

    def __init__(self, recent: list[Episode]) -> None:
        self._recent = recent
        self.stored: list = []

    async def recent_for_agent(self, agent_id, k=5):
        return list(self._recent)

    async def store(self, episode):
        self.stored.append(episode)


class _FakeCallsigns:
    def get_callsign(self, agent_type):
        return "Ezri" if agent_type == "counselor" else ""


def _dream(text: str) -> Episode:
    return Episode(
        user_input=f"[Reflection] {text}",
        reflection=f"[Reflection] {text}",
        source=MemorySource.REFLECTION,
    )


def _normal(text: str) -> Episode:
    return Episode(user_input=text, source=MemorySource.DIRECT)


def _make_agent(*, enabled: bool, llm, recent):
    comm = CommunicationsConfig(dream_interpretation_enabled=enabled)
    episodic = _DreamEpisodic(recent)
    runtime = SimpleNamespace(
        config=SimpleNamespace(communications=comm),
        callsign_registry=_FakeCallsigns(),
        episodic_memory=episodic,
    )
    agent = CognitiveAgent(
        agent_id="counselor.1",
        agent_type="counselor",
        instructions="You are the counselor.",
        llm_client=llm,
        runtime=runtime,
    )
    return agent, episodic


@pytest.mark.asyncio
async def test_disabled_returns_none():
    agent, _ = _make_agent(enabled=False, llm=_ScriptedLLM(), recent=[_dream("a pattern")])
    assert await agent.interpret_own_dream() is None


@pytest.mark.asyncio
async def test_no_dreams_returns_none():
    # Recency window has only non-reflection episodes -> no dream to interpret.
    agent, _ = _make_agent(
        enabled=True, llm=_ScriptedLLM(), recent=[_normal("a task"), _normal("another")]
    )
    assert await agent.interpret_own_dream() is None


@pytest.mark.asyncio
async def test_empty_window_returns_none():
    agent, _ = _make_agent(enabled=True, llm=_ScriptedLLM(), recent=[])
    assert await agent.interpret_own_dream() is None


@pytest.mark.asyncio
async def test_interprets_own_dream_and_stores():
    llm = _ScriptedLLM("My dreams show I stabilize the crew after conflict.")
    agent, episodic = _make_agent(
        enabled=True,
        llm=llm,
        recent=[
            _dream("success cluster: counselor mediated 5 disputes"),
            _normal("a routine log"),
            _dream("convergence on crew morale with ops"),
        ],
    )
    out = await agent.interpret_own_dream()
    assert out == "My dreams show I stabilize the crew after conflict."
    # Only the REFLECTION (dream) episodes reached the interpretation prompt.
    prompt = llm.requests[0].prompt
    assert "mediated 5 disputes" in prompt
    assert "crew morale" in prompt
    assert "a routine log" not in prompt
    # The interpretation was stored as an agent-owned reflection.
    assert episodic.stored
    ep = episodic.stored[0]
    assert ep.agent_ids == [agent.id]
    assert ep.reflection.startswith("[interpretation]")
    assert ep.source == MemorySource.REFLECTION


@pytest.mark.asyncio
async def test_dream_interpretation_focus_in_prompt():
    llm = _ScriptedLLM()
    agent, _ = _make_agent(enabled=True, llm=llm, recent=[_dream("a pattern about latency")])
    await agent.interpret_own_dream()
    # The dream-specific focus is injected.
    assert "reveal about how you work" in llm.requests[0].prompt


@pytest.mark.asyncio
async def test_no_llm_returns_none():
    agent, _ = _make_agent(enabled=True, llm=None, recent=[_dream("a pattern")])
    assert await agent.interpret_own_dream() is None


@pytest.mark.asyncio
async def test_k_limits_dreams_interpreted():
    llm = _ScriptedLLM()
    dreams = [_dream(f"dream number {i}") for i in range(10)]
    agent, _ = _make_agent(enabled=True, llm=llm, recent=dreams)
    await agent.interpret_own_dream(k=3)
    # At most k dreams appear in the prompt (numbered list 1..3).
    prompt = llm.requests[0].prompt
    assert "1. " in prompt and "3. " in prompt
    assert "4. " not in prompt
