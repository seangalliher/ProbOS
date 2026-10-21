"""AD-1346 M1a (epic #1601, checklist M1, first slice): ``IdentityRef`` and the ``IdentityService`` facade.

``probos.identity_service`` resolves an agent's identity, in any form a caller holds, to one frozen ``IdentityRef``:
a slot id, a birth-certificate UUID, a ``did:probos`` agent DID or an asset-tag UUID through ``resolve``, and a
callsign through ``resolve_callsign``. These tests drive the facade over a real ``AgentIdentityRegistry`` and a real
``CallsignRegistry`` bound to a real ``AgentRegistry``, and they hold the three things AD-1346 M3 (#1604) builds on:
the facade agrees with BF-907's ``resolve_slot_id`` over every identity form that resolver accepts and takes the slot
ids it does not (T3); ``IdentityRef.to_dict()`` is the frozen form a shadow decision embeds (T10); and the facade is
the only constructor of a ref in ``src`` and holds no copy of the resolution logic (T12, T13).

Every fixture uses the live shapes (2026-10-18/19) of ``tests/test_bf907_trust_identity.py``: slot ids
``surgeon_medical_surgeon_0_b2321292`` and ``counselor_counselor_0_67c601cb``, certificate UUIDs and DIDs issued by a
real ``AgentIdentityRegistry``. All state lives in ``tmp_path``; the live data directory, the OS keyring and the
network are never touched. Nothing here sleeps.
"""

from __future__ import annotations

import ast
import copy
import dataclasses
import inspect
import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio

import probos
import probos.identity as identity
from probos.crew_profile import CallsignRegistry
from probos.identity import AgentBirthCertificate, AgentIdentityRegistry
from probos.identity_service import IDENTITY_REF_KEYS, IdentityRef, IdentityService
from probos.substrate.registry import AgentRegistry

INSTANCE_ID = "ad1346-ship"
VESSEL_NAME = "Ad1346"
SURGEON_SLOT = "surgeon_medical_surgeon_0_b2321292"
SURGEON_SECOND_SLOT = "surgeon_medical_surgeon_1_9d41e0aa"
COUNSELOR_SLOT = "counselor_counselor_0_67c601cb"
TOOL_SLOT = "calculator_calculator_0_5f3a9c1e"
SCOUT_SLOT = "scout_scout_0_1a2b3c4d"
RUNTIME_ID = "24ca56be31064c24a102afbceaff6636"  # a dashless 32-hex runtime agent id (the BaseAgent default)
PEER_KEY = "federation_peer:ship-b"
PROFILE_CALLSIGNS = {"surgeon": "Meridian", "counselor": "Ezri", "scout": "Wesley"}

_SRC = Path(probos.__file__).resolve().parent


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def registry(tmp_path: Path) -> AsyncIterator[AgentIdentityRegistry]:
    """A real identity registry in ``tmp_path``, started and commissioned as tests/test_bf907_trust_identity.py does."""
    reg = AgentIdentityRegistry(data_dir=tmp_path / "identity")
    try:
        await reg.start()
        await reg.start(instance_id=INSTANCE_ID, vessel_name=VESSEL_NAME, version="1")
        yield reg
    finally:
        await reg.stop()


@pytest.fixture
def agents() -> AgentRegistry:
    """A real, empty ``AgentRegistry``: a test registers the live agents it needs."""
    return AgentRegistry()


@pytest.fixture
def callsigns(tmp_path: Path, agents: AgentRegistry) -> CallsignRegistry:
    """A real ``CallsignRegistry`` over three profiles written to ``tmp_path``, bound to ``agents``."""
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    for agent_type, callsign in PROFILE_CALLSIGNS.items():
        (profiles / f"{agent_type}.yaml").write_text(f"callsign: {callsign}\n", encoding="utf-8")
    directory = CallsignRegistry()
    directory.load_from_profiles(str(profiles))
    directory.bind_registry(agents)
    return directory


@pytest.fixture
def service(registry: AgentIdentityRegistry, callsigns: CallsignRegistry) -> IdentityService:
    """The facade, built before a test issues any identity: it holds both registries by reference."""
    return IdentityService(registry, callsigns)


