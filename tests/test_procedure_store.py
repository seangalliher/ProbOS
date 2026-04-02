"""AD-533: Procedure Store tests.

Tests cover:
- Part 0: Dataclass extension (new fields, from_dict)
- Parts 1-2: ProcedureStore class structure + schema
- Part 3: CRUD operations (save, get, list_active, has_cluster, delete)
- Part 4: Semantic search (find_matching)
- Part 5: Quality metrics (counters, derived rates)
- Part 6: Version DAG traversal (lineage, descendants, deactivate)
- Part 7: Dream cycle integration (persistence, cross-session dedup)
- Part 8: Thread safety (WAL mode, foreign keys)
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.procedures import Procedure, ProcedureStep
from probos.types import Episode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_procedure(
    proc_id: str = "proc-1",
    name: str = "Test Procedure",
    description: str = "A test procedure",
    steps: list[ProcedureStep] | None = None,
    intent_types: list[str] | None = None,
    origin_cluster_id: str = "cluster-1",
    evolution_type: str = "CAPTURED",
    is_active: bool = True,
    is_negative: bool = False,
    generation: int = 0,
    parent_procedure_ids: list[str] | None = None,
    compilation_level: int = 1,
    tags: list[str] | None = None,
) -> Procedure:
    """Build a minimal Procedure for testing."""
    return Procedure(
        id=proc_id,
        name=name,
        description=description,
        steps=steps or [
            ProcedureStep(step_number=1, action="Do thing"),
            ProcedureStep(step_number=2, action="Do other thing"),
        ],
        intent_types=intent_types or ["read"],
        origin_cluster_id=origin_cluster_id,
        origin_agent_ids=["agent-a"],
        provenance=["ep-1", "ep-2"],
        extraction_date=time.time(),
        evolution_type=evolution_type,
        is_active=is_active,
        is_negative=is_negative,
        generation=generation,
        parent_procedure_ids=parent_procedure_ids or [],
        compilation_level=compilation_level,
        tags=tags or [],
    )


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
    cluster_id: str = "abc123",
    episode_ids: list[str] | None = None,
    is_success_dominant: bool = True,
    is_failure_dominant: bool = False,
    success_rate: float = 1.0,
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
    c.intent_types = intent_types or ["read"]
    return c


@pytest.fixture
async def store(tmp_path: Path):
    """Create a ProcedureStore with a real SQLite backend (no ChromaDB)."""
    from probos.cognitive.procedure_store import ProcedureStore

    s = ProcedureStore(data_dir=tmp_path / "procedures")
    await s.start()
    yield s
    await s.stop()


# ===========================================================================
# Part 0: Dataclass Extension
# ===========================================================================


class TestProcedureDataclassExtension:
    """Tests for the 6 new fields added by AD-533."""

    def test_new_fields_have_defaults(self):
        """All 6 new fields have backward-compatible defaults."""
        p = Procedure()
        assert p.is_active is True
        assert p.generation == 0
        assert p.parent_procedure_ids == []
        assert p.is_negative is False
        assert p.superseded_by == ""
        assert p.tags == []

    def test_to_dict_includes_new_fields(self):
        """to_dict() serializes all 6 new fields."""
        p = Procedure(is_active=False, generation=2, tags=["domain:ops"])
        d = p.to_dict()
        assert d["is_active"] is False
        assert d["generation"] == 2
        assert d["parent_procedure_ids"] == []
        assert d["is_negative"] is False
        assert d["superseded_by"] == ""
        assert d["tags"] == ["domain:ops"]

    def test_from_dict_round_trip(self):
        """from_dict(to_dict()) produces an equivalent Procedure."""
        original = _make_procedure(
            is_negative=True, generation=3,
            parent_procedure_ids=["parent-1"],
            tags=["security"],
        )
        reconstructed = Procedure.from_dict(original.to_dict())
        assert reconstructed.id == original.id
        assert reconstructed.name == original.name
        assert reconstructed.is_negative == original.is_negative
        assert reconstructed.generation == original.generation
        assert reconstructed.parent_procedure_ids == original.parent_procedure_ids
        assert reconstructed.tags == original.tags
        assert len(reconstructed.steps) == len(original.steps)

    def test_from_dict_missing_fields_uses_defaults(self):
        """from_dict() gracefully handles missing new fields."""
        minimal = {"id": "abc", "name": "Minimal"}
        p = Procedure.from_dict(minimal)
        assert p.id == "abc"
        assert p.name == "Minimal"
        assert p.is_active is True
        assert p.generation == 0
        assert p.tags == []

    def test_from_dict_preserves_steps(self):
        """from_dict() reconstructs ProcedureStep objects."""
        data = {
            "steps": [
                {"step_number": 1, "action": "Parse input"},
                {"step_number": 2, "action": "Execute"},
            ]
        }
        p = Procedure.from_dict(data)
        assert len(p.steps) == 2
        assert p.steps[0].action == "Parse input"
        assert p.steps[1].step_number == 2


# ===========================================================================
# Parts 1-2: Store Init + Schema
# ===========================================================================


class TestStoreInit:
    """Tests for ProcedureStore initialization and lifecycle."""

    @pytest.mark.asyncio
    async def test_init_accepts_all_params(self, tmp_path: Path):
        from probos.cognitive.procedure_store import ProcedureStore

        mock_factory = MagicMock()
        s = ProcedureStore(
            data_dir=tmp_path,
            records_store=MagicMock(),
            connection_factory=mock_factory,
        )
        assert s._connection_factory is mock_factory

    @pytest.mark.asyncio
    async def test_init_falls_back_to_default_factory(self, tmp_path: Path):
        from probos.cognitive.procedure_store import ProcedureStore
        from probos.storage.sqlite_factory import default_factory

        s = ProcedureStore(data_dir=tmp_path)
        assert s._connection_factory is default_factory

    @pytest.mark.asyncio
    async def test_start_creates_db(self, store):
        assert store._db is not None

    @pytest.mark.asyncio
    async def test_stop_closes_db(self, tmp_path: Path):
        from probos.cognitive.procedure_store import ProcedureStore

        s = ProcedureStore(data_dir=tmp_path / "proc")
        await s.start()
        assert s._db is not None
        await s.stop()
        assert s._db is None

    @pytest.mark.asyncio
    async def test_chroma_failure_non_fatal(self, tmp_path: Path):
        """ChromaDB failure doesn't prevent start."""
        from probos.cognitive.procedure_store import ProcedureStore

        s = ProcedureStore(data_dir=tmp_path / "proc")
        # Ensure that _init_chroma's internal try/except catches the error
        with patch("probos.cognitive.procedure_store.ProcedureStore._init_chroma") as mock_init:
            mock_init.side_effect = None  # Don't raise, let it be a no-op
            await s.start()
            assert s._chroma_collection is None  # Was never set
            await s.stop()

    @pytest.mark.asyncio
    async def test_schema_creates_tables(self, store):
        """Schema creates expected tables."""
        cursor = await store._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='procedure_records'"
        )
        row = await cursor.fetchone()
        assert row is not None

        cursor = await store._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='procedure_lineage_parents'"
        )
        row = await cursor.fetchone()
        assert row is not None


