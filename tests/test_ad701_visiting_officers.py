"""Tests for AD-701 — Visiting Officer registry.

Wave 130. Closes #477.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.visiting_officers import (
    VISITING_AGENT_TYPE,
    VisitingOfficerRegistry,
    VisitingOfficerSession,
)


@dataclass(frozen=True)
class _FakeBirthCert:
    did: str
    agent_uuid: str = "fake-uuid"
    certificate_hash: str = "fake-hash"


class _FakeIdentityRegistry:
    """Minimal stub mimicking AgentIdentityRegistry for AD-701 tests."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._counter = 0

    async def issue_birth_certificate(
        self,
        agent_type: str,
        callsign: str,
        instance_id: str,
        vessel_name: str,
        department: str,
        post_id: str,
        baseline_version: str,
        slot_id: str = "",
    ) -> _FakeBirthCert:
        self._counter += 1
        self.calls.append({
            "agent_type": agent_type,
            "callsign": callsign,
            "instance_id": instance_id,
            "vessel_name": vessel_name,
            "department": department,
            "post_id": post_id,
            "baseline_version": baseline_version,
        })
        return _FakeBirthCert(did=f"did:probos:test:{callsign}-{self._counter}")


class _FakeClock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def _make_registry(
    *,
    identity: _FakeIdentityRegistry | None = None,
    emit: list | None = None,
    clock: _FakeClock | None = None,
    session_ttl: float = 3600.0,
    sweep_interval: float = 60.0,
) -> tuple[VisitingOfficerRegistry, _FakeIdentityRegistry, list, _FakeClock]:
    identity = identity or _FakeIdentityRegistry()
    emit_log: list = emit if emit is not None else []
    clock = clock or _FakeClock()

    def emit_event(name: str, payload: dict[str, Any]) -> None:
        emit_log.append((name, payload))

    reg = VisitingOfficerRegistry(
        identity_registry=identity,
        instance_id="inst-1",
        vessel_name="USS Test",
        baseline_version="0.0.1",
        emit_event=emit_event,
        session_ttl_seconds=session_ttl,
        sweep_interval_seconds=sweep_interval,
        clock=clock,
    )
    return reg, identity, emit_log, clock


@pytest.mark.asyncio
async def test_register_issues_did_via_identity_registry() -> None:
    reg, identity, _emit, _clock = _make_registry()

    session = await reg.register(
        callsign="claude-code-1",
        capabilities=["ward_room.post"],
    )

    assert isinstance(session, VisitingOfficerSession)
    assert session.did.startswith("did:probos:")
    assert len(identity.calls) == 1
    call = identity.calls[0]
    assert call["agent_type"] == VISITING_AGENT_TYPE
    assert call["department"] == "visiting"
    assert call["callsign"] == "claude-code-1"
    assert call["instance_id"] == "inst-1"
    assert call["vessel_name"] == "USS Test"
    assert call["baseline_version"] == "0.0.1"


@pytest.mark.asyncio
async def test_register_records_session_with_capabilities() -> None:
    reg, _identity, _emit, clock = _make_registry()

    session = await reg.register(
        callsign="copilot",
        capabilities=["ward_room.post", "ward_room.read"],
        origin="vscode",
    )

    fetched = reg.get(session.did)
    assert fetched is not None
    assert fetched.capabilities == frozenset({"ward_room.post", "ward_room.read"})
    assert fetched.origin == "vscode"
    assert fetched.registered_at == clock.t
    assert fetched.expires_at == clock.t + 3600.0


@pytest.mark.asyncio
async def test_register_emits_event() -> None:
    reg, _identity, emit_log, _clock = _make_registry()

    await reg.register(callsign="x", capabilities=["c"], origin="o")

    names = [name for name, _ in emit_log]
    assert "VISITING_OFFICER_REGISTERED" in names
    payload = next(p for n, p in emit_log if n == "VISITING_OFFICER_REGISTERED")
    assert payload["callsign"] == "x"
    assert payload["origin"] == "o"
    assert payload["capabilities"] == ["c"]
    assert "expires_at" in payload
    assert "did" in payload


@pytest.mark.asyncio
async def test_register_rejects_empty_callsign_or_caps() -> None:
    reg, _identity, _emit, _clock = _make_registry()

    with pytest.raises(ValueError):
        await reg.register(callsign="", capabilities=["c"])
    with pytest.raises(ValueError):
        await reg.register(callsign="x", capabilities=[])
    with pytest.raises(ValueError):
        await reg.register(callsign="x", capabilities=["c"], session_ttl_seconds=0)


