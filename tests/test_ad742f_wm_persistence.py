"""AD-742f: SQLite persistence for VisionWorkingMemory ring buffers."""
from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path

import pytest

from probos.perception.consumer import (
    _WORKING_MEMORIES,
    get_or_create_working_memory,
    reset_working_memories_for_tests,
    set_working_memory_store,
)
from probos.perception.working_memory import VisionObservation, VisionWorkingMemory
from probos.perception.wm_store import WorkingMemoryStore


@pytest.fixture(autouse=True)
def _reset_module_state():
    reset_working_memories_for_tests()
    yield
    reset_working_memories_for_tests()


def _make_obs(*, ts: float = 0.0, desc: str = "a frame", ref: str = "deadbeef") -> VisionObservation:
    return VisionObservation(
        timestamp=ts,
        attachment_ref=ref,
        description=desc,
        novelty_score=0.5,
        subject_identity="captain",
        session_id="sess-1",
    )


def test_store_init_creates_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "wm.db"
    store = WorkingMemoryStore(db_path)
    assert store.available is True
    # Verify the table exists via PRAGMA table_info.
    with sqlite3.connect(db_path) as conn:
        cols = list(conn.execute("PRAGMA table_info(vision_observations)"))
    col_names = {row[1] for row in cols}
    assert {"agent_id", "timestamp", "attachment_ref", "description",
            "novelty_score", "subject_identity", "session_id"} <= col_names


def test_append_persists_and_loads(tmp_path: Path) -> None:
    store = WorkingMemoryStore(tmp_path / "wm.db")
    obs = _make_obs(ts=time.time(), desc="captain at desk")
    store.append("agent-x", obs, capacity=8)
    wm = VisionWorkingMemory(capacity=8, store=store, agent_id="agent-x")
    entries = wm.entries()
    assert len(entries) == 1
    assert entries[0].description == "captain at desk"
    assert entries[0].subject_identity == "captain"


def test_load_respects_capacity_cap(tmp_path: Path) -> None:
    store = WorkingMemoryStore(tmp_path / "wm.db")
    for i in range(12):
        store.append("agent-x", _make_obs(ts=float(i), desc=f"frame {i}"), capacity=64)
    rows = store.load_for_agent("agent-x", capacity=8)
    assert len(rows) == 8
    # Newest 8 by timestamp (4..11), loaded oldest-first -> newest-last.
    assert [r.description for r in rows] == [f"frame {i}" for i in range(4, 12)]


def test_append_evicts_oldest_beyond_capacity(tmp_path: Path) -> None:
    store = WorkingMemoryStore(tmp_path / "wm.db")
    wm = VisionWorkingMemory(capacity=8, store=store, agent_id="agent-y")
    for i in range(12):
        wm.append(_make_obs(ts=float(i), desc=f"frame {i}"))
    # Construct a fresh WM and verify only the newest 8 are persisted.
    wm2 = VisionWorkingMemory(capacity=8, store=store, agent_id="agent-y")
    entries = wm2.entries()
    assert len(entries) == 8
    assert [e.description for e in entries] == [f"frame {i}" for i in range(4, 12)]


def test_clear_for_agent_isolated(tmp_path: Path) -> None:
    store = WorkingMemoryStore(tmp_path / "wm.db")
    store.append("agent-a", _make_obs(ts=1.0, desc="a-frame"), capacity=8)
    store.append("agent-b", _make_obs(ts=2.0, desc="b-frame"), capacity=8)
    store.clear_for_agent("agent-a")
    assert store.load_for_agent("agent-a", capacity=8) == []
    rows_b = store.load_for_agent("agent-b", capacity=8)
    assert len(rows_b) == 1
    assert rows_b[0].description == "b-frame"


def test_unavailable_store_honest_degrade(tmp_path: Path, caplog) -> None:
    # Construct store at a path under a NON-DIRECTORY existing file -> mkdir fails.
    blocker = tmp_path / "block.txt"
    blocker.write_text("not a directory")
    bad_path = blocker / "sub" / "wm.db"
    with caplog.at_level(logging.WARNING):
        store = WorkingMemoryStore(bad_path)
    assert store.available is False
    # A WM with an unavailable store still functions as in-memory ring.
    wm = VisionWorkingMemory(capacity=4, store=store, agent_id="agent-x")
    obs = _make_obs(ts=1.0)
    wm.append(obs)
    assert len(wm.entries()) == 1


def test_wm_without_store_in_memory_only(tmp_path: Path) -> None:
    wm = VisionWorkingMemory(capacity=4, store=None, agent_id="")
    wm.append(_make_obs(ts=1.0))
    wm.append(_make_obs(ts=2.0))
    assert len(wm.entries()) == 2
    # No .db files created anywhere.
    assert not any(p.suffix == ".db" for p in tmp_path.iterdir())


def test_ad731_invariant_no_image_bytes(tmp_path: Path) -> None:
    """Schema must store text refs only — no BLOB columns for image bytes."""
    db_path = tmp_path / "wm.db"
    WorkingMemoryStore(db_path)
    with sqlite3.connect(db_path) as conn:
        cols = list(conn.execute("PRAGMA table_info(vision_observations)"))
    # Each row: (cid, name, type, notnull, dflt_value, pk)
    for _cid, name, col_type, *_ in cols:
        assert col_type.upper() != "BLOB", (
            f"AD-731 violation: column {name} is BLOB"
        )


def test_consumer_factory_threads_store(tmp_path: Path) -> None:
    store = WorkingMemoryStore(tmp_path / "wm.db")
    set_working_memory_store(store)
    wm = get_or_create_working_memory("agent-x", capacity=4)
    assert wm._store is store
    assert wm._agent_id == "agent-x"


def test_factory_reset_clears_store_handle(tmp_path: Path) -> None:
    store = WorkingMemoryStore(tmp_path / "wm.db")
    set_working_memory_store(store)
    # Touch one WM so the registry is populated.
    get_or_create_working_memory("agent-x", capacity=4)
    reset_working_memories_for_tests()
    assert _WORKING_MEMORIES == {}
    # Subsequent factory call builds WM with store=None.
    wm = get_or_create_working_memory("agent-y", capacity=4)
    assert wm._store is None