async def _issue(
    reg: AgentIdentityRegistry,
    slot_id: str = SURGEON_SLOT,
    agent_type: str = "surgeon",
    callsign: str = "Meridian",
    department: str = "medical",
    post_id: str = "surgeon",
) -> AgentBirthCertificate:
    """Issue (or resolve) the birth certificate of a slot through the real registry."""
    return await reg.resolve_or_issue(
        slot_id=slot_id, agent_type=agent_type, callsign=callsign, instance_id=INSTANCE_ID,
        vessel_name=VESSEL_NAME, department=department, post_id=post_id, baseline_version="v1",
    )


async def _go_live(agents: AgentRegistry, slot_id: str, agent_type: str) -> None:
    """Register a live agent of ``agent_type`` under ``slot_id``; ``CallsignRegistry.resolve`` finds it by pool."""
    await agents.register(SimpleNamespace(id=slot_id, agent_type=agent_type, pool=agent_type, is_alive=True))


def _non_candidates() -> list[str]:
    """Keys that name no registered identity: the live non-candidate shapes, and sovereign-shaped keys bound to nothing."""
    unknown_uuid = str(uuid.uuid4())
    return [
        RUNTIME_ID, "system", "captain", PEER_KEY, "mcp-peer:tool-x", "device:usb-1",
        unknown_uuid,
        f"did:probos:{INSTANCE_ID}:{unknown_uuid}",  # an unknown DID
        f"did:probos:{INSTANCE_ID}",  # the ship DID
        f"did:probos:{INSTANCE_ID}:{unknown_uuid}:extra",  # a 5-part DID
        "Meridian",  # a callsign is a name, not a key (D6)
    ]


def _slot_of(service: IdentityService, key: Any) -> str | None:
    """The slot id of the ref ``service.resolve(key)`` gives, or None."""
    ref = service.resolve(key)
    return ref.slot_id if ref is not None else None


def _assert_agreement(
    service: IdentityService, registry: AgentIdentityRegistry, slots: tuple[str, ...], keys: list[str],
) -> None:
    """The facade agrees with BF-907's resolver on every key it accepts and takes the slot ids it does not."""
    for slot in slots:
        assert registry.resolve_slot_id(slot) is None, slot  # BF-907 does not take a slot id ...
        assert _slot_of(service, slot) == slot, slot  # ... so the facade's slot path is its own
    for key in keys:
        if identity.is_sovereign_identity_key(key):
            assert _slot_of(service, key) == registry.resolve_slot_id(key), key
        else:
            assert registry.resolve_slot_id(key) is None, key
            assert _slot_of(service, key) is None, key


def _identity_ref_calls(tree: ast.AST) -> int:
    """How many ``IdentityRef(...)`` and ``module.IdentityRef(...)`` calls ``tree`` holds."""
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == "IdentityRef")
            or (isinstance(node.func, ast.Attribute) and node.func.attr == "IdentityRef")
        )
    )


def _module_names(statements: list[ast.stmt]) -> set[str]:
    """The dotted modules the ``import`` and ``from ... import`` statements among ``statements`` name."""
    names: set[str] = set()
    for node in statements:
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add("." * node.level + (node.module or ""))
    return names


class _S(str):
    """A ``str`` subclass: ``type(x) is not str``, so ``IdentityRef`` refuses it (T9)."""


# ---------------------------------------------------------------------------
# Resolution by delegation (T1 to T8)
# ---------------------------------------------------------------------------


async def test_resolve_a_slot_id_gives_its_certificate_ref(
    registry: AgentIdentityRegistry, service: IdentityService,
) -> None:
    """A slot id resolves to the ref of its birth certificate, with the live callsign (kills M2, M7, M10)."""
    cert = await _issue(registry)
    # premise: BF-907's resolver does not take a slot id, so the facade's slot path is its own
    assert registry.resolve_slot_id(SURGEON_SLOT) is None

    ref = service.resolve(SURGEON_SLOT)

    assert isinstance(ref, IdentityRef)
    assert ref.slot_id == SURGEON_SLOT
    assert ref.sovereign_id == cert.agent_uuid
    assert ref.did == cert.did
    assert ref.callsign == "Meridian"
    assert ref.agent_type == "surgeon"


