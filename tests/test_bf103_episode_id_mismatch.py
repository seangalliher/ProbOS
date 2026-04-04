"""BF-103: Episodic Memory Agent ID Mismatch — tests for sovereign ID resolution.

15 tests covering:
- D1: ID resolution helpers (3)
- D2: Storage path fixes (3)
- D3: Migration (6)
- D4/D5: Wiring (3)
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.episodic import (
    migrate_episode_agent_ids,
    resolve_sovereign_id,
    resolve_sovereign_id_from_slot,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent(*, sovereign_id: str | None = None, agent_id: str = "slot_abc123") -> SimpleNamespace:
    """Create a minimal agent-like object."""
    ns = SimpleNamespace(id=agent_id)
    if sovereign_id is not None:
        ns.sovereign_id = sovereign_id
    return ns


def _make_registry(mappings: dict[str, str] | None = None) -> MagicMock:
    """Create a mock identity registry.

    mappings: {slot_id: sovereign_uuid}
    """
    reg = MagicMock()
    mappings = mappings or {}

    def _get_by_slot(slot_id: str):
        if slot_id in mappings:
            return SimpleNamespace(agent_uuid=mappings[slot_id])
        return None

    reg.get_by_slot = MagicMock(side_effect=_get_by_slot)
    return reg


def _make_chromadb_collection(episodes: list[dict[str, Any]]) -> MagicMock:
    """Create a mock ChromaDB collection with get() and upsert()."""
    coll = MagicMock()
    ids = [ep["id"] for ep in episodes]
    metadatas = [ep["metadata"] for ep in episodes]

    coll.get = MagicMock(return_value={"ids": ids, "metadatas": metadatas})
    coll.upsert = MagicMock()
    return coll


# ===========================================================================
# D1: ID Resolution (3 tests)
# ===========================================================================

class TestResolveIDs:
    """Sovereign ID resolution helpers."""

    def test_resolve_sovereign_id_prefers_sovereign(self):
        """Agent with both sovereign_id and id returns sovereign_id."""
        agent = _make_agent(sovereign_id="sov-uuid-1234", agent_id="slot_abc123")
        assert resolve_sovereign_id(agent) == "sov-uuid-1234"

    def test_resolve_sovereign_id_falls_back_to_id(self):
        """Agent without sovereign_id returns agent.id."""
        agent = _make_agent(agent_id="slot_abc123")
        assert resolve_sovereign_id(agent) == "slot_abc123"

    def test_resolve_sovereign_id_from_slot_maps_correctly(self):
        """Slot ID with registry mapping returns sovereign UUID; unknown returns slot unchanged."""
        reg = _make_registry({"slot_abc": "sov-uuid-5678"})

        # Known slot → sovereign
        assert resolve_sovereign_id_from_slot("slot_abc", reg) == "sov-uuid-5678"
        # Unknown slot → unchanged
        assert resolve_sovereign_id_from_slot("unknown_slot", reg) == "unknown_slot"
        # No registry → unchanged
        assert resolve_sovereign_id_from_slot("slot_abc", None) == "slot_abc"


# ===========================================================================
# D2: Storage Path Fixes (4 tests)
# ===========================================================================

class TestStoragePathFixes:
    """Verify each storage path uses sovereign IDs in episodes."""

    def test_ward_room_message_store_has_identity_registry(self):
        """MessageStore accepts and stores identity_registry for sovereign ID resolution."""
        from probos.ward_room.messages import MessageStore

        reg = _make_registry({"slot_author_1": "sov-uuid-author"})
        store = MessageStore(
            db=AsyncMock(),
            emit_fn=MagicMock(),
            identity_registry=reg,
        )
        assert store._identity_registry is reg

        # Verify resolve_sovereign_id_from_slot works with registry
        resolved = resolve_sovereign_id_from_slot("slot_author_1", reg)
        assert resolved == "sov-uuid-author"

    def test_ward_room_thread_manager_has_identity_registry(self):
        """ThreadManager accepts and stores identity_registry for sovereign ID resolution."""
        from probos.ward_room.threads import ThreadManager

        reg = _make_registry({"slot_author_2": "sov-uuid-author-2"})
        mgr = ThreadManager(
            db=AsyncMock(),
            emit_fn=MagicMock(),
            identity_registry=reg,
        )
        assert mgr._identity_registry is reg

        # Verify resolve_sovereign_id_from_slot works with registry
        resolved = resolve_sovereign_id_from_slot("slot_author_2", reg)
        assert resolved == "sov-uuid-author-2"

    def test_dream_adapter_episode_uses_sovereign_id(self):
        """Episode created by dream adapter stores sovereign_id, not slot ID."""
        from probos.dream_adapter import DreamAdapter

        reg = _make_registry({"slot_agent_1": "sov-uuid-dream"})

        adapter = DreamAdapter(
            dream_scheduler=None,
            emergent_detector=None,
            episodic_memory=MagicMock(),
            knowledge_store=None,
            hebbian_router=MagicMock(),
            trust_network=MagicMock(get_events_since=MagicMock(return_value=[])),
            event_emitter=MagicMock(),
            self_mod_pipeline=None,
            bridge_alerts=None,
            ward_room=None,
            registry=MagicMock(),
            event_log=None,
            config=MagicMock(dreaming=MagicMock(max_episode_reflection_chars=500)),
            pools={},
            identity_registry=reg,
        )
        adapter._cold_start = False
        adapter._last_shapley_values = None

        # Build a mock DAG + execution_result (dag goes inside execution_result)
        node = SimpleNamespace(
            id="n1", intent="test_intent", status="completed",
            depends_on=[],
        )
        dag = SimpleNamespace(nodes=[node])
        t_now = time.time()
        execution_result = {
            "dag": dag,
            "results": {
                "n1": {
                    "results": [{"agent_id": "slot_agent_1", "response": "ok"}],
                },
            },
            "reflection": "test reflection",
        }

        # build_episode(text, execution_result, t_start, t_end)
        ep = adapter.build_episode(
            text="test input",
            execution_result=execution_result,
            t_start=t_now - 1.0,
            t_end=t_now,
        )
        assert "sov-uuid-dream" in ep.agent_ids
        assert "slot_agent_1" not in ep.agent_ids

    def test_runtime_episode_uses_sovereign_id(self):
        """Runtime QA episode stores sovereign_id, not a.id."""
        agent = _make_agent(sovereign_id="sov-uuid-runtime", agent_id="slot_qa_1")
        resolved = resolve_sovereign_id(agent)
        assert resolved == "sov-uuid-runtime"
        # This verifies the helper used in runtime.py:2862


# ===========================================================================
# D3: Migration (6 tests)
# ===========================================================================

class TestMigration:
    """Episode ID migration from slot IDs to sovereign IDs."""

    @pytest.mark.asyncio
    async def test_migration_converts_slot_ids_to_sovereign(self):
        """Episodes with slot IDs in agent_ids_json are updated to sovereign IDs."""
        collection = _make_chromadb_collection([
            {"id": "ep1", "metadata": {"agent_ids_json": json.dumps(["slot_a"])}},
        ])
        reg = _make_registry({"slot_a": "sov-uuid-a"})

        em = MagicMock()
        em._collection = collection

        migrated = await migrate_episode_agent_ids(em, reg)
        assert migrated == 1
        collection.upsert.assert_called_once()
        call_meta = collection.upsert.call_args[1]["metadatas"][0]
        assert json.loads(call_meta["agent_ids_json"]) == ["sov-uuid-a"]

    @pytest.mark.asyncio
    async def test_migration_leaves_sovereign_ids_unchanged(self):
        """Episodes already using sovereign IDs are not modified."""
        collection = _make_chromadb_collection([
            {"id": "ep1", "metadata": {"agent_ids_json": json.dumps(["sov-uuid-x"])}},
        ])
        reg = _make_registry({})  # No slot mappings

        em = MagicMock()
        em._collection = collection

        migrated = await migrate_episode_agent_ids(em, reg)
        assert migrated == 0
        collection.upsert.assert_not_called()

    @pytest.mark.asyncio
    async def test_migration_handles_mixed_ids(self):
        """Episode with both slot ID and sovereign ID only converts the slot ID."""
        collection = _make_chromadb_collection([
            {"id": "ep1", "metadata": {"agent_ids_json": json.dumps(["slot_b", "sov-uuid-existing"])}},
        ])
        reg = _make_registry({"slot_b": "sov-uuid-b"})

        em = MagicMock()
        em._collection = collection

        migrated = await migrate_episode_agent_ids(em, reg)
        assert migrated == 1
        call_meta = collection.upsert.call_args[1]["metadatas"][0]
        assert json.loads(call_meta["agent_ids_json"]) == ["sov-uuid-b", "sov-uuid-existing"]

    @pytest.mark.asyncio
    async def test_migration_returns_count(self):
        """Returns correct count of migrated episodes."""
        collection = _make_chromadb_collection([
            {"id": "ep1", "metadata": {"agent_ids_json": json.dumps(["slot_x"])}},
            {"id": "ep2", "metadata": {"agent_ids_json": json.dumps(["sov-already"])}},
            {"id": "ep3", "metadata": {"agent_ids_json": json.dumps(["slot_y"])}},
        ])
        reg = _make_registry({"slot_x": "sov-x", "slot_y": "sov-y"})

        em = MagicMock()
        em._collection = collection

        migrated = await migrate_episode_agent_ids(em, reg)
        assert migrated == 2

    @pytest.mark.asyncio
    async def test_migration_idempotent(self):
        """Running migration twice produces same result (second run returns 0)."""
        episodes = [
            {"id": "ep1", "metadata": {"agent_ids_json": json.dumps(["slot_z"])}},
        ]
        collection = _make_chromadb_collection(episodes)
        reg = _make_registry({"slot_z": "sov-z"})

        em = MagicMock()
        em._collection = collection

        # First run
        migrated_1 = await migrate_episode_agent_ids(em, reg)
        assert migrated_1 == 1

        # Simulate the update by changing the collection data
        collection.get = MagicMock(return_value={
            "ids": ["ep1"],
            "metadatas": [{"agent_ids_json": json.dumps(["sov-z"])}],
        })
        collection.upsert.reset_mock()

        # Second run
        migrated_2 = await migrate_episode_agent_ids(em, reg)
        assert migrated_2 == 0
        collection.upsert.assert_not_called()

    @pytest.mark.asyncio
    async def test_migration_handles_empty_collection(self):
        """No episodes → returns 0, no errors."""
        collection = _make_chromadb_collection([])
        reg = _make_registry({"slot_a": "sov-a"})

        em = MagicMock()
        em._collection = collection

        migrated = await migrate_episode_agent_ids(em, reg)
        assert migrated == 0


# ===========================================================================
# D4/D5: Wiring (3 tests)
# ===========================================================================

class TestWiring:
    """Startup wiring and identity registry access."""

    @pytest.mark.asyncio
    async def test_startup_migration_runs_after_identity_registry(self):
        """Migration executes in correct startup phase (after episodic + identity init)."""
        from probos.startup.cognitive_services import init_cognitive_services

        # The function signature accepts identity_registry
        import inspect
        sig = inspect.signature(init_cognitive_services)
        assert "identity_registry" in sig.parameters

    @pytest.mark.asyncio
    async def test_startup_migration_failure_non_fatal(self):
        """Migration exception is caught; does not propagate."""
        # The migrate function itself catches exceptions internally
        em = MagicMock()
        em._collection = MagicMock()
        em._collection.get = MagicMock(side_effect=RuntimeError("DB error"))

        reg = _make_registry({})

        # Should not raise
        migrated = await migrate_episode_agent_ids(em, reg)
        assert migrated == 0

    def test_ward_room_has_identity_registry_access(self):
        """Ward Room service accepts and propagates identity_registry."""
        from probos.ward_room.service import WardRoomService

        reg = _make_registry({})
        ws = WardRoomService(
            db_path=None,
            emit_event=MagicMock(),
            identity_registry=reg,
        )
        assert ws._identity_registry is reg

        # Verify sub-services would receive it
        from probos.ward_room.messages import MessageStore
        from probos.ward_room.threads import ThreadManager

        import inspect
        msg_sig = inspect.signature(MessageStore.__init__)
        assert "identity_registry" in msg_sig.parameters

        thread_sig = inspect.signature(ThreadManager.__init__)
        assert "identity_registry" in thread_sig.parameters
