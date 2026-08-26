"""BF-821: the connection lands on the address the guard approved.

`check_resolved_address` resolved the hostname, judged every address it mapped
to, then threw the addresses away and answered about the URL *string*. httpx
resolved the same name again when it connected. Two lookups, no guarantee they
agree -- so a nameserver answering differently for the two put a connection on
loopback carrying the guard's blessing. Measured on `39373c76`, against a real
`HTTPServer`::

    CONTROL  guard on a loopback-first name -> 'Blocked private/reserved IP: 127.0.0.1'
    PREMISE  guard on the FIRST (public) answer -> None
    A REBIND -> HTTP 200 body='LOOPBACK REACHED'
    A lookups: guard=1 connector=1
    A victim hits: ['/x']

**Every assertion here is about the address actually connected to, never about
the guard's verdict.** A verdict assertion is what shipped this bug: the guard
was right every single time, and the connection went somewhere else.

Every test that stubs resolution carries a control proving the stub reaches the
code under test. Without one, a green result and a stub that never fired are
the same observation.
"""

from __future__ import annotations

import asyncio
import datetime
import socket
import ssl
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx
import pytest

from probos.agents.http_fetch import DomainRateState, HttpFetchAgent
from probos.security import url_guard
from probos.security.url_guard import (
    PinnedTarget,
    check_resolved_address,
    resolve_and_pin,
    validate_and_pin_public_url,
    validate_public_url,
)

# A public address that never leaves the test: the guard approves it and the
# resolver stub is what decides where it actually points.
PUBLIC = "93.184.216.34"


@pytest.fixture(autouse=True)
def _clean():
    HttpFetchAgent._inflight.clear()
    HttpFetchAgent._waiters.clear()
    HttpFetchAgent._domain_state.clear()
    # Another module in the same xdist worker may have left this set.
    HttpFetchAgent._egress_policy = None
    yield
    HttpFetchAgent._inflight.clear()
    HttpFetchAgent._waiters.clear()
    HttpFetchAgent._domain_state.clear()
    HttpFetchAgent._egress_policy = None


# ── infrastructure ───────────────────────────────────────────────


class _Recorder:
    """A real HTTP server on one loopback address, recording what reached it.

    ``port`` is settable so two recorders can share ONE port across two
    loopback addresses -- which is what makes the seam test an assertion about
    the address connected to rather than about the URL.
    """

    def __init__(
        self, address: str, body: bytes, *, port: int = 0, status: int = 200
    ) -> None:
        self.hits: list[str] = []
        self.hosts: list[str] = []
        recorder = self

        class _H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def do_GET(self) -> None:  # noqa: N802
                recorder.hits.append(self.path)
                recorder.hosts.append(self.headers.get("Host", ""))
                self.send_response(status)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_a: object) -> None:
                pass

        self._srv = HTTPServer((address, port), _H)
        self.address = address
        self.port = self._srv.server_port

    def serve(self) -> None:
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()

    def close(self) -> None:
        self._srv.shutdown()
        self._srv.server_close()


class _Resolver:
    """Answers the guard and the connector differently, and counts both.

    The guard resolves the ``str`` hostname it got from ``urlparse``; anyio
    IDNA-encodes before resolving, so httpx's lookup arrives as ``bytes``.
    Keying the answer on that is the rebinding threat model exactly -- the
    guard gets one answer, the thing that opens the socket gets another -- and
    unlike a call counter it does not have to be re-tuned whenever either side
    changes how many times it looks up.
    """

    def __init__(
        self,
        guard: dict[str, list[str]],
        connector: dict[str, list[str]] | None = None,
    ) -> None:
        self.guard_answers = guard
        self.connector_answers = connector if connector is not None else guard
        self.guard_lookups: list[str] = []
        self.connector_lookups: list[str] = []
        self._real = socket.getaddrinfo

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(socket, "getaddrinfo", self)

    def __call__(self, host, port, *args, **kwargs):  # noqa: ANN001, ANN002
        from_connector = isinstance(host, bytes)
        name = host.decode("ascii") if from_connector else host
        table = self.connector_answers if from_connector else self.guard_answers
        if name not in table:
            return self._real(host, port, *args, **kwargs)
        (self.connector_lookups if from_connector else self.guard_lookups).append(name)
        return [
            (
                socket.AF_INET6 if ":" in ip else socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                ((ip, port or 0, 0, 0) if ":" in ip else (ip, port or 0)),
            )
            for ip in table[name]
        ]


