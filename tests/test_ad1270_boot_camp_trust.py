"""AD-1270 (#1324) slice 4b, M1: the AD-638 boot camp and /conn read trust through the real TrustNetwork.

TrustNetwork had ``get_score`` only, while ``protocols.TrustNetworkProtocol`` and the
coordinator's own protocol declare ``get_trust_score``; every earlier test mocked the
missing method. Nothing here mocks it: each case uses a real ``TrustNetwork``.
"""

from __future__ import annotations

import ast
import io
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from rich.console import Console

from probos.boot_camp import BootCampCoordinator
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.sub_task import SubTaskChain, SubTaskResult, SubTaskSpec, SubTaskType
from probos.config import BootCampConfig, ChainTuningConfig, SystemConfig
from probos.conn import ConnManager
from probos.consensus.trust import TrustNetwork
from probos.events import EventType
from probos.experience.commands import commands_autonomous
from probos.protocols import TrustNetworkProtocol
from probos.runtime import ProbOSRuntime

_SRC = Path(__file__).resolve().parents[1] / "src" / "probos"

CHIEF = {"agent_id": "chief-1", "callsign": "Worf", "department": "security"}
CREW = {"agent_id": "crew-1", "callsign": "Wesley", "department": "science"}


class _Episodes:
    """The coordinator's episode-count collaborator (not under repair)."""

    def __init__(self, count: int) -> None:
        self.count = count

    async def count_for_agent(self, agent_id: str) -> int:
        return self.count


def _coordinator(trust: TrustNetwork, *, events: list | None = None, **config: object) -> BootCampCoordinator:
    settings = {"min_time_minutes": 0, "nudge_cooldown_seconds": 0, **config}
    sink = events if events is not None else []
    return BootCampCoordinator(
        config=BootCampConfig(**settings),
        ward_room=SimpleNamespace(),
        trust_service=trust,
        episodic_memory=_Episodes(10),
        emit_event_fn=lambda event_type, data: sink.append((event_type, data)),
    )


# --- the method under repair -------------------------------------------------------------


def test_trust_network_satisfies_the_trust_protocol() -> None:
    """AD-514's runtime-checkable protocol; closes the gap test_ad702 recorded."""
    assert isinstance(TrustNetwork(), TrustNetworkProtocol)


@pytest.mark.parametrize("alpha_beta", [None, (3.0, 1.0)], ids=["unknown-agent", "recorded-agent"])
def test_get_trust_score_is_get_score(alpha_beta: tuple[float, float] | None) -> None:
    trust = TrustNetwork()
    if alpha_beta is not None:
        trust.create_with_prior("agent-x", *alpha_beta)

    assert trust.get_trust_score("agent-x") == trust.get_score("agent-x")
    assert trust.get_trust_score("agent-x") == pytest.approx(0.5 if alpha_beta is None else 0.75)


def test_get_trust_score_follows_a_patched_get_score(monkeypatch: pytest.MonkeyPatch) -> None:
    """Delegation by call, not a class alias: a patched get_score governs both reads."""
    trust = TrustNetwork()
    monkeypatch.setattr(trust, "get_score", lambda agent_id: 0.123)

    assert trust.get_trust_score("anyone") == 0.123


# --- the boot camp through the real trust network ----------------------------------------


@pytest.mark.asyncio
async def test_activate_with_the_real_trust_network_enrols_crew_and_skips_chiefs() -> None:
    trust = TrustNetwork()
    trust.create_with_prior(CHIEF["agent_id"], 3.0, 1.0)  # 0.75, the AD-640 chief tier
    events: list = []
    coord = _coordinator(trust, events=events)

    await coord.activate([CHIEF, CREW])

    assert coord.is_enrolled(CREW["agent_id"])
    assert not coord.is_enrolled(CHIEF["agent_id"])  # AD-640: 0.75 >= min_trust_score 0.55
    assert [event_type for event_type, _ in events] == [EventType.BOOT_CAMP_ACTIVATED]


@pytest.mark.asyncio
async def test_graduation_reads_the_real_trust_network() -> None:
    trust = TrustNetwork()
    events: list = []
    coord = _coordinator(trust, events=events)
    await coord.activate([CREW])
    crew = CREW["agent_id"]
    for _ in range(3):
        await coord.on_agent_post(crew, "department")
    await coord.on_agent_dm(crew)

    assert coord.is_enrolled(crew)  # every criterion met except trust: 0.5 < 0.55

    trust.create_with_prior(crew, 3.0, 2.0)  # 0.6
    await coord.on_agent_post(crew, "department")

    assert not coord.is_enrolled(crew)
    graduations = [data for event_type, data in events if event_type == EventType.BOOT_CAMP_GRADUATION]
    assert [g["agent_id"] for g in graduations] == [crew]
    assert graduations[0]["trust_score"] == pytest.approx(0.6)


# --- /conn through the real trust network ------------------------------------------------


def _conn_host(trust: TrustNetwork) -> SimpleNamespace:
    """A runtime stand-in carrying the real ProbOSRuntime.is_conn_qualified (BF-708 pattern)."""
    chief = SimpleNamespace(id="security_officer-0", agent_type="security_officer", callsign="Worf")
    junior = SimpleNamespace(id="engineering_officer-0", agent_type="engineering_officer", callsign="Reed")
    agents = {agent.id: agent for agent in (chief, junior)}
    posts = {  # both hold conn-eligible posts: only trust tells them apart
        "security_officer": SimpleNamespace(id="chief_security"),
        "engineering_officer": SimpleNamespace(id="chief_engineer"),
    }
    host = SimpleNamespace(
        registry=SimpleNamespace(get=agents.get, all=lambda: list(agents.values())),
        trust_network=trust,
        ontology=SimpleNamespace(get_post_for_agent=posts.get),
        conn_manager=ConnManager(),
        ward_room=None,
    )
    host.is_conn_qualified = types.MethodType(ProbOSRuntime.is_conn_qualified, host)
    return host