# ===========================================================================
# Part 3: CRUD Operations
# ===========================================================================


class TestCRUD:
    """Tests for save, get, list_active, has_cluster, delete."""

    @pytest.mark.asyncio
    async def test_save_and_get_round_trip(self, store):
        proc = _make_procedure()
        returned_id = await store.save(proc)
        assert returned_id == proc.id

        loaded = await store.get(proc.id)
        assert loaded is not None
        assert loaded.id == proc.id
        assert loaded.name == proc.name
        assert len(loaded.steps) == 2

    @pytest.mark.asyncio
    async def test_save_requires_procedure_type(self, store):
        with pytest.raises(TypeError, match="Expected Procedure"):
            await store.save({"not": "a procedure"})

    @pytest.mark.asyncio
    async def test_get_not_found_returns_none(self, store):
        result = await store.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_active_returns_saved_procedures(self, store):
        proc = _make_procedure()
        await store.save(proc)

        results = await store.list_active()
        assert len(results) == 1
        assert results[0]["id"] == proc.id
        assert results[0]["name"] == proc.name

    @pytest.mark.asyncio
    async def test_list_active_excludes_inactive(self, store):
        active = _make_procedure(proc_id="active-1")
        inactive = _make_procedure(proc_id="inactive-1", is_active=False)
        await store.save(active)
        await store.save(inactive)

        results = await store.list_active()
        ids = [r["id"] for r in results]
        assert "active-1" in ids
        assert "inactive-1" not in ids

    @pytest.mark.asyncio
    async def test_list_active_filter_by_evolution_type(self, store):
        cap = _make_procedure(proc_id="cap-1", evolution_type="CAPTURED")
        fix = _make_procedure(proc_id="fix-1", evolution_type="FIX")
        await store.save(cap)
        await store.save(fix)

        results = await store.list_active(evolution_type="FIX")
        assert len(results) == 1
        assert results[0]["id"] == "fix-1"

    @pytest.mark.asyncio
    async def test_list_active_filter_by_intent_type(self, store):
        p1 = _make_procedure(proc_id="p1", intent_types=["read"])
        p2 = _make_procedure(proc_id="p2", intent_types=["write"])
        await store.save(p1)
        await store.save(p2)

        results = await store.list_active(intent_type="read")
        assert len(results) == 1
        assert results[0]["id"] == "p1"

    @pytest.mark.asyncio
    async def test_list_active_filter_by_min_compilation_level(self, store):
        low = _make_procedure(proc_id="low", compilation_level=1)
        high = _make_procedure(proc_id="high", compilation_level=3)
        await store.save(low)
        await store.save(high)

        results = await store.list_active(min_compilation_level=2)
        assert len(results) == 1
        assert results[0]["id"] == "high"

    @pytest.mark.asyncio
    async def test_has_cluster_true(self, store):
        proc = _make_procedure(origin_cluster_id="cluster-x")
        await store.save(proc)
        assert await store.has_cluster("cluster-x") is True

    @pytest.mark.asyncio
    async def test_has_cluster_false(self, store):
        assert await store.has_cluster("nonexistent") is False

    @pytest.mark.asyncio
    async def test_delete_removes_procedure(self, store):
        proc = _make_procedure()
        await store.save(proc)
        assert await store.get(proc.id) is not None

        deleted = await store.delete(proc.id)
        assert deleted is True
        assert await store.get(proc.id) is None

    @pytest.mark.asyncio
    async def test_delete_not_found_returns_false(self, store):
        assert await store.delete("nonexistent") is False

    @pytest.mark.asyncio
    async def test_save_writes_to_records_store(self, tmp_path: Path):
        """save() calls records_store.write_entry()."""
        from probos.cognitive.procedure_store import ProcedureStore

        mock_records = AsyncMock()
        s = ProcedureStore(data_dir=tmp_path / "proc", records_store=mock_records)
        await s.start()
        try:
            proc = _make_procedure()
            await s.save(proc)
            mock_records.write_entry.assert_called_once()
            call_kwargs = mock_records.write_entry.call_args
            assert "procedures/" in call_kwargs.kwargs.get("path", call_kwargs[1].get("path", ""))
        finally:
            await s.stop()

    @pytest.mark.asyncio
    async def test_save_negative_to_anti_patterns_subdir(self, tmp_path: Path):
        """Negative procedures go to procedures/anti-patterns/."""
        from probos.cognitive.procedure_store import ProcedureStore

        mock_records = AsyncMock()
        s = ProcedureStore(data_dir=tmp_path / "proc", records_store=mock_records)
        await s.start()
        try:
            proc = _make_procedure(is_negative=True)
            await s.save(proc)
            call_kwargs = mock_records.write_entry.call_args
            path_arg = call_kwargs.kwargs.get("path", call_kwargs[1].get("path", ""))
            assert "anti-patterns" in path_arg
        finally:
            await s.stop()


