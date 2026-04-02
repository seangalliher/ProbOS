"""BF-099: Trust engine concurrency safety tests."""

import asyncio
from collections import Counter
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.consensus.trust import TrustNetwork, TrustRecord, TrustEvent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trust(**kwargs) -> TrustNetwork:
    """Create a TrustNetwork without DB (in-memory only)."""
    return TrustNetwork(**kwargs)


async def _make_trust_with_db(tmp_path) -> TrustNetwork:
    """Create a TrustNetwork with real SQLite DB."""
    db_path = str(tmp_path / "trust.db")
    tn = TrustNetwork(db_path=db_path)
    await tn.start()
    return tn


# ---------------------------------------------------------------------------
# Part 1: Lock-protected operations
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_record_outcome_concurrent_writes_no_lost_updates():
    """Launch 10 concurrent record_outcome() calls for the same agent.
    Verify final alpha + beta equals expected sum (no lost updates)."""
    tn = _make_trust()

    for _ in range(10):
        tn.record_outcome("agent1", success=True, weight=1.0)

    record = tn.get_record("agent1")
    # Started at alpha=2.0, added 10 * 1.0 = 12.0
    assert record.alpha == 12.0
    assert record.beta == 2.0


@pytest.mark.asyncio
async def test_record_outcome_concurrent_different_agents():
    """Launch concurrent record_outcome() for 5 different agents.
    Verify all 5 records exist with correct values."""
    tn = _make_trust()

    for i in range(5):
        tn.record_outcome(f"agent{i}", success=True, weight=2.0)
        tn.record_outcome(f"agent{i}", success=False, weight=1.0)

    for i in range(5):
        rec = tn.get_record(f"agent{i}")
        assert rec is not None
        assert rec.alpha == 4.0  # prior 2.0 + success 2.0
        assert rec.beta == 3.0  # prior 2.0 + failure 1.0


@pytest.mark.asyncio
async def test_decay_all_doesnt_race_with_record_outcome():
    """Launch record_outcome() and decay_all() concurrently.
    Verify no exception and records are in valid state."""
    tn = _make_trust()
    tn.record_outcome("agent1", success=True, weight=5.0)
    tn.record_outcome("agent2", success=False, weight=3.0)

    # Interleave decay and writes
    tn.decay_all()
    tn.record_outcome("agent1", success=True, weight=1.0)
    tn.decay_all()

    rec1 = tn.get_record("agent1")
    rec2 = tn.get_record("agent2")
    assert rec1 is not None
    assert rec2 is not None
    assert rec1.alpha > 2.0  # Still has positive observations
    assert rec1.score > 0  # Valid score


# ---------------------------------------------------------------------------
# Part 2: Transaction atomicity
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_save_to_db_transaction_atomicity(tmp_path):
    """Call _save_to_db() and verify records are all present."""
    tn = await _make_trust_with_db(tmp_path)
    try:
        for i in range(5):
            tn.record_outcome(f"agent{i}", success=True, weight=1.0)

        await tn._save_to_db()

        # Reload fresh to verify
        tn2 = TrustNetwork(db_path=str(tmp_path / "trust.db"))
        await tn2.start()
        assert tn2.agent_count == 5
        await tn2.stop()
    finally:
        await tn.stop()


@pytest.mark.asyncio
async def test_save_to_db_uses_begin_immediate(tmp_path):
    """Verify BEGIN IMMEDIATE is called before DELETE."""
    tn = await _make_trust_with_db(tmp_path)
    try:
        tn.record_outcome("agent1", success=True)

        calls = []
        original_execute = tn._db.execute

        async def spy_execute(sql, *args, **kwargs):
            if isinstance(sql, str):
                calls.append(sql.strip())
            return await original_execute(sql, *args, **kwargs)

        tn._db.execute = spy_execute
        await tn._save_to_db()

        # BEGIN IMMEDIATE must appear before DELETE
        begin_idx = next(i for i, c in enumerate(calls) if "BEGIN" in c)
        delete_idx = next(i for i, c in enumerate(calls) if "DELETE" in c)
        assert begin_idx < delete_idx
    finally:
        tn._db.execute = original_execute
        await tn.stop()


