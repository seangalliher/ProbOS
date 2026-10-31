"""AD-1346 M3e2a (#1604): the subprocess sinks of the code sandbox and the dependency installer, their wiring, and the
census rows that no other ``src`` code reaches.

- SP1  the three ``Unreached`` rows of ``tests/fixtures/ad1346_effect_census.py``: each launching scope's outermost name
       is one of the row's names, and ``unreached_references`` finds no reference to them in ``src``.
- SP2  ``unreached_references`` on synthetic modules: it reports a reference in the row's own module outside the
       functions and classes so named, and elsewhere an attribute of something other than ``self`` and three
       import forms; it does not report an attribute of ``self`` in another module, a reference inside a named
       function, or a name that only contains one.
- SP3  by AST: ``src`` holds five calls named ``SubprocessSandbox``; the code runner's two and the code execution
       tool's two pass ``admission_service`` read from their runtime, and ``SkillForge._smoke_test``'s passes none;
       ``ProbOSRuntime.start`` holds the call ``self.dependency_resolver.set_admission(self.admission_service)``.
- SP4  #1604 property 1's crossing test for the two sinks: inside the real run entry, a real ``CodeExecutionTool``
       whose runtime holds the service runs its ``SubprocessSandbox``, and a ``DependencyResolver`` handed the service
       installs a package; each counts ``ticket_live``, after a Captain's stop ``ticket_revoked``, and outside any hold
       ``ticket_missing``, and each answer is the replaced launch's.
- SP5  #1604 property 12 at the two sinks: a sandbox and an installer answer the same with the service and without it,
       with nothing carried, under a live ticket and after a Captain's stop; an installer with an ``install_fn``
       checks nothing.

SP4 and SP5 replace ``SubprocessSandbox._run_sync_inner`` and ``subprocess.run``, make ``subprocess.Popen`` a recorder
that raises ``OSError``, and assert that it recorded no call.
"""

from __future__ import annotations

import ast
import asyncio
import json
import subprocess
import unicodedata
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio

from probos.admission import AdmissionService
from probos.admission.tickets import TicketRegistry
from probos.agent_stop import AgentStopService
from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
from probos.cognitive.dependency_resolver import DependencyResolver
from probos.config import ExecutionConfig
from probos.crew_profile import CallsignRegistry
from probos.execution.isolation import ExecutionRequest, ExecutionResult, SubprocessSandbox
from probos.execution.long_runs import LongRunService
from probos.identity import AgentIdentityRegistry
from probos.identity_service import IdentityService
from probos.substrate.registry import AgentRegistry
from probos.tools.code_execution_tool import CodeExecutionTool
from probos.tools.registry import ToolRegistry
from tests.fixtures.ad1343_seam_census import calls, function
from tests.fixtures.ad1346_effect_census import SUBPROCESS_SITES, Unreached, src_sources, unreached_references

INSTANCE_ID = "ad1346-m3e2a-ship"
VESSEL_NAME = "Ad1346m3e2a"
AGENT_A = "ad1346-m3e2a-agent-a"
CODE = "print('ad1346-m3e2a')"
STDOUT = "ad1346-m3e2a"
PACKAGE = "ad1346-m3e2a-package"
INSTALLED = "ad1346-m3e2a installed"
CONTEXT: dict[str, Any] = {"agent_id": AGENT_A, "thread_id": ""}
_RUNTIME_SERVICE = "getattr(self._runtime, 'admission_service', None)"
#: (file, function) -> the ``admission_service`` keyword of each ``SubprocessSandbox`` construction there, or None.
_SANDBOX_BUILDERS: dict[tuple[str, str], list[str | None]] = {
    ("src/probos/agents/code_runner.py", "CodeRunnerAgent._run_python"): [_RUNTIME_SERVICE],
    ("src/probos/agents/code_runner.py", "CodeRunnerAgent._install_package"): [_RUNTIME_SERVICE],
    ("src/probos/tools/code_execution_tool.py", "CodeExecutionTool.invoke"): [_RUNTIME_SERVICE, _RUNTIME_SERVICE],
    ("src/probos/cognitive/skill_forge.py", "SkillForge._smoke_test"): [None],
}


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


class _Audit:
    """The code execution tool's audit log: a durable stream that keeps each record (as the #1417 probes' does)."""

    def __init__(self) -> None:
        self.records: list[tuple[str, dict[str, Any]]] = []

    def durable_stream_open(self) -> bool:
        return True

    def append(self, *, category: str, detail: str) -> None:
        self.records.append((category, json.loads(detail)))


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


