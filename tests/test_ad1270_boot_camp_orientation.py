"""AD-1270 (#1324) slice 4c, M2: AD-638's uncalled phases 2 and 3 are deleted, and an enrolled
agent's Captain DM carries the AD-683 cold-start snapshot.

The snapshot was keyed on ``_boot_camp_active``, which only a chain phase sets (through
``_refresh_boot_camp_relaxation``, while ``relax_quality_gates`` is on), and ``direct_message``
is not a chain intent: with the flag off it reached no prompt, and with it on only after a chain
fell through to the single call, on that chain's last answer. It is keyed on enrolment now and
read through the coordinator, whose ``is_enrolled`` enforces the timeout. BF-261's late-bind goes
through a finalization helper and a public setter. Time comes from an injected clock, trust from
a real TrustNetwork.
"""

from __future__ import annotations

import ast
import inspect
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from probos.boot_camp import AgentBootCampState, BootCampCoordinator
from probos.config import BootCampConfig, SystemConfig
from probos.consensus.trust import TrustNetwork
from probos.events import EventType
from probos.onboarding import ShipStateSnapshot
from probos.startup import finalize
from tests.fixtures.ad1028_golden._capture_golden import dm_observation, make_dm_agent

_REPO = Path(__file__).resolve().parents[1]
_SRC = _REPO / "src" / "probos"
_START = 1_000_000.0
_HEADER = "--- Ship State Snapshot (captured when boot camp began) ---"
_SNAPSHOT = ShipStateSnapshot(captured_at=_START, vessel_name="Enterprise", active_crew_count=3)
_FAILED = "render_text failed"


class _Clock:
    def __init__(self, now: float = _START) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class _Episodes:
    async def count_for_agent(self, agent_id: str) -> int:
        return 10


class _Builder:
    """A ShipStateSnapshotBuilder stand-in: ``build`` is the one method the coordinator calls."""

    def __init__(self, snapshot: ShipStateSnapshot) -> None:
        self.snapshot = snapshot
        self.builds = 0

    async def build(self) -> ShipStateSnapshot:
        self.builds += 1
        return self.snapshot


class _Unrenderable:
    def render_text(self) -> str:
        raise RuntimeError("render broke")


class _NewCrewStats:
    """The one episodic-memory read ``finalize._is_new_crew_start`` makes: an empty store."""

    async def get_stats(self) -> dict:
        return {"total": 0}


def _coordinator(
    clock: _Clock, *, events: list | None = None, relax: bool = False, **injected: object,
) -> BootCampCoordinator:
    sink = events if events is not None else []
    return BootCampCoordinator(
        config=BootCampConfig(min_time_minutes=0, timeout_minutes=120, relax_quality_gates=relax),
        trust_service=TrustNetwork(),
        episodic_memory=_Episodes(),
        emit_event_fn=lambda event_type, data: sink.append((event_type, data)),
        clock=clock,
        **injected,
    )


def _agent(boot_camp: object):
    """The AD-1028 DM rig with test_ad1227's runtime shape, plus ``boot_camp``."""
    agent = make_dm_agent()
    agent._runtime = SimpleNamespace(
        config=SystemConfig(), attachment_store=None, artifact_store=None, episodic_memory=None,
        work_item_store=None, chat_thread_store=None, ontology=None, registry=None,
        boot_camp=boot_camp,
    )
    return agent


def _crew(agent_id: str) -> list[dict[str, str]]:
    return [{"agent_id": agent_id, "callsign": "Tester", "department": "science"}]


# --- R6: the snapshot reaches an enrolled agent's DM ---------------------------------------


async def test_an_enrolled_agents_captain_dm_carries_the_snapshot() -> None:
    agent = _agent(None)
    coord = _coordinator(_Clock())
    assert coord.bind_ship_state_builder(_Builder(_SNAPSHOT)) is True
    await coord.activate(_crew(agent.id))
    agent._runtime.boot_camp = coord
    assert coord.is_enrolled(agent.id) and not coord.relaxes_quality_gates(agent.id)  # premise: flag off

    msg = await agent._build_user_message(dm_observation())

    assert _HEADER in msg
    assert _SNAPSHOT.render_text() in msg


