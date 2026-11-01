"""AD-1346 M3e3b (#1604): the egress sinks of ``http_fetch`` and the red team's verifier, and the image endpoint's
model-call check, in shadow.

``HttpFetchAgent._fetch_url`` and ``RedTeamAgent._verify_http_fetch`` call ``check_at`` with ``EFFECT_EGRESS``, and
``dispatch_image_gen`` calls it with ``SEAM_MODEL_CALL``. ``ProbOSRuntime.start`` hands ``HttpFetchAgent`` the service
through its class-level ``set_admission`` and shutdown sets it back to None; the red team reads it from the runtime
``_spawn_red_team`` hands each agent; ``dispatch_image_gen`` reads it from the runtime it is given.

- ES1  by AST: each egress ``Sink`` row's check function holds one ``check_at`` call, a statement of its body, with the
       row's service, the effect ``EFFECT_EGRESS`` and the row's presented id, on a line before its point or before its
       first reference to the next function of its chain; in its file each later link of the chain is referenced only
       in the function before it and in itself; the image endpoint's row holds one check, with ``SEAM_MODEL_CALL`` and
       ``agent_id``, on a line before its point.
- ES2  the production hand-off: after ``ProbOSRuntime.start`` with ``admission.shadow_enabled`` true, a member of the
       ``http`` pool, a red team agent and ``dispatch_image_gen`` given that runtime each hand ``check_ticket`` the
       runtime's service; after ``ProbOSRuntime.stop`` the class-level service is None.
- ES3  #1604 property 1 at the three checks: each counts ``ticket_missing`` outside a hold, ``ticket_live`` inside a
       hold the test makes and ``ticket_revoked`` after a Captain's stop; a coalesced pair is counted once per caller
       and requested once, a URL the floor refuses is counted and not requested, and the image endpoint's check for
       another agent counts ``ticket_principal_mismatch``.
- ES4  #1604 property 12 at the three checks: the agents and the dispatcher answer the same with the service and
       without it, with nothing carried, under a live ticket and after a Captain's stop.

ES3 and ES4 replace ``httpx.AsyncClient`` with a client over a recording ``httpx.MockTransport``, the fetch agent's
rate-limit wait, the two URL-floor functions ``probos.agents.http_fetch`` imports with the floor's shape check alone,
and ``socket.getaddrinfo`` with a recorder that raises. ES2 replaces ``httpx.AsyncClient``, the rate-limit wait and
``AdmissionService.check_ticket``, and boots a real runtime under ``tmp_path``, as
``tests/test_ad1346_admission_build_test_sink.py``'s BT2 does.
"""

from __future__ import annotations

import ast
import asyncio
import dataclasses
import socket
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import pytest_asyncio

from probos.admission import AdmissionService
from probos.admission.taxonomy import EFFECT_EGRESS, SEAM_MODEL_CALL
from probos.admission.tickets import TicketRegistry
from probos.agent_stop import AgentStopService
from probos.agents.http_fetch import HttpFetchAgent
from probos.agents.red_team import RedTeamAgent
from probos.cognitive.image_gen_dispatch import dispatch_image_gen
from probos.cognitive.llm_client import MockLLMClient
from probos.config import SystemConfig
from probos.crew_profile import CallsignRegistry
from probos.identity import AgentIdentityRegistry
from probos.identity_service import IdentityService
from probos.runtime import ProbOSRuntime
from probos.security.url_guard import PinnedTarget, check_url_shape
from probos.substrate.registry import AgentRegistry
from probos.types import IntentMessage, IntentResult
from tests.fixtures.ad1343_seam_census import calls, function
from tests.fixtures.ad1346_effect_census import (
    EGRESS_SITES,
    OtherClass,
    Sink,
    egress_points,
    references_outside,
    src_sources,
)

