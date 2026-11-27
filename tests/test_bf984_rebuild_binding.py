"""BF-984 (#1830) G1: ``probos rebuild-episodic`` binds its memory's gates through the helper startup uses.

Before BF-984 the rebuild command built its own EpisodicMemory and called no setter, while its comment said the gates
fire. ``bind_episodic_memory_gates`` is now shared with ``init_cognitive_services``. These tests run a real
EpisodicMemory under tmp_path over a real ward_room.db (tests/test_ad819_rebuild_episodic.py's fixture plus one post
that matches an AD-607h injection pattern), and the real command; the AST guard fails on any production construction
of EpisodicMemory that is not bound. Names the change adds are imported inside the tests, so the file collects on the
base.
"""

from __future__ import annotations

import argparse
import asyncio
import sqlite3
from pathlib import Path

import pytest

import probos.__main__ as cli
from probos.cognitive.episodic import EpisodicMemory
from probos.cognitive.memory_security import MemorySecurityGate
from probos.cognitive.storage_gate import StorageGate
from probos.config import SystemConfig
from probos.events import EventType
from probos.maintenance.rebuild_episodic import _stable_episode_id, rebuild_from_wardroom
from probos.types import Episode
from tests import test_bf938_ad607_binding as binding
from tests.test_ad819_rebuild_episodic import _build_wardroom_fixture
from tests.test_bf984_recall_gate_coverage import calls_named

_CLEAN_ID = _stable_episode_id(source="wardroom_rebuild_post", source_id="p1")
_INJECTED_ID = _stable_episode_id(source="wardroom_rebuild_post", source_id="p9")
# The constructions startup binds, with the reason. Every other construction calls the helper in the same function.
_BOUND_BY_STARTUP: dict[tuple[str, str], str] = {
    ("__main__.py", "_boot_runtime"): "the runtime's memory: init_cognitive_services binds it through "
    "bind_episodic_memory_gates (tests/test_bf938_ad607_binding.py)",
}


def _wardroom(root: Path) -> Path:
    """test_ad819's ward room, plus post p9, whose body matches an AD-607h injection pattern."""
    db = root / "ward_room.db"
    _build_wardroom_fixture(db)
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "INSERT INTO posts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            ("p9", "t1", None, "agent-E", binding._INJECTED, 1030.0, None, 0, "", "", 0, "Crusher"),
        )
        conn.commit()
    finally:
        conn.close()
    return db


def _config(*, armed: bool, storage_gate: bool = False) -> SystemConfig:
    config = SystemConfig()
    config.storage_gate.enabled = storage_gate  # AD-610's utility gate is under test only in B2; AD-607h runs after it
    config.security.memory.enforce_store = armed
    return config


async def _persisted(db_path: Path, ids: list[str]) -> list[str]:
    em = EpisodicMemory(db_path=str(db_path), relevance_threshold=0.0)
    await em.start()
    try:
        return sorted(em._collection.get(ids=ids)["ids"])
    finally:
        await em.stop()


def test_every_production_episodic_memory_is_bound() -> None:
    constructions = calls_named("EpisodicMemory")
    binders = calls_named("bind_episodic_memory_gates")
    assert ("__main__.py", "_boot_runtime") in constructions  # control: the runtime's construction is found
    assert len(constructions) >= 2  # control: and the rebuild command's
    assert sorted(site for site in constructions if site not in binders and site not in _BOUND_BY_STARTUP) == []
    assert ("startup/cognitive_services.py", "init_cognitive_services") in binders
    assert set(_BOUND_BY_STARTUP) <= constructions  # no stale entry


@pytest.mark.parametrize("enabled", [False, True], ids=["off", "on"])
def test_the_shared_binding_binds_the_storage_gate_only_when_enabled(tmp_path: Path, enabled: bool) -> None:
    from probos.startup.cognitive_services import bind_episodic_memory_gates

    config = _config(armed=False, storage_gate=enabled)
    emit = binding._Recorder()
    em = EpisodicMemory(db_path=str(tmp_path / "episodic.db"))  # never started: binding needs no open store
    bind_episodic_memory_gates(em, config, emit)
    assert isinstance(em._storage_gate, StorageGate) is enabled
    assert em._security_config is config.security.memory
    assert isinstance(em._security_gate, MemorySecurityGate)
    assert em._security_event_emitter is emit


@pytest.mark.parametrize("armed", [False, True], ids=["off", "on"])
async def test_the_shared_binding_gates_a_rebuilt_episode(tmp_path: Path, armed: bool) -> None:
    from probos.startup.cognitive_services import bind_episodic_memory_gates

    db = _wardroom(tmp_path)
    recorder = binding._Recorder()
    em = EpisodicMemory(db_path=str(tmp_path / "episodic.db"), relevance_threshold=0.0)
    await em.start()
    try:
        bind_episodic_memory_gates(em, _config(armed=armed), recorder)

        async def _store(kwargs: dict) -> None:
            await em.store(Episode(**kwargs))

        report = await rebuild_from_wardroom(wardroom_db=db, store_episode=_store)
        assert report.errors == []  # premise: every row reached store()
        persisted = sorted(em._collection.get(ids=[_CLEAN_ID, _INJECTED_ID])["ids"])
    finally:
        await em.stop()
    assert persisted == sorted([_CLEAN_ID] if armed else [_CLEAN_ID, _INJECTED_ID])
    assert recorder.ids(EventType.MEMORY_INJECTION_SUSPECTED) == [_INJECTED_ID]


def test_rebuild_episodic_stores_through_the_bound_gates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _wardroom(data_dir)
    recorder = binding._Recorder()
    monkeypatch.setattr(cli, "_load_config_with_fallback", lambda _path: (_config(armed=True), None))
    monkeypatch.setattr(cli, "_log_rebuild_memory_event", recorder, raising=False)  # absent on the base
    args = argparse.Namespace(data_dir=data_dir, config=None, since=None, dry_run=False)
    assert cli._cmd_rebuild_episodic(args) == 0
    assert asyncio.run(_persisted(data_dir / "episodic.db", [_CLEAN_ID, _INJECTED_ID])) == [_CLEAN_ID]
    assert recorder.ids(EventType.MEMORY_INJECTION_SUSPECTED) == [_INJECTED_ID]
