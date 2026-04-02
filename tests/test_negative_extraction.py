"""AD-532c: Negative procedure extraction (anti-pattern) tests.

Tests cover:
- extract_negative_procedure_from_cluster() function (Part 0)
- Contradiction enrichment (3b)
- Dream cycle Step 7c integration (3c)
- DreamReport negative_procedures_extracted field (3d)
- End-to-end pipeline verification (3e)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
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
        agent_ids=agent_ids or [],
        timestamp=timestamp,
        reflection=reflection,
        dag_summary=dag_summary or {},
    )


def _make_cluster(
    cluster_id: str = "fail-cluster-001",
    episode_ids: list[str] | None = None,
    is_success_dominant: bool = False,
    is_failure_dominant: bool = True,
    success_rate: float = 0.2,
    participating_agents: list[str] | None = None,
    intent_types: list[str] | None = None,
) -> MagicMock:
    c = MagicMock()
    c.cluster_id = cluster_id
    c.episode_ids = episode_ids or ["e1", "e2", "e3"]
    c.is_success_dominant = is_success_dominant
    c.is_failure_dominant = is_failure_dominant
    c.success_rate = success_rate
    c.participating_agents = participating_agents or ["agent-a"]
    c.intent_types = intent_types or ["deploy"]
    return c


@dataclass
class FakeContradiction:
    """Lightweight stand-in for Contradiction dataclass."""
    older_episode_id: str
    newer_episode_id: str
    intent: str
    agent_id: str
    older_outcome: str
    newer_outcome: str
    similarity: float
    description: str = ""


_VALID_NEGATIVE_JSON = json.dumps({
    "name": "Deploy without validation",
    "description": "Deploying code without running validation leads to failures",
    "steps": [
        {
            "step_number": 1,
            "action": "Skipped pre-deploy validation",
            "expected_input": "code changes ready",
            "expected_output": "expected clean deploy",
            "fallback_action": "Run validation suite before deploy",
            "invariants": ["validation must pass before deploy"],
        },
    ],
    "preconditions": ["code changes pending deployment"],
    "postconditions": ["deployment failure", "rollback required"],
})


def _mock_llm_response(content: str) -> MagicMock:
    resp = MagicMock()
    resp.content = content
    return resp


def _make_episodes(ids: list[str]) -> list[Episode]:
    return [_make_episode(eid) for eid in ids]


# ---------------------------------------------------------------------------
# 3a: extract_negative_procedure_from_cluster()
# ---------------------------------------------------------------------------


class TestExtractNegativeProcedure:
    """Tests for the negative extraction function."""

    @pytest.mark.asyncio
    async def test_returns_procedure_with_is_negative_true(self) -> None:
        from probos.cognitive.procedures import extract_negative_procedure_from_cluster

        llm = AsyncMock()
        llm.complete.return_value = _mock_llm_response(_VALID_NEGATIVE_JSON)

        cluster = _make_cluster()
        episodes = _make_episodes(["e1", "e2", "e3"])

        result = await extract_negative_procedure_from_cluster(cluster, episodes, llm)

        assert result is not None
        assert result.is_negative is True

    @pytest.mark.asyncio
    async def test_sets_evolution_type_captured(self) -> None:
        from probos.cognitive.procedures import extract_negative_procedure_from_cluster

        llm = AsyncMock()
        llm.complete.return_value = _mock_llm_response(_VALID_NEGATIVE_JSON)

        result = await extract_negative_procedure_from_cluster(
            _make_cluster(), _make_episodes(["e1"]), llm,
        )
        assert result is not None
        assert result.evolution_type == "CAPTURED"
        assert result.compilation_level == 1

    @pytest.mark.asyncio
    async def test_sets_cluster_metadata(self) -> None:
        from probos.cognitive.procedures import extract_negative_procedure_from_cluster

        llm = AsyncMock()
        llm.complete.return_value = _mock_llm_response(_VALID_NEGATIVE_JSON)

        cluster = _make_cluster(
            cluster_id="c-99",
            intent_types=["deploy", "build"],
            participating_agents=["agent-x", "agent-y"],
            episode_ids=["e1", "e2"],
        )
        result = await extract_negative_procedure_from_cluster(
            cluster, _make_episodes(["e1", "e2"]), llm,
        )

        assert result is not None
        assert result.intent_types == ["deploy", "build"]
        assert result.origin_cluster_id == "c-99"
        assert result.origin_agent_ids == ["agent-x", "agent-y"]
        assert result.provenance == ["e1", "e2"]

    @pytest.mark.asyncio
    async def test_uses_format_episode_blocks(self) -> None:
        """Verify READ-ONLY framing appears in the LLM prompt."""
        from probos.cognitive.procedures import extract_negative_procedure_from_cluster

        llm = AsyncMock()
        llm.complete.return_value = _mock_llm_response(_VALID_NEGATIVE_JSON)

        episodes = _make_episodes(["e1"])
        await extract_negative_procedure_from_cluster(
            _make_cluster(), episodes, llm,
        )

        call_args = llm.complete.call_args[0][0]
        assert "READ-ONLY EPISODE" in call_args.prompt

    @pytest.mark.asyncio
    async def test_returns_none_on_error_response(self) -> None:
        from probos.cognitive.procedures import extract_negative_procedure_from_cluster

        llm = AsyncMock()
        llm.complete.return_value = _mock_llm_response(
            json.dumps({"error": "no_common_antipattern"})
        )

        result = await extract_negative_procedure_from_cluster(
            _make_cluster(), _make_episodes(["e1"]), llm,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_llm_exception(self) -> None:
        from probos.cognitive.procedures import extract_negative_procedure_from_cluster

        llm = AsyncMock()
        llm.complete.side_effect = RuntimeError("LLM down")

        result = await extract_negative_procedure_from_cluster(
            _make_cluster(), _make_episodes(["e1"]), llm,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_malformed_json(self) -> None:
        from probos.cognitive.procedures import extract_negative_procedure_from_cluster

        llm = AsyncMock()
        llm.complete.return_value = _mock_llm_response("not valid json at all")

        result = await extract_negative_procedure_from_cluster(
            _make_cluster(), _make_episodes(["e1"]), llm,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_handles_empty_episodes(self) -> None:
        from probos.cognitive.procedures import extract_negative_procedure_from_cluster

        llm = AsyncMock()
        llm.complete.return_value = _mock_llm_response(_VALID_NEGATIVE_JSON)

        result = await extract_negative_procedure_from_cluster(
            _make_cluster(), [], llm,
        )
        # Should succeed even with empty episodes (LLM gets empty block)
        assert result is not None
        assert result.is_negative is True

    @pytest.mark.asyncio
    async def test_uses_negative_system_prompt(self) -> None:
        from probos.cognitive.procedures import (
            extract_negative_procedure_from_cluster,
            _NEGATIVE_SYSTEM_PROMPT,
        )

        llm = AsyncMock()
        llm.complete.return_value = _mock_llm_response(_VALID_NEGATIVE_JSON)

        await extract_negative_procedure_from_cluster(
            _make_cluster(), _make_episodes(["e1"]), llm,
        )

        call_args = llm.complete.call_args[0][0]
        assert call_args.system_prompt == _NEGATIVE_SYSTEM_PROMPT

    @pytest.mark.asyncio
    async def test_reuses_parse_and_build_helpers(self) -> None:
        """Verify _parse_procedure_json and _build_steps_from_data are used (DRY)."""
        from probos.cognitive.procedures import extract_negative_procedure_from_cluster

        llm = AsyncMock()
        llm.complete.return_value = _mock_llm_response(_VALID_NEGATIVE_JSON)

        result = await extract_negative_procedure_from_cluster(
            _make_cluster(), _make_episodes(["e1"]), llm,
        )
        assert result is not None
        assert len(result.steps) == 1
        assert result.steps[0].action == "Skipped pre-deploy validation"

    @pytest.mark.asyncio
    async def test_name_and_description_populated(self) -> None:
        from probos.cognitive.procedures import extract_negative_procedure_from_cluster

        llm = AsyncMock()
        llm.complete.return_value = _mock_llm_response(_VALID_NEGATIVE_JSON)

        result = await extract_negative_procedure_from_cluster(
            _make_cluster(), _make_episodes(["e1"]), llm,
        )
        assert result is not None
        assert result.name == "Deploy without validation"
        assert result.postconditions == ["deployment failure", "rollback required"]


# ---------------------------------------------------------------------------
# 3b: Contradiction enrichment
# ---------------------------------------------------------------------------


class TestContradictionEnrichment:
    """Tests for contradiction context injection into the LLM prompt."""

    @pytest.mark.asyncio
    async def test_contradiction_context_included(self) -> None:
        from probos.cognitive.procedures import extract_negative_procedure_from_cluster

        llm = AsyncMock()
        llm.complete.return_value = _mock_llm_response(_VALID_NEGATIVE_JSON)

        contradictions = [
            FakeContradiction(
                older_episode_id="e1", newer_episode_id="e2",
                intent="deploy", agent_id="agent-a",
                older_outcome="success", newer_outcome="failure",
                similarity=0.95, description="Config changed between runs",
            ),
        ]

        await extract_negative_procedure_from_cluster(
            _make_cluster(intent_types=["deploy"]),
            _make_episodes(["e1", "e2"]),
            llm,
            contradictions=contradictions,
        )

        prompt = llm.complete.call_args[0][0].prompt
        assert "CONTRADICTION CONTEXT" in prompt
        assert "e1" in prompt
        assert "Config changed between runs" in prompt

    @pytest.mark.asyncio
    async def test_only_matching_intents_included(self) -> None:
        from probos.cognitive.procedures import extract_negative_procedure_from_cluster

        llm = AsyncMock()
        llm.complete.return_value = _mock_llm_response(_VALID_NEGATIVE_JSON)

        contradictions = [
            FakeContradiction(
                older_episode_id="e1", newer_episode_id="e2",
                intent="deploy", agent_id="a",
                older_outcome="success", newer_outcome="failure",
                similarity=0.9,
            ),
            FakeContradiction(
                older_episode_id="e3", newer_episode_id="e4",
                intent="build",  # does NOT match cluster intent "deploy"
                agent_id="b",
                older_outcome="success", newer_outcome="failure",
                similarity=0.8,
            ),
        ]

        await extract_negative_procedure_from_cluster(
            _make_cluster(intent_types=["deploy"]),
            _make_episodes(["e1"]),
            llm,
            contradictions=contradictions,
        )

        prompt = llm.complete.call_args[0][0].prompt
        assert "CONTRADICTION CONTEXT" in prompt
        # deploy contradiction included
        assert "e1" in prompt and "e2" in prompt
        # build contradiction excluded
        assert "e3" not in prompt

    @pytest.mark.asyncio
    async def test_contradictions_limited_to_five(self) -> None:
        from probos.cognitive.procedures import extract_negative_procedure_from_cluster

        llm = AsyncMock()
        llm.complete.return_value = _mock_llm_response(_VALID_NEGATIVE_JSON)

        # Create 7 contradictions — only top 5 by similarity should be included
        contradictions = [
            FakeContradiction(
                older_episode_id=f"old-{i}", newer_episode_id=f"new-{i}",
                intent="deploy", agent_id="a",
                older_outcome="success", newer_outcome="failure",
                similarity=0.5 + i * 0.05,
            )
            for i in range(7)
        ]

        await extract_negative_procedure_from_cluster(
            _make_cluster(intent_types=["deploy"]),
            _make_episodes(["e1"]),
            llm,
            contradictions=contradictions,
        )

        prompt = llm.complete.call_args[0][0].prompt
        # Top 5 (i=6,5,4,3,2) should be present; i=0,1 should not
        assert "old-6" in prompt
        assert "old-2" in prompt
        assert "old-1" not in prompt
        assert "old-0" not in prompt

    @pytest.mark.asyncio
    async def test_no_contradiction_section_when_none(self) -> None:
        from probos.cognitive.procedures import extract_negative_procedure_from_cluster

        llm = AsyncMock()
        llm.complete.return_value = _mock_llm_response(_VALID_NEGATIVE_JSON)

        await extract_negative_procedure_from_cluster(
            _make_cluster(), _make_episodes(["e1"]), llm,
            contradictions=None,
        )

        prompt = llm.complete.call_args[0][0].prompt
        assert "CONTRADICTION CONTEXT" not in prompt

    @pytest.mark.asyncio
    async def test_no_contradiction_section_when_empty(self) -> None:
        from probos.cognitive.procedures import extract_negative_procedure_from_cluster

        llm = AsyncMock()
        llm.complete.return_value = _mock_llm_response(_VALID_NEGATIVE_JSON)

        await extract_negative_procedure_from_cluster(
            _make_cluster(), _make_episodes(["e1"]), llm,
            contradictions=[],
        )

        prompt = llm.complete.call_args[0][0].prompt
        assert "CONTRADICTION CONTEXT" not in prompt

    @pytest.mark.asyncio
    async def test_no_section_when_no_intents_match(self) -> None:
        from probos.cognitive.procedures import extract_negative_procedure_from_cluster

        llm = AsyncMock()
        llm.complete.return_value = _mock_llm_response(_VALID_NEGATIVE_JSON)

        contradictions = [
            FakeContradiction(
                older_episode_id="e1", newer_episode_id="e2",
                intent="build",  # cluster intent is "deploy"
                agent_id="a",
                older_outcome="success", newer_outcome="failure",
                similarity=0.9,
            ),
        ]

        await extract_negative_procedure_from_cluster(
            _make_cluster(intent_types=["deploy"]),
            _make_episodes(["e1"]),
            llm,
            contradictions=contradictions,
        )

        prompt = llm.complete.call_args[0][0].prompt
        assert "CONTRADICTION CONTEXT" not in prompt


# ---------------------------------------------------------------------------
# 3c: Dream cycle Step 7c integration
# ---------------------------------------------------------------------------


def _make_dreaming_engine(
    llm_client: AsyncMock | None = None,
    procedure_store: AsyncMock | None = None,
) -> "DreamingEngine":
    """Build a DreamingEngine with mocked dependencies."""
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


class TestDreamCycleStep7c:
    """Tests for negative extraction in the dream cycle."""

    @pytest.mark.asyncio
    async def test_processes_failure_dominant_clusters(self) -> None:
        llm = AsyncMock()
        llm.complete.return_value = _mock_llm_response(_VALID_NEGATIVE_JSON)
        store = AsyncMock()
        store.has_cluster.return_value = False
        store.list_active.return_value = []

        engine = _make_dreaming_engine(llm_client=llm, procedure_store=store)
        episodes = _make_episodes(["e1", "e2", "e3"])
        engine.episodic_memory.recent.return_value = episodes
        engine.episodic_memory.get_stats.return_value = {"total": 3}
        engine.episodic_memory.get_embeddings.return_value = {"e1": [0.1], "e2": [0.2], "e3": [0.3]}

        failure_cluster = _make_cluster(
            cluster_id="fail-1",
            episode_ids=["e1", "e2", "e3"],
            is_failure_dominant=True,
            is_success_dominant=False,
            success_rate=0.2,
        )

        with patch("probos.cognitive.dreaming.cluster_episodes", return_value=[failure_cluster]):
            with patch("probos.cognitive.dreaming.detect_contradictions", return_value=[]):
                with patch("probos.cognitive.dreaming.predict_gaps", return_value=[]):
                    report = await engine.dream_cycle()

        assert report.negative_procedures_extracted == 1
        store.save.assert_called_once()
        saved_proc = store.save.call_args[0][0]
        assert saved_proc.is_negative is True

    @pytest.mark.asyncio
    async def test_skips_success_dominant_clusters(self) -> None:
        llm = AsyncMock()
        store = AsyncMock()
        store.has_cluster.return_value = False
        store.list_active.return_value = []

        engine = _make_dreaming_engine(llm_client=llm, procedure_store=store)
        episodes = _make_episodes(["e1"])
        engine.episodic_memory.recent.return_value = episodes
        engine.episodic_memory.get_stats.return_value = {"total": 1}
        engine.episodic_memory.get_embeddings.return_value = {"e1": [0.1]}

        success_cluster = _make_cluster(
            is_failure_dominant=False,
            is_success_dominant=True,
        )

        with patch("probos.cognitive.dreaming.cluster_episodes", return_value=[success_cluster]):
            with patch("probos.cognitive.dreaming.detect_contradictions", return_value=[]):
                with patch("probos.cognitive.dreaming.predict_gaps", return_value=[]):
                    report = await engine.dream_cycle()

        # Step 7c processes failure-dominant only; positive extraction is Step 7
        assert report.negative_procedures_extracted == 0

    @pytest.mark.asyncio
    async def test_skips_already_processed_clusters(self) -> None:
        llm = AsyncMock()
        llm.complete.return_value = _mock_llm_response(_VALID_NEGATIVE_JSON)
        store = AsyncMock()
        store.has_cluster.return_value = False
        store.list_active.return_value = []

        engine = _make_dreaming_engine(llm_client=llm, procedure_store=store)
        engine._extracted_cluster_ids.add("fail-dup")

        episodes = _make_episodes(["e1"])
        engine.episodic_memory.recent.return_value = episodes
        engine.episodic_memory.get_stats.return_value = {"total": 1}
        engine.episodic_memory.get_embeddings.return_value = {"e1": [0.1]}

        cluster = _make_cluster(cluster_id="fail-dup")

        with patch("probos.cognitive.dreaming.cluster_episodes", return_value=[cluster]):
            with patch("probos.cognitive.dreaming.detect_contradictions", return_value=[]):
                with patch("probos.cognitive.dreaming.predict_gaps", return_value=[]):
                    report = await engine.dream_cycle()

        assert report.negative_procedures_extracted == 0

    @pytest.mark.asyncio
    async def test_skips_clusters_in_store(self) -> None:
        llm = AsyncMock()
        store = AsyncMock()
        store.has_cluster.return_value = True  # already persisted
        store.list_active.return_value = []

        engine = _make_dreaming_engine(llm_client=llm, procedure_store=store)

        episodes = _make_episodes(["e1"])
        engine.episodic_memory.recent.return_value = episodes
        engine.episodic_memory.get_stats.return_value = {"total": 1}
        engine.episodic_memory.get_embeddings.return_value = {"e1": [0.1]}

        cluster = _make_cluster(cluster_id="fail-stored")

        with patch("probos.cognitive.dreaming.cluster_episodes", return_value=[cluster]):
            with patch("probos.cognitive.dreaming.detect_contradictions", return_value=[]):
                with patch("probos.cognitive.dreaming.predict_gaps", return_value=[]):
                    report = await engine.dream_cycle()

        assert report.negative_procedures_extracted == 0

    @pytest.mark.asyncio
    async def test_passes_contradictions_filtered_by_intent(self) -> None:
        llm = AsyncMock()
        llm.complete.return_value = _mock_llm_response(_VALID_NEGATIVE_JSON)
        store = AsyncMock()
        store.has_cluster.return_value = False
        store.list_active.return_value = []

        engine = _make_dreaming_engine(llm_client=llm, procedure_store=store)

        episodes = _make_episodes(["e1", "e2"])
        engine.episodic_memory.recent.return_value = episodes
        engine.episodic_memory.get_stats.return_value = {"total": 2}
        engine.episodic_memory.get_embeddings.return_value = {"e1": [0.1], "e2": [0.2]}

        cluster = _make_cluster(
            cluster_id="fail-c",
            episode_ids=["e1", "e2"],
            intent_types=["deploy"],
        )

        # One matching, one not
        matching_c = FakeContradiction(
            older_episode_id="e1", newer_episode_id="e2",
            intent="deploy", agent_id="a",
            older_outcome="success", newer_outcome="failure",
            similarity=0.9,
        )
        non_matching_c = FakeContradiction(
            older_episode_id="e3", newer_episode_id="e4",
            intent="build", agent_id="b",
            older_outcome="success", newer_outcome="failure",
            similarity=0.8,
        )

        with patch("probos.cognitive.dreaming.cluster_episodes", return_value=[cluster]):
            with patch("probos.cognitive.dreaming.detect_contradictions", return_value=[matching_c, non_matching_c]):
                with patch("probos.cognitive.dreaming.predict_gaps", return_value=[]):
                    with patch("probos.cognitive.dreaming.extract_negative_procedure_from_cluster", new_callable=AsyncMock) as mock_extract:
                        mock_proc = MagicMock()
                        mock_proc.is_negative = True
                        mock_proc.name = "test"
                        mock_proc.steps = []
                        mock_extract.return_value = mock_proc

                        await engine.dream_cycle()

                        # Verify only matching contradictions were passed
                        call_kwargs = mock_extract.call_args[1]
                        passed_contradictions = call_kwargs.get("contradictions")
                        assert passed_contradictions is not None
                        assert len(passed_contradictions) == 1
                        assert passed_contradictions[0].intent == "deploy"

    @pytest.mark.asyncio
    async def test_store_save_failure_noncritical(self) -> None:
        llm = AsyncMock()
        llm.complete.return_value = _mock_llm_response(_VALID_NEGATIVE_JSON)
        store = AsyncMock()
        store.has_cluster.return_value = False
        store.save.side_effect = RuntimeError("DB error")
        store.list_active.return_value = []

        engine = _make_dreaming_engine(llm_client=llm, procedure_store=store)
        episodes = _make_episodes(["e1"])
        engine.episodic_memory.recent.return_value = episodes
        engine.episodic_memory.get_stats.return_value = {"total": 1}
        engine.episodic_memory.get_embeddings.return_value = {"e1": [0.1]}

        cluster = _make_cluster(cluster_id="fail-save", episode_ids=["e1"])

        with patch("probos.cognitive.dreaming.cluster_episodes", return_value=[cluster]):
            with patch("probos.cognitive.dreaming.detect_contradictions", return_value=[]):
                with patch("probos.cognitive.dreaming.predict_gaps", return_value=[]):
                    # Should NOT raise despite store.save failing
                    report = await engine.dream_cycle()

        assert report.negative_procedures_extracted == 1

    @pytest.mark.asyncio
    async def test_extraction_failure_noncritical(self) -> None:
        llm = AsyncMock()
        llm.complete.side_effect = RuntimeError("LLM down")
        store = AsyncMock()
        store.has_cluster.return_value = False
        store.list_active.return_value = []

        engine = _make_dreaming_engine(llm_client=llm, procedure_store=store)
        episodes = _make_episodes(["e1"])
        engine.episodic_memory.recent.return_value = episodes
        engine.episodic_memory.get_stats.return_value = {"total": 1}
        engine.episodic_memory.get_embeddings.return_value = {"e1": [0.1]}

        cluster = _make_cluster(cluster_id="fail-ext", episode_ids=["e1"])

        with patch("probos.cognitive.dreaming.cluster_episodes", return_value=[cluster]):
            with patch("probos.cognitive.dreaming.detect_contradictions", return_value=[]):
                with patch("probos.cognitive.dreaming.predict_gaps", return_value=[]):
                    # Should NOT raise
                    report = await engine.dream_cycle()

        assert report.negative_procedures_extracted == 0

    @pytest.mark.asyncio
    async def test_increments_counter_correctly(self) -> None:
        llm = AsyncMock()
        llm.complete.return_value = _mock_llm_response(_VALID_NEGATIVE_JSON)
        store = AsyncMock()
        store.has_cluster.return_value = False
        store.list_active.return_value = []

        engine = _make_dreaming_engine(llm_client=llm, procedure_store=store)
        episodes = _make_episodes(["e1", "e2", "e3"])
        engine.episodic_memory.recent.return_value = episodes
        engine.episodic_memory.get_stats.return_value = {"total": 3}
        engine.episodic_memory.get_embeddings.return_value = {"e1": [0.1], "e2": [0.2], "e3": [0.3]}

        c1 = _make_cluster(cluster_id="fail-a", episode_ids=["e1"])
        c2 = _make_cluster(cluster_id="fail-b", episode_ids=["e2"])

        with patch("probos.cognitive.dreaming.cluster_episodes", return_value=[c1, c2]):
            with patch("probos.cognitive.dreaming.detect_contradictions", return_value=[]):
                with patch("probos.cognitive.dreaming.predict_gaps", return_value=[]):
                    report = await engine.dream_cycle()

        assert report.negative_procedures_extracted == 2

    @pytest.mark.asyncio
    async def test_empty_cluster_list_handled(self) -> None:
        llm = AsyncMock()
        store = AsyncMock()
        store.list_active.return_value = []

        engine = _make_dreaming_engine(llm_client=llm, procedure_store=store)
        episodes = _make_episodes(["e1"])
        engine.episodic_memory.recent.return_value = episodes
        engine.episodic_memory.get_stats.return_value = {"total": 1}
        engine.episodic_memory.get_embeddings.return_value = {"e1": [0.1]}

        with patch("probos.cognitive.dreaming.cluster_episodes", return_value=[]):
            with patch("probos.cognitive.dreaming.detect_contradictions", return_value=[]):
                with patch("probos.cognitive.dreaming.predict_gaps", return_value=[]):
                    report = await engine.dream_cycle()

        assert report.negative_procedures_extracted == 0

    @pytest.mark.asyncio
    async def test_updates_extracted_cluster_ids(self) -> None:
        llm = AsyncMock()
        llm.complete.return_value = _mock_llm_response(_VALID_NEGATIVE_JSON)
        store = AsyncMock()
        store.has_cluster.return_value = False
        store.list_active.return_value = []

        engine = _make_dreaming_engine(llm_client=llm, procedure_store=store)
        episodes = _make_episodes(["e1"])
        engine.episodic_memory.recent.return_value = episodes
        engine.episodic_memory.get_stats.return_value = {"total": 1}
        engine.episodic_memory.get_embeddings.return_value = {"e1": [0.1]}

        cluster = _make_cluster(cluster_id="fail-track", episode_ids=["e1"])

        with patch("probos.cognitive.dreaming.cluster_episodes", return_value=[cluster]):
            with patch("probos.cognitive.dreaming.detect_contradictions", return_value=[]):
                with patch("probos.cognitive.dreaming.predict_gaps", return_value=[]):
                    await engine.dream_cycle()

        assert "fail-track" in engine._extracted_cluster_ids


# ---------------------------------------------------------------------------
# 3d: DreamReport
# ---------------------------------------------------------------------------


class TestDreamReportNegative:
    """Tests for the negative_procedures_extracted field."""

    def test_field_defaults_to_zero(self) -> None:
        report = DreamReport()
        assert report.negative_procedures_extracted == 0

    def test_field_populated(self) -> None:
        report = DreamReport(negative_procedures_extracted=3)
        assert report.negative_procedures_extracted == 3


# ---------------------------------------------------------------------------
# 3e: End-to-end pipeline verification
# ---------------------------------------------------------------------------


class TestEndToEndPipeline:
    """Verify the full pipeline: extract → save → consume."""

    @pytest.mark.asyncio
    async def test_negative_procedure_flows_through_pipeline(self) -> None:
        """Negative extraction → ProcedureStore save → _check_procedural_memory block."""
        from probos.cognitive.procedures import extract_negative_procedure_from_cluster

        # Step 1: Extract
        llm = AsyncMock()
        llm.complete.return_value = _mock_llm_response(_VALID_NEGATIVE_JSON)

        cluster = _make_cluster()
        procedure = await extract_negative_procedure_from_cluster(
            cluster, _make_episodes(["e1"]), llm,
        )

        assert procedure is not None
        assert procedure.is_negative is True

        # Step 2: Verify it would be saved with is_negative=True
        proc_dict = procedure.to_dict()
        assert proc_dict["is_negative"] is True

        # Step 3: Verify it can be reconstructed from dict
        from probos.cognitive.procedures import Procedure
        restored = Procedure.from_dict(proc_dict)
        assert restored.is_negative is True
        assert restored.name == procedure.name
        assert restored.evolution_type == "CAPTURED"

    @pytest.mark.asyncio
    async def test_negative_prompt_has_anti_pattern_schema(self) -> None:
        """Verify the negative system prompt has the correct schema fields."""
        from probos.cognitive.procedures import _NEGATIVE_SYSTEM_PROMPT

        assert "anti-pattern" in _NEGATIVE_SYSTEM_PROMPT.lower()
        assert "fallback_action" in _NEGATIVE_SYSTEM_PROMPT
        assert "BAD action" in _NEGATIVE_SYSTEM_PROMPT
        assert "SHOULD be done instead" in _NEGATIVE_SYSTEM_PROMPT
        assert "no_common_antipattern" in _NEGATIVE_SYSTEM_PROMPT
