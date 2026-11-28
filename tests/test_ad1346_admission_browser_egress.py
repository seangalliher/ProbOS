"""AD-1346 M3e3c (#1604): the egress sinks of the browser tool's engine, in shadow.

``BrowserSession.start`` and ``BrowserSession.connect`` call ``check_at`` with ``EFFECT_EGRESS`` and the session's agent,
reading the service from the runtime the session is handed. ``BrowserTool._create_session`` and
``BrowserTool._connect_bridge_session`` hand each session the tool's runtime, and ``_wire_browser_tool`` builds the tool
with the runtime. ``tests/test_ad1346_admission_egress_sinks.py``'s ES1 checks the two checks' placement by AST.

- BE1  the production hand-off: after ``ProbOSRuntime.start`` with ``admission.shadow_enabled`` and the browser tool
       on, the runtime's ``browser_tool`` hands ``check_ticket`` the runtime's service at an engine start through
       ``invoke`` and at a bridge connect.
- BE2  #1604 property 1 at the two checks: each counts ``ticket_missing`` outside a hold, ``ticket_live`` inside a
       hold the test makes and ``ticket_revoked`` after a Captain's stop, and an engine started for another agent inside
       the hold counts ``ticket_principal_mismatch``; a call through ``ToolRegistry.check_and_invoke`` that starts an
       engine is counted at ``tool`` and at ``egress``, and after the stop the registry refuses it and no engine starts
       for it.
- BE3  #1604 property 12 at the two checks: ``BrowserTool.invoke`` and ``connect_bridge_session`` answer the same with
       the service and without it, with nothing carried, under a live ticket and after a Captain's stop.

Each test replaces ``playwright`` and ``playwright.async_api`` in ``sys.modules`` with two stand-in modules, the second
binding ``async_playwright`` to a function that returns a recording fake engine, and
``probos.tools.browser.session.loop_supports_subprocess`` with a function that returns True, as
``tests/test_browser_session_lifecycle.py`` does. BE1 boots a real runtime under ``tmp_path``, as
``tests/test_ad1346_admission_egress_sinks.py``'s ES2 does.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio

from probos.admission import AdmissionService
from probos.admission.taxonomy import EFFECT_EGRESS
from probos.admission.tickets import TicketRegistry
from probos.agent_stop import AgentStopService
from probos.cognitive.llm_client import MockLLMClient
from probos.config import SystemConfig
from probos.crew_profile import CallsignRegistry
from probos.identity import AgentIdentityRegistry
from probos.identity_service import IdentityService
from probos.runtime import ProbOSRuntime
from probos.substrate.registry import AgentRegistry
from probos.tools.browser.tool import BrowserTool
from probos.tools.registry import ToolRegistry

INSTANCE_ID = "ad1346-m3e3c-ship"
VESSEL_NAME = "Ad1346m3e3c"
AGENT_A = "ad1346-m3e3c-agent-a"
AGENT_B = "ad1346-m3e3c-agent-b"
BODY = "ad1346-m3e3c"
ENDPOINT = "http://127.0.0.1:9222"
BOOT_SESSION = "ad1346-m3e3c-boot"


class _Clock:
    """A fixed clock: no test in this file moves it."""

    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


class _Page:
    """The fake engine's page; ``extract_text`` reads ``inner_text``."""

    async def inner_text(self, selector: str) -> str:
        return BODY

    def set_default_timeout(self, timeout: int) -> None:
        pass

    async def close(self) -> None:
        pass


