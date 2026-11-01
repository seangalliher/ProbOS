"""AD-1346 M3e2b (#1604): the subprocess sink of the builder's targeted tests of an approved build, and its wiring.

- BT1  by AST: ``src`` holds three calls by the executor's two names (``execute_approved_build`` in the
       resolve route's ``_execute_build`` and in ``BuildDispatcher._execute_build``, ``_legacy_execute_approved_build`` in
       ``BuildPipeline.execute_approved_build``), each passing ``admission_service`` as ``_EXECUTOR_CALLS`` records,
       and ``ProbOSRuntime.start`` calls ``self.build_dispatcher.set_admission(self.admission_service)``.
- BT2  the production hand-off: after ``ProbOSRuntime.start`` with ``admission.shadow_enabled`` true, the resolve route
       on that runtime, its build dispatcher and its build pipeline each hand the executor the runtime's service; the
       executor is replaced in each.
- BT3  #1604 property 1's crossing test at the new sink: the resolve route over a runtime double holding the service runs
       the real executor; its targeted-test check counts ``ticket_missing`` outside any hold, ``ticket_live`` inside a
       hold the test makes and ``ticket_revoked`` after a Captain's stop, and each run emits the same event types.
- BT4  #1604 property 12 at the new sink: the executor answers the same with the service and without it, with nothing
       carried, under a live ticket and after a Captain's stop; with ``run_tests`` false it checks nothing.

BT3 and BT4 answer each ``subprocess.run`` call (git's with ``main``, every other with a pass), make
``asyncio.create_subprocess_exec`` return a process that already ended with exit 1, and make ``subprocess.Popen`` and
``asyncio.create_subprocess_shell`` recorders that raise ``OSError``; each asserts that the raising recorders saw no
call and that each exec call was git's. BT2 boots a real runtime, as ``tests/test_bf904b_sealed_core_observation.py``'s
S7 does, and replaces none of those four.
"""

from __future__ import annotations

import ast
import asyncio
import shutil
import subprocess
import unicodedata
from collections.abc import AsyncIterator, Coroutine
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from probos.admission import AdmissionService
from probos.admission.tickets import TicketRegistry
from probos.agent_stop import AgentStopService
from probos.api_models import BuildResolveRequest
from probos.cognitive.builder import BuildFailureReport, BuildResult, BuildSpec, execute_approved_build
from probos.cognitive.copilot_adapter import CopilotBuilderAdapter
from probos.cognitive.llm_client import MockLLMClient
from probos.config import SystemConfig
from probos.crew_profile import CallsignRegistry
from probos.events import EventType
from probos.identity import AgentIdentityRegistry
from probos.identity_service import IdentityService
from probos.runtime import ProbOSRuntime
from probos.substrate.registry import AgentRegistry
from probos.worktree_manager import WorktreeInfo, WorktreeManager
from tests.fixtures.ad1343_seam_census import calls, function
from tests.fixtures.ad1346_effect_census import src_sources

INSTANCE_ID = "ad1346-m3e2b-ship"
VESSEL_NAME = "Ad1346m3e2b"
AGENT_A = "ad1346-m3e2b-agent-a"
BUILD_ID = "ad1346m3e2b"
WIDGET = "src/probos/widget.py"
_CHANGES: tuple[dict[str, str], ...] = ({"path": WIDGET, "mode": "create", "content": "w = 1\n"},)
_EXECUTOR_NAMES = ("execute_approved_build", "_legacy_execute_approved_build")
#: (file, function) -> (the executor name it calls, its ``admission_service`` keyword as ``ast.unparse`` renders it).
_EXECUTOR_CALLS: dict[tuple[str, str], tuple[str, str]] = {
    ("src/probos/routers/build.py", "_execute_build"): ("execute_approved_build", "getattr(rt, 'admission_service', None)"),
    ("src/probos/build_dispatcher.py", "BuildDispatcher._execute_build"): ("execute_approved_build", "self._admission"),
    ("src/probos/build_pipeline.py", "BuildPipeline.execute_approved_build"): (
        "_legacy_execute_approved_build", "getattr(self._runtime, 'admission_service', None)",
    ),
}


