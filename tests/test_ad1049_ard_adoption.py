"""AD-1049: tests for governed discovery-before-design + gated adopt/connect.

Two surfaces:
  * ``surface_discovery_candidates`` — the discovery-before-design hook. The two
    heavy collaborators (``get_cached_catalog`` projection + ``ArdClient`` outbound
    fetch) are substituted at the module seam with real async stubs returning real
    domain objects (``AiCatalog`` / ``DiscoveredCatalog``) — NOT MagicMock. The
    config-gated runtime hook's byte-identical-when-off short-circuit is proven by
    mirroring its exact guard predicate against the default + enabled config.
  * ``connect_candidate`` — the explicit gated adopt. Exercised with a REAL
    ``ToolPermissionStore(db_path="")`` (cache-only, BF-287), a REAL ``TrustNetwork``,
    and a fake MCP bridge exposing the real ``register_server`` shape. The
    permission-before-trust ordering is proven by asserting a denied connect leaves
    NO trust record (``get_record(id) is None``).

asyncio_mode="auto": async tests carry NO ``@pytest.mark.asyncio`` marker; no
``asyncio.run`` is used.

Run: d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1049_ard_adoption.py -q -n 0 -p no:cacheprovider
"""

from __future__ import annotations

from typing import Any

from probos.config import FederationArdConfig, FederationConfig, SystemConfig
from probos.consensus.trust import TrustNetwork
from probos.federation.ard import (
    MT_A2A_AGENT,
    MT_MCP_SERVER,
    MT_PROBOS_TOOL,
    AiCatalog,
    CatalogEntry,
    DiscoveredCatalog,
    ard_resource_tool_id,
    connect_candidate,
)
from probos.federation.ard import adoption
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolPermission


def _config(*, enabled: bool = True, endpoints: list[str] | None = None) -> SystemConfig:
    return SystemConfig(
        federation=FederationConfig(
            ard=FederationArdConfig(enabled=enabled, discovery_endpoints=endpoints or [])
        )
    )


class _SurfaceRuntime:
    """Real-attribute runtime stub for surface_discovery_candidates."""

    def __init__(self, config: SystemConfig) -> None:
        self.config = config
        self.events: list[tuple[str, dict]] = []

    def emit_event(self, event: Any, data: dict | None = None) -> None:
        self.events.append((str(event), data or {}))


def _patch_catalog(monkeypatch: Any, catalog: AiCatalog) -> None:
    async def _fake(runtime: Any, **kw: Any) -> AiCatalog:
        return catalog

    monkeypatch.setattr(adoption, "get_cached_catalog", _fake)


def _patch_catalog_raises(monkeypatch: Any) -> None:
    async def _boom(runtime: Any, **kw: Any) -> AiCatalog:
        raise RuntimeError("projection failed")

    monkeypatch.setattr(adoption, "get_cached_catalog", _boom)


def _patch_ardclient(monkeypatch: Any, results: list[DiscoveredCatalog]) -> None:
    class _FakeArdClient:
        def __init__(self, *a: Any, **k: Any) -> None:
            pass

        async def discover(self, endpoints: list[str]) -> list[DiscoveredCatalog]:
            return results

    monkeypatch.setattr(adoption, "ArdClient", _FakeArdClient)


# --------------------------------------------------------------------------- #
# surface_discovery_candidates
# --------------------------------------------------------------------------- #


async def test_surface_own_catalog_finds_match(monkeypatch: Any) -> None:
    _patch_catalog(
        monkeypatch,
        AiCatalog(
            entries=[
                CatalogEntry(
                    identifier="urn:air:own:tools:weather",
                    display_name="weather tool",
                    type=MT_PROBOS_TOOL,
                    data={"axis": "tool"},
                )
            ]
        ),
    )
    rt = _SurfaceRuntime(_config(endpoints=[]))
    out = await adoption.surface_discovery_candidates(
        rt, {"name": "weather", "description": "get weather"}
    )
    assert len(out) == 1
    assert out[0]["identifier"] == "urn:air:own:tools:weather"
    assert out[0]["source"] == "own"


async def test_surface_external_verifies_score_and_domain(monkeypatch: Any) -> None:
    _patch_catalog(monkeypatch, AiCatalog(entries=[]))
    entry = CatalogEntry(
        identifier="urn:air:peer.example.com:mcp:weather",
        display_name="weather mcp",
        type=MT_MCP_SERVER,
        url="https://peer.example.com/mcp",
    )
    _patch_ardclient(
        monkeypatch,
        [DiscoveredCatalog(source_endpoint="https://peer.example.com", catalog=AiCatalog(entries=[entry]))],
    )
    rt = _SurfaceRuntime(_config(endpoints=["https://peer.example.com"]))
    out = await adoption.surface_discovery_candidates(rt, {"name": "weather", "description": ""})
    assert len(out) == 1
    candidate = out[0]
    assert candidate["source"] == "https://peer.example.com"
    # endpoint host peer.example.com == URN publisher domain → domain_match.
    assert candidate["domain_match"] is True
    assert candidate["score"] > 0.0


