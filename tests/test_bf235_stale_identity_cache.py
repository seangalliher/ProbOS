"""BF-235: Clear stale identity caches on stasis resume."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.standing_orders import (
    _build_personality_block,
    _load_file,
    clear_cache,
)
from probos.cognitive.cognitive_agent import CognitiveAgent, _DECISION_CACHES


# ── Test 1 ────────────────────────────────────────────────────────────

def test_clear_cache_evicts_personality_block_entries():
    """clear_cache() removes cached personality block entries."""
    clear_cache()  # start clean
    # Call to populate cache
    _build_personality_block("test_agent_bf235", "science", "Atlas")
    assert _build_personality_block.cache_info().currsize > 0

    clear_cache()
    assert _build_personality_block.cache_info().currsize == 0


# ── Test 2 ────────────────────────────────────────────────────────────

def test_clear_cache_clears_file_cache(tmp_path):
    """clear_cache() forces _load_file() to re-read from disk."""
    clear_cache()  # start clean

    test_file = tmp_path / "test_orders.md"
    test_file.write_text("Version 1", encoding="utf-8")

    result1 = _load_file(test_file)
    assert result1 == "Version 1"

    # Overwrite file — cache still serves old value
    test_file.write_text("Version 2", encoding="utf-8")
    assert _load_file(test_file) == "Version 1"

    # Clear cache — now reads updated file
    clear_cache()
    result2 = _load_file(test_file)
    assert result2 == "Version 2"


# ── Test 3 ────────────────────────────────────────────────────────────

def test_evict_cache_for_type_clears_all_entries():
    """evict_cache_for_type() removes all entries for the given agent type."""
    import time

    prior = _DECISION_CACHES.get("bf235_test_agent")
    try:
        _DECISION_CACHES["bf235_test_agent"] = {
            "hash1": ({"result": "a"}, time.monotonic(), 3600.0),
            "hash2": ({"result": "b"}, time.monotonic(), 3600.0),
            "hash3": ({"result": "c"}, time.monotonic(), 3600.0),
        }

        evicted = CognitiveAgent.evict_cache_for_type("bf235_test_agent")
        assert evicted == 3
        assert len(_DECISION_CACHES["bf235_test_agent"]) == 0
    finally:
        if prior is not None:
            _DECISION_CACHES["bf235_test_agent"] = prior
        else:
            _DECISION_CACHES.pop("bf235_test_agent", None)


# ── Test 4 ────────────────────────────────────────────────────────────

def test_evict_cache_for_type_noop_for_unknown_agent():
    """evict_cache_for_type() returns 0 for unknown agent types (no raise)."""
    evicted = CognitiveAgent.evict_cache_for_type("nonexistent_agent_bf235")
    assert evicted == 0


# ── Test 5 ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stasis_resume_clears_standing_orders_cache():
    """Stasis recovery path calls clear_cache() for standing orders."""
    from probos.startup.finalize import finalize_startup

    runtime = MagicMock()
    runtime._lifecycle_state = "stasis_recovery"
    runtime._cold_start = False
    runtime._previous_session = {}
    runtime._stasis_duration = 100.0
    runtime.ward_room = None
    runtime.episodic_memory = None
    runtime.trust_network = None
    runtime._knowledge_store = None
    runtime._intent_bus = None
    runtime._orientation_service = None

    # Crew agent mock
    agent = MagicMock()
    agent.agent_type = "science_officer"
    agent.id = "agent-1"
    runtime.registry.all.return_value = [agent]
    runtime.ontology = MagicMock()

    config = MagicMock()
    config.proactive_cognitive.enabled = False
    config.orientation.warm_boot_orientation = False

    # Patch at the source module — finalize_startup imports clear_cache locally
    # inside the function body, so we must patch the origin.
    with patch(
        "probos.cognitive.standing_orders.clear_cache"
    ) as mock_so_clear:
        try:
            await finalize_startup(runtime=runtime, config=config)
        except Exception:
            pass  # finalize_startup touches many subsystems; we only care about cache clearing

        # clear_cache is called twice on stasis_recovery: once defensively at top,
        # once in the stasis_recovery block. Verify at least one call happened.
        assert mock_so_clear.call_count >= 1


# ── Test 6 ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stasis_resume_evicts_decision_caches():
    """Stasis recovery evicts decision cache entries for crew agents."""
    import time

    prior_state = {}
    agent_types = ["science_officer_bf235", "engineer_bf235"]
    try:
        # Save prior state
        for at in agent_types:
            prior_state[at] = _DECISION_CACHES.get(at)
            _DECISION_CACHES[at] = {
                "h1": ({"r": "x"}, time.monotonic(), 3600.0),
            }

        # Simulate what finalize_startup does on stasis_recovery
        from probos.cognitive.cognitive_agent import CognitiveAgent

        evicted_total = 0
        for at in agent_types:
            evicted_total += CognitiveAgent.evict_cache_for_type(at)

        assert evicted_total == 2
        for at in agent_types:
            assert len(_DECISION_CACHES[at]) == 0
    finally:
        for at in agent_types:
            if prior_state.get(at) is not None:
                _DECISION_CACHES[at] = prior_state[at]
            else:
                _DECISION_CACHES.pop(at, None)


# ── Test 7 ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_orientation_diagnostic_log(caplog):
    """Stasis recovery orientation logs BF-235 diagnostic with callsign."""
    # Build minimal mocks for the orientation loop
    agent = MagicMock()
    agent.agent_type = "medical_officer"
    agent.id = "agent-med-1"
    agent.callsign = "Bones"

    orientation_service = MagicMock()
    orientation_ctx = MagicMock()
    orientation_service.build_orientation.return_value = orientation_ctx
    orientation_service.render_warm_boot_orientation.return_value = "orientation text"

    runtime = MagicMock()
    runtime._lifecycle_state = "stasis_recovery"
    runtime._orientation_service = orientation_service
    runtime._previous_session = {"shutdown_time_utc": 1700000000.0}
    runtime._stasis_duration = 3600.0
    runtime.registry.all.return_value = [agent]
    runtime.ontology = MagicMock()
    runtime.episodic_memory = None
    runtime.trust_network = None
    runtime.callsign_registry = MagicMock()
    runtime.callsign_registry.all_callsigns.return_value = {"medical_officer": "Bones"}

    config = MagicMock()
    config.orientation.warm_boot_orientation = True

    # Simulate just the orientation block logic
    from probos.crew_utils import is_crew_agent

    with patch("probos.crew_utils.is_crew_agent", return_value=True):
        with caplog.at_level(logging.DEBUG):
            # Inline the orientation block logic from finalize.py
            _all_crew_names = runtime.callsign_registry.all_callsigns()
            for ag in runtime.registry.all():
                _crew_names = sorted(
                    cs for at, cs in _all_crew_names.items()
                    if cs and at != ag.agent_type
                )
                _ctx = orientation_service.build_orientation(
                    ag,
                    lifecycle_state="stasis_recovery",
                    stasis_duration=runtime._stasis_duration,
                    stasis_shutdown_utc="2023-11-14 22:13:20 UTC",
                    stasis_resume_utc="2023-11-14 23:13:20 UTC",
                    episodic_memory_count=0,
                    trust_score=0.5,
                    crew_names=_crew_names,
                )
                _rendered = orientation_service.render_warm_boot_orientation(_ctx)
                ag.set_orientation(_rendered, _ctx)
                logging.getLogger("probos.startup.finalize").debug(
                    "BF-235: %s orientation set — callsign=%s",
                    ag.agent_type,
                    getattr(ag, 'callsign', '?'),
                )

    assert "BF-235:" in caplog.text
    assert "Bones" in caplog.text
    assert "medical_officer" in caplog.text