async def test_the_snapshot_block_is_the_only_difference() -> None:
    baseline = await _agent(None)._build_user_message(dm_observation())
    agent = _agent(None)
    coord = _coordinator(_Clock())
    coord.bind_ship_state_builder(_Builder(_SNAPSHOT))
    await coord.activate(_crew(agent.id))
    agent._runtime.boot_camp = coord

    msg = await agent._build_user_message(dm_observation())

    assert msg == f"{_HEADER}\n{_SNAPSHOT.render_text()}\n---\n\n" + baseline


@pytest.mark.parametrize("case", ["not-enrolled", "graduated", "timed-out", "no-snapshot", "render-fails"])
async def test_no_block_unless_enrolled_with_a_snapshot(
    case: str, caplog: pytest.LogCaptureFixture,
) -> None:
    clock, agent = _Clock(), _agent(None)
    baseline = await agent._build_user_message(dm_observation())
    coord = _coordinator(clock)
    if case != "no-snapshot":
        coord.bind_ship_state_builder(_Builder(_SNAPSHOT))
    await coord.activate(_crew("someone-else" if case == "not-enrolled" else agent.id))
    if case == "graduated":
        await coord.force_graduate_all()
    if case == "timed-out":
        clock.now += 120 * 60
    if case == "render-fails":
        coord.ship_state_snapshot = _Unrenderable()
    if case in ("no-snapshot", "render-fails"):
        assert coord.is_enrolled(agent.id)  # premise: only the snapshot is missing or broken
    agent._runtime.boot_camp = coord

    with caplog.at_level(logging.DEBUG, logger="probos.boot_camp"):
        msg = await agent._build_user_message(dm_observation())

    assert msg == baseline
    failures = [r for r in caplog.records if _FAILED in r.getMessage()]
    assert len(failures) == (1 if case == "render-fails" else 0)


async def test_a_non_text_answer_from_the_runtime_adds_nothing() -> None:
    """A rig that gives an agent a MagicMock runtime gets a MagicMock back from any boot_camp
    call; the prompt builder must add nothing rather than fail the join. Passes on the base too."""
    baseline = await _agent(None)._build_user_message(dm_observation())
    agent = _agent(SimpleNamespace(orientation_snapshot_text=lambda agent_id: object()))

    assert await agent._build_user_message(dm_observation()) == baseline


def _stale_dm() -> dict:
    """A DM observation still carrying an earlier chain phase's relaxation answer."""
    return {**dm_observation(), "_boot_camp_active": True}


async def test_a_stale_relaxation_marker_adds_no_snapshot() -> None:
    """4b-R6, A2: the DM branch read the observation's ``_boot_camp_active``, so a chain that fell
    through to the single call carried its last phase's answer into the prompt. It reads the
    coordinator now: a marker left by a relaxation that has since ended adds nothing."""
    clock, agent = _Clock(), _agent(None)
    baseline = await agent._build_user_message(_stale_dm())
    coord = _coordinator(clock, relax=True)
    coord.bind_ship_state_builder(_Builder(_SNAPSHOT))
    await coord.activate(_crew(agent.id))
    assert coord.relaxes_quality_gates(agent.id)  # premise: the flag is on and the agent was relaxed
    clock.now += 120 * 60
    agent._runtime.boot_camp = coord

    msg = await agent._build_user_message(_stale_dm())

    assert msg == baseline
    assert "Ship State Snapshot" not in msg


@pytest.mark.parametrize("snapshot", [True, False], ids=["with-snapshot", "without-snapshot"])
async def test_the_dm_read_ends_an_expired_boot_camp(snapshot: bool) -> None:
    """``orientation_snapshot_text`` asks ``is_enrolled`` first, so past the timeout the DM build is
    an expiring reader like the others (4b's D4): it emits the one BOOT_CAMP_TIMEOUT and adds no
    block, with or without a captured snapshot."""
    clock, events, agent = _Clock(), [], _agent(None)
    baseline = await agent._build_user_message(dm_observation())
    coord = _coordinator(clock, events=events)
    if snapshot:
        coord.bind_ship_state_builder(_Builder(_SNAPSHOT))
    await coord.activate(_crew(agent.id))
    agent._runtime.boot_camp = coord
    clock.now += 120 * 60
    assert [event_type for event_type, _ in events] == [EventType.BOOT_CAMP_ACTIVATED]  # premise: no read yet

    msg = await agent._build_user_message(dm_observation())

    assert msg == baseline
    assert [event_type for event_type, _ in events] == [EventType.BOOT_CAMP_ACTIVATED, EventType.BOOT_CAMP_TIMEOUT]
    assert coord.get_state(agent.id).graduated


