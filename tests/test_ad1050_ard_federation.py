"""AD-1050: tests for federated ARD discovery modes (referral fan-out + merge).

DD-2 referral source: ``referral_endpoints`` is unit-tested against a real
``SystemConfig`` carrying ``a2a.outbound_peers``. ``discover_federated`` is exercised
with a real ``httpx.AsyncClient`` over an ``httpx.MockTransport`` (BF-287 real
transport, no network) injected via the ``client`` seam. The mode-gated
byte-identical-when-off proof asserts the ``none`` mode returns ``[]`` WITHOUT ever
touching the injected transport. ``merge_catalog_entries`` is unit-tested on
hand-built catalogs.

asyncio_mode="auto": async tests carry NO ``@pytest.mark.asyncio`` marker; no
``asyncio.run`` is used.

Run: d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1050_ard_federation.py -q -n 0 -p no:cacheprovider
"""

from __future__ import annotations

from typing import Any

import httpx

from probos.config import (
    A2APeerConfig,
    FederationA2AConfig,
    FederationArdConfig,
    FederationConfig,
    SystemConfig,
)
from probos.federation.ard import (
    MT_PROBOS_TOOL,
    AiCatalog,
    CatalogEntry,
    DiscoveredCatalog,
    discover_federated,
    merge_catalog_entries,
    referral_endpoints,
)

_GOOD_CATALOG = {
    "specVersion": "1.0",
    "host": {"displayName": "Peer"},
    "entries": [
        {
            "identifier": "urn:air:peer.example.com:tools:x",
            "displayName": "X",
            "type": MT_PROBOS_TOOL,
            "data": {"axis": "tool"},
        }
    ],
}


def _config(*, mode: str = "none", peers: list[str] | None = None, max_peers: int = 5) -> SystemConfig:
    return SystemConfig(
        federation=FederationConfig(
            ard=FederationArdConfig(federation_mode=mode, max_referral_peers=max_peers),
            a2a=FederationA2AConfig(
                outbound_peers=[A2APeerConfig(peer_url=u) for u in (peers or [])]
            ),
        )
    )


class _FedRuntime:
    def __init__(self, config: SystemConfig) -> None:
        self.config = config


def _entry(identifier: str, name: str = "E") -> CatalogEntry:
    return CatalogEntry(
        identifier=identifier, display_name=name, type=MT_PROBOS_TOOL, data={"axis": "tool"}
    )


# --------------------------------------------------------------------------- #
# referral_endpoints (pure, bounded)
# --------------------------------------------------------------------------- #


def test_referral_endpoints_collects_peer_urls() -> None:
    cfg = _config(peers=["https://p1", "https://p2"])
    assert referral_endpoints(cfg, max_peers=5) == ["https://p1", "https://p2"]


def test_referral_endpoints_caps_at_max_peers() -> None:
    cfg = _config(peers=["https://p1", "https://p2", "https://p3"])
    assert referral_endpoints(cfg, max_peers=2) == ["https://p1", "https://p2"]


def test_referral_endpoints_zero_max_peers_returns_empty() -> None:
    cfg = _config(peers=["https://p1"])
    assert referral_endpoints(cfg, max_peers=0) == []


def test_referral_endpoints_drops_empty_urls() -> None:
    cfg = _config(peers=["https://p1", "", "https://p2"])
    assert referral_endpoints(cfg, max_peers=5) == ["https://p1", "https://p2"]


# --------------------------------------------------------------------------- #
# discover_federated (mode-gated; MockTransport seam)
# --------------------------------------------------------------------------- #


async def test_discover_federated_none_mode_no_http() -> None:
    def _explode(request: httpx.Request) -> httpx.Response:
        raise AssertionError("HTTP must not be called in 'none' mode")

    client = httpx.AsyncClient(transport=httpx.MockTransport(_explode))
    try:
        rt = _FedRuntime(_config(mode="none", peers=["https://p1"]))
        out = await discover_federated(rt, client=client)
    finally:
        await client.aclose()
    assert out == []


async def test_discover_federated_referrals_fetches() -> None:
    calls: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json=_GOOD_CATALOG)

    client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    try:
        rt = _FedRuntime(_config(mode="referrals", peers=["https://p1"]))
        out = await discover_federated(rt, client=client)
    finally:
        await client.aclose()
    assert len(out) == 1
    assert out[0].catalog is not None
    assert calls == ["https://p1/.well-known/ai-catalog.json"]


async def test_discover_federated_auto_degrades_to_referrals() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_GOOD_CATALOG)

    client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    try:
        rt = _FedRuntime(_config(mode="auto", peers=["https://p1"]))
        out = await discover_federated(rt, client=client)
    finally:
        await client.aclose()
    assert len(out) == 1
    assert out[0].catalog is not None


async def test_discover_federated_referrals_no_peers_no_http() -> None:
    def _explode(request: httpx.Request) -> httpx.Response:
        raise AssertionError("HTTP must not be called with zero peers")

    client = httpx.AsyncClient(transport=httpx.MockTransport(_explode))
    try:
        rt = _FedRuntime(_config(mode="referrals", peers=[]))
        out = await discover_federated(rt, client=client)
    finally:
        await client.aclose()
    assert out == []


# --------------------------------------------------------------------------- #
# merge_catalog_entries (flatten + dedupe by URN, first-wins)
# --------------------------------------------------------------------------- #


def test_merge_dedupe_by_urn_first_wins() -> None:
    first = _entry("urn:air:a:tools:dup", name="first")
    second = _entry("urn:air:a:tools:dup", name="second")
    cat_a = AiCatalog(entries=[first])
    cat_b = AiCatalog(entries=[second])
    merged = merge_catalog_entries([cat_a, cat_b])
    assert len(merged) == 1
    assert merged[0].display_name == "first"  # first occurrence wins


def test_merge_flattens_aicatalog_and_discovered() -> None:
    own = AiCatalog(entries=[_entry("urn:air:a:tools:x")])
    peer = DiscoveredCatalog(
        source_endpoint="https://peer", catalog=AiCatalog(entries=[_entry("urn:air:b:tools:y")])
    )
    merged = merge_catalog_entries([own, peer])
    assert {e.identifier for e in merged} == {"urn:air:a:tools:x", "urn:air:b:tools:y"}


def test_merge_skips_failed_discovered() -> None:
    ok = DiscoveredCatalog(
        source_endpoint="https://ok", catalog=AiCatalog(entries=[_entry("urn:air:a:tools:x")])
    )
    failed = DiscoveredCatalog(source_endpoint="https://bad", error="boom")
    merged = merge_catalog_entries([ok, failed])
    assert [e.identifier for e in merged] == ["urn:air:a:tools:x"]
