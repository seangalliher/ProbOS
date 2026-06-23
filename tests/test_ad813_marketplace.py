"""AD-813: tests for the read-only remote skill/pack marketplace BROWSE endpoint.

BROWSE ONLY — nothing is downloaded, written, scanned, loaded, or executed. The
#1 invariant is the SSRF guard: the registry host comes ONLY from
``config.skills_marketplace.registry_url`` (never the request), and
``follow_redirects=False`` on every request.

BF-287 real-transport: the router path is exercised through a real FastAPI
``TestClient`` + a config-shaped ``SimpleNamespace`` runtime (no MagicMock at the
boundary). Because the router builds its own ``httpx.AsyncClient`` internally,
the tests monkeypatch ``httpx.AsyncClient`` onto a deterministic
``httpx.MockTransport`` and record how many clients were built (so the disabled
path can prove ZERO HTTP). The follow-redirects SSRF guard is proven at the
``fetch_marketplace_index`` seam (mirrors AD-1046).

asyncio_mode="auto": async tests carry NO marker.

Run: d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad813_marketplace.py -q -n 0
"""
from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.packs.marketplace import fetch_marketplace_index, parse_marketplace_index
from probos.routers import marketplace as marketplace_router
from probos.routers.deps import get_runtime

_REGISTRY_URL = "https://registry.internal/index"


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #


def _runtime(
    *,
    enabled: bool,
    registry_url: str,
    max_results: int = 100,
    default_page_size: int = 20,
):
    """A config-shaped runtime (SimpleNamespace, not MagicMock) for the router."""
    return SimpleNamespace(
        config=SimpleNamespace(
            skills_marketplace=SimpleNamespace(
                enabled=enabled,
                registry_url=registry_url,
                timeout_seconds=10.0,
                max_bytes=2_000_000,
                max_results=max_results,
                default_page_size=default_page_size,
            )
        )
    )


def _client(runtime) -> TestClient:
    app = FastAPI()
    app.include_router(marketplace_router.router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app)


def _install_transport(monkeypatch, handler: Callable[[httpx.Request], httpx.Response]) -> dict:
    """Force the router's internal ``httpx.AsyncClient`` onto a ``MockTransport``.

    Records ``clients_built`` (so the disabled path proves ZERO HTTP) and the
    per-construction kwargs (so ``follow_redirects=False`` can be asserted).
    monkeypatch auto-restores ``httpx.AsyncClient`` after the test.
    """
    rec: dict = {"clients_built": 0, "ctor_kwargs": []}
    real_cls = httpx.AsyncClient

    def factory(*args, **kwargs):
        rec["clients_built"] += 1
        rec["ctor_kwargs"].append(dict(kwargs))
        kwargs = dict(kwargs)
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_cls(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    return rec


_GOOD_INDEX = {
    "packs": [
        {
            "name": "foo-pack",
            "version": "1.0.0",
            "description": "A foo capability pack",
            "skills": ["lint", "format"],
            "agents": ["reviewer"],
        },
        {
            "name": "bar-pack",
            "version": "2.1.0",
            "description": "A bar capability pack",
            "skills": ["scan"],
            "agents": [],
        },
    ]
}


def _exploding_handler(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"SSRF/disabled violation: HTTP attempted to {request.url}")


# --------------------------------------------------------------------------- #
# 1-2. Disabled → inert shape, ZERO HTTP (exploding transport never touched)
# --------------------------------------------------------------------------- #


def test_disabled_off_returns_inert_no_http(monkeypatch) -> None:
    rec = _install_transport(monkeypatch, _exploding_handler)
    rt = _runtime(enabled=False, registry_url=_REGISTRY_URL)
    with _client(rt) as client:
        resp = client.get("/api/skills/marketplace")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"enabled": False, "results": [], "counts": {"total": 0, "returned": 0}}
    assert rec["clients_built"] == 0  # no HTTP client was ever built


def test_disabled_no_url_returns_inert_no_http(monkeypatch) -> None:
    rec = _install_transport(monkeypatch, _exploding_handler)
    rt = _runtime(enabled=True, registry_url="")  # enabled but no URL → disabled
    with _client(rt) as client:
        resp = client.get("/api/skills/marketplace")
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False
    assert rec["clients_built"] == 0


# --------------------------------------------------------------------------- #
# 3. Happy path → results mirror the descriptor
# --------------------------------------------------------------------------- #


def test_happy_path_results_mirror_descriptor(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_GOOD_INDEX)

    rec = _install_transport(monkeypatch, handler)
    rt = _runtime(enabled=True, registry_url=_REGISTRY_URL)
    with _client(rt) as client:
        resp = client.get("/api/skills/marketplace")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert rec["clients_built"] == 1
    assert body["counts"] == {"total": 2, "returned": 2}
    by_name = {r["name"]: r for r in body["results"]}
    assert by_name["foo-pack"]["version"] == "1.0.0"
    assert by_name["foo-pack"]["description"] == "A foo capability pack"
    assert by_name["foo-pack"]["skills"] == ["lint", "format"]
    assert by_name["foo-pack"]["agents"] == ["reviewer"]
    assert by_name["foo-pack"]["source"] == _REGISTRY_URL


# --------------------------------------------------------------------------- #
# 4. query filter narrows results
# --------------------------------------------------------------------------- #


