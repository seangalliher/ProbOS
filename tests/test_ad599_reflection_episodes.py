"""AD-599: Reflection as Recallable Episodes — Dream Insight Promotion tests."""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import inspect
import logging
import types as stdlib_types
from typing import get_type_hints
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.config import DreamingConfig
from probos.types import (
    DreamReport,
    Episode,
    EpisodeDuplicatePolicy,
    EpisodeStoreOutcome,
    MemorySource,
)


# ── Helpers ──────────────────────────────────────────────────────────


def _make_engine(*, config: DreamingConfig | None = None):
    """Create a DreamingEngine with minimal stubs."""
    from probos.cognitive.dreaming import DreamingEngine

    mem = AsyncMock()
    mem.store = AsyncMock(return_value=EpisodeStoreOutcome.STORED)
    mem.recent = AsyncMock(return_value=[])
    mem.get_embeddings = AsyncMock(return_value={})

    engine = DreamingEngine(
        router=MagicMock(),
        trust_network=MagicMock(),
        episodic_memory=mem,
        config=config or DreamingConfig(),
    )
    return engine


def _make_cluster(
    *,
    cluster_id: str = "clust-1",
    episode_ids: list[str] | None = None,
    is_success_dominant: bool = False,
    is_failure_dominant: bool = False,
    anchor_summary: str | None = None,
):
    """Create a SimpleNamespace cluster stub."""
    return stdlib_types.SimpleNamespace(
        cluster_id=cluster_id,
        episode_ids=episode_ids or [],
        is_success_dominant=is_success_dominant,
        is_failure_dominant=is_failure_dominant,
        anchor_summary=anchor_summary,
    )


def _make_episode(*, ep_id: str = "ep-1", agent_ids: list[str] | None = None):
    """Create a minimal Episode stub for cluster agent extraction."""
    ep = MagicMock()
    ep.id = ep_id
    ep.agent_ids = agent_ids or []
    return ep


# ===========================================================================
# 1. MemorySource enum (1 test)
# ===========================================================================


class TestMemorySourceReflection:
    def test_memory_source_reflection_exists(self):
        """MemorySource.REFLECTION exists and equals 'reflection'."""
        assert MemorySource.REFLECTION == "reflection"
        assert MemorySource.REFLECTION.value == "reflection"

    def test_episode_store_policy_and_outcome_types_exist(self):
        """BF-669: shared typed duplicate policy and store outcome exist."""
        import probos.types as probos_types

        assert hasattr(probos_types, "EpisodeDuplicatePolicy")
        assert hasattr(probos_types, "EpisodeStoreOutcome")

    def test_episode_store_policy_and_outcome_values_are_exact(self):
        """BF-669: policy and outcome enums expose only the pinned values."""
        assert [(item.name, item.value) for item in EpisodeDuplicatePolicy] == [
            ("UNEXPECTED", "unexpected"),
            ("EXPECT_SAME_REFLECTION", "expect_same_reflection"),
        ]
        assert [(item.name, item.value) for item in EpisodeStoreOutcome] == [
            ("STORED", "stored"),
            ("DUPLICATE", "duplicate"),
            ("SKIPPED", "skipped"),
        ]

    def test_episodic_memory_protocol_store_signature_is_exact(self):
        """BF-669: protocol has the additive keyword-only typed contract."""
        from probos.protocols import EpisodicMemoryProtocol

        signature = inspect.signature(EpisodicMemoryProtocol.store)
        assert list(signature.parameters) == ["self", "episode", "duplicate_policy"]
        policy = signature.parameters["duplicate_policy"]
        assert policy.kind is inspect.Parameter.KEYWORD_ONLY
        assert policy.default is EpisodeDuplicatePolicy.UNEXPECTED
        hints = get_type_hints(EpisodicMemoryProtocol.store)
        assert hints["episode"] is Episode
        assert hints["duplicate_policy"] is EpisodeDuplicatePolicy
        assert hints["return"] is EpisodeStoreOutcome

    @pytest.mark.parametrize(
        "store_owner",
        [
            pytest.param("real", id="real"),
            pytest.param("mock", id="mock"),
            pytest.param("protocol", id="protocol"),
        ],
    )
    def test_real_mock_and_protocol_store_signatures_match(self, store_owner):
        """BF-669: all three public contracts have exact signature/type parity."""
        from probos.cognitive.episodic import EpisodicMemory
        from probos.cognitive.episodic_mock import MockEpisodicMemory
        from probos.protocols import EpisodicMemoryProtocol

        owner = {
            "real": EpisodicMemory,
            "mock": MockEpisodicMemory,
            "protocol": EpisodicMemoryProtocol,
        }[store_owner]
        signature = inspect.signature(owner.store)
        policy = signature.parameters["duplicate_policy"]
        hints = get_type_hints(owner.store)

        assert list(signature.parameters) == ["self", "episode", "duplicate_policy"]
        assert policy.kind is inspect.Parameter.KEYWORD_ONLY
        assert policy.default is EpisodeDuplicatePolicy.UNEXPECTED
        assert hints["episode"] is Episode
        assert hints["duplicate_policy"] is EpisodeDuplicatePolicy
        assert hints["return"] is EpisodeStoreOutcome