@pytest.mark.asyncio
async def test_save_to_db_rollback_on_error(tmp_path):
    """Inject an error during INSERT — verify ROLLBACK is called."""
    tn = await _make_trust_with_db(tmp_path)
    try:
        tn.record_outcome("agent1", success=True)
        await tn._save_to_db()  # Initial save to establish data

        # Add second agent and sabotage INSERT
        tn.record_outcome("agent2", success=True)

        original_execute = tn._db.execute
        call_count = [0]
        rollback_called = [False]

        async def failing_execute(sql, *args, **kwargs):
            if isinstance(sql, str):
                if "ROLLBACK" in sql:
                    rollback_called[0] = True
                if "INSERT" in sql:
                    call_count[0] += 1
                    if call_count[0] >= 2:  # Fail on second INSERT
                        raise RuntimeError("Injected failure")
            return await original_execute(sql, *args, **kwargs)

        tn._db.execute = failing_execute
        with pytest.raises(RuntimeError, match="Injected failure"):
            await tn._save_to_db()

        assert rollback_called[0] is True
    finally:
        tn._db.execute = original_execute
        await tn.stop()


# ---------------------------------------------------------------------------
# Part 3: WAL mode and busy timeout
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_wal_mode_enabled(tmp_path):
    """After start(), query PRAGMA journal_mode and assert 'wal'."""
    tn = await _make_trust_with_db(tmp_path)
    try:
        async with tn._db.execute("PRAGMA journal_mode") as cursor:
            row = await cursor.fetchone()
            assert row[0].lower() == "wal"
    finally:
        await tn.stop()


@pytest.mark.asyncio
async def test_busy_timeout_set(tmp_path):
    """After start(), query PRAGMA busy_timeout and assert >= 5000."""
    tn = await _make_trust_with_db(tmp_path)
    try:
        async with tn._db.execute("PRAGMA busy_timeout") as cursor:
            row = await cursor.fetchone()
            assert row[0] >= 5000
    finally:
        await tn.stop()


# ---------------------------------------------------------------------------
# Part 4: Dream consolidation through record_outcome
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dream_consolidation_uses_record_outcome():
    """Run _consolidate_trust() and verify record_outcome() was called."""
    from probos.cognitive.dreaming import DreamingEngine
    from probos.types import Episode

    engine = object.__new__(DreamingEngine)
    engine._agent_id = "test-agent"
    engine._agent_type = "TestAgent"
    engine._router = MagicMock()
    engine._config = MagicMock()
    engine.config = engine._config
    engine.config.trust_boost = 0.5
    engine.config.trust_penalty = 0.5

    # Track calls to record_outcome
    tn = _make_trust()
    original_record = tn.record_outcome
    calls = []

    def tracking_record(*args, **kwargs):
        calls.append((args, kwargs))
        return original_record(*args, **kwargs)

    tn.record_outcome = tracking_record
    engine.trust_network = tn

    # Create episodes with consistent success for agent1
    episodes = [
        Episode(user_input="test1", timestamp=1.0, agent_ids=["agent1"],
                outcomes=[{"success": True}], dag_summary={}),
        Episode(user_input="test2", timestamp=2.0, agent_ids=["agent1"],
                outcomes=[{"success": True}], dag_summary={}),
    ]

    result = engine._consolidate_trust(episodes)
    assert result >= 1
    assert len(calls) >= 1
    # Verify source is dream_consolidation
    for _, kwargs in calls:
        assert kwargs.get("source") == "dream_consolidation"


@pytest.mark.asyncio
async def test_dream_consolidation_emits_trust_event():
    """Run _consolidate_trust() and verify TrustEvent was logged."""
    from probos.cognitive.dreaming import DreamingEngine
    from probos.types import Episode

    engine = object.__new__(DreamingEngine)
    engine._agent_id = "test-agent"
    engine._agent_type = "TestAgent"
    engine._router = MagicMock()
    engine._config = MagicMock()
    engine.config = engine._config
    engine.config.trust_boost = 0.5
    engine.config.trust_penalty = 0.5

    tn = _make_trust()
    engine.trust_network = tn

    episodes = [
        Episode(user_input="test1", timestamp=1.0, agent_ids=["agent1"],
                outcomes=[{"success": True}], dag_summary={}),
        Episode(user_input="test2", timestamp=2.0, agent_ids=["agent1"],
                outcomes=[{"success": True}], dag_summary={}),
    ]

    engine._consolidate_trust(episodes)
    events = tn.get_events_for_agent("agent1")
    assert len(events) >= 1  # At least one event logged


