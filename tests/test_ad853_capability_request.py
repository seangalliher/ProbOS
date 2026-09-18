"""AD-853: tests for the unified CapabilityRequest model + approval queue."""
from __future__ import annotations

import sqlite3

import pytest

from probos.capability_request import (
    FULFILMENT_KINDS,
    CapabilityRequest,
    CapabilityRequestStore,
    validate_python_install_target,
)
from probos.events import EventType


class _StringSubclass(str):
    pass


@pytest.mark.parametrize("target", [
    "numpy", "numpy.linalg", "_private", "match", "case", "type", "caf\u00e9",
])
def test_validate_python_install_target_accepts_single_dotted_import(target):
    assert validate_python_install_target(target) == target


@pytest.mark.parametrize("target", [
    None, 7, True, [], {}, b"numpy", _StringSubclass("numpy"),
    "", " ", " numpy", "numpy ", "numpy\n", "not-a-package", "for", "None",
    "numpy as np", "numpy # comment", "numpy; import scipy", "numpy, scipy",
    "numpy; pass", "numpy\nimport scipy", ".numpy", "numpy.", "numpy..linalg",
    "numpy .linalg", "numpy.\nlinalg", "123", "numpy\x00", "\ud800", "\u212anumpy",
])
def test_validate_python_install_target_rejects_noncanonical_or_compound_input(target):
    assert validate_python_install_target(target) is None


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

    async def test_list_actionable_includes_pending_and_approved_fulfilment_kinds(self, store):
        pending = [
            await store.file_request("agent", kind, "target")
            for kind in ("grant", "install", "build", "continue", "action", "future")
        ]
        approved = []
        for kind in FULFILMENT_KINDS:
            req = await store.file_request("agent", kind, "target")
            approved.append(await store.decide(req.id, True))

        actionable = await store.list_actionable()

        assert {req.id for req in actionable} == {
            req.id for req in [*pending, *approved]
        }
        assert await store.list_pending() == pending

    async def test_list_actionable_excludes_approved_actions_and_terminal_rows(self, tmp_path):
        db = str(tmp_path / "exclusions.db")
        store = CapabilityRequestStore(db_path=db)
        await store.start()
        try:
            for kind in ("grant", "install", "build", "continue", "action", "future"):
                for status in ("approved", "denied", "fulfilled", "failed"):
                    req = await store.file_request("agent", kind, status)
                    await store.decide(req.id, status != "denied")
                    if status == "fulfilled":
                        await store.mark_fulfilled(req.id)
        finally:
            await store.stop()
        with sqlite3.connect(db) as connection:
            connection.execute(
                "UPDATE capability_requests SET status = 'failed' WHERE target = 'failed'"
            )
        reopened = CapabilityRequestStore(db_path=db)
        await reopened.start()
        try:
            actionable = await reopened.list_actionable()
            assert {(req.kind, req.status) for req in actionable} == {
                (kind, "approved") for kind in FULFILMENT_KINDS
            }
            assert len(actionable) == len(FULFILMENT_KINDS)
        finally:
            await reopened.stop()

    async def test_list_actionable_empty_is_authoritative(self, store):
        assert await store.list_actionable() == []
        memory = CapabilityRequestStore()
        assert await memory.list_actionable() == []

    async def test_list_actionable_survives_restart(self, tmp_path):
        db = str(tmp_path / "actionable.db")
        store = CapabilityRequestStore(db_path=db)
        await store.start()
        try:
            pending = await store.file_request("agent", "action", "browser.navigate")
            approved = await store.file_request(
                "agent", "install", "server", work_item_id="blocked-work",
                payload={"install_kind": "mcp", "mcp_server_id": "server-id"},
            )
            await store.decide(approved.id, True, reason="permitted")
            expected = await store.list_actionable()
        finally:
            await store.stop()
        reopened = CapabilityRequestStore(db_path=db)
        await reopened.start()
        try:
            assert await reopened.list_actionable() == expected
            assert [req.id for req in await reopened.list_pending()] == [pending.id]
            assert (await reopened.get(approved.id)).payload == approved.payload
        finally:
            await reopened.stop()

    @pytest.mark.parametrize("target", [
        None, [], {}, 7, "", "numpy ", "not-a-package", "for", "numpy as np",
        "numpy, scipy", "numpy; import scipy", "numpy # comment", "\ud800", "\u212anumpy",
    ])
    async def test_python_filing_rejects_invalid_targets_before_store_effects(self, tmp_path, target):
        events = []
        db = str(tmp_path / "invalid-target.db")
        store = CapabilityRequestStore(
            db_path=db, emit_event=lambda kind, data: events.append((kind, data)),
        )
        await store.start()
        try:
            with pytest.raises(ValueError, match="Invalid Python install target"):
                await store.file_request("agent", "install", target, payload={"install_kind": "python"})
            assert await store.list_actionable() == []
            assert events == []
            with sqlite3.connect(db) as connection:
                assert connection.execute("SELECT COUNT(*) FROM capability_requests").fetchone() == (0,)
        finally:
            await store.stop()

    async def test_python_filing_keeps_dotted_target_and_mcp_label_distinct(self, store):
        python = await store.file_request("agent", "install", "numpy.linalg", payload={"install_kind": "python"})
        mcp = await store.file_request(
            "agent", "install", "a-server-name",
            payload={"install_kind": "mcp", "mcp_server_id": "server-id"},
        )
        assert python.target == "numpy.linalg"
        assert mcp.target == "a-server-name"
        assert [row.id for row in await store.list_actionable()] == [python.id, mcp.id]

    def test_actionable_kinds_match_router_fulfillers(self):
        from probos.routers.capability_requests import _APPROVAL_FULFILLERS

        assert FULFILMENT_KINDS == frozenset(_APPROVAL_FULFILLERS)
        assert "action" not in FULFILMENT_KINDS

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