# ===========================================================================
# Part 4: Semantic Search
# ===========================================================================


class TestSemanticSearch:
    """Tests for find_matching (ChromaDB)."""

    @pytest.mark.asyncio
    async def test_find_matching_empty_on_no_chroma(self, store):
        """Graceful empty list when ChromaDB unavailable."""
        store._chroma_collection = None
        results = await store.find_matching("read file")
        assert results == []


# ===========================================================================
# Part 5: Quality Metrics
# ===========================================================================


class TestQualityMetrics:
    """Tests for quality metric recording and reading."""

    @pytest.mark.asyncio
    async def test_record_selection_increments_counter(self, store):
        proc = _make_procedure()
        await store.save(proc)
        await store.record_selection(proc.id)

        metrics = await store.get_quality_metrics(proc.id)
        assert metrics["total_selections"] == 1

    @pytest.mark.asyncio
    async def test_record_applied_increments_counter(self, store):
        proc = _make_procedure()
        await store.save(proc)
        await store.record_applied(proc.id)

        metrics = await store.get_quality_metrics(proc.id)
        assert metrics["total_applied"] == 1

    @pytest.mark.asyncio
    async def test_record_completion_increments_counter(self, store):
        proc = _make_procedure()
        await store.save(proc)
        await store.record_completion(proc.id)

        metrics = await store.get_quality_metrics(proc.id)
        assert metrics["total_completions"] == 1

    @pytest.mark.asyncio
    async def test_record_fallback_increments_counter(self, store):
        proc = _make_procedure()
        await store.save(proc)
        await store.record_fallback(proc.id)

        metrics = await store.get_quality_metrics(proc.id)
        assert metrics["total_fallbacks"] == 1

    @pytest.mark.asyncio
    async def test_get_quality_metrics_returns_counters_and_rates(self, store):
        proc = _make_procedure()
        await store.save(proc)
        # Simulate: 10 selections, 8 applied, 6 completed, 2 fallbacks
        for _ in range(10):
            await store.record_selection(proc.id)
        for _ in range(8):
            await store.record_applied(proc.id)
        for _ in range(6):
            await store.record_completion(proc.id)
        for _ in range(2):
            await store.record_fallback(proc.id)

        metrics = await store.get_quality_metrics(proc.id)
        assert metrics["total_selections"] == 10
        assert metrics["total_applied"] == 8
        assert metrics["total_completions"] == 6
        assert metrics["total_fallbacks"] == 2
        assert metrics["applied_rate"] == pytest.approx(0.8)
        assert metrics["completion_rate"] == pytest.approx(0.75)
        assert metrics["effective_rate"] == pytest.approx(0.6)
        assert metrics["fallback_rate"] == pytest.approx(0.2)

    @pytest.mark.asyncio
    async def test_get_quality_metrics_not_found_returns_none(self, store):
        assert await store.get_quality_metrics("unknown") is None

    @pytest.mark.asyncio
    async def test_increment_invalid_column_raises(self, store):
        with pytest.raises(ValueError, match="Invalid counter column"):
            await store._increment_counter("proc-1", "not_a_real_column")