async def test_surface_emits_advisory_event(monkeypatch: Any) -> None:
    _patch_catalog(
        monkeypatch,
        AiCatalog(
            entries=[
                CatalogEntry(
                    identifier="urn:air:own:tools:x",
                    display_name="weather",
                    type=MT_PROBOS_TOOL,
                    data={"a": 1},
                )
            ]
        ),
    )
    rt = _SurfaceRuntime(_config(endpoints=[]))
    await adoption.surface_discovery_candidates(rt, {"name": "weather", "description": "x"})
    assert len(rt.events) == 1
    name, data = rt.events[0]
    assert name == "ard_discovery_candidates"
    assert data["intent"] == "weather"
    assert isinstance(data["candidates"], list) and len(data["candidates"]) == 1


async def test_surface_own_axis_failure_degrades(monkeypatch: Any) -> None:
    _patch_catalog_raises(monkeypatch)
    rt = _SurfaceRuntime(_config(endpoints=[]))
    out = await adoption.surface_discovery_candidates(rt, {"name": "x", "description": ""})
    assert out == []
    # The advisory event still fires (with empty candidates) — honest-degrade.
    assert rt.events and rt.events[0][0] == "ard_discovery_candidates"


async def test_surface_caps_candidates_at_five(monkeypatch: Any) -> None:
    _patch_catalog(
        monkeypatch,
        AiCatalog(
            entries=[
                CatalogEntry(
                    identifier=f"urn:air:own:tools:weather{i}",
                    display_name=f"weather {i}",
                    type=MT_PROBOS_TOOL,
                    data={"i": i},
                )
                for i in range(10)
            ]
        ),
    )
    rt = _SurfaceRuntime(_config(endpoints=[]))
    out = await adoption.surface_discovery_candidates(rt, {"name": "weather", "description": ""})
    assert len(out) == 5


def test_runtime_hook_guard_off_by_default() -> None:
    """Byte-identical-when-off proof: mirror the runtime.py call-site guard predicate.

    The hook reads ``_ard_cfg = getattr(getattr(self.config, "federation", None),
    "ard", None)`` then ``if _ard_cfg is not None and getattr(_ard_cfg,
    "discovery_before_design", False):``. With the DEFAULT config that predicate is
    False, so ``surface_discovery_candidates`` is never imported or called.
    """
    default_cfg = SystemConfig()
    ard = getattr(getattr(default_cfg, "federation", None), "ard", None)
    guard = ard is not None and getattr(ard, "discovery_before_design", False)
    assert guard is False

    on_cfg = SystemConfig(
        federation=FederationConfig(ard=FederationArdConfig(discovery_before_design=True))
    )
    ard_on = getattr(getattr(on_cfg, "federation", None), "ard", None)
    guard_on = ard_on is not None and getattr(ard_on, "discovery_before_design", False)
    assert guard_on is True


# --------------------------------------------------------------------------- #
# connect_candidate — permission → trust → connect ordering
# --------------------------------------------------------------------------- #


class _FakeBridge:
    """Fake MCP bridge exposing the real ``register_server(url, headers)`` shape."""

    def __init__(self, *, result: bool = True) -> None:
        self.result = result
        self.calls: list[tuple[str, dict | None]] = []

    def register_server(self, url: str, headers: dict[str, str] | None = None) -> bool:
        self.calls.append((url, headers))
        return self.result


class _ConnectRuntime:
    """Real-attribute runtime stub for connect_candidate."""

    def __init__(self, *, store: Any, trust_network: Any, mcp_bridge: Any) -> None:
        self.tool_permission_store = store
        self.trust_network = trust_network
        self.mcp_bridge = mcp_bridge


def _mcp_entry(identifier: str, url: str = "https://pub.example.com/mcp") -> CatalogEntry:
    return CatalogEntry(
        identifier=identifier, display_name="MCP", type=MT_MCP_SERVER, url=url
    )


async def _enable(store: ToolPermissionStore, agent_id: str, catalog: str, resource: str) -> None:
    await store.issue_grant(
        agent_id, ard_resource_tool_id(catalog, resource), ToolPermission.READ
    )


