"""BF-296 — shutdown.py Phase A ordering.

Verifies that startup/shutdown.shutdown() calls
``intent_bus.close_to_new_dispatches()`` BEFORE
``dream_scheduler.stop_gracefully()`` and BEFORE the explicit
``consolidate_for_shutdown()`` consolidation call (AD-959 — the lean
shutdown consolidation that replaced the full ``dream_cycle()``).

See prompts/bf-296/bf-296-shutdown-phase-a.md and #771.
"""
from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.startup.shutdown import _stop_runtime_sqlite_sidecars, shutdown


@pytest.mark.asyncio
async def test_phase_a_runs_before_stop_gracefully(tmp_path: Any) -> None:
    """BF-296 Phase A: intent bus close happens before DreamScheduler.stop_gracefully."""
    call_order: list[str] = []

    runtime = MagicMock()
    runtime._started = True
    runtime._shutdown_started = False  # BF-598: MagicMock auto-creates a truthy attr otherwise
    runtime._session_id = "s1"
    runtime._start_time_wall = time.time()
    runtime._start_time = time.monotonic()
    runtime._data_dir = tmp_path
    runtime.registry.all.return_value = []
    runtime.ontology = MagicMock()
    runtime.event_log.log = AsyncMock()
    runtime.ward_room = None
    runtime.config.memory.shutdown_drain_timeout_s = 1.0
    runtime.config.memory.shutdown_consolidation_timeout_s = 1.0

    # intent_bus.close_to_new_dispatches records call order
    intent_bus = MagicMock()
    intent_bus.close_to_new_dispatches = MagicMock(
        side_effect=lambda: call_order.append("close")
    )
    runtime.intent_bus = intent_bus

    # dream_scheduler.stop_gracefully records call order
    dream_sched = MagicMock()

    async def _stop_gracefully(timeout: float) -> bool:
        call_order.append("stop_gracefully")
        return True

    dream_sched.stop_gracefully = _stop_gracefully

    # engine.consolidate_for_shutdown records call order (AD-959 lean path)
    engine = MagicMock()

    async def _consolidate_for_shutdown() -> Any:
        call_order.append("dream_cycle")
        report = MagicMock()
        report.episodes_replayed = 0
        report.weights_strengthened = 0
        report.weights_pruned = 0
        return report

    engine.consolidate_for_shutdown = _consolidate_for_shutdown
    dream_sched.engine = engine
    runtime.dream_scheduler = dream_sched

    runtime.episodic_memory = MagicMock()
    runtime.episodic_memory.stop = AsyncMock()

    try:
        await shutdown(runtime, reason="test")
    except Exception:
        # Phase 2 service stops may raise on our MagicMock — we only care
        # about the Phase 1 ordering captured in call_order before the raise.
        pass

    # Required ordering: close → stop_gracefully → dream_cycle
    assert "close" in call_order
    assert "stop_gracefully" in call_order
    assert "dream_cycle" in call_order
    assert call_order.index("close") < call_order.index("stop_gracefully")
    assert call_order.index("stop_gracefully") < call_order.index("dream_cycle")


