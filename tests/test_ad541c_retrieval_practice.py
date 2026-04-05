"""AD-541c: Spaced Retrieval Therapy — 30 tests.

Tests cover:
- D1: RetrievalPracticeEngine core (14 tests)
- D1 extended: Schedule edge cases (4 tests)
- D2: SQLite persistence (4 tests)
- D3: Dream Step 11 per-agent (4 tests)
- D4: Config and DreamReport (2 tests)
- D5: Counselor integration (2 tests)
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.retrieval_practice import (
    RetrievalPracticeEngine,
    RetrievalSchedule,
    RetrievalPracticeResult,
)
from probos.config import DreamingConfig
from probos.types import DreamReport, Episode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_episode(
    *,
    ep_id: str = "ep-001",
    agent_ids: list[str] | None = None,
    source: str = "direct",
    user_input: str = "What is the ship status?",
    reflection: str = "The ship is healthy",
    outcomes: list[dict] | None = None,
    trust_deltas: list[dict] | None = None,
    dag_summary: dict | None = None,
) -> Episode:
    return Episode(
        id=ep_id,
        timestamp=time.time(),
        user_input=user_input,
        agent_ids=agent_ids or ["agent-A"],
        source=source,
        reflection=reflection,
        outcomes=outcomes or [{"intent": "check_status", "success": True, "status": "completed"}],
        trust_deltas=trust_deltas or [],
        dag_summary=dag_summary or {"intent_types": ["check_status"], "node_count": 1},
    )


def _make_engine(**overrides) -> RetrievalPracticeEngine:
    defaults = dict(
        success_threshold=0.6,
        partial_threshold=0.3,
        initial_interval_hours=24.0,
        max_interval_hours=168.0,
        episodes_per_cycle=3,
        counselor_failure_streak=3,
    )
    defaults.update(overrides)
    return RetrievalPracticeEngine(**defaults)


# ==================================================================
# D1 Tests — RetrievalPracticeEngine core (14 tests)
# ==================================================================


class TestD1Core:
    """Tests 1-14: Core engine functionality."""

    def test_retrieval_schedule_defaults(self):
        """T1: Verify RetrievalSchedule default values."""
        sched = RetrievalSchedule()
        assert sched.interval_hours == 24.0
        assert sched.retired is False
        assert sched.consecutive_successes == 0
        assert sched.consecutive_failures == 0
        assert sched.total_practices == 0
        assert sched.total_successes == 0
        assert sched.recall_accuracy == 0.0
        assert sched.agent_id == ""
        assert sched.episode_id == ""

    def test_select_episodes_filters_non_direct(self):
        """T2: Only DIRECT source episodes are selected."""
        engine = _make_engine()
        episodes = [
            _make_episode(ep_id="ep-1", source="direct"),
            _make_episode(ep_id="ep-2", source="secondhand"),
            _make_episode(ep_id="ep-3", source="direct"),
        ]
        result = engine.select_episodes_for_practice(episodes, "agent-A")
        ids = [ep.id for ep in result]
        assert "ep-1" in ids
        assert "ep-3" in ids
        assert "ep-2" not in ids

    def test_select_episodes_limits_to_max(self):
        """T3: At most episodes_per_cycle returned."""
        engine = _make_engine(episodes_per_cycle=3)
        episodes = [
            _make_episode(ep_id=f"ep-{i}") for i in range(10)
        ]
        result = engine.select_episodes_for_practice(episodes, "agent-A")
        assert len(result) == 3

    def test_select_episodes_prioritizes_trust_deltas(self):
        """T4: Episodes with trust_deltas are selected before those without."""
        engine = _make_engine(episodes_per_cycle=2)
        ep_no_delta = _make_episode(ep_id="ep-no-delta", trust_deltas=[])
        ep_with_delta = _make_episode(
            ep_id="ep-with-delta",
            trust_deltas=[{"agent_id": "a", "old": 0.5, "new": 0.6}],
        )
        # ep_with_delta listed second but should be selected first (among new)
        episodes = [ep_no_delta, ep_with_delta]
        result = engine.select_episodes_for_practice(episodes, "agent-A")
        assert result[0].id == "ep-with-delta"

    def test_select_episodes_due_before_new(self):
        """T5: Due episodes (next_due in past) come before new episodes."""
        engine = _make_engine(episodes_per_cycle=2)
        ep_due = _make_episode(ep_id="ep-due")
        ep_new = _make_episode(ep_id="ep-new")

        # Create a schedule for ep_due that's overdue
        engine._schedules["agent-A:ep-due"] = RetrievalSchedule(
            agent_id="agent-A",
            episode_id="ep-due",
            next_due=time.time() - 100,  # overdue
            interval_hours=24.0,
        )
        result = engine.select_episodes_for_practice([ep_due, ep_new], "agent-A")
        assert result[0].id == "ep-due"

    def test_select_episodes_skips_retired(self):
        """T6: Retired schedules are not selected."""
        engine = _make_engine()
        ep = _make_episode(ep_id="ep-retired")
        engine._schedules["agent-A:ep-retired"] = RetrievalSchedule(
            agent_id="agent-A",
            episode_id="ep-retired",
            retired=True,
        )
        result = engine.select_episodes_for_practice([ep], "agent-A")
        assert len(result) == 0

    def test_select_episodes_filters_by_agent_id(self):
        """T7: Only episodes where agent_id is in agent_ids are selected."""
        engine = _make_engine()
        ep_a = _make_episode(ep_id="ep-a", agent_ids=["agent-A"])
        ep_b = _make_episode(ep_id="ep-b", agent_ids=["agent-B"])
        ep_ab = _make_episode(ep_id="ep-ab", agent_ids=["agent-A", "agent-B"])

        result = engine.select_episodes_for_practice([ep_a, ep_b, ep_ab], "agent-A")
        ids = [ep.id for ep in result]
        assert "ep-a" in ids
        assert "ep-ab" in ids
        assert "ep-b" not in ids

    def test_build_recall_prompt_contains_context(self):
        """T8: Prompt includes context (user_input, timestamp) but not outcomes."""
        engine = _make_engine()
        ep = _make_episode(
            user_input="Check warp drive",
            dag_summary={"intent_types": ["check_warp"], "node_count": 2},
        )
        prompt = engine.build_recall_prompt(ep)
        assert "Check warp drive" in prompt
        assert "check_warp" in prompt
        assert "Agents involved: 2" in prompt
        assert "EPISODE CONTEXT" in prompt

    def test_build_recall_prompt_withholds_outcome(self):
        """T9: Prompt does NOT contain reflection or outcome details."""
        engine = _make_engine()
        ep = _make_episode(
            reflection="The warp drive was at 95%",
            outcomes=[{"intent": "check_warp", "status": "completed"}],
        )
        prompt = engine.build_recall_prompt(ep)
        assert "95%" not in prompt
        assert "completed" not in prompt
        assert ep.reflection not in prompt

    def test_build_expected_text_combines_reflection_and_outcomes(self):
        """T10: Expected text includes reflection and outcome summaries."""
        engine = _make_engine()
        ep = _make_episode(
            reflection="Warp drive nominal",
            outcomes=[
                {"intent": "check_warp", "status": "completed"},
                {"intent": "read_sensor", "success": True},
            ],
        )
        expected = engine.build_expected_text(ep)
        assert "Warp drive nominal" in expected
        assert "check_warp: completed" in expected
        assert "read_sensor:" in expected

    def test_score_recall_high_accuracy(self):
        """T11: Similar text scores ≥ 0.6."""
        engine = _make_engine()
        expected = "the warp drive is nominal and operational at full capacity"
        recalled = "the warp drive is nominal and operational at full capacity levels"
        score = engine.score_recall(recalled, expected)
        assert score >= 0.6

    def test_score_recall_low_accuracy(self):
        """T12: Unrelated text scores < 0.3."""
        engine = _make_engine()
        expected = "the warp drive is nominal and operational"
        recalled = "banana fruit smoothie recipe dessert"
        score = engine.score_recall(recalled, expected)
        assert score < 0.3

    def test_update_schedule_success_doubles_interval(self):
        """T13: Accuracy ≥ threshold doubles interval, increments successes."""
        engine = _make_engine(success_threshold=0.6)
        sched = engine.update_schedule("agent-A", "ep-1", accuracy=0.8)
        assert sched.interval_hours == 48.0  # 24 * 2
        assert sched.consecutive_successes == 1
        assert sched.consecutive_failures == 0
        assert sched.total_successes == 1
        assert sched.total_practices == 1

    def test_update_schedule_failure_halves_interval(self):
        """T14: Accuracy < partial_threshold halves interval, increments failures."""
        engine = _make_engine(partial_threshold=0.3, initial_interval_hours=24.0)
        # First set a longer interval
        engine._schedules["agent-A:ep-1"] = RetrievalSchedule(
            agent_id="agent-A",
            episode_id="ep-1",
            interval_hours=96.0,
        )
        sched = engine.update_schedule("agent-A", "ep-1", accuracy=0.1)
        assert sched.interval_hours == 48.0  # 96 / 2
        assert sched.consecutive_failures == 1
        assert sched.consecutive_successes == 0


# ==================================================================
# D1 Extended Tests (4 tests)
# ==================================================================


class TestD1Extended:
    """Tests 15-18: Extended schedule behavior."""

    def test_update_schedule_retires_at_max_interval(self):
        """T15: Interval exceeding max retires the schedule."""
        engine = _make_engine(max_interval_hours=168.0)
        # Set interval close to max
        engine._schedules["agent-A:ep-1"] = RetrievalSchedule(
            agent_id="agent-A",
            episode_id="ep-1",
            interval_hours=100.0,
        )
        sched = engine.update_schedule("agent-A", "ep-1", accuracy=0.9)
        assert sched.interval_hours == 200.0  # 100 * 2
        assert sched.retired is True

    def test_update_schedule_partial_maintains_interval(self):
        """T16: Partial accuracy (0.3-0.6) keeps interval, resets streaks."""
        engine = _make_engine()
        engine._schedules["agent-A:ep-1"] = RetrievalSchedule(
            agent_id="agent-A",
            episode_id="ep-1",
            interval_hours=48.0,
            consecutive_successes=3,
        )
        sched = engine.update_schedule("agent-A", "ep-1", accuracy=0.45)
        assert sched.interval_hours == 48.0  # unchanged
        assert sched.consecutive_successes == 0
        assert sched.consecutive_failures == 0

    def test_get_counselor_concerns_filters_by_agent(self):
        """T17: Concerns filtered by agent_id."""
        engine = _make_engine(counselor_failure_streak=2)
        engine._schedules["agent-A:ep-1"] = RetrievalSchedule(
            agent_id="agent-A",
            episode_id="ep-1",
            consecutive_failures=3,
        )
        engine._schedules["agent-B:ep-2"] = RetrievalSchedule(
            agent_id="agent-B",
            episode_id="ep-2",
            consecutive_failures=5,
        )
        concerns_a = engine.get_counselor_concerns("agent-A")
        assert len(concerns_a) == 1
        assert concerns_a[0].agent_id == "agent-A"

        concerns_all = engine.get_counselor_concerns()
        assert len(concerns_all) == 2

    def test_get_agent_recall_stats(self):
        """T18: Aggregate stats for an agent are correct."""
        engine = _make_engine(counselor_failure_streak=3)
        engine._schedules["agent-A:ep-1"] = RetrievalSchedule(
            agent_id="agent-A",
            episode_id="ep-1",
            total_practices=5,
            total_successes=3,
            recall_accuracy=0.7,
        )
        engine._schedules["agent-A:ep-2"] = RetrievalSchedule(
            agent_id="agent-A",
            episode_id="ep-2",
            total_practices=3,
            total_successes=1,
            recall_accuracy=0.3,
            consecutive_failures=4,
        )
        engine._schedules["agent-A:ep-3"] = RetrievalSchedule(
            agent_id="agent-A",
            episode_id="ep-3",
            retired=True,
        )
        stats = engine.get_agent_recall_stats("agent-A")
        assert stats["total_scheduled"] == 3
        assert stats["total_practiced"] == 2
        assert stats["total_retired"] == 1
        assert stats["episodes_at_risk"] == 1  # ep-2 has 4 consecutive failures
        assert abs(stats["avg_recall_accuracy"] - 0.5) < 0.01  # (0.7 + 0.3) / 2
        assert stats["practice_sessions_total"] == 8  # 5 + 3 + 0


# ==================================================================
# D2 Tests — SQLite persistence (4 tests)
# ==================================================================


class TestD2Persistence:
    """Tests 19-22: SQLite persistence."""

    @pytest.mark.asyncio
    async def test_save_and_load_schedules_roundtrip(self, tmp_path):
        """T19: Schedules persist across engine restarts."""
        engine1 = _make_engine(data_dir=str(tmp_path))
        await engine1.start()

        engine1.update_schedule("agent-A", "ep-1", accuracy=0.8)
        await engine1._save_schedule(engine1._schedules["agent-A:ep-1"])
        await engine1.stop()

        engine2 = _make_engine(data_dir=str(tmp_path))
        await engine2.start()
        assert "agent-A:ep-1" in engine2._schedules
        sched = engine2._schedules["agent-A:ep-1"]
        assert sched.interval_hours == 48.0
        assert sched.total_successes == 1
        await engine2.stop()

    @pytest.mark.asyncio
    async def test_persistence_survives_restart(self, tmp_path):
        """T20: Intervals and streaks persist correctly across restart."""
        engine = _make_engine(data_dir=str(tmp_path))
        await engine.start()

        # Practice with failures
        for _ in range(3):
            sched = engine.update_schedule("agent-A", "ep-1", accuracy=0.1)
            await engine._save_schedule(sched)
        await engine.stop()

        engine2 = _make_engine(data_dir=str(tmp_path))
        await engine2.start()
        sched = engine2._schedules["agent-A:ep-1"]
        assert sched.consecutive_failures == 3
        assert sched.total_practices == 3
        await engine2.stop()

    @pytest.mark.asyncio
    async def test_start_without_data_dir_is_memory_only(self):
        """T21: No data_dir — engine works in memory only."""
        engine = _make_engine()
        await engine.start()  # No error
        sched = engine.update_schedule("agent-A", "ep-1", accuracy=0.8)
        assert sched.interval_hours == 48.0
        await engine.stop()

    @pytest.mark.asyncio
    async def test_stop_closes_db(self, tmp_path):
        """T22: Double stop doesn't raise."""
        engine = _make_engine(data_dir=str(tmp_path))
        await engine.start()
        await engine.stop()
        await engine.stop()  # No error on double stop