async def test_connect_permission_denied_never_seeds_trust() -> None:
    # No grant → permission_denied FIRST, BEFORE any trust seed (the core ordering).
    store = ToolPermissionStore(db_path="")
    trust = TrustNetwork()
    bridge = _FakeBridge()
    rt = _ConnectRuntime(store=store, trust_network=trust, mcp_bridge=bridge)
    entry = _mcp_entry("urn:air:pub.example.com:mcp:weather")

    result = await connect_candidate(
        rt,
        agent_id="agent-1",
        catalog="cat",
        resource="res",
        entry=entry,
        endpoint_host="pub.example.com",
    )
    assert result.connected is False
    assert result.reason == "permission_denied"
    # Permission-before-trust: a denied connect must NEVER seed a trust record.
    assert trust.get_record("urn:air:pub.example.com:mcp:weather") is None
    assert bridge.calls == []


async def test_connect_trust_below_threshold_no_bridge_call() -> None:
    store = ToolPermissionStore(db_path="")
    await _enable(store, "agent-2", "cat", "res")
    trust = TrustNetwork()
    bridge = _FakeBridge()
    rt = _ConnectRuntime(store=store, trust_network=trust, mcp_bridge=bridge)
    # No publisher-domain match → Beta(1,3) = 0.25 < 0.4.
    entry = _mcp_entry("urn:air:other.example.com:mcp:weather")

    result = await connect_candidate(
        rt,
        agent_id="agent-2",
        catalog="cat",
        resource="res",
        entry=entry,
        endpoint_host="pub.example.com",
    )
    assert result.connected is False
    assert result.reason == "trust_below_threshold"
    assert result.trust_score == 0.25
    assert bridge.calls == []  # never reached the connect step


async def test_connect_mcp_registered() -> None:
    store = ToolPermissionStore(db_path="")
    await _enable(store, "agent-3", "cat", "res")
    trust = TrustNetwork()
    bridge = _FakeBridge(result=True)
    rt = _ConnectRuntime(store=store, trust_network=trust, mcp_bridge=bridge)
    # Domain match → Beta(2,3) = 0.40 (exactly at the gate, allowed).
    entry = _mcp_entry("urn:air:pub.example.com:mcp:weather", url="https://pub.example.com/mcp")

    result = await connect_candidate(
        rt,
        agent_id="agent-3",
        catalog="cat",
        resource="res",
        entry=entry,
        endpoint_host="pub.example.com",
    )
    assert result.connected is True
    assert result.reason == "mcp_registered"
    assert result.source == "https://pub.example.com/mcp"
    assert result.trust_score == 0.4
    assert bridge.calls == [("https://pub.example.com/mcp", None)]


async def test_connect_mcp_register_failed() -> None:
    store = ToolPermissionStore(db_path="")
    await _enable(store, "agent-4", "cat", "res")
    trust = TrustNetwork()
    bridge = _FakeBridge(result=False)  # bridge refuses a dup/empty url
    rt = _ConnectRuntime(store=store, trust_network=trust, mcp_bridge=bridge)
    entry = _mcp_entry("urn:air:pub.example.com:mcp:weather")

    result = await connect_candidate(
        rt,
        agent_id="agent-4",
        catalog="cat",
        resource="res",
        entry=entry,
        endpoint_host="pub.example.com",
    )
    assert result.connected is False
    assert result.reason == "mcp_register_failed"
    assert result.trust_score == 0.4


async def test_connect_mcp_bridge_unavailable() -> None:
    store = ToolPermissionStore(db_path="")
    await _enable(store, "agent-5", "cat", "res")
    trust = TrustNetwork()
    rt = _ConnectRuntime(store=store, trust_network=trust, mcp_bridge=None)
    entry = _mcp_entry("urn:air:pub.example.com:mcp:weather")

    result = await connect_candidate(
        rt,
        agent_id="agent-5",
        catalog="cat",
        resource="res",
        entry=entry,
        endpoint_host="pub.example.com",
    )
    assert result.connected is False
    assert result.reason == "mcp_bridge_unavailable"
    assert result.trust_score == 0.4


async def test_connect_not_supported_v1_for_non_mcp() -> None:
    store = ToolPermissionStore(db_path="")
    await _enable(store, "agent-6", "cat", "res")
    trust = TrustNetwork()
    bridge = _FakeBridge()
    rt = _ConnectRuntime(store=store, trust_network=trust, mcp_bridge=bridge)
    # A2A agent card with a url + domain match → passes trust but unsupported in v1.
    entry = CatalogEntry(
        identifier="urn:air:pub.example.com:agents:assistant",
        display_name="A",
        type=MT_A2A_AGENT,
        url="https://pub.example.com/a2a",
    )

    result = await connect_candidate(
        rt,
        agent_id="agent-6",
        catalog="cat",
        resource="res",
        entry=entry,
        endpoint_host="pub.example.com",
    )
    assert result.connected is False
    assert result.reason == "connect_not_supported_v1"
    assert result.trust_score == 0.4
    assert bridge.calls == []  # never registered