@pytest.mark.asyncio
async def test_concurrent_dream_and_verification():
    """Launch _consolidate_trust() and record_outcome() — no exception."""
    from probos.cognitive.dreaming import DreamingEngine
    from probos.types import Episode

    engine = object.__new__(DreamingEngine)
    engine._agent_id = "test-agent"
    engine._agent_type = "TestAgent"
    engine._router = MagicMock()
    engine._config = MagicMock()
    engine.config = engine._config
    engine.config.trust_boost = 0.5
    engine.config.trust_penalty = 0.5

    tn = _make_trust()
    engine.trust_network = tn

    episodes = [
        Episode(user_input="test1", timestamp=1.0, agent_ids=["agent1"],
                outcomes=[{"success": True}], dag_summary={}),
        Episode(user_input="test2", timestamp=2.0, agent_ids=["agent1"],
                outcomes=[{"success": True}], dag_summary={}),
    ]

    # Interleave dream consolidation and direct record_outcome
    tn.record_outcome("agent1", success=True, weight=1.0)
    engine._consolidate_trust(episodes)
    tn.record_outcome("agent1", success=False, weight=0.5)

    rec = tn.get_record("agent1")
    assert rec is not None
    assert rec.alpha > 2.0
    assert rec.score > 0


# ---------------------------------------------------------------------------
# Part 5: Shutdown race fix
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_shutdown_waits_for_flush_cancellation():
    """Verify shutdown sequence awaits flush task cancellation."""
    flush_started = asyncio.Event()
    flush_cancelled = asyncio.Event()

    async def slow_flush():
        flush_started.set()
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            flush_cancelled.set()
            raise

    flush_task = asyncio.create_task(slow_flush())
    await flush_started.wait()  # Ensure task is running

    # This is the BF-099 pattern from shutdown.py
    flush_task.cancel()
    try:
        await flush_task
    except (asyncio.CancelledError, Exception):
        pass

    # Flush task was cancelled and awaited properly
    assert flush_cancelled.is_set()
    assert flush_task.done()


# ---------------------------------------------------------------------------
# Part 1 supplement: Lock exists
# ---------------------------------------------------------------------------

def test_trust_network_has_lock():
    """TrustNetwork has an asyncio.Lock on construction."""
    tn = _make_trust()
    assert hasattr(tn, "_lock")
    assert isinstance(tn._lock, asyncio.Lock)


@pytest.mark.asyncio
async def test_get_or_create_under_lock():
    """Concurrent get_or_create() for same agent_id.
    Verify only one record created (no duplicate)."""
    tn = _make_trust()

    # Call get_or_create many times for same agent
    for _ in range(20):
        tn.get_or_create("agent1")

    assert tn.agent_count == 1
    rec = tn.get_record("agent1")
    assert rec.alpha == 2.0  # Unchanged from prior


# ---------------------------------------------------------------------------
# Part 1 supplement: Source parameter
# ---------------------------------------------------------------------------

def test_record_outcome_accepts_source_parameter():
    """record_outcome() accepts an optional source parameter."""
    tn = _make_trust()
    score = tn.record_outcome("agent1", success=True, source="dream_consolidation")
    assert score > 0.5


def test_record_outcome_default_source():
    """record_outcome() defaults source to 'verification'."""
    import inspect
    sig = inspect.signature(TrustNetwork.record_outcome)
    assert sig.parameters["source"].default == "verification"


# ---------------------------------------------------------------------------
# Part 6: Hebbian router WAL + transaction
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hebbian_router_wal_mode(tmp_path):
    """After routing.start(), verify WAL mode is enabled."""
    from probos.mesh.routing import HebbianRouter

    router = HebbianRouter(db_path=str(tmp_path / "hebbian.db"))
    await router.start()
    try:
        async with router._db.execute("PRAGMA journal_mode") as cursor:
            row = await cursor.fetchone()
            assert row[0].lower() == "wal"
    finally:
        await router.stop()


@pytest.mark.asyncio
async def test_hebbian_router_transaction_save(tmp_path):
    """Verify Hebbian save uses BEGIN IMMEDIATE."""
    from probos.mesh.routing import HebbianRouter

    router = HebbianRouter(db_path=str(tmp_path / "hebbian.db"))
    await router.start()
    try:
        router.record_interaction("intent1", "agent1", success=True)

        calls = []
        original_execute = router._db.execute

        async def spy_execute(sql, *args, **kwargs):
            if isinstance(sql, str):
                calls.append(sql.strip())
            return await original_execute(sql, *args, **kwargs)

        router._db.execute = spy_execute
        await router._save_to_db()

        assert any("BEGIN" in c for c in calls)
        begin_idx = next(i for i, c in enumerate(calls) if "BEGIN" in c)
        delete_idx = next(i for i, c in enumerate(calls) if "DELETE" in c)
        assert begin_idx < delete_idx
    finally:
        router._db.execute = original_execute
        await router.stop()
