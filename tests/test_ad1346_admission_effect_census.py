"""AD-1346 M3e1 (#1604): the sink set, the subprocess effect point's census, its sinks and its crossing test.

``tests/fixtures/ad1346_effect_census.py`` holds the census: BF-892's launch scan by (file, enclosing function), each row
covered by a subprocess sink, a system principal, the operator's command line, or a later slice. These tests check the
census against the code, and drive three of the five sinks over a real ``IdentityService`` and ``AgentStopService`` under
``tmp_path`` and a ``TicketRegistry`` on a fixed clock.

- EC1  the effect ``subprocess`` is a ``TICKET_EFFECTS`` member and not a seam, and ``ticket_findings``' per-day bound
       is 1,248 rows, 43,680 over 35 days, below ``AGGREGATE_ROW_LIMIT``.
- EC2  every (file, function) of BF-892's scan is a row with its launch count, and every row is one; the census holds
       7 sink, 16 system, 5 command-line and 11 pending launches, the pending ones M3e2's.
- EC3  each sink function holds one ``check_at`` call, a statement of its own, with the runtime's service, the effect
       ``EFFECT_SUBPROCESS`` and the row's presented id, on a line before its launch or its reference to the launching
       function.
- EC4  a sink whose launch is in another function: in its file, that function's name is referenced only in the sink's
       function and its own.
- EC5  ``SYSTEM_PRINCIPALS`` is the set of the system rows' principals and the ``system:`` literals a seam statement
       presents, each admitted by ``check_principal``.
- EC6  each command-line row is in a module under ``OUTSIDE_RUNTIME``, and no other ``src`` module imports one by an
       absolute import.
- EC7  the sink set: five classes, and the delivered ones are the members of ``TICKET_EFFECTS``.
- EC8  the census helpers report an unlisted site, a stale row, a count, a reference, an import and a literal.
- EC9  #1604 property 1's crossing test for the subprocess class: inside the real run entry (its shadow statement and
       hold), the shell agent's launch counts ``ticket_live``, after a Captain's stop on the run's agent
       ``ticket_revoked``, and outside any hold ``ticket_missing``; each answer is the replaced launch's.
- EC10 #1604 property 12 at three sinks: the shell agent, the code search agent and ``run_command`` answer the
       same with the service and without it, with nothing carried, under a live ticket and after a Captain's stop.

The test replaces asyncio's two subprocess constructors and the shell agent's ``_run_sync``, so no process starts.
"""

from __future__ import annotations

import ast
import asyncio
import dataclasses
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio

from probos.admission import AdmissionService
from probos.admission.checks import Principal, check_principal
from probos.admission.store import AGGREGATE_RETENTION_DAYS, AGGREGATE_ROW_LIMIT
from probos.admission.taxonomy import (
    EFFECT_SUBPROCESS,
    PRINCIPAL_SYSTEM,
    SEAM_MODEL_CALL,
    SEAMS,
    SYSTEM_PRINCIPAL_PREFIX,
    SYSTEM_PRINCIPALS,
    TICKET_REASON_CODES,
    WORK_KINDS,
)
from probos.admission.tickets import TICKET_EFFECTS, TICKET_OPERATIONS, TicketRegistry
from probos.agent_stop import SEAM_TOOL, AgentStopService
from probos.agent_stop import SEAMS as STOP_SEAMS
from probos.agents.code_search import CodeSearchAgent
from probos.agents.shell_command import ShellCommandAgent
from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
from probos.cognitive.swe_harness.tools import RunCommandTool
from probos.crew_profile import CallsignRegistry
from probos.identity import AgentIdentityRegistry
from probos.identity_service import IdentityService
from probos.substrate.registry import AgentRegistry
from probos.tools.registry import ToolRegistry
from tests.fixtures.ad1343_seam_census import calls, function
from tests.fixtures.ad1346_effect_census import (
    DELIVERED,
    EFFECT_CLASSES,
    OUTSIDE_RUNTIME,
    SERVICE_EXPR,
    SHIP,
    SUBPROCESS_SITES,
    OutsideRuntime,
    Pending,
    Sink,
    System,
    census_problems,
    launch_counts,
    launch_lines,
    outside_importers,
    references_outside,
    src_sources,
    system_principal_literals,
)

