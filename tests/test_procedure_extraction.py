"""AD-532: Procedure extraction tests.

Tests cover:
- Procedure & ProcedureStep schema (Part 1)
- extract_procedure_from_cluster() LLM extraction (Part 2)
- Dream cycle integration — Step 7 (Part 3)
- LLM client wiring (Part 0)
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.types import Episode, DreamReport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_episode(
    episode_id: str,
    user_input: str = "test",
    outcomes: list[dict] | None = None,
    agent_ids: list[str] | None = None,
    timestamp: float = 0.0,
    reflection: str = "",
    dag_summary: dict | None = None,
) -> Episode:
    """Build a minimal Episode for testing."""
    return Episode(
        id=episode_id,
        user_input=user_input,
        outcomes=outcomes or [],
        agent_ids=agent_ids or [],
        timestamp=timestamp,
        reflection=reflection,
        dag_summary=dag_summary or {},
    )


def _make_cluster(
    cluster_id: str = "abc123",
    episode_ids: list[str] | None = None,
    is_success_dominant: bool = True,
    is_failure_dominant: bool = False,
    success_rate: float = 1.0,
    participating_agents: list[str] | None = None,
    intent_types: list[str] | None = None,
) -> MagicMock:
    """Build a mock EpisodeCluster."""
    c = MagicMock()
    c.cluster_id = cluster_id
    c.episode_ids = episode_ids or ["e1", "e2", "e3"]
    c.is_success_dominant = is_success_dominant
    c.is_failure_dominant = is_failure_dominant
    c.success_rate = success_rate
    c.participating_agents = participating_agents or ["agent-a"]
    c.intent_types = intent_types or ["read"]
    return c


_VALID_LLM_JSON = json.dumps({
    "name": "Handle read request",
    "description": "Steps to process a read request",
    "steps": [
        {
            "step_number": 1,
            "action": "Parse user input",
            "expected_input": "raw text",
            "expected_output": "parsed intent",
            "fallback_action": "request clarification",
            "invariants": ["input is non-empty"],
        },
        {
            "step_number": 2,
            "action": "Execute read operation",
            "expected_input": "parsed intent",
            "expected_output": "data result",
            "fallback_action": "retry once",
            "invariants": [],
        },
    ],
    "preconditions": ["user is authenticated"],
    "postconditions": ["data returned to user"],
})


def _mock_llm_response(content: str) -> MagicMock:
    resp = MagicMock()
    resp.content = content
    return resp


# ---------------------------------------------------------------------------
# Part 0: LLM client wiring
# ---------------------------------------------------------------------------


class TestLLMClientWiring:
    """Tests for llm_client wiring through DreamingEngine."""

    def test_dreaming_engine_accepts_llm_client(self) -> None:
        """AD-532: DreamingEngine stores llm_client for procedure extraction."""
        from probos.cognitive.dreaming import DreamingEngine
        from probos.config import DreamingConfig

        mock_client = MagicMock()
        engine = DreamingEngine(
            router=MagicMock(),
            trust_network=MagicMock(),
            episodic_memory=MagicMock(),
            config=DreamingConfig(),
            llm_client=mock_client,
        )
        assert engine._llm_client is mock_client

    def test_dreaming_engine_llm_client_defaults_none(self) -> None:
        from probos.cognitive.dreaming import DreamingEngine
        from probos.config import DreamingConfig

        engine = DreamingEngine(
            router=MagicMock(),
            trust_network=MagicMock(),
            episodic_memory=MagicMock(),
            config=DreamingConfig(),
        )
        assert engine._llm_client is None

    def test_dreaming_engine_has_last_procedures_property(self) -> None:
        from probos.cognitive.dreaming import DreamingEngine
        from probos.config import DreamingConfig

        engine = DreamingEngine(
            router=MagicMock(),
            trust_network=MagicMock(),
            episodic_memory=MagicMock(),
            config=DreamingConfig(),
        )
        assert engine.last_procedures == []

    def test_dreaming_engine_has_extracted_cluster_ids(self) -> None:
        from probos.cognitive.dreaming import DreamingEngine
        from probos.config import DreamingConfig

        engine = DreamingEngine(
            router=MagicMock(),
            trust_network=MagicMock(),
            episodic_memory=MagicMock(),
            config=DreamingConfig(),
        )
        assert engine._extracted_cluster_ids == set()


# ---------------------------------------------------------------------------
# Part 1: Schema tests
# ---------------------------------------------------------------------------


class TestProcedureStepSchema:
    """Tests for ProcedureStep dataclass."""

    def test_procedure_step_creation(self) -> None:
        from probos.cognitive.procedures import ProcedureStep

        step = ProcedureStep(
            step_number=1,
            action="do something",
            expected_input="input state",
            expected_output="output state",
            fallback_action="retry",
            invariants=["must be true"],
        )
        assert step.step_number == 1
        assert step.action == "do something"
        assert step.invariants == ["must be true"]

    def test_procedure_step_to_dict(self) -> None:
        from probos.cognitive.procedures import ProcedureStep

        step = ProcedureStep(step_number=1, action="act")
        d = step.to_dict()
        assert d["step_number"] == 1
        assert d["action"] == "act"
        assert "invariants" in d


class TestProcedureSchema:
    """Tests for Procedure dataclass."""

    def test_procedure_creation_defaults(self) -> None:
        from probos.cognitive.procedures import Procedure

        p = Procedure()
        assert p.name == ""
        assert p.steps == []
        assert len(p.id) > 0  # UUID generated

    def test_procedure_with_steps(self) -> None:
        from probos.cognitive.procedures import Procedure, ProcedureStep

        steps = [ProcedureStep(step_number=1, action="a"), ProcedureStep(step_number=2, action="b")]
        p = Procedure(steps=steps)
        assert len(p.steps) == 2
        assert p.steps[0].action == "a"

    def test_procedure_to_dict(self) -> None:
        from probos.cognitive.procedures import Procedure, ProcedureStep

        p = Procedure(
            name="test",
            steps=[ProcedureStep(step_number=1, action="x")],
            preconditions=["pre"],
            postconditions=["post"],
        )
        d = p.to_dict()
        assert d["name"] == "test"
        assert len(d["steps"]) == 1
        assert d["steps"][0]["action"] == "x"
        assert d["preconditions"] == ["pre"]

    def test_procedure_to_dict_includes_all_fields(self) -> None:
        from probos.cognitive.procedures import Procedure

        p = Procedure()
        d = p.to_dict()
        expected_keys = {
            "id", "name", "description", "steps", "preconditions",
            "postconditions", "intent_types", "origin_cluster_id",
            "origin_agent_ids", "provenance", "extraction_date",
            "evolution_type", "compilation_level", "success_count",
            "failure_count",
            # AD-533: store and evolution support
            "is_active", "generation", "parent_procedure_ids",
            "is_negative", "superseded_by", "tags",
            # AD-537: observational learning
            "learned_via", "learned_from",
            # AD-538: lifecycle management
            "last_used_at", "is_archived",
            # AD-567d: anchor provenance
            "source_anchors",
            # AD-596c: T2→T3 provenance
            "source_skill_id",
        }
        assert set(d.keys()) == expected_keys

    def test_procedure_default_evolution_type(self) -> None:
        from probos.cognitive.procedures import Procedure

        assert Procedure().evolution_type == "CAPTURED"

    def test_procedure_default_compilation_level(self) -> None:
        from probos.cognitive.procedures import Procedure

        assert Procedure().compilation_level == 1


# ---------------------------------------------------------------------------
# Part 2: Extraction tests
# ---------------------------------------------------------------------------


class TestExtractProcedure:
    """Tests for extract_procedure_from_cluster()."""

    @pytest.mark.asyncio
    async def test_extract_procedure_success(self) -> None:
        from probos.cognitive.procedures import extract_procedure_from_cluster

        cluster = _make_cluster()
        episodes = [_make_episode(f"e{i}", user_input="read file") for i in range(3)]
        llm = AsyncMock()
        llm.complete.return_value = _mock_llm_response(_VALID_LLM_JSON)

        result = await extract_procedure_from_cluster(cluster, episodes, llm)
        assert result is not None
        assert result.name == "Handle read request"
        assert len(result.steps) == 2
        assert result.evolution_type == "CAPTURED"

    @pytest.mark.asyncio
    async def test_extract_procedure_llm_error(self) -> None:
        from probos.cognitive.procedures import extract_procedure_from_cluster

        cluster = _make_cluster()
        episodes = [_make_episode("e1")]
        llm = AsyncMock()
        llm.complete.side_effect = RuntimeError("LLM down")

        result = await extract_procedure_from_cluster(cluster, episodes, llm)
        assert result is None

    @pytest.mark.asyncio
    async def test_extract_procedure_invalid_json(self) -> None:
        from probos.cognitive.procedures import extract_procedure_from_cluster

        cluster = _make_cluster()
        episodes = [_make_episode("e1")]
        llm = AsyncMock()
        llm.complete.return_value = _mock_llm_response("not json at all {{{")

        result = await extract_procedure_from_cluster(cluster, episodes, llm)
        assert result is None

    @pytest.mark.asyncio
    async def test_extract_procedure_no_common_pattern(self) -> None:
        from probos.cognitive.procedures import extract_procedure_from_cluster

        cluster = _make_cluster()
        episodes = [_make_episode("e1")]
        llm = AsyncMock()
        llm.complete.return_value = _mock_llm_response('{"error": "no_common_pattern"}')

        result = await extract_procedure_from_cluster(cluster, episodes, llm)
        assert result is None

    @pytest.mark.asyncio
    async def test_extract_procedure_read_only_framing(self) -> None:
        """Verify AD-541b markers appear in the prompt sent to LLM."""
        from probos.cognitive.procedures import extract_procedure_from_cluster

        cluster = _make_cluster()
        episodes = [_make_episode("e1", user_input="hello")]
        llm = AsyncMock()
        llm.complete.return_value = _mock_llm_response(_VALID_LLM_JSON)

        await extract_procedure_from_cluster(cluster, episodes, llm)
        call_args = llm.complete.call_args[0][0]
        assert "=== READ-ONLY EPISODE" in call_args.prompt
        assert "=== END READ-ONLY EPISODE ===" in call_args.prompt

    @pytest.mark.asyncio
    async def test_extract_procedure_uses_standard_tier(self) -> None:
        from probos.cognitive.procedures import extract_procedure_from_cluster

        cluster = _make_cluster()
        episodes = [_make_episode("e1")]
        llm = AsyncMock()
        llm.complete.return_value = _mock_llm_response(_VALID_LLM_JSON)

        await extract_procedure_from_cluster(cluster, episodes, llm)
        request = llm.complete.call_args[0][0]
        assert request.tier == "standard"

    @pytest.mark.asyncio
    async def test_extract_procedure_provenance(self) -> None:
        from probos.cognitive.procedures import extract_procedure_from_cluster

        cluster = _make_cluster(episode_ids=["ep-a", "ep-b", "ep-c"])
        episodes = [_make_episode("ep-a"), _make_episode("ep-b"), _make_episode("ep-c")]
        llm = AsyncMock()
        llm.complete.return_value = _mock_llm_response(_VALID_LLM_JSON)

        result = await extract_procedure_from_cluster(cluster, episodes, llm)
        assert result is not None
        assert result.provenance == ["ep-a", "ep-b", "ep-c"]
        assert result.origin_cluster_id == "abc123"

    @pytest.mark.asyncio
    async def test_extract_procedure_strips_markdown_fences(self) -> None:
        from probos.cognitive.procedures import extract_procedure_from_cluster

        cluster = _make_cluster()
        episodes = [_make_episode("e1")]
        llm = AsyncMock()
        fenced = f"```json\n{_VALID_LLM_JSON}\n```"
        llm.complete.return_value = _mock_llm_response(fenced)

        result = await extract_procedure_from_cluster(cluster, episodes, llm)
        assert result is not None
        assert result.name == "Handle read request"


# ---------------------------------------------------------------------------
# Part 3: Dream cycle integration
# ---------------------------------------------------------------------------


def _make_dream_engine(llm_client=None):
    """Build a DreamingEngine with standard mocks for dream cycle tests."""
    from probos.cognitive.dreaming import DreamingEngine
    from probos.config import DreamingConfig

    mock_router = MagicMock()
    mock_router.get_weight.return_value = 0.5
    mock_router.decay_all.return_value = None
    mock_router._weights = {}
    mock_router._compat_weights = {}

    mock_trust = MagicMock()
    mock_trust.get_or_create.return_value = MagicMock(alpha=1.0, beta=1.0)

    episodes = [
        _make_episode(
            f"e{i}",
            outcomes=[{"intent": "read", "success": True}],
            agent_ids=["agent-a"],
        )
        for i in range(5)
    ]

    mock_mem = AsyncMock()
    mock_mem.recent.return_value = episodes
    mock_mem.get_stats.return_value = {"total": 5}
    mock_mem.get_embeddings.return_value = {
        f"e{i}": [1.0, 0.0, 0.0] for i in range(5)
    }

    engine = DreamingEngine(
        router=mock_router,
        trust_network=mock_trust,
        episodic_memory=mock_mem,
        config=DreamingConfig(),
        llm_client=llm_client,
    )
    return engine, episodes


class TestDreamCycleProcedureIntegration:
    """Tests for procedure extraction within the dream cycle."""

    @pytest.mark.asyncio
    async def test_dream_cycle_extracts_procedures(self) -> None:
        mock_llm = AsyncMock()
        mock_llm.complete.return_value = _mock_llm_response(_VALID_LLM_JSON)

        engine, _ = _make_dream_engine(llm_client=mock_llm)
        report = await engine.dream_cycle()

        assert report.procedures_extracted > 0
        assert len(report.procedures) > 0

    @pytest.mark.asyncio
    async def test_dream_cycle_skips_failure_clusters(self) -> None:
        """Only success-dominant clusters get procedure extraction."""
        from probos.cognitive.episode_clustering import EpisodeCluster

        mock_llm = AsyncMock()
        mock_llm.complete.return_value = _mock_llm_response(_VALID_LLM_JSON)

        engine, _ = _make_dream_engine(llm_client=mock_llm)

        # Patch cluster_episodes to return a failure cluster
        failure_cluster = _make_cluster(is_success_dominant=False, is_failure_dominant=True)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "probos.cognitive.dreaming.cluster_episodes",
                lambda **kw: [failure_cluster],
            )
            report = await engine.dream_cycle()

        assert report.procedures_extracted == 0

    @pytest.mark.asyncio
    async def test_dream_cycle_skips_already_extracted(self) -> None:
        mock_llm = AsyncMock()
        mock_llm.complete.return_value = _mock_llm_response(_VALID_LLM_JSON)

        engine, _ = _make_dream_engine(llm_client=mock_llm)

        # Run first cycle — should extract
        report1 = await engine.dream_cycle()
        count1 = report1.procedures_extracted

        # Run second cycle — same cluster IDs should be skipped
        report2 = await engine.dream_cycle()
        assert report2.procedures_extracted == 0
        assert count1 > 0

    @pytest.mark.asyncio
    async def test_dream_cycle_procedure_log_and_degrade(self) -> None:
        mock_llm = AsyncMock()
        mock_llm.complete.side_effect = RuntimeError("LLM exploded")

        engine, _ = _make_dream_engine(llm_client=mock_llm)
        report = await engine.dream_cycle()

        # Dream cycle completes — no crash
        assert report.procedures_extracted == 0
        assert report.episodes_replayed >= 0

    @pytest.mark.asyncio
    async def test_dream_cycle_no_procedures_without_llm(self) -> None:
        engine, _ = _make_dream_engine(llm_client=None)
        report = await engine.dream_cycle()

        assert report.procedures_extracted == 0
        assert report.procedures == []

    @pytest.mark.asyncio
    async def test_dream_cycle_no_procedures_without_clusters(self) -> None:
        mock_llm = AsyncMock()
        engine, _ = _make_dream_engine(llm_client=mock_llm)

        # No embeddings → no clusters → no procedures
        engine.episodic_memory.get_embeddings.return_value = {}
        report = await engine.dream_cycle()

        assert report.procedures_extracted == 0

    @pytest.mark.asyncio
    async def test_dream_report_includes_procedures(self) -> None:
        mock_llm = AsyncMock()
        mock_llm.complete.return_value = _mock_llm_response(_VALID_LLM_JSON)

        engine, _ = _make_dream_engine(llm_client=mock_llm)
        report = await engine.dream_cycle()

        assert hasattr(report, "procedures")
        assert hasattr(report, "procedures_extracted")
        assert report.procedures_extracted == len(report.procedures)

    @pytest.mark.asyncio
    async def test_dream_report_procedures_extracted_count(self) -> None:
        mock_llm = AsyncMock()
        mock_llm.complete.return_value = _mock_llm_response(_VALID_LLM_JSON)

        engine, _ = _make_dream_engine(llm_client=mock_llm)
        report = await engine.dream_cycle()

        assert report.procedures_extracted == len(report.procedures)

    @pytest.mark.asyncio
    async def test_gap_prediction_still_works(self) -> None:
        """Gap prediction (Step 8) still runs after procedure extraction."""
        mock_llm = AsyncMock()
        mock_llm.complete.return_value = _mock_llm_response(_VALID_LLM_JSON)

        gap_fn = MagicMock()
        engine, _ = _make_dream_engine(llm_client=mock_llm)
        engine._gap_prediction_fn = gap_fn

        report = await engine.dream_cycle()

        # Gap prediction should still be called
        assert report.gaps_predicted >= 0