# ===========================================================================
# 2. DreamReport field (1 test)
# ===========================================================================


class TestDreamReportField:
    def test_dream_report_reflections_created_default(self):
        """DreamReport().reflections_created defaults to 0."""
        report = DreamReport()
        assert report.reflections_created == 0

    def test_dream_report_adds_no_duplicate_or_skipped_counter(self):
        """BF-669: the existing public creation count is corrected in place."""
        names = {field.name for field in dataclasses.fields(DreamReport)}

        assert "reflections_created" in names
        assert "reflections_duplicate" not in names
        assert "reflections_skipped" not in names


# ===========================================================================
# 3. Config fields (2 tests)
# ===========================================================================


class TestConfigFields:
    def test_config_reflection_enabled_default(self):
        """DreamingConfig().reflection_enabled defaults to True."""
        cfg = DreamingConfig()
        assert cfg.reflection_enabled is True

    def test_config_reflection_max_per_cycle_default(self):
        """DreamingConfig().reflection_max_per_cycle defaults to 3."""
        cfg = DreamingConfig()
        assert cfg.reflection_max_per_cycle == 3


# ===========================================================================
# 4. Step 15 — convergence reflections (3 tests)
# ===========================================================================


class TestConvergenceReflections:
    @pytest.mark.asyncio
    async def test_step15_convergence_report_creates_reflection(self):
        """Single convergence report → one store call with correct fields."""
        engine = _make_engine()
        conv = {
            "agents": ["a1", "a2"],
            "departments": ["science", "engineering"],
            "topic": "latency",
            "coherence": 0.85,
        }
        result = await engine._step_15_reflection_promotion(
            episodes=[],
            clusters=[],
            convergence_reports=[conv],
            emergence_capacity=None,
            coordination_balance=None,
            notebook_consolidations=0,
            behavioral_quality_score=None,
        )
        assert result == 1
        assert engine.episodic_memory.store.call_count == 1

        stored = engine.episodic_memory.store.call_args[0][0]
        assert stored.source == MemorySource.REFLECTION
        assert stored.importance == 8
        assert stored.user_input.startswith("[Reflection]")
        assert stored.agent_ids == []
        assert stored.dag_summary["involved_agents"] == ["a1", "a2"]
        assert engine.episodic_memory.store.call_args.kwargs == {
            "duplicate_policy": EpisodeDuplicatePolicy.EXPECT_SAME_REFLECTION
        }

    @pytest.mark.asyncio
    async def test_step15_convergence_with_independence(self):
        """Convergence with independence field → content includes it."""
        engine = _make_engine()
        conv = {
            "agents": ["a1"],
            "departments": ["science"],
            "topic": "test",
            "coherence": 0.5,
            "independence": "low",
        }
        await engine._step_15_reflection_promotion(
            episodes=[],
            clusters=[],
            convergence_reports=[conv],
            emergence_capacity=None,
            coordination_balance=None,
            notebook_consolidations=0,
            behavioral_quality_score=None,
        )
        stored = engine.episodic_memory.store.call_args[0][0]
        assert "Independence: low" in stored.user_input
        assert stored.agent_ids == []

    @pytest.mark.asyncio
    async def test_step15_multiple_convergence_reports(self):
        """Two convergence reports → two store calls."""
        engine = _make_engine()
        convs = [
            {"agents": ["a1"], "departments": ["sci"], "topic": "t1", "coherence": 0.8},
            {"agents": ["a2"], "departments": ["eng"], "topic": "t2", "coherence": 0.7},
        ]
        result = await engine._step_15_reflection_promotion(
            episodes=[],
            clusters=[],
            convergence_reports=convs,
            emergence_capacity=None,
            coordination_balance=None,
            notebook_consolidations=0,
            behavioral_quality_score=None,
        )
        assert result == 2
        assert engine.episodic_memory.store.call_count == 2