class _Clock:
    """A fixed clock: no test in this file moves it."""

    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


class _Finished:
    """What the replaced exec constructor returns: a process that already ended with exit 1 and no output."""

    returncode = 1

    async def communicate(self) -> tuple[bytes, bytes]:
        return b"", b""


class _Launches:
    """What the replaced launchers saw: each non-git ``subprocess.run`` argv, each exec call, and each call of a raising one."""

    def __init__(self) -> None:
        self.tests: list[list[str]] = []
        self.execs: list[tuple[Any, ...]] = []
        self.refused: list[tuple[Any, ...]] = []


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


def _route() -> Any:
    """``probos.routers.build``; it takes its failure cache from ``probos.api``, so that module loads first."""
    import probos.api  # noqa: F401
    from probos.routers import build as build_router

    return build_router


def _spec() -> BuildSpec:
    return BuildSpec(title="ad1346 m3e2b", description="d")


def _changes() -> list[dict[str, str]]:
    return [dict(change) for change in _CHANGES]


def _seed(work: Path) -> str:
    """A fresh tree at ``work`` holding the one test file the change maps to (``tests/test_widget.py``)."""
    shutil.rmtree(work, ignore_errors=True)
    (work / "tests").mkdir(parents=True)
    (work / "tests" / "test_widget.py").write_text("def test_widget():\n    pass\n", encoding="utf-8")
    return str(work)


def _cached(work_dir: str) -> dict[str, Any]:
    """A failed build in the resolve route's cache, with the four keys ``resolve_build`` reads."""
    return {"file_changes": _changes(), "spec": _spec(), "work_dir": work_dir, "report": BuildFailureReport()}


def _handed(executor: AsyncMock) -> object:
    assert executor.await_args is not None, "premise: the caller reached the executor"
    return executor.await_args.kwargs["admission_service"]


def _no_launch(monkeypatch: pytest.MonkeyPatch) -> _Launches:
    """Answer git's ``subprocess.run`` with ``main`` and record and pass every other call; the exec constructor
    answers a finished process; ``subprocess.Popen`` and the shell constructor raise."""
    seen = _Launches()

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        if argv[0] == "git":
            return subprocess.CompletedProcess(argv, 0, stdout=b"main\n", stderr=b"")
        seen.tests.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, stdout=b"1 passed\n", stderr=b"")

    async def exec_(*args: Any, **kwargs: Any) -> _Finished:
        seen.execs.append(args)
        return _Finished()

    def popen(*args: Any, **kwargs: Any) -> Any:
        seen.refused.append(args)
        raise OSError("ad1346-m3e2b: no process is started")

    async def shell(*args: Any, **kwargs: Any) -> Any:
        seen.refused.append(args)
        raise OSError("ad1346-m3e2b: no process is started")

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", exec_)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", shell)
    return seen


def test_the_three_executor_calls_pass_their_service_and_the_runtime_hands_the_dispatcher_its_own() -> None:
    """BT1 (D187)."""
    found = sorted(
        (rel, name)
        for rel, source in src_sources().items() if "execute_approved_build" in unicodedata.normalize("NFKC", source)
        for node in ast.walk(ast.parse(source, filename=rel))
        for name in _EXECUTOR_NAMES if calls(name)(node)
    )
    assert found == sorted((rel, callee) for (rel, _qualname), (callee, _service) in _EXECUTOR_CALLS.items()), found
    for (rel, qualname), (callee, service) in _EXECUTOR_CALLS.items():
        (call,) = [node for node in ast.walk(function(rel, qualname)) if calls(callee)(node)]
        keywords = {keyword.arg: ast.unparse(keyword.value) for keyword in call.keywords}
        assert keywords.get("admission_service") == service, (rel, qualname, keywords)
    start = function("src/probos/runtime.py", "ProbOSRuntime.start")
    handed = {ast.unparse(node) for node in ast.walk(start) if calls("set_admission")(node)}
    assert "self.build_dispatcher.set_admission(self.admission_service)" in handed, sorted(handed)


