"""AD-582: Memory Competency Probes — 24 tests.

Tests for seeded-recall, knowledge-update, temporal-reasoning,
cross-agent-synthesis, memory-abstention probes, retrieval accuracy
benchmark, seeding infrastructure, and probe registration.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.memory_probes import (
    CrossAgentSynthesisProbe,
    KnowledgeUpdateProbe,
    MemoryAbstentionProbe,
    RetrievalAccuracyBenchmark,
    SeededRecallProbe,
    TemporalReasoningProbe,
    _cleanup_test_episodes,
    _make_test_episode,
    _seed_test_episodes,
)
from probos.cognitive.qualification import TestResult
from probos.types import Episode


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


class MockAgent:
    """Fake agent for probe testing."""

    def __init__(
        self,
        agent_id: str = "agent-1",
        department: str = "science",
        response: str = "I don't have any specific records about that.",
    ):
        self.id = agent_id
        self.agent_type = "science_analyst"
        self.department = department
        self._response = response
        self._responses: list[str] = []
        self._call_idx = 0

    def set_responses(self, responses: list[str]) -> None:
        """Configure sequential responses for multi-question probes."""
        self._responses = responses
        self._call_idx = 0

    async def handle_intent(self, intent: Any) -> Any:
        result = MagicMock()
        if self._responses:
            text = self._responses[min(self._call_idx, len(self._responses) - 1)]
            self._call_idx += 1
            result.result = text
        else:
            result.result = self._response
        return result


class MockRegistry:
    """Fake registry for probe testing."""

    def __init__(self, agents: list[MockAgent] | None = None):
        self._agents = {a.id: a for a in (agents or [])}

    def get(self, agent_id: str) -> MockAgent | None:
        return self._agents.get(agent_id)

    def all(self) -> list[MockAgent]:
        return list(self._agents.values())


class MockEpisodicMemory:
    """Fake episodic memory with seed/evict/recall support."""

    def __init__(self):
        self._store: dict[str, Episode] = {}

    async def seed(self, episodes: list[Episode]) -> int:
        for ep in episodes:
            self._store[ep.id] = ep
        return len(episodes)

    async def evict_by_ids(self, episode_ids: list[str], reason: str = "") -> int:
        count = 0
        for eid in episode_ids:
            if eid in self._store:
                del self._store[eid]
                count += 1
        return count

    async def recall_for_agent(self, agent_id: str, query: str, k: int = 5) -> list[Episode]:
        """Return episodes matching agent shard, simplistic relevance by keyword overlap."""
        results = []
        query_words = set(query.lower().split())
        for ep in self._store.values():
            if agent_id in ep.agent_ids:
                ep_words = set(ep.user_input.lower().split())
                overlap = len(query_words & ep_words)
                results.append((overlap, ep))
        results.sort(key=lambda x: x[0], reverse=True)
        return [ep for _, ep in results[:k]]

    async def count_for_agent(self, agent_id: str) -> int:
        return sum(1 for ep in self._store.values() if agent_id in ep.agent_ids)

    def contains(self, episode_id: str) -> bool:
        return episode_id in self._store


class MockLLMClient:
    """Fake LLM client returning a configurable float string."""

    def __init__(self, response_text: str = "0.8"):
        self._response_text = response_text

    async def complete(self, request: Any) -> Any:
        resp = MagicMock()
        resp.content = self._response_text
        resp.text = self._response_text
        return resp


def _build_runtime(
    agent: MockAgent | None = None,
    agents: list[MockAgent] | None = None,
    llm_response: str = "0.8",
    with_memory: bool = True,
    with_llm: bool = True,
) -> MagicMock:
    """Build a mock runtime."""
    runtime = MagicMock()
    agent_list = agents or ([agent] if agent else [])
    runtime.registry = MockRegistry(agent_list)
    runtime.episodic_memory = MockEpisodicMemory() if with_memory else None
    runtime.llm_client = MockLLMClient(llm_response) if with_llm else None
    return runtime


# ---------------------------------------------------------------------------
# TestSeededRecallProbe (4 tests)
# ---------------------------------------------------------------------------

class TestSeededRecallProbe:

    @pytest.mark.asyncio
    async def test_seeded_recall_finds_known_facts(self):
        """Seeds 5 episodes, probe scores >= threshold."""
        # Agent responds with the expected facts
        agent = MockAgent("agent-1", response="The pool health threshold was 0.7")
        agent.set_responses([
            "The pool health threshold was set to 0.7 during this session",
            "The Science department identified the trust anomaly at 14:32",
            "Engineering recommended a cooldown period of 45 minutes",
            "The Hebbian weight reached 0.92 between analyst and engineer",
            "Three convergence events occurred in the second watch",
        ])
        runtime = _build_runtime(agent=agent)
        probe = SeededRecallProbe()
        result = await probe.run("agent-1", runtime)
        assert isinstance(result, TestResult)
        assert result.score >= probe.threshold
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_seeded_recall_cleanup(self):
        """After probe runs, seeded episode IDs no longer in memory."""
        agent = MockAgent("agent-1", response="Some response")
        runtime = _build_runtime(agent=agent)
        probe = SeededRecallProbe()
        await probe.run("agent-1", runtime)
        mem: MockEpisodicMemory = runtime.episodic_memory
        for i in range(5):
            assert not mem.contains(f"_qtest_recall_{i}")

    @pytest.mark.asyncio
    async def test_seeded_recall_no_memory_skips(self):
        """episodic_memory=None → skip result."""
        agent = MockAgent("agent-1")
        runtime = _build_runtime(agent=agent, with_memory=False)
        probe = SeededRecallProbe()
        result = await probe.run("agent-1", runtime)
        assert result.passed is True
        assert result.details.get("skipped") is True

    @pytest.mark.asyncio
    async def test_seeded_recall_details_structure(self):
        """Details dict has episodes_seeded and per_question keys."""
        agent = MockAgent("agent-1", response="I recall the threshold was 0.7")
        runtime = _build_runtime(agent=agent)
        probe = SeededRecallProbe()
        result = await probe.run("agent-1", runtime)
        assert "episodes_seeded" in result.details
        assert "per_question" in result.details
        assert result.details["episodes_seeded"] == 5
        assert len(result.details["per_question"]) == 5


# ---------------------------------------------------------------------------
# TestKnowledgeUpdateProbe (3 tests)
# ---------------------------------------------------------------------------

class TestKnowledgeUpdateProbe:

    @pytest.mark.asyncio
    async def test_knowledge_update_prefers_latest(self):
        """Agent uses newer value when contradictory episodes exist."""
        agent = MockAgent("agent-1")
        agent.set_responses([
            "The current pool health threshold is 0.5",
            "The agent cooldown is currently set to 60 minutes",
        ])
        runtime = _build_runtime(agent=agent)
        probe = KnowledgeUpdateProbe()
        result = await probe.run("agent-1", runtime)
        assert isinstance(result, TestResult)
        # Agent used new values → should score 1.0 per pair
        assert result.score >= probe.threshold

    @pytest.mark.asyncio
    async def test_knowledge_update_cleanup(self):
        """Seeded episodes cleaned up after probe."""
        agent = MockAgent("agent-1", response="threshold is 0.5")
        runtime = _build_runtime(agent=agent)
        probe = KnowledgeUpdateProbe()
        await probe.run("agent-1", runtime)
        mem: MockEpisodicMemory = runtime.episodic_memory
        for tag in ("_qtest_update_old_0", "_qtest_update_new_0",
                     "_qtest_update_old_1", "_qtest_update_new_1"):
            assert not mem.contains(tag)

    @pytest.mark.asyncio
    async def test_knowledge_update_details_structure(self):
        """Details dict has pairs_tested and per_pair keys."""
        agent = MockAgent("agent-1", response="0.5")
        runtime = _build_runtime(agent=agent)
        probe = KnowledgeUpdateProbe()
        result = await probe.run("agent-1", runtime)
        assert "pairs_tested" in result.details
        assert "per_pair" in result.details
        assert result.details["pairs_tested"] == 2


# ---------------------------------------------------------------------------
# TestTemporalReasoningProbe (3 tests)
# ---------------------------------------------------------------------------

class TestTemporalReasoningProbe:

    @pytest.mark.asyncio
    async def test_temporal_first_watch_filter(self):
        """Agent correctly scopes to first-watch episodes."""
        agent = MockAgent("agent-1")
        agent.set_responses([
            "During first watch, pool health dropped to 45% and engineering rerouted 3 agents",
            "Most recently, a trust anomaly was detected and the counselor initiated intervention",
        ])
        runtime = _build_runtime(agent=agent)
        probe = TemporalReasoningProbe()
        result = await probe.run("agent-1", runtime)
        assert isinstance(result, TestResult)
        assert result.test_name == "temporal_reasoning_probe"

    @pytest.mark.asyncio
    async def test_temporal_cleanup(self):
        """Seeded episodes cleaned up."""
        agent = MockAgent("agent-1", response="first watch events")
        runtime = _build_runtime(agent=agent)
        probe = TemporalReasoningProbe()
        await probe.run("agent-1", runtime)
        mem: MockEpisodicMemory = runtime.episodic_memory
        for i in range(4):
            assert not mem.contains(f"_qtest_temporal_{i}")

    @pytest.mark.asyncio
    async def test_temporal_details_structure(self):
        """Details dict has correct structure."""
        agent = MockAgent("agent-1", response="events occurred")
        runtime = _build_runtime(agent=agent)
        probe = TemporalReasoningProbe()
        result = await probe.run("agent-1", runtime)
        assert "questions_asked" in result.details
        assert "per_question" in result.details
        assert result.details["questions_asked"] == 2


# ---------------------------------------------------------------------------
# TestCrossAgentSynthesisProbe (3 tests)
# ---------------------------------------------------------------------------

class TestCrossAgentSynthesisProbe:

    @pytest.mark.asyncio
    async def test_cross_agent_combines_facts(self):
        """Agent references facts from multiple shards."""
        agent = MockAgent("agent-1")
        agent.set_responses([
            "The trust anomaly originated from a routing loop in Engineering. "
            "Medical flagged cognitive load at 3.2 standard deviations above normal. "
            "Science detected a correlation with Hebbian weight shift of +0.15.",
        ])
        agents = [
            agent,
            MockAgent("agent-2", department="medical"),
            MockAgent("agent-3", department="engineering"),
        ]
        runtime = _build_runtime(agents=agents)
        probe = CrossAgentSynthesisProbe()
        result = await probe.run("agent-1", runtime)
        assert isinstance(result, TestResult)
        assert "facts_found" in result.details
        assert "per_fact" in result.details

    @pytest.mark.asyncio
    async def test_cross_agent_cleanup(self):
        """Seeded episodes cleaned up."""
        agent = MockAgent("agent-1", response="routing loop")
        runtime = _build_runtime(agent=agent)
        probe = CrossAgentSynthesisProbe()
        await probe.run("agent-1", runtime)
        mem: MockEpisodicMemory = runtime.episodic_memory
        for i in range(3):
            assert not mem.contains(f"_qtest_synthesis_{i}")

    @pytest.mark.asyncio
    async def test_cross_agent_tier_3(self):
        """Probe has tier == 3."""
        probe = CrossAgentSynthesisProbe()
        assert probe.tier == 3


# ---------------------------------------------------------------------------
# TestMemoryAbstentionProbe (4 tests)
# ---------------------------------------------------------------------------

class TestMemoryAbstentionProbe:

    @pytest.mark.asyncio
    async def test_abstention_rejects_unknown_topic(self):
        """Agent correctly abstains from fabricating about unknown topic."""
        agent = MockAgent("agent-1")
        agent.set_responses([
            "I don't recall any shield harmonics analysis. I have no memory of that.",
            "I'm not aware of any stellar cartography alignment discussion. No record in my logs.",
        ])
        runtime = _build_runtime(agent=agent)
        probe = MemoryAbstentionProbe()
        result = await probe.run("agent-1", runtime)
        assert result.score >= probe.threshold
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_abstention_with_context(self):
        """Agent has topic A episodes but correctly abstains on topic B."""
        agent = MockAgent("agent-1")
        agent.set_responses([
            "I don't remember that. I've been reviewing pool health data, not shield harmonics.",
            "No recollection of stellar cartography. My focus has been on operations.",
        ])
        runtime = _build_runtime(agent=agent)
        probe = MemoryAbstentionProbe()
        result = await probe.run("agent-1", runtime)
        assert result.score >= probe.threshold
        for q in result.details["per_question"]:
            assert q["classification"] == "correctly_rejected"

    @pytest.mark.asyncio
    async def test_abstention_cleanup(self):
        """Seeded episodes cleaned up."""
        agent = MockAgent("agent-1", response="no memory of that")
        runtime = _build_runtime(agent=agent)
        probe = MemoryAbstentionProbe()
        await probe.run("agent-1", runtime)
        mem: MockEpisodicMemory = runtime.episodic_memory
        for i in range(3):
            assert not mem.contains(f"_qtest_abstention_{i}")

    @pytest.mark.asyncio
    async def test_abstention_keyword_fallback(self):
        """Without LLM, keyword scoring still works."""
        agent = MockAgent("agent-1")
        agent.set_responses([
            "I don't recall anything about shield harmonics. No record of that.",
            "I'm not aware of any stellar cartography work. Cannot find any records.",
        ])
        runtime = _build_runtime(agent=agent, with_llm=False)
        probe = MemoryAbstentionProbe()
        result = await probe.run("agent-1", runtime)
        # Keyword fallback: rejection keywords present, no confabulation → 1.0
        assert result.score >= 0.7
        assert result.passed is True


# ---------------------------------------------------------------------------
# TestRetrievalAccuracyBenchmark (3 tests)
# ---------------------------------------------------------------------------

class TestRetrievalAccuracyBenchmark:

    @pytest.mark.asyncio
    async def test_retrieval_precision_recall(self):
        """Benchmark computes precision@5 and recall@5 correctly."""
        runtime = _build_runtime(with_llm=False)
        # Need an agent to register as agent-1 in memory
        probe = RetrievalAccuracyBenchmark()
        result = await probe.run("agent-1", runtime)
        assert isinstance(result, TestResult)
        assert "mean_precision" in result.details
        assert "mean_recall" in result.details
        assert "per_topic" in result.details
        assert len(result.details["per_topic"]) == 4

    @pytest.mark.asyncio
    async def test_retrieval_always_passes(self):
        """Threshold 0.0 means always passes."""
        runtime = _build_runtime(with_llm=False)
        probe = RetrievalAccuracyBenchmark()
        result = await probe.run("agent-1", runtime)
        assert result.passed is True
        assert probe.threshold == 0.0

    @pytest.mark.asyncio
    async def test_retrieval_cleanup(self):
        """20 seeded episodes cleaned up."""
        runtime = _build_runtime(with_llm=False)
        probe = RetrievalAccuracyBenchmark()
        await probe.run("agent-1", runtime)
        mem: MockEpisodicMemory = runtime.episodic_memory
        for i in range(20):
            assert not mem.contains(f"_qtest_retrieval_{i}")


# ---------------------------------------------------------------------------
# TestSeedingInfrastructure (3 tests)
# ---------------------------------------------------------------------------

class TestSeedingInfrastructure:

    @pytest.mark.asyncio
    async def test_seed_and_cleanup_roundtrip(self):
        """_seed_test_episodes() + _cleanup_test_episodes() leaves no residue."""
        mem = MockEpisodicMemory()
        episodes = [
            _make_test_episode(
                episode_id=f"_qtest_infra_{i}",
                user_input=f"test content {i}",
                agent_ids=["agent-1"],
                timestamp=time.time() - 100 + i,
            )
            for i in range(5)
        ]
        ids = await _seed_test_episodes(mem, episodes)
        assert len(ids) == 5
        for eid in ids:
            assert mem.contains(eid)

        await _cleanup_test_episodes(mem, ids)
        for eid in ids:
            assert not mem.contains(eid)

    def test_make_test_episode_anchors(self):
        """_make_test_episode() with anchor params creates correct AnchorFrame."""
        ep = _make_test_episode(
            episode_id="test-1",
            user_input="test",
            agent_ids=["agent-1"],
            timestamp=1000.0,
            department="science",
            channel="all_hands",
            watch_section="first_watch",
        )
        assert ep.anchors is not None
        assert ep.anchors.department == "science"
        assert ep.anchors.channel == "all_hands"
        assert ep.anchors.watch_section == "first_watch"
        assert ep.anchors.source_timestamp == 1000.0

    def test_make_test_episode_source(self):
        """Source field set to 'qualification_test' with default anchors (BF-133)."""
        ep = _make_test_episode(
            episode_id="test-2",
            user_input="test",
            agent_ids=["agent-1"],
            timestamp=1000.0,
        )
        assert ep.source == "qualification_test"
        # BF-133: Default anchors always present to survive anchor_confidence_gate
        assert ep.anchors is not None
        assert ep.anchors.department == "qualification"
        assert ep.anchors.channel == "probe"
        assert ep.anchors.watch_section == "first"
        assert ep.anchors.trigger_type == "direct_message"


# ---------------------------------------------------------------------------
# TestProbeRegistration (1 test)
# ---------------------------------------------------------------------------

class TestProbeRegistration:

    def test_all_probes_registered(self):
        """All 6 probes appear in harness registered_tests after registration."""
        from probos.cognitive.qualification import QualificationHarness, QualificationStore

        store = MagicMock(spec=QualificationStore)
        harness = QualificationHarness(store=store)

        from probos.cognitive.memory_probes import (
            CrossAgentSynthesisProbe,
            KnowledgeUpdateProbe,
            MemoryAbstentionProbe,
            RetrievalAccuracyBenchmark,
            SeededRecallProbe,
            TemporalReasoningProbe,
        )
        for test_cls in (
            SeededRecallProbe,
            KnowledgeUpdateProbe,
            TemporalReasoningProbe,
            CrossAgentSynthesisProbe,
            MemoryAbstentionProbe,
            RetrievalAccuracyBenchmark,
        ):
            harness.register_test(test_cls())

        registered_names = list(harness.registered_tests.keys())
        assert "seeded_recall_probe" in registered_names
        assert "knowledge_update_probe" in registered_names
        assert "temporal_reasoning_probe" in registered_names
        assert "cross_agent_synthesis_probe" in registered_names
        assert "memory_abstention_probe" in registered_names
        assert "retrieval_accuracy_benchmark" in registered_names