def _tools(stops: AgentStopService, service: AdmissionService) -> ToolRegistry:
    registry = ToolRegistry()
    registry.set_stop_gate(stops)
    registry.set_admission(service)
    return registry


def _no_launch(monkeypatch: pytest.MonkeyPatch) -> tuple[list[object], list[object]]:
    """Replace the sandbox's launching function and ``subprocess.run``; make ``subprocess.Popen`` a recorder that raises."""
    popen: list[object] = []
    ran: list[object] = []

    def no_popen(*args: Any, **kwargs: Any) -> Any:
        popen.append(args)
        raise OSError("ad1346-m3e2a: no process is started")

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        ran.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout=INSTALLED, stderr="")

    def inner(self: SubprocessSandbox, request: ExecutionRequest) -> ExecutionResult:
        return ExecutionResult(success=True, stdout=STDOUT, exit_code=0)

    monkeypatch.setattr(subprocess, "Popen", no_popen)
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(SubprocessSandbox, "_run_sync_inner", inner)
    return popen, ran


def _tool(tmp_path: Path, service: AdmissionService) -> CodeExecutionTool:
    """A real code execution tool whose runtime holds ``service`` (the #1417 probes' tool runtime, with the service)."""
    runtime = SimpleNamespace(
        config=SimpleNamespace(execution=ExecutionConfig(enabled=True, scratch_dir=str(tmp_path / "scratch"))),
        audit_log=_Audit(), execution_long_runs=LongRunService(), admission_service=service,
    )
    return CodeExecutionTool(runtime=runtime)


def test_each_unreached_row_is_reached_from_no_other_src_code() -> None:
    """SP1 (D177; kills EP-7)."""
    rows = [(path, scope, cover) for (path, scope), (_n, cover) in SUBPROCESS_SITES.items() if isinstance(cover, Unreached)]
    assert sorted((path, scope) for path, scope, _cover in rows) == [
        ("src/probos/cognitive/builder.py", "_run_tests._sync_run"),
        ("src/probos/security/container_sandbox.py", "DockerContainerSandbox.run"),
        ("src/probos/security/container_sandbox.py", "InProcessContainerSandbox.run"),
    ]
    for path, scope, cover in rows:
        assert scope.split(".")[0] in cover.names, (path, scope, cover.names)
        assert unreached_references(src_sources(), path, cover.names) == [], (path, scope)


def test_unreached_references_reports_each_way_in_and_nothing_else() -> None:
    """SP2 (kills EP-8): the helper on synthetic modules, so a helper that reports nothing cannot pass SP1 silently."""
    sources = {
        "src/probos/sandbox_mod.py": (
            "def launch():\n    return launch\n\n\nclass Other:\n    def go(self):\n        return launch()\n\n\nlaunch()\n"
        ),
        "src/probos/a.py": "from probos.sandbox_mod import Thing\n",
        "src/probos/b.py": "from probos import sandbox_mod\n",
        "src/probos/c.py": "import probos.sandbox_mod as m\n",
        "src/probos/d.py": "class D:\n    def f(self):\n        return self.launch\n",
        "src/probos/e.py": "def f(runner):\n    return runner.launch()\n",
        "src/probos/f.py": "def f(runner):\n    return runner.\uff4caunch()\n",
        "src/probos/g.py": "relaunch = 1\nlaunched = 2\n",
        "src/probos/h.py": "from probos.other import launch_all\n",
    }
    assert unreached_references(sources, "src/probos/sandbox_mod.py", ("sandbox_mod", "launch")) == [
        ("src/probos/sandbox_mod.py", 7), ("src/probos/sandbox_mod.py", 10), ("src/probos/a.py", 1),
        ("src/probos/b.py", 1), ("src/probos/c.py", 1), ("src/probos/e.py", 2), ("src/probos/f.py", 2),
    ]


def test_the_sandbox_constructions_and_the_installer_receive_the_runtimes_service() -> None:
    """SP3 (D175; kills EP-4, EP-6)."""
    built = sum(
        1 for rel, source in src_sources().items() if "SubprocessSandbox" in unicodedata.normalize("NFKC", source)
        for node in ast.walk(ast.parse(source, filename=rel)) if calls("SubprocessSandbox")(node)
    )
    assert built == sum(len(services) for services in _SANDBOX_BUILDERS.values()) == 5
    for (rel, qualname), services in _SANDBOX_BUILDERS.items():
        found = [node for node in ast.walk(function(rel, qualname)) if calls("SubprocessSandbox")(node)]
        passed = [next((ast.unparse(k.value) for k in node.keywords if k.arg == "admission_service"), None) for node in found]
        assert passed == services, (rel, qualname, passed)
    start = function("src/probos/runtime.py", "ProbOSRuntime.start")
    handed = {ast.unparse(node) for node in ast.walk(start) if calls("set_admission")(node)}
    assert "self.dependency_resolver.set_admission(self.admission_service)" in handed, sorted(handed)