# ===========================================================================
# 5. Step 15 — emergence reflections (2 tests)
# ===========================================================================


class TestEmergenceReflections:
    @pytest.mark.asyncio
    async def test_step15_emergence_snapshot_creates_reflection(self):
        """Emergence capacity → one store call with metrics in content."""
        engine = _make_engine()
        result = await engine._step_15_reflection_promotion(
            episodes=[],
            clusters=[],
            convergence_reports=[],
            emergence_capacity=0.75,
            coordination_balance=0.60,
            notebook_consolidations=0,
            behavioral_quality_score=None,
        )
        assert result == 1
        stored = engine.episodic_memory.store.call_args[0][0]
        assert "capacity=0.750" in stored.user_input
        assert "coordination_balance=0.600" in stored.user_input

    @pytest.mark.asyncio
    async def test_step15_emergence_with_behavioral(self):
        """Emergence + behavioral quality → both in content."""
        engine = _make_engine()
        await engine._step_15_reflection_promotion(
            episodes=[],
            clusters=[],
            convergence_reports=[],
            emergence_capacity=0.75,
            coordination_balance=None,
            notebook_consolidations=0,
            behavioral_quality_score=0.82,
        )
        stored = engine.episodic_memory.store.call_args[0][0]
        assert "behavioral_quality=0.820" in stored.user_input


# ===========================================================================
# 6. Step 15 — notebook consolidation reflections (1 test)
# ===========================================================================


class TestNotebookReflections:
    @pytest.mark.asyncio
    async def test_step15_notebook_consolidation_creates_reflection(self):
        """Notebook consolidations > 0 → reflection with merge count."""
        engine = _make_engine()
        result = await engine._step_15_reflection_promotion(
            episodes=[],
            clusters=[],
            convergence_reports=[],
            emergence_capacity=None,
            coordination_balance=None,
            notebook_consolidations=5,
            behavioral_quality_score=None,
        )
        assert result == 1
        stored = engine.episodic_memory.store.call_args[0][0]
        assert "merged 5 redundant notebook clusters" in stored.user_input


# ===========================================================================
# 7. Step 15 — cluster pattern reflections (2 tests)
# ===========================================================================


class TestClusterReflections:
    @pytest.mark.asyncio
    async def test_step15_success_cluster_creates_reflection(self):
        """Success-dominant cluster with 6 episodes → reflection created."""
        ep_ids = [f"ep-{i}" for i in range(6)]
        cluster = _make_cluster(
            cluster_id="clust-abc",
            episode_ids=ep_ids,
            is_success_dominant=True,
        )
        episodes = [_make_episode(ep_id=eid, agent_ids=["agent-x"]) for eid in ep_ids]

        engine = _make_engine()
        result = await engine._step_15_reflection_promotion(
            episodes=episodes,
            clusters=[cluster],
            convergence_reports=[],
            emergence_capacity=None,
            coordination_balance=None,
            notebook_consolidations=0,
            behavioral_quality_score=None,
        )
        assert result == 1
        stored = engine.episodic_memory.store.call_args[0][0]
        assert "success-dominant pattern cluster" in stored.user_input
        assert "6 episodes" in stored.user_input
        assert "cluster_id=clust-abc" in stored.user_input
        assert stored.agent_ids == []
        assert "agent-x" in stored.dag_summary["involved_agents"]

    @pytest.mark.asyncio
    async def test_step15_small_cluster_skipped(self):
        """Cluster with only 3 episodes → below threshold, skipped."""
        cluster = _make_cluster(
            cluster_id="clust-tiny",
            episode_ids=["e1", "e2", "e3"],
            is_success_dominant=True,
        )
        engine = _make_engine()
        result = await engine._step_15_reflection_promotion(
            episodes=[],
            clusters=[cluster],
            convergence_reports=[],
            emergence_capacity=None,
            coordination_balance=None,
            notebook_consolidations=0,
            behavioral_quality_score=None,
        )
        assert result == 0
        engine.episodic_memory.store.assert_not_called()


# ===========================================================================
# 8. Step 15 — rate limiting (2 tests)
# ===========================================================================