async def test_resolve_an_asset_slot_and_its_asset_uuid(
    registry: AgentIdentityRegistry, service: IdentityService,
) -> None:
    """An asset's slot and its asset-tag UUID resolve to one ref: the tag UUID is the sovereign id, no DID (kills M3, M4, M11)."""
    tag = await registry.resolve_or_issue_asset_tag(TOOL_SLOT, "calculator", "calculator")

    by_slot = service.resolve(TOOL_SLOT)
    by_uuid = service.resolve(tag.asset_uuid)

    expected = IdentityRef(slot_id=TOOL_SLOT, sovereign_id=tag.asset_uuid, did="", callsign="", agent_type="calculator")
    for ref in (by_slot, by_uuid):
        assert ref is not None
        assert ref == expected
        assert ref.slot_id == TOOL_SLOT
        assert ref.sovereign_id == tag.asset_uuid
        assert ref.did == ""
        assert ref.callsign == ""  # no profile for a calculator (D2)
        assert ref.agent_type == "calculator"


async def test_the_facade_agrees_with_resolve_slot_id_over_every_identity_form(
    registry: AgentIdentityRegistry, service: IdentityService,
) -> None:
    """Over every identity form, the facade's slot is BF-907's, and the facade takes the slot ids BF-907 does not.

    Pass one: every identity is bound to one slot. Pass two: the surgeon is bound to a second slot (ambiguous), so its
    UUID and DID resolve to None from both resolvers, and its two slots are two different refs (kills M2, M3, M4).
    """
    surgeon = await _issue(registry)
    counselor = await _issue(registry, COUNSELOR_SLOT, "counselor", "Ezri", "medical", "counselor")
    tag = await registry.resolve_or_issue_asset_tag(TOOL_SLOT, "calculator", "calculator")
    bound = {
        surgeon.agent_uuid: SURGEON_SLOT, surgeon.did: SURGEON_SLOT,
        counselor.agent_uuid: COUNSELOR_SLOT, counselor.did: COUNSELOR_SLOT,
        tag.asset_uuid: TOOL_SLOT,
    }
    non_candidates = _non_candidates()
    slots = (SURGEON_SLOT, COUNSELOR_SLOT, TOOL_SLOT)

    # pass one: each identity is bound to one slot; the second surgeon slot is not occupied yet
    _assert_agreement(service, registry, slots, [*bound, *non_candidates, SURGEON_SECOND_SLOT])
    for key, slot in bound.items():  # premise: the agreement is not two Nones
        assert registry.resolve_slot_id(key) == slot, key
        assert _slot_of(service, key) == slot, key

    ok, _message = await registry.reassign_slot(surgeon.agent_uuid, SURGEON_SECOND_SLOT)
    assert ok is True

    # pass two: the surgeon is bound to two slots, so neither resolver names one for its UUID or DID
    _assert_agreement(service, registry, (*slots, SURGEON_SECOND_SLOT), [*bound, *non_candidates])
    for key, slot in bound.items():
        expected = None if slot == SURGEON_SLOT else slot
        assert registry.resolve_slot_id(key) == expected, key
        assert _slot_of(service, key) == expected, key
    first = service.resolve(SURGEON_SLOT)
    second = service.resolve(SURGEON_SECOND_SLOT)
    assert first is not None and second is not None
    assert first.sovereign_id == second.sovereign_id == surgeon.agent_uuid
    assert first != second


async def test_resolve_returns_none_for_empty_non_string_unknown_and_callsign_keys(
    registry: AgentIdentityRegistry, agents: AgentRegistry, service: IdentityService,
) -> None:
    """Empty, non-string, unknown and callsign keys resolve to None and never raise; ``["x"]`` is unhashable (kills M1)."""
    await _issue(registry)
    await _go_live(agents, SURGEON_SLOT, "surgeon")
    # premise: Meridian is a callsign the facade DOES resolve, through resolve_callsign; resolve() must not take it (D6)
    assert service.resolve_callsign("Meridian") is not None

    for key in ["", None, 7, ["x"], b"x", "meridian", *_non_candidates()]:
        assert service.resolve(key) is None, key  # type: ignore[arg-type]