INSTANCE_ID = "ad1346-m3e3b-ship"
VESSEL_NAME = "Ad1346m3e3b"
AGENT_A = "ad1346-m3e3b-agent-a"
AGENT_B = "ad1346-m3e3b-agent-b"
FETCH_ID = "ad1346-m3e3b-fetch"
RED_ID = "ad1346-m3e3b-red"
BODY = "ad1346-m3e3b"
PROMPT = "ad1346-m3e3b chart"
INTENT_URL = "https://ad1346-m3e3b.test/intent"
GOVERNED_URL = "https://ad1346-m3e3b.test/governed"
SHARED_URL = "https://ad1346-m3e3b.test/shared"
VERIFIED_URL = "https://ad1346-m3e3b.test/verified"
REFUSED_URL = "http://127.0.0.1/ad1346-m3e3b"
IMAGE_BASE = "https://ad1346-m3e3b-images.test/v1"
IMAGE_URL = f"{IMAGE_BASE}/images/generations"
_REFUSED = {"success": False, "error": "SSRF protection: Blocked private/reserved IP: 127.0.0.1"}
_FETCH_ROW = ("src/probos/agents/http_fetch.py", "HttpFetchAgent._follow_and_fetch")
_VERIFY_ROW = ("src/probos/agents/red_team.py", "RedTeamAgent._verify_http_fetch")
_IMAGE_ROW = ("src/probos/cognitive/image_gen_dispatch.py", "dispatch_image_gen")


class _Clock:
    """A fixed clock: no test in this file moves it."""

    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


class _Net:
    """What the replaced network saw: each URL the transport answered and each call of the raising resolver."""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self.lookups: list[tuple[Any, ...]] = []


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