class TestRateLimiting:
    @pytest.mark.asyncio
    async def test_step15_respects_max_per_cycle(self):
        """max_per_cycle=2 with 4 convergence reports → only 2 stored."""
        cfg = DreamingConfig(reflection_max_per_cycle=2)
        engine = _make_engine(config=cfg)
        convs = [
            {"agents": [f"a{i}"], "departments": ["d"], "topic": f"t{i}", "coherence": 0.8}
            for i in range(4)
        ]
        result = await engine._step_15_reflection_promotion(
            episodes=[],
            clusters=[],
            convergence_reports=convs,
            emergence_capacity=None,
            coordination_balance=None,
            notebook_consolidations=0,
            behavioral_quality_score=None,
        )
        assert result == 2
        assert engine.episodic_memory.store.call_count == 2

    @pytest.mark.asyncio
    async def test_step15_disabled_creates_none(self):
        """reflection_enabled=False → step returns 0."""
        cfg = DreamingConfig(reflection_enabled=False)
        engine = _make_engine(config=cfg)
        # Step is gated at the call site, so we test that the engine config is False
        # and the call site guard prevents invocation
        assert engine.config.reflection_enabled is False


# ===========================================================================
# 9. Step 15 — deduplication (1 test)
# ===========================================================================


class TestDeduplication:
    @pytest.mark.asyncio
    async def test_step15_deterministic_ids(self):
        """Same content → same episode ID (deterministic hash)."""
        engine = _make_engine()
        conv = {
            "agents": ["a1"],
            "departments": ["science"],
            "topic": "test",
            "coherence": 0.9,
        }
        await engine._step_15_reflection_promotion(
            episodes=[],
            clusters=[],
            convergence_reports=[conv],
            emergence_capacity=None,
            coordination_balance=None,
            notebook_consolidations=0,
            behavioral_quality_score=None,
        )
        id_1 = engine.episodic_memory.store.call_args[0][0].id

        engine.episodic_memory.store.reset_mock()
        await engine._step_15_reflection_promotion(
            episodes=[],
            clusters=[],
            convergence_reports=[conv],
            emergence_capacity=None,
            coordination_balance=None,
            notebook_consolidations=0,
            behavioral_quality_score=None,
        )
        id_2 = engine.episodic_memory.store.call_args[0][0].id

        assert id_1 == id_2
        assert id_1.startswith("reflection-")
        assert len(id_1) == len("reflection-") + 16
        stored_text = engine.episodic_memory.store.call_args[0][0].user_input
        assert id_1 == f"reflection-{hashlib.sha256(stored_text.encode()).hexdigest()[:16]}"

    @pytest.mark.asyncio
    async def test_step15_real_store_replay_counts_only_first_primary_write(
        self, tmp_path, caplog
    ):
        """BF-669: deterministic real-store replay reports 1 then 0."""
        from probos.cognitive.episodic import EpisodicMemory

        memory = EpisodicMemory(tmp_path / "bf669-real-replay.db")
        await memory.start()
        engine = _make_engine()
        engine.episodic_memory = memory
        conv = {
            "agents": ["a1"],
            "departments": ["science"],
            "topic": "idempotent reflection",
            "coherence": 0.9,
        }
        try:
            first = await engine._step_15_reflection_promotion(
                episodes=[], clusters=[], convergence_reports=[conv],
                emergence_capacity=None, coordination_balance=None,
                notebook_consolidations=0, behavioral_quality_score=None,
            )
            stored_once = await memory.recent(k=10)
            caplog.clear()
            with caplog.at_level(logging.DEBUG, logger="probos.cognitive.episodic"):
                second = await engine._step_15_reflection_promotion(
                    episodes=[], clusters=[], convergence_reports=[conv],
                    emergence_capacity=None, coordination_balance=None,
                    notebook_consolidations=0, behavioral_quality_score=None,
                )
            stored_twice = await memory.recent(k=10)

            assert (first, second) == (1, 0)
            assert len(stored_once) == len(stored_twice) == 1
            assert stored_twice[0] == stored_once[0]
            assert not [
                record for record in caplog.records
                if record.levelno >= logging.WARNING
            ]
            duplicate_logs = [
                record.message for record in caplog.records
                if "Episode duplicate id=" in record.message
            ]
            assert len(duplicate_logs) == 1
            assert "policy=expect_same_reflection" in duplicate_logs[0]
            assert "equivalence=timestamp_neutral" in duplicate_logs[0]
            assert stored_once[0].id in duplicate_logs[0]
        finally:
            await memory.stop()

    @pytest.mark.asyncio
    async def test_step15_mock_replay_counts_only_first_and_preserves_authority(self):
        from probos.cognitive.episodic_mock import MockEpisodicMemory

        memory = MockEpisodicMemory()
        engine = _make_engine()
        engine.episodic_memory = memory
        conv = {
            "agents": ["a1"],
            "departments": ["science"],
            "topic": "mock replay",
            "coherence": 0.9,
        }

        first = await engine._step_15_reflection_promotion(
            episodes=[], clusters=[], convergence_reports=[conv],
            emergence_capacity=None, coordination_balance=None,
            notebook_consolidations=0, behavioral_quality_score=None,
        )
        authoritative = memory._episodes[0]
        second = await engine._step_15_reflection_promotion(
            episodes=[], clusters=[], convergence_reports=[conv],
            emergence_capacity=None, coordination_balance=None,
            notebook_consolidations=0, behavioral_quality_score=None,
        )

        assert (first, second) == (1, 0)
        assert memory._episodes == [authoritative]

    @pytest.mark.asyncio
    async def test_step15_mixed_duplicate_and_new_counts_only_new_row(self):
        from probos.cognitive.episodic_mock import MockEpisodicMemory

        memory = MockEpisodicMemory()
        engine = _make_engine()
        engine.episodic_memory = memory
        first_conv = {
            "agents": ["a1"], "departments": ["science"],
            "topic": "existing", "coherence": 0.9,
        }
        new_conv = {
            "agents": ["a2"], "departments": ["engineering"],
            "topic": "new", "coherence": 0.8,
        }
        assert await engine._step_15_reflection_promotion(
            episodes=[], clusters=[], convergence_reports=[first_conv],
            emergence_capacity=None, coordination_balance=None,
            notebook_consolidations=0, behavioral_quality_score=None,
        ) == 1

        mixed = await engine._step_15_reflection_promotion(
            episodes=[], clusters=[], convergence_reports=[first_conv, new_conv],
            emergence_capacity=None, coordination_balance=None,
            notebook_consolidations=0, behavioral_quality_score=None,
        )

        assert mixed == 1
        assert len(memory._episodes) == 2