def _permit(monkeypatch: pytest.MonkeyPatch, *allowed: str) -> None:
    """Let the guard approve specific loopback addresses.

    Needed because the only addresses a test can actually bind and observe are
    loopback ones, which the floor exists to refuse. Scoped to the exact
    addresses named, so every other refusal stays real.
    """
    real = url_guard._reject_address
    monkeypatch.setattr(
        url_guard,
        "_reject_address",
        lambda ip: None if str(ip) in allowed else real(ip),
    )


def _no_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _no_wait(self, _domain, state):  # noqa: ANN001
        state.last_request_time = 0
        return 0.0

    monkeypatch.setattr(HttpFetchAgent, "_wait_for_rate_limit", _no_wait)


def _mock_transport(monkeypatch: pytest.MonkeyPatch, handler) -> None:  # noqa: ANN001
    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
    )


def _logical_host(request: httpx.Request) -> str:
    """The host a real server would dispatch on: the ``Host`` header.

    With the connection pinned, ``request.url.host`` is the literal address --
    that is the whole point -- so a handler keyed on it would stop matching.
    A name-based virtual host reads the header, and so does this.
    """
    return request.headers.get("host", request.url.netloc.decode("ascii"))


# ── 1-3: the seam, with its controls ─────────────────────────────


class TestTheConnectionLandsOnTheApprovedAddress:
    """The one property this whole change exists for."""

    async def test_a_rebinding_name_reaches_the_approved_address_not_the_victim(
        self, monkeypatch
    ) -> None:
        """Guard is told 127.0.0.1, connector would say 127.0.0.2.

        Both servers listen on the SAME port, so nothing but the address the
        socket is opened to decides which one answers. That is what makes this
        an address-level assertion rather than a verdict one.
        """
        good = _Recorder("127.0.0.1", b"APPROVED")
        port = good.port
        victim = _Recorder("127.0.0.2", b"VICTIM", port=port)
        good.serve()
        victim.serve()
        try:
            # CONTROL: the victim really is reachable on that address:port, so
            # "the victim recorded nothing" is a fact about the pin and not
            # about a server that was never listening.
            async with httpx.AsyncClient(timeout=5.0) as probe:
                sanity = await probe.get(f"http://127.0.0.2:{port}/control")
            assert sanity.text == "VICTIM"
            assert victim.hits == ["/control"]
            victim.hits.clear()

            resolver = _Resolver(
                guard={"rebind.test": ["127.0.0.1"]},
                connector={"rebind.test": ["127.0.0.2"]},
            )
            resolver.install(monkeypatch)
            _permit(monkeypatch, "127.0.0.1", "127.0.0.2")
            _no_rate_limit(monkeypatch)

            agent = HttpFetchAgent(agent_id="pin-seam", pool="http")
            result = await agent.fetch_governed(f"http://rebind.test:{port}/x")

            assert result["success"] is True, result
            assert result["data"]["body"] == "APPROVED"
            assert good.hits == ["/x"]
            assert victim.hits == [], (
                f"the connection landed on the unapproved address: {victim.hits}"
            )
            assert resolver.connector_lookups == [], (
                "httpx resolved the name itself, so the pin is not being used"
            )
            assert resolver.guard_lookups, "the resolver stub never reached the guard"
        finally:
            good.close()
            victim.close()

    async def test_the_control_a_name_that_resolves_private_is_still_refused(
        self, monkeypatch
    ) -> None:
        """Without this, the test above proves nothing.

        It is what shows the resolver stub actually reaches the guard, so an
        approval in that test is a real approval rather than a probe that
        never fired.
        """
        resolver = _Resolver(guard={"loopback.test": ["127.0.0.1"]})
        resolver.install(monkeypatch)

        reason = check_resolved_address("http://loopback.test/x")

        assert reason == "Blocked private/reserved IP: 127.0.0.1"
        assert resolver.guard_lookups == ["loopback.test"]

    async def test_a_legitimate_fetch_still_succeeds(self, monkeypatch) -> None:
        """Guards against a fix that fails everything closed and passes the
        seam test for the wrong reason."""
        good = _Recorder("127.0.0.1", b"LEGITIMATE")
        good.serve()
        try:
            resolver = _Resolver(guard={"good.test": ["127.0.0.1"]})
            resolver.install(monkeypatch)
            _permit(monkeypatch, "127.0.0.1")
            _no_rate_limit(monkeypatch)

            agent = HttpFetchAgent(agent_id="pin-ok", pool="http")
            result = await agent.fetch_governed(f"http://good.test:{good.port}/ok")

            assert result["success"] is True, result
            assert result["data"]["body"] == "LEGITIMATE"
            assert good.hits == ["/ok"]
        finally:
            good.close()

    async def test_the_control_an_unpinned_request_does_reach_the_connector(
        self, monkeypatch
    ) -> None:
        """Proves the connector branch of the resolver can fire at all.

        Round-1 review: the seam test asserts ``connector_lookups == []``, which
        is exactly what a discriminator that never classifies anything as a
        connector lookup would also produce. That assertion is only evidence if
        an UNPINNED request is shown to land in the same branch -- so this makes
        one deliberately, bypassing the agent, and requires it to be counted.

        It is also the canary for the ``bytes`` keying itself: if httpx ever
        stops IDNA-encoding before it resolves, this fails and says so, rather
        than the seam test quietly going vacuous.
        """
        good = _Recorder("127.0.0.1", b"UNPINNED")
        good.serve()
        try:
            resolver = _Resolver(guard={"good.test": ["127.0.0.1"]})
            resolver.install(monkeypatch)

            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"http://good.test:{good.port}/raw")

            assert response.status_code == 200
            assert response.text == "UNPINNED"
            assert resolver.connector_lookups == ["good.test"], (
                "an unpinned request must be observed as a CONNECTOR lookup, or "
                "the seam test's `connector_lookups == []` proves nothing"
            )
            assert resolver.guard_lookups == [], (
                "premise: nothing here goes through the guard"
            )
        finally:
            good.close()