def test_the_dm_snapshot_is_the_one_enrolment_read_in_the_prompt_builder() -> None:
    """A guard in the manner of 4b's chain census: cognitive_agent.py reads enrolment once, through
    ``orientation_snapshot_text`` in ``_build_user_message``, and the prompt builder no longer reads
    the per-phase ``_boot_camp_active`` marker or the coordinator's snapshot attribute."""
    tree = ast.parse((_SRC / "cognitive" / "cognitive_agent.py").read_bytes())
    functions = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    builders = [n for n in functions if n.name == "_build_user_message"]
    assert len(builders) == 1  # premise
    constants = {n.value for n in ast.walk(builders[0]) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    attributes = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}

    assert sorted(n.name for n in functions if _call_lines(n, "orientation_snapshot_text")) == ["_build_user_message"]
    assert "boot_snapshot" in constants  # premise: the scan sees the bid's label
    assert "_boot_camp_active" not in constants
    assert "ship_state_snapshot" not in constants | attributes


# --- BF-261: the late-bind goes through the public setter -----------------------------------


async def test_bind_ship_state_builder_never_replaces_an_injected_builder() -> None:
    injected, late = _Builder(_SNAPSHOT), _Builder(_SNAPSHOT)
    owned = _coordinator(_Clock(), ship_state_builder=injected)
    assert owned.bind_ship_state_builder(late) is False
    await owned.activate(_crew("crew-1"))
    assert (injected.builds, late.builds) == (1, 0)

    unbound = _coordinator(_Clock())
    assert unbound.bind_ship_state_builder(None) is False
    assert unbound.bind_ship_state_builder(late) is True
    assert unbound.bind_ship_state_builder(injected) is False
    await unbound.activate(_crew("crew-1"))
    assert (injected.builds, late.builds) == (1, 1)
    assert unbound.ship_state_snapshot is _SNAPSHOT


def _call_lines(body: ast.AST, name: str) -> list[int]:
    return sorted(
        node.lineno for node in ast.walk(body)
        if isinstance(node, ast.Call) and (
            (isinstance(node.func, ast.Name) and node.func.id == name)
            or (isinstance(node.func, ast.Attribute) and node.func.attr == name)
        )
    )


def test_finalization_late_binds_through_the_public_setter() -> None:
    tree = ast.parse((_SRC / "startup" / "finalize.py").read_bytes())
    body = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "finalize_startup")
    helper = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_late_bind_boot_camp_snapshot")
    private = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == "_ship_state_builder"]
    snapshots = _call_lines(body, "_wire_ship_state_snapshot")
    binds = _call_lines(body, "_late_bind_boot_camp_snapshot")
    activations = _call_lines(body, "_activate_boot_camp_on_cold_start")

    assert private == []
    assert (len(snapshots), len(binds), len(activations)) == (1, 1, 1)
    assert snapshots[0] < binds[0] < activations[0]
    assert len(_call_lines(helper, "bind_ship_state_builder")) == 1


async def test_finalization_late_bind_reaches_an_enrolled_agents_dm() -> None:
    """4b-R13: the AST case above pins where the late-bind sits; this one pins what it does.
    Finalization's helper binds the builder, the activation that follows captures through it, and
    the capture is what an enrolled agent's DM shows. Without the bind, nothing."""
    shown: dict[bool, bool] = {}
    for bound in (True, False):
        late, agent = _Builder(_SNAPSHOT), _agent(None)
        coord = _coordinator(_Clock())  # Phase 7 injected no builder: runtime.ship_state_snapshot did not exist
        member = SimpleNamespace(id=agent.id, agent_type="security_officer", callsign="Tester", department="security")
        runtime = SimpleNamespace(
            boot_camp=coord, ship_state_snapshot=late, ontology=None, is_cold_start=False,
            _lifecycle_state="first_boot", episodic_memory=_NewCrewStats(),
            registry=SimpleNamespace(all=lambda member=member: [member]),
        )
        if bound:
            assert finalize._late_bind_boot_camp_snapshot(runtime=runtime) is True
        assert await finalize._activate_boot_camp_on_cold_start(runtime=runtime) is True
        assert late.builds == (1 if bound else 0)
        agent._runtime.boot_camp = coord
        shown[bound] = _HEADER in await agent._build_user_message(dm_observation())

    assert shown == {True: True, False: False}
    no_coordinator = SimpleNamespace(boot_camp=None, ship_state_snapshot=_Builder(_SNAPSHOT))
    assert finalize._late_bind_boot_camp_snapshot(runtime=no_coordinator) is False


