"""AD-802: tests for the pairing substrate (registry + service + doctor check + EventType)."""
from __future__ import annotations

import time
from dataclasses import dataclass

import pytest

from probos.events import EventType
from probos.security.pairing import (
    DEFAULT_CAPABILITIES,
    DEFAULT_CODE_ALPHABET,
    PairingRegistry,
    PairingService,
    UnknownPairingCode,
)


# ----- fake VisitingOfficerRegistry -----


@dataclass(frozen=True)
class _FakeSession:
    did: str
    callsign: str


class _FakeVO:
    """Mirrors `VisitingOfficerRegistry.register` / `deregister` shape (AD-701)."""

    def __init__(self) -> None:
        self.sessions: dict[str, _FakeSession] = {}
        self.register_calls: list[dict] = []
        self.deregister_calls: list[str] = []
        self._counter = 0

    async def register(
        self,
        callsign: str,
        capabilities,
        *,
        origin: str = "",
        session_ttl_seconds: float | None = None,
    ) -> _FakeSession:
        self._counter += 1
        did = f"did:fake:visiting:{self._counter:06x}"
        sess = _FakeSession(did=did, callsign=callsign)
        self.sessions[did] = sess
        self.register_calls.append({
            "callsign": callsign,
            "capabilities": list(capabilities),
            "origin": origin,
            "session_ttl_seconds": session_ttl_seconds,
        })
        return sess

    def deregister(self, did: str) -> bool:
        self.deregister_calls.append(did)
        return self.sessions.pop(did, None) is not None


@pytest.fixture
def registry(tmp_path):
    return PairingRegistry(tmp_path / "pairings.db")


@pytest.fixture
def vo():
    return _FakeVO()


@pytest.fixture
def service(registry, vo):
    events: list[tuple[str, dict]] = []

    def _emit(name: str, payload: dict) -> None:
        events.append((name, payload))

    svc = PairingService(
        registry=registry,
        visiting_officers=vo,
        emit_event=_emit,
    )
    svc._test_events = events  # type: ignore[attr-defined]
    return svc


# ----- registry primitives -----


def test_event_type_pairing_values_present():
    """AD-802 emits three new event types — must be in the EventType enum."""
    assert EventType.PAIRING_REQUESTED.value == "pairing_requested"
    assert EventType.PAIRING_APPROVED.value == "pairing_approved"
    assert EventType.PAIRING_REVOKED.value == "pairing_revoked"


def test_registry_mint_pending_persists(registry):
    pending = registry.mint_pending(
        channel="telegram",
        raw_id="tg-12345",
        code="ABC123",
        capabilities=["dm.send"],
        ttl_seconds=3600.0,
    )
    assert pending.code == "ABC123"
    # Round-trip via a fresh registry instance reads the same row.
    fresh = PairingRegistry(registry._db_path)
    got = fresh.get_pending("telegram", "ABC123")
    assert got is not None
    assert got.raw_id == "tg-12345"
    assert "dm.send" in got.capabilities


def test_registry_consume_pending_returns_then_deletes(registry):
    registry.mint_pending("telegram", "tg-1", "AAAAAA", ["dm.send"], ttl_seconds=60.0)
    first = registry.consume_pending("telegram", "AAAAAA")
    assert first is not None
    second = registry.consume_pending("telegram", "AAAAAA")
    assert second is None


def test_registry_sweep_expired_pending(tmp_path):
    """Expired rows are deleted by `sweep_expired_pending`."""
    clock = {"now": 1000.0}
    reg = PairingRegistry(tmp_path / "pairings.db", clock=lambda: clock["now"])
    reg.mint_pending("c", "r1", "AAA", ["dm.send"], ttl_seconds=10.0)
    reg.mint_pending("c", "r2", "BBB", ["dm.send"], ttl_seconds=1000.0)
    clock["now"] = 1020.0  # AAA expired, BBB still valid
    removed = reg.sweep_expired_pending()
    assert removed == 1
    assert reg.get_pending("c", "AAA") is None
    assert reg.get_pending("c", "BBB") is not None


# ----- service: request / approve / revoke / resolve -----


@pytest.mark.asyncio
async def test_request_pairing_emits_event_and_returns_code(service):
    code = await service.request_pairing("telegram", "tg-99")
    assert len(code) == 6
    assert all(c in DEFAULT_CODE_ALPHABET for c in code)
    events = service._test_events  # type: ignore[attr-defined]
    assert any(name == "pairing_requested" for name, _ in events)