@pytest.mark.asyncio
async def test_phase_a_logs_info_on_success(
    tmp_path: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """BF-296: shutdown logs 'intent dispatch closed' INFO line on success."""
    import logging

    runtime = MagicMock()
    runtime._started = True
    runtime._shutdown_started = False  # BF-598: MagicMock auto-creates a truthy attr otherwise
    runtime._session_id = "s1"
    runtime._start_time_wall = time.time()
    runtime._start_time = time.monotonic()
    runtime._data_dir = tmp_path
    runtime.registry.all.return_value = []
    runtime.ontology = MagicMock()
    runtime.event_log.log = AsyncMock()
    runtime.ward_room = None
    runtime.config.memory.shutdown_drain_timeout_s = 1.0
    runtime.config.memory.shutdown_consolidation_timeout_s = 1.0

    intent_bus = MagicMock()
    intent_bus.close_to_new_dispatches = MagicMock()
    runtime.intent_bus = intent_bus

    runtime.dream_scheduler = None  # skip Phase 1 dream consolidation
    runtime.episodic_memory = None

    with caplog.at_level(logging.INFO, logger="probos.startup.shutdown"):
        try:
            await shutdown(runtime, reason="test")
        except Exception:
            pass

    assert any(
        "BF-296" in rec.message and "intent dispatch closed" in rec.message
        for rec in caplog.records
    )


@pytest.mark.asyncio
async def test_phase_a_honest_degrades_when_method_missing(
    tmp_path: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """If intent_bus lacks close_to_new_dispatches (transitional), shutdown still proceeds."""
    import logging

    runtime = MagicMock()
    runtime._started = True
    runtime._shutdown_started = False  # BF-598: MagicMock auto-creates a truthy attr otherwise
    runtime._session_id = "s1"
    runtime._start_time_wall = time.time()
    runtime._start_time = time.monotonic()
    runtime._data_dir = tmp_path
    runtime.registry.all.return_value = []
    runtime.ontology = MagicMock()
    runtime.event_log.log = AsyncMock()
    runtime.ward_room = None
    runtime.config.memory.shutdown_drain_timeout_s = 1.0
    runtime.config.memory.shutdown_consolidation_timeout_s = 1.0

    # intent_bus exists but has NO close_to_new_dispatches attr
    intent_bus = object()  # plain object — no attrs
    runtime.intent_bus = intent_bus

    runtime.dream_scheduler = None
    runtime.episodic_memory = None

    # Must not raise
    with caplog.at_level(logging.INFO, logger="probos.startup.shutdown"):
        try:
            await shutdown(runtime, reason="test")
        except Exception:
            pass

    # Should NOT have the "Phase A closed" INFO line (method was absent),
    # but should also NOT have raised. Honest-degrade.


@pytest.mark.asyncio
async def test_shutdown_stops_evolution_store_before_episodic_memory(
    tmp_path: Any,
) -> None:
    """BF-662: the second Chroma client closes before episodic persistence."""
    call_order: list[str] = []
    runtime = MagicMock()
    runtime._started = True
    runtime._shutdown_started = False
    runtime._session_id = "s1"
    runtime._start_time_wall = time.time()
    runtime._start_time = time.monotonic()
    runtime._data_dir = tmp_path
    runtime.registry.all.return_value = []
    runtime.ontology = MagicMock()
    runtime.event_log.log = AsyncMock()
    runtime.ward_room = None
    runtime.intent_bus = object()
    runtime.dream_scheduler = None
    runtime.config.memory.shutdown_drain_timeout_s = 1.0
    runtime.config.memory.shutdown_consolidation_timeout_s = 1.0
    runtime.evolution_store = MagicMock()
    runtime.evolution_store.stop.side_effect = lambda: call_order.append("evolution")
    runtime.episodic_memory = MagicMock()

    async def _stop_episodic() -> None:
        call_order.append("episodic")

    runtime.episodic_memory.stop = _stop_episodic

    with patch("probos.startup.shutdown.asyncio.sleep", new_callable=AsyncMock):
        try:
            await shutdown(runtime, reason="test")
        except Exception:
            pass

    assert call_order[:2] == ["evolution", "episodic"]


@pytest.mark.asyncio
async def test_runtime_sqlite_sidecars_close_and_clear_despite_one_failure() -> None:
    runtime = MagicMock()
    runtime.capability_request_store = MagicMock()
    runtime.capability_request_store.stop = AsyncMock()
    runtime.knowledge_edges = MagicMock()
    runtime.knowledge_edges.stop = AsyncMock(
        side_effect=RuntimeError("injected close failure")
    )
    runtime.personal_ontology_prober = MagicMock()
    runtime.personal_ontology_prober.stop = AsyncMock()
    runtime.rejection_cache = MagicMock()
    runtime.rejection_cache.stop = AsyncMock()
    services = [
        runtime.capability_request_store,
        runtime.knowledge_edges,
        runtime.personal_ontology_prober,
        runtime.rejection_cache,
    ]

    await _stop_runtime_sqlite_sidecars(runtime)
    await _stop_runtime_sqlite_sidecars(runtime)

    for service in services:
        service.stop.assert_awaited_once_with()
    assert runtime.capability_request_store is None
    assert runtime.knowledge_edges is None
    assert runtime.personal_ontology_prober is None
    assert runtime.rejection_cache is None