async def test_the_certificate_wins_over_an_asset_tag_on_one_slot(
    registry: AgentIdentityRegistry, service: IdentityService,
) -> None:
    """A slot that holds a tag and then a certificate, the live order, resolves to the certificate (D7; kills M8)."""
    tag = await registry.resolve_or_issue_asset_tag(SURGEON_SLOT, "surgeon", "surgeon")
    cert = await _issue(registry)
    # premise: the slot holds both, two different identities
    assert registry.get_asset_by_slot(SURGEON_SLOT) is tag
    assert registry.get_by_slot(SURGEON_SLOT) is cert
    assert tag.asset_uuid != cert.agent_uuid

    by_slot = service.resolve(SURGEON_SLOT)
    by_tag = service.resolve(tag.asset_uuid)

    assert by_slot is not None
    assert by_slot.sovereign_id == cert.agent_uuid
    assert by_slot.did == cert.did
    assert by_tag is not None
    assert by_tag.slot_id == SURGEON_SLOT
    assert by_tag.sovereign_id == cert.agent_uuid


async def test_resolve_callsign_names_the_live_agent_and_nothing_else(
    registry: AgentIdentityRegistry, agents: AgentRegistry, callsigns: CallsignRegistry, service: IdentityService,
) -> None:
    """A callsign resolves to the ref of the live agent that holds it, and to None in every other case (kills M5, M6)."""
    await _issue(registry)
    await _issue(registry, COUNSELOR_SLOT, "counselor", "Ezri", "medical", "counselor")  # certified, but not live
    await _go_live(agents, SURGEON_SLOT, "surgeon")
    await _go_live(agents, SCOUT_SLOT, "scout")  # live, but it has no certificate or tag
    # premises: Meridian's agent is live and certified; Ezri has a profile and no live agent; Wesley's agent is live and unidentified
    surgeon_ref = service.resolve(SURGEON_SLOT)
    assert surgeon_ref is not None
    assert callsigns.resolve("Meridian")["agent_id"] == SURGEON_SLOT  # type: ignore[index]
    assert callsigns.resolve("Ezri")["agent_id"] is None  # type: ignore[index]
    assert callsigns.resolve("Wesley")["agent_id"] == SCOUT_SLOT  # type: ignore[index]
    assert registry.get_by_slot(SCOUT_SLOT) is None
    assert registry.get_asset_by_slot(SCOUT_SLOT) is None

    named = service.resolve_callsign("Meridian")
    folded = service.resolve_callsign("meridian")

    assert named is not None and folded is not None
    assert named == folded == surgeon_ref
    assert named.to_dict() == folded.to_dict() == surgeon_ref.to_dict()
    assert service.resolve_callsign("Ezri") is None  # a profile with no live agent
    assert service.resolve_callsign("Wesley") is None  # a live agent with no identity
    for callsign in ("Nobody", "", None, ["x"]):  # ``["x"]`` has no ``lower`` (kills M5)
        assert service.resolve_callsign(callsign) is None, callsign  # type: ignore[arg-type]


async def test_the_facade_reads_the_registries_live(
    registry: AgentIdentityRegistry, callsigns: CallsignRegistry, service: IdentityService,
) -> None:
    """The facade holds references: a certificate issued after it was built resolves, a renamed callsign is read (kills M9)."""
    assert service.resolve(SURGEON_SLOT) is None  # `service` was built before anything was issued

    cert = await _issue(registry)
    earlier = service.resolve(SURGEON_SLOT)
    assert earlier is not None
    assert earlier.callsign == "Meridian"

    callsigns.set_callsign("surgeon", "Zed")  # the naming ceremony (AD-442)
    later = service.resolve(SURGEON_SLOT)

    assert later is not None
    assert later.callsign == "Zed"
    assert cert.callsign == "Meridian"  # the certificate's callsign is a birth record; the live one is not
    assert later == earlier
    assert hash(later) == hash(earlier)