# ==================================================================
# D3 Tests — Dream Step 11 per-agent (4 tests)
# ==================================================================


def _build_dreaming_engine(
    *,
    active_retrieval_enabled: bool = False,
    retrieval_practice_engine: RetrievalPracticeEngine | None = None,
    retrieval_llm_client: Any = None,
) -> Any:
    """Build a minimal DreamingEngine with bypass pattern for Step 11 testing."""
    from probos.cognitive.dreaming import DreamingEngine

    config = DreamingConfig(active_retrieval_enabled=active_retrieval_enabled)
    engine = object.__new__(DreamingEngine)
    engine.router = MagicMock()
    engine.trust_network = MagicMock()
    engine.episodic_memory = AsyncMock()
    engine.config = config
    engine.pre_warm_intents = []
    engine._idle_scale_down_fn = None
    engine._gap_prediction_fn = None
    engine._last_clusters = []
    engine._contradiction_resolve_fn = None
    engine._last_consolidated_count = 0
    engine._llm_client = None
    engine._procedure_store = None
    engine._ward_room = None
    engine._agent_id = ""
    engine._trust_network_lookup = None
    engine._emergence_metrics_engine = None
    engine._get_department = None
    engine._records_store = None
    engine._notebook_quality_engine = None
    engine._retrieval_practice_engine = retrieval_practice_engine
    engine._retrieval_llm_client = retrieval_llm_client
    engine._last_procedures = []
    engine._extracted_cluster_ids = set()
    engine._addressed_degradations = {}
    engine._extraction_candidates = {}
    engine._reactive_cooldowns = {}
    engine._fallback_learning_queue = []
    engine._observed_threads = set()
    # AD-567d fields
    engine._activation_tracker = None
    return engine