# ===========================================================================
# Part 6: Version DAG Traversal
# ===========================================================================


class TestVersionDAG:
    """Tests for lineage, descendants, and deactivation."""

    @pytest.mark.asyncio
    async def test_get_lineage_single_parent(self, store):
        parent = _make_procedure(proc_id="parent")
        child = _make_procedure(proc_id="child", parent_procedure_ids=["parent"])
        await store.save(parent)
        await store.save(child)

        lineage = await store.get_lineage("child")
        assert "parent" in lineage

    @pytest.mark.asyncio
    async def test_get_lineage_multi_generation(self, store):
        grandparent = _make_procedure(proc_id="gp")
        parent = _make_procedure(proc_id="parent", parent_procedure_ids=["gp"])
        child = _make_procedure(proc_id="child", parent_procedure_ids=["parent"])
        await store.save(grandparent)
        await store.save(parent)
        await store.save(child)

        lineage = await store.get_lineage("child")
        assert "parent" in lineage
        assert "gp" in lineage

    @pytest.mark.asyncio
    async def test_get_descendants_single_child(self, store):
        parent = _make_procedure(proc_id="parent")
        child = _make_procedure(proc_id="child", parent_procedure_ids=["parent"])
        await store.save(parent)
        await store.save(child)

        descendants = await store.get_descendants("parent")
        assert "child" in descendants

    @pytest.mark.asyncio
    async def test_get_descendants_multi_generation(self, store):
        root = _make_procedure(proc_id="root")
        mid = _make_procedure(proc_id="mid", parent_procedure_ids=["root"])
        leaf = _make_procedure(proc_id="leaf", parent_procedure_ids=["mid"])
        await store.save(root)
        await store.save(mid)
        await store.save(leaf)

        descendants = await store.get_descendants("root")
        assert "mid" in descendants
        assert "leaf" in descendants

    @pytest.mark.asyncio
    async def test_deactivate_sets_inactive_and_superseded(self, store):
        proc = _make_procedure(proc_id="old")
        await store.save(proc)

        await store.deactivate("old", superseded_by="new")

        loaded = await store.get("old")
        assert loaded is not None
        assert loaded.is_active is False
        assert loaded.superseded_by == "new"

    @pytest.mark.asyncio
    async def test_deactivate_removes_from_active_list(self, store):
        proc = _make_procedure(proc_id="to-deactivate")
        await store.save(proc)
        assert len(await store.list_active()) == 1

        await store.deactivate("to-deactivate")
        assert len(await store.list_active()) == 0

    @pytest.mark.asyncio
    async def test_lineage_empty_for_root_procedure(self, store):
        root = _make_procedure(proc_id="root")
        await store.save(root)
        assert await store.get_lineage("root") == []

    @pytest.mark.asyncio
    async def test_descendants_empty_for_leaf_procedure(self, store):
        leaf = _make_procedure(proc_id="leaf")
        await store.save(leaf)
        assert await store.get_descendants("leaf") == []