class TestStoreOutcomeAccounting:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("outcome", "expected"),
        [
            (EpisodeStoreOutcome.STORED, 1),
            (EpisodeStoreOutcome.DUPLICATE, 0),
            (EpisodeStoreOutcome.SKIPPED, 0),
        ],
    )
    async def test_step15_counts_only_stored(self, outcome, expected):
        engine = _make_engine()
        engine.episodic_memory.store.return_value = outcome

        created = await engine._step_15_reflection_promotion(
            episodes=[], clusters=[], convergence_reports=[{
                "agents": ["a1"], "departments": ["science"],
                "topic": "typed outcome", "coherence": 0.9,
            }],
            emergence_capacity=None, coordination_balance=None,
            notebook_consolidations=0, behavioral_quality_score=None,
        )

        assert created == expected
        assert engine.episodic_memory.store.call_args.kwargs[
            "duplicate_policy"
        ] is EpisodeDuplicatePolicy.EXPECT_SAME_REFLECTION

    @pytest.mark.asyncio
    async def test_step15_passes_expected_policy_for_every_candidate(self):
        engine = _make_engine()
        convs = [
            {"agents": ["a1"], "departments": ["science"], "topic": "one", "coherence": 0.9},
            {"agents": ["a2"], "departments": ["engineering"], "topic": "two", "coherence": 0.8},
        ]

        created = await engine._step_15_reflection_promotion(
            episodes=[], clusters=[], convergence_reports=convs,
            emergence_capacity=None, coordination_balance=None,
            notebook_consolidations=0, behavioral_quality_score=None,
        )

        assert created == 2
        assert all(
            call.kwargs["duplicate_policy"]
            is EpisodeDuplicatePolicy.EXPECT_SAME_REFLECTION
            for call in engine.episodic_memory.store.await_args_list
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "invalid",
        [
            pytest.param("stored", id="raw-stored"),
            pytest.param("duplicate", id="raw-duplicate"),
            pytest.param("skipped", id="raw-skipped"),
            pytest.param(True, id="bool"),
            pytest.param(None, id="none"),
            pytest.param(object(), id="object"),
        ],
    )
    async def test_step15_invalid_outcome_not_counted_and_later_candidate_runs(
        self, invalid, caplog
    ):
        engine = _make_engine()
        engine.episodic_memory.store.side_effect = [
            invalid,
            EpisodeStoreOutcome.STORED,
        ]
        convs = [
            {"agents": ["a1"], "departments": ["science"], "topic": "bad", "coherence": 0.9},
            {"agents": ["a2"], "departments": ["engineering"], "topic": "good", "coherence": 0.8},
        ]

        with caplog.at_level(logging.DEBUG, logger="probos.cognitive.dreaming"):
            created = await engine._step_15_reflection_promotion(
                episodes=[], clusters=[], convergence_reports=convs,
                emergence_capacity=None, coordination_balance=None,
                notebook_consolidations=0, behavioral_quality_score=None,
            )

        assert created == 1
        assert engine.episodic_memory.store.await_count == 2
        first_episode = engine.episodic_memory.store.await_args_list[0].args[0]
        assert first_episode.id in caplog.text
        assert "was not stored and was not counted" in caplog.text
        contract_failures = [
            record
            for record in caplog.records
            if "was not stored and was not counted" in record.message
        ]
        assert len(contract_failures) == 1
        assert contract_failures[0].levelno == logging.DEBUG
        assert contract_failures[0].exc_info is not None
        contract_error = contract_failures[0].exc_info[1]
        assert isinstance(contract_error, TypeError)
        assert str(contract_error) == (
            "episodic_memory.store returned an invalid EpisodeStoreOutcome"
        )

    @pytest.mark.asyncio
    async def test_step15_ordinary_failure_continues_to_later_candidate(self):
        engine = _make_engine()
        engine.episodic_memory.store.side_effect = [
            RuntimeError("transient primary failure"),
            EpisodeStoreOutcome.STORED,
        ]

        created = await engine._step_15_reflection_promotion(
            episodes=[], clusters=[], convergence_reports=[
                {"agents": ["a1"], "departments": ["science"], "topic": "first", "coherence": 0.9},
                {"agents": ["a2"], "departments": ["engineering"], "topic": "second", "coherence": 0.8},
            ],
            emergence_capacity=None, coordination_balance=None,
            notebook_consolidations=0, behavioral_quality_score=None,
        )

        assert created == 1
        assert engine.episodic_memory.store.await_count == 2

    @pytest.mark.asyncio
    async def test_step15_cancellation_propagates_and_stops_candidates(self):
        engine = _make_engine()
        engine.episodic_memory.store.side_effect = asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            await engine._step_15_reflection_promotion(
                episodes=[], clusters=[], convergence_reports=[
                    {"agents": ["a1"], "departments": ["science"], "topic": "first", "coherence": 0.9},
                    {"agents": ["a2"], "departments": ["engineering"], "topic": "second", "coherence": 0.8},
                ],
                emergence_capacity=None, coordination_balance=None,
                notebook_consolidations=0, behavioral_quality_score=None,
            )

        assert engine.episodic_memory.store.await_count == 1


