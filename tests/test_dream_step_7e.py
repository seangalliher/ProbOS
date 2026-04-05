"""AD-537: Dream Step 7e observational learning tests.

Tests for the observational learning pipeline that scans Ward Room
threads during dream consolidation to extract procedures from
other agents' discussions.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.procedures import Procedure, ProcedureStep
from probos.config import (
    DreamingConfig,
    OBSERVATION_MAX_THREADS_PER_DREAM,
    OBSERVATION_MIN_TRUST,
)


# ------------------------------------------------------------------ helpers


@dataclass
class _MockThread:
    """Minimal thread object matching Ward Room browse_threads output."""

    id: str = ""
    title: str = ""
    body: str = ""
    author_id: str = ""
    author_callsign: str = ""
    channel_name: str = ""


def _make_store_mock():
    """Build a mock procedure store."""
    store = AsyncMock()
    store.find_matching = AsyncMock(return_value=[])
    store.get = AsyncMock(return_value=None)
    store.get_quality_metrics = AsyncMock(return_value={})
    store.record_selection = AsyncMock()
    store.record_applied = AsyncMock()
    store.record_completion = AsyncMock()
    store.record_fallback = AsyncMock()
    store.save = AsyncMock()
    store.deactivate = AsyncMock()
    store.list_active = AsyncMock(return_value=[])
    store.has_cluster = AsyncMock(return_value=False)
    store.record_consecutive_success = AsyncMock(return_value=1)
    store.reset_consecutive_successes = AsyncMock()
    store.promote_compilation_level = AsyncMock()
    store.demote_compilation_level = AsyncMock()
    return store


def _make_procedure(**overrides):
    """Build a minimal Procedure for testing."""
    defaults = {
        "id": "obs-proc-001",
        "name": "Observed Procedure",
        "description": "Learned from observation",
        "steps": [ProcedureStep(step_number=1, action="Do something observed")],
        "intent_types": ["observed_intent"],
        "is_active": True,
        "generation": 0,
        "compilation_level": 1,
        "tags": [],
    }
    defaults.update(overrides)
    return Procedure(**defaults)


def _make_dreaming_engine(**overrides):
    """Build a minimal DreamingEngine with AD-537 observational learning fields."""
    from probos.cognitive.dreaming import DreamingEngine

    engine = object.__new__(DreamingEngine)
    engine.router = MagicMock()
    engine.trust_network = MagicMock()
    engine.episodic_memory = overrides.get("episodic_memory", AsyncMock())
    engine.config = DreamingConfig()
    engine.pre_warm_intents = []
    engine._idle_scale_down_fn = None
    engine._gap_prediction_fn = None
    engine._last_clusters = []
    engine._contradiction_resolve_fn = None
    engine._last_consolidated_count = 0
    engine._llm_client = overrides.get("llm_client", AsyncMock())
    engine._procedure_store = overrides.get("procedure_store", _make_store_mock())
    engine._last_procedures = []
    engine._extracted_cluster_ids = set()
    engine._addressed_degradations = {}
    engine._extraction_candidates = {}
    engine._reactive_cooldowns = {}
    engine._fallback_learning_queue = []
    # AD-537 fields
    engine._ward_room = overrides.get("ward_room", None)
    engine._agent_id = overrides.get("agent_id", "observer-agent")
    engine._trust_network_lookup = overrides.get("trust_network_lookup", None)
    engine._observed_threads = overrides.get("observed_threads", set())
    # AD-557 fields
    engine._emergence_metrics_engine = None
    engine._get_department = None
    # AD-551 fields
    engine._records_store = None
    # AD-555 fields
    engine._notebook_quality_engine = None
    # AD-541c fields
    engine._retrieval_practice_engine = None
    engine._retrieval_llm_client = None
    # AD-567d fields
    engine._activation_tracker = None
    return engine


def _make_thread(**overrides):
    """Build a mock Ward Room thread."""
    defaults = {
        "id": "thread-001",
        "title": "How to handle sensor calibration",
        "body": "Step 1: Run diagnostics\nStep 2: Adjust thresholds",
        "author_id": "other-agent",
        "author_callsign": "LaForge",
        "channel_name": "engineering",
    }
    defaults.update(overrides)
    return _MockThread(**defaults)


# ==================================================================
# Test Class: TestObservationalLearning (Dream Step 7e)
# ==================================================================


class TestObservationalLearning:
    """AD-537: Observational learning from Ward Room threads."""

    @pytest.mark.asyncio
    async def test_step_7e_scans_recent_threads(self):
        """browse_threads is called and threads are scanned."""
        ward_room = AsyncMock()
        thread = _make_thread()
        ward_room.browse_threads = AsyncMock(return_value=[thread])

        store = _make_store_mock()
        store.find_matching = AsyncMock(return_value=[])

        # Trust lookup returns high trust
        trust_lookup = lambda aid: 0.8

        engine = _make_dreaming_engine(
            ward_room=ward_room,
            procedure_store=store,
            trust_network_lookup=trust_lookup,
        )

        with patch(
            "probos.cognitive.dreaming.extract_procedure_from_observation",
            new_callable=AsyncMock,
            return_value=None,
        ):
            stats = await engine._process_observational_learning()

        ward_room.browse_threads.assert_called_once()
        call_kwargs = ward_room.browse_threads.call_args.kwargs
        assert call_kwargs["agent_id"] == "observer-agent"
        assert call_kwargs["sort"] == "recent"
        assert stats["scanned"] == 1

    @pytest.mark.asyncio
    async def test_step_7e_skips_own_threads(self):
        """Threads authored by the dreaming agent itself are skipped."""
        ward_room = AsyncMock()
        own_thread = _make_thread(author_id="observer-agent")
        ward_room.browse_threads = AsyncMock(return_value=[own_thread])

        trust_lookup = lambda aid: 0.8

        engine = _make_dreaming_engine(
            ward_room=ward_room,
            trust_network_lookup=trust_lookup,
        )

        with patch(
            "probos.cognitive.dreaming.extract_procedure_from_observation",
            new_callable=AsyncMock,
        ) as mock_extract:
            stats = await engine._process_observational_learning()

        # Thread was scanned but extraction was never called (skipped)
        assert stats["scanned"] == 1
        assert stats["observed"] == 0
        mock_extract.assert_not_called()

    @pytest.mark.asyncio
    async def test_step_7e_skips_low_trust_authors(self):
        """Threads from authors with trust below OBSERVATION_MIN_TRUST are skipped."""
        ward_room = AsyncMock()
        thread = _make_thread(author_id="untrusted-agent")
        ward_room.browse_threads = AsyncMock(return_value=[thread])

        # Return trust below the 0.5 threshold
        trust_lookup = lambda aid: 0.3

        engine = _make_dreaming_engine(
            ward_room=ward_room,
            trust_network_lookup=trust_lookup,
        )

        with patch(
            "probos.cognitive.dreaming.extract_procedure_from_observation",
            new_callable=AsyncMock,
        ) as mock_extract:
            stats = await engine._process_observational_learning()

        assert stats["scanned"] == 1
        assert stats["observed"] == 0
        mock_extract.assert_not_called()

    @pytest.mark.asyncio
    async def test_step_7e_skips_dm_channels(self):
        """Threads in DM channels (channel_name starts with 'dm:') are skipped."""
        ward_room = AsyncMock()
        dm_thread = _make_thread(channel_name="dm:observer-agent:other-agent")
        ward_room.browse_threads = AsyncMock(return_value=[dm_thread])

        trust_lookup = lambda aid: 0.8

        engine = _make_dreaming_engine(
            ward_room=ward_room,
            trust_network_lookup=trust_lookup,
        )

        with patch(
            "probos.cognitive.dreaming.extract_procedure_from_observation",
            new_callable=AsyncMock,
        ) as mock_extract:
            stats = await engine._process_observational_learning()

        assert stats["scanned"] == 1
        assert stats["observed"] == 0
        mock_extract.assert_not_called()

    @pytest.mark.asyncio
    async def test_step_7e_respects_max_threads(self):
        """The limit passed to browse_threads matches OBSERVATION_MAX_THREADS_PER_DREAM."""
        ward_room = AsyncMock()
        ward_room.browse_threads = AsyncMock(return_value=[])

        engine = _make_dreaming_engine(ward_room=ward_room)

        await engine._process_observational_learning()

        call_kwargs = ward_room.browse_threads.call_args.kwargs
        assert call_kwargs["limit"] == OBSERVATION_MAX_THREADS_PER_DREAM

    @pytest.mark.asyncio
    async def test_step_7e_dedup_across_dreams(self):
        """Already-observed thread IDs are not re-processed in subsequent dreams."""
        ward_room = AsyncMock()
        thread = _make_thread(id="thread-seen-before")
        ward_room.browse_threads = AsyncMock(return_value=[thread])

        trust_lookup = lambda aid: 0.8

        # Pre-populate _observed_threads to simulate a previous dream cycle
        engine = _make_dreaming_engine(
            ward_room=ward_room,
            trust_network_lookup=trust_lookup,
            observed_threads={"thread-seen-before"},
        )

        with patch(
            "probos.cognitive.dreaming.extract_procedure_from_observation",
            new_callable=AsyncMock,
        ) as mock_extract:
            stats = await engine._process_observational_learning()

        # Thread scanned but skipped due to dedup
        assert stats["scanned"] == 1
        assert stats["observed"] == 0
        mock_extract.assert_not_called()

    @pytest.mark.asyncio
    async def test_step_7e_saves_to_procedure_store(self):
        """When extraction succeeds, the procedure is saved to the store."""
        ward_room = AsyncMock()
        thread = _make_thread(id="thread-new")
        ward_room.browse_threads = AsyncMock(return_value=[thread])

        store = _make_store_mock()
        store.find_matching = AsyncMock(return_value=[])

        trust_lookup = lambda aid: 0.8
        extracted_proc = _make_procedure()

        engine = _make_dreaming_engine(
            ward_room=ward_room,
            procedure_store=store,
            trust_network_lookup=trust_lookup,
        )

        with patch(
            "probos.cognitive.dreaming.extract_procedure_from_observation",
            new_callable=AsyncMock,
            return_value=extracted_proc,
        ):
            stats = await engine._process_observational_learning()

        assert stats["observed"] == 1
        store.save.assert_called_once_with(extracted_proc)
        # Verify provenance tag was added
        assert any("ward_room_thread:thread-new" in t for t in extracted_proc.tags)

    @pytest.mark.asyncio
    async def test_step_7e_skips_if_similar_exists(self):
        """When find_matching returns a high-score result, the procedure is skipped."""
        ward_room = AsyncMock()
        thread = _make_thread(id="thread-dup")
        ward_room.browse_threads = AsyncMock(return_value=[thread])

        store = _make_store_mock()
        # Simulate an existing similar procedure with high similarity score
        store.find_matching = AsyncMock(return_value=[{"id": "existing-proc", "score": 0.95}])

        trust_lookup = lambda aid: 0.8
        extracted_proc = _make_procedure()

        engine = _make_dreaming_engine(
            ward_room=ward_room,
            procedure_store=store,
            trust_network_lookup=trust_lookup,
        )

        with patch(
            "probos.cognitive.dreaming.extract_procedure_from_observation",
            new_callable=AsyncMock,
            return_value=extracted_proc,
        ):
            stats = await engine._process_observational_learning()

        assert stats["observed"] == 0
        store.save.assert_not_called()

    @pytest.mark.asyncio
    async def test_step_7e_updates_dream_report(self):
        """DreamReport includes procedures_observed and observation_threads_scanned."""
        ward_room = AsyncMock()
        thread = _make_thread(id="thread-report")
        ward_room.browse_threads = AsyncMock(return_value=[thread])

        store = _make_store_mock()
        store.find_matching = AsyncMock(return_value=[])

        trust_lookup = lambda aid: 0.8
        extracted_proc = _make_procedure()

        engine = _make_dreaming_engine(
            ward_room=ward_room,
            procedure_store=store,
            trust_network_lookup=trust_lookup,
        )

        with patch(
            "probos.cognitive.dreaming.extract_procedure_from_observation",
            new_callable=AsyncMock,
            return_value=extracted_proc,
        ):
            stats = await engine._process_observational_learning()

        # Verify the stats dict that feeds DreamReport
        assert stats["observed"] == 1
        assert stats["scanned"] == 1

    @pytest.mark.asyncio
    async def test_step_7e_no_ward_room_graceful(self):
        """When no ward_room is configured, returns zero counts gracefully."""
        engine = _make_dreaming_engine(ward_room=None)

        stats = await engine._process_observational_learning()

        assert stats == {"observed": 0, "scanned": 0}
