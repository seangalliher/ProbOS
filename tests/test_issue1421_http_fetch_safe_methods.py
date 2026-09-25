"""#1421: the governed HTTP fetch sends only GET and HEAD.

Before this fix every method a caller named reached the transport. Measured at
98266146: the agentic ``http_fetch`` tool, ``ship.fetch`` in ``run_python`` and a
decomposer DAG node each sent one DELETE, and the same node with consensus sent
seven -- one from the HttpFetchAgents, then six more from the red team verifying
it by sending it again.

Every test stubs DNS strictly (the test host and loopback, nothing else) and
builds ``httpx.AsyncClient`` on ``httpx.MockTransport``, which also captures the
red team's own client. The SSRF guard and BF-821's pin run for real. The #1421
names are imported inside the tests so the file collects on the unfixed tree.
"""

from __future__ import annotations

import asyncio
import http
import logging
import socket
import types
from typing import Any

import httpx
import pytest

from probos.agents.http_fetch import HttpFetchAgent
from probos.agents.red_team import RedTeamAgent
from probos.cognitive.agentic_dispatch import DispatchToolExecutor, register_mesh_intent_tools
from probos.cognitive.decomposer import DAGExecutor, is_capability_gap
from probos.config import ExecutionConfig, SystemConfig
from probos.consensus.quorum import QuorumEngine
from probos.execution.isolation import ExecutionRequest, SubprocessSandbox
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.runtime import ProbOSRuntime
from probos.security.url_guard import PinnedTarget
from probos.tools.code_execution_tool import CodeExecutionTool
from probos.tools.registry import ToolRegistry
from probos.types import IntentMessage, IntentResult, QuorumPolicy, TaskDAG, TaskNode

HOST = "api.example.test"
PUBLIC = "93.184.215.14"
URL = f"https://{HOST}/items/1"
_REAL_WAIT = HttpFetchAgent._wait_for_rate_limit
_ABSENT = object()

REFUSED = [
    pytest.param("POST", id="POST"),
    pytest.param("PUT", id="PUT"),
    pytest.param("PATCH", id="PATCH"),
    pytest.param("DELETE", id="DELETE"),
    pytest.param("delete", id="delete"),
    pytest.param("OPTIONS", id="OPTIONS"),
    pytest.param("TRACE", id="TRACE"),
    pytest.param("CONNECT", id="CONNECT"),
    pytest.param("PROPFIND", id="PROPFIND"),
    pytest.param("", id="empty"),
    pytest.param(" GET", id="leading-space"),
    pytest.param("GET\r\n", id="crlf"),
    pytest.param(None, id="None"),
    pytest.param(123, id="int"),
    pytest.param(b"GET", id="bytes"),
    pytest.param(http.HTTPMethod.DELETE, id="HTTPMethod.DELETE"),
]

SAFE = [
    pytest.param(_ABSENT, "GET", id="absent"),
    pytest.param("GET", "GET", id="GET"),
    pytest.param("get", "GET", id="get"),
    pytest.param("Get", "GET", id="Get"),
    pytest.param("HEAD", "HEAD", id="HEAD"),
    pytest.param("head", "HEAD", id="head"),
    pytest.param(http.HTTPMethod.GET, "GET", id="HTTPMethod.GET"),
]

CANONICAL = [
    pytest.param("GET", "GET", id="GET"),
    pytest.param("get", "GET", id="get"),
    pytest.param("Get", "GET", id="Get"),
    pytest.param("gEt", "GET", id="gEt"),
    pytest.param("HEAD", "HEAD", id="HEAD"),
    pytest.param("head", "HEAD", id="head"),
    pytest.param("hEaD", "HEAD", id="hEaD"),
    pytest.param(http.HTTPMethod.GET, "GET", id="HTTPMethod.GET"),
    pytest.param(http.HTTPMethod.HEAD, "HEAD", id="HTTPMethod.HEAD"),
]