class TestD3DreamStep11:
    """Tests 23-26: Dream Step 11 integration."""

    @pytest.mark.asyncio
    async def test_step_11_skipped_when_disabled(self):
        """T23: No LLM calls when active_retrieval_enabled=False."""
        llm = AsyncMock()
        engine = _build_dreaming_engine(
            active_retrieval_enabled=False,
            retrieval_practice_engine=_make_engine(),
            retrieval_llm_client=llm,
        )
        episodes = [_make_episode()]
        result = await engine._step_11_retrieval_practice(episodes)
        assert result["practices"] == 0
        llm.complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_step_11_skipped_when_no_engine(self):
        """T24: No errors when retrieval_practice_engine is None."""
        engine = _build_dreaming_engine(
            active_retrieval_enabled=True,
            retrieval_practice_engine=None,
        )
        episodes = [_make_episode()]
        result = await engine._step_11_retrieval_practice(episodes)
        assert result["practices"] == 0

    @pytest.mark.asyncio
    async def test_step_11_per_agent_practice(self):
        """T25: Each agent's episodes are practiced separately."""
        rp_engine = _make_engine(episodes_per_cycle=5)

        # Mock LLM response
        mock_resp = MagicMock()
        mock_resp.content = "the ship status was checked and everything was healthy"
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value=mock_resp)

        engine = _build_dreaming_engine(
            active_retrieval_enabled=True,
            retrieval_practice_engine=rp_engine,
            retrieval_llm_client=llm,
        )

        episodes = [
            _make_episode(ep_id="ep-A", agent_ids=["agent-A"]),
            _make_episode(ep_id="ep-B", agent_ids=["agent-B"]),
            _make_episode(ep_id="ep-AB", agent_ids=["agent-A", "agent-B"]),
        ]
        result = await engine._step_11_retrieval_practice(episodes)
        # Each agent practices their eligible episodes
        assert result["practices"] >= 2  # At least some practices happened
        assert len(result["accuracies"]) == result["practices"]

    @pytest.mark.asyncio
    async def test_step_11_emits_per_agent_concern_events(self):
        """T26: RETRIEVAL_PRACTICE_CONCERN event emitted for failing agents."""
        rp_engine = _make_engine(counselor_failure_streak=1)

        # Pre-populate a failing schedule
        rp_engine._schedules["agent-A:ep-fail"] = RetrievalSchedule(
            agent_id="agent-A",
            episode_id="ep-fail",
            consecutive_failures=2,
            next_due=time.time() - 100,
        )

        # Mock LLM returning garbage (low recall)
        mock_resp = MagicMock()
        mock_resp.content = "completely unrelated banana smoothie"
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value=mock_resp)

        engine = _build_dreaming_engine(
            active_retrieval_enabled=True,
            retrieval_practice_engine=rp_engine,
            retrieval_llm_client=llm,
        )

        emitted_events = []

        def mock_emit(event_type, data):
            emitted_events.append((event_type, data))

        engine._emit_event_fn = mock_emit

        episodes = [
            _make_episode(
                ep_id="ep-fail",
                agent_ids=["agent-A"],
                reflection="Warp drive recalibrated successfully",
                outcomes=[{"intent": "recalibrate_warp", "status": "completed"}],
            ),
        ]
        result = await engine._step_11_retrieval_practice(episodes)
        assert result["concerns"] >= 1
        assert any(
            evt_type == "retrieval_practice_concern"
            for evt_type, _ in emitted_events
        )


