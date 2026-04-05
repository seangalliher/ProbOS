"""AD-566b: Tier 1 Baseline Tests — 27 tests.

Tests cover D1 (PersonalityProbe), D2 (EpisodicRecallProbe),
D3 (ConfabulationProbe), D4 (TemperamentProbe),
D5 (registration & harness wiring).
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from probos.cognitive.qualification import (
    QualificationHarness,
    QualificationStore,
    QualificationTest,
    TestResult,
)
from probos.cognitive.qualification_tests import (
    ConfabulationProbe,
    EpisodicRecallProbe,
    PersonalityProbe,
    TemperamentProbe,
    _parse_bfi_scores,
)
from probos.config import QualificationConfig


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


class MockAgent:
    """Fake agent for probe testing."""

    def __init__(
        self,
        agent_id: str = "agent-1",
        agent_type: str = "science_analyst",
        department: str = "science",
        response: str = "This is a mock response.",
    ):
        self.id = agent_id
        self.agent_type = agent_type
        self.department = department
        self._response = response

    async def handle_intent(self, intent: Any) -> Any:
        result = MagicMock()
        result.result = self._response
        return result


class MockRegistry:
    """Fake registry that returns a MockAgent."""

    def __init__(self, agent: MockAgent | None = None):
        self._agent = agent

    def get(self, agent_id: str) -> MockAgent | None:
        if self._agent and self._agent.id == agent_id:
            return self._agent
        return None


@dataclass
class MockEpisode:
    """Fake episode for recall testing."""

    id: str = "ep-001"
    user_input: str = "Analyze trust patterns"
    outcomes: list = field(default_factory=lambda: [{"intent": "analyze", "status": "success"}])
    timestamp: float = 1000.0
    agent_ids: list = field(default_factory=lambda: ["agent-1"])
    reflection: str = ""
    dag_summary: dict = field(default_factory=lambda: {"intent_types": ["analysis"]})


class MockEpisodicMemory:
    """Fake episodic memory."""

    def __init__(self, episodes: list | None = None, count: int = 0):
        self._episodes = episodes or []
        self._count = count

    async def recent_for_agent(self, agent_id: str, k: int = 5) -> list:
        return self._episodes[:k]

    async def count_for_agent(self, agent_id: str) -> int:
        return self._count


class MockLLMClient:
    """Fake LLM client that returns configurable responses."""

    def __init__(self, response_text: str = "0.5"):
        self._response_text = response_text

    async def complete(self, request: Any) -> Any:
        resp = MagicMock()
        resp.content = self._response_text
        resp.text = self._response_text
        return resp


def _build_runtime(
    agent: MockAgent | None = None,
    episodes: list | None = None,
    episode_count: int = 0,
    llm_response: str = "0.5",
    episodic_memory: Any = "auto",
) -> MagicMock:
    """Build a mock runtime with standard components."""
    runtime = MagicMock()
    runtime.registry = MockRegistry(agent)
    runtime.llm_client = MockLLMClient(llm_response)
    if episodic_memory == "auto":
        runtime.episodic_memory = MockEpisodicMemory(episodes or [], episode_count)
    else:
        runtime.episodic_memory = episodic_memory
    return runtime


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def store(tmp_path: Path) -> QualificationStore:
    s = QualificationStore(data_dir=tmp_path)
    await s.start()
    yield s
    await s.stop()


# =========================================================================
# D1 — PersonalityProbe (6 tests)
# =========================================================================


class TestPersonalityProbe:
    """Tests for the BFI-2 personality probe."""

    def test_personality_probe_protocol_compliance(self):
        """PersonalityProbe implements QualificationTest protocol."""
        probe = PersonalityProbe()
        assert isinstance(probe, QualificationTest)

    @pytest.mark.asyncio
    @patch("probos.crew_profile.load_seed_profile")
    async def test_personality_probe_matching_seed(self, mock_load):
        """Agent responds with seed-aligned traits → high score."""
        mock_load.return_value = {
            "personality": {
                "openness": 0.8,
                "conscientiousness": 0.7,
                "extraversion": 0.6,
                "agreeableness": 0.7,
                "neuroticism": 0.3,
            }
        }
        # LLM extracts exact seed traits back
        llm_response = (
            "openness: 0.8\nconscientiousness: 0.7\nextraversion: 0.6\n"
            "agreeableness: 0.7\nneuroticism: 0.3"
        )
        agent = MockAgent(response="I am open, conscientious, social, agreeable, and calm.")
        runtime = _build_runtime(agent=agent, llm_response=llm_response)

        probe = PersonalityProbe()
        result = await probe.run("agent-1", runtime)

        assert result.score == pytest.approx(1.0, abs=0.01)
        assert result.passed is True
        assert "seed" in result.details
        assert "extracted" in result.details
        assert result.details["distance"] == pytest.approx(0.0, abs=0.01)

    @pytest.mark.asyncio
    @patch("probos.crew_profile.load_seed_profile")
    async def test_personality_probe_drifted_personality(self, mock_load):
        """Agent responds with divergent traits → lower score."""
        mock_load.return_value = {
            "personality": {
                "openness": 0.8,
                "conscientiousness": 0.7,
                "extraversion": 0.6,
                "agreeableness": 0.7,
                "neuroticism": 0.3,
            }
        }
        # LLM extracts inverted traits
        llm_response = (
            "openness: 0.2\nconscientiousness: 0.3\nextraversion: 0.4\n"
            "agreeableness: 0.3\nneuroticism: 0.7"
        )
        agent = MockAgent(response="I prefer convention, am casual, introverted...")
        runtime = _build_runtime(agent=agent, llm_response=llm_response)

        probe = PersonalityProbe()
        result = await probe.run("agent-1", runtime)

        assert result.score < 0.8
        assert result.details["distance"] > 0.3

    @pytest.mark.asyncio
    async def test_personality_probe_missing_agent(self):
        """agent_id not in registry → error result, not crash."""
        runtime = _build_runtime(agent=None)
        probe = PersonalityProbe()
        result = await probe.run("nonexistent-agent", runtime)

        assert result.score == 0.0
        assert result.passed is False
        assert result.error is not None
        assert "not found" in result.error

    @pytest.mark.asyncio
    @patch("probos.crew_profile.load_seed_profile")
    async def test_personality_probe_llm_scoring_fallback(self, mock_load):
        """LLM extraction fails → graceful degradation (uses seed as fallback)."""
        mock_load.return_value = {
            "personality": {
                "openness": 0.5,
                "conscientiousness": 0.5,
                "extraversion": 0.5,
                "agreeableness": 0.5,
                "neuroticism": 0.5,
            }
        }
        agent = MockAgent(response="Some response")
        runtime = _build_runtime(agent=agent, llm_response="UNPARSEABLE GARBAGE")

        probe = PersonalityProbe()
        result = await probe.run("agent-1", runtime)

        # Should not crash; falls back to seed traits → distance = 0 → score = 1.0
        assert result.error is None
        assert result.score == pytest.approx(1.0, abs=0.01)

    @pytest.mark.asyncio
    @patch("probos.crew_profile.load_seed_profile")
    async def test_personality_probe_details_structure(self, mock_load):
        """Verify details dict contains seed, extracted, distance, per_trait_deltas."""
        mock_load.return_value = {
            "personality": {
                "openness": 0.5,
                "conscientiousness": 0.5,
                "extraversion": 0.5,
                "agreeableness": 0.5,
                "neuroticism": 0.5,
            }
        }
        llm_response = (
            "openness: 0.6\nconscientiousness: 0.5\nextraversion: 0.5\n"
            "agreeableness: 0.5\nneuroticism: 0.5"
        )
        agent = MockAgent(response="test")
        runtime = _build_runtime(agent=agent, llm_response=llm_response)

        probe = PersonalityProbe()
        result = await probe.run("agent-1", runtime)

        assert "seed" in result.details
        assert "extracted" in result.details
        assert "distance" in result.details
        assert "per_trait_deltas" in result.details
        assert isinstance(result.details["per_trait_deltas"], dict)
        assert set(result.details["per_trait_deltas"].keys()) == {
            "openness", "conscientiousness", "extraversion",
            "agreeableness", "neuroticism",
        }


# =========================================================================
# D2 — EpisodicRecallProbe (7 tests)
# =========================================================================


class TestEpisodicRecallProbe:
    """Tests for the episodic recall probe."""

    def test_recall_probe_protocol_compliance(self):
        """EpisodicRecallProbe implements QualificationTest protocol."""
        probe = EpisodicRecallProbe()
        assert isinstance(probe, QualificationTest)

    @pytest.mark.asyncio
    async def test_recall_probe_accurate_recall(self):
        """Agent recalls episode correctly → high accuracy."""
        episodes = [
            MockEpisode(id=f"ep-{i}", user_input=f"Task {i}", timestamp=float(i))
            for i in range(3)
        ]
        agent = MockAgent(
            response="I analyzed trust patterns and the task was successful.",
        )
        # LLM scoring returns 0.9 (high accuracy)
        runtime = _build_runtime(
            agent=agent, episodes=episodes, episode_count=3,
            llm_response="0.9",
        )

        probe = EpisodicRecallProbe()
        result = await probe.run("agent-1", runtime)

        assert result.score > 0.5
        assert result.details.get("skipped") is False
        assert result.details["episodes_tested"] == 3

    @pytest.mark.asyncio
    async def test_recall_probe_confabulated_recall(self):
        """Agent adds false details → low accuracy."""
        episodes = [
            MockEpisode(id=f"ep-{i}", user_input=f"Task {i}", timestamp=float(i))
            for i in range(3)
        ]
        agent = MockAgent(
            response="I don't recall any such analysis occurring.",
        )
        runtime = _build_runtime(
            agent=agent, episodes=episodes, episode_count=3,
            llm_response="0.1",
        )

        probe = EpisodicRecallProbe()
        result = await probe.run("agent-1", runtime)

        assert result.score < 0.5

    @pytest.mark.asyncio
    async def test_recall_probe_no_episodes_skipped(self):
        """Agent has 0 episodes → score 1.0, skipped."""
        agent = MockAgent()
        runtime = _build_runtime(agent=agent, episodes=[], episode_count=0)

        probe = EpisodicRecallProbe()
        result = await probe.run("agent-1", runtime)

        assert result.score == 1.0
        assert result.passed is True
        assert result.details["skipped"] is True
        assert result.details["reason"] == "insufficient_episodes"

    @pytest.mark.asyncio
    async def test_recall_probe_no_episodic_memory(self):
        """runtime.episodic_memory is None → score 1.0, skipped."""
        agent = MockAgent()
        runtime = _build_runtime(agent=agent, episodic_memory=None)

        probe = EpisodicRecallProbe()
        result = await probe.run("agent-1", runtime)

        assert result.score == 1.0
        assert result.passed is True
        assert result.details["skipped"] is True
        assert result.details["reason"] == "no_episodic_memory"

    @pytest.mark.asyncio
    async def test_recall_probe_partial_recall(self):
        """Agent gets some details right → mid-range score."""
        episodes = [
            MockEpisode(id=f"ep-{i}", user_input=f"Task {i}", timestamp=float(i))
            for i in range(3)
        ]
        agent = MockAgent(
            response="I think there was some kind of analysis task.",
        )
        runtime = _build_runtime(
            agent=agent, episodes=episodes, episode_count=3,
            llm_response="0.5",
        )

        probe = EpisodicRecallProbe()
        result = await probe.run("agent-1", runtime)

        assert 0.3 <= result.score <= 0.7
        assert result.details["episodes_tested"] == 3

    @pytest.mark.asyncio
    async def test_recall_probe_details_structure(self):
        """Verify per_episode list in details."""
        episodes = [
            MockEpisode(id=f"ep-{i}", user_input=f"Task {i}", timestamp=float(i))
            for i in range(3)
        ]
        agent = MockAgent(response="I recall the task.")
        runtime = _build_runtime(
            agent=agent, episodes=episodes, episode_count=3,
            llm_response="0.7",
        )

        probe = EpisodicRecallProbe()
        result = await probe.run("agent-1", runtime)

        assert "per_episode" in result.details
        assert isinstance(result.details["per_episode"], list)
        assert len(result.details["per_episode"]) == 3
        for ep_result in result.details["per_episode"]:
            assert "episode_id" in ep_result
            assert "accuracy" in ep_result
            assert "classification" in ep_result


# =========================================================================
# D3 — ConfabulationProbe (6 tests)
# =========================================================================


class TestConfabulationProbe:
    """Tests for the confabulation detection probe."""

    def test_confab_probe_protocol_compliance(self):
        """ConfabulationProbe implements QualificationTest protocol."""
        probe = ConfabulationProbe()
        assert isinstance(probe, QualificationTest)

    @pytest.mark.asyncio
    async def test_confab_probe_correct_rejection(self):
        """Agent says 'I don't remember' → score 1.0."""
        agent = MockAgent(
            response="I don't recall any such analysis. I have no memory of "
                     "Commander Zephyr or that specific correlation finding.",
        )
        runtime = _build_runtime(agent=agent, llm_response="1.0")

        probe = ConfabulationProbe()
        result = await probe.run("agent-1", runtime)

        assert result.score == pytest.approx(1.0)
        assert result.passed is True
        assert result.details["classification"] == "correctly_rejected"

    @pytest.mark.asyncio
    async def test_confab_probe_confabulation_detected(self):
        """Agent elaborates on fabricated scenario → score 0.0."""
        agent = MockAgent(
            response="Yes, I remember that analysis well. The 0.73 correlation "
                     "was significant and I documented the methodology "
                     "including control variables. The findings showed...",
        )
        runtime = _build_runtime(agent=agent, llm_response="0.0")

        probe = ConfabulationProbe()
        result = await probe.run("agent-1", runtime)

        assert result.score == pytest.approx(0.0)
        assert result.passed is False
        assert result.details["classification"] == "confabulated"

    @pytest.mark.asyncio
    async def test_confab_probe_partial_rejection(self):
        """Agent is uncertain but doesn't fully reject → mid-range score."""
        agent = MockAgent(
            response="I'm not entirely sure about that. It sounds vaguely "
                     "familiar but I can't confirm the specifics.",
        )
        runtime = _build_runtime(agent=agent, llm_response="0.5")

        probe = ConfabulationProbe()
        result = await probe.run("agent-1", runtime)

        assert 0.2 <= result.score <= 0.8
        assert result.details["classification"] == "uncertain"

    @pytest.mark.asyncio
    async def test_confab_probe_fabrication_includes_specifics(self):
        """Verify fabricated scenario contains specific false details."""
        probe = ConfabulationProbe()
        agent = MockAgent(department="science", response="I don't recall.")
        runtime = _build_runtime(agent=agent, llm_response="1.0")

        result = await probe.run("agent-1", runtime)

        scenario = result.details["fabricated_scenario"]
        # Should contain fabricated specifics
        assert any(c.isdigit() for c in scenario)  # numbers
        assert "Commander" in scenario or "Lieutenant" in scenario or "Dr." in scenario  # names

    @pytest.mark.asyncio
    async def test_confab_probe_details_structure(self):
        """Verify fabricated_scenario, classification, indicators in details."""
        agent = MockAgent(response="I don't recall that event at all.")
        runtime = _build_runtime(agent=agent, llm_response="1.0")

        probe = ConfabulationProbe()
        result = await probe.run("agent-1", runtime)

        assert "fabricated_scenario" in result.details
        assert "response_summary" in result.details
        assert "classification" in result.details
        assert "rejection_indicators" in result.details
        assert "confabulation_indicators" in result.details
        assert isinstance(result.details["rejection_indicators"], list)
        assert isinstance(result.details["confabulation_indicators"], list)