NOT_SAFE = [
    pytest.param("DELETE", id="DELETE"),
    pytest.param("delete", id="delete"),
    pytest.param("POST", id="POST"),
    pytest.param("PUT", id="PUT"),
    pytest.param("PATCH", id="PATCH"),
    pytest.param("OPTIONS", id="OPTIONS"),
    pytest.param("TRACE", id="TRACE"),
    pytest.param("CONNECT", id="CONNECT"),
    pytest.param("PROPFIND", id="PROPFIND"),
    pytest.param("", id="empty"),
    pytest.param(" GET", id="leading-space"),
    pytest.param("GET ", id="trailing-space"),
    pytest.param("GET\r\n", id="crlf"),
    pytest.param("G\u0435T", id="cyrillic-ie"),
    pytest.param(None, id="None"),
    pytest.param(123, id="int"),
    pytest.param(1.0, id="float"),
    pytest.param(True, id="bool"),
    pytest.param(b"GET", id="bytes"),
    pytest.param(bytearray(b"GET"), id="bytearray"),
    pytest.param(["GET"], id="list"),
    pytest.param({"GET": 1}, id="dict"),
    pytest.param(http.HTTPMethod.DELETE, id="HTTPMethod.DELETE"),
    pytest.param(http.HTTPMethod.POST, id="HTTPMethod.POST"),
]

_EXPECTED_DATA = {
    "url": URL,
    "status_code": 200,
    "headers": {"content-length": "2"},
    "body": "ok",
    "body_length": 2,
    "truncated": False,
    "total_bytes": 2,
    "rate_limit_delay": 0.0,
}


def _refusal() -> str:
    from probos.agents.http_fetch import UNSAFE_METHOD_REFUSAL

    return UNSAFE_METHOD_REFUSAL


def _safe_fetch_method() -> Any:
    from probos.agents.http_fetch import safe_fetch_method

    return safe_fetch_method


# ── fixtures ──────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clean():
    HttpFetchAgent._inflight.clear()
    HttpFetchAgent._waiters.clear()
    HttpFetchAgent._domain_state.clear()
    yield
    HttpFetchAgent._inflight.clear()
    HttpFetchAgent._waiters.clear()
    HttpFetchAgent._domain_state.clear()


@pytest.fixture(autouse=True)
def _no_wait(monkeypatch):
    async def _no_wait(self, _domain, state):
        state.last_request_time = 0
        return 0.0

    monkeypatch.setattr(HttpFetchAgent, "_wait_for_rate_limit", _no_wait)


