"""BF-903 (#1581) M1: one owner for the visiting-officer capability names, and AD-701's registry as the seam.

Real objects: a real ``AgentIdentityRegistry`` in ``tmp_path`` (started and commissioned as
``tests/test_ad1346_admission_service.py`` does), the real ``VisitingOfficerRegistry`` with an injected clock, the
real ``PairingRegistry`` and ``PairingService``, the real config models and the real ``probos pairing approve``.
Nothing reads the live data directory.
"""

from __future__ import annotations

from argparse import Namespace as _Namespace  # the standard library's, not a ProbOS name
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import probos.__main__ as probos_main
import probos.config_models.crew as config_crew  # A2: the vocabulary's owner, imported as test_ad1270e2g_crew_models does
from probos.config import SystemConfig, VisitingOfficersConfig
from probos.identity import AgentIdentityRegistry
from probos.security.pairing import DEFAULT_CAPABILITIES, PairingRegistry, PairingService
from probos.visiting_officers import (
    CAP_DM_RECEIVE,
    CAP_DM_SEND,
    CAP_WARD_ROOM_POST,
    CAP_WARD_ROOM_READ,
    REFUSED_CAPABILITY,
    REFUSED_EXPIRED,
    REFUSED_NO_SESSION,
    REFUSED_REGISTRY_OFF,
    VISITOR_CAPABILITIES,
    UnknownCapabilityError,
    VisitingOfficerRegistry,
    VisitorScopeRefused,
    is_visiting_identity,
    require_visitor_capability,
)

INSTANCE_ID = "bf903-m1-ship"
VESSEL_NAME = "Bf903m1"
CREW_SLOT = "counselor_counselor_0_67c601cb"
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"
Events = list[tuple[str, dict[str, Any]]]