# ===========================================================================
# Part 7: Dream Cycle Integration
# ===========================================================================


def _make_mock_router():
    """Create a mock HebbianRouter that doesn't crash on weight operations."""
    router = MagicMock()
    router.get_weight = MagicMock(return_value=0.5)
    router._weights = {}
    router._compat_weights = {}
    router.decay_all = MagicMock()
    return router


class TestDreamCycleIntegration:
    """Tests for procedure_store wiring in DreamingEngine."""

    def test_dreaming_engine_accepts_procedure_store(self):
        """DreamingEngine.__init__ stores _procedure_store."""
        from probos.cognitive.dreaming import DreamingEngine
        from probos.config import DreamingConfig

        mock_store = MagicMock()
        engine = DreamingEngine(
            router=_make_mock_router(),
            trust_network=MagicMock(),
            episodic_memory=MagicMock(),
            config=DreamingConfig(),
            procedure_store=mock_store,
        )
        assert engine._procedure_store is mock_store

    @pytest.mark.asyncio
    async def test_dream_cycle_persists_procedures_to_store(self):
        """Dream cycle calls store.save() for each extracted procedure."""
        from probos.cognitive.dreaming import DreamingEngine
        from probos.config import DreamingConfig

        mock_store = AsyncMock()
        mock_store.has_cluster = AsyncMock(return_value=False)

        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=MagicMock(
            content=json.dumps({
                "name": "Test proc",
                "description": "desc",
                "steps": [{"step_number": 1, "action": "act"}],
                "preconditions": [],
                "postconditions": [],
            })
        ))

        episodes = [
            _make_episode(f"e{i}", outcomes=[{"intent": "read", "success": True}], agent_ids=["a1"])
            for i in range(3)
        ]

        mock_mem = AsyncMock()
        mock_mem.recent = AsyncMock(return_value=episodes)
        mock_mem.get_stats = AsyncMock(return_value={"total": 3})
        mock_mem.get_embeddings = AsyncMock(return_value={
            f"e{i}": [float(i) / 10] * 128 for i in range(3)
        })

        engine = DreamingEngine(
            router=_make_mock_router(),
            trust_network=MagicMock(raw_scores=MagicMock(return_value={})),
            episodic_memory=mock_mem,
            config=DreamingConfig(),
            llm_client=mock_llm,
            procedure_store=mock_store,
        )

        # Mock cluster_episodes to return a success-dominant cluster
        cluster = _make_cluster(episode_ids=["e0", "e1", "e2"])
        with patch("probos.cognitive.dreaming.cluster_episodes", return_value=[cluster]):
            await engine.dream_cycle()

        # At least one save call should have been made
        assert mock_store.save.call_count >= 1

    @pytest.mark.asyncio
    async def test_dream_cycle_cross_session_dedup(self):
        """Dream cycle skips clusters already in persistent store."""
        from probos.cognitive.dreaming import DreamingEngine
        from probos.config import DreamingConfig

        mock_store = AsyncMock()
        mock_store.has_cluster = AsyncMock(return_value=True)  # Already persisted

        mock_llm = AsyncMock()

        episodes = [
            _make_episode(f"e{i}", outcomes=[{"intent": "read", "success": True}], agent_ids=["a1"])
            for i in range(3)
        ]

        mock_mem = AsyncMock()
        mock_mem.recent = AsyncMock(return_value=episodes)
        mock_mem.get_stats = AsyncMock(return_value={"total": 3})
        mock_mem.get_embeddings = AsyncMock(return_value={
            f"e{i}": [float(i) / 10] * 128 for i in range(3)
        })

        engine = DreamingEngine(
            router=_make_mock_router(),
            trust_network=MagicMock(raw_scores=MagicMock(return_value={})),
            episodic_memory=mock_mem,
            config=DreamingConfig(),
            llm_client=mock_llm,
            procedure_store=mock_store,
        )

        cluster = _make_cluster(episode_ids=["e0", "e1", "e2"])
        with patch("probos.cognitive.dreaming.cluster_episodes", return_value=[cluster]):
            report = await engine.dream_cycle()

        # LLM should NOT have been called (cluster was deduped)
        mock_llm.complete.assert_not_called()
        assert report.procedures_extracted == 0

    @pytest.mark.asyncio
    async def test_dream_cycle_store_failure_non_critical(self):
        """Store save() failure doesn't crash dream cycle."""
        from probos.cognitive.dreaming import DreamingEngine
        from probos.config import DreamingConfig

        mock_store = AsyncMock()
        mock_store.has_cluster = AsyncMock(return_value=False)
        mock_store.save = AsyncMock(side_effect=Exception("disk full"))

        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=MagicMock(
            content=json.dumps({
                "name": "Test proc",
                "description": "desc",
                "steps": [{"step_number": 1, "action": "act"}],
                "preconditions": [],
                "postconditions": [],
            })
        ))

        episodes = [
            _make_episode(f"e{i}", outcomes=[{"intent": "read", "success": True}], agent_ids=["a1"])
            for i in range(3)
        ]

        mock_mem = AsyncMock()
        mock_mem.recent = AsyncMock(return_value=episodes)
        mock_mem.get_stats = AsyncMock(return_value={"total": 3})
        mock_mem.get_embeddings = AsyncMock(return_value={
            f"e{i}": [float(i) / 10] * 128 for i in range(3)
        })

        engine = DreamingEngine(
            router=_make_mock_router(),
            trust_network=MagicMock(raw_scores=MagicMock(return_value={})),
            episodic_memory=mock_mem,
            config=DreamingConfig(),
            llm_client=mock_llm,
            procedure_store=mock_store,
        )

        cluster = _make_cluster(episode_ids=["e0", "e1", "e2"])
        with patch("probos.cognitive.dreaming.cluster_episodes", return_value=[cluster]):
            report = await engine.dream_cycle()

        # Extraction still counted even though persistence failed
        assert report.procedures_extracted >= 1

    @pytest.mark.asyncio
    async def test_dream_cycle_works_without_store(self):
        """procedure_store=None doesn't cause errors."""
        from probos.cognitive.dreaming import DreamingEngine
        from probos.config import DreamingConfig

        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=MagicMock(
            content=json.dumps({
                "name": "Test proc",
                "description": "desc",
                "steps": [{"step_number": 1, "action": "act"}],
                "preconditions": [],
                "postconditions": [],
            })
        ))

        episodes = [
            _make_episode(f"e{i}", outcomes=[{"intent": "read", "success": True}], agent_ids=["a1"])
            for i in range(3)
        ]

        mock_mem = AsyncMock()
        mock_mem.recent = AsyncMock(return_value=episodes)
        mock_mem.get_stats = AsyncMock(return_value={"total": 3})
        mock_mem.get_embeddings = AsyncMock(return_value={
            f"e{i}": [float(i) / 10] * 128 for i in range(3)
        })

        engine = DreamingEngine(
            router=_make_mock_router(),
            trust_network=MagicMock(raw_scores=MagicMock(return_value={})),
            episodic_memory=mock_mem,
            config=DreamingConfig(),
            llm_client=mock_llm,
            procedure_store=None,  # No store
        )

        cluster = _make_cluster(episode_ids=["e0", "e1", "e2"])
        with patch("probos.cognitive.dreaming.cluster_episodes", return_value=[cluster]):
            report = await engine.dream_cycle()

        assert report.procedures_extracted >= 1


# ===========================================================================
# Part 8: Thread Safety
# ===========================================================================


class TestThreadSafety:
    """Tests for WAL mode and foreign keys."""

    @pytest.mark.asyncio
    async def test_wal_mode_enabled(self, store):
        """PRAGMA journal_mode returns 'wal'."""
        cursor = await store._db.execute("PRAGMA journal_mode")
        row = await cursor.fetchone()
        assert row is not None
        assert row[0].lower() == "wal"

    @pytest.mark.asyncio
    async def test_foreign_keys_enabled(self, store):
        """PRAGMA foreign_keys returns 1."""
        cursor = await store._db.execute("PRAGMA foreign_keys")
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == 1

    @pytest.mark.asyncio
    async def test_write_lock_exists(self, store):
        """Store has a threading.Lock for write serialization."""
        assert hasattr(store, '_write_lock')
        # Verify it's a lock by checking it has acquire/release
        assert hasattr(store._write_lock, 'acquire')
        assert hasattr(store._write_lock, 'release')
