"""BF-945 (#1720): the red team's http_fetch verifier applies the fetch agent's URL floor.

Real: the ``RedTeamAgent``, the URL guard and pin, the fetch agent's own floor and request path and, in the chain
test, the runtime's ``submit_intent_with_consensus``. Replaced in every test: ``socket.getaddrinfo`` (a resolver that
knows its own names) and ``httpx.AsyncClient`` (on a recording ``httpx.MockTransport``). Replaced where a test needs
it: the fetch agent's class-level egress policy (the egress test) and, in the chain test, the fetch agents'
``_wait_for_rate_limit`` (no wait), the trust network (a recorder), ``RedTeamAgent._verify_http_fetch`` (a wrapper
that makes the name change its answer, then calls the real method) and the runtime itself: ``_stub_runtime`` of
``test_issue1421_http_fetch_safe_methods`` binds the real ``submit_intent_with_consensus`` to a runtime, with stubs for
its event log and Hebbian router and ``consensus_mode_for`` fixed to ``execute_then_vote``. The class holds the cases
the tree before BF-945 fails; the functions before it pass on both. No BF-945 name is imported.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
import types
from typing import Any
from urllib.parse import urlparse

import httpx
import pytest

from probos.agents.http_fetch import HttpFetchAgent
from probos.agents.red_team import RedTeamAgent
from probos.cognitive.decomposer import is_capability_gap
from probos.types import IntentMessage, IntentResult

NAME, PUBLIC, SECOND = "api.example.test", "93.184.215.14", "93.184.215.15"
URL = f"https://{NAME}/items/1"
UNREACHED = "Verifier cannot reach URL but agent claims success"
REFUSAL = "Agent claims success for a URL that the fetch floor refuses, so it was not re-fetched"
FAULT = "The URL floor could not judge the URL, so it was not re-fetched"
_LOGGER = "probos.agents.red_team"
_AT = "@"  # joins the "credentials" URL below: a tool's output redacts a literal user:password@host, so a reader could not copy it

class _Resolver:
    """``socket.getaddrinfo``: a list answers every call, a list of lists one per call (the last repeated), an exception
    is raised; an address literal answers itself; any other name is refused."""

    def __init__(self, answers: dict[str, Any]) -> None:
        self.answers, self.calls = answers, []

    def __call__(self, host: Any, *_args: Any, **_kwargs: Any) -> list[Any]:
        name = host.decode("ascii") if isinstance(host, bytes) else str(host)
        self.calls.append(name)
        answer = self.answers.get(name)
        if isinstance(answer, Exception):
            raise answer
        if answer is None:
            try:
                ipaddress.ip_address(name)
            except ValueError:
                raise socket.gaierror(f"not a test name: {name!r}") from None
            answer = [name]
        elif isinstance(answer[0], list):
            answer = answer[min(self.calls.count(name), len(answer)) - 1]
        return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in answer]


def _rig(monkeypatch: pytest.MonkeyPatch, answers: dict[str, Any] | None = None, handler: Any = None):
    """The resolver and a transport recording each request (200 and ``ok``, ``handler``'s response, or the exception
    ``handler`` is). Once per test: it wraps ``httpx.AsyncClient``."""
    names = {NAME: [PUBLIC], "localtest.me": ["127.0.0.1"], "boom.example.test": UnicodeError("label too long")}
    resolver = _Resolver({**names, **(answers or {})})
    monkeypatch.setattr(socket, "getaddrinfo", resolver)
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if isinstance(handler, Exception):
            raise handler
        return handler(request) if handler else httpx.Response(200, content=b"ok", request=request)

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(answer), **kw))
    return resolver, seen


async def _verify(url: str, success: bool = True, *, status: int = 200, length: int = 2,
                  verifier: RedTeamAgent | None = None) -> Any:
    intent = IntentMessage(intent="http_fetch", params={"url": url})
    claimed = IntentResult(
        intent_id=intent.id, agent_id="http-0", success=success, error=None if success else "refused",
        result={"status_code": status, "body_length": length} if success else None,
    )
    return await (verifier or RedTeamAgent(agent_id="rt-0", pool="red_team")).verify("http-0", intent, claimed)


AS_BEFORE = [  # id, claimed success, claimed status, claimed length, transport answer, verified, discrepancy
    ("verified", True, 200, 2, None, True, ""),
    ("claims-failure-but-reachable", False, 200, 2, None, False, "Agent claims failure but URL is reachable"),
    ("status-mismatch", True, 204, 2, None, False, "Status code mismatch: expected=200 actual=204"),
    ("unreachable", True, 200, 2, httpx.ConnectError("down"), False, UNREACHED),
]
REFUSED = [  # id, url, what the log names: the reason without a scheme's value, or a raising floor's exception class
    ("loopback", "http://127.0.0.1:8080/admin", "Blocked private/reserved IP: 127.0.0.1"),
    ("link-local-metadata", "http://169.254.169.254/latest/meta-data/", "Blocked private/reserved IP: 169.254.169.254"),
    ("private", "http://10.0.0.5/", "Blocked private/reserved IP: 10.0.0.5"),
    ("reserved", "http://240.0.0.1/", "Blocked private/reserved IP: 240.0.0.1"),
    ("name-to-loopback", "http://localtest.me/", "Blocked private/reserved IP: 127.0.0.1"),
    ("unresolvable", "http://nowhere.example.test/", "Cannot resolve hostname: nowhere.example.test"),
    ("file-scheme", "file:///etc/passwd", "Blocked scheme"),
    ("userinfo-no-scheme", "acct-9f3b:s3cret" + _AT + "api.example.test/items/1", "Blocked scheme"),
    # refused for its destination, not its userinfo: it pins that the log omits the userinfo
    # (a public host with userinfo is approved, as before the change)
    ("credentials", "http://user:s3cret" + _AT + "169.254.169.254/latest/", "Blocked private/reserved IP: 169.254.169.254"),
    ("floor-raises", "http://boom.example.test/", "UnicodeError"),
]


@pytest.mark.parametrize("case", AS_BEFORE, ids=[case[0] for case in AS_BEFORE])
async def test_a_url_that_passes_the_floor_is_verified_as_before(monkeypatch, case):
    _label, success, status, length, answer, verified, discrepancy = case
    _resolver, seen = _rig(monkeypatch, handler=answer)
    verdict = await _verify(URL, success, status=status, length=length)
    assert (verdict.verified, verdict.discrepancy) == (verified, discrepancy) and len(seen) == 1


async def test_a_redirect_is_not_followed(monkeypatch):
    answered: list[httpx.Request] = []

    def redirect_once(request: httpx.Request) -> httpx.Response:
        answered.append(request)
        return httpx.Response(302 if len(answered) == 1 else 200, headers={"location": "http://127.0.0.1/admin"}, request=request)

    _resolver, seen = _rig(monkeypatch, handler=redirect_once)
    verdict = await _verify(URL)
    assert len(seen) == 1 and seen[0].url.host in (NAME, PUBLIC), [str(request.url) for request in seen]
    assert verdict.discrepancy == "Status code mismatch: expected=302 actual=200"


class TestTheVerifierJudgesTheUrlAsTheFetchAgentDoes:
    @pytest.mark.parametrize("success", [True, False], ids=["claimed-success", "claimed-failure"])
    @pytest.mark.parametrize("label,url,logged", REFUSED, ids=[row[0] for row in REFUSED])
    async def test_a_url_the_floor_refuses_or_cannot_judge_is_not_requested(
        self, monkeypatch, caplog, label, url, logged, success,
    ):
        _resolver, seen = _rig(monkeypatch)
        assert (await _verify(URL)).verified is True and len(seen) == 1, "premise: an approved URL is requested once"
        seen.clear()
        verifier = RedTeamAgent(agent_id="rt-0", pool="red_team")
        before = verifier.confidence
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            verdict = await _verify(url, success, verifier=verifier)
        expected = (False, FAULT) if label == "floor-raises" else (not success, REFUSAL if success else "")
        assert seen == [], "a URL the floor refuses or cannot judge was requested"
        assert (verdict.verified, verdict.discrepancy) == expected
        assert not is_capability_gap(expected[1]) and verdict.confidence == verifier.confidence == before
        host = urlparse(url).hostname or "-"  # the log names the host, or - for a URL with none (file:///...)
        verb = "could not judge" if label == "floor-raises" else "refused"
        assert f"{verb} {host} ({logged})" in caplog.text
        assert not any(text in caplog.text for text in ("s3cret", "acct-9f3b", "label too long")), caplog.text

    @pytest.mark.parametrize("answers", [[PUBLIC], [[PUBLIC], ["127.0.0.1"]]], ids=["stable", "name-changes-its-answer"])
    async def test_the_request_goes_to_the_approved_address_and_speaks_the_name(self, monkeypatch, answers):
        resolver, seen = _rig(monkeypatch, {NAME: answers})
        verdict = await _verify(URL)
        (request,) = seen
        assert (request.url.host, request.headers.get("host"), request.extensions.get("sni_hostname")) == (PUBLIC, NAME, NAME)
        assert resolver.calls == [NAME] and verdict.verified is True

    @pytest.mark.parametrize(
        "first,second,attempts,answered",
        [
            (httpx.ConnectTimeout, None, 2, True),
            (httpx.ConnectError, None, 2, True),
            (httpx.ConnectTimeout, httpx.ConnectTimeout, 2, False),
            (httpx.ReadTimeout, None, 1, False),
            (httpx.WriteTimeout, None, 1, False),
        ],
        ids=["connect-timeout-then-answer", "connect-error-then-answer", "connect-timeout-twice",
             "read-timeout-no-fallback", "write-timeout-no-fallback"],
    )
    async def test_the_next_approved_address_is_tried_only_after_a_failed_connect(
        self, monkeypatch, first, second, attempts, answered,
    ):
        def handler(request: httpx.Request) -> httpx.Response:
            failure = first if request.url.host == PUBLIC else second
            if failure is not None:
                raise failure("this address", request=request)
            return httpx.Response(200, content=b"ok", request=request)

        resolver, seen = _rig(monkeypatch, {NAME: [PUBLIC, SECOND]}, handler=handler)
        verdict = await _verify(URL)
        tried = [(r.url.host, r.headers.get("host"), r.extensions.get("sni_hostname")) for r in seen]
        assert tried == [(PUBLIC, NAME, NAME), (SECOND, NAME, NAME)][:attempts]
        assert (verdict.verified, verdict.discrepancy) == ((True, "") if answered else (False, UNREACHED))
        assert resolver.calls == [NAME]

    @pytest.mark.parametrize(
        "answer,success,verified,discrepancy",
        [(False, True, False, REFUSAL), (False, False, True, ""), (True, True, True, "")],
        ids=["denies-claimed-success", "denies-claimed-failure", "allows"],
    )
    async def test_the_egress_policy_the_fetch_agent_holds_decides_for_the_verifier(
        self, monkeypatch, caplog, answer, success, verified, discrepancy,
    ):
        _resolver, seen = _rig(monkeypatch)
        calls: list[str] = []
        monkeypatch.setattr(
            HttpFetchAgent, "_egress_policy", types.SimpleNamespace(is_allowed=lambda url: calls.append(url) or answer),
        )
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            verdict = await _verify(URL, success)
        assert calls == [URL] and len(seen) == int(answer)
        assert (verdict.verified, verdict.discrepancy) == (verified, discrepancy)
        assert ("Egress policy: blocked by AD-456b runtime sandboxing" in caplog.text) is (not answer)

    async def test_a_fetch_the_verifier_cannot_reproduce_is_not_confirmed_and_costs_the_fetch_agent_trust(self, monkeypatch):
        from tests.test_issue1421_http_fetch_safe_methods import _bus_with_agents, _stub_runtime

        async def no_wait(self, _domain, state):
            state.last_request_time = 0
            return 0.0

        monkeypatch.setattr(HttpFetchAgent, "_wait_for_rate_limit", no_wait)
        resolver, seen = _rig(monkeypatch)
        outcomes: list[tuple[str, bool]] = []
        trust = types.SimpleNamespace(
            get_score=lambda _id: 0.5, record_outcome=lambda agent_id, *, success, **_kw: outcomes.append((agent_id, success)),
        )

        async def one_round():
            for table in (HttpFetchAgent._inflight, HttpFetchAgent._waiters, HttpFetchAgent._domain_state):
                table.clear()
            seen.clear()
            outcomes.clear()
            runtime = _stub_runtime(_bus_with_agents()[0])
            runtime.trust_network = trust
            out = await runtime.submit_intent_with_consensus("http_fetch", params={"url": URL}, timeout=30.0)
            rechecks = [r for r in seen if r.headers["user-agent"] != HttpFetchAgent.USER_AGENT]
            return [(v.verified, v.discrepancy) for v in out["verifications"]], list(outcomes), rechecks

        verdicts, trusted, rechecks = await one_round()
        assert verdicts == [(True, "")] * 6 and len(rechecks) == 6, "premise: 2 verifiers x 3 results, all verified"
        assert trusted == [(f"http-{i}", True) for i in range(3)], "premise: the round records trust"
        recheck = RedTeamAgent._verify_http_fetch

        async def name_changes_its_answer(self, *args, **kwargs):
            resolver.answers[NAME] = ["127.0.0.1"]
            return await recheck(self, *args, **kwargs)

        monkeypatch.setattr(RedTeamAgent, "_verify_http_fetch", name_changes_its_answer)
        verdicts, trusted, rechecks = await one_round()
        assert seen, "premise: the fetch agents fetched at the public address"
        assert verdicts == [(False, REFUSAL)] * 6 and rechecks == []
        assert trusted == [(f"http-{i}", False) for i in range(3)]
