"""AD-1270 (#1324) slice 4b, M2: the AD-638 boot camp activates, counts DMs and times out.

Activation moved from startup/dreaming.py (Phase 5, before the coordinator exists) into
finalization, for a new crew (Amendment A1: no session record and no episodes). ``is_active``,
``is_enrolled``, ``check_graduation``, ``on_agent_post``, ``on_agent_dm`` and ``check_timeout``
enforce the timeout, with no task, and ``relaxes_quality_gates`` does when its flag is on;
``get_state`` returns raw state. A crew DM sent through the proactive path counts. Time comes
from an injected clock, trust from a real TrustNetwork.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from probos.boot_camp import BootCampCoordinator
from probos.cognitive.dm_sanity_gate import DmSanityGate
from probos.config import BootCampConfig, SystemConfig
from probos.consensus.trust import TrustNetwork
from probos.crew_profile import CallsignRegistry
from probos.events import EventType
from probos.proactive import ProactiveCognitiveLoop
from probos.startup.finalize import _activate_boot_camp_on_cold_start
from probos.substrate.identity import generate_pool_ids
from probos.substrate.registry import AgentRegistry
from probos.ward_room.service import WardRoomService

_SRC = Path(__file__).resolve().parents[1] / "src" / "probos"
_START = 1_000_000.0
_TIMEOUT_S = 120 * 60

CREW = {"agent_id": "crew-1", "callsign": "Wesley", "department": "science"}
CHIEF = {"agent_id": "chief-1", "callsign": "Worf", "department": "security"}


class _Clock:
    def __init__(self, now: float = _START) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class _Episodes:
    def __init__(self, count: int) -> None:
        self.count = count

    async def count_for_agent(self, agent_id: str) -> int:
        return self.count


def _coordinator(
    trust: TrustNetwork,
    clock: _Clock,
    *,
    events: list | None = None,
    **config: object,
) -> BootCampCoordinator:
    # AD-1270 (#1324) slice 4c: the coordinator has no nudge cooldown and no ward-room dependency.
    settings = {"min_time_minutes": 0, "timeout_minutes": 120, **config}
    sink = events if events is not None else []
    return BootCampCoordinator(
        config=BootCampConfig(**settings),
        trust_service=trust,
        episodic_memory=_Episodes(10),
        emit_event_fn=lambda event_type, data: sink.append((event_type, data)),
        clock=clock,
    )


async def _enrolled(clock: _Clock, **config: object) -> BootCampCoordinator:
    coord = _coordinator(TrustNetwork(), clock, **config)
    await coord.activate([CREW])
    return coord


# --- the timeout, by construction ---------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("offset", "enrolled"), [(_TIMEOUT_S - 1, True), (_TIMEOUT_S, False)], ids=["just-before", "at"])
async def test_nobody_is_enrolled_past_the_timeout(offset: float, enrolled: bool) -> None:
    clock = _Clock()
    coord = await _enrolled(clock)
    clock.now = _START + offset

    assert coord.is_enrolled(CREW["agent_id"]) is enrolled
    state = coord.get_state(CREW["agent_id"])
    assert state.graduated is (not enrolled)
    if not enrolled:
        assert state.graduated_at == _START + offset
        assert state.phase == 4


@pytest.mark.asyncio
async def test_is_active_turns_false_at_the_timeout() -> None:
    clock = _Clock()
    coord = await _enrolled(clock)
    clock.now = _START + _TIMEOUT_S

    assert coord.is_active is False


@pytest.mark.asyncio
async def test_the_timeout_emits_one_event_and_graduates_the_rest() -> None:
    clock, events = _Clock(), []
    coord = _coordinator(TrustNetwork(), clock, events=events)
    await coord.activate([CREW, {"agent_id": "crew-2", "callsign": "Nog", "department": "operations"}])
    clock.now = _START + _TIMEOUT_S + 30

    for _ in range(3):
        assert not coord.is_enrolled(CREW["agent_id"])
    assert coord.is_active is False

    timeouts = [data for event_type, data in events if event_type == EventType.BOOT_CAMP_TIMEOUT]
    assert len(timeouts) == 1
    assert sorted(timeouts[0]["agent_ids"]) == ["crew-1", "crew-2"]
    assert timeouts[0]["duration_minutes"] == 120.5
    for agent_id in ("crew-1", "crew-2"):
        assert coord.get_state(agent_id).graduated_at == _START + _TIMEOUT_S + 30


@pytest.mark.asyncio
async def test_the_timeout_ends_the_relaxation() -> None:
    clock = _Clock()
    coord = await _enrolled(clock, relax_quality_gates=True)
    assert coord.relaxes_quality_gates(CREW["agent_id"])

    clock.now = _START + _TIMEOUT_S

    assert not coord.relaxes_quality_gates(CREW["agent_id"])


@pytest.mark.asyncio
async def test_the_timeout_changes_no_trust_record_and_forgets_nobody() -> None:
    trust = TrustNetwork()
    trust.create_with_prior(CREW["agent_id"], 2.0, 3.0)  # 0.4
    clock = _Clock()
    coord = _coordinator(trust, clock)
    await coord.activate([CREW])
    before = trust.get_record(CREW["agent_id"])
    alpha_beta = (before.alpha, before.beta)

    clock.now = _START + _TIMEOUT_S
    assert not coord.is_enrolled(CREW["agent_id"])

    after = trust.get_record(CREW["agent_id"])
    assert (after.alpha, after.beta) == alpha_beta
    assert coord.get_state(CREW["agent_id"]) is not None  # graduated, not deleted


@pytest.mark.asyncio
@pytest.mark.parametrize("activity", ["post", "dm"])
async def test_activity_past_the_timeout_is_not_counted(activity: str) -> None:
    clock = _Clock()
    coord = await _enrolled(clock)
    clock.now = _START + _TIMEOUT_S

    if activity == "post":
        await coord.on_agent_post(CREW["agent_id"], "department")
    else:
        await coord.on_agent_dm(CREW["agent_id"])

    state = coord.get_state(CREW["agent_id"])
    assert (state.ward_room_posts, state.dm_conversations) == (0, 0)
    assert state.graduated


@pytest.mark.asyncio
async def test_check_graduation_past_the_timeout_reports_graduated() -> None:
    clock = _Clock()
    coord = await _enrolled(clock)  # no posts or DMs: the criteria are not met
    clock.now = _START + _TIMEOUT_S

    assert await coord.check_graduation(CREW["agent_id"]) is True


@pytest.mark.asyncio
async def test_the_timeout_with_nobody_enrolled_ends_boot_camp() -> None:
    trust = TrustNetwork()
    trust.create_with_prior(CHIEF["agent_id"], 3.0, 1.0)
    clock, events = _Clock(), []
    coord = _coordinator(trust, clock, events=events)
    await coord.activate([CHIEF])  # AD-640 skips the only agent
    clock.now = _START + _TIMEOUT_S

    assert coord.is_active is False
    assert EventType.BOOT_CAMP_TIMEOUT not in [event_type for event_type, _ in events]


@pytest.mark.asyncio
async def test_reads_before_activation_are_safe() -> None:
    coord = _coordinator(TrustNetwork(), _Clock())

    assert coord.is_active is False
    assert coord.is_enrolled(CREW["agent_id"]) is False
    assert coord.relaxes_quality_gates(CREW["agent_id"]) is False


@pytest.mark.asyncio
async def test_check_timeout_still_ends_boot_camp() -> None:
    clock = _Clock()
    coord = await _enrolled(clock)
    clock.now = _START + _TIMEOUT_S

    await coord.check_timeout()

    assert coord.get_state(CREW["agent_id"]).graduated  # get_state reads without expiring


# --- the injected clock -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_graduation_waits_for_min_time_on_the_injected_clock() -> None:
    trust, clock = TrustNetwork(), _Clock()
    coord = _coordinator(trust, clock, min_time_minutes=60)
    await coord.activate([CREW])
    trust.create_with_prior(CREW["agent_id"], 3.0, 2.0)  # 0.6, after enrolment
    for _ in range(3):
        await coord.on_agent_post(CREW["agent_id"], "department")
    await coord.on_agent_dm(CREW["agent_id"])
    assert coord.is_enrolled(CREW["agent_id"])  # 0 of 60 minutes served

    clock.now = _START + 60 * 60

    assert await coord.check_graduation(CREW["agent_id"]) is True
    assert coord.get_state(CREW["agent_id"]).graduated_at == _START + 60 * 60


def test_the_coordinator_reads_time_only_through_its_clock() -> None:
    tree = ast.parse((_SRC / "boot_camp.py").read_bytes())
    coordinator = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "BootCampCoordinator")
    wall_reads = [
        call.lineno
        for call in ast.walk(coordinator)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr in {"time", "monotonic"}
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "time"
    ]

    assert wall_reads == []


# --- DMs through the real proactive path ---------------------------------------------------

_DM_CREW = (
    ("security_officer", "Worf", "security"),
    ("counselor", "Troi", "medical"),
)


def _crew_member(agent_type: str, callsign: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=generate_pool_ids(agent_type, agent_type, 1)[0], agent_type=agent_type,
        pool=agent_type, callsign=callsign, is_alive=True, capabilities=[],
    )


@pytest.fixture
async def dm_rig(tmp_path):
    """The BF-874 rig (tests/test_bf874_dm_callsign_and_fail_closed.py:65-98) with a real
    coordinator and a real TrustNetwork in place of ``boot_camp=None``."""
    ws = WardRoomService(db_path=str(tmp_path / "wr.db"))
    await ws.start()
    registry = AgentRegistry()
    agents = {callsign: _crew_member(agent_type, callsign) for agent_type, callsign, _ in _DM_CREW}
    for agent in agents.values():
        await registry.register(agent)
    callsigns = CallsignRegistry()
    for agent_type, callsign, _ in _DM_CREW:
        callsigns.set_callsign(agent_type, callsign)
    callsigns.bind_registry(registry)
    departments = {agent_type: dept for agent_type, _, dept in _DM_CREW}
    config = SystemConfig()
    config.communications.dm_min_rank = "ensign"
    trust, clock, events = TrustNetwork(), _Clock(), []
    coord = _coordinator(trust, clock, events=events, min_time_minutes=60)
    rt = SimpleNamespace(
        ward_room=ws, registry=registry, callsign_registry=callsigns,
        ontology=SimpleNamespace(get_agent_department=lambda t: departments.get(t)),
        config=config, trust_network=trust, ward_room_router=None,
        episodic_memory=None, hebbian_router=None, dispatcher=None, _records_store=None,
        working_memory=None, dm_sanity_gate=DmSanityGate(), skill_service=None,
        boot_camp=coord, emit_event=lambda *a, **k: None,
    )
    loop = ProactiveCognitiveLoop(cooldown=300.0)
    loop.set_runtime(rt)
    sender = agents["Worf"]  # 0.5 prior: below 0.55, so enrolled
    await coord.activate([{"agent_id": sender.id, "callsign": "Worf", "department": "security"}])
    yield SimpleNamespace(loop=loop, sender=sender, coord=coord, trust=trust, clock=clock, events=events)
    await ws.stop()


@pytest.mark.asyncio
async def test_a_crew_dm_through_the_proactive_path_is_counted(dm_rig) -> None:
    _, actions = await dm_rig.loop.extract_and_execute_dms(dm_rig.sender, "[DM @Troi] Reporting in for duty. [/DM]")

    assert [action["target_callsign"] for action in actions] == ["Troi"]
    assert dm_rig.coord.get_state(dm_rig.sender.id).dm_conversations == 1


@pytest.mark.asyncio
async def test_a_dm_to_the_captain_is_not_counted(dm_rig) -> None:
    _, actions = await dm_rig.loop.extract_and_execute_dms(dm_rig.sender, "[DM @Captain] Settling in well. [/DM]")

    assert [action["target_callsign"] for action in actions] == ["captain"]
    assert dm_rig.coord.get_state(dm_rig.sender.id).dm_conversations == 0


@pytest.mark.asyncio
async def test_an_unsent_dm_is_not_counted(dm_rig) -> None:
    _, actions = await dm_rig.loop.extract_and_execute_dms(dm_rig.sender, "[DM @Nobody] Hello there. [/DM]")

    assert actions == []
    assert dm_rig.coord.get_state(dm_rig.sender.id).dm_conversations == 0


@pytest.mark.asyncio
async def test_a_crew_agent_graduates_through_the_real_dm_path_and_real_trust(dm_rig) -> None:
    agent_id = dm_rig.sender.id
    for _ in range(3):
        await dm_rig.coord.on_agent_post(agent_id, "department")
    await dm_rig.loop.extract_and_execute_dms(dm_rig.sender, "[DM @Troi] First watch report. [/DM]")
    assert dm_rig.trust.get_record(agent_id) is None
    dm_rig.trust.create_with_prior(agent_id, 3.0, 2.0)  # 0.6: above min_trust_score
    assert dm_rig.coord.is_enrolled(agent_id)  # 0 of 60 minutes served

    dm_rig.clock.now = _START + 61 * 60
    await dm_rig.coord.on_agent_post(agent_id, "department")

    assert not dm_rig.coord.is_enrolled(agent_id)
    graduations = [data for event_type, data in dm_rig.events if event_type == EventType.BOOT_CAMP_GRADUATION]
    assert [g["agent_id"] for g in graduations] == [agent_id]
    assert dm_rig.coord.get_state(agent_id).graduated_at == _START + 61 * 60


# --- activation at finalization ------------------------------------------------------------

_FLEET = [
    SimpleNamespace(id="security_officer-0", agent_type="security_officer", callsign="Worf", department="security"),
    SimpleNamespace(id="file_reader-0", agent_type="file_reader", callsign="", department=""),
]


class _Stats:
    """The one episodic-memory read ``_is_new_crew_start`` makes."""

    def __init__(self, total: int) -> None:
        self.total = total

    async def get_stats(self) -> dict:
        return {"total": self.total}


def _startup_runtime(coord: BootCampCoordinator | None, *, new_crew: bool, agents: list) -> SimpleNamespace:
    # AD-1270 A1: is_cold_start is False, as production reports it whenever a coordinator exists
    # (register R10); a new crew is no session record (first_boot) and an empty episode store.
    return SimpleNamespace(
        boot_camp=coord, is_cold_start=False, ontology=None,
        _lifecycle_state="first_boot" if new_crew else "stasis_recovery", episodic_memory=_Stats(0),
        registry=SimpleNamespace(all=lambda: list(agents)),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("cold", [True, False], ids=["cold", "warm"])
async def test_cold_start_finalization_enrols_crew(cold: bool) -> None:
    coord = _coordinator(TrustNetwork(), _Clock())

    ran = await _activate_boot_camp_on_cold_start(runtime=_startup_runtime(coord, new_crew=cold, agents=_FLEET))

    assert ran is cold
    assert coord.is_enrolled("security_officer-0") is cold
    assert not coord.is_enrolled("file_reader-0")  # not crew (crew_utils.is_crew_agent)
    assert coord.is_active is cold


@pytest.mark.asyncio
async def test_no_coordinator_or_no_crew_means_no_activation() -> None:
    assert await _activate_boot_camp_on_cold_start(runtime=_startup_runtime(None, new_crew=True, agents=_FLEET)) is False

    coord = _coordinator(TrustNetwork(), _Clock())
    no_crew = _startup_runtime(coord, new_crew=True, agents=_FLEET[1:])
    assert await _activate_boot_camp_on_cold_start(runtime=no_crew) is False
    assert coord.is_active is False


def _named_calls(node: ast.AST, name: str) -> list[int]:
    return sorted(
        call.lineno
        for call in ast.walk(node)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == name
    )


def test_finalization_activates_the_boot_camp_after_the_snapshot_late_bind() -> None:
    tree = ast.parse((_SRC / "startup" / "finalize.py").read_bytes())
    body = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "finalize_startup")
    activations = _named_calls(body, "_activate_boot_camp_on_cold_start")
    snapshots = _named_calls(body, "_wire_ship_state_snapshot")

    assert len(activations) == 1 and len(snapshots) == 1
    assert activations[0] > snapshots[0]
    awaited = sorted(
        node.value.lineno
        for node in ast.walk(body)
        if isinstance(node, ast.Await) and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name) and node.value.func.id == "_activate_boot_camp_on_cold_start"
    )
    assert awaited == activations  # A1: awaited, not a coroutine left unawaited


def test_phase_5_no_longer_tries_to_activate_the_boot_camp() -> None:
    tree = ast.parse((_SRC / "startup" / "dreaming.py").read_bytes())

    assert [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == "boot_camp"] == []