# --- R5: phases 2 and 3 are gone ------------------------------------------------------------


def test_the_counselor_voiced_phases_are_gone() -> None:
    for name in ("run_phase_2_introductions", "run_phase_3_observation", "_can_nudge", "_record_nudge"):
        assert not hasattr(BootCampCoordinator, name), name
    assert "trust_service" in inspect.signature(BootCampCoordinator).parameters  # premise
    assert "ward_room" not in inspect.signature(BootCampCoordinator).parameters
    assert "timeout_minutes" in BootCampConfig.model_fields  # premise
    assert "nudge_cooldown_seconds" not in BootCampConfig.model_fields
    fields = set(AgentBootCampState.__dataclass_fields__)
    assert {"ward_room_posts", "dm_conversations", "phase"} <= fields  # premise
    assert fields.isdisjoint({"introduced_to_chief", "cross_dept_contact", "shared_observation", "notebook_started"})


def test_the_phase_advance_event_type_is_gone() -> None:
    assert {"BOOT_CAMP_ACTIVATED", "BOOT_CAMP_GRADUATION", "BOOT_CAMP_TIMEOUT"} <= set(EventType.__members__)
    assert "BOOT_CAMP_PHASE_ADVANCE" not in EventType.__members__
    assert "boot_camp_phase_advance" not in {member.value for member in EventType}


async def test_a_lifecycle_goes_from_enrolled_to_graduated_with_no_phase_between() -> None:
    clock, events = _Clock(), []
    coord = _coordinator(clock, events=events)
    await coord.activate(_crew("crew-1"))
    assert coord.get_state("crew-1").phase == 1

    clock.now += 120 * 60

    assert not coord.is_enrolled("crew-1")
    assert coord.get_state("crew-1").phase == 4
    assert [event_type for event_type, _ in events] == [EventType.BOOT_CAMP_ACTIVATED, EventType.BOOT_CAMP_TIMEOUT]


def test_a_config_that_still_sets_nudge_cooldown_seconds_loads() -> None:
    cfg = SystemConfig.model_validate({"boot_camp": {"nudge_cooldown_seconds": 600, "timeout_minutes": 90}})

    assert cfg.boot_camp.timeout_minutes == 90  # the section was read
    assert "nudge_cooldown_seconds" not in cfg.boot_camp.model_dump()


def test_the_tracked_yaml_carries_no_nudge_key() -> None:
    boot_camp = yaml.safe_load((_REPO / "config" / "system.yaml").read_text(encoding="utf-8"))["boot_camp"]

    assert boot_camp["timeout_minutes"] == 120  # premise: this is the boot_camp section
    assert "nudge_cooldown_seconds" not in boot_camp


def test_every_boot_camp_field_is_described() -> None:
    """4b-R12: each BootCampConfig field carries a description, so its generated reference row is
    not blank, and the relaxation's says whose switch it is."""
    fields = BootCampConfig.model_fields
    assert list(fields) == [
        "enabled", "min_episodes", "min_ward_room_posts", "min_dm_conversations",
        "min_trust_score", "min_time_minutes", "timeout_minutes", "relax_quality_gates",
    ]  # premise: the field set after this slice
    assert [name for name, field in fields.items() if not (field.description or "").strip()] == []
    assert "Captain" in fields["relax_quality_gates"].description

    reference = (_REPO / "docs" / "development" / "config-reference.md").read_text(encoding="utf-8")
    section = reference.split("## `boot_camp`\n", 1)[1].split("\n## ", 1)[0]
    rows = [line for line in section.splitlines() if line.startswith("| `")]
    assert len(rows) == len(fields)
    assert [line for line in rows if line.rstrip().endswith("|  |")] == []