# =========================================================================
# D4 — TemperamentProbe (6 tests)
# =========================================================================


class TestTemperamentProbe:
    """Tests for the MTI temperament profile probe."""

    def test_temperament_probe_protocol_compliance(self):
        """TemperamentProbe implements QualificationTest protocol."""
        probe = TemperamentProbe()
        assert isinstance(probe, QualificationTest)

    @pytest.mark.asyncio
    async def test_temperament_probe_four_axes_scored(self):
        """Verify all 4 axes present in details."""
        agent = MockAgent(response="I would investigate methodically.")
        runtime = _build_runtime(agent=agent, llm_response="0.6")

        probe = TemperamentProbe()
        result = await probe.run("agent-1", runtime)

        assert "reactivity" in result.details
        assert "compliance" in result.details
        assert "sociality" in result.details
        assert "resilience" in result.details

    @pytest.mark.asyncio
    async def test_temperament_probe_axis_scores_bounded(self):
        """All axis scores 0.0–1.0."""
        agent = MockAgent(response="I would respond proportionally.")
        runtime = _build_runtime(agent=agent, llm_response="0.7")

        probe = TemperamentProbe()
        result = await probe.run("agent-1", runtime)

        for axis in ("reactivity", "compliance", "sociality", "resilience"):
            score = result.details[axis]
            assert 0.0 <= score <= 1.0, f"{axis} = {score} out of bounds"

    def test_temperament_probe_threshold_zero(self):
        """Threshold is 0.0 (profile, not pass/fail)."""
        probe = TemperamentProbe()
        assert probe.threshold == 0.0

    @pytest.mark.asyncio
    async def test_temperament_probe_missing_agent(self):
        """Agent not in registry → error result."""
        runtime = _build_runtime(agent=None)
        probe = TemperamentProbe()
        result = await probe.run("nonexistent", runtime)

        assert result.score == 0.0
        assert result.passed is False
        assert result.error is not None
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_temperament_probe_details_structure(self):
        """Verify reactivity, compliance, sociality, resilience + per_axis_responses."""
        agent = MockAgent(response="I'd check the alert details first.")
        runtime = _build_runtime(agent=agent, llm_response="0.5")

        probe = TemperamentProbe()
        result = await probe.run("agent-1", runtime)

        assert "per_axis_responses" in result.details
        responses = result.details["per_axis_responses"]
        assert set(responses.keys()) == {"reactivity", "compliance", "sociality", "resilience"}
        for axis_response in responses.values():
            assert isinstance(axis_response, str)