class _Clock:
    """The registry's injected clock."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
async def identities(tmp_path: Path) -> AsyncIterator[AgentIdentityRegistry]:
    registry = AgentIdentityRegistry(data_dir=tmp_path / "identity")
    try:
        await registry.start()
        await registry.start(instance_id=INSTANCE_ID, vessel_name=VESSEL_NAME, version="1")
        yield registry
    finally:
        await registry.stop()


def _officers(identities: AgentIdentityRegistry, clock: _Clock, events: Events) -> VisitingOfficerRegistry:
    return VisitingOfficerRegistry(
        identities,
        instance_id=INSTANCE_ID,
        vessel_name=VESSEL_NAME,
        baseline_version="1",
        emit_event=lambda name, payload: events.append((name, payload)),
        clock=clock,
    )


async def _crew(identities: AgentIdentityRegistry) -> Any:
    return await identities.resolve_or_issue(
        slot_id=CREW_SLOT, agent_type="counselor", callsign="Counselor", instance_id=INSTANCE_ID,
        vessel_name=VESSEL_NAME, department="medical", post_id="counselor", baseline_version="v1",
    )


def _refusals(events: Events) -> list[dict[str, Any]]:
    return [payload for name, payload in events if name == "VISITING_OFFICER_REFUSED"]


def test_one_vocabulary_names_every_visitor_capability() -> None:
    """V1: the registry, the pairing defaults and the config default use one set of four names, defined once in
    ``config_models/crew.py`` and re-exported by ``probos.visiting_officers`` (A2)."""
    assert (CAP_WARD_ROOM_POST, CAP_WARD_ROOM_READ, CAP_DM_SEND, CAP_DM_RECEIVE) == (
        "ward_room.post", "ward_room.read", "dm.send", "dm.receive",
    )
    assert VISITOR_CAPABILITIES == frozenset({"ward_room.post", "ward_room.read", "dm.send", "dm.receive"})
    assert VISITOR_CAPABILITIES is config_crew.VISITOR_CAPABILITIES  # one owner: the re-export is the same object
    assert DEFAULT_CAPABILITIES == (CAP_DM_SEND, CAP_DM_RECEIVE)
    assert VisitingOfficersConfig().default_capabilities == [CAP_WARD_ROOM_POST, CAP_WARD_ROOM_READ]
    assert SystemConfig().visiting_officers.default_capabilities == [CAP_WARD_ROOM_POST, CAP_WARD_ROOM_READ]


@pytest.mark.parametrize(
    ("capabilities", "unknown"),
    [
        (["ward_room.pots"], ("ward_room.pots",)),
        (["tool.use"], ("tool.use",)),
        ([CAP_DM_SEND, "tool.use", "tool.use"], ("tool.use",)),
        ("dm.send", ("d", "m", ".", "s", "e", "n")),
    ],
    ids=["typo", "undeclared", "one-of-two", "a-bare-string"],
)
async def test_register_refuses_an_undeclared_capability_before_a_certificate(
    identities: AgentIdentityRegistry, capabilities: Any, unknown: tuple[str, ...],
) -> None:
    """V2: an undeclared name is refused by name; no certificate, session or event follows."""
    events: Events = []
    officers = _officers(identities, _Clock(), events)
    births = len(identities.get_all())
    with pytest.raises(UnknownCapabilityError) as refused:
        await officers.register("visitor", capabilities)
    assert refused.value.unknown == unknown
    assert len(identities.get_all()) == births
    assert officers.active() == ()
    assert events == []


def test_the_config_refuses_an_undeclared_default_capability() -> None:
    """V3: an undeclared name in visiting_officers.default_capabilities fails when the config is parsed."""
    with pytest.raises(ValidationError, match="tool.use"):
        VisitingOfficersConfig(default_capabilities=[CAP_WARD_ROOM_POST, "tool.use"])
    assert VisitingOfficersConfig(default_capabilities=[CAP_DM_SEND]).default_capabilities == [CAP_DM_SEND]


async def test_pairing_refuses_an_undeclared_capability_before_it_is_stored(
    identities: AgentIdentityRegistry, tmp_path: Path,
) -> None:
    """V4: a request or an override naming an undeclared capability stores nothing, the refused override
    leaves the code usable, and the defaults register as declared capabilities."""
    officers = _officers(identities, _Clock(), [])
    store = PairingRegistry(tmp_path / "pairings.db")
    service = PairingService(store, officers)
    with pytest.raises(UnknownCapabilityError):
        await service.request_pairing("telegram", "tg-1", capabilities=["tool.use"])
    assert store.list_pending() == []
    code = await service.request_pairing("telegram", "tg-1")
    with pytest.raises(UnknownCapabilityError):  # A3: a repeat from a sender with a pending row is checked too
        await service.request_pairing("telegram", "tg-1", capabilities=["tool.use"])
    assert await service.request_pairing("telegram", "tg-1") == code
    with pytest.raises(UnknownCapabilityError):
        await service.approve_pairing("telegram", code, capabilities_override=[CAP_DM_SEND, "tool.use"])
    assert store.get_pending("telegram", code) is not None
    assert officers.active() == ()
    paired = await service.approve_pairing("telegram", code)
    session = officers.get(paired.did)
    assert session is not None
    assert session.capabilities == frozenset({CAP_DM_SEND, CAP_DM_RECEIVE})


@pytest.mark.parametrize(
    ("stored", "cap", "named"),
    [
        ([CAP_DM_SEND], "dm.send,tool.use", "tool.use"),
        (["tool.use"], None, "tool.use"),
        ([CAP_DM_SEND], "dm.send,[/red]tool.use", "[/red]tool.use"),
    ],
    ids=["undeclared-cap-flag", "row-minted-before-bf903", "markup-in-a-name"],
)
def test_the_cli_names_an_undeclared_capability_and_keeps_the_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    stored: list[str], cap: str | None, named: str,
) -> None:
    """V5: `probos pairing approve` prints the undeclared name as text, returns 1 and records no pairing; the
    pending row is kept, whether the name came from --cap or from a row minted before BF-903, so a retry with a
    declared --cap approves it (A3)."""
    data = tmp_path / "data"
    monkeypatch.setattr(probos_main, "_default_data_dir", lambda: data)
    store = PairingRegistry(data / "pairings.db")
    store.mint_pending("telegram", "tg-9", "ABCDEF", stored, ttl_seconds=600.0)
    status = probos_main._cmd_pairing(
        _Namespace(pairing_cmd="approve", channel="telegram", code="ABCDEF", cap=cap, ttl_days=None),
    )
    assert status == 1
    assert named in capsys.readouterr().out
    assert store.list_paired() == []
    assert store.get_pending("telegram", "ABCDEF") is not None
    retried = probos_main._cmd_pairing(
        _Namespace(pairing_cmd="approve", channel="telegram", code="ABCDEF", cap=CAP_DM_SEND, ttl_days=None),
    )
    assert retried == 0
    assert [p.capabilities for p in store.list_paired()] == [(CAP_DM_SEND,)]
    assert store.get_pending("telegram", "ABCDEF") is None


@pytest.mark.parametrize(
    "stored", [[CAP_DM_SEND], [CAP_DM_SEND, "tool.use"]], ids=["declared", "row-minted-before-bf903"],
)
def test_an_expired_pending_row_is_consumed_and_answers_expired_whatever_names_it_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], stored: list[str],
) -> None:
    """V10 (A4): `probos pairing approve` without --cap consumes an expired pending row and answers that it expired,
    whatever names the row holds: one minted before BF-903 with an undeclared name is neither refused by name nor
    kept (A3's candidate did both); the declared row is the control."""
    data = tmp_path / "data"
    monkeypatch.setattr(probos_main, "_default_data_dir", lambda: data)
    minted_long_ago = PairingRegistry(data / "pairings.db", clock=lambda: 1000.0)  # the row expires at 1600.0
    minted_long_ago.mint_pending("telegram", "tg-10", "ABCDEF", stored, ttl_seconds=600.0)
    status = probos_main._cmd_pairing(
        _Namespace(pairing_cmd="approve", channel="telegram", code="ABCDEF", cap=None, ttl_days=None),
    )
    assert status == 1
    out = capsys.readouterr().out
    assert "expired" in out
    assert "tool.use" not in out
    store = PairingRegistry(data / "pairings.db")
    assert store.get_pending("telegram", "ABCDEF") is None
    assert store.get_pending_by_raw_id("telegram", "tg-10") is None
    assert store.list_paired() == []


async def test_a_malformed_agent_did_is_never_looked_up(
    identities: AgentIdentityRegistry, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """V9 (A3): a did:probos DID whose agent part is not a lower-case certificate UUID is not a visitor, passes
    the guard and costs no certificate lookup: an invalid, empty, upper-case or NUL-bearing agent part."""
    officers = _officers(identities, _Clock(), [])
    session = await officers.register("visitor", [CAP_WARD_ROOM_READ])
    prefix, visitor_uuid = session.did.rsplit(":", 1)

    def _no_lookup(_uuid: str) -> None:
        raise AssertionError("not expected: a malformed agent DID was looked up")

    monkeypatch.setattr(identities, "get_by_uuid", _no_lookup)
    for actor in (f"{prefix}:not-a-uuid", f"{prefix}:", f"{prefix}:{visitor_uuid.upper()}", f"{prefix}:{visitor_uuid}\x00"):
        assert is_visiting_identity(identities, actor) is False
        require_visitor_capability(
            actor, CAP_WARD_ROOM_POST, surface="v9", identity_registry=identities, visiting_officers=officers,
        )


async def test_the_registry_refuses_by_session_capability_and_expiry_at_use(identities: AgentIdentityRegistry) -> None:
    """V6: check() serves a held capability and refuses a missing one, a deregistered session and an expired
    one before any sweep, each with its code and one event; get() and has_capability agree."""
    clock = _Clock()
    events: Events = []
    officers = _officers(identities, clock, events)
    reader = await officers.register("reader", [CAP_WARD_ROOM_READ], session_ttl_seconds=10.0)
    gone = await officers.register("gone", [CAP_WARD_ROOM_READ])
    officers.check(reader.did, CAP_WARD_ROOM_READ, surface="v6.read")
    with pytest.raises(VisitorScopeRefused) as missing:
        officers.check(reader.did, CAP_WARD_ROOM_POST, surface="v6.post")
    assert (missing.value.did, missing.value.capability, missing.value.reason, missing.value.surface) == (
        reader.did, CAP_WARD_ROOM_POST, REFUSED_CAPABILITY, "v6.post",
    )
    officers.deregister(gone.did)
    with pytest.raises(VisitorScopeRefused) as deregistered:
        officers.check(gone.did, CAP_WARD_ROOM_READ, surface="v6.gone")
    assert deregistered.value.reason == REFUSED_NO_SESSION
    clock.now += 10.0
    assert officers.get(reader.did) is None
    assert officers.has_capability(reader.did, CAP_WARD_ROOM_READ) is False
    with pytest.raises(VisitorScopeRefused) as expired:
        officers.check(reader.did, CAP_WARD_ROOM_READ, surface="v6.read")
    assert expired.value.reason == REFUSED_EXPIRED
    assert _refusals(events) == [
        {"did": reader.did, "capability": CAP_WARD_ROOM_POST, "reason": REFUSED_CAPABILITY, "surface": "v6.post"},
        {"did": gone.did, "capability": CAP_WARD_ROOM_READ, "reason": REFUSED_NO_SESSION, "surface": "v6.gone"},
        {"did": reader.did, "capability": CAP_WARD_ROOM_READ, "reason": REFUSED_EXPIRED, "surface": "v6.read"},
    ]
    assert [p["reason"] for n, p in events if n == "VISITING_OFFICER_DEREGISTERED"] == ["explicit"]


async def test_a_visitor_is_known_by_its_certificate_and_other_ids_are_never_looked_up(
    identities: AgentIdentityRegistry, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """V7: a visiting certificate's DID is a visitor even after its session ends; a crew DID, an unknown DID,
    the ship's DID and a missing registry are not; ids that are not DIDs are never looked up."""
    officers = _officers(identities, _Clock(), [])
    session = await officers.register("visitor", [CAP_WARD_ROOM_READ])
    crew = await _crew(identities)
    assert is_visiting_identity(identities, session.did) is True
    officers.deregister(session.did)
    assert is_visiting_identity(identities, session.did) is True
    assert is_visiting_identity(identities, crew.did) is False
    assert is_visiting_identity(identities, f"did:probos:{INSTANCE_ID}:{UNKNOWN_UUID}") is False
    assert is_visiting_identity(identities, f"did:probos:{INSTANCE_ID}") is False
    assert is_visiting_identity(None, session.did) is False

    def _no_lookup(_uuid: str) -> None:
        raise AssertionError("not expected: an id that is not a DID was looked up")

    monkeypatch.setattr(identities, "get_by_uuid", _no_lookup)
    for actor in (CREW_SLOT, "captain", "system", crew.agent_uuid, "", None):
        assert is_visiting_identity(identities, actor) is False


async def test_the_one_guard_passes_crew_and_refuses_what_the_seam_does_not_allow(
    identities: AgentIdentityRegistry,
) -> None:
    """V8: crew pass with or without the registry; a visitor is served a held capability, refused a missing
    one and refused outright with the registry off; an undeclared capability raises for anyone."""
    events: Events = []
    officers = _officers(identities, _Clock(), events)
    session = await officers.register("visitor", [CAP_WARD_ROOM_READ])
    for registry in (None, officers):
        require_visitor_capability(
            CREW_SLOT, CAP_WARD_ROOM_POST, surface="v8", identity_registry=identities, visiting_officers=registry,
        )
    require_visitor_capability(
        session.did, CAP_WARD_ROOM_READ, surface="v8", identity_registry=identities, visiting_officers=officers,
    )
    with pytest.raises(VisitorScopeRefused) as missing:
        require_visitor_capability(
            session.did, CAP_WARD_ROOM_POST, surface="v8.post", identity_registry=identities,
            visiting_officers=officers,
        )
    assert missing.value.reason == REFUSED_CAPABILITY
    with pytest.raises(VisitorScopeRefused) as off:
        require_visitor_capability(
            session.did, CAP_WARD_ROOM_READ, surface="v8.off", identity_registry=identities, visiting_officers=None,
        )
    assert (off.value.reason, off.value.surface) == (REFUSED_REGISTRY_OFF, "v8.off")
    with pytest.raises(UnknownCapabilityError):
        require_visitor_capability(
            CREW_SLOT, "ward_room.pots", surface="v8", identity_registry=identities, visiting_officers=officers,
        )
    assert [p["surface"] for p in _refusals(events)] == ["v8.post"]