async def test_a_reused_slot_is_a_different_ref(
    registry: AgentIdentityRegistry, service: IdentityService,
) -> None:
    """A slot taken over by another identity gives a different ref, and the displaced identity resolves to nothing (D3; kills M13)."""
    surgeon = await _issue(registry)
    counselor = await _issue(registry, COUNSELOR_SLOT, "counselor", "Ezri", "medical", "counselor")
    before = service.resolve(SURGEON_SLOT)

    ok, _message = await registry.reassign_slot(counselor.agent_uuid, SURGEON_SLOT)
    assert ok is True
    after = service.resolve(SURGEON_SLOT)

    assert before is not None and after is not None
    assert before.slot_id == after.slot_id == SURGEON_SLOT
    assert before != after
    assert len({before, after}) == 2
    assert after.sovereign_id == counselor.agent_uuid
    assert service.resolve(surgeon.agent_uuid) is None  # bound to no slot now


# ---------------------------------------------------------------------------
# The value, its frozen form, and the facade's contract (T9 to T11)
# ---------------------------------------------------------------------------


def test_identity_ref_rejects_non_str_and_empty_identity() -> None:
    """A ref needs exact ``str`` fields and a non-empty slot id and sovereign id; the other three may be empty (kills M14, M15)."""
    fields = {"slot_id": "s", "sovereign_id": "u", "did": "d", "callsign": "c", "agent_type": "t"}
    IdentityRef(**fields)  # the baseline constructs
    IdentityRef(slot_id="s", sovereign_id="u", did="", callsign="", agent_type="")  # an asset's shape: only two are required

    with pytest.raises(TypeError, match="slot_id"):
        IdentityRef(**{**fields, "slot_id": _S("s")})  # a str subclass is not a str (kills M14)
    with pytest.raises(TypeError, match="did"):
        IdentityRef(**{**fields, "did": None})
    with pytest.raises(ValueError):
        IdentityRef(**{**fields, "slot_id": ""})
    with pytest.raises(ValueError):
        IdentityRef(**{**fields, "sovereign_id": ""})  # (kills M15)


async def test_identity_ref_v1_is_frozen(registry: AgentIdentityRegistry, service: IdentityService) -> None:
    """The v1 key set, order, types and equality of an ``IdentityRef`` (kills M12, M13, M16, M17).

    Changing any assertion here breaks AD-1346 M3's shadow records; add keys at the end only (D4).
    """
    cert = await _issue(registry)
    ref = service.resolve(SURGEON_SLOT)
    assert ref is not None

    assert IDENTITY_REF_KEYS == ("slot_id", "sovereign_id", "did", "callsign", "agent_type")
    assert [f.name for f in dataclasses.fields(IdentityRef)] == list(IDENTITY_REF_KEYS)
    assert [f.name for f in dataclasses.fields(IdentityRef) if f.compare] == ["slot_id", "sovereign_id"]

    form = ref.to_dict()
    assert list(form) == list(IDENTITY_REF_KEYS)
    assert form == {
        "slot_id": SURGEON_SLOT,
        "sovereign_id": cert.agent_uuid,
        "did": cert.did,
        "callsign": "Meridian",
        "agent_type": "surgeon",
    }
    assert all(type(value) is str for value in form.values())
    assert json.loads(json.dumps(form)) == form
    with pytest.raises(dataclasses.FrozenInstanceError):
        ref.slot_id = "x"  # type: ignore[misc]