class _FakeDns:
    """``socket.getaddrinfo`` that knows the test host and loopback and refuses
    every other name, so no test here can resolve a real one."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, host: Any, port: Any = None, *args: Any, **kwargs: Any) -> list[Any]:
        name = host.decode("ascii") if isinstance(host, bytes) else str(host)
        self.calls.append(name)
        numeric = isinstance(port, int) or (isinstance(port, str) and port.isdigit())
        p = int(port) if numeric else 0
        if name == HOST:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC, p))]
        if name in ("127.0.0.1", "localhost"):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", p))]
        raise socket.gaierror(f"#1421 test DNS: {name!r} is not a test host")


@pytest.fixture
def dns(monkeypatch):
    fake = _FakeDns()
    monkeypatch.setattr(socket, "getaddrinfo", fake)
    return fake


def _sender(request: httpx.Request) -> str:
    agent = request.headers.get("user-agent", "")
    if agent == HttpFetchAgent.USER_AGENT:
        return "http_fetch"
    return "red_team" if agent.startswith("python-httpx") else f"other:{agent}"


def _install_transport(monkeypatch: pytest.MonkeyPatch, handler: Any) -> None:
    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )


class _RecordingTransport:
    def __init__(self) -> None:
        self.sent: list[tuple[Any, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.sent.append((request.method, _sender(request)))
        return httpx.Response(200, content=b"ok", request=request)


@pytest.fixture
def transport(monkeypatch):
    recorder = _RecordingTransport()
    _install_transport(monkeypatch, recorder)
    return recorder


def _judge_without_pinning(self: HttpFetchAgent, url: str) -> PinnedTarget:
    return PinnedTarget(HttpFetchAgent._validate_url(self, url), ())


def _bus_with_agents(n: int = 3) -> tuple[IntentBus, list[HttpFetchAgent]]:
    bus = IntentBus(SignalManager())
    agents = [HttpFetchAgent(agent_id=f"http-{i}", pool="http") for i in range(n)]
    for agent in agents:
        bus.subscribe(agent.id, agent.handle_intent, ["http_fetch"])
    return bus, agents


def _broker_runtime(cfg: ExecutionConfig, fetcher: HttpFetchAgent) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        config=types.SimpleNamespace(execution=cfg, dependency=None),
        registry=types.SimpleNamespace(all=lambda: [fetcher]),
        artifact_store=None,
        attachment_store=None,
    )


class _FakeEventLog:
    async def log(self, **kw: Any) -> int:
        return 1


class _FakeHebbian:
    def record_interaction(self, **kw: Any) -> None: ...

    def get_weight(self, *a: Any) -> float:
        return 0.5

    def record_verification(self, **kw: Any) -> None: ...


class _FakeTrust:
    def get_score(self, _id: str) -> float:
        return 0.5

    def record_outcome(self, *a: Any, **kw: Any) -> None: ...


def _stub_runtime(bus: IntentBus) -> ProbOSRuntime:
    """The real submit_intent / submit_intent_with_consensus, bound to a runtime
    carrying only what they read; exactly two red team agents, so the verifier
    count cannot follow a config default."""
    rt = ProbOSRuntime.__new__(ProbOSRuntime)
    rt.config = SystemConfig()
    c = rt.config.consensus
    rt.intent_bus = bus
    rt.event_log = _FakeEventLog()
    rt.hebbian_router = _FakeHebbian()
    rt._event_listeners = []
    rt._live_event_listeners = []
    rt._event_listener_tasks = set()
    rt._nats_events_wired = False
    rt.nats_bus = None
    rt._emergent_detector = None
    rt.quorum_engine = QuorumEngine(policy=QuorumPolicy(
        min_votes=c.min_votes,
        approval_threshold=c.approval_threshold,
        use_confidence_weights=c.use_confidence_weights,
    ))
    rt.red_team_agents = [RedTeamAgent(agent_id=f"rt-{i}", pool="red_team") for i in range(2)]
    rt.trust_network = _FakeTrust()
    rt.bridge_alerts = None
    rt.ward_room_router = None
    rt._last_shapley_values = {}
    rt.consensus_mode_for = lambda intent: "execute_then_vote"
    return rt


# ── every producer: an unsafe method sends nothing ───────────────


@pytest.mark.parametrize("method", ["DELETE", "POST"])
async def test_agentic_http_fetch_refuses_an_unsafe_method_before_any_request(
    dns, transport, method
):
    bus, _agents = _bus_with_agents()
    registry = ToolRegistry()
    register_mesh_intent_tools(registry, bus)
    executor = DispatchToolExecutor(registry=registry)

    async def _invoke(params: dict[str, Any]) -> Any:
        return await executor.invoke(
            "agent-a", "http_fetch", params,
            agent_department="engineering", agent_rank="ensign",
        )

    control = await _invoke({"url": URL})
    assert control.error is None and transport.sent == [("GET", "http_fetch")], (
        f"premise: a GET through the real tool is sent once: {control.error!r} {transport.sent}"
    )
    assert dns.calls, "premise: the GET consulted DNS"
    sent, looked_up = len(transport.sent), len(dns.calls)

    res = await _invoke({"url": URL, "method": method})

    assert transport.sent[sent:] == [], f"{method} reached the transport"
    assert dns.calls[looked_up:] == [], f"the refused {method} still resolved DNS"
    assert res.error == _refusal()


@pytest.mark.parametrize("method", REFUSED)
async def test_the_intent_path_refuses_every_unsafe_or_malformed_method(dns, transport, method):
    agent = HttpFetchAgent(agent_id="http-t2", pool="http")

    result = await agent.handle_intent(
        IntentMessage(intent="http_fetch", params={"url": URL, "method": method})
    )

    assert transport.sent == [], f"{method!r} reached the transport"
    assert dns.calls == [], f"the refused {method!r} still resolved DNS"
    assert result is not None and result.success is False
    assert result.error == _refusal()


@pytest.mark.parametrize("method", REFUSED)
async def test_fetch_governed_refuses_every_unsafe_or_malformed_method(dns, transport, method):
    agent = HttpFetchAgent(agent_id="http-t3", pool="http")

    result = await agent.fetch_governed(URL, method)

    assert transport.sent == [], f"{method!r} reached the transport"
    assert dns.calls == [], f"the refused {method!r} still resolved DNS"
    assert result == {"success": False, "error": _refusal()}


async def test_ship_fetch_raises_for_an_unsafe_method(dns, transport, tmp_path):
    fetcher = HttpFetchAgent(agent_id="http-broker", pool="http")
    cfg = ExecutionConfig(fetch_broker_enabled=True)
    tool = CodeExecutionTool(runtime=_broker_runtime(cfg, fetcher))
    workdir = tmp_path / "run"
    workdir.mkdir()
    env, broker = await tool._start_fetch_broker(cfg, workdir)
    assert broker is not None, "premise: the relay started with a real HttpFetchAgent behind it"
    try:
        result = await SubprocessSandbox(scratch_root=str(tmp_path)).run(
            ExecutionRequest(
                code=(
                    "import ship\n"
                    f"r = ship.fetch({URL!r})\n"
                    "print('STATUS=%d' % r['status_code'])\n"
                    "try:\n"
                    f"    ship.fetch({URL!r}, 'DELETE')\n"
                    "    print('SENT')\n"
                    "except ship.FetchError as e:\n"
                    "    print('REFUSED=' + str(e))\n"
                ),
                workdir=workdir,
                timeout_seconds=60,
                allow_network=False,
                env=env,
                import_workdir=True,
            )
        )
    finally:
        await broker.stop()

    assert result.success, result.stderr
    assert "STATUS=200" in result.stdout, "premise: the GET went through the real broker"
    assert transport.sent == [("GET", "http_fetch")], f"the DELETE reached the transport: {transport.sent}"
    assert "REFUSED=" + _refusal() in result.stdout, result.stdout


@pytest.mark.parametrize("use_consensus", [False, True], ids=["plain", "use_consensus"])
async def test_a_dag_node_with_an_unsafe_method_fails_without_sending(
    dns, transport, use_consensus
):
    async def _run(params: dict[str, Any]) -> TaskNode:
        bus, _agents = _bus_with_agents()
        dag = TaskDAG(nodes=[TaskNode(
            id="t1", intent="http_fetch", params=params, use_consensus=use_consensus,
        )])
        await DAGExecutor(runtime=_stub_runtime(bus), timeout=30.0).execute(dag)
        return dag.nodes[0]

    control = await _run({"url": URL, "method": "GET"})
    expected = [("GET", "http_fetch")] + ([("GET", "red_team")] * 6 if use_consensus else [])
    assert control.status == "completed" and sorted(transport.sent) == sorted(expected), (
        f"premise: 1 request plain, 7 with consensus (1 + 3 results x 2 verifiers): {transport.sent}"
    )
    before = len(transport.sent)

    node = await _run({"url": URL, "method": "DELETE"})

    assert transport.sent[before:] == [], f"the DELETE node sent {transport.sent[before:]}"
    assert node.status == "failed"
    results = node.result["results"] if use_consensus else node.result
    assert len(results) == 3
    assert [r.error for r in results] == [_refusal()] * 3


# ── GET and HEAD are unchanged ───────────────────────────────────


@pytest.mark.parametrize("path", ["intent", "fetch_governed"])
@pytest.mark.parametrize("method,canonical", SAFE)
async def test_safe_methods_are_sent_exactly_as_before(dns, transport, path, method, canonical):
    agent = HttpFetchAgent(agent_id="http-t6", pool="http")

    if path == "intent":
        params = {"url": URL} if method is _ABSENT else {"url": URL, "method": method}
        res = await agent.handle_intent(IntentMessage(intent="http_fetch", params=params))
        assert res is not None and res.success is True and res.error is None
        data = res.result
    else:
        out = await (
            agent.fetch_governed(URL) if method is _ABSENT else agent.fetch_governed(URL, method)
        )
        assert out["success"] is True
        data = out["data"]

    assert transport.sent == [(canonical, "http_fetch")]
    assert data == _EXPECTED_DATA
    assert dns.calls, "the SSRF guard resolved the host"


def test_redirects_never_change_a_safe_method():
    for status in range(100, 600):
        assert HttpFetchAgent._redirect_method("GET", status) == "GET", status
        assert HttpFetchAgent._redirect_method("HEAD", status) == "HEAD", status


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize("method", ["GET", "HEAD"])
async def test_redirects_never_change_a_safe_method_on_the_wire(monkeypatch, dns, method, status):
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.url.path == "/start":
            return httpx.Response(status, headers={"location": "/after"}, request=request)
        return httpx.Response(200, content=b"ok", request=request)

    _install_transport(monkeypatch, handler)
    monkeypatch.setattr(HttpFetchAgent, "_validate_and_pin", _judge_without_pinning)
    agent = HttpFetchAgent(agent_id=f"t7-{method}-{status}", pool="http")

    result = await agent._fetch_url(f"https://{HOST}/start", method)

    assert result["success"] is True, result
    assert methods == [method, method]


# ── the red team verifier ────────────────────────────────────────


@pytest.mark.parametrize("claimed_success", [True, False], ids=["claimed_success", "claimed_failure"])
async def test_the_red_team_never_resends_an_unsafe_method(dns, transport, claimed_success):
    verifier = RedTeamAgent(agent_id="rt-0", pool="red_team")
    intent = IntentMessage(intent="http_fetch", params={"url": URL, "method": "DELETE"})
    claimed = IntentResult(
        intent_id=intent.id,
        agent_id="http-0",
        success=claimed_success,
        result={"status_code": 200, "body_length": 2} if claimed_success else None,
        error=None if claimed_success else "refused",
    )
    before = verifier.confidence

    verdict = await verifier.verify("http-0", intent, claimed)

    assert transport.sent == [], "the verifier repeated a state-changing request"
    assert verdict.verified is (not claimed_success)
    assert bool(verdict.discrepancy) is claimed_success
    assert not is_capability_gap(verdict.discrepancy)
    assert verifier.confidence == before
    assert verdict.confidence == before


async def test_the_red_team_rechecks_a_get_as_before(dns, transport):
    verifier = RedTeamAgent(agent_id="rt-0", pool="red_team")
    intent = IntentMessage(intent="http_fetch", params={"url": URL, "method": "GET"})
    claimed = IntentResult(
        intent_id=intent.id,
        agent_id="http-0",
        success=True,
        result={"status_code": 200, "body_length": 2},
    )

    verdict = await verifier.verify("http-0", intent, claimed)

    assert transport.sent == [("GET", "red_team")]
    assert verdict.verified is True


# ── the refusal and the helper ───────────────────────────────────


def test_the_refusal_routes_to_the_captain_and_is_not_a_capability_gap():
    assert is_capability_gap("I can't do that"), "premise: the real gap regex fires"
    refusal = _refusal()
    assert not is_capability_gap(refusal)
    assert "GET and HEAD" in refusal
    assert "Captain" in refusal


@pytest.mark.parametrize("value,canonical", CANONICAL)
def test_safe_fetch_method_canonicalises(value, canonical):
    got = _safe_fetch_method()(value)

    assert got == canonical
    assert type(got) is str


@pytest.mark.parametrize("value", NOT_SAFE)
def test_safe_fetch_method_refuses(value):
    assert _safe_fetch_method()(value) is None


class _LyingUpper(str):
    def upper(self) -> str:  # type: ignore[override]
        return "GET"


class _LyingEq(str):
    def __eq__(self, other: object) -> bool:
        return True

    def __hash__(self) -> int:
        return hash("GET")


class _UpperReturnsSubclass(str):
    def upper(self) -> str:  # type: ignore[override]
        return _LyingEq("GET")


def test_safe_fetch_method_cannot_be_talked_into_a_safe_answer():
    from probos.agents.http_fetch import SAFE_FETCH_METHODS, safe_fetch_method

    assert _LyingUpper("DELETE").upper() == "GET", "premise: its own upper() answers GET"
    assert _LyingEq("DELETE") in SAFE_FETCH_METHODS, "premise: its own __eq__ makes it a member"
    for value in (_LyingUpper("DELETE"), _LyingEq("DELETE"), _UpperReturnsSubclass("DELETE")):
        assert safe_fetch_method(value) is None, type(value).__name__


async def test_coalescing_keys_on_the_canonical_method(monkeypatch, dns):
    entered = asyncio.Event()
    release = asyncio.Event()
    methods: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        entered.set()
        await release.wait()
        return httpx.Response(200, content=b"ok", request=request)

    _install_transport(monkeypatch, handler)
    first = HttpFetchAgent(agent_id="http-u4a", pool="http")
    second = HttpFetchAgent(agent_id="http-u4b", pool="http")

    tasks = [asyncio.create_task(first._fetch_url(URL, "get"))]
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        tasks.append(asyncio.create_task(second._fetch_url(URL, "GET")))
        await asyncio.sleep(0)
    finally:
        release.set()
    results = await asyncio.gather(*tasks)

    assert len(results) == 2 and all(r["success"] for r in results)
    assert methods == ["GET"], f"'get' and 'GET' for one URL did not share a request: {methods}"


async def test_the_refusal_precedes_dns_the_limiter_and_coalescing(monkeypatch, dns, transport, caplog):
    waits: list[str] = []

    async def _recording_wait(self, domain, state):
        waits.append(domain)
        return await _REAL_WAIT(self, domain, state)

    monkeypatch.setattr(HttpFetchAgent, "_wait_for_rate_limit", _recording_wait)
    agent = HttpFetchAgent(agent_id="http-u5", pool="http")

    with caplog.at_level(logging.INFO, logger="probos.agents.http_fetch"):
        refused = await agent._fetch_url(URL, "DELETE")

    assert dns.calls == [], "the refusal came after DNS"
    assert waits == [], "the refusal came after the per-domain limiter"
    assert HttpFetchAgent._inflight == {} and HttpFetchAgent._domain_state == {}
    assert transport.sent == []
    assert refused == {"success": False, "error": _refusal()}
    assert [r.getMessage() for r in caplog.records if r.name == "probos.agents.http_fetch"] == [
        "#1421: refused an http_fetch whose method is not GET or HEAD; "
        "no request was made"
    ]

    fetched = await agent._fetch_url(URL, "GET")

    assert fetched["success"] is True
    assert dns.calls and waits and HttpFetchAgent._domain_state, (
        "premise: a GET reaches DNS, the limiter and the domain state"
    )


class _NewlineRepr(str):
    """A method whose ``repr`` would start a forged log line."""

    def __repr__(self) -> str:
        return "'x'\nWARNING probos.agents.http_fetch: forged"


@pytest.mark.parametrize(
    "method",
    ["https://x.io", _NewlineRepr("PATCH"), "DELETE\r\nINJECTED"],
    ids=["host-in-method", "newline-repr", "crlf-in-method"],
)
async def test_the_refusal_log_carries_nothing_the_caller_supplied(dns, transport, caplog, method):
    # Review, 2026-09-25: `%.16r` of the method put a host in the log and let a
    # str subclass's repr forge a line. The refusal line must be fixed text.
    agent = HttpFetchAgent(agent_id="http-u5b", pool="http")
    with caplog.at_level(logging.INFO, logger="probos.agents.http_fetch"):
        refused = await agent._fetch_url(URL, method)
    # Premise: the call was refused, so a refusal line is what was logged.
    assert refused == {"success": False, "error": _refusal()}
    assert transport.sent == [] and dns.calls == []
    messages = [r.getMessage() for r in caplog.records if r.name == "probos.agents.http_fetch"]
    # Each input has its own discriminating check: the old line showed the host,
    # the forged repr text, and an escaped prefix of the CRLF method ("DELETE\\r...").
    assert not any("x.io" in m or "forged" in m or "DELETE" in m or "INJ" in m for m in messages)
    assert not any("\n" in m or "\r" in m for m in messages)
    assert messages == [
        "#1421: refused an http_fetch whose method is not GET or HEAD; "
        "no request was made"
    ]
