"""AD-646b: Chain Cognitive Parity — Tests.

Verifies that chain ward_room path receives self-monitoring, telemetry,
oracle context, cold-start note, rich source attribution, self-recognition
cue, and that prompts render new data without double-rendering in Prior Data.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.sub_task import SubTaskResult, SubTaskSpec, SubTaskType
from probos.cognitive.sub_tasks.analyze import _build_thread_analysis_prompt
from probos.cognitive.sub_tasks.compose import _build_user_prompt
from probos.cognitive.sub_tasks.query import (
    _query_self_monitoring,
    _query_introspective_telemetry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent(**kwargs) -> CognitiveAgent:
    agent = CognitiveAgent(agent_id="test-agent", instructions="Test agent instructions.")
    agent.callsign = "LaForge"
    agent.agent_type = "test_agent"
    agent._runtime = kwargs.get("runtime", None)
    return agent


def _make_runtime(trust_score=0.75, is_cold_start=False):
    rt = MagicMock()
    rt.trust_network.get_score.return_value = trust_score
    rt.is_cold_start = is_cold_start
    rt.ontology.get_crew_context.return_value = {
        "identity": {"callsign": "LaForge", "post": "Chief Engineer"},
        "department": {"name": "Engineering"},
        "reports_to": "Captain",
        "direct_reports": ["Barclay"],
        "peers": ["Scotty"],
        "vessel": {"name": "ProbOS", "version": "0.4", "alert_condition": "GREEN"},
    }
    return rt


def _make_spec():
    return SubTaskSpec(
        sub_task_type=SubTaskType.QUERY,
        name="test-query",
        context_keys=(),
    )


def _make_query_result(**data):
    return SubTaskResult(
        sub_task_type=SubTaskType.QUERY,
        name="query-thread-context",
        result=data,
        duration_ms=1.0,
        success=True,
    )


# ---------------------------------------------------------------------------
# Test 1: _query_self_monitoring detects repetition in DM thread
# ---------------------------------------------------------------------------

class TestSelfMonitoringRepetition:

    @pytest.mark.asyncio
    async def test_detects_repetition_in_dm_thread(self):
        rt = MagicMock()
        rt.ward_room = AsyncMock()
        rt.ward_room.get_posts_by_author = AsyncMock(return_value=[
            {"body": "The latency spike was caused by the EPS grid."},
            {"body": "The latency spike was caused by the EPS grid overload."},
            {"body": "The EPS grid caused the latency spike we observed."},
        ])
        context = {
            "params": {
                "channel_name": "dm-agent",
                "thread_id": "t1",
                "callsign": "LaForge",
            },
        }
        result = await _query_self_monitoring(rt, _make_spec(), context)
        assert "self-similarity" in result["self_monitoring"]


# ---------------------------------------------------------------------------
# Test 2: _query_self_monitoring returns empty for non-DM channels
# ---------------------------------------------------------------------------

class TestSelfMonitoringNonDM:

    @pytest.mark.asyncio
    async def test_returns_empty_for_non_dm(self):
        rt = MagicMock()
        context = {
            "params": {"channel_name": "engineering", "thread_id": "t1"},
        }
        result = await _query_self_monitoring(rt, _make_spec(), context)
        assert result["self_monitoring"] == ""


# ---------------------------------------------------------------------------
# Test 3: _query_self_monitoring returns empty for low similarity
# ---------------------------------------------------------------------------

class TestSelfMonitoringLowSim:

    @pytest.mark.asyncio
    async def test_returns_empty_for_low_similarity(self):
        rt = MagicMock()
        rt.ward_room = AsyncMock()
        rt.ward_room.get_posts_by_author = AsyncMock(return_value=[
            {"body": "The warp core needs recalibration after the last jump."},
            {"body": "Counselor, crew morale seems high after the shore leave."},
            {"body": "I recommend we run diagnostics on the deflector array."},
        ])
        context = {
            "params": {
                "channel_name": "dm-agent",
                "thread_id": "t1",
                "callsign": "LaForge",
            },
        }
        result = await _query_self_monitoring(rt, _make_spec(), context)
        assert result["self_monitoring"] == ""


# ---------------------------------------------------------------------------
# Test 4: _query_introspective_telemetry fires for self-referential text
# ---------------------------------------------------------------------------

class TestTelemetryFires:

    @pytest.mark.asyncio
    async def test_fires_for_introspective_text(self):
        rt = MagicMock()
        svc = AsyncMock()
        svc.get_full_snapshot = AsyncMock(return_value={"memory": {}})
        svc.render_telemetry_context = MagicMock(
            return_value="--- Your Telemetry ---\nMemory: 42 episodes",
        )
        rt._introspective_telemetry = svc
        context = {
            "params": {"title": "how is your memory working", "text": ""},
            "_agent_id": "test-agent",
        }
        result = await _query_introspective_telemetry(rt, _make_spec(), context)
        assert "Telemetry" in result["introspective_telemetry"]


# ---------------------------------------------------------------------------
# Test 5: _query_introspective_telemetry returns empty for non-introspective
# ---------------------------------------------------------------------------

class TestTelemetryNonIntrospective:

    @pytest.mark.asyncio
    async def test_returns_empty_for_non_introspective(self):
        rt = MagicMock()
        context = {
            "params": {"title": "Weather report for today", "text": ""},
        }
        result = await _query_introspective_telemetry(rt, _make_spec(), context)
        assert result["introspective_telemetry"] == ""


# ---------------------------------------------------------------------------
# Test 6: _query_introspective_telemetry degrades when service unavailable
# ---------------------------------------------------------------------------

class TestTelemetryDegrades:

    @pytest.mark.asyncio
    async def test_degrades_when_no_service(self):
        rt = MagicMock(spec=[])  # No _introspective_telemetry attribute
        context = {
            "params": {"title": "how is your memory", "text": ""},
        }
        result = await _query_introspective_telemetry(rt, _make_spec(), context)
        assert result["introspective_telemetry"] == ""


# ---------------------------------------------------------------------------
# Test 7: Baseline produces cold-start note
# ---------------------------------------------------------------------------

class TestColdStartNote:

    def test_cold_start_note_present(self):
        rt = _make_runtime(is_cold_start=True)
        agent = _make_agent(runtime=rt)
        with patch.object(agent, '_build_temporal_context', return_value=""):
            result = agent._build_cognitive_baseline({})
        assert "_cold_start_note" in result
        assert "fresh start" in result["_cold_start_note"]


# ---------------------------------------------------------------------------
# Test 8: Baseline produces NO cold-start note when False
# ---------------------------------------------------------------------------

class TestNoColdStartNote:

    def test_no_cold_start_note(self):
        rt = _make_runtime(is_cold_start=False)
        agent = _make_agent(runtime=rt)
        with patch.object(agent, '_build_temporal_context', return_value=""):
            result = agent._build_cognitive_baseline({})
        assert "_cold_start_note" not in result


# ---------------------------------------------------------------------------
# Test 9: Baseline produces rich source attribution from dataclass
# ---------------------------------------------------------------------------

class TestRichSourceAttribution:

    def test_rich_source_attribution(self):
        from probos.cognitive.source_governance import (
            KnowledgeSource,
            SourceAttribution,
            RetrievalStrategy,
        )
        attr = SourceAttribution(
            retrieval_strategy=RetrievalStrategy.DEEP,
            primary_source=KnowledgeSource.EPISODIC,
            episodic_count=3,
            procedural_count=0,
            oracle_used=True,
            source_framing_authority="authoritative",
            confabulation_rate=0.0,
            budget_adjustment=1.0,
        )
        rt = _make_runtime()
        agent = _make_agent(runtime=rt)
        observation = {"_source_attribution": attr}
        with patch.object(agent, '_build_temporal_context', return_value=""):
            result = agent._build_cognitive_baseline(observation)
        text = result["_source_attribution_text"]
        assert "<source_awareness>" in text
        assert "episodic memory (3 episodes)" in text
        assert "ship's records" in text
        assert "Primary basis: episodic" in text


# ---------------------------------------------------------------------------
# Test 10: Rich attribution overrides simplified version
# ---------------------------------------------------------------------------

class TestRichOverridesSimplified:

    def test_rich_overrides_simplified(self):
        from probos.cognitive.source_governance import (
            KnowledgeSource,
            SourceAttribution,
            RetrievalStrategy,
        )
        attr = SourceAttribution(
            retrieval_strategy=RetrievalStrategy.SHALLOW,
            primary_source=KnowledgeSource.EPISODIC,
            episodic_count=2,
            procedural_count=0,
            oracle_used=False,
            source_framing_authority="supplementary",
            confabulation_rate=0.0,
            budget_adjustment=1.0,
        )
        rt = _make_runtime()
        agent = _make_agent(runtime=rt)
        observation = {
            "recent_memories": [{"content": "ep1"}, {"content": "ep2"}],
            "_source_attribution": attr,
        }
        with patch.object(agent, '_build_temporal_context', return_value=""):
            result = agent._build_cognitive_baseline(observation)
        # Rich version (with <source_awareness>) should have won
        assert "<source_awareness>" in result["_source_attribution_text"]


# ---------------------------------------------------------------------------
# Test 11: Baseline produces self-recognition cue
# ---------------------------------------------------------------------------

class TestSelfRecognitionCue:

    def test_self_recognition_cue(self):
        rt = _make_runtime()
        agent = _make_agent(runtime=rt)
        observation = {"context": "Hey @LaForge, what do you think about the warp core?"}
        with patch.object(agent, '_build_temporal_context', return_value=""):
            result = agent._build_cognitive_baseline(observation)
        assert "_self_recognition_cue" in result
        assert result["_self_recognition_cue"]  # non-empty


# ---------------------------------------------------------------------------
# Test 12: Thread analysis prompt renders oracle context
# ---------------------------------------------------------------------------

class TestAnalyzeOracleContext:

    def test_oracle_in_analysis_prompt(self):
        context = {
            "context": "Thread content here",
            "_agent_type": "agent",
            "_agent_rank": None,
            "_skill_profile": None,
            "_formatted_memories": "",
            "_oracle_context": "Ship's Records: power grid stable",
        }
        _sys, user = _build_thread_analysis_prompt(context, [], "LaForge", "Engineering")
        assert "Cross-Tier Knowledge" in user
        assert "power grid stable" in user


# ---------------------------------------------------------------------------
# Test 13: Thread analysis prompt renders self-monitoring from QUERY
# ---------------------------------------------------------------------------

class TestAnalyzeSelfMonitoring:

    def test_self_monitoring_in_analysis_prompt(self):
        context = {
            "context": "Thread content",
            "_agent_type": "agent",
            "_agent_rank": None,
            "_skill_profile": None,
            "_formatted_memories": "",
        }
        prior = [_make_query_result(
            self_monitoring="WARNING: 80% self-similarity",
            thread_metadata={"title": "Test"},
        )]
        _sys, user = _build_thread_analysis_prompt(context, prior, "LaForge", "Engineering")
        assert "Self-Monitoring" in user
        assert "80% self-similarity" in user


# ---------------------------------------------------------------------------
# Test 14: Thread analysis prompt renders telemetry from QUERY
# ---------------------------------------------------------------------------

class TestAnalyzeTelemetry:

    def test_telemetry_in_analysis_prompt(self):
        context = {
            "context": "Thread content",
            "_agent_type": "agent",
            "_agent_rank": None,
            "_skill_profile": None,
            "_formatted_memories": "",
        }
        prior = [_make_query_result(
            introspective_telemetry="--- Your Telemetry ---\nMemory: 42 episodes",
        )]
        _sys, user = _build_thread_analysis_prompt(context, prior, "LaForge", "Engineering")
        assert "Your Telemetry" in user


# ---------------------------------------------------------------------------
# Test 15: Compose user prompt renders oracle context
# ---------------------------------------------------------------------------

class TestComposeOracleContext:

    def test_oracle_in_compose_prompt(self):
        context = {
            "context": "Thread content",
            "_oracle_context": "Duty logs from yesterday",
        }
        result = _build_user_prompt(context, [])
        assert "Cross-Tier Knowledge" in result
        assert "Duty logs from yesterday" in result


# ---------------------------------------------------------------------------
# Test 16: Prior Data excludes dedicated AD-646b keys
# ---------------------------------------------------------------------------

class TestPriorDataExclusion:

    def test_prior_data_excludes_dedicated_keys(self):
        context = {"context": "Thread content"}
        prior = [_make_query_result(
            thread_metadata={"title": "Test thread"},
            self_monitoring="WARNING: repetition detected",
            introspective_telemetry="telemetry text here",
        )]
        result = _build_user_prompt(context, prior)
        # Self-monitoring should be in dedicated section, not in Prior Data as raw key
        assert "## Self-Monitoring" in result
        assert "WARNING: repetition detected" in result
        # Prior Data should have thread_metadata but NOT self_monitoring/introspective_telemetry
        prior_data_idx = result.index("## Prior Data")
        self_mon_idx = result.index("## Self-Monitoring")
        # Prior Data section should not contain the raw keys
        prior_data_section = result[prior_data_idx:self_mon_idx]
        assert "self_monitoring" not in prior_data_section
        assert "introspective_telemetry" not in prior_data_section


# ---------------------------------------------------------------------------
# Test 17: Ward room chain context_keys include new operations
# ---------------------------------------------------------------------------

class TestChainContextKeys:

    def test_ward_room_chain_includes_new_keys(self):
        agent = _make_agent()
        observation = {
            "intent": "ward_room_notification",
            "params": {"channel_name": "general", "thread_id": "t1"},
        }
        chain = agent._build_chain_for_intent(observation)
        assert chain is not None
        # Find the QUERY step
        query_step = None
        for step in chain.steps:
            if step.sub_task_type == SubTaskType.QUERY:
                query_step = step
                break
        assert query_step is not None
        assert "self_monitoring" in query_step.context_keys
        assert "introspective_telemetry" in query_step.context_keys


# ---------------------------------------------------------------------------
# Test 18: Full chain regression — proactive path still works
# ---------------------------------------------------------------------------

class TestProactivePathRegression:

    def test_proactive_path_still_works(self):
        rt = _make_runtime()
        agent = _make_agent(runtime=rt)
        context_parts = {
            "recent_memories": [{"content": "ep1"}],
            "self_monitoring": {"cognitive_zone": "GREEN"},
            "introspective_telemetry": "CPU: 45%",
            "ontology": {
                "identity": {"callsign": "LaForge", "post": "Chief Engineer"},
                "department": {"name": "Engineering"},
                "vessel": {"name": "ProbOS", "version": "0.4", "alert_condition": "GREEN"},
            },
        }
        observation = {
            "recent_memories": [{"content": "ep1"}],
            "context": "Discussion about @LaForge performance",
        }

        with patch.object(agent, '_build_temporal_context', return_value="Current time: 2026-04-19"):
            result = agent._build_cognitive_state(context_parts, observation=observation)

        # Baseline keys
        assert "_temporal_context" in result
        assert "_agent_metrics" in result
        assert "_confabulation_guard" in result
        # Extension keys
        assert "_self_monitoring" in result
        assert "_introspective_telemetry" in result
        # New baseline keys
        assert "_self_recognition_cue" in result  # @LaForge in context
        # No cold-start note (is_cold_start=False by default)
        assert "_cold_start_note" not in result