INSTANCE_ID = "ad1346-m3e1-ship"
VESSEL_NAME = "Ad1346m3e1"
AGENT_A = "ad1346-m3e1-agent-a"
SHELL_ID = "ad1346-m3e1-shell"
SEARCH_ID = "ad1346-m3e1-search"
COMMAND = "echo ad1346-m3e1"
_SPAWNED: dict[str, Any] = {"success": True, "data": {"stdout": "ad1346-m3e1", "stderr": "", "exit_code": 0}}
_PLAN: dict[str, Any] = {"max_results": 5, "case_insensitive": False, "include_ignored": False, "glob": "", "pattern": "ad1346"}


class _Clock:
    """A fixed clock: no test in this file moves it."""

    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


class _ScriptedRun(WorkItemAgenticExecutor):
    """The real run entry (its stop check, shadow statement and hold) over a scripted body in place of the agentic loop."""

    def __init__(self, bodies: dict[str, Callable[[dict[str, Any]], Awaitable[str]]]) -> None:
        super().__init__(llm_client=None)
        self.bodies = bodies

    async def _run_reserved(self, **arguments: Any) -> Any:
        return await self.bodies[arguments["agent_id"]](arguments)


class _Finished:
    """What the replaced exec constructor returns: a process that already ended with no match (exit 1, no output)."""

    returncode = 1

    async def communicate(self) -> tuple[bytes, bytes]:
        return b"", b""


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


def _shell(service: AdmissionService | None) -> tuple[ShellCommandAgent, list[str]]:
    """A real shell agent whose runtime holds ``service``, with its blocking launch replaced by a recorder."""
    agent = ShellCommandAgent(pool="ad1346-m3e1", agent_id=SHELL_ID, runtime=SimpleNamespace(admission_service=service))
    spawned: list[str] = []

    def run_sync(command: str, deadline: float | None = None, slot: object = None) -> dict[str, Any]:
        spawned.append(command)
        return dict(_SPAWNED)

    agent._run_sync = run_sync  # type: ignore[method-assign]
    return agent, spawned


def _tools(stops: AgentStopService, service: AdmissionService) -> ToolRegistry:
    registry = ToolRegistry()
    registry.set_stop_gate(stops)
    registry.set_admission(service)
    return registry


def test_the_effect_vocabulary_holds_subprocess_and_the_finding_bound() -> None:
    """EC1 (D161; kills EX-1, EX-2)."""
    assert EFFECT_SUBPROCESS == "subprocess" and EFFECT_SUBPROCESS not in SEAMS
    assert SEAMS == STOP_SEAMS | {SEAM_MODEL_CALL}, "no seam is added, so the verdicts' per-day bounds do not move"
    assert TICKET_EFFECTS == (SEAM_TOOL, SEAM_MODEL_CALL, EFFECT_SUBPROCESS) == ("tool", "model_call", "subprocess")
    assert TICKET_OPERATIONS == ("issue", "tool", "model_call", "subprocess")
    one_day = len(TICKET_OPERATIONS) * len(TICKET_REASON_CODES) * (len(WORK_KINDS) + 1) * 2
    assert (one_day, one_day * AGGREGATE_RETENTION_DAYS) == (1_248, 43_680)
    assert one_day * AGGREGATE_RETENTION_DAYS < AGGREGATE_ROW_LIMIT


def test_every_launch_bf892_scans_is_a_row_and_every_row_a_launch() -> None:
    """EC2 (D162, D163): a new, removed or recounted launch site of BF-892's scan fails here."""
    found = launch_counts()
    assert census_problems(found, SUBPROCESS_SITES) == []
    by_kind = {
        kind: sum(count for count, cover in SUBPROCESS_SITES.values() if type(cover) is kind)
        for kind in (Sink, System, OutsideRuntime, Pending)
    }
    assert by_kind == {Sink: 7, System: 16, OutsideRuntime: 5, Pending: 11}, by_kind
    assert {cover.owner for _count, cover in SUBPROCESS_SITES.values() if type(cover) is Pending} == {"M3e2"}
    assert sum(found.values()) == 39


def test_each_subprocess_sink_holds_one_check_before_its_launch() -> None:
    """EC3 (D164, D165; kills EX-6, EX-8, EX-9)."""
    lines = launch_lines()
    for (path, scope), (_count, cover) in SUBPROCESS_SITES.items():
        if not isinstance(cover, Sink):
            continue
        fn = function(path, cover.check)
        checks = [node for node in ast.walk(fn) if calls("check_at")(node)]
        assert len(checks) == 1, (path, cover.check, len(checks))
        call = checks[0]
        assert [ast.unparse(arg) for arg in call.args] == [SERVICE_EXPR], (path, cover.check)
        keywords = {keyword.arg: ast.unparse(keyword.value) for keyword in call.keywords}
        assert keywords == {"effect": "EFFECT_SUBPROCESS", "presented_id": cover.presented}, (path, cover.check, keywords)
        assert any(isinstance(node, ast.Expr) and node.value is call for node in ast.walk(fn)), (path, cover.check)
        if cover.check == scope:
            before = min(lines[(path, scope)])
        else:
            name = scope.rsplit(".", 1)[-1]
            before = min(
                node.lineno for node in ast.walk(fn)
                if (isinstance(node, ast.Attribute) and node.attr == name) or (isinstance(node, ast.Name) and node.id == name)
            )
        assert call.lineno < before, (path, cover.check, call.lineno, before)


