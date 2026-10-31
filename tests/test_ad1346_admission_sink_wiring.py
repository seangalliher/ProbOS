"""AD-1346 M3e1 (#1604), A2: the runtime hands itself to the shell, code-search and red team agents its factories build.

``ProbOSRuntime.create_pool`` hands the runtime to a shell or code-search pool made without a ``runtime`` keyword, as
``create_agent_fleet`` makes both, and ``ProbOSRuntime._spawn_red_team`` hands it to each red team agent. Those agents'
subprocess sink statements read the admission service from it. SW1 and SW2 drive both factories over a real
``IdentityService`` and ``AgentStopService`` under ``tmp_path`` and a ``TicketRegistry`` on a fixed clock.

- SW1  ``create_pool`` with no ``runtime`` keyword: outside a hold, each sink check of the shell pool's two initial
       members, of a member added later and of the code-search pool's two members counts one
       ``subprocess``/``ticket_missing``; the member of a shell pool made with a caller's runtime, which holds no
       service, counts none.
- SW2  ``_spawn_red_team``: outside a hold, each red team agent's re-run counts one ``subprocess``/``ticket_missing``.
- SW3  a code-search pool member's read floor (BF-758) reads the runtime ``create_pool`` hands it: with that runtime's
       ``security_infra.read_roots`` set, a search rooted outside them is refused and no launch is reached; the same
       search by an agent built with no runtime reaches its launch.

The test replaces asyncio's exec constructor, the shell agent's ``_run_sync``, the red team's ``_run_verify_sync`` and the
code-search module's ``_resolve_rg_binary``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

from probos.admission import AdmissionService
from probos.admission.tickets import TicketRegistry
from probos.agent_stop import AgentStopService
from probos.agents.code_search import CodeSearchAgent
from probos.agents.red_team import RedTeamAgent
from probos.agents.shell_command import ShellCommandAgent
from probos.config import PoolConfig, SecurityInfraConfig, SystemConfig
from probos.crew_profile import CallsignRegistry
from probos.identity import AgentIdentityRegistry
from probos.identity_service import IdentityService
from probos.runtime import ProbOSRuntime
from probos.substrate.pool import ResourcePool
from probos.substrate.registry import AgentRegistry
from probos.substrate.spawner import AgentSpawner
from probos.types import IntentMessage, IntentResult

INSTANCE_ID = "ad1346-m3e1-a2-ship"
VESSEL_NAME = "Ad1346m3e1a2"
COMMAND = "echo ad1346-m3e1-a2"
SHELL_ID = "ad1346-m3e1-a2-shell"
MISSING = ("subprocess", "ticket_missing")
_PLAN: dict[str, Any] = {"max_results": 5, "case_insensitive": False, "include_ignored": False, "glob": "", "pattern": "ad1346"}


class _Clock:
    """A fixed clock: no test in this file moves it."""

    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


class _Finished:
    """What the replaced exec constructor returns: a process that already ended with no match (exit 1, no output)."""

    returncode = 1

    async def communicate(self) -> tuple[bytes, bytes]:
        return b"", b""


class _EventLog:
    async def log(self, **kwargs: Any) -> None:
        return None


class _AgentRegistry:
    async def register(self, agent: Any) -> None:
        return None


class _CapabilityRegistry:
    def register(self, agent_id: str, capabilities: Any) -> None:
        return None


class _Gossip:
    def update_local(self, **kwargs: Any) -> None:
        return None


class _TrustNetwork:
    def get_or_create(self, agent_id: str) -> None:
        return None


class _PoolRuntime:
    """A runtime double for ``ProbOSRuntime.create_pool`` (after ``tests/test_ad1328_s2a_startup_and_doctor.py``'s): a
    real ``SystemConfig``, registry and spawner with the shell and code-search templates, and ``admission_service``."""

    def __init__(self, service: AdmissionService | None, read_roots: list[str] | None = None) -> None:
        self.config = SystemConfig(
            pools=PoolConfig(default_pool_size=2, min_pool_size=1, max_pool_size=3),
            security_infra=SecurityInfraConfig(read_roots=read_roots or []),
        )
        self.pools: dict[str, ResourcePool] = {}
        self.registry = AgentRegistry()
        self.spawner = AgentSpawner(self.registry)
        self.spawner.register_template("shell_command", ShellCommandAgent)
        self.spawner.register_template("code_search", CodeSearchAgent)
        self.acm = None
        self.ontology = None
        self.event_log = _EventLog()
        self.admission_service = service


class _RedTeamRuntime:
    """A runtime double for ``ProbOSRuntime._spawn_red_team``: a real ``SystemConfig``, stand-ins that accept and drop
    what it registers, and ``admission_service``; it has no ``command_policy_gate``."""

    def __init__(self, service: AdmissionService) -> None:
        self.config = SystemConfig()
        self.registry = _AgentRegistry()
        self.capability_registry = _CapabilityRegistry()
        self.gossip = _Gossip()
        self.trust_network = _TrustNetwork()
        self.event_log = _EventLog()
        self.red_team_agents: list[RedTeamAgent] = []
        self.admission_service = service


@pytest_asyncio.fixture
async def identity_registry(tmp_path: Path) -> AsyncIterator[AgentIdentityRegistry]:
    reg = AgentIdentityRegistry(data_dir=tmp_path / "identity")
    try:
        await reg.start()
        await reg.start(instance_id=INSTANCE_ID, vessel_name=VESSEL_NAME, version="1")
        yield reg
    finally:
        await reg.stop()


@pytest.fixture
def identities(tmp_path: Path, identity_registry: AgentIdentityRegistry) -> IdentityService:
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "surgeon.yaml").write_text("callsign: Meridian\n", encoding="utf-8")
    callsigns = CallsignRegistry()
    callsigns.load_from_profiles(str(profiles))
    callsigns.bind_registry(AgentRegistry())
    return IdentityService(identity_registry, callsigns)


@pytest_asyncio.fixture
async def stops(tmp_path: Path) -> AsyncIterator[AgentStopService]:
    record = AgentStopService(data_dir=tmp_path / "stops")
    await record.start()
    try:
        yield record
    finally:
        await record.stop()


@pytest.fixture
def tickets(stops: AgentStopService) -> TicketRegistry:
    return TicketRegistry(stops, max_depth=1, clock=_Clock())


@pytest.fixture
def launches(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace the shell agent's ``_run_sync`` and asyncio's exec constructor; what reached them, in order (the shell's
    command, or ``"exec"``)."""
    reached: list[str] = []

    def run_sync(self: ShellCommandAgent, command: str, deadline: float | None = None, slot: object = None) -> dict[str, Any]:
        reached.append(command)
        return {"success": True, "data": {"stdout": "", "stderr": "", "exit_code": 0}}

    async def no_exec(*args: Any, **kwargs: Any) -> _Finished:
        reached.append("exec")
        return _Finished()

    monkeypatch.setattr(ShellCommandAgent, "_run_sync", run_sync)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", no_exec)
    return reached


async def _stop_pools(runtime: _PoolRuntime) -> None:
    for pool in list(runtime.pools.values()):
        await pool.stop()


async def test_create_pool_hands_the_runtime_to_shell_and_code_search_members(
    identities: IdentityService, stops: AgentStopService, tickets: TicketRegistry, launches: list[str], tmp_path: Path,
) -> None:
    """SW1 (kills EX-10): each pooled member's sink check finds the runtime's service; a caller's runtime wins."""
    service = AdmissionService(identities, stops, tickets=tickets, loop=asyncio.get_running_loop())
    runtime, caller = _PoolRuntime(service), _PoolRuntime(None)
    try:
        shell_pool = await ProbOSRuntime.create_pool(runtime, "shell", "shell_command", target_size=2)
        await ProbOSRuntime.create_pool(runtime, "code_search", "code_search", target_size=2)
        await ProbOSRuntime.create_pool(runtime, "shell-caller", "shell_command", target_size=1, runtime=caller)
        added = await shell_pool.add_agent()
        shell = runtime.registry.get_by_pool("shell")
        search = runtime.registry.get_by_pool("code_search")
        own = runtime.registry.get_by_pool("shell-caller")
        assert (len(shell), len(search), len(own), added in {member.id for member in shell}) == (3, 2, 1, True)  # premise

        for member in [*shell, *own]:
            await member._run_command(COMMAND)
        for member in search:
            await member._search_rg("rg", dict(_PLAN), tmp_path)

        assert launches == [COMMAND] * 4 + ["exec"] * 2
        assert tickets.tally() == {MISSING: 5}
        assert service.failures == 0
    finally:
        await _stop_pools(runtime)


async def test_spawn_red_team_hands_the_runtime_to_each_agent(
    identities: IdentityService, stops: AgentStopService, tickets: TicketRegistry, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SW2 (kills EX-12): each red team agent's re-run check finds the runtime's service."""
    service = AdmissionService(identities, stops, tickets=tickets, loop=asyncio.get_running_loop())
    reruns: list[str] = []

    def rerun(command: str, env: Any, deadline: float | None = None, slot: Any = None) -> tuple[int, str]:
        reruns.append(command)
        return (0, "")

    monkeypatch.setattr(RedTeamAgent, "_run_verify_sync", staticmethod(rerun))
    runtime = _RedTeamRuntime(service)
    try:
        await ProbOSRuntime._spawn_red_team(runtime, 2)
        assert len(runtime.red_team_agents) == 2  # premise
        for agent in runtime.red_team_agents:
            intent = IntentMessage(intent="run_command", params={"command": COMMAND})
            claimed = IntentResult(
                intent_id=intent.id, agent_id=SHELL_ID, success=True, result={"exit_code": 0, "stdout": ""}, confidence=0.8,
            )
            await agent._verify_run_command(SHELL_ID, intent, claimed, intent.params)
        assert reruns == [COMMAND] * 2
        assert tickets.tally() == {MISSING: 2}
        assert service.failures == 0
    finally:
        for agent in runtime.red_team_agents:
            await agent.stop()


async def test_a_pooled_code_search_agent_applies_the_runtimes_read_roots(
    launches: list[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """SW3 (kills EX-11): the member's floor confines the search to the runtime's read roots; the control's does not."""
    monkeypatch.setattr("probos.agents.code_search._resolve_rg_binary", lambda: "rg")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    plan: dict[str, Any] = {"action": "search", "path": str(elsewhere), **_PLAN}
    runtime = _PoolRuntime(None, read_roots=[str(tmp_path / "allowed")])
    try:
        await ProbOSRuntime.create_pool(runtime, "code_search", "code_search", target_size=1)
        (member,) = runtime.registry.get_by_pool("code_search")
        assert await member.act(dict(plan)) == {"success": False, "error": "path is outside every readable root"}
        assert launches == []
        control = CodeSearchAgent(pool="ad1346-m3e1-a2", agent_id="ad1346-m3e1-a2-search")
        assert (await control.act(dict(plan)))["success"] is True
        assert launches == ["exec"]
    finally:
        await _stop_pools(runtime)