class _Context:
    def __init__(self) -> None:
        self.pages = [_Page()]

    async def new_page(self) -> _Page:
        return self.pages[0]

    async def route(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def close(self) -> None:
        pass


class _Browser:
    def __init__(self) -> None:
        self.contexts = [_Context()]

    async def new_context(self, **kwargs: Any) -> _Context:
        return self.contexts[0]

    async def close(self) -> None:
        pass


class _Engines:
    """The fake engine and what it saw: ``"launch"`` for each launch and the endpoint of each CDP connect, in order."""

    def __init__(self) -> None:
        self.seen: list[str] = []

    @property
    def chromium(self) -> _Engines:
        return self

    async def start(self) -> _Engines:
        return self

    async def stop(self) -> None:
        pass

    async def launch(self, **kwargs: Any) -> _Browser:
        self.seen.append("launch")
        return _Browser()

    async def connect_over_cdp(self, endpoint: str) -> _Browser:
        self.seen.append(endpoint)
        return _Browser()


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


def _fake_engine(monkeypatch: pytest.MonkeyPatch) -> _Engines:
    """``async_playwright`` returns one recording fake engine, and the session's loop counts as able to spawn."""
    engines = _Engines()
    module = ModuleType("playwright.async_api")
    setattr(module, "async_playwright", lambda: engines)
    monkeypatch.setitem(sys.modules, "playwright", ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.async_api", module)
    monkeypatch.setattr("probos.tools.browser.session.loop_supports_subprocess", lambda loop: True)
    return engines


def _browser_config(config: SystemConfig) -> SystemConfig:
    """The browser tool and its bridge on."""
    config.browser_tool.enabled = True
    config.browser_tool.bridge_enabled = True
    return config


def _tool(service: AdmissionService | None) -> BrowserTool:
    """A browser tool over a runtime whose only attribute is ``admission_service``."""
    return BrowserTool(config=_browser_config(SystemConfig()).browser_tool, runtime=SimpleNamespace(admission_service=service))


async def test_a_booted_runtime_hands_its_service_to_the_engine_checks_through_its_browser_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BE1 (D212: the production hand-off; kills EB-6)."""
    engines = _fake_engine(monkeypatch)
    config = _browser_config(SystemConfig())
    config.admission.shadow_enabled = True
    config.onboarding.naming_ceremony = False
    config.proactive_cognitive.enabled = False
    config.qa.enabled = False
    runtime = ProbOSRuntime(config=config, data_dir=tmp_path / "data", llm_client=MockLLMClient())
    await asyncio.wait_for(runtime.start(), timeout=600)
    try:
        service = runtime.admission_service
        assert type(service) is AdmissionService, "premise: the boot built the shadow service"
        assert type(runtime.browser_tool) is BrowserTool, "premise: the boot wired the browser tool"
        seen: list[tuple[bool, str, object]] = []

        def record(self: AdmissionService, *, effect: str, presented_id: object) -> None:
            if effect == EFFECT_EGRESS:
                seen.append((self is service, effect, presented_id))

        monkeypatch.setattr(AdmissionService, "check_ticket", record)
        started = await runtime.browser_tool.invoke({"action": "extract_text", "session_id": BOOT_SESSION}, {"agent_id": AGENT_A})
        bridged = await runtime.browser_tool.connect_bridge_session(ENDPOINT, agent_id="captain", confirm=True)
        assert seen == [(True, "egress", AGENT_A), (True, "egress", "captain")], seen
        assert started.error is None and bridged["connected"] is True, (started, bridged)
        assert engines.seen == ["launch", ENDPOINT], engines.seen
    finally:
        await asyncio.wait_for(runtime.stop(), timeout=600)


async def test_each_engine_check_counts_missing_outside_a_hold_then_live_and_revoked(
    identities: IdentityService, stops: AgentStopService, tickets: TicketRegistry, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BE2 (#1604 property 1 at the two checks; D211, D213; kills EB-1, EB-2, EB-4)."""
    service = AdmissionService(identities, stops, tickets=tickets, loop=asyncio.get_running_loop())
    engines = _fake_engine(monkeypatch)
    tool = _tool(service)
    registry = ToolRegistry()
    registry.set_stop_gate(stops)
    registry.set_admission(service)
    registry.register(tool, default_permissions={"ensign": "read"})
    answers: list[tuple[object, object, object]] = []

    async def each(phase: str) -> None:
        through = await registry.check_and_invoke(AGENT_A, "browser", {"action": "extract_text", "session_id": f"{phase}-registry"})
        bridged = await tool.connect_bridge_session(ENDPOINT, agent_id=AGENT_A, confirm=True)
        other = await tool.invoke({"action": "extract_text", "session_id": f"{phase}-other"}, {"agent_id": AGENT_B})
        answers.append((through.error, bridged["connected"], other.error))

    await each("outside")
    hold = service.hold(presented_id=AGENT_A, work_kind="agentic_run", seam="agentic_run", child=False)
    try:
        await each("held")
        await stops.issue_stop(AGENT_A, reason="ad1346-m3e3c: the Captain stops the held work")
        await each("stopped")
    finally:
        hold.end()
    assert tickets.tally() == {
        ("issue", "ticket_issued"): 1,
        ("tool", "ticket_missing"): 1, ("tool", "ticket_live"): 1, ("tool", "ticket_revoked"): 1,
        ("egress", "ticket_missing"): 3, ("egress", "ticket_live"): 2,
        ("egress", "ticket_principal_mismatch"): 1, ("egress", "ticket_revoked"): 2,
    }
    assert engines.seen == ["launch", ENDPOINT, "launch"] * 2 + [ENDPOINT, "launch"], engines.seen
    assert answers[:2] == [(None, True, None)] * 2, answers
    assert answers[2][0] is not None and answers[2][1:] == (True, None), answers
    assert service.failures == 0


async def test_with_and_without_the_service_the_engine_checks_answer_identically(
    identities: IdentityService, stops: AgentStopService, tickets: TicketRegistry, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BE3 (#1604 property 12 at the two checks; kills EB-10)."""
    service = AdmissionService(identities, stops, tickets=tickets, loop=asyncio.get_running_loop())
    engines = _fake_engine(monkeypatch)

    async def answers(with_service: bool, phase: str) -> tuple[Any, ...]:
        tool = _tool(service if with_service else None)
        started = await tool.invoke({"action": "extract_text", "session_id": f"{phase}-start"}, {"agent_id": AGENT_A})
        bridged = await tool.connect_bridge_session(ENDPOINT, agent_id=AGENT_A, confirm=True)
        return (
            started.output, started.error, started.metadata,
            {key: value for key, value in bridged.items() if key != "session_id"},
        )

    first = (await answers(True, "outside"), await answers(False, "outside"))
    hold = service.hold(presented_id=AGENT_A, work_kind="agentic_run", seam="agentic_run", child=False)
    try:
        second = (await answers(True, "held"), await answers(False, "held"))
        await stops.issue_stop(AGENT_A, reason="ad1346-m3e3c: the golden test's stop")
        third = (await answers(True, "stopped"), await answers(False, "stopped"))
    finally:
        hold.end()
    assert first[0] == first[1] and second[0] == second[1] and third[0] == third[1]
    assert first[0][0] == {"session_id": "outside-start", "text": BODY}, "premise: the engine answered"
    assert first[0][3]["connected"] is True, "premise: the bridge connected"
    assert tickets.tally() == {
        ("issue", "ticket_issued"): 1,
        ("egress", "ticket_missing"): 2, ("egress", "ticket_live"): 2, ("egress", "ticket_revoked"): 2,
    }
    assert len(engines.seen) == 12 and service.failures == 0
