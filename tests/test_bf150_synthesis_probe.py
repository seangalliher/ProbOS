"""BF-150: Cross-agent synthesis probe — redesign for sovereign shard synthesis."""

import pytest

from probos.cognitive.memory_probes import (
    _SYNTHESIS_FACTS,
    CrossAgentSynthesisProbe,
    _distinctive_keywords,
    _make_test_episode,
    _ward_room_content,
)


class TestBF150SynthesisFactsRedesign:
    """Synthesis facts use department attribution, not cross-shard seeding."""

    def test_synthesis_facts_have_department_field(self):
        """BF-150: Each synthesis fact must have a 'department' field."""
        for fact in _SYNTHESIS_FACTS:
            assert "department" in fact, f"Missing 'department' in {fact}"
            assert fact["department"] in {"engineering", "medical", "science"}

    def test_synthesis_facts_have_content_field(self):
        """BF-150: Each synthesis fact must have a 'content' field."""
        for fact in _SYNTHESIS_FACTS:
            assert "content" in fact
            assert len(fact["content"]) > 20

    def test_three_distinct_departments(self):
        """BF-150: Facts should span 3 different departments."""
        departments = {f["department"] for f in _SYNTHESIS_FACTS}
        assert len(departments) == 3

    def test_distinctive_keywords_per_fact(self):
        """BF-150: Each fact has distinctive keywords for scoring."""
        for fact in _SYNTHESIS_FACTS:
            kw = _distinctive_keywords(fact["content"])
            assert len(kw) >= 4, f"Not enough distinctive keywords in: {fact['content'][:50]}"

    def test_facts_share_trust_anomaly_theme(self):
        """BF-150: All facts relate to the same incident for synthesis testing."""
        for fact in _SYNTHESIS_FACTS:
            assert "trust" in fact["content"].lower() or "anomaly" in fact["content"].lower()


class TestBF150ProbePathway:
    """Probe results include pathway metadata."""

    def test_probe_pathway_in_details(self):
        """BF-150: TestResult details must include probe_pathway field."""
        probe = CrossAgentSynthesisProbe()
        assert probe.name == "cross_agent_synthesis_probe"
        assert probe.tier == 3


class TestCrewSkipGuard:
    """BF-160: CrossAgentSynthesisProbe skips when run as __crew__."""

    @pytest.mark.asyncio
    async def test_crew_agent_id_returns_skip(self):
        """Probe returns skip result when agent_id is __crew__."""
        from probos.cognitive.memory_probes import CrossAgentSynthesisProbe
        from probos.cognitive.qualification import CREW_AGENT_ID

        probe = CrossAgentSynthesisProbe()

        class MockRuntime:
            episodic_memory = True
            registry = type("R", (), {"get": lambda self, x: None})()

        result = await probe.run(CREW_AGENT_ID, MockRuntime())
        assert result.passed is True
        assert result.score == 1.0
        assert result.details.get("skipped") is True
        assert result.details.get("reason") == "per_agent_only"