async def test_a_runs_sandbox_and_install_launches_are_checked_live_then_revoked_and_missing_outside(
    identities: IdentityService, stops: AgentStopService, tickets: TicketRegistry, monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """SP4 (#1604 property 1, the crossing test for the two sinks; kills EP-1, EP-2, EP-3): the run entry's hold, then the
    tool's sandbox and the installer. Both present no principal (D176)."""
    service = AdmissionService(identities, stops, tickets=tickets, loop=asyncio.get_running_loop())
    popen, ran = _no_launch(monkeypatch)
    tool = _tool(tmp_path, service)
    resolver = DependencyResolver(allowed_imports=[])
    resolver.set_admission(service)
    seen: dict[str, Any] = {}

    async def both() -> tuple[Any, tuple[bool, str]]:
        return await tool.invoke({"code": CODE}, dict(CONTEXT)), await resolver._install_package(PACKAGE)

    async def body(arguments: dict[str, Any]) -> str:
        seen["live"] = await both()
        seen["tally_live"] = tickets.tally()
        await stops.issue_stop(AGENT_A, reason="ad1346-m3e2a: the Captain stops a run in flight")
        seen["revoked"] = await both()
        return "ran"

    runtime = SimpleNamespace(tool_registry=_tools(stops, service), admission_service=service)
    runner = _ScriptedRun({AGENT_A: body})
    assert await runner.run(agent_id=AGENT_A, instructions="i", task_text="t", runtime=runtime, extra_context=None) == "ran"
    outside = await both()
    assert seen["tally_live"] == {("issue", "ticket_issued"): 1, ("subprocess", "ticket_live"): 2}
    assert tickets.tally() == {
        **seen["tally_live"], ("subprocess", "ticket_revoked"): 2, ("subprocess", "ticket_missing"): 2,
    }
    answers = [seen["live"], seen["revoked"], outside]
    assert [(result.error, result.output["stdout"]) for result, _installed in answers] == [(None, STDOUT)] * 3
    assert [installed for _result, installed in answers] == [(True, INSTALLED)] * 3, "nothing is refused"
    assert popen == [] and len(ran) == 3 and service.failures == 0


async def test_with_and_without_the_service_the_sandbox_and_the_installer_answer_identically(
    identities: IdentityService, stops: AgentStopService, tickets: TicketRegistry, monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """SP5 (#1604 property 12 at the two sinks; kills EP-5, EP-10)."""
    service = AdmissionService(identities, stops, tickets=tickets, loop=asyncio.get_running_loop())
    popen, ran = _no_launch(monkeypatch)

    async def answers(with_service: bool) -> tuple[ExecutionResult, tuple[bool, str]]:
        held = service if with_service else None
        sandbox = SubprocessSandbox(scratch_root=tmp_path / "scratch", admission_service=held)
        resolver = DependencyResolver(allowed_imports=[])
        resolver.set_admission(held)
        return await sandbox.run(ExecutionRequest(code=CODE)), await resolver._install_package(PACKAGE)

    first = (await answers(True), await answers(False))
    hold = service.hold(presented_id=AGENT_A, work_kind="agentic_run", seam="agentic_run", child=False)
    try:
        second = (await answers(True), await answers(False))
        await stops.issue_stop(AGENT_A, reason="ad1346-m3e2a: the golden test's stop")
        third = (await answers(True), await answers(False))
    finally:
        hold.end()

    async def fixed(package: str) -> tuple[bool, str]:
        return True, f"{package} by install_fn"

    quiet = DependencyResolver(allowed_imports=[], install_fn=fixed)
    quiet.set_admission(service)
    assert await quiet._install_package(PACKAGE) == (True, f"{PACKAGE} by install_fn")
    assert first[0] == first[1] and second[0] == second[1] and third[0] == third[1]
    assert first[0] == (ExecutionResult(success=True, stdout=STDOUT, exit_code=0), (True, INSTALLED))
    assert tickets.tally() == {
        ("subprocess", "ticket_missing"): 2, ("issue", "ticket_issued"): 1, ("subprocess", "ticket_live"): 2,
        ("subprocess", "ticket_revoked"): 2,
    }, "two checks for each answer with the service, none without it, none with an install_fn"
    assert popen == [] and len(ran) == 6 and service.failures == 0