def test_a_sinks_launching_function_is_reached_only_from_its_check_function() -> None:
    """EC4: in its file, a sink's separate launching function is referenced only in the sink's function and in itself."""
    rows = [(path, scope, cover) for (path, scope), (_n, cover) in SUBPROCESS_SITES.items() if isinstance(cover, Sink)]
    split = [(path, scope, cover) for path, scope, cover in rows if cover.check != scope]
    assert {path for path, _scope, _cover in split} == {"src/probos/agents/shell_command.py", "src/probos/agents/red_team.py"}
    for path, scope, cover in split:
        tree = ast.parse(src_sources()[path], filename=path)
        assert references_outside(tree, scope.rsplit(".", 1)[-1], (cover.check, scope)) == [], path


def test_the_system_principal_allowlist_is_what_the_census_names() -> None:
    """EC5 (D166; kills EX-3)."""
    named = {cover.principal for _count, cover in SUBPROCESS_SITES.values() if isinstance(cover, System)}
    presented = system_principal_literals(src_sources())
    assert SYSTEM_PRINCIPALS == frozenset(named | presented), (sorted(named), sorted(presented))
    assert (named, presented) == ({SHIP}, set())
    for principal in SYSTEM_PRINCIPALS:
        assert principal.startswith(SYSTEM_PRINCIPAL_PREFIX), principal
        assert check_principal(Principal(PRINCIPAL_SYSTEM, principal, None)) is None, principal


def test_outside_runtime_rows_are_in_modules_no_runtime_module_imports() -> None:
    """EC6 (D167)."""
    rows = [path for (path, _scope), (_n, cover) in SUBPROCESS_SITES.items() if isinstance(cover, OutsideRuntime)]
    assert rows and all(path.startswith(OUTSIDE_RUNTIME) for path in rows), rows
    assert outside_importers(src_sources()) == []


def test_the_sink_set_names_five_classes_and_the_delivered_ones_are_the_ticket_effects() -> None:
    """EC7 (D168)."""
    assert list(EFFECT_CLASSES) == ["model_call", "tool", "subprocess", "egress", "store_write"]
    assert DELIVERED == frozenset(TICKET_EFFECTS) == {SEAM_MODEL_CALL, SEAM_TOOL, EFFECT_SUBPROCESS}
    assert DELIVERED < frozenset(EFFECT_CLASSES)


def test_the_census_helpers_report_a_new_site_a_stale_row_a_count_a_reference_an_import_and_a_literal() -> None:
    """EC8: the helpers on synthetic input, so a helper that reports nothing cannot pass EC2, EC4, EC5 or EC6 silently."""
    listed: dict[tuple[str, str], tuple[int, object]] = {
        ("src/probos/a.py", "f"): (1, System(SHIP, "r")),
        ("src/probos/b.py", "g"): (2, System(SHIP, "r")),
        ("src/probos/d.py", "k"): (1, System(SHIP, "r")),
    }
    found = {("src/probos/a.py", "f"): 1, ("src/probos/b.py", "g"): 1, ("src/probos/c.py", "h"): 1}
    assert census_problems(found, listed) == [
        "unlisted launch site ('src/probos/c.py', 'h')",
        "stale row ('src/probos/d.py', 'k')",
        "('src/probos/b.py', 'g'): 1 launches, the row says 2",
    ]
    source = "class A:\n    def run(self):\n        self._go()\n    def other(self):\n        return self._go\n    def _go(self):\n        pass\n\n\n_go = None\n"
    assert references_outside(ast.parse(source), "_go", ("A.run", "A._go")) == [("A.other", 5), ("<module>", 10)]
    sources = {
        "src/probos/runtime.py": "from probos.doctor import run_doctor\n",
        "src/probos/doctor/x.py": "from probos.doctor.protocol import A\n",
        "src/probos/__main__.py": "from probos.doctor import run_doctor\n",
        "src/probos/y.py": "import json\nimport probos.__main__\n",
        "src/probos/z.py": "from probos import doctor\n",
        "src/probos/w.py": "from probos.doctorate import x\n",
    }
    assert outside_importers(sources) == [("src/probos/runtime.py", 1), ("src/probos/y.py", 2), ("src/probos/z.py", 1)]
    literal = (
        'check_at(s, effect=E, presented_id="system:x")\n'
        'shadow_at(s, presented_id="agent-1", work_kind="k", seam="s", origin="o", origin_id="i", refused=False)\n'
        'seam.hold_at(s, presented_id="system:y", work_kind="k", seam="s", child=False)\n'
        'other(presented_id="system:z")\n'
    )
    assert system_principal_literals({"src/probos/a.py": literal}) == {"system:x", "system:y"}