async def test_the_facade_never_creates_or_changes_an_identity(
    registry: AgentIdentityRegistry, agents: AgentRegistry, callsigns: CallsignRegistry, service: IdentityService,
) -> None:
    """Every input of T3 to T6, through both methods, leaves the registries as they were; the facade is synchronous (kills M18)."""
    surgeon = await _issue(registry)
    counselor = await _issue(registry, COUNSELOR_SLOT, "counselor", "Ezri", "medical", "counselor")
    tag = await registry.resolve_or_issue_asset_tag(TOOL_SLOT, "calculator", "calculator")
    await _go_live(agents, SURGEON_SLOT, "surgeon")
    await _go_live(agents, SCOUT_SLOT, "scout")
    slots = (SURGEON_SLOT, COUNSELOR_SLOT, TOOL_SLOT, SCOUT_SLOT)
    resolve_inputs: list[Any] = [
        *slots, surgeon.agent_uuid, counselor.agent_uuid, surgeon.did, counselor.did, tag.asset_uuid,
        *_non_candidates(), "", None, 7, ["x"], b"x", "meridian",
    ]
    callsign_inputs: list[Any] = ["Meridian", "meridian", "Ezri", "Wesley", "Nobody", "", None, ["x"]]

    async def snapshot() -> dict[str, Any]:
        return {
            "certificates": [c.agent_uuid for c in registry.get_all()],
            "tags": [t.asset_uuid for t in registry.get_asset_tags()],
            "chain": await registry.export_chain(),
            "callsigns": callsigns.all_callsigns(),
            "slots": {s: copy.deepcopy(registry.get_by_slot(s)) for s in slots},  # a copy: an in-place change shows
        }

    before = await snapshot()
    resolved = [service.resolve(key) for key in resolve_inputs]
    named = [service.resolve_callsign(callsign) for callsign in callsign_inputs]
    after = await snapshot()

    assert after == before
    # premise: the calls reached the resolving paths, so "nothing changed" is not "nothing happened"
    assert len([ref for ref in resolved if ref is not None]) == 8  # three slots, two UUIDs, two DIDs, the tag UUID
    assert len([ref for ref in named if ref is not None]) == 2  # Meridian, in two cases
    assert inspect.iscoroutinefunction(IdentityService.resolve) is False
    assert inspect.iscoroutinefunction(IdentityService.resolve_callsign) is False
    with pytest.raises(TypeError):
        IdentityService(None, callsigns)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        IdentityService(registry, None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Structural guards over src/probos (T12, T13)
# ---------------------------------------------------------------------------


def test_only_the_facade_constructs_an_identity_ref_in_src() -> None:
    """The facade is the only constructor of an ``IdentityRef`` in ``src`` (D5), and the detector finds its two."""
    # the detector's premise: it counts both call shapes, and no mention, annotation or subclass
    probe = ast.parse(
        "a = IdentityRef('s', 'u', 'd', 'c', 't')\n"
        "b = identity_service.IdentityRef('s', 'u', 'd', 'c', 't')\n"
        "def f(x: IdentityRef) -> IdentityRef | None: return isinstance(x, IdentityRef)\n"
        "class Sub(IdentityRef): pass\n"
    )
    assert _identity_ref_calls(probe) == 2

    constructions: dict[str, int] = {}
    for path in sorted(_SRC.rglob("*.py")):
        count = _identity_ref_calls(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        if count:
            constructions[path.relative_to(_SRC.parent).as_posix()] = count

    # exactly the two constructions in the facade (the cert and the tag), which also proves the detector finds real ones
    assert constructions == {"probos/identity_service.py": 2}


def test_the_facade_imports_no_resolution_logic() -> None:
    """The facade imports the standard library at runtime and the two registries for typing only, none of the logic (D9)."""
    tree = ast.parse((_SRC / "identity_service.py").read_text(encoding="utf-8"))
    guarded = [
        statement
        for node in tree.body
        if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING"
        for statement in node.body
    ]

    assert _module_names(tree.body) == {"__future__", "dataclasses", "typing"}
    assert _module_names(guarded) == {"probos.crew_profile", "probos.identity"}
    # no import hides in a function body, and none brings parse_did, re or is_sovereign_identity_key in
    every = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
    assert _module_names(every) == {"__future__", "dataclasses", "typing", "probos.crew_profile", "probos.identity"}
    imported = {alias.name for node in every for alias in node.names}
    assert not imported & {"parse_did", "re", "is_sovereign_identity_key"}