@pytest.mark.asyncio
async def test_deregister_removes_session_and_emits() -> None:
    reg, _identity, emit_log, _clock = _make_registry()
    session = await reg.register(callsign="x", capabilities=["c"])

    assert reg.deregister(session.did) is True
    assert reg.get(session.did) is None
    # Second call returns False (already removed).
    assert reg.deregister(session.did) is False

    deregistered = [p for n, p in emit_log if n == "VISITING_OFFICER_DEREGISTERED"]
    assert len(deregistered) == 1
    assert deregistered[0]["reason"] == "explicit"
    assert deregistered[0]["callsign"] == "x"


@pytest.mark.asyncio
async def test_has_capability_enforces_scope_and_expiry() -> None:
    clock = _FakeClock(t=1000.0)
    reg, _identity, _emit, _ = _make_registry(clock=clock, session_ttl=10.0)
    session = await reg.register(callsign="x", capabilities=["ward_room.post"])

    # In-scope cap, not expired
    assert reg.has_capability(session.did, "ward_room.post") is True
    # Out-of-scope cap
    assert reg.has_capability(session.did, "ward_room.admin") is False
    # Expire the session
    clock.t = 1100.0
    assert reg.has_capability(session.did, "ward_room.post") is False
    # Unknown DID
    assert reg.has_capability("did:probos:unknown", "ward_room.post") is False


@pytest.mark.asyncio
async def test_sweep_loop_deregisters_expired() -> None:
    clock = _FakeClock(t=1000.0)
    reg, _identity, emit_log, _ = _make_registry(clock=clock, session_ttl=10.0)
    session = await reg.register(callsign="x", capabilities=["c"])
    assert reg.get(session.did) is not None

    # Advance past expiry and trigger one sweep cycle.
    clock.t = 2000.0
    await reg._sweep_once()

    assert reg.get(session.did) is None
    deregistered = [p for n, p in emit_log if n == "VISITING_OFFICER_DEREGISTERED"]
    assert len(deregistered) == 1
    assert deregistered[0]["reason"] == "expired"
    assert deregistered[0]["did"] == session.did


@pytest.mark.asyncio
async def test_active_excludes_expired() -> None:
    clock = _FakeClock(t=1000.0)
    reg, _identity, _emit, _ = _make_registry(clock=clock, session_ttl=10.0)
    s1 = await reg.register(callsign="alive", capabilities=["c"])
    s2 = await reg.register(
        callsign="dying", capabilities=["c"], session_ttl_seconds=5.0
    )
    # Advance clock past s2 expiry (1005) but before s1 (1010)
    clock.t = 1006.0

    active = reg.active()
    dids = {s.did for s in active}
    assert s1.did in dids
    assert s2.did not in dids


@pytest.mark.asyncio
async def test_start_stop_idempotent() -> None:
    reg, _identity, _emit, _clock = _make_registry(sweep_interval=0.05)

    await reg.start()
    await reg.start()  # idempotent no-op
    await asyncio.sleep(0.01)
    await reg.stop()
    await reg.stop()  # idempotent no-op


@pytest.mark.asyncio
async def test_pydantic_visiting_officers_config_defaults() -> None:
    from probos.config import VisitingOfficersConfig

    cfg = VisitingOfficersConfig()
    assert cfg.enabled is False  # convention #14
    assert cfg.session_ttl_seconds == 3600.0
    assert cfg.sweep_interval_seconds == 60.0
    assert "ward_room.post" in cfg.default_capabilities


@pytest.mark.asyncio
async def test_emit_event_failure_does_not_break_register() -> None:
    """Log-and-degrade: if emit_event raises, register still succeeds."""
    identity = _FakeIdentityRegistry()

    def bad_emit(name: str, payload: dict[str, Any]) -> None:
        raise RuntimeError("emit broken")

    reg = VisitingOfficerRegistry(
        identity_registry=identity,
        instance_id="inst-1",
        vessel_name="USS Test",
        baseline_version="0.0.1",
        emit_event=bad_emit,
    )
    session = await reg.register(callsign="x", capabilities=["c"])
    assert session.did.startswith("did:probos:")
