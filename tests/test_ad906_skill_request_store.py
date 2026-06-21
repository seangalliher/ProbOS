"""AD-906: tests for the SkillRequest model + Captain approval queue.

asyncio_mode="auto" (pyproject): tests are plain ``async def`` with no
``@pytest.mark.asyncio`` marker. BF-287: real ``SkillRequestStore`` fixtures,
no MagicMock at the substrate boundary.
"""
from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from probos.api_models import SkillRequestDecideRequest
from probos.events import EventType
from probos.skill_request import SkillRequest, SkillRequestStore


class _FakeTrust:
    """Records record_outcome calls so the trust path can be asserted."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def record_outcome(
        self,
        agent_id: str,
        success: bool,
        *,
        weight: float = 1.0,
        intent_type: str = "",
        source: str = "",
    ) -> None:
        self.calls.append({
            "agent_id": agent_id,
            "success": success,
            "weight": weight,
            "intent_type": intent_type,
            "source": source,
        })


@pytest.fixture
async def store(tmp_path: Any) -> SkillRequestStore:
    s = SkillRequestStore(db_path=str(tmp_path / "skill_requests.db"))
    await s.start()
    try:
        yield s
    finally:
        await s.stop()


async def test_file_request_appears_in_list_pending(store: SkillRequestStore) -> None:
    req = await store.file_request(
        "agent-1", "summarization",
        skill_label="Summarization", source="self",
        justification="needs to condense long reports",
    )

    assert isinstance(req, SkillRequest)
    assert req.status == "requested"
    assert req.skill_id == "summarization"
    assert req.source == "self"
    pending = await store.list_pending()
    assert [r.id for r in pending] == [req.id]


async def test_decide_approve_sets_approved_and_emits(tmp_path: Any) -> None:
    captured: list[tuple] = []
    s = SkillRequestStore(
        db_path=str(tmp_path / "sk.db"),
        emit_event=lambda et, data: captured.append((et, data)),
    )
    await s.start()
    try:
        req = await s.file_request("agent-2", "negotiation")
        captured.clear()
        updated = await s.decide(req.id, approve=True, reason="useful")
        assert updated is not None
        assert updated.status == "approved"
        assert updated.decided_by == "captain"
        assert updated.decision_reason == "useful"
        assert any(et == EventType.SKILL_REQUEST_DECIDED for et, _ in captured)
    finally:
        await s.stop()


async def test_decide_deny_records_trust_outcome(tmp_path: Any) -> None:
    trust = _FakeTrust()
    s = SkillRequestStore(db_path=str(tmp_path / "sk.db"), trust_network=trust)
    await s.start()
    try:
        req = await s.file_request("agent-3", "forecasting")
        updated = await s.decide(req.id, approve=False, reason="out of scope")
        assert updated is not None
        assert updated.status == "denied"
        assert len(trust.calls) == 1
        call = trust.calls[0]
        assert call["agent_id"] == "agent-3"
        assert call["success"] is False
        assert call["intent_type"] == "skill_request"
        assert call["source"] == "skill_request"
    finally:
        await s.stop()


async def test_decide_transitions_status_away_from_requested(store: SkillRequestStore) -> None:
    # The router's 400 already-decided guard relies on the store leaving the
    # request in a non-"requested" state after a decision.
    req = await store.file_request("agent-4", "translation")
    await store.decide(req.id, approve=True)

    again = await store.get(req.id)
    assert again is not None
    assert again.status != "requested"
    assert again.status == "approved"
    assert await store.list_pending() == []


async def test_decide_unknown_id_returns_none(store: SkillRequestStore) -> None:
    result = await store.decide("does-not-exist", approve=True)
    assert result is None


async def test_decide_deny_without_reason_rejected_by_validator() -> None:
    # The api_models validator owns the deny-needs-reason guard.
    with pytest.raises(ValidationError):
        SkillRequestDecideRequest(approve=False, reason="   ")
    # An approve may omit the reason.
    ok = SkillRequestDecideRequest(approve=True)
    assert ok.approve is True


async def test_db_path_empty_is_cache_only_no_file_io(tmp_path: Any) -> None:
    # db_path="" means no SQLite file is opened; the store runs cache-only.
    s = SkillRequestStore(db_path="")
    await s.start()
    try:
        req = await s.file_request("agent-5", "planning")
        assert (await store_get(s, req.id)).status == "requested"
        pending = await s.list_pending()
        assert [r.id for r in pending] == [req.id]
        # No DB handle was opened, and nothing was written under tmp_path.
        assert s._db is None
        assert not any(tmp_path.iterdir())
    finally:
        await s.stop()


async def store_get(s: SkillRequestStore, request_id: str) -> SkillRequest:
    got = await s.get(request_id)
    assert got is not None
    return got


async def test_begin_training_links_simulation_and_sets_in_training(
    store: SkillRequestStore,
) -> None:
    req = await store.file_request("agent-6", "synthesis")
    await store.decide(req.id, approve=True)

    updated = await store.begin_training(req.id, "sim-123")
    assert updated is not None
    assert updated.status == "in_training"
    assert updated.linked_simulation_id == "sim-123"


async def test_list_by_agent_returns_all_statuses(store: SkillRequestStore) -> None:
    r1 = await store.file_request("agent-7", "skill-a")
    r2 = await store.file_request("agent-7", "skill-b")
    await store.file_request("agent-8", "skill-c")
    await store.decide(r1.id, approve=True)

    by_agent = await store.list_by_agent("agent-7")
    ids = {r.id for r in by_agent}
    assert ids == {r1.id, r2.id}