@pytest.mark.asyncio
async def test_conn_goes_to_a_qualified_chief_through_the_real_trust_network() -> None:
    trust = TrustNetwork()
    trust.create_with_prior("security_officer-0", 9.0, 1.0)  # 0.9: Senior
    host = _conn_host(trust)
    out = io.StringIO()

    await commands_autonomous.cmd_conn(host, Console(file=out, width=200), "Worf")

    assert host.conn_manager.is_active
    assert host.conn_manager.holder == "Worf"
    assert "has the conn" in out.getvalue()


@pytest.mark.asyncio
async def test_conn_is_refused_below_commander() -> None:
    host = _conn_host(TrustNetwork())  # Reed reads the 0.5 prior: Lieutenant
    out = io.StringIO()

    await commands_autonomous.cmd_conn(host, Console(file=out, width=200), "Reed")

    assert not host.conn_manager.is_active
    assert "not qualified" in out.getvalue()


# --- the relaxation flag ------------------------------------------------------------------


def test_the_relaxation_is_off_by_default() -> None:
    assert BootCampConfig().relax_quality_gates is False
    assert SystemConfig().boot_camp.relax_quality_gates is False


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", [False, True], ids=["off", "on"])
async def test_an_enrolled_agent_relaxes_only_when_the_flag_is_on(flag: bool) -> None:
    coord = _coordinator(TrustNetwork(), relax_quality_gates=flag)
    await coord.activate([CREW])

    assert coord.is_enrolled(CREW["agent_id"])
    assert coord.relaxes_quality_gates(CREW["agent_id"]) is flag


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["unknown", "graduated"])
async def test_an_agent_not_enrolled_never_relaxes(case: str) -> None:
    coord = _coordinator(TrustNetwork(), relax_quality_gates=True)
    await coord.activate([CREW])
    agent_id = CREW["agent_id"]
    if case == "unknown":
        agent_id = "not-enrolled"
    else:
        await coord.force_graduate_all()

    assert coord.relaxes_quality_gates(agent_id) is False


def _chain_agent(coord: BootCampCoordinator) -> CognitiveAgent:
    """The AD-632g harness (tests/test_ad632g_cognitive_jit_integration.py:212-223), real coordinator."""
    agent = CognitiveAgent.__new__(CognitiveAgent)
    agent.id = CREW["agent_id"]
    agent.agent_type = "test_agent"
    agent._sub_task_executor = MagicMock()
    agent._sub_task_executor.enabled = True
    agent._sub_task_executor.execute = AsyncMock(return_value=[SubTaskResult(
        sub_task_type=SubTaskType.COMPOSE, name="compose", success=True,
        result={"output": "Hello"}, tier_used="standard",
    )])
    agent._runtime = MagicMock()
    agent._runtime.cognitive_journal = MagicMock()
    agent._runtime.boot_camp = coord
    agent._runtime.config.chain_tuning = ChainTuningConfig(enabled=False)
    return agent


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", [False, True], ids=["off", "on"])
async def test_the_chain_marks_boot_camp_only_when_the_relaxation_is_on(flag: bool) -> None:
    settings = {"relax_quality_gates": True} if flag else {}  # off uses the model default
    coord = _coordinator(TrustNetwork(), **settings)
    await coord.activate([CREW])
    observation: dict = {"intent": "ward_room_notification"}
    chain = SubTaskChain(steps=[SubTaskSpec(sub_task_type=SubTaskType.COMPOSE, name="compose")])

    await _chain_agent(coord)._execute_sub_task_chain(chain, observation)

    assert observation.get("_boot_camp_active") is (True if flag else None)


def _attribute_calls(node: ast.AST) -> list[str]:
    return [
        call.func.attr
        for call in ast.walk(node)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
    ]


# A2 (AD-1270, #1324): every method that executes a sub-task chain is classified here. A gating
# phase can run Evaluate or Reflect and must ask again through the one producer; a lookup runs
# QUERY steps only. A new chain-executing method fails this test until it is classified.
_GATING_PHASES = {"_execute_sub_task_chain", "_execute_chain_with_intent_routing", "_re_reflect_with_feedback"}
_LOOKUP_PHASES = {"_maybe_dispatch_oracle_lookup", "_maybe_dispatch_ward_room_lookup"}


def _executes_a_chain(node: ast.AST) -> bool:
    return any(
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "execute"
        and isinstance(call.func.value, ast.Attribute)
        and call.func.value.attr == "_sub_task_executor"
        for call in ast.walk(node)
    )


def _step_kinds(node: ast.AST) -> set[str]:
    return {
        keyword.value.attr
        for call in ast.walk(node)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "SubTaskSpec"
        for keyword in call.keywords
        if keyword.arg == "sub_task_type" and isinstance(keyword.value, ast.Attribute)
    }


def test_every_gating_chain_phase_asks_for_the_relaxation_not_enrolment() -> None:
    tree = ast.parse((_SRC / "cognitive" / "cognitive_agent.py").read_bytes())
    functions = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    methods = {node.name: node for node in functions}

    assert {node.name for node in functions if _executes_a_chain(node)} == _GATING_PHASES | _LOOKUP_PHASES
    for name in _GATING_PHASES:
        assert "_refresh_boot_camp_relaxation" in _attribute_calls(methods[name]), name
    for name in _LOOKUP_PHASES:
        assert _step_kinds(methods[name]) == {"QUERY"}, name
    assert "relaxes_quality_gates" in _attribute_calls(methods["_refresh_boot_camp_relaxation"])
    assert "is_enrolled" not in _attribute_calls(tree)