@pytest.mark.asyncio
async def test_request_pairing_is_idempotent_per_raw_id(service):
    """Two requests for the same (channel, raw_id) must return the same code."""
    code1 = await service.request_pairing("telegram", "tg-77")
    code2 = await service.request_pairing("telegram", "tg-77")
    assert code1 == code2


@pytest.mark.asyncio
async def test_approve_pairing_mints_vo_and_persists(service, vo, registry):
    code = await service.request_pairing("telegram", "tg-42", capabilities=["dm.send", "ward_room.post"])
    paired = await service.approve_pairing("telegram", code)
    # VO got called with the right capabilities + origin.
    assert vo.register_calls[-1]["capabilities"] == ["dm.send", "ward_room.post"]
    assert vo.register_calls[-1]["origin"] == "pairing:telegram"
    # paired_users row persisted.
    persisted = registry.lookup_by_did(paired.did)
    assert persisted is not None
    assert persisted.raw_id == "tg-42"
    # Pending row consumed.
    assert registry.get_pending("telegram", code) is None


@pytest.mark.asyncio
async def test_approve_unknown_code_raises(service):
    with pytest.raises(UnknownPairingCode):
        await service.approve_pairing("telegram", "ZZZZZZ")


@pytest.mark.asyncio
async def test_revoke_pairing_clears_vo_and_row(service, vo, registry):
    code = await service.request_pairing("telegram", "tg-55")
    paired = await service.approve_pairing("telegram", code)
    removed = await service.revoke_pairing(paired.did)
    assert removed is True
    assert vo.deregister_calls[-1] == paired.did
    assert registry.lookup_by_did(paired.did) is None


@pytest.mark.asyncio
async def test_resolve_did_returns_did_for_paired_sender(service):
    code = await service.request_pairing("telegram", "tg-22")
    paired = await service.approve_pairing("telegram", code)
    assert service.resolve_did("telegram", "tg-22") == paired.did
    assert service.resolve_did("telegram", "tg-unknown") is None


@pytest.mark.asyncio
async def test_capabilities_override_on_approve(service):
    code = await service.request_pairing("telegram", "tg-33", capabilities=["dm.send"])
    paired = await service.approve_pairing(
        "telegram", code,
        capabilities_override=["dm.send", "tool.use", "ward_room.post"],
    )
    assert "tool.use" in paired.capabilities
    assert "ward_room.post" in paired.capabilities


@pytest.mark.asyncio
async def test_restore_active_sessions_repopulates_vo(tmp_path):
    """On runtime boot, paired_users rows are re-registered as VO sessions."""
    clock = {"now": 1000.0}
    reg = PairingRegistry(tmp_path / "pairings.db", clock=lambda: clock["now"])
    # Pre-populate two rows: one active, one expired.
    reg.record_pairing("telegram", "tg-1", "did:foo:1", ["dm.send"], ttl_seconds=10000.0)
    reg.record_pairing("telegram", "tg-2", "did:foo:2", ["dm.send"], ttl_seconds=1.0)
    clock["now"] = 1005.0  # tg-2 has expired

    vo = _FakeVO()
    svc = PairingService(registry=reg, visiting_officers=vo, clock=lambda: clock["now"])
    restored = await svc.restore_active_sessions()
    assert restored == 1
    assert len(vo.register_calls) == 1


# ----- doctor pairing check -----


@pytest.mark.asyncio
async def test_doctor_pairing_check_reports_active_count(tmp_path):
    """The AD-802 doctor check reports active + pending counts."""
    from probos.doctor.checks.pairing_check import _PairingCheck
    from probos.doctor.protocol import CheckOutcome, DoctorContext

    # Pre-populate the store at the location the check expects (data_dir/pairings.db).
    reg = PairingRegistry(tmp_path / "pairings.db")
    reg.record_pairing("telegram", "tg-1", "did:foo:1", ["dm.send"], ttl_seconds=10000.0)
    reg.mint_pending("telegram", "tg-2", "AAAAAA", ["dm.send"], ttl_seconds=10000.0)

    ctx = DoctorContext(config=None, home_dir=tmp_path, data_dir=tmp_path, config_path=None)
    result = await _PairingCheck().run(ctx)
    assert result.outcome is CheckOutcome.OK
    assert "1 active" in result.message
    assert "1 pending" in result.message