# =========================================================================
# D5 — Registration & Wiring (2 tests)
# =========================================================================


class TestRegistration:
    """Tests for harness registration and tier execution."""

    def test_harness_registers_all_tier1_tests(self):
        """All 4 tests registered, all have tier == 1."""
        store = MagicMock(spec=QualificationStore)
        harness = QualificationHarness(store=store)

        for test_cls in (PersonalityProbe, EpisodicRecallProbe,
                         ConfabulationProbe, TemperamentProbe):
            harness.register_test(test_cls())

        registered = harness.registered_tests
        assert len(registered) == 4
        assert "bfi2_personality_probe" in registered
        assert "episodic_recall_probe" in registered
        assert "confabulation_probe" in registered
        assert "mti_temperament_profile" in registered
        for test in registered.values():
            assert test.tier == 1

    @pytest.mark.asyncio
    async def test_harness_run_tier1_executes_all(self, store: QualificationStore):
        """run_tier(agent_id, 1, runtime) runs all 4 tests."""
        harness = QualificationHarness(store=store)
        agent = MockAgent(response="test response")
        runtime = _build_runtime(
            agent=agent, episodes=[], episode_count=0,
            llm_response="0.5",
        )

        # Patch load_seed_profile for PersonalityProbe
        with patch("probos.crew_profile.load_seed_profile") as mock_load:
            mock_load.return_value = {
                "personality": {
                    "openness": 0.5, "conscientiousness": 0.5,
                    "extraversion": 0.5, "agreeableness": 0.5,
                    "neuroticism": 0.5,
                }
            }
            for test_cls in (PersonalityProbe, EpisodicRecallProbe,
                             ConfabulationProbe, TemperamentProbe):
                harness.register_test(test_cls())

            results = await harness.run_tier("agent-1", 1, runtime)

        assert len(results) == 4
        test_names = {r.test_name for r in results}
        assert test_names == {
            "bfi2_personality_probe",
            "episodic_recall_probe",
            "confabulation_probe",
            "mti_temperament_profile",
        }


# =========================================================================
# BFI score parser unit test
# =========================================================================


class TestBFIParser:
    """Unit test for _parse_bfi_scores helper."""

    def test_parse_valid_scores(self):
        text = (
            "openness: 0.7\n"
            "conscientiousness: 0.8\n"
            "extraversion: 0.3\n"
            "agreeableness: 0.6\n"
            "neuroticism: 0.2\n"
        )
        scores = _parse_bfi_scores(text)
        assert scores == {
            "openness": 0.7,
            "conscientiousness": 0.8,
            "extraversion": 0.3,
            "agreeableness": 0.6,
            "neuroticism": 0.2,
        }

    def test_parse_clamped(self):
        text = "openness: 1.5\nneuroticism: -0.3\n"
        scores = _parse_bfi_scores(text)
        assert scores["openness"] == 1.0
        assert scores["neuroticism"] == 0.0
