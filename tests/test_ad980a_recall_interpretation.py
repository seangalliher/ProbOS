"""AD-980a (Agent self-interpretation epic, #910): reflective recall interpretation.

The meaning-making rung above the AD-979 metamemory layer: AD-979 made recall
*honest* (do I know this? how sure?); AD-980a makes it *meaningful* (what do I
make of it?). ``CognitiveAgent.interpret_recall`` runs an instructions-first LLM
pass over the agent's OWN recalled episodes and returns a first-person reading,
optionally stored as an agent-owned reflection episode so the interpretation is
itself recallable. Reuses the AD-721d ``propose_appearance`` reflection shape.

Honesty bound (AD-592): no episodes -> nothing to interpret -> ``None`` (never
invents); the stored episode is labeled ``[interpretation]`` + ``MemorySource.
REFLECTION``. Opt-in: ``None`` unless ``communications.recall_interpretation_
enabled`` is set (an extra LLM pass).

BF-287 discipline: a real ``CommunicationsConfig`` + real-but-fake recording
episodic memory and a scripted fake LLM client (NOT MagicMock).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.config import CommunicationsConfig
from probos.types import AnchorFrame, Episode, MemorySource


# --------------------------- real-but-fake substrate ---------------------------


class _FakeLLMResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class _ScriptedLLM:
    """Records the request and returns a canned interpretation (NOT MagicMock)."""

    def __init__(self, content: str = "These memories show a recurring pattern.") -> None:
        self._content = content
        self.requests: list = []

    async def complete(self, request, priority=None):
        self.requests.append(request)
        return _FakeLLMResponse(self._content)


class _RaisingLLM:
    async def complete(self, request, priority=None):
        raise RuntimeError("llm down")


class _RecordingEpisodic:
    def __init__(self) -> None:
        self.episodes: list = []

    async def store(self, episode) -> None:
        self.episodes.append(episode)


class _FakeCallsigns:
    def get_callsign(self, agent_type):
        return "Ezri" if agent_type == "counselor" else ""


def _make_agent(*, enabled: bool, llm, episodic=None):
    comm = CommunicationsConfig(recall_interpretation_enabled=enabled)
    runtime = SimpleNamespace(
        config=SimpleNamespace(communications=comm),
        callsign_registry=_FakeCallsigns(),
        episodic_memory=episodic,
    )
    # Construct a CognitiveAgent without the full pool machinery.
    agent = CognitiveAgent(
        agent_id="counselor.1",
        agent_type="counselor",
        instructions="You are the counselor.",
        llm_client=llm,
        runtime=runtime,
    )
    return agent


def _eps(*texts: str) -> list[Episode]:
    return [Episode(user_input=t) for t in texts]


# ------------------------------------ tests ------------------------------------


@pytest.mark.asyncio
async def test_disabled_returns_none():
    agent = _make_agent(enabled=False, llm=_ScriptedLLM())
    out = await agent.interpret_recall(_eps("I helped the away team debrief."))
    assert out is None


@pytest.mark.asyncio
async def test_no_episodes_returns_none_honest_noop():
    # Honesty by construction: nothing recalled -> nothing to interpret.
    agent = _make_agent(enabled=True, llm=_ScriptedLLM())
    assert await agent.interpret_recall([]) is None


@pytest.mark.asyncio
async def test_enabled_produces_interpretation():
    llm = _ScriptedLLM("I notice I keep returning to crew wellness after conflict.")
    agent = _make_agent(enabled=True, llm=llm)
    out = await agent.interpret_recall(
        _eps("Logged a wellness check after the bridge argument.",
             "Followed up with the ensign the next day."),
        store=False,
    )
    assert out == "I notice I keep returning to crew wellness after conflict."
    # The LLM saw the recalled material in its prompt.
    assert llm.requests
    assert "wellness check" in llm.requests[0].prompt


@pytest.mark.asyncio
async def test_llm_failure_returns_none():
    agent = _make_agent(enabled=True, llm=_RaisingLLM())
    out = await agent.interpret_recall(_eps("Something happened."))
    assert out is None


@pytest.mark.asyncio
async def test_interpretation_stored_as_agent_owned_reflection():
    episodic = _RecordingEpisodic()
    llm = _ScriptedLLM("A pattern of stepping in during crew stress.")
    agent = _make_agent(enabled=True, llm=llm, episodic=episodic)
    out = await agent.interpret_recall(
        _eps("Mediated a dispute in engineering."), store=True
    )
    assert out
    assert episodic.episodes, "the interpretation should be stored"
    ep = episodic.episodes[0]
    # Agent-owned (sovereign shard), labeled, and tagged as reflection.
    assert ep.agent_ids == [agent.id]
    assert ep.reflection.startswith("[interpretation]")
    assert "stepping in during crew stress" in ep.reflection
    assert ep.source == MemorySource.REFLECTION
    assert ep.outcomes[0]["kind"] == "recall_interpretation"
    # The interpretation is carried as the outcome response (passes should_store).
    assert "stepping in during crew stress" in ep.outcomes[0]["response"]


@pytest.mark.asyncio
async def test_store_false_does_not_persist():
    episodic = _RecordingEpisodic()
    agent = _make_agent(enabled=True, llm=_ScriptedLLM(), episodic=episodic)
    await agent.interpret_recall(_eps("A memory."), store=False)
    assert episodic.episodes == []


@pytest.mark.asyncio
async def test_focus_is_included_in_prompt():
    llm = _ScriptedLLM()
    agent = _make_agent(enabled=True, llm=llm)
    await agent.interpret_recall(
        _eps("The diplomatic mission to Rigel."), focus="my role in conflicts", store=False
    )
    assert "my role in conflicts" in llm.requests[0].prompt


@pytest.mark.asyncio
async def test_system_prompt_is_gap_regex_safe():
    # The instruction text must not trip the capability-gap detector (it would
    # otherwise be mistaken for a self-mod trigger).
    llm = _ScriptedLLM()
    agent = _make_agent(enabled=True, llm=llm)
    await agent.interpret_recall(_eps("An event."), store=False)
    req = llm.requests[0]
    assert _CAPABILITY_GAP_RE.search(req.system_prompt) is None
    assert _CAPABILITY_GAP_RE.search(req.prompt) is None


@pytest.mark.asyncio
async def test_reflection_only_episodes_are_usable():
    # Episodes whose content is in `reflection` (e.g. a group AD-977 episode)
    # are still interpretable — the method falls back to reflection text.
    llm = _ScriptedLLM("I tend to summarize for the room.")
    agent = _make_agent(enabled=True, llm=llm)
    ep = Episode(user_input="", reflection="Ezri said in group chat: let's regroup.")
    out = await agent.interpret_recall([ep], store=False)
    assert out
    assert "regroup" in llm.requests[0].prompt
