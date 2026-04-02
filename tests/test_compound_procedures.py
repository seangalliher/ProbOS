"""AD-532d: Compound (multi-agent) procedure extraction tests.

Tests cover:
- ProcedureStep agent_role field (Test Class 1)
- _COMPOUND_SYSTEM_PROMPT content (Test Class 2)
- extract_compound_procedure_from_cluster() (Test Class 3)
- Dream cycle routing (Test Class 4)
- Replay formatting enhancement (Test Class 5)
- End-to-end pipeline (Test Class 6)
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

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
    return Episode(
        id=episode_id,
        user_input=user_input,
        outcomes=outcomes or [],
        agent_ids=agent_ids or ["agent-a", "agent-b"],
        timestamp=timestamp,
        reflection=reflection,
        dag_summary=dag_summary or {},
    )


def _make_cluster(
    cluster_id: str = "compound-001",
    episode_ids: list[str] | None = None,
    is_success_dominant: bool = True,
    is_failure_dominant: bool = False,
    success_rate: float = 0.9,
    participating_agents: list[str] | None = None,
    intent_types: list[str] | None = None,
) -> MagicMock:
    c = MagicMock()
    c.cluster_id = cluster_id
    c.episode_ids = episode_ids or ["e1", "e2", "e3"]
    c.is_success_dominant = is_success_dominant
    c.is_failure_dominant = is_failure_dominant
    c.success_rate = success_rate
    c.participating_agents = participating_agents or ["worf", "laforge"]
    c.intent_types = intent_types or ["security_review"]
    return c


_VALID_COMPOUND_JSON = json.dumps({
    "name": "Security review then engineering fix",
    "description": "Security analyzes vulnerability, engineering implements patch",
    "steps": [
        {
            "step_number": 1,
            "action": "Analyze code for vulnerability patterns",
            "expected_input": "code diff submitted for review",
            "expected_output": "vulnerability report with severity",
            "fallback_action": "escalate to senior analyst",
            "invariants": ["code must be parseable"],
            "agent_role": "security_analysis",
        },
        {
            "step_number": 2,
            "action": "Implement remediation patch",
            "expected_input": "vulnerability report with severity",
            "expected_output": "patched code with tests",
            "fallback_action": "request manual review",
            "invariants": ["must not break existing tests"],
            "agent_role": "engineering_implementation",
        },
    ],
    "preconditions": ["code changes pending review"],
    "postconditions": ["vulnerability remediated", "tests pass"],
})

_VALID_STANDARD_JSON = json.dumps({
    "name": "Simple read",
    "description": "Read a file",
    "steps": [
        {
            "step_number": 1,
            "action": "Read the requested file",
            "expected_input": "file path",
            "expected_output": "file contents",
            "fallback_action": "report not found",
            "invariants": [],
        },
    ],
    "preconditions": ["file exists"],
    "postconditions": ["contents returned"],
})


def _mock_llm_response(content: str) -> MagicMock:
    resp = MagicMock()
    resp.content = content
    return resp


def _make_episodes(ids: list[str]) -> list[Episode]:
    return [_make_episode(eid) for eid in ids]


# ---------------------------------------------------------------------------
# Test Class 1: ProcedureStep agent_role
# ---------------------------------------------------------------------------


class TestProcedureStepAgentRole:
    """Tests for the agent_role field on ProcedureStep."""

    def test_agent_role_default_empty(self) -> None:
        from probos.cognitive.procedures import ProcedureStep
        step = ProcedureStep(step_number=1, action="do something")
        assert step.agent_role == ""

    def test_agent_role_set(self) -> None:
        from probos.cognitive.procedures import ProcedureStep
        step = ProcedureStep(step_number=1, action="analyze", agent_role="security_analysis")
        assert step.agent_role == "security_analysis"

    def test_to_dict_includes_agent_role(self) -> None:
        from probos.cognitive.procedures import ProcedureStep
        step = ProcedureStep(step_number=1, action="a", agent_role="engineering")
        d = step.to_dict()
        assert "agent_role" in d
        assert d["agent_role"] == "engineering"

    def test_to_dict_agent_role_empty(self) -> None:
        from probos.cognitive.procedures import ProcedureStep
        step = ProcedureStep(step_number=1, action="a")
        d = step.to_dict()
        assert "agent_role" in d
        assert d["agent_role"] == ""

    def test_build_steps_parses_agent_role(self) -> None:
        from probos.cognitive.procedures import _build_steps_from_data
        data = {
            "steps": [
                {"step_number": 1, "action": "scan", "agent_role": "security_analysis"}
            ]
        }
        steps = _build_steps_from_data(data)
        assert len(steps) == 1
        assert steps[0].agent_role == "security_analysis"

    def test_build_steps_missing_agent_role_defaults_empty(self) -> None:
        from probos.cognitive.procedures import _build_steps_from_data
        data = {
            "steps": [
                {"step_number": 1, "action": "scan"}
            ]
        }
        steps = _build_steps_from_data(data)
        assert steps[0].agent_role == ""

    def test_build_steps_backward_compatible(self) -> None:
        """Existing step data without agent_role key works."""
        from probos.cognitive.procedures import _build_steps_from_data
        data = {
            "steps": [
                {
                    "step_number": 1,
                    "action": "read file",
                    "expected_input": "path",
                    "expected_output": "data",
                    "fallback_action": "retry",
                    "invariants": ["file exists"],
                }
            ]
        }
        steps = _build_steps_from_data(data)
        assert steps[0].agent_role == ""
        assert steps[0].action == "read file"


# ---------------------------------------------------------------------------
# Test Class 2: Compound system prompt
# ---------------------------------------------------------------------------


class TestCompoundSystemPrompt:
    """Tests for the _COMPOUND_SYSTEM_PROMPT content."""

    def test_compound_prompt_exists(self) -> None:
        from probos.cognitive.procedures import _COMPOUND_SYSTEM_PROMPT
        assert isinstance(_COMPOUND_SYSTEM_PROMPT, str)
        assert len(_COMPOUND_SYSTEM_PROMPT) > 100

    def test_compound_prompt_mentions_agent_role(self) -> None:
        from probos.cognitive.procedures import _COMPOUND_SYSTEM_PROMPT
        assert "agent_role" in _COMPOUND_SYSTEM_PROMPT

    def test_compound_prompt_mentions_handoff(self) -> None:
        from probos.cognitive.procedures import _COMPOUND_SYSTEM_PROMPT
        assert "handoff" in _COMPOUND_SYSTEM_PROMPT.lower()

    def test_compound_prompt_read_only_framing(self) -> None:
        from probos.cognitive.procedures import _COMPOUND_SYSTEM_PROMPT
        # AD-541b constraints
        assert "do not reconstruct narratives" in _COMPOUND_SYSTEM_PROMPT.lower()


# ---------------------------------------------------------------------------
# Test Class 3: extract_compound_procedure_from_cluster()
# ---------------------------------------------------------------------------


class TestExtractCompoundProcedure:
    """Tests for the compound extraction function."""

    @pytest.mark.asyncio
    async def test_basic_compound_extraction(self) -> None:
        from probos.cognitive.procedures import extract_compound_procedure_from_cluster

        llm = AsyncMock()
        llm.complete.return_value = _mock_llm_response(_VALID_COMPOUND_JSON)

        result = await extract_compound_procedure_from_cluster(
            _make_cluster(), _make_episodes(["e1", "e2"]), llm,
        )

        assert result is not None
        assert len(result.steps) == 2
        assert result.steps[0].agent_role == "security_analysis"
        assert result.steps[1].agent_role == "engineering_implementation"

    @pytest.mark.asyncio
    async def test_compound_extraction_origin_agent_ids(self) -> None:
        from probos.cognitive.procedures import extract_compound_procedure_from_cluster

        llm = AsyncMock()
        llm.complete.return_value = _mock_llm_response(_VALID_COMPOUND_JSON)

        cluster = _make_cluster(participating_agents=["worf", "laforge", "data"])
        result = await extract_compound_procedure_from_cluster(
            cluster, _make_episodes(["e1"]), llm,
        )

        assert result is not None
        assert result.origin_agent_ids == ["worf", "laforge", "data"]

    @pytest.mark.asyncio
    async def test_compound_extraction_llm_decline(self) -> None:
        from probos.cognitive.procedures import extract_compound_procedure_from_cluster

        llm = AsyncMock()
        llm.complete.return_value = _mock_llm_response(
            json.dumps({"error": "no_compound_pattern"})
        )

        result = await extract_compound_procedure_from_cluster(
            _make_cluster(), _make_episodes(["e1"]), llm,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_compound_extraction_llm_failure(self) -> None:
        from probos.cognitive.procedures import extract_compound_procedure_from_cluster

        llm = AsyncMock()
        llm.complete.side_effect = RuntimeError("boom")

        result = await extract_compound_procedure_from_cluster(
            _make_cluster(), _make_episodes(["e1"]), llm,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_compound_extraction_malformed_json(self) -> None:
        from probos.cognitive.procedures import extract_compound_procedure_from_cluster

        llm = AsyncMock()
        llm.complete.return_value = _mock_llm_response("not json!")

        result = await extract_compound_procedure_from_cluster(
            _make_cluster(), _make_episodes(["e1"]), llm,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_compound_extraction_markdown_fences(self) -> None:
        from probos.cognitive.procedures import extract_compound_procedure_from_cluster

        llm = AsyncMock()
        llm.complete.return_value = _mock_llm_response(
            f"```json\n{_VALID_COMPOUND_JSON}\n```"
        )

        result = await extract_compound_procedure_from_cluster(
            _make_cluster(), _make_episodes(["e1"]), llm,
        )
        assert result is not None
        assert result.steps[0].agent_role == "security_analysis"

    @pytest.mark.asyncio
    async def test_compound_extraction_preserves_intent_types(self) -> None:
        from probos.cognitive.procedures import extract_compound_procedure_from_cluster

        llm = AsyncMock()
        llm.complete.return_value = _mock_llm_response(_VALID_COMPOUND_JSON)

        cluster = _make_cluster(intent_types=["deploy", "review"])
        result = await extract_compound_procedure_from_cluster(
            cluster, _make_episodes(["e1"]), llm,
        )
        assert result is not None
        assert result.intent_types == ["deploy", "review"]

    @pytest.mark.asyncio
    async def test_compound_extraction_provenance(self) -> None:
        from probos.cognitive.procedures import extract_compound_procedure_from_cluster

        llm = AsyncMock()
        llm.complete.return_value = _mock_llm_response(_VALID_COMPOUND_JSON)

        cluster = _make_cluster(episode_ids=["ep-a", "ep-b", "ep-c"])
        result = await extract_compound_procedure_from_cluster(
            cluster, _make_episodes(["ep-a", "ep-b"]), llm,
        )
        assert result is not None
        assert result.provenance == ["ep-a", "ep-b", "ep-c"]

    @pytest.mark.asyncio
    async def test_compound_extraction_steps_have_roles(self) -> None:
        from probos.cognitive.procedures import extract_compound_procedure_from_cluster

        llm = AsyncMock()
        llm.complete.return_value = _mock_llm_response(_VALID_COMPOUND_JSON)

        result = await extract_compound_procedure_from_cluster(
            _make_cluster(), _make_episodes(["e1"]), llm,
        )
        assert result is not None
        for step in result.steps:
            assert step.agent_role != "", f"Step {step.step_number} has no agent_role"

    @pytest.mark.asyncio
    async def test_compound_extraction_uses_format_episode_blocks(self) -> None:
        from probos.cognitive.procedures import extract_compound_procedure_from_cluster

        llm = AsyncMock()
        llm.complete.return_value = _mock_llm_response(_VALID_COMPOUND_JSON)

        await extract_compound_procedure_from_cluster(
            _make_cluster(), _make_episodes(["e1"]), llm,
        )

        call_args = llm.complete.call_args[0][0]
        assert "READ-ONLY EPISODE" in call_args.prompt


# ---------------------------------------------------------------------------
# Test Class 4: Dream cycle compound routing
# ---------------------------------------------------------------------------


def _make_dreaming_engine(
    llm_client: AsyncMock | None = None,
    procedure_store: AsyncMock | None = None,
) -> "DreamingEngine":
    from probos.cognitive.dreaming import DreamingEngine
    from probos.config import DreamingConfig

    router = MagicMock()
    router.get_weight.return_value = 0.5
    router._weights = {}
    router._compat_weights = {}
    router.decay_all = MagicMock()

    trust = MagicMock()
    trust.get_or_create.return_value = MagicMock(alpha=1.0, beta=1.0)

    mem = AsyncMock()
    mem.recent.return_value = []
    mem.get_stats.return_value = {"total": 0}
    mem.get_embeddings.return_value = {}

    return DreamingEngine(
        router=router,
        trust_network=trust,
        episodic_memory=mem,
        config=DreamingConfig(),
        llm_client=llm_client,
        procedure_store=procedure_store,
    )


class TestDreamCycleCompoundRouting:
    """Tests for dream cycle routing to compound vs standard extraction."""

    @pytest.mark.asyncio
    async def test_multi_agent_cluster_uses_compound_extraction(self) -> None:
        llm = AsyncMock()
        llm.complete.return_value = _mock_llm_response(_VALID_COMPOUND_JSON)
        store = AsyncMock()
        store.has_cluster.return_value = False
        store.list_active.return_value = []

        engine = _make_dreaming_engine(llm_client=llm, procedure_store=store)
        episodes = _make_episodes(["e1", "e2"])
        engine.episodic_memory.recent.return_value = episodes
        engine.episodic_memory.get_stats.return_value = {"total": 2}
        engine.episodic_memory.get_embeddings.return_value = {"e1": [0.1], "e2": [0.2]}

        # Multi-agent cluster (2+ agents)
        cluster = _make_cluster(
            cluster_id="multi-1",
            episode_ids=["e1", "e2"],
            participating_agents=["worf", "laforge"],
            is_success_dominant=True,
            is_failure_dominant=False,
        )

        with patch("probos.cognitive.dreaming.cluster_episodes", return_value=[cluster]):
            with patch("probos.cognitive.dreaming.detect_contradictions", return_value=[]):
                with patch("probos.cognitive.dreaming.predict_gaps", return_value=[]):
                    with patch("probos.cognitive.dreaming.extract_compound_procedure_from_cluster", new_callable=AsyncMock) as mock_compound:
                        with patch("probos.cognitive.dreaming.extract_procedure_from_cluster", new_callable=AsyncMock) as mock_standard:
                            mock_compound.return_value = MagicMock(name="compound", steps=[])
                            await engine.dream_cycle()

                            mock_compound.assert_called_once()
                            mock_standard.assert_not_called()

    @pytest.mark.asyncio
    async def test_single_agent_cluster_uses_standard_extraction(self) -> None:
        llm = AsyncMock()
        llm.complete.return_value = _mock_llm_response(_VALID_STANDARD_JSON)
        store = AsyncMock()
        store.has_cluster.return_value = False
        store.list_active.return_value = []

        engine = _make_dreaming_engine(llm_client=llm, procedure_store=store)
        episodes = _make_episodes(["e1"])
        engine.episodic_memory.recent.return_value = episodes
        engine.episodic_memory.get_stats.return_value = {"total": 1}
        engine.episodic_memory.get_embeddings.return_value = {"e1": [0.1]}

        # Single-agent cluster
        cluster = _make_cluster(
            cluster_id="single-1",
            episode_ids=["e1"],
            participating_agents=["data"],  # only 1 agent
            is_success_dominant=True,
            is_failure_dominant=False,
        )

        with patch("probos.cognitive.dreaming.cluster_episodes", return_value=[cluster]):
            with patch("probos.cognitive.dreaming.detect_contradictions", return_value=[]):
                with patch("probos.cognitive.dreaming.predict_gaps", return_value=[]):
                    with patch("probos.cognitive.dreaming.extract_compound_procedure_from_cluster", new_callable=AsyncMock) as mock_compound:
                        with patch("probos.cognitive.dreaming.extract_procedure_from_cluster", new_callable=AsyncMock) as mock_standard:
                            mock_standard.return_value = MagicMock(name="standard", steps=[])
                            await engine.dream_cycle()

                            mock_standard.assert_called_once()
                            mock_compound.assert_not_called()

    @pytest.mark.asyncio
    async def test_compound_extracted_saved_to_store(self) -> None:
        llm = AsyncMock()
        llm.complete.return_value = _mock_llm_response(_VALID_COMPOUND_JSON)
        store = AsyncMock()
        store.has_cluster.return_value = False
        store.list_active.return_value = []

        engine = _make_dreaming_engine(llm_client=llm, procedure_store=store)
        episodes = _make_episodes(["e1", "e2"])
        engine.episodic_memory.recent.return_value = episodes
        engine.episodic_memory.get_stats.return_value = {"total": 2}
        engine.episodic_memory.get_embeddings.return_value = {"e1": [0.1], "e2": [0.2]}

        cluster = _make_cluster(
            cluster_id="multi-save",
            episode_ids=["e1", "e2"],
            participating_agents=["a", "b"],
            is_success_dominant=True,
            is_failure_dominant=False,
        )

        with patch("probos.cognitive.dreaming.cluster_episodes", return_value=[cluster]):
            with patch("probos.cognitive.dreaming.detect_contradictions", return_value=[]):
                with patch("probos.cognitive.dreaming.predict_gaps", return_value=[]):
                    report = await engine.dream_cycle()

        store.save.assert_called_once()
        assert report.procedures_extracted == 1

    @pytest.mark.asyncio
    async def test_compound_cluster_dedup(self) -> None:
        llm = AsyncMock()
        llm.complete.return_value = _mock_llm_response(_VALID_COMPOUND_JSON)
        store = AsyncMock()
        store.has_cluster.return_value = False
        store.list_active.return_value = []

        engine = _make_dreaming_engine(llm_client=llm, procedure_store=store)
        episodes = _make_episodes(["e1"])
        engine.episodic_memory.recent.return_value = episodes
        engine.episodic_memory.get_stats.return_value = {"total": 1}
        engine.episodic_memory.get_embeddings.return_value = {"e1": [0.1]}

        cluster = _make_cluster(
            cluster_id="multi-dedup",
            episode_ids=["e1"],
            participating_agents=["a", "b"],
            is_success_dominant=True,
            is_failure_dominant=False,
        )

        with patch("probos.cognitive.dreaming.cluster_episodes", return_value=[cluster]):
            with patch("probos.cognitive.dreaming.detect_contradictions", return_value=[]):
                with patch("probos.cognitive.dreaming.predict_gaps", return_value=[]):
                    await engine.dream_cycle()

        assert "multi-dedup" in engine._extracted_cluster_ids

    @pytest.mark.asyncio
    async def test_compound_extraction_failure_nonfatal(self) -> None:
        llm = AsyncMock()
        llm.complete.side_effect = RuntimeError("LLM crash")
        store = AsyncMock()
        store.has_cluster.return_value = False
        store.list_active.return_value = []

        engine = _make_dreaming_engine(llm_client=llm, procedure_store=store)
        episodes = _make_episodes(["e1"])
        engine.episodic_memory.recent.return_value = episodes
        engine.episodic_memory.get_stats.return_value = {"total": 1}
        engine.episodic_memory.get_embeddings.return_value = {"e1": [0.1]}

        cluster = _make_cluster(
            cluster_id="multi-fail",
            episode_ids=["e1"],
            participating_agents=["a", "b"],
            is_success_dominant=True,
            is_failure_dominant=False,
        )

        with patch("probos.cognitive.dreaming.cluster_episodes", return_value=[cluster]):
            with patch("probos.cognitive.dreaming.detect_contradictions", return_value=[]):
                with patch("probos.cognitive.dreaming.predict_gaps", return_value=[]):
                    # Should NOT raise
                    report = await engine.dream_cycle()

        assert report.procedures_extracted == 0


# ---------------------------------------------------------------------------
# Test Class 5: Replay formatting
# ---------------------------------------------------------------------------


class TestReplayFormatting:
    """Tests for _format_procedure_replay with agent_role."""

    def _make_agent(self):
        """Build a minimal CognitiveAgent for replay formatting tests."""
        from probos.cognitive.cognitive_agent import CognitiveAgent

        class ReplayAgent(CognitiveAgent):
            def __init__(self):
                self.id = "test-agent"
                self.agent_type = "test"
                self._runtime = None

            async def act(self, observation):
                return {}

        return ReplayAgent()

    def test_format_replay_with_agent_role(self) -> None:
        from probos.cognitive.procedures import ProcedureStep, Procedure

        proc = Procedure(
            name="Compound Workflow",
            steps=[
                ProcedureStep(step_number=1, action="Analyze", agent_role="security_analysis"),
            ],
        )
        agent = self._make_agent()
        output = agent._format_procedure_replay(proc, 0.9)
        assert "[security_analysis]" in output
        assert "**Step 1 [security_analysis]:** Analyze" in output

    def test_format_replay_without_agent_role(self) -> None:
        from probos.cognitive.procedures import ProcedureStep, Procedure

        proc = Procedure(
            name="Simple Workflow",
            steps=[
                ProcedureStep(step_number=1, action="Do something"),
            ],
        )
        agent = self._make_agent()
        output = agent._format_procedure_replay(proc, 0.8)
        assert "[" not in output or "[Procedure Replay" in output
        assert "**Step 1:** Do something" in output

    def test_format_replay_mixed_roles(self) -> None:
        from probos.cognitive.procedures import ProcedureStep, Procedure

        proc = Procedure(
            name="Mixed Workflow",
            steps=[
                ProcedureStep(step_number=1, action="Scan", agent_role="security"),
                ProcedureStep(step_number=2, action="Execute"),  # no role
                ProcedureStep(step_number=3, action="Deploy", agent_role="ops"),
            ],
        )
        agent = self._make_agent()
        output = agent._format_procedure_replay(proc, 0.7)
        assert "**Step 1 [security]:** Scan" in output
        assert "**Step 2:** Execute" in output
        assert "**Step 3 [ops]:** Deploy" in output


# ---------------------------------------------------------------------------
# Test Class 6: End-to-end pipeline
# ---------------------------------------------------------------------------


class TestCompoundEndToEnd:
    """Verify the full compound procedure pipeline."""

    @pytest.mark.asyncio
    async def test_full_pipeline_compound(self) -> None:
        """Multi-agent cluster → compound extraction → store → replay with roles."""
        from probos.cognitive.procedures import (
            extract_compound_procedure_from_cluster,
            Procedure,
        )

        # Step 1: Extract compound procedure
        llm = AsyncMock()
        llm.complete.return_value = _mock_llm_response(_VALID_COMPOUND_JSON)

        cluster = _make_cluster(participating_agents=["worf", "laforge"])
        procedure = await extract_compound_procedure_from_cluster(
            cluster, _make_episodes(["e1", "e2"]), llm,
        )

        assert procedure is not None
        assert procedure.evolution_type == "CAPTURED"
        assert len(procedure.steps) == 2

        # Step 2: Verify round-trip through to_dict/from_dict
        d = procedure.to_dict()
        assert d["steps"][0]["agent_role"] == "security_analysis"
        assert d["steps"][1]["agent_role"] == "engineering_implementation"

        restored = Procedure.from_dict(d)
        assert restored.steps[0].agent_role == "security_analysis"
        assert restored.steps[1].agent_role == "engineering_implementation"
        assert restored.origin_agent_ids == ["worf", "laforge"]

        # Step 3: Verify replay formatting includes role annotations
        from probos.cognitive.cognitive_agent import CognitiveAgent

        class TestAgent(CognitiveAgent):
            def __init__(self):
                self.id = "test"
                self.agent_type = "test"
                self._runtime = None
            async def act(self, observation):
                return {}

        agent = TestAgent()
        output = agent._format_procedure_replay(restored, 0.85)
        assert "[security_analysis]" in output
        assert "[engineering_implementation]" in output
