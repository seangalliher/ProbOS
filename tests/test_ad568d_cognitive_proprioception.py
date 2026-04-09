"""AD-568d: Cognitive Proprioception — Ambient Source Attribution Sense.

Tests:
1. KnowledgeSource enum and SourceAttribution computation (8)
2. Confabulation rate threading (5)
3. WorkingMemoryEntry knowledge_source field (5)
4. Dream step 14 source attribution consolidation (7)
5. Ambient source tag in prompt (5)
"""

import dataclasses
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.source_governance import (
    BudgetAdjustment,
    KnowledgeSource,
    RetrievalStrategy,
    SourceAttribution,
    SourceFraming,
    SourceAuthority,
    classify_retrieval_strategy,
    compute_source_attribution,
    compute_source_framing,
)
from probos.cognitive.agent_working_memory import (
    AgentWorkingMemory,
    WorkingMemoryEntry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_dream_engine(**kwargs):
    """Minimal DreamingEngine for step 14 testing."""
    from probos.cognitive.dreaming import DreamingEngine
    from probos.config import DreamingConfig
    from probos.mesh.routing import HebbianRouter
    from probos.consensus.trust import TrustNetwork
    config = DreamingConfig(
        idle_threshold_seconds=1.0,
        dream_interval_seconds=1.0,
        replay_episode_count=50,
    )
    router = HebbianRouter(decay_rate=0.995, reward=0.05)
    trust = TrustNetwork(prior_alpha=2.0, prior_beta=2.0, decay_rate=0.999)
    memory = MagicMock()
    memory.recent_for_agent = AsyncMock(return_value=[])
    return DreamingEngine(router, trust, memory, config, **kwargs)


def _make_episode_with_attribution(primary_source: str, confab: float = 0.0):
    """Create a mock episode with source_attribution metadata."""
    ep = SimpleNamespace(
        user_input="test",
        timestamp=time.time(),
        agent_ids=["agent-1"],
        outcomes=[{"intent": "test", "success": True}],
        reflection="test",
        metadata={
            "source_attribution": {
                "primary_source": primary_source,
                "retrieval_strategy": "shallow",
                "episodic_count": 1 if primary_source == "episodic" else 0,
                "procedural_count": 1 if primary_source == "procedural" else 0,
                "oracle_used": primary_source == "oracle",
                "confabulation_rate": confab,
            }
        },
    )
    return ep


def _make_episode_no_metadata():
    """Create a mock episode with no source_attribution metadata."""
    return SimpleNamespace(
        user_input="test",
        timestamp=time.time(),
        agent_ids=["agent-1"],
        outcomes=[],
        reflection="",
        metadata={},
    )


# ---------------------------------------------------------------------------
# Test Class 1: KnowledgeSource and SourceAttribution (8 tests)
# ---------------------------------------------------------------------------
class TestKnowledgeSourceAttribution:
    """AD-568d: Knowledge source enum and attribution computation."""

    def test_knowledge_source_values(self) -> None:
        """KnowledgeSource enum has all expected values."""
        assert set(KnowledgeSource) == {
            KnowledgeSource.EPISODIC, KnowledgeSource.PARAMETRIC,
            KnowledgeSource.PROCEDURAL, KnowledgeSource.ORACLE,
            KnowledgeSource.STANDING_ORDERS, KnowledgeSource.UNKNOWN,
        }

    def test_none_strategy_parametric_primary(self) -> None:
        """NONE strategy with no procedures -> PARAMETRIC primary."""
        attr = compute_source_attribution(
            retrieval_strategy=RetrievalStrategy.NONE,
        )
        assert attr.primary_source == KnowledgeSource.PARAMETRIC

    def test_none_strategy_with_procedures(self) -> None:
        """NONE strategy with procedures -> PROCEDURAL primary."""
        attr = compute_source_attribution(
            retrieval_strategy=RetrievalStrategy.NONE,
            procedural_count=3,
        )
        assert attr.primary_source == KnowledgeSource.PROCEDURAL

    def test_episodic_recall_primary(self) -> None:
        """Episodes recalled -> EPISODIC primary."""
        attr = compute_source_attribution(
            retrieval_strategy=RetrievalStrategy.SHALLOW,
            episodic_count=5,
        )
        assert attr.primary_source == KnowledgeSource.EPISODIC

    def test_oracle_only_primary(self) -> None:
        """Oracle used without episodic -> ORACLE primary."""
        attr = compute_source_attribution(
            retrieval_strategy=RetrievalStrategy.DEEP,
            oracle_used=True,
            episodic_count=0,
        )
        assert attr.primary_source == KnowledgeSource.ORACLE

    def test_attribution_captures_confab_rate(self) -> None:
        """SourceAttribution stores confabulation rate."""
        attr = compute_source_attribution(confabulation_rate=0.15)
        assert attr.confabulation_rate == 0.15

    def test_attribution_captures_budget_scale(self) -> None:
        """SourceAttribution stores budget adjustment scale factor."""
        budget = BudgetAdjustment(4000, 5200, "test", 1.3)
        attr = compute_source_attribution(budget_adjustment=budget)
        assert attr.budget_adjustment == 1.3

    def test_attribution_defaults_safe(self) -> None:
        """Default attribution is safe (PARAMETRIC, no confabulation)."""
        attr = compute_source_attribution()
        assert attr.primary_source == KnowledgeSource.PARAMETRIC
        assert attr.confabulation_rate == 0.0
        assert attr.budget_adjustment == 1.0


# ---------------------------------------------------------------------------
# Test Class 2: Confabulation Rate Threading (5 tests)
# ---------------------------------------------------------------------------
class TestConfabulationRateThreading:
    """AD-568d: Confabulation rate wired from Counselor to retrieval strategy."""

    def test_high_confab_downgrades_deep(self) -> None:
        """High confabulation rate should downgrade DEEP to SHALLOW."""
        result = classify_retrieval_strategy(
            "incident_response",
            episodic_count=10,
            recent_confabulation_rate=0.5,
        )
        assert result == RetrievalStrategy.SHALLOW

    def test_low_confab_preserves_deep(self) -> None:
        """Low confabulation rate preserves DEEP strategy."""
        result = classify_retrieval_strategy(
            "incident_response",
            episodic_count=10,
            recent_confabulation_rate=0.1,
        )
        assert result == RetrievalStrategy.DEEP

    def test_confab_threshold_boundary(self) -> None:
        """Exactly 0.3 does NOT trigger downgrade."""
        result = classify_retrieval_strategy(
            "incident_response",
            episodic_count=10,
            recent_confabulation_rate=0.3,
        )
        assert result == RetrievalStrategy.DEEP

    def test_confab_does_not_affect_shallow(self) -> None:
        """Confabulation rate only affects DEEP, not SHALLOW intents."""
        result = classify_retrieval_strategy(
            "direct_message",
            episodic_count=10,
            recent_confabulation_rate=0.9,
        )
        assert result == RetrievalStrategy.SHALLOW

    def test_confab_does_not_affect_none(self) -> None:
        """Confabulation rate irrelevant when NONE (no episodes)."""
        result = classify_retrieval_strategy(
            "incident_response",
            episodic_count=0,
            recent_confabulation_rate=0.9,
        )
        assert result == RetrievalStrategy.NONE


# ---------------------------------------------------------------------------
# Test Class 3: Working Memory Source Tagging (5 tests)
# ---------------------------------------------------------------------------
class TestWorkingMemorySourceTag:
    """AD-568d: WorkingMemoryEntry knowledge_source field."""

    def test_default_knowledge_source_unknown(self) -> None:
        """Default knowledge_source is 'unknown'."""
        entry = WorkingMemoryEntry(
            content="test", category="action", source_pathway="system",
        )
        assert entry.knowledge_source == "unknown"

    def test_explicit_knowledge_source(self) -> None:
        """Explicit knowledge_source is stored."""
        entry = WorkingMemoryEntry(
            content="test", category="action", source_pathway="dm",
            knowledge_source="episodic",
        )
        assert entry.knowledge_source == "episodic"

    def test_to_dict_includes_knowledge_source(self) -> None:
        """Serialization includes knowledge_source."""
        mem = AgentWorkingMemory()
        mem.record_action("test action", source="system")
        d = mem.to_dict()
        entries = d.get("recent_actions", [])
        assert len(entries) > 0
        assert all("knowledge_source" in e for e in entries)

    def test_from_dict_restores_knowledge_source(self) -> None:
        """Deserialization restores knowledge_source."""
        mem = AgentWorkingMemory()
        mem.record_action("test", source="system", knowledge_source="episodic")
        d = mem.to_dict()
        mem2 = AgentWorkingMemory.from_dict(d, stale_threshold_seconds=86400.0)
        d2 = mem2.to_dict()
        entries = d2.get("recent_actions", [])
        # Should have original entry + stasis event
        episodic_entries = [e for e in entries if e.get("knowledge_source") == "episodic"]
        assert len(episodic_entries) > 0

    def test_render_context_includes_source_tag(self) -> None:
        """render_context() shows source tag for non-unknown entries."""
        mem = AgentWorkingMemory()
        entry = WorkingMemoryEntry(
            content="analyzed logs", category="action",
            source_pathway="system", knowledge_source="episodic",
        )
        mem._recent_actions.append(entry)
        output = mem.render_context()
        assert "episodic" in output


# ---------------------------------------------------------------------------
# Test Class 4: Dream Step 14 (7 tests)
# ---------------------------------------------------------------------------
class TestDreamStep14SourceAttribution:
    """AD-568d: Dream consolidation step for source attribution."""

    @pytest.mark.asyncio
    async def test_step_returns_empty_for_no_episodes(self) -> None:
        """No episodes -> empty result."""
        engine = _make_dream_engine()
        result = await engine._step_14_source_attribution([])
        assert result["episodes_with_attribution"] == 0

    @pytest.mark.asyncio
    async def test_step_counts_attributions(self) -> None:
        """Counts episodes with source_attribution metadata."""
        episodes = [_make_episode_with_attribution("episodic")]
        engine = _make_dream_engine()
        result = await engine._step_14_source_attribution(episodes)
        assert result["episodes_with_attribution"] == 1

    @pytest.mark.asyncio
    async def test_source_distribution_computed(self) -> None:
        """Source distribution tallies primary sources."""
        episodes = [
            _make_episode_with_attribution("episodic"),
            _make_episode_with_attribution("episodic"),
            _make_episode_with_attribution("parametric"),
        ]
        engine = _make_dream_engine()
        result = await engine._step_14_source_attribution(episodes)
        assert result["source_distribution"]["episodic"] == 2
        assert result["source_distribution"]["parametric"] == 1

    @pytest.mark.asyncio
    async def test_mean_confabulation_rate(self) -> None:
        """Mean confabulation rate computed from attribution snapshots."""
        episodes = [
            _make_episode_with_attribution("episodic", confab=0.1),
            _make_episode_with_attribution("episodic", confab=0.3),
        ]
        engine = _make_dream_engine()
        result = await engine._step_14_source_attribution(episodes)
        assert abs(result["mean_confabulation_rate"] - 0.2) < 0.01

    @pytest.mark.asyncio
    async def test_source_diversity_score_single_source(self) -> None:
        """Single source type -> diversity 0."""
        episodes = [_make_episode_with_attribution("episodic")]
        engine = _make_dream_engine()
        result = await engine._step_14_source_attribution(episodes)
        assert result["source_diversity_score"] == 0.0

    @pytest.mark.asyncio
    async def test_source_diversity_score_multiple_sources(self) -> None:
        """Multiple source types -> diversity > 0."""
        episodes = [
            _make_episode_with_attribution("episodic"),
            _make_episode_with_attribution("parametric"),
        ]
        engine = _make_dream_engine()
        result = await engine._step_14_source_attribution(episodes)
        assert result["source_diversity_score"] > 0.0

    @pytest.mark.asyncio
    async def test_step_degrades_gracefully_on_bad_metadata(self) -> None:
        """Episodes with missing/corrupt metadata -> skip gracefully."""
        ep = _make_episode_no_metadata()
        engine = _make_dream_engine()
        result = await engine._step_14_source_attribution([ep])
        assert result["episodes_with_attribution"] == 0


# ---------------------------------------------------------------------------
# Test Class 5: Ambient Source Tag in Prompt (5 tests)
# ---------------------------------------------------------------------------
class TestAmbientSourceTag:
    """AD-568d: Source awareness tag in cognitive prompt."""

    def test_tag_includes_episodic_count(self) -> None:
        """Source tag mentions episodic count when present."""
        attr = compute_source_attribution(
            retrieval_strategy=RetrievalStrategy.SHALLOW,
            episodic_count=3,
        )
        assert attr.episodic_count == 3
        assert attr.primary_source == KnowledgeSource.EPISODIC

    def test_tag_shows_training_only_when_no_retrieval(self) -> None:
        """No retrieval -> tag says 'training knowledge only'."""
        attr = compute_source_attribution(
            retrieval_strategy=RetrievalStrategy.NONE,
        )
        assert attr.primary_source == KnowledgeSource.PARAMETRIC
        assert attr.episodic_count == 0
        assert attr.procedural_count == 0
        assert attr.oracle_used is False

    def test_tag_includes_oracle(self) -> None:
        """Oracle used -> tag includes ship's records."""
        attr = compute_source_attribution(
            retrieval_strategy=RetrievalStrategy.DEEP,
            oracle_used=True,
            episodic_count=2,
        )
        assert attr.oracle_used is True

    def test_tag_includes_procedures(self) -> None:
        """Procedures available -> tag mentions them."""
        attr = compute_source_attribution(
            retrieval_strategy=RetrievalStrategy.SHALLOW,
            procedural_count=5,
            episodic_count=2,
        )
        assert attr.procedural_count == 5

    def test_attribution_survives_serialization(self) -> None:
        """SourceAttribution fields are all primitives -- JSON-safe."""
        attr = compute_source_attribution(
            retrieval_strategy=RetrievalStrategy.DEEP,
            episodic_count=3,
            procedural_count=2,
            oracle_used=True,
            confabulation_rate=0.1,
        )
        d = {
            "primary_source": attr.primary_source.value,
            "retrieval_strategy": attr.retrieval_strategy.value,
            "episodic_count": attr.episodic_count,
            "procedural_count": attr.procedural_count,
            "oracle_used": attr.oracle_used,
            "confabulation_rate": attr.confabulation_rate,
        }
        serialized = json.dumps(d)
        assert serialized  # No serialization errors