def test_query_filter_narrows(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # The registry ignores ?q= here; the router's defensive filter narrows.
        return httpx.Response(200, json=_GOOD_INDEX)

    _install_transport(monkeypatch, handler)
    rt = _runtime(enabled=True, registry_url=_REGISTRY_URL)
    with _client(rt) as client:
        resp = client.get("/api/skills/marketplace", params={"query": "foo"})
    body = resp.json()
    assert [r["name"] for r in body["results"]] == ["foo-pack"]
    assert body["counts"] == {"total": 1, "returned": 1}


# --------------------------------------------------------------------------- #
# 5. max_results cap + page/page_size slice
# --------------------------------------------------------------------------- #


def test_pagination_and_cap(monkeypatch) -> None:
    index = {"packs": [{"name": f"pack{i}"} for i in range(5)]}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=index)

    _install_transport(monkeypatch, handler)
    rt = _runtime(enabled=True, registry_url=_REGISTRY_URL, max_results=3, default_page_size=2)
    with _client(rt) as client:
        page1 = client.get("/api/skills/marketplace").json()
        page2 = client.get("/api/skills/marketplace", params={"page": 2}).json()
    # 5 entries → capped to max_results=3 → total=3; page_size=2.
    assert page1["counts"] == {"total": 3, "returned": 2}
    assert [r["name"] for r in page1["results"]] == ["pack0", "pack1"]
    assert page1["page"] == 1 and page1["page_size"] == 2
    assert page2["counts"] == {"total": 3, "returned": 1}
    assert [r["name"] for r in page2["results"]] == ["pack2"]


# --------------------------------------------------------------------------- #
# 6-8. Honest-degrade: timeout / bad JSON / non-200 → 200 with error
# --------------------------------------------------------------------------- #


def test_registry_timeout_honest_degrades(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("slow registry")

    _install_transport(monkeypatch, handler)
    rt = _runtime(enabled=True, registry_url=_REGISTRY_URL)
    with _client(rt) as client:
        resp = client.get("/api/skills/marketplace")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert body["results"] == []
    assert body["error"]  # generic honest-degrade reason
    assert "slow registry" not in body["error"]  # no internals leaked


def test_bad_json_honest_degrades(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json {{{")

    _install_transport(monkeypatch, handler)
    rt = _runtime(enabled=True, registry_url=_REGISTRY_URL)
    with _client(rt) as client:
        resp = client.get("/api/skills/marketplace")
    assert resp.status_code == 200
    body = resp.json()
    assert body["results"] == []
    assert body["error"] == "invalid registry response"


def test_non_200_honest_degrades(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="nope")

    _install_transport(monkeypatch, handler)
    rt = _runtime(enabled=True, registry_url=_REGISTRY_URL)
    with _client(rt) as client:
        resp = client.get("/api/skills/marketplace")
    assert resp.status_code == 200
    body = resp.json()
    assert body["results"] == []
    assert body["error"] == "registry returned 404"


# --------------------------------------------------------------------------- #
# 9. SSRF: the endpoint has NO url param — the host is config-only
# --------------------------------------------------------------------------- #


def test_ssrf_ignores_request_url(monkeypatch) -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(200, json=_GOOD_INDEX)

    rec = _install_transport(monkeypatch, handler)
    rt = _runtime(enabled=True, registry_url=_REGISTRY_URL)
    with _client(rt) as client:
        # A hostile caller supplies ?url=http://evil — the endpoint has NO url
        # param, so it is silently ignored; only ?query= reaches the fetch.
        resp = client.get(
            "/api/skills/marketplace",
            params={"query": "foo", "url": "http://evil.example/registry"},
        )
    assert resp.status_code == 200
    assert rec["clients_built"] == 1
    assert len(requested) == 1
    # The host is ONLY the configured registry — never the request-supplied one.
    hit = httpx.URL(requested[0])
    assert hit.host == "registry.internal"
    assert "evil.example" not in requested[0]


# --------------------------------------------------------------------------- #
# 10. follow_redirects=False — a 302 is NOT followed (SSRF guard)
# --------------------------------------------------------------------------- #


async def test_no_redirect_follow() -> None:
    # Inject a client whose OWN default is the UNSAFE follow_redirects=True; the
    # per-request follow_redirects=False must still win, so a 302 Location to an
    # SSRF target is never dereferenced (mirrors AD-1046).
    requested: list[str] = []
    metadata = "http://169.254.169.254/latest/meta-data/"

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(302, headers={"Location": metadata})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)
    try:
        result = await fetch_marketplace_index(_REGISTRY_URL, http=http)
    finally:
        await http.aclose()

    # Only the configured registry was hit; the 302 Location was NOT followed.
    assert len(requested) == 1
    assert "169.254.169.254" not in requested[0]
    assert result.entries == []
    assert result.error  # empty 302 body → invalid registry response


# --------------------------------------------------------------------------- #
# 11. parse_marketplace_index — pure honest-degrade
# --------------------------------------------------------------------------- #


def test_parse_honest_degrade_skips_malformed() -> None:
    data = [
        {"name": "good-pack", "version": "1.0", "skill_paths": ["a"], "agent_paths": ["b"]},
        "not-a-dict",  # dropped
        {"version": "9.9"},  # no name → dropped
        {"name": "", "skills": ["x"]},  # blank name → dropped
        {"name": "second", "skills": ["s"], "agents": ["g"]},
    ]
    entries = parse_marketplace_index(data, source="https://reg/x")
    assert [e.name for e in entries] == ["good-pack", "second"]
    # scanner-descriptor field names (skill_paths/agent_paths) are accepted.
    good = entries[0]
    assert good.skills == ["a"]
    assert good.agents == ["b"]
    assert good.source == "https://reg/x"
    # plain skills/agents are accepted too.
    assert entries[1].skills == ["s"]
    assert entries[1].agents == ["g"]