def _offline(monkeypatch: pytest.MonkeyPatch, *, resolver: bool = True) -> _Net:
    """A recording transport answers every ``httpx.AsyncClient`` made from here on with 200 and ``BODY``; the fetch agent
    waits for no rate-limit slot and consults no egress policy. With ``resolver``, the URL floor keeps its shape check
    alone and ``socket.getaddrinfo`` raises."""
    net = _Net()

    def answer(request: httpx.Request) -> httpx.Response:
        net.sent.append(str(request.url))
        return httpx.Response(200, text=BODY)

    transport = httpx.MockTransport(answer)
    real_client = httpx.AsyncClient

    def client(**kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("transport", None)
        return real_client(transport=transport, **kwargs)

    async def no_wait(self: HttpFetchAgent, domain: str, state: Any) -> float:
        state.last_request_time = 0
        return 0.0

    monkeypatch.setattr(httpx, "AsyncClient", client)
    monkeypatch.setattr(HttpFetchAgent, "_wait_for_rate_limit", no_wait)
    monkeypatch.setattr(HttpFetchAgent, "_egress_policy", None)
    if resolver:
        def refuse(*args: Any, **kwargs: Any) -> Any:
            net.lookups.append(args)
            raise OSError("ad1346-m3e3b: no name is resolved")

        monkeypatch.setattr("probos.agents.http_fetch.validate_public_url", lambda url, resolve=True: check_url_shape(url))
        monkeypatch.setattr("probos.agents.http_fetch.validate_and_pin_public_url", lambda url: PinnedTarget(check_url_shape(url)))
        monkeypatch.setattr(socket, "getaddrinfo", refuse)
    return net


def _image_tier(config: SystemConfig) -> SystemConfig:
    """The image tier on, with no wellness review line."""
    config.avatars.image_gen_enabled = True
    config.avatars.image_gen_wellness_review_required = False
    config.cognitive.llm_base_url_image_gen = IMAGE_BASE
    config.cognitive.llm_model_image_gen = "ad1346-m3e3b-image"
    return config


def _image_runtime(service: AdmissionService | None) -> SimpleNamespace:
    """What ``dispatch_image_gen`` reads from its runtime: a real ``SystemConfig`` with the image tier on, no attachment
    store (the transport's answer does not parse, so none is reached) and ``admission_service``."""
    return SimpleNamespace(config=_image_tier(SystemConfig()), attachment_store=None, admission_service=service)


def _claimed(intent: IntentMessage) -> IntentResult:
    """A fetch agent's claimed success for ``intent``, with the status and body length the transport answers."""
    return IntentResult(
        intent_id=intent.id, agent_id=FETCH_ID, success=True, result={"status_code": 200, "body_length": len(BODY)},
        confidence=0.8,
    )


def test_each_egress_sink_and_the_image_endpoint_hold_one_check_before_the_request() -> None:
    """ES1 (D204 to D207; AD-1346 M3e3c: D211, D214; kills EH-8, EH-12, EH-13, EB-3, EB-5, EB-7, EB-9)."""
    lines: dict[tuple[str, str], list[int]] = {}
    for path, scope, line, _primitive, _shape in egress_points():
        lines.setdefault((path, scope), []).append(line)
    sinks = [(site, cover) for site, (_n, cover) in EGRESS_SITES.items() if isinstance(cover, Sink)]
    assert sorted(site for site, _cover in sinks) == [
        _FETCH_ROW,
        _VERIFY_ROW,
        ("src/probos/tools/browser/session.py", "BrowserSession._connect_impl"),  # AD-1346 M3e3c
        ("src/probos/tools/browser/session.py", "BrowserSession._start_impl"),  # AD-1346 M3e3c
    ]
    for (path, scope), cover in sinks:
        fn = function(path, cover.check)
        (call,) = [node for node in ast.walk(fn) if calls("check_at")(node)]
        assert [ast.unparse(arg) for arg in call.args] == [cover.service], (path, cover.check)
        keywords = {keyword.arg: ast.unparse(keyword.value) for keyword in call.keywords}
        assert keywords == {"effect": "EFFECT_EGRESS", "presented_id": cover.presented}, (path, cover.check, keywords)
        assert any(isinstance(stmt, ast.Expr) and stmt.value is call for stmt in fn.body), (path, cover.check)
        if cover.check == scope:
            before = min(lines[(path, scope)])
        else:
            name = (cover.via[0] if cover.via else scope).rsplit(".", 1)[-1]
            refs = [node.lineno for node in ast.walk(fn) if isinstance(node, ast.Attribute) and node.attr == name]
            assert refs, (path, cover.check, name)
            before = min(refs)
        assert call.lineno < before, (path, cover.check, call.lineno, before)
        tree = ast.parse(src_sources()[path], filename=path)
        chain = (cover.check, *cover.via, scope)
        for caller, callee in zip(chain, chain[1:]):
            if caller != callee:
                assert references_outside(tree, callee.rsplit(".", 1)[-1], (caller, callee)) == [], (path, callee)
    own = [site for site, (_n, cover) in EGRESS_SITES.items() if isinstance(cover, OtherClass) and cover.check == site]
    assert own == [_IMAGE_ROW]
    (call,) = [node for node in ast.walk(function(*_IMAGE_ROW)) if calls("check_at")(node)]
    keywords = {keyword.arg: ast.unparse(keyword.value) for keyword in call.keywords}
    assert keywords == {"effect": "SEAM_MODEL_CALL", "presented_id": "agent_id"}, keywords
    assert call.lineno < min(lines[_IMAGE_ROW])


async def test_a_booted_runtime_hands_its_service_to_the_three_checks_and_its_stop_releases_the_fetch_agents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ES2 (D203, D205, D206: the production hand-off; kills EH-4, EH-5, EH-6)."""
    monkeypatch.setattr(HttpFetchAgent, "_admission", None)  # restored after the test, whatever the boot leaves
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
        seen: list[tuple[bool, str, object]] = []

        def record(self: AdmissionService, *, effect: str, presented_id: object) -> None:
            if effect in (EFFECT_EGRESS, SEAM_MODEL_CALL):
                seen.append((self is service, effect, presented_id))

        monkeypatch.setattr(AdmissionService, "check_ticket", record)
        net = _offline(monkeypatch, resolver=False)
        fetcher = runtime.registry.get_by_pool("http")[0]
        assert type(fetcher) is HttpFetchAgent and runtime.red_team_agents, "premise: the fleet's fetch pool and red team"
        assert await fetcher.fetch_governed(REFUSED_URL) == _REFUSED
        intent = IntentMessage(intent="http_fetch", params={"url": VERIFIED_URL})
        await runtime.red_team_agents[0].verify(FETCH_ID, intent, _claimed(intent))
        _image_tier(runtime.config)
        await dispatch_image_gen(runtime, agent_id=AGENT_A, prompt=PROMPT)
        assert seen == [(True, "egress", None), (True, "egress", None), (True, "model_call", AGENT_A)], seen
        assert VERIFIED_URL in net.sent and IMAGE_URL in net.sent and REFUSED_URL not in net.sent, net.sent
    finally:
        await asyncio.wait_for(runtime.stop(), timeout=600)
    assert HttpFetchAgent._admission is None


async def test_each_new_check_counts_missing_outside_a_hold_then_live_and_revoked(
    identities: IdentityService, stops: AgentStopService, tickets: TicketRegistry, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ES3 (#1604 property 1 at the three checks; kills EH-1, EH-2, EH-3, EH-7, EH-9, EH-10)."""
    service = AdmissionService(identities, stops, tickets=tickets, loop=asyncio.get_running_loop())
    net = _offline(monkeypatch)
    monkeypatch.setattr(HttpFetchAgent, "_admission", service)
    first = HttpFetchAgent(pool="ad1346-m3e3b", agent_id=f"{FETCH_ID}-1")
    second = HttpFetchAgent(pool="ad1346-m3e3b", agent_id=f"{FETCH_ID}-2")
    verifier = RedTeamAgent(pool="ad1346-m3e3b", agent_id=RED_ID, runtime=SimpleNamespace(admission_service=service))
    images = _image_runtime(service)
    intent = IntentMessage(intent="http_fetch", params={"url": VERIFIED_URL})
    refused: list[dict[str, Any]] = []

    async def each() -> None:
        await first.handle_intent(IntentMessage(intent="http_fetch", params={"url": INTENT_URL}))
        await first.fetch_governed(GOVERNED_URL)
        await asyncio.gather(first._fetch_url(SHARED_URL, "GET"), second._fetch_url(SHARED_URL, "GET"))
        refused.append(await first.fetch_governed(REFUSED_URL))
        await verifier.verify(FETCH_ID, intent, _claimed(intent))
        await dispatch_image_gen(images, agent_id=AGENT_A, prompt=PROMPT)
        await dispatch_image_gen(images, agent_id=AGENT_B, prompt=PROMPT)

    await each()
    hold = service.hold(presented_id=AGENT_A, work_kind="agentic_run", seam="agentic_run", child=False)
    try:
        await each()
        await stops.issue_stop(AGENT_A, reason="ad1346-m3e3b: the Captain stops the held work")
        await each()
    finally:
        hold.end()
    assert tickets.tally() == {
        ("issue", "ticket_issued"): 1,
        ("egress", "ticket_missing"): 6, ("egress", "ticket_live"): 6, ("egress", "ticket_revoked"): 6,
        ("model_call", "ticket_missing"): 2, ("model_call", "ticket_live"): 1,
        ("model_call", "ticket_principal_mismatch"): 1, ("model_call", "ticket_revoked"): 2,
    }
    assert net.sent == [INTENT_URL, GOVERNED_URL, SHARED_URL, VERIFIED_URL, IMAGE_URL, IMAGE_URL] * 3, net.sent
    assert refused == [_REFUSED] * 3
    assert net.lookups == [] and service.failures == 0


async def test_with_and_without_the_service_the_three_checks_answer_identically(
    identities: IdentityService, stops: AgentStopService, tickets: TicketRegistry, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ES4 (#1604 property 12 at the three checks; kills EH-11)."""
    service = AdmissionService(identities, stops, tickets=tickets, loop=asyncio.get_running_loop())
    net = _offline(monkeypatch)
    fetch = IntentMessage(intent="http_fetch", params={"url": INTENT_URL})
    verify = IntentMessage(intent="http_fetch", params={"url": VERIFIED_URL})

    async def answers(with_service: bool) -> tuple[Any, ...]:
        held = service if with_service else None
        monkeypatch.setattr(HttpFetchAgent, "_admission", held)
        fetcher = HttpFetchAgent(pool="ad1346-m3e3b", agent_id=FETCH_ID)
        verifier = RedTeamAgent(pool="ad1346-m3e3b", agent_id=RED_ID, runtime=SimpleNamespace(admission_service=held))
        handled = await fetcher.handle_intent(fetch)
        verdict = await verifier.verify(FETCH_ID, verify, _claimed(verify))
        return (
            None if handled is None else (handled.success, handled.result, handled.error, handled.confidence),
            await fetcher.fetch_governed(GOVERNED_URL),
            {key: value for key, value in dataclasses.asdict(verdict).items() if key != "timestamp"},
            await dispatch_image_gen(_image_runtime(held), agent_id=AGENT_A, prompt=PROMPT),
        )

    first = (await answers(True), await answers(False))
    hold = service.hold(presented_id=AGENT_A, work_kind="agentic_run", seam="agentic_run", child=False)
    try:
        second = (await answers(True), await answers(False))
        await stops.issue_stop(AGENT_A, reason="ad1346-m3e3b: the golden test's stop")
        third = (await answers(True), await answers(False))
    finally:
        hold.end()
    assert first[0] == first[1] and second[0] == second[1] and third[0] == third[1]
    assert first[0][1]["success"] is True and first[0][2]["verified"] is True, "premise: each request was answered"
    assert tickets.tally() == {
        ("issue", "ticket_issued"): 1,
        ("egress", "ticket_missing"): 3, ("egress", "ticket_live"): 3, ("egress", "ticket_revoked"): 3,
        ("model_call", "ticket_missing"): 1, ("model_call", "ticket_live"): 1, ("model_call", "ticket_revoked"): 1,
    }
    assert len(net.sent) == 24 and net.lookups == [] and service.failures == 0