# ==================================================================
# D4 Tests — Config and DreamReport (2 tests)
# ==================================================================


class TestD4ConfigReport:
    """Tests 27-28: Config defaults and DreamReport fields."""

    def test_dreaming_config_retrieval_defaults(self):
        """T27: DreamingConfig has correct retrieval defaults."""
        cfg = DreamingConfig()
        assert cfg.active_retrieval_enabled is False
        assert cfg.retrieval_episodes_per_cycle == 3
        assert cfg.retrieval_success_threshold == 0.6
        assert cfg.retrieval_partial_threshold == 0.3
        assert cfg.retrieval_initial_interval_hours == 24.0
        assert cfg.retrieval_max_interval_hours == 168.0
        assert cfg.retrieval_counselor_failure_streak == 3

    def test_dream_report_retrieval_fields_default(self):
        """T28: DreamReport has correct retrieval field defaults."""
        report = DreamReport()
        assert report.retrieval_practices == 0
        assert report.retrieval_accuracy is None
        assert report.retrieval_concerns == 0


# ==================================================================
# D5 Tests — Counselor integration (2 tests)
# ==================================================================


class TestD5Counselor:
    """Tests 29-30: Counselor integration."""

    @pytest.mark.asyncio
    async def test_counselor_handles_retrieval_practice_concern(self):
        """T29: Counselor updates CognitiveProfile on retrieval concern event."""
        from probos.cognitive.counselor import CounselorAgent, CognitiveProfile

        # Build a minimal Counselor via bypass
        counselor = object.__new__(CounselorAgent)
        counselor._cognitive_profiles = {
            "agent-A": CognitiveProfile(agent_id="agent-A"),
        }
        counselor._profile_store = None  # AD-541d: handler now checks this
        counselor._reminiscence_engine = None  # AD-541d: handler conditionally triggers
        counselor._reminiscence_concern_threshold = 3

        # Fire the handler directly
        await counselor._on_retrieval_practice_concern({
            "agent_id": "agent-A",
            "episodes_at_risk": 3,
            "avg_recall_accuracy": 0.25,
        })

        profile = counselor._cognitive_profiles["agent-A"]
        assert profile.retrieval_concerns == 3
        assert profile.last_retrieval_accuracy == 0.25

    def test_cognitive_profile_retrieval_fields(self):
        """T30: CognitiveProfile has retrieval fields with correct defaults."""
        from probos.cognitive.counselor import CognitiveProfile

        profile = CognitiveProfile()
        assert profile.retrieval_concerns == 0
        assert profile.last_retrieval_accuracy == 0.0