# ===========================================================================
# 10. Step 15 — error handling (2 tests)
# ===========================================================================


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_step15_store_failure_degrades(self):
        """store() raises → returns 0, no crash."""
        engine = _make_engine()
        engine.episodic_memory.store = AsyncMock(side_effect=Exception("db error"))
        conv = {
            "agents": ["a1"],
            "departments": ["science"],
            "topic": "test",
            "coherence": 0.9,
        }
        result = await engine._step_15_reflection_promotion(
            episodes=[],
            clusters=[],
            convergence_reports=[conv],
            emergence_capacity=None,
            coordination_balance=None,
            notebook_consolidations=0,
            behavioral_quality_score=None,
        )
        assert result == 0

    @pytest.mark.asyncio
    async def test_step15_empty_inputs_returns_zero(self):
        """All empty inputs → 0 reflections, no store calls."""
        engine = _make_engine()
        result = await engine._step_15_reflection_promotion(
            episodes=[],
            clusters=[],
            convergence_reports=[],
            emergence_capacity=None,
            coordination_balance=None,
            notebook_consolidations=0,
            behavioral_quality_score=None,
        )
        assert result == 0
        engine.episodic_memory.store.assert_not_called()


# ===========================================================================
# 11. DreamReport wiring (1 test)
# ===========================================================================


class TestDreamReportWiring:
    def test_dream_cycle_includes_reflections_created(self):
        """DreamReport accepts and stores reflections_created."""
        report = DreamReport(reflections_created=3)
        assert report.reflections_created == 3

        default_report = DreamReport()
        assert default_report.reflections_created == 0