async def test_a_booted_runtime_hands_its_service_to_the_resolve_route_the_dispatcher_and_the_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BT2 (D187, the production hand-off; kills EQ-3 to EQ-6)."""
    config = SystemConfig()
    config.admission.shadow_enabled = True
    config.onboarding.naming_ceremony = False
    config.proactive_cognitive.enabled = False
    config.qa.enabled = False
    runtime = ProbOSRuntime(config=config, data_dir=tmp_path / "data", llm_client=MockLLMClient())
    await asyncio.wait_for(runtime.start(), timeout=600)
    try:
        service = runtime.admission_service
        assert type(service) is AdmissionService, "premise: the boot built the shadow service"
        stopped = BuildResult(success=False, spec=_spec(), error="ad1346-m3e2b: stop after the executor")
        handed: dict[str, object] = {}

        build_router = _route()
        monkeypatch.setattr(build_router, "_pending_failures", {BUILD_ID: _cached(str(tmp_path / "route"))})
        scheduled: list[Coroutine[Any, Any, None]] = []
        request = BuildResolveRequest(build_id=BUILD_ID, resolution="retry_targeted")
        with patch("probos.cognitive.builder.execute_approved_build", new_callable=AsyncMock, return_value=stopped) as executor:
            await build_router.resolve_build(request, runtime=runtime, track_task=lambda coro, name=None: scheduled.append(coro))
            await asyncio.wait_for(scheduled[0], timeout=120)
        handed["route"] = _handed(executor)

        dispatcher = runtime.build_dispatcher
        build = runtime.build_queue.enqueue(BuildSpec(title="ad1346 m3e2b dispatch", description="d"))
        runtime.build_queue.update_status(build.id, "dispatched")
        worktrees = MagicMock(spec=WorktreeManager)
        worktrees.create = AsyncMock(return_value=WorktreeInfo(
            path=str(tmp_path / "wt"), branch=f"builder-{build.id[:8]}", build_id=build.id, created_at=0.0,
        ))
        monkeypatch.setattr(dispatcher, "_worktree_mgr", worktrees)
        generated = MagicMock()
        generated.success = True
        generated.file_blocks = _changes()
        generated.error = ""
        adapter = MagicMock(spec=CopilotBuilderAdapter)
        adapter.start = AsyncMock()
        adapter.stop = AsyncMock()
        adapter.execute = AsyncMock(return_value=generated)
        with patch("probos.build_dispatcher._SDK_AVAILABLE", True), \
             patch("probos.build_dispatcher.CopilotBuilderAdapter", return_value=adapter) as adapter_cls, \
             patch("probos.build_dispatcher.repository_identity", new_callable=AsyncMock, return_value=str(tmp_path / "wt" / ".git")), \
             patch("probos.build_dispatcher.execute_approved_build", new_callable=AsyncMock, return_value=stopped) as executor:
            adapter_cls.is_available.return_value = True
            await asyncio.wait_for(dispatcher._execute_build(build), timeout=120)
        handed["dispatcher"] = _handed(executor)

        with patch("probos.cognitive.builder.execute_approved_build", new_callable=AsyncMock, return_value=stopped) as executor:
            assert await runtime.build_pipeline.execute_approved_build(_changes(), _spec(), str(tmp_path / "pipe")) is stopped
        handed["pipeline"] = _handed(executor)
        assert handed == dict.fromkeys(("route", "dispatcher", "pipeline"), service), handed
    finally:
        await asyncio.wait_for(runtime.stop(), timeout=600)


async def test_the_resolve_routes_targeted_tests_count_missing_outside_a_hold_then_live_and_revoked(
    identities: IdentityService, stops: AgentStopService, tickets: TicketRegistry, monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """BT3 (#1604 property 1, the crossing test at the targeted-test sink; kills EQ-2): no build entry holds a ticket
    (register R86), so the hold here is the test's. The check presents no principal (D188)."""
    service = AdmissionService(identities, stops, tickets=tickets, loop=asyncio.get_running_loop())
    seen = _no_launch(monkeypatch)
    build_router = _route()
    cache: dict[str, dict[str, Any]] = {}
    monkeypatch.setattr(build_router, "_pending_failures", cache)
    events: list[tuple[Any, dict[str, Any]]] = []
    runtime = SimpleNamespace(admission_service=service, emit_event=lambda kind, data: events.append((kind, data)))
    work = tmp_path / "work"

    async def resolve() -> list[Any]:
        cache[BUILD_ID] = _cached(_seed(work))
        scheduled: list[Coroutine[Any, Any, None]] = []
        request = BuildResolveRequest(build_id=BUILD_ID, resolution="retry_targeted")
        answer = await build_router.resolve_build(request, runtime=runtime, track_task=lambda coro, name=None: scheduled.append(coro))
        assert answer == {"status": "ok", "resolution": "retry_targeted", "build_id": BUILD_ID}
        start = len(events)
        await asyncio.wait_for(scheduled[0], timeout=120)
        return [kind for kind, _data in events[start:]]

    outside = await resolve()
    hold = service.hold(presented_id=AGENT_A, work_kind="agentic_run", seam="agentic_run", child=False)
    try:
        live = await resolve()
        await stops.issue_stop(AGENT_A, reason="ad1346-m3e2b: the Captain stops a run in flight")
        revoked = await resolve()
    finally:
        hold.end()
    assert outside == live == revoked and outside[-1] in (EventType.BUILD_SUCCESS, EventType.BUILD_FAILURE), outside
    assert tickets.tally() == {
        ("subprocess", "ticket_missing"): 1, ("issue", "ticket_issued"): 1, ("subprocess", "ticket_live"): 1,
        ("subprocess", "ticket_revoked"): 1,
    }
    assert len(seen.tests) == 3 and seen.refused == [] and service.failures == 0
    assert all(args[0] == "git" for args in seen.execs), seen.execs


async def test_with_and_without_the_service_an_approved_build_answers_identically(
    identities: IdentityService, stops: AgentStopService, tickets: TicketRegistry, monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """BT4 (#1604 property 12 at the targeted-test sink; kills EQ-1)."""
    service = AdmissionService(identities, stops, tickets=tickets, loop=asyncio.get_running_loop())
    seen = _no_launch(monkeypatch)
    work = tmp_path / "work"

    async def answer(held: object, *, run_tests: bool = True) -> BuildResult:
        build = execute_approved_build(_changes(), _spec(), _seed(work), run_tests=run_tests, admission_service=held)
        return await asyncio.wait_for(build, timeout=120)

    first = (await answer(service), await answer(None))
    hold = service.hold(presented_id=AGENT_A, work_kind="agentic_run", seam="agentic_run", child=False)
    try:
        second = (await answer(service), await answer(None))
        await stops.issue_stop(AGENT_A, reason="ad1346-m3e2b: the golden test's stop")
        third = (await answer(service), await answer(None))
    finally:
        hold.end()
    await answer(service, run_tests=False)
    assert first[0] == first[1] == second[0] == second[1] == third[0] == third[1]
    assert first[0].metadata.get("targeted_tests") == "passed", "premise: the targeted tests ran and passed"
    assert tickets.tally() == {
        ("subprocess", "ticket_missing"): 1, ("issue", "ticket_issued"): 1, ("subprocess", "ticket_live"): 1,
        ("subprocess", "ticket_revoked"): 1,
    }, "one check for each build with the service and its tests on, none without the service or with its tests off"
    assert len(seen.tests) == 6 and seen.refused == [] and service.failures == 0
    assert all(args[0] == "git" for args in seen.execs), seen.execs