# ── 4: TLS is still verified against the NAME ────────────────────


@pytest.fixture(scope="module")
def _tls_server(tmp_path_factory):
    """An HTTPS server on 127.0.0.1 holding a cert valid only for `pinned.test`.

    The cert deliberately does NOT cover the address, so a connection that
    verifies against the literal fails and a connection that verifies against
    the name succeeds. That is what makes the pair below discriminate.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    tmp = Path(tmp_path_factory.mktemp("bf821tls"))
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "pinned.test")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=30))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("pinned.test")]), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    cert_path = tmp / "cert.pem"
    key_path = tmp / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )

    recorder = _Recorder("127.0.0.1", b"TLS OK")
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(cert_path), str(key_path))
    recorder._srv.socket = ctx.wrap_socket(recorder._srv.socket, server_side=True)
    recorder.serve()
    try:
        yield recorder, ssl.create_default_context(cafile=str(cert_path))
    finally:
        recorder.close()


class TestTlsIsVerifiedAgainstTheNameNotTheAddress:
    """`Host` alone would have traded SSRF for a broken certificate chain.

    Measured against httpx 0.28.1: rewriting the URL and setting only the
    header verifies the certificate against the literal address, so a
    legitimate HTTPS host stops connecting. `sni_hostname` becomes
    `server_hostname` in httpcore's `start_tls`, which is what the ssl module
    matches the certificate against.
    """

    async def test_a_pinned_https_fetch_verifies_against_the_hostname(
        self, monkeypatch, _tls_server
    ) -> None:
        server, ca = _tls_server
        server.hits.clear()
        server.hosts.clear()
        resolver = _Resolver(guard={"pinned.test": ["127.0.0.1"]})
        resolver.install(monkeypatch)
        _permit(monkeypatch, "127.0.0.1")
        _no_rate_limit(monkeypatch)
        real = httpx.AsyncClient
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(verify=ca, **kw))

        agent = HttpFetchAgent(agent_id="tls-pin", pool="http")
        result = await agent.fetch_governed(f"https://pinned.test:{server.port}/s")

        assert result["success"] is True, result
        assert result["data"]["body"] == "TLS OK"
        assert server.hosts == [f"pinned.test:{server.port}"]

    async def test_the_negative_without_sni_the_same_connection_fails_verification(
        self, monkeypatch, _tls_server
    ) -> None:
        """Both halves, or the pair cannot tell a working pin from a disabled
        verifier."""
        server, ca = _tls_server
        server.hits.clear()
        resolver = _Resolver(guard={"pinned.test": ["127.0.0.1"]})
        resolver.install(monkeypatch)
        _permit(monkeypatch, "127.0.0.1")
        _no_rate_limit(monkeypatch)
        real = httpx.AsyncClient
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(verify=ca, **kw))

        # Same rewrite, same Host header, SNI dropped.
        def _host_only(logical, addresses):  # noqa: ANN001
            if not addresses:
                return [(logical, {}, {})]
            return [
                (
                    logical.copy_with(host=addr),
                    {"Host": logical.netloc.decode("ascii")},
                    {},
                )
                for addr in addresses
            ]

        monkeypatch.setattr(HttpFetchAgent, "_pin_kwargs", staticmethod(_host_only))

        agent = HttpFetchAgent(agent_id="tls-nosni", pool="http")
        result = await agent.fetch_governed(f"https://pinned.test:{server.port}/s")

        assert result["success"] is False
        assert "CERTIFICATE_VERIFY_FAILED" in result["error"], result
        assert server.hits == []


# ── 5-7: the rewrite itself ──────────────────────────────────────


class TestTheRewrittenRequest:
    def test_the_host_header_carries_the_name_not_the_address(self) -> None:
        attempts = HttpFetchAgent._pin_kwargs(
            httpx.URL("https://example.com/a"), (PUBLIC,)
        )
        (url, headers, extensions), = attempts
        assert url.host == PUBLIC
        assert headers["Host"] == "example.com"
        assert extensions["sni_hostname"] == "example.com"

    def test_a_non_default_port_stays_in_the_host_header(self) -> None:
        (_url, headers, _ext), = HttpFetchAgent._pin_kwargs(
            httpx.URL("https://example.com:8443/a"), (PUBLIC,)
        )
        assert headers["Host"] == "example.com:8443"

    def test_userinfo_never_reaches_the_host_header(self) -> None:
        (_url, headers, _ext), = HttpFetchAgent._pin_kwargs(
            httpx.URL("https://user:pw@example.com/a"), (PUBLIC,)
        )
        assert "@" not in headers["Host"]
        assert "pw" not in headers["Host"]
        assert headers["Host"] == "example.com"

    def test_an_internationalised_name_is_pinned_in_its_ascii_form(self) -> None:
        """`URL.host` is the unicode form and `URL.raw_host` the IDNA one.

        httpcore's own default `server_hostname` is `origin.host.decode(ascii)`,
        so sending the unicode form would change what TLS is verified against
        for exactly the hosts least likely to be exercised.
        """
        (_url, headers, extensions), = HttpFetchAgent._pin_kwargs(
            httpx.URL("https://b\u00fccher.example:8443/p"), (PUBLIC,)
        )
        assert headers["Host"] == "xn--bcher-kva.example:8443"
        assert extensions["sni_hostname"] == "xn--bcher-kva.example"

    def test_an_ipv6_address_is_bracketed_in_the_rewritten_url(self) -> None:
        v6 = "2606:2800:220:1:248:1893:25c8:1946"
        (url, _h, _e), = HttpFetchAgent._pin_kwargs(
            httpx.URL("https://example.com:8443/a"), (v6,)
        )
        assert str(url) == f"https://[{v6}]:8443/a"

    def test_port_path_query_and_fragment_survive_the_rewrite(self) -> None:
        (url, _h, _e), = HttpFetchAgent._pin_kwargs(
            httpx.URL("https://example.com:8443/a/b?q=1#f"), (PUBLIC,)
        )
        assert str(url) == f"https://{PUBLIC}:8443/a/b?q=1#f"

    def test_no_approved_addresses_means_no_rewrite(self) -> None:
        """Reachable only for a hostname-less URL, which `check_url_shape`
        refuses first -- so the request goes out unchanged rather than being
        rewritten to nothing."""
        logical = httpx.URL("https://example.com/a")
        assert HttpFetchAgent._pin_kwargs(logical, ()) == [(logical, {}, {})]

    def test_every_approved_address_becomes_an_attempt_in_order(self) -> None:
        attempts = HttpFetchAgent._pin_kwargs(
            httpx.URL("https://example.com/a"), ("93.184.216.34", "93.184.216.35")
        )
        assert [u.host for u, _h, _e in attempts] == [
            "93.184.216.34",
            "93.184.216.35",
        ]


# ── 8-12: the request path around the pin ────────────────────────


class TestThePinAcrossRetriesAndRedirects:
    async def test_a_429_retry_reuses_the_pin_without_resolving_again(
        self, monkeypatch
    ) -> None:
        """AD-270 re-requests the same hop. Re-validating there would open a
        THIRD lookup inside one hop, which is the defect itself."""
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            if len(seen) == 1:
                return httpx.Response(429, content=b"slow down", request=request)
            return httpx.Response(200, content=b"ok", request=request)

        resolver = _Resolver(guard={"example.test": [PUBLIC]})
        resolver.install(monkeypatch)
        _mock_transport(monkeypatch, handler)
        _no_rate_limit(monkeypatch)

        agent = HttpFetchAgent(agent_id="retry", pool="http")
        result = await agent.fetch_governed("https://example.test/x")

        assert result["success"] is True, result
        assert len(seen) == 2, seen
        assert seen[0] == seen[1] == f"https://{PUBLIC}/x", seen
        # One at the pre-coalescing gate, one for the hop's pin. A third would
        # be the retry re-resolving.
        assert len(resolver.guard_lookups) == 2, resolver.guard_lookups

    async def test_each_redirect_hop_is_pinned_independently(
        self, monkeypatch
    ) -> None:
        """Hop 1's approval says nothing about hop 2's host, and hop 2 must not
        inherit hop 1's address."""
        seen: list[tuple[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append((_logical_host(request), str(request.url)))
            if _logical_host(request) == "first.test":
                return httpx.Response(
                    302,
                    headers={"location": "https://second.test/landing"},
                    request=request,
                )
            return httpx.Response(200, content=b"landed", request=request)

        resolver = _Resolver(
            guard={"first.test": ["93.184.216.34"], "second.test": ["93.184.216.35"]}
        )
        resolver.install(monkeypatch)
        _mock_transport(monkeypatch, handler)
        _no_rate_limit(monkeypatch)

        agent = HttpFetchAgent(agent_id="hops", pool="http")
        result = await agent.fetch_governed("https://first.test/start")

        assert result["success"] is True, result
        assert seen == [
            ("first.test", "https://93.184.216.34/start"),
            ("second.test", "https://93.184.216.35/landing"),
        ], seen

    async def test_a_hop_onto_a_rebinding_name_is_refused_and_never_requested(
        self, monkeypatch
    ) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(_logical_host(request))
            if _logical_host(request) == "first.test":
                return httpx.Response(
                    302,
                    headers={"location": "https://evil.test/internal"},
                    request=request,
                )
            return httpx.Response(200, content=b"SECRET", request=request)

        resolver = _Resolver(
            guard={"first.test": [PUBLIC], "evil.test": ["127.0.0.1"]}
        )
        resolver.install(monkeypatch)
        _mock_transport(monkeypatch, handler)
        _no_rate_limit(monkeypatch)

        agent = HttpFetchAgent(agent_id="hop2", pool="http")
        result = await agent.fetch_governed("https://first.test/start")

        assert result["success"] is False
        assert result["error"] == (
            "SSRF protection: Blocked private/reserved IP: 127.0.0.1"
        )
        assert seen == ["first.test"], f"the second hop was contacted: {seen}"
        assert "SECRET" not in str(result)

    async def test_a_relative_location_resolves_against_the_name(
        self, monkeypatch
    ) -> None:
        """If the hop were joined against the pinned URL, a relative Location
        would silently move the request onto the literal address."""
        seen: list[tuple[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append((_logical_host(request), request.url.path))
            if request.url.path == "/start":
                return httpx.Response(
                    302, headers={"location": "/moved"}, request=request
                )
            return httpx.Response(200, content=b"ok", request=request)

        resolver = _Resolver(guard={"example.test": [PUBLIC]})
        resolver.install(monkeypatch)
        _mock_transport(monkeypatch, handler)
        _no_rate_limit(monkeypatch)

        agent = HttpFetchAgent(agent_id="rel", pool="http")
        result = await agent.fetch_governed("https://example.test/start")

        assert result["success"] is True, result
        assert seen == [("example.test", "/start"), ("example.test", "/moved")], seen
        assert result["data"]["url"] == "https://example.test/moved"

    async def test_the_reported_url_is_the_name_on_a_plain_fetch(
        self, monkeypatch
    ) -> None:
        """`response.url` is the pinned literal once the hop is rewritten, and
        a caller asked for a name. Guards test_bf819:177,210 from the inside."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"ok", request=request)

        resolver = _Resolver(guard={"example.test": [PUBLIC]})
        resolver.install(monkeypatch)
        _mock_transport(monkeypatch, handler)
        _no_rate_limit(monkeypatch)

        agent = HttpFetchAgent(agent_id="url", pool="http")
        result = await agent.fetch_governed("https://example.test/page")

        assert result["data"]["url"] == "https://example.test/page"
        assert PUBLIC not in result["data"]["url"]

    async def test_the_reported_url_is_the_name_of_the_final_hop(
        self, monkeypatch
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if _logical_host(request) == "first.test":
                return httpx.Response(
                    302,
                    headers={"location": "https://second.test/landing"},
                    request=request,
                )
            return httpx.Response(200, content=b"ok", request=request)

        resolver = _Resolver(
            guard={"first.test": ["93.184.216.34"], "second.test": ["93.184.216.35"]}
        )
        resolver.install(monkeypatch)
        _mock_transport(monkeypatch, handler)
        _no_rate_limit(monkeypatch)

        agent = HttpFetchAgent(agent_id="url2", pool="http")
        result = await agent.fetch_governed("https://first.test/start")

        assert result["data"]["url"] == "https://second.test/landing"

    async def test_the_rate_limit_key_is_the_name_not_the_address(
        self, monkeypatch
    ) -> None:
        """Keyed on the address, every rotation of a round-robin DNS answer
        would hand the caller a fresh budget."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"ok", request=request)

        resolver = _Resolver(
            guard={"rotating.test": ["93.184.216.34"]}
        )
        resolver.install(monkeypatch)
        _mock_transport(monkeypatch, handler)
        _no_rate_limit(monkeypatch)

        agent = HttpFetchAgent(agent_id="ratekey", pool="http")
        await agent.fetch_governed("https://rotating.test/a")
        # A different address next time: the budget must not follow it.
        resolver.guard_answers["rotating.test"] = ["93.184.216.35"]
        await agent.fetch_governed("https://rotating.test/b")

        assert list(HttpFetchAgent._domain_state) == ["rotating.test"], (
            f"the limiter re-keyed per address: {list(HttpFetchAgent._domain_state)}"
        )


# ── 13-14: multi-A fallback, and failing closed ──────────────────


class _FakeClient:
    """Records attempts and refuses the addresses it was told to refuse."""

    def __init__(self, refuse: set[str]) -> None:
        self.attempts: list[str] = []
        self._refuse = refuse

    async def request(self, method, url, **kwargs):  # noqa: ANN001
        self.attempts.append(str(url.host))
        if str(url.host) in self._refuse:
            raise httpx.ConnectError("refused")
        return httpx.Response(200, content=b"ok")


class TestMultipleApprovedAddresses:
    """Pinning necessarily gives up anyio's overlapped Happy Eyeballs, so the
    fallback is sequential. Every address here came from the ONE judged lookup,
    so moving to the next is not a second rebinding window.
    """

    async def test_a_second_approved_address_is_tried_when_the_first_refuses(
        self,
    ) -> None:
        agent = HttpFetchAgent(agent_id="multi-a", pool="http")
        client = _FakeClient(refuse={"93.184.216.34"})
        attempts = HttpFetchAgent._pin_kwargs(
            httpx.URL("https://example.com/a"), ("93.184.216.34", "93.184.216.35")
        )

        response = await agent._request_pinned(client, "GET", attempts)

        assert response.status_code == 200
        assert client.attempts == ["93.184.216.34", "93.184.216.35"], client.attempts

    async def test_when_every_approved_address_fails_the_fetch_fails_closed(
        self,
    ) -> None:
        agent = HttpFetchAgent(agent_id="multi-a-dead", pool="http")
        client = _FakeClient(refuse={"93.184.216.34", "93.184.216.35"})
        attempts = HttpFetchAgent._pin_kwargs(
            httpx.URL("https://example.com/a"), ("93.184.216.34", "93.184.216.35")
        )

        with pytest.raises(httpx.ConnectError):
            await agent._request_pinned(client, "GET", attempts)

        assert client.attempts == ["93.184.216.34", "93.184.216.35"]

    async def test_an_empty_attempt_list_raises_rather_than_returning_nothing(
        self,
    ) -> None:
        agent = HttpFetchAgent(agent_id="multi-a-empty", pool="http")
        with pytest.raises(httpx.ConnectError):
            await agent._request_pinned(_FakeClient(refuse=set()), "GET", [])

    async def test_a_dead_first_address_still_reaches_a_live_second_one(
        self, monkeypatch
    ) -> None:
        """End to end over real sockets: the first approved address has nothing
        listening, the second does."""
        good = _Recorder("127.0.0.1", b"SECOND")
        good.serve()
        dead = socket.socket()
        dead.bind(("127.0.0.3", good.port))
        # Bound but never listening, so a connect is refused rather than hung.
        try:
            resolver = _Resolver(guard={"multi.test": ["127.0.0.3", "127.0.0.1"]})
            resolver.install(monkeypatch)
            _permit(monkeypatch, "127.0.0.1", "127.0.0.3")
            _no_rate_limit(monkeypatch)

            agent = HttpFetchAgent(agent_id="multi-real", pool="http")
            result = await agent.fetch_governed(f"http://multi.test:{good.port}/x")

            assert result["success"] is True, result
            assert result["data"]["body"] == "SECOND"
            assert good.hits == ["/x"]
        finally:
            dead.close()
            good.close()


# ── 15-16: the guard's own contract ──────────────────────────────


class TestTheGuardContract:
    def test_a_mixed_public_and_private_answer_is_refused_entirely(
        self, monkeypatch
    ) -> None:
        """One hostile answer among several refuses the lot -- it must not pin
        the public one and proceed."""
        resolver = _Resolver(guard={"mixed.test": [PUBLIC, "10.0.0.5"]})
        resolver.install(monkeypatch)

        target = resolve_and_pin("https://mixed.test/x")

        assert target.reason == "Blocked private/reserved IP: 10.0.0.5"
        assert target.addresses == ()

    def test_resolve_and_pin_returns_every_address_it_judged(
        self, monkeypatch
    ) -> None:
        resolver = _Resolver(guard={"two.test": ["93.184.216.34", "93.184.216.35"]})
        resolver.install(monkeypatch)

        target = resolve_and_pin("https://two.test/x")

        assert target.reason is None
        assert target.addresses == ("93.184.216.34", "93.184.216.35")

    def test_a_hostname_less_url_is_allowed_with_no_addresses(self) -> None:
        """Unchanged from before: `check_url_shape` is what refuses these."""
        target = resolve_and_pin("file:///etc/passwd")
        assert target == PinnedTarget(None, ())

    def test_an_unresolvable_name_refuses_with_no_addresses(
        self, monkeypatch
    ) -> None:
        def _boom(*_a, **_k):
            raise socket.gaierror("nope")

        monkeypatch.setattr(socket, "getaddrinfo", _boom)
        target = resolve_and_pin("https://nx.test/x")
        assert target == PinnedTarget("Cannot resolve hostname: nx.test", ())

    @pytest.mark.parametrize(
        ("answers", "label"),
        [
            ([], "no answers at all"),
            (
                [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("not-an-ip", 0))],
                "answers that do not parse as addresses",
            ),
        ],
    )
    def test_a_name_that_resolves_to_nothing_usable_fails_closed(
        self, monkeypatch, answers, label,
    ) -> None:
        """Round-1 review: approving with an EMPTY pin is a fail-OPEN.

        Measured before the repair: ``reason=None, addresses=()``. The caller
        then falls back to the logical name, which resolves a second time --
        the entire defect BF-821 exists to close, reopened by the one shape
        where the guard had nothing to hand back.

        The docstring on ``PinnedTarget`` asserted this could not happen. It
        could, so the code now enforces what the docstring claims.
        """
        monkeypatch.setattr(socket, "getaddrinfo", lambda *_a, **_k: answers)

        target = validate_and_pin_public_url("https://weird.test/x")

        assert target.reason is not None, (
            f"{label}: approving with nothing to pin sends the caller back to "
            "the name, which resolves again"
        )
        assert "weird.test" in target.reason
        assert target.addresses == ()

    def test_a_usable_answer_alongside_junk_still_pins(self, monkeypatch) -> None:
        """The fail-closed branch must not swallow a resolvable host.

        Premise for the test above: without this, 'refuses' could mean 'refuses
        everything', and the pair would not discriminate.
        """
        monkeypatch.setattr(
            socket, "getaddrinfo",
            lambda *_a, **_k: [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("not-an-ip", 0)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
            ],
        )

        target = validate_and_pin_public_url("https://mixed.test/x")

        assert target == PinnedTarget(None, ("93.184.216.34",))

    def test_validate_and_pin_applies_the_shape_refusals_first(self) -> None:
        assert validate_and_pin_public_url("file:///etc/passwd") == PinnedTarget(
            "Blocked scheme: file", ()
        )
        assert validate_and_pin_public_url("http://127.0.0.1/x") == PinnedTarget(
            "Blocked private/reserved IP: 127.0.0.1", ()
        )

    def test_validate_public_url_refusal_strings_are_unchanged(
        self, monkeypatch
    ) -> None:
        """Re-asserted here so an edit to `resolve_and_pin` cannot drift the
        delegating path. These four are pinned by test_bf743:288-301 as a
        standing contract that they never reword."""
        resolver = _Resolver(guard={"bad.test": ["10.0.0.5"]})
        resolver.install(monkeypatch)

        assert validate_public_url("file:///etc/passwd") == "Blocked scheme: file"
        assert validate_public_url("") == "No URL"
        assert (
            validate_public_url("http://metadata.google.internal/x")
            == "Blocked metadata endpoint: metadata.google.internal"
        )
        assert (
            validate_public_url("http://bad.test/x")
            == "Blocked private/reserved IP: 10.0.0.5"
        )

    def test_check_resolved_address_still_returns_only_a_reason(
        self, monkeypatch
    ) -> None:
        resolver = _Resolver(guard={"ok.test": [PUBLIC]})
        resolver.install(monkeypatch)

        assert check_resolved_address("https://ok.test/x") is None
        assert isinstance(check_resolved_address("http://10.0.0.5/x"), str)


# ── the residual this fix does NOT close ─────────────────────────


def test_the_browser_path_is_documented_as_still_unpinned() -> None:
    """BF-822's floor sees a URL, not an address, and Playwright resolves
    inside the browser process. A reader arriving from #1283 must find that
    said where the question was asked, rather than inferring it is fixed."""
    from probos.agents import http_fetch

    doc = http_fetch.HttpFetchAgent._fetch_url_uncoalesced.__doc__ or ""
    assert "BF-821 closed it" in doc
    assert "BrowserTool" in doc
    assert "acknowledged, not fixed here" in doc


def test_domain_rate_state_is_still_keyed_on_host_and_port() -> None:
    """Sanity that the pin did not disturb BF-819's userinfo stripping."""
    agent = HttpFetchAgent(agent_id="key", pool="http")
    domain, state = agent._get_domain_state("https://user:pw@example.com:8443/a")
    assert domain == "example.com:8443"
    assert isinstance(state, DomainRateState)