async def test_a_runs_subprocess_launch_is_checked_live_then_revoked_and_missing_outside(
    identities: IdentityService, stops: AgentStopService, tickets: TicketRegistry,
) -> None:
    """EC9 (#1604 property 1, the subprocess class's crossing test; kills EX-4, EX-5): request, shadow decision and the
    sink's liveness record, in memory. The shell agent presents no principal (D164)."""
    service = AdmissionService(identities, stops, tickets=tickets, loop=asyncio.get_running_loop())
    shell, spawned = _shell(service)
    seen: dict[str, Any] = {}

    async def body(arguments: dict[str, Any]) -> str:
        seen["live"] = await shell._run_command(COMMAND)
        seen["tally_live"] = tickets.tally()
        await stops.issue_stop(AGENT_A, reason="ad1346-m3e1: the Captain stops a run in flight")
        seen["revoked"] = await shell._run_command(COMMAND)
        return "ran"

    runtime = SimpleNamespace(tool_registry=_tools(stops, service), admission_service=service)
    runner = _ScriptedRun({AGENT_A: body})
    assert await runner.run(agent_id=AGENT_A, instructions="i", task_text="t", runtime=runtime, extra_context=None) == "ran"
    outside = await shell._run_command(COMMAND)
    assert seen["tally_live"] == {("issue", "ticket_issued"): 1, ("subprocess", "ticket_live"): 1}
    assert tickets.tally() == {
        **seen["tally_live"], ("subprocess", "ticket_revoked"): 1, ("subprocess", "ticket_missing"): 1,
    }
    assert [key[0] for key in service.tally()] == ["agentic_run"], "the run entry's shadow decision"
    assert seen["live"] == seen["revoked"] == outside == _SPAWNED, "nothing is refused"
    assert spawned == [COMMAND] * 3 and service.failures == 0


async def test_with_and_without_the_service_the_subprocess_sinks_answer_identically(
    identities: IdentityService, stops: AgentStopService, tickets: TicketRegistry, monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """EC10 (#1604 property 12 at three sinks; kills EX-7)."""
    service = AdmissionService(identities, stops, tickets=tickets, loop=asyncio.get_running_loop())

    async def no_shell(*args: Any, **kwargs: Any) -> Any:
        raise OSError("ad1346-m3e1: no process is started")

    async def no_exec(*args: Any, **kwargs: Any) -> _Finished:
        return _Finished()

    monkeypatch.setattr(asyncio, "create_subprocess_shell", no_shell)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", no_exec)

    async def answers(with_service: bool) -> tuple[Any, Any, Any]:
        held = service if with_service else None
        shell, _spawned = _shell(held)
        search = CodeSearchAgent(pool="ad1346-m3e1", agent_id=SEARCH_ID, runtime=SimpleNamespace(admission_service=held))
        tool = RunCommandTool(SimpleNamespace(admission_service=held))
        return (
            await shell._run_command(COMMAND),
            await search._search_rg("rg", dict(_PLAN), tmp_path),
            dataclasses.asdict(await tool.invoke({"command": COMMAND}, {"agent_id": AGENT_A})),
        )

    first = (await answers(True), await answers(False))
    hold = service.hold(presented_id=AGENT_A, work_kind="agentic_run", seam="agentic_run", child=False)
    try:
        second = (await answers(True), await answers(False))
        await stops.issue_stop(AGENT_A, reason="ad1346-m3e1: the golden test's stop")
        third = (await answers(True), await answers(False))
    finally:
        hold.end()
    assert first[0] == first[1] and second[0] == second[1] and third[0] == third[1]
    assert tickets.tally() == {
        ("subprocess", "ticket_missing"): 3, ("issue", "ticket_issued"): 1, ("subprocess", "ticket_live"): 3,
        ("subprocess", "ticket_revoked"): 3,
    }
    assert service.failures == 0
