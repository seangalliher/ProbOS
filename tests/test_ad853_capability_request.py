"""AD-853: tests for the unified CapabilityRequest model + approval queue."""
from __future__ import annotations

import pytest

from probos.capability_request import CapabilityRequest, CapabilityRequestStore
from probos.events import EventType


class TestCapabilityRequestStore:
    @pytest.fixture
    async def store(self, tmp_path):
        s = CapabilityRequestStore(
            db_path=str(tmp_path / "capability_requests.db"),
        )
        await s.start()
        yield s
        await s.stop()

    @pytest.mark.asyncio
    async def test_file_request_creates_pending(self, store):
        # Arrange / Act
        req = await store.file_request(
            agent_id="agent-1",
            kind="grant",
            target="filesystem_writers",
            rationale="needs to write the report",
        )
        # Assert
        assert isinstance(req, CapabilityRequest)
        assert req.id
        assert req.agent_id == "agent-1"
        assert req.kind == "grant"
        assert req.target == "filesystem_writers"
        assert req.status == "pending"
        assert req.created_at > 0
        assert (await store.get(req.id)).status == "pending"

    @pytest.mark.asyncio
    async def test_decide_approve_sets_approved_and_emits(self, tmp_path):
        # Arrange
        captured: list[tuple] = []
        s = CapabilityRequestStore(
            db_path=str(tmp_path / "cap.db"),
            emit_event=lambda et, data: captured.append((et, data)),
        )
        await s.start()
        try:
            req = await s.file_request("agent-2", "install", "httpx")
            captured.clear()
            # Act
            updated = await s.decide(req.id, approve=True, reason="ok")
            # Assert
            assert updated is not None
            assert updated.status == "approved"
            assert updated.decided_at is not None
            assert updated.decided_by == "captain"
            assert updated.decision_reason == "ok"
            assert any(
                et == EventType.CAPABILITY_REQUEST_DECIDED for et, _ in captured
            )
        finally:
            await s.stop()

    @pytest.mark.asyncio
    async def test_decide_deny_sets_denied(self, store):
        # Arrange
        req = await store.file_request("agent-3", "build", "WeatherAgent")
        # Act
        updated = await store.decide(req.id, approve=False, reason="too risky")
        # Assert
        assert updated.status == "denied"
        assert updated.decision_reason == "too risky"

    @pytest.mark.asyncio
    async def test_decide_unknown_id_returns_none(self, store):
        # Act
        result = await store.decide("does-not-exist", approve=True)
        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_list_pending_excludes_decided(self, store):
        # Arrange
        r1 = await store.file_request("agent-4", "grant", "shell")
        r2 = await store.file_request("agent-4", "install", "numpy")
        await store.decide(r1.id, approve=True)
        # Act
        pending = await store.list_pending()
        # Assert
        pending_ids = {r.id for r in pending}
        assert r2.id in pending_ids
        assert r1.id not in pending_ids

    @pytest.mark.asyncio
    async def test_persistence_round_trip(self, tmp_path):
        # Arrange
        db = str(tmp_path / "persist.db")
        s1 = CapabilityRequestStore(db_path=db)
        await s1.start()
        req = await s1.file_request(
            "agent-5", "grant", "directory", work_item_id="wi-9"
        )
        await s1.stop()
        # Act — new store, same db
        s2 = CapabilityRequestStore(db_path=db)
        await s2.start()
        try:
            restored = await s2.get(req.id)
            # Assert
            assert restored is not None
            assert restored.agent_id == "agent-5"
            assert restored.target == "directory"
            assert restored.work_item_id == "wi-9"
        finally:
            await s2.stop()

    @pytest.mark.asyncio
    async def test_work_item_id_carried_through(self, store):
        # Arrange / Act
        req = await store.file_request(
            "agent-6", "build", "ReportAgent", work_item_id="wi-42"
        )
        # Assert
        fetched = await store.get(req.id)
        assert fetched.work_item_id == "wi-42"

    @pytest.mark.asyncio
    async def test_decide_records_trust_outcome(self, tmp_path):
        # Arrange — real TrustNetwork (in-memory), no MagicMock at the boundary
        from probos.consensus.trust import TrustNetwork

        trust = TrustNetwork()
        s = CapabilityRequestStore(
            db_path=str(tmp_path / "trust.db"),
            trust_network=trust,
        )
        await s.start()
        try:
            req = await s.file_request("agent-7", "grant", "http")
            before = trust.get_score("agent-7")
            # Act — an approval is a successful outcome, raising the score
            await s.decide(req.id, approve=True)
            after = trust.get_score("agent-7")
            # Assert
            assert after > before
        finally:
            await s.stop()
