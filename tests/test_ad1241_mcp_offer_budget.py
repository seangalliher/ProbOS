"""AD-1241: candidate-bounded MCP dispatch selection."""

from __future__ import annotations

import asyncio
import json
import re
import sys
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import probos.cognitive.crew_verifier as verifier_module
import probos.cognitive.mcp_workbench as workbench_module
import probos.cognitive.swe_harness.agentic_loop as loop_module
import probos.cognitive.swe_harness.tool_call as tool_call_module
import probos.tools.permissions as permissions_module
from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor, WorkItemAgenticOutcome
from probos.cognitive.crew_verifier import (
    _SessionCorrectionRuntime,
    _session_correction_runtime,
)
from probos.cognitive.llm_client import LLMResponse
from probos.cognitive.mcp_workbench import (
    MCP_DISPATCH_OFFER_CONTEXT_KEY,
    MCPDispatchOffer,
    MCPDispatchSource,
    MCPWorkbench,
)
from probos.cognitive.swe_harness.tool_call import (
    TextBlock,
    ToolCallRequest,
    ToolUseBlock,
    llm_function_name,
)
from probos.config import BrowserToolConfig
from probos.integrations.mcp_bridge import MCPBridge
from probos.integrations.mcp_bridge.access import resolve_mcp_access
from probos.integrations.mcp_bridge.reaper import McpWorkbenchReaper
from probos.integrations.mcp_bridge.store import McpServerRecord, McpServerStore
from probos.tools.browser.tool import BrowserTool
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolAccessGrant, ToolPermission, ToolResult, ToolType
from probos.tools.registry import ToolRegistry
from probos.types import LLMRequest


class _CountingGrants:
    def __init__(self, store: ToolPermissionStore) -> None:
        self.store = store
        self.reads = 0
        self.fail_next_read = False
        self.failures = 0

    def get_active_grants_sync(
        self, agent_id: str, tool_id: str | None = None
    ) -> list[ToolAccessGrant]:
        self.reads += 1
        if self.fail_next_read:
            self.fail_next_read = False
            self.failures += 1
            raise RuntimeError("injected workbench grant read failure")
        return self.store.get_active_grants_sync(agent_id, tool_id)


class _OfflineServerStore:
    def __init__(self, records: list[McpServerRecord]) -> None:
        self.records = records
        self.reads = 0

    def list_sync(self) -> list[McpServerRecord]:
        self.reads += 1
        return list(self.records)


class _OfflineBridge:
    def __init__(self) -> None:
        self.client_reads = 0

    def get_client(self, server_url: str) -> None:
        self.client_reads += 1
        raise AssertionError("Descriptor pulls and dispatch must not access the bridge")


async def _no_consensus(
    server_url: str, tool_name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    raise AssertionError("Dispatch selection must not invoke consensus")


@pytest.mark.asyncio
async def test_bounded_dispatch_scans_only_candidates_and_reads_grants_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent_id = "agent"
    record = McpServerRecord(name="offline", type="stdio", id="offline-server")
    server_store = _OfflineServerStore([record])
    permission_store = ToolPermissionStore()
    agent_grants = _CountingGrants(permission_store)
    department_grants = _CountingGrants(ToolPermissionStore())
    registry = ToolRegistry()
    bridge = _OfflineBridge()
    workbench = MCPWorkbench(
        tool_registry=registry,
        bridge=bridge,
        consensus_invoke=_no_consensus,
        episode_writer=None,
        server_store=server_store,
        perm_store=agent_grants,
        dept_grant_store=department_grants,
        risk_store=None,
        ontology=None,
        agent_registry=None,
    )

    assert workbench.dispatch_tool_ids(agent_id) == ["find_mcp_tool"]
    assert workbench.pulled_count == 0
    await permission_store.issue_grant(
        agent_id, "mcp:offline", permission=ToolPermission.WRITE
    )
    tool_names = [f"tool_{index:03d}" for index in range(100)]
    warm_ids = [f"mcp:offline:{tool_name}" for tool_name in tool_names]
    for tool_name in tool_names:
        assert await workbench.pull_tool(
            agent_id,
            "offline",
            tool_name,
            descriptor={
                "name": tool_name,
                "description": f"Offline tool {tool_name}",
                "input_schema": {"type": "object"},
            },
        ) is True

    assert workbench.pulled_count == 100
    assert registry.count() == 101
    assert all(registry.get(tool_id) is not None for tool_id in warm_ids)
    final_registration = registry.get(warm_ids[-1])
    assert final_registration is not None
    assert final_registration.enabled is True
    assert workbench.dispatch_tool_ids(agent_id, candidate_ids=None) == [
        "find_mcp_tool", *warm_ids,
    ]

    await permission_store.issue_grant(
        agent_id, warm_ids[5], permission=ToolPermission.NONE, is_restriction=True
    )
    disabled_registration = registry.get(warm_ids[6])
    assert disabled_registration is not None
    registry.register(disabled_registration.tool, enabled=False)
    assert registry.unregister(warm_ids[8]) is True

    resolved: list[tuple[str, str]] = []

    def count_access(
        grants: list[ToolAccessGrant],
        server_name: str,
        tool_name: str,
        *,
        department_grants: Sequence[ToolAccessGrant] = (),
    ) -> tuple[bool, str]:
        resolved.append((server_name, tool_name))
        return resolve_mcp_access(
            grants, server_name, tool_name, department_grants=department_grants
        )

    monkeypatch.setattr(workbench_module, "resolve_mcp_access", count_access)
    agent_grants.reads = 0
    department_grants.reads = 0
    server_store.reads = 0

    assert workbench.dispatch_tool_ids(agent_id, candidate_ids=[]) == ["find_mcp_tool"]
    assert agent_grants.reads == 0
    assert department_grants.reads == 0
    assert server_store.reads == 0
    assert resolved == []

    offered = workbench.dispatch_tool_ids(
        agent_id,
        candidate_ids=[
            warm_ids[99],
            warm_ids[5],
            warm_ids[6],
            warm_ids[8],
            "mcp:offline:missing",
            warm_ids[7],
            warm_ids[99],
            "",
        ],
    )

    assert offered == ["find_mcp_tool", warm_ids[99], warm_ids[7]]
    assert resolved == [
        ("offline", "tool_099"),
        ("offline", "tool_005"),
        ("offline", "tool_007"),
    ]
    assert agent_grants.reads == 1
    assert department_grants.reads == 0
    assert server_store.reads == 1
    assert bridge.client_reads == 0

    resolved.clear()
    server_store.records = [replace(record, enabled=False)]
    assert workbench.dispatch_tool_ids(
        agent_id, candidate_ids=[warm_ids[99], warm_ids[7]]
    ) == ["find_mcp_tool"]
    server_store.records = []
    assert workbench.dispatch_tool_ids(
        agent_id, candidate_ids=[warm_ids[99], warm_ids[7]]
    ) == ["find_mcp_tool"]
    assert resolved == []
    assert server_store.reads == 3
    assert bridge.client_reads == 0


class _SearchServerStore(_OfflineServerStore):
    def __init__(self, records: list[McpServerRecord]) -> None:
        super().__init__(records)
        self.fail_next_read = False

    def list_sync(self) -> list[McpServerRecord]:
        records = super().list_sync()
        if self.fail_next_read:
            self.fail_next_read = False
            raise RuntimeError("offline server read failed")
        return records


class _SearchClient:
    def __init__(self, tool_names: Sequence[str]) -> None:
        self.tools: list[dict[str, Any]] = [
            {
                "name": tool_name,
                "description": f"Offline lookup {tool_name}",
                "inputSchema": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                },
            }
            for tool_name in tool_names
        ]
        self.list_calls = 0
        self.on_list: Callable[[int], Awaitable[None]] | None = None

    async def list_tools(self) -> list[dict[str, Any]]:
        self.list_calls += 1
        if self.on_list is not None:
            await self.on_list(self.list_calls)
        return [dict(tool) for tool in self.tools]


class _SearchBridge:
    def __init__(self, client: _SearchClient) -> None:
        self.client = client
        self.client_reads = 0
        self.invocations: list[tuple[str, str, dict[str, Any]]] = []

    def get_client(self, server_url: str) -> _SearchClient | None:
        self.client_reads += 1
        return self.client if server_url == "offline" else None

    async def invoke(
        self, server_url: str, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        self.invocations.append((server_url, tool_name, dict(arguments)))
        return dict(arguments)


@dataclass
class _OfferEnv:
    workbench: MCPWorkbench
    registry: ToolRegistry
    permissions: ToolPermissionStore
    servers: _SearchServerStore
    bridge: _SearchBridge
    client: _SearchClient


def _make_offer_env() -> _OfferEnv:
    client = _SearchClient([f"tool_{index:03d}" for index in range(40)])
    bridge = _SearchBridge(client)
    servers = _SearchServerStore([
        McpServerRecord(
            name="offline", type="stdio", id="offline-server", default_risk="open"
        )
    ])
    permissions = ToolPermissionStore()
    registry = ToolRegistry()
    workbench = MCPWorkbench(
        tool_registry=registry,
        bridge=bridge,
        consensus_invoke=_no_consensus,
        episode_writer=None,
        server_store=servers,
        perm_store=permissions,
        dept_grant_store=None,
        risk_store=None,
        ontology=None,
        agent_registry=None,
    )
    return _OfferEnv(workbench, registry, permissions, servers, bridge, client)


@pytest.fixture
async def offer_env() -> _OfferEnv:
    environment = _make_offer_env()
    await environment.permissions.issue_grant(
        "agent", "mcp:offline", permission=ToolPermission.WRITE
    )
    return environment


def _tool_id(index: int) -> str:
    return f"mcp:offline:tool_{index:03d}"


def _query(start: int, count: int) -> str:
    return " ".join(f"{index:03d}" for index in range(start, start + count))


async def _search(
    environment: _OfferEnv,
    query: str,
    offer: MCPDispatchOffer | None = None,
    *,
    agent_id: str = "agent",
) -> ToolResult:
    registration = environment.registry.get(environment.workbench.register_search_tool())
    assert registration is not None
    context: dict[str, Any] = {"agent_id": agent_id}
    if offer is not None:
        context[MCP_DISPATCH_OFFER_CONTEXT_KEY] = offer
    return await registration.tool.invoke({"query": query}, context)


def _matched_ids(result: ToolResult) -> list[str]:
    assert result.error is None
    return [f"mcp:{match['server']}:{match['tool']}" for match in result.output["matches"]]


def _assert_counts(result: ToolResult, *, deferred: int = 0, failed: int = 0) -> None:
    assert result.error is None
    assert result.output["capacity_deferred_count"] == deferred
    assert result.output["failed_pull_count"] == failed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("preload_limit", "preload_count", "capacity"),
    [(-5, 0, 24), (0, 0, 24), (4, 4, 24), (24, 24, 24), (32, 32, 32)],
)
async def test_create_dispatch_offer_uses_run_preload_not_warm_population(
    offer_env: _OfferEnv, preload_limit: int, preload_count: int, capacity: int
) -> None:
    warm_ids = await offer_env.workbench.preload_open_tools("agent", limit=40)
    assert warm_ids == [_tool_id(index) for index in range(40)]
    assert offer_env.workbench.pulled_count == 40
    before = offer_env.client.list_calls

    offer = await offer_env.workbench.create_dispatch_offer(
        "agent", preload_limit=preload_limit
    )

    assert type(offer) is MCPDispatchOffer
    assert offer.capacity == capacity
    assert offer.selected_ids == tuple(warm_ids[:preload_count])
    assert offer.pending_ids == ()
    assert offer.belongs_to(offer_env.workbench, "agent") is True
    assert offer.belongs_to(offer_env.workbench, "other") is False
    assert offer_env.client.list_calls == before + int(preload_count > 0)
    assert offer_env.workbench.dispatch_tool_ids(
        "agent", candidate_ids=offer.selected_ids
    ) == ["find_mcp_tool", *warm_ids[:preload_count]]
    assert offer_env.workbench.dispatch_tool_ids("agent", candidate_ids=None) == [
        "find_mcp_tool", *warm_ids,
    ]
    if preload_count == 0:
        result = await _search(offer_env, "039", offer)
        assert _matched_ids(result) == [_tool_id(39)]
        assert offer.selected_ids == (_tool_id(39),)
        assert offer.pending_ids == offer.selected_ids
        _assert_counts(result)


@pytest.mark.asyncio
async def test_create_dispatch_offer_invalid_arguments_do_not_preload(
    offer_env: _OfferEnv,
) -> None:
    invalid_arguments: list[tuple[Any, Any]] = [
        ("", 24), (None, 24), ("agent", None), ("agent", "24"), ("agent", True),
    ]
    for agent_id, preload_limit in invalid_arguments:
        with pytest.raises((TypeError, ValueError)):
            await offer_env.workbench.create_dispatch_offer(
                agent_id, preload_limit=preload_limit
            )
        with pytest.raises((TypeError, ValueError)):
            MCPDispatchOffer(offer_env.workbench, agent_id, preload_limit=preload_limit)
    assert offer_env.client.list_calls == 0
    assert offer_env.workbench.pulled_count == 0


@pytest.mark.asyncio
async def test_offer_invalid_admissions_leave_bounded_seed_unchanged(
    offer_env: _OfferEnv,
) -> None:
    preloaded = await offer_env.workbench.preload_open_tools("agent", limit=3)
    offer = MCPDispatchOffer(
        offer_env.workbench, "agent", preload_limit=2,
        preloaded_ids=[
            "", "find_mcp_tool", "mcp::missing", preloaded[0], preloaded[0],
            preloaded[1], preloaded[2],
        ],
    )
    assert offer.selected_ids == tuple(preloaded[:2])
    assert offer.admit(preloaded[0]) is True
    before = (offer.selected_ids, offer.pending_ids)
    invalid_ids: list[Any] = ["", "find_mcp_tool", "plain", "mcp::tool", "mcp:offline:", None]
    for tool_id in invalid_ids:
        assert offer.admit(tool_id) is False
        assert (offer.selected_ids, offer.pending_ids) == before


@pytest.mark.asyncio
async def test_offer_duplicate_promotes_and_evicts_oldest_unpinned_only(
    offer_env: _OfferEnv,
) -> None:
    offer = await offer_env.workbench.create_dispatch_offer("agent", preload_limit=24)
    initial = offer.selected_ids
    evicted_registration = offer_env.registry.get(initial[1])
    assert evicted_registration is not None
    assert offer.admit(initial[0]) is True
    assert await offer_env.workbench.pull_tool("agent", "offline", "tool_024") is True

    assert offer.admit(_tool_id(24)) is True

    assert offer.selected_ids == (*initial[2:], initial[0], _tool_id(24))
    assert offer.pending_ids == (initial[0], _tool_id(24))
    assert offer_env.registry.get(initial[1]) is evicted_registration
    assert offer_env.workbench.pulled_count == 25
    assert offer.admit(initial[0]) is True
    assert offer.selected_ids[-1] == initial[0]
    assert len(offer.selected_ids) == offer.capacity
    assert set(offer.pending_ids) == {initial[0], _tool_id(24)}


@pytest.mark.asyncio
async def test_offer_pins_survive_failed_refresh_until_successful_publication(
    offer_env: _OfferEnv,
) -> None:
    offer = await offer_env.workbench.create_dispatch_offer("agent", preload_limit=24)
    for tool_id in offer.selected_ids:
        assert offer.admit(tool_id) is True
    initial = offer.selected_ids
    published = offer_env.workbench.dispatch_tool_ids("agent", candidate_ids=initial)
    assert published == ["find_mcp_tool", *initial]
    assert offer.pending_ids == initial

    offer_env.servers.fail_next_read = True
    with pytest.raises(RuntimeError, match="offline server read failed"):
        offer_env.workbench.dispatch_tool_ids("agent", candidate_ids=initial)
    with pytest.raises(ValueError, match="current offer"):
        offer.acknowledge_published([initial[0], _tool_id(39)])
    invalid_publications: list[Any] = [None, "mcp:offline:tool_000"]
    for invalid in invalid_publications:
        with pytest.raises(TypeError, match="sequence"):
            offer.acknowledge_published(invalid)
    assert offer.selected_ids == initial
    assert offer.pending_ids == initial
    assert offer.admit(_tool_id(24)) is False

    offer.acknowledge_published([*published, initial[0]])

    assert offer.selected_ids == initial
    assert offer.pending_ids == ()
    assert offer.admit(_tool_id(24)) is True
    assert offer.selected_ids == (*initial[1:], _tool_id(24))
    offer.acknowledge_published([])
    assert offer.selected_ids == ()
    assert offer.pending_ids == ()


@pytest.mark.asyncio
async def test_search_ranked_saturation_defers_then_allows_rediscovery(
    offer_env: _OfferEnv,
) -> None:
    offer = await offer_env.workbench.create_dispatch_offer("agent", preload_limit=0)
    for start in (0, 8, 16):
        result = await _search(offer_env, _query(start, 8), offer)
        assert _matched_ids(result) == [_tool_id(index) for index in range(start, start + 8)]
        _assert_counts(result)
    assert offer.selected_ids == tuple(_tool_id(index) for index in range(24))
    assert offer.pending_ids == offer.selected_ids

    saturated = await _search(offer_env, _query(23, 3), offer)

    assert _matched_ids(saturated) == [_tool_id(23)]
    _assert_counts(saturated, deferred=2)
    assert len(offer.selected_ids) == len(offer.pending_ids) == offer.capacity
    assert _tool_id(24) not in offer.selected_ids
    assert _tool_id(25) not in offer.selected_ids
    offer.acknowledge_published(offer_env.workbench.dispatch_tool_ids(
        "agent", candidate_ids=offer.selected_ids
    ))
    rediscovered = await _search(offer_env, _query(23, 3), offer)
    assert _matched_ids(rediscovered) == [_tool_id(23), _tool_id(24), _tool_id(25)]
    _assert_counts(rediscovered)
    assert _tool_id(0) not in offer.selected_ids
    assert _tool_id(1) not in offer.selected_ids
    assert offer.pending_ids == (_tool_id(23), _tool_id(24), _tool_id(25))
    assert MCP_DISPATCH_OFFER_CONTEXT_KEY not in json.dumps(rediscovered.output)
    assert rediscovered.metadata == {}


@pytest.mark.asyncio
async def test_search_counts_failed_pulls_without_pinning_or_consuming_capacity(
    offer_env: _OfferEnv,
) -> None:
    offer = await offer_env.workbench.create_dispatch_offer("agent", preload_limit=0)

    async def fail_pulls(call_number: int) -> None:
        if call_number == 1:
            offer_env.servers.fail_next_read = True
        elif call_number == 2:
            offer_env.client.tools = [
                tool for tool in offer_env.client.tools if tool["name"] != "tool_001"
            ]

    offer_env.client.on_list = fail_pulls
    result = await _search(offer_env, _query(0, 3), offer)

    assert offer_env.client.list_calls == 3
    assert _matched_ids(result) == [_tool_id(2)]
    _assert_counts(result, failed=2)
    assert offer.selected_ids == offer.pending_ids == (_tool_id(2),)
    assert offer_env.registry.get(_tool_id(0)) is None
    assert offer_env.registry.get(_tool_id(1)) is None
    assert offer_env.bridge.invocations == []


@pytest.mark.asyncio
@pytest.mark.parametrize("second_index", [30, 31])
async def test_overlapping_searches_cannot_evict_a_promised_match_or_oversubscribe(
    offer_env: _OfferEnv, second_index: int
) -> None:
    offer = await offer_env.workbench.create_dispatch_offer("agent", preload_limit=24)
    initial = offer.selected_ids
    for tool_id in initial[:23]:
        assert offer.admit(tool_id) is True
    assert len(offer.pending_ids) == 23
    blocked_call = offer_env.client.list_calls + 2
    started = asyncio.Event()
    release = asyncio.Event()

    async def pause_first_pull(call_number: int) -> None:
        if call_number == blocked_call:
            started.set()
            await release.wait()

    offer_env.client.on_list = pause_first_pull
    first_task = asyncio.create_task(_search(offer_env, "030", offer))
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        assert not first_task.done()
        second = await _search(offer_env, f"{second_index:03d}", offer)
        assert _matched_ids(second) == [_tool_id(second_index)]
        _assert_counts(second)
        release.set()
        first = await asyncio.wait_for(first_task, timeout=5)
    finally:
        release.set()
        if not first_task.done():
            first_task.cancel()
        await asyncio.gather(first_task, return_exceptions=True)

    assert _matched_ids(first) == ([_tool_id(30)] if second_index == 30 else [])
    _assert_counts(first, deferred=int(second_index != 30))
    assert offer.selected_ids == (*initial[:23], _tool_id(second_index))
    assert offer.pending_ids == offer.selected_ids
    assert len(offer.selected_ids) == offer.capacity


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["restriction", "disabled", "missing"])
async def test_pull_rechecks_current_authority_after_await_before_admission(
    offer_env: _OfferEnv, change: str
) -> None:
    offer = await offer_env.workbench.create_dispatch_offer("agent", preload_limit=0)

    async def change_during_pull(call_number: int) -> None:
        if call_number != 2:
            return
        if change == "restriction":
            await offer_env.permissions.issue_grant(
                "agent", _tool_id(0), permission=ToolPermission.NONE, is_restriction=True
            )
        elif change == "disabled":
            offer_env.servers.records = [replace(offer_env.servers.records[0], enabled=False)]
        else:
            offer_env.servers.records = []

    offer_env.client.on_list = change_during_pull
    result = await _search(offer_env, "000", offer)

    assert offer_env.client.list_calls == 2
    assert _matched_ids(result) == []
    _assert_counts(result, failed=1)
    assert offer.selected_ids == offer.pending_ids == ()
    assert offer_env.registry.get(_tool_id(0)) is None
    assert offer_env.bridge.invocations == []


@pytest.mark.asyncio
async def test_search_absent_offer_preserves_standalone_output_and_run_isolation(
    offer_env: _OfferEnv,
) -> None:
    offer = await offer_env.workbench.create_dispatch_offer("agent", preload_limit=0)
    no_match = await _search(offer_env, "zzzz", offer)
    assert _matched_ids(no_match) == []
    _assert_counts(no_match)

    standalone = await _search(offer_env, "000")

    assert _matched_ids(standalone) == [_tool_id(0)]
    assert set(standalone.output) == {"matches"}
    assert offer_env.registry.get(_tool_id(0)) is not None
    assert offer.selected_ids == offer.pending_ids == ()
    registration = offer_env.registry.get("find_mcp_tool")
    assert registration is not None
    context_absent = await registration.tool.invoke({"query": "000"})
    assert context_absent.error is None
    assert context_absent.output == {"matches": []}
    assert offer.selected_ids == ()


@pytest.mark.asyncio
async def test_search_invalid_parameters_preserve_existing_error_envelopes(
    offer_env: _OfferEnv,
) -> None:
    offer = await offer_env.workbench.create_dispatch_offer("agent", preload_limit=0)
    registration = offer_env.registry.get(offer_env.workbench.register_search_tool())
    assert registration is not None
    invalid_params: list[dict[str, Any]] = [
        {}, {"query": ""}, {"query": None},
        {"query": "000", "unexpected": True},
        {"query": "000", MCP_DISPATCH_OFFER_CONTEXT_KEY: "untrusted"},
    ]
    for params in invalid_params:
        result = await registration.tool.invoke(params, {
            "agent_id": "agent", MCP_DISPATCH_OFFER_CONTEXT_KEY: offer,
        })
        assert result.error is not None
        assert result.output is None
        if not params.get("query"):
            assert result.error == "find_mcp_tool requires a non-empty 'query'."
    assert offer_env.client.list_calls == 0
    assert offer.selected_ids == offer.pending_ids == ()
    assert _matched_ids(await _search(offer_env, "000", offer)) == [_tool_id(0)]


@pytest.mark.asyncio
async def test_search_cancellation_propagates_without_admitting_unfinished_pull(
    offer_env: _OfferEnv,
) -> None:
    offer = await offer_env.workbench.create_dispatch_offer("agent", preload_limit=0)

    async def cancel_pull(call_number: int) -> None:
        if call_number == 2:
            raise asyncio.CancelledError

    offer_env.client.on_list = cancel_pull
    with pytest.raises(asyncio.CancelledError):
        await _search(offer_env, "000", offer)
    assert offer_env.client.list_calls == 2
    assert offer.selected_ids == offer.pending_ids == ()
    assert offer_env.registry.get(_tool_id(0)) is None
    assert offer_env.bridge.invocations == []


@pytest.mark.asyncio
async def test_search_malformed_offer_or_coerced_identity_cannot_mutate_run(
    offer_env: _OfferEnv,
) -> None:
    offer = await offer_env.workbench.create_dispatch_offer("agent", preload_limit=0)
    registration = offer_env.registry.get(offer_env.workbench.register_search_tool())
    assert registration is not None
    for malformed in (None, {}, "serialized-offer", 0):
        result = await registration.tool.invoke({"query": "000"}, {
            "agent_id": "agent", MCP_DISPATCH_OFFER_CONTEXT_KEY: malformed,
        })
        assert result.error == "find_mcp_tool received an invalid dispatch offer."
        assert result.output is None
    await offer_env.permissions.issue_grant(
        "123", "mcp:offline", permission=ToolPermission.WRITE
    )
    numeric_offer = await offer_env.workbench.create_dispatch_offer("123", preload_limit=0)
    result = await registration.tool.invoke({"query": "000"}, {
        "agent_id": 123, MCP_DISPATCH_OFFER_CONTEXT_KEY: numeric_offer,
    })
    assert result.error == "find_mcp_tool received an invalid dispatch offer."
    assert offer_env.client.list_calls == 0
    assert offer.selected_ids == numeric_offer.selected_ids == ()
    control = await _search(offer_env, "000", numeric_offer, agent_id="123")
    assert _matched_ids(control) == [_tool_id(0)]
    assert offer.selected_ids == offer.pending_ids == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["agent", "workbench"])
async def test_search_mismatched_owner_cannot_mutate_another_offer(
    offer_env: _OfferEnv, mismatch: str
) -> None:
    invoking_agent = "other" if mismatch == "agent" else "agent"
    await offer_env.permissions.issue_grant(
        invoking_agent, "mcp:offline", permission=ToolPermission.WRITE
    )
    foreign = _make_offer_env()
    owner = offer_env.workbench if mismatch == "agent" else foreign.workbench
    protected = await owner.create_dispatch_offer("agent", preload_limit=0)
    valid = await offer_env.workbench.create_dispatch_offer(invoking_agent, preload_limit=0)
    registration = offer_env.registry.get(offer_env.workbench.register_search_tool())
    assert registration is not None
    assert protected.belongs_to(offer_env.workbench, invoking_agent) is False

    refused = await registration.tool.invoke({"query": "000"}, {
        "agent_id": invoking_agent, MCP_DISPATCH_OFFER_CONTEXT_KEY: protected,
    })

    assert refused.error == "find_mcp_tool received an invalid dispatch offer."
    assert protected.selected_ids == protected.pending_ids == ()
    assert offer_env.client.list_calls == foreign.client.list_calls == 0
    control = await _search(offer_env, "000", valid, agent_id=invoking_agent)
    assert _matched_ids(control) == [_tool_id(0)]
    assert protected.selected_ids == ()
    assert valid.selected_ids == (_tool_id(0),)


@pytest.mark.asyncio
async def test_same_agent_runs_have_independent_selection_and_publication_pins(
    offer_env: _OfferEnv,
) -> None:
    first = await offer_env.workbench.create_dispatch_offer("agent", preload_limit=0)
    assert _matched_ids(await _search(offer_env, "000", first)) == [_tool_id(0)]
    second = await offer_env.workbench.create_dispatch_offer("agent", preload_limit=0)
    assert second is not first
    assert second.selected_ids == second.pending_ids == ()
    assert _matched_ids(await _search(offer_env, "001", second)) == [_tool_id(1)]

    first.acknowledge_published(offer_env.workbench.dispatch_tool_ids(
        "agent", candidate_ids=first.selected_ids
    ))

    assert first.selected_ids == (_tool_id(0),)
    assert first.pending_ids == ()
    assert second.selected_ids == second.pending_ids == (_tool_id(1),)
    assert first.belongs_to(offer_env.workbench, "agent") is True
    assert second.belongs_to(offer_env.workbench, "agent") is True


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["disabled", "missing", "store_error", "restriction"])
async def test_warm_adapter_invoke_rechecks_current_server_and_grants(
    offer_env: _OfferEnv, change: str
) -> None:
    offer = await offer_env.workbench.create_dispatch_offer("agent", preload_limit=0)
    assert _matched_ids(await _search(offer_env, "000", offer)) == [_tool_id(0)]
    registration = offer_env.registry.get(_tool_id(0))
    assert registration is not None
    control = await registration.tool.invoke({"value": "control"}, {"agent_id": "agent"})
    assert control.success is True
    assert control.output == {"value": "control"}
    assert len(offer_env.bridge.invocations) == 1
    if change == "disabled":
        offer_env.servers.records = [replace(offer_env.servers.records[0], enabled=False)]
    elif change == "missing":
        offer_env.servers.records = []
    elif change == "store_error":
        offer_env.servers.fail_next_read = True
    else:
        await offer_env.permissions.issue_grant(
            "agent", _tool_id(0), permission=ToolPermission.NONE, is_restriction=True
        )

    denied = await registration.tool.invoke({"value": "denied"}, {"agent_id": "agent"})

    assert denied.error is not None
    assert "not authorized" in denied.error
    assert len(offer_env.bridge.invocations) == 1


@pytest.mark.asyncio
async def test_deliberate_search_restores_missing_adapter_without_enabling_disabled_one(
    offer_env: _OfferEnv,
) -> None:
    offer = await offer_env.workbench.create_dispatch_offer("agent", preload_limit=0)
    assert _matched_ids(await _search(offer_env, "000", offer)) == [_tool_id(0)]
    original = offer_env.registry.get(_tool_id(0))
    assert original is not None
    assert offer_env.registry.unregister(_tool_id(0)) is True
    filtered = offer_env.workbench.dispatch_tool_ids("agent", candidate_ids=offer.selected_ids)
    assert filtered == ["find_mcp_tool"]
    offer.acknowledge_published(filtered)
    assert offer.selected_ids == offer.pending_ids == ()

    restored_result = await _search(offer_env, "000", offer)

    assert _matched_ids(restored_result) == [_tool_id(0)]
    restored = offer_env.registry.get(_tool_id(0))
    assert restored is not None
    assert restored.tool is not original.tool
    assert offer_env.workbench.pulled_count == 1
    offer_env.registry.register(restored.tool, enabled=False)
    disabled_result = await _search(offer_env, "000", offer)
    assert _matched_ids(disabled_result) == []
    _assert_counts(disabled_result, failed=1)
    disabled = offer_env.registry.get(_tool_id(0))
    assert disabled is not None
    assert disabled.enabled is False
    offer.acknowledge_published(offer_env.workbench.dispatch_tool_ids(
        "agent", candidate_ids=offer.selected_ids
    ))
    assert offer.selected_ids == offer.pending_ids == ()
    await offer_env.workbench.unload_tool(_tool_id(0))
    assert offer_env.workbench.pulled_count == 0
    assert offer_env.registry.get(_tool_id(0)) is None
    assert _matched_ids(await _search(offer_env, "000", offer)) == [_tool_id(0)]


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True], ids=["legacy", "structured"])
async def test_dispatch_full_offer_discovers_and_invokes_echo_next_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, structured: bool
) -> None:
    fixture = Path(__file__).parent / "fixtures" / "echo_mcp_server.py"
    assert fixture.is_file()
    agent_id = "agent"
    capacity = 24
    preload_servers = [f"preload-{index:02d}" for index in range(8)]
    discovery_server = "aaa-discovery"
    discovery_id = f"mcp:{discovery_server}:echo"
    discovery_alias = llm_function_name(discovery_id)
    initial_ids = [
        f"mcp:{server}:{tool}"
        for server in preload_servers
        for tool in ("badjson", "echo", "slow")
    ]
    initial_aliases = [llm_function_name(tool_id) for tool_id in initial_ids]
    echo_arguments = {"q": "ad1241-echo-roundtrip"}
    offers: list[MCPDispatchOffer] = []
    bridge_calls: list[tuple[str, str, dict[str, Any], dict[str, Any]]] = []

    async with AsyncExitStack() as cleanup:
        bridge = MCPBridge(
            request_timeout=5.0,
            stdio_enabled=True,
            command_allowlist=[sys.executable],
        )
        cleanup.push_async_callback(bridge.close_all)
        servers = McpServerStore(db_path=str(tmp_path / "servers.db"))
        cleanup.push_async_callback(servers.stop)
        await servers.start()
        permissions = ToolPermissionStore(db_path=str(tmp_path / "permissions.db"))
        cleanup.push_async_callback(permissions.stop)
        await permissions.start()
        for server in [*preload_servers, discovery_server]:
            assert await bridge.register_stdio_server(
                name=server, command=sys.executable, args=[str(fixture)],
                env={}, cwd="", timeout=5.0,
            ) is True
            assert bridge.get_client(server) is not None
            await servers.create(McpServerRecord(
                name=server, type="stdio", command=sys.executable,
                args=[str(fixture)], default_risk="open",
            ))
        for server in preload_servers:
            await permissions.issue_grant(
                agent_id, f"mcp:{server}", permission=ToolPermission.WRITE
            )
        assert resolve_mcp_access(
            permissions.get_active_grants_sync(agent_id), discovery_server, "echo"
        )[0] is False

        registry = ToolRegistry()
        registry.set_permission_store(permissions)
        workbench = MCPWorkbench(
            tool_registry=registry,
            bridge=bridge,
            consensus_invoke=_no_consensus,
            episode_writer=None,
            server_store=servers,
            perm_store=permissions,
            dept_grant_store=None,
            risk_store=None,
            ontology=None,
            agent_registry=None,
        )
        assert workbench.pulled_count == 0
        assert workbench.dispatch_tool_ids(agent_id, candidate_ids=()) == ["find_mcp_tool"]

        real_invoke = bridge.invoke

        async def record_bridge_invoke(
            server_url: str, tool_name: str, arguments: dict[str, Any]
        ) -> dict[str, Any]:
            output = await real_invoke(server_url, tool_name, arguments)
            bridge_calls.append((server_url, tool_name, dict(arguments), output))
            return output

        monkeypatch.setattr(bridge, "invoke", record_bridge_invoke)

        class _OrdinaryTool:
            tool_id: str = "ordinary_probe"
            name: str = "Ordinary Probe"
            tool_type: ToolType = ToolType.UTILITY_AGENT
            description: str = "Return a deterministic progress marker."
            input_schema: dict[str, Any] = {"type": "object", "properties": {}}
            output_schema: dict[str, Any] = {"type": "object"}

            async def invoke(
                self, params: dict[str, Any], context: dict[str, Any] | None = None
            ) -> ToolResult:
                assert params == {}
                assert type(context) is dict
                assert context["agent_id"] == agent_id
                assert context["department"] == "engineering"
                offer = context.get(MCP_DISPATCH_OFFER_CONTEXT_KEY)
                assert type(offer) is MCPDispatchOffer
                assert offer.belongs_to(workbench, agent_id)
                assert offer.capacity == capacity
                assert offer.selected_ids == tuple(initial_ids)
                assert offer.pending_ids == ()
                assert workbench.pulled_count == capacity
                assert all(registry.get(tool_id) is not None for tool_id in initial_ids)
                assert registry.get(discovery_id) is None
                offers.append(offer)
                await permissions.issue_grant(
                    agent_id, discovery_id, permission=ToolPermission.WRITE
                )
                return ToolResult(output={"ordinary_complete": True})

        registry.register(_OrdinaryTool())
        await permissions.issue_grant(
            agent_id, "ordinary_probe", permission=ToolPermission.READ
        )

        class _ScriptedDispatchLLM:
            def __init__(self) -> None:
                self.requests: list[LLMRequest] = []

            async def complete(self, request: LLMRequest, **kwargs: Any) -> LLMResponse:
                request_index = len(self.requests)
                self.requests.append(request)
                assert bool(request.messages) is structured
                definitions = {
                    definition["function"]["name"]: definition["function"]
                    for definition in request.tools or []
                }
                assert len(definitions) == len(request.tools or []) == capacity + 2
                assert all(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name) for name in definitions)
                assert MCP_DISPATCH_OFFER_CONTEXT_KEY not in json.dumps(request.tools)
                history = json.dumps(request.messages) if structured else request.prompt
                if request_index == 0:
                    assert list(definitions) == [
                        "ordinary_probe", "find_mcp_tool", *initial_aliases,
                    ]
                    assert discovery_alias not in definitions
                    call = ToolCallRequest(name="ordinary_probe", arguments={}, id="ordinary-call")
                elif request_index == 1:
                    assert len(offers) == 1
                    assert "ordinary_complete" in history
                    assert resolve_mcp_access(
                        permissions.get_active_grants_sync(agent_id), discovery_server, "echo"
                    )[0] is True
                    assert request.tools is self.requests[0].tools
                    assert offers[0].selected_ids == tuple(initial_ids)
                    assert discovery_alias not in definitions
                    call = ToolCallRequest(
                        name="find_mcp_tool", arguments={"query": "echo arguments"},
                        id="discovery-call",
                    )
                elif request_index == 2:
                    assert "capacity_deferred_count" in history
                    assert "failed_pull_count" in history
                    assert discovery_server in history
                    assert workbench.pulled_count == capacity + 1
                    assert registry.get(discovery_id) is not None
                    assert registry.get(initial_ids[0]) is not None
                    assert discovery_alias in definitions
                    assert discovery_alias != discovery_id
                    assert initial_aliases[0] not in definitions
                    assert set(definitions) == {
                        "ordinary_probe", "find_mcp_tool", *initial_aliases[1:], discovery_alias,
                    }
                    parameters = definitions[discovery_alias]["parameters"]
                    assert parameters["required"] == ["q"]
                    assert parameters["properties"]["q"]["type"] == "string"
                    assert discovery_id in offers[0].selected_ids
                    assert offers[0].pending_ids == ()
                    call = ToolCallRequest(
                        name=discovery_alias, arguments=echo_arguments, id="echo-call"
                    )
                elif request_index == 3:
                    assert request.tools is self.requests[2].tools
                    assert len(bridge_calls) == 1
                    server_url, tool_name, arguments, output = bridge_calls[0]
                    assert (server_url, tool_name, arguments) == (
                        discovery_server, "echo", echo_arguments,
                    )
                    assert json.loads(output["content"][0]["text"]) == echo_arguments
                    if structured:
                        results = [
                            message for message in request.messages or []
                            if message.get("role") == "tool"
                        ]
                        assert [message["tool_call_id"] for message in results] == [
                            "ordinary-call", "discovery-call", "echo-call",
                        ]
                        assert echo_arguments["q"] in results[-1]["content"]
                    else:
                        assert "[tool_result:echo-call error=False]" in request.prompt
                        assert echo_arguments["q"] in request.prompt
                    return LLMResponse(
                        content="echo crossing complete", tier="fast", tokens_used=1,
                        content_blocks=[TextBlock(text="echo crossing complete")],
                    )
                else:
                    raise AssertionError("The scripted crossing must complete in four requests")
                return LLMResponse(
                    content="", tier="fast", tokens_used=1,
                    content_blocks=[ToolUseBlock(tool_call=call)],
                )

        llm = _ScriptedDispatchLLM()
        runtime = SimpleNamespace(
            tool_registry=registry,
            tool_permission_store=permissions,
            mcp_workbench=workbench,
            config=SimpleNamespace(
                mcp=SimpleNamespace(agent_tools_enabled=True, max_directly_offered_tools=capacity),
                agentic_loop=SimpleNamespace(structured_tool_messages=structured),
            ),
        )
        outcome = await WorkItemAgenticExecutor(llm_client=llm).run(
            agent_id=agent_id,
            instructions="Use the offered tools to complete the echo task.",
            task_text="Run the ordinary probe, discover echo, and invoke the offered echo tool.",
            runtime=runtime,
            department="engineering",
            rank="lieutenant",
            max_iterations=5,
            tier="fast",
            extra_context={"agent_id": "untrusted-agent", "department": "untrusted-department"},
        )

        assert outcome.stopped_reason == "complete"
        assert outcome.final_text == "echo crossing complete"
        assert outcome.denied_tools == []
        assert len(llm.requests) == 4
        assert len(offers) == 1
        assert len(bridge_calls) == 1
        assert len(offers[0].selected_ids) == capacity
        assert offers[0].pending_ids == ()
        assert initial_ids[0] not in offers[0].selected_ids
        assert workbench.pulled_count == capacity + 1
        assert registry.get(initial_ids[0]) is not None


class _DispatchProbe:
    tool_id: str = "ordinary_probe"
    name: str = "Ordinary Probe"
    tool_type: ToolType = ToolType.UTILITY_AGENT
    description: str = "Return a deterministic progress marker."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {"marker": {"type": "string"}},
        "required": ["marker"],
    }
    output_schema: dict[str, Any] = {"type": "object"}

    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, Any], dict[str, Any]]] = []
        self.assertions: list[str] = []
        self.on_invoke: Callable[
            [dict[str, Any], dict[str, Any]], Awaitable[None]
        ] | None = None

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None
    ) -> ToolResult:
        supplied_context = dict(context or {})
        self.calls.append((dict(params), supplied_context))
        try:
            if self.on_invoke is not None:
                await self.on_invoke(params, supplied_context)
            return ToolResult(output={"marker": params["marker"]})
        except AssertionError as exc:
            self.assertions.append(str(exc))
            raise


class _TraceRecorder:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def write(
        self, *, content_hash: str, blob: bytes, mime: str, origin: str
    ) -> None:
        assert mime == "application/json"
        assert origin == "crew_trace"
        self.blobs[content_hash] = blob


class _BoundaryLLM:
    def __init__(
        self,
        step: Callable[[int, LLMRequest], Awaitable[list[ToolCallRequest] | None]],
    ) -> None:
        self.step = step
        self.requests: list[LLMRequest] = []
        self.assertions: list[str] = []

    async def complete(self, request: LLMRequest, **kwargs: Any) -> LLMResponse:
        request_index = len(self.requests)
        self.requests.append(request)
        try:
            names = _offered_names(request)
            assert len(names) == len(set(names))
            assert all(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name) for name in names)
            assert MCP_DISPATCH_OFFER_CONTEXT_KEY not in json.dumps(request.tools)
            calls = await self.step(request_index, request)
        except AssertionError as exc:
            self.assertions.append(str(exc))
            raise
        if calls is None:
            return LLMResponse(
                content="boundary complete", tier="fast", tokens_used=1,
                content_blocks=[TextBlock(text="boundary complete")],
            )
        return LLMResponse(
            content="", tier="fast", tokens_used=1,
            content_blocks=[ToolUseBlock(tool_call=call) for call in calls],
        )


@dataclass
class _DispatchEnv:
    workbench: MCPWorkbench
    registry: ToolRegistry
    permissions: ToolPermissionStore
    departments: ToolPermissionStore
    agent_grants: _CountingGrants
    department_grants: _CountingGrants
    access_grant: ToolAccessGrant
    servers: McpServerStore
    server: McpServerRecord
    bridge: MCPBridge | _SearchBridge
    client: _SearchClient | None
    probe: _DispatchProbe
    traces: _TraceRecorder
    events: list[tuple[str, dict[str, Any]]]
    runtime: SimpleNamespace


@asynccontextmanager
async def _dispatch_environment(
    tmp_path: Path, *, echo: bool = False
) -> AsyncIterator[_DispatchEnv]:
    async with AsyncExitStack() as cleanup:
        servers = McpServerStore(db_path=str(tmp_path / "boundary-servers.db"))
        permissions = ToolPermissionStore(db_path=str(tmp_path / "boundary-agent.db"))
        departments = ToolPermissionStore(db_path=str(tmp_path / "boundary-department.db"))
        for store in (servers, permissions, departments):
            cleanup.push_async_callback(store.stop)
            await store.start()
        client = None if echo else _SearchClient([
            f"tool_{index:03d}" for index in range(100)
        ])
        bridge: MCPBridge | _SearchBridge
        if echo:
            fixture = Path(__file__).parent / "fixtures" / "echo_mcp_server.py"
            assert fixture.is_file()
            bridge = MCPBridge(
                request_timeout=5.0, stdio_enabled=True,
                command_allowlist=[sys.executable],
            )
            cleanup.push_async_callback(bridge.close_all)
            assert await bridge.register_stdio_server(
                name="offline", command=sys.executable, args=[str(fixture)],
                env={}, cwd="", timeout=5.0,
            ) is True
        else:
            assert client is not None
            bridge = _SearchBridge(client)
        server = await servers.create(McpServerRecord(
            name="offline", type="stdio", command=sys.executable, default_risk="open",
        ))
        registry = ToolRegistry()
        registry.set_permission_store(permissions)
        agent_grants = _CountingGrants(permissions)
        department_grants = _CountingGrants(departments)
        workbench = MCPWorkbench(
            tool_registry=registry, bridge=bridge, consensus_invoke=_no_consensus,
            episode_writer=None, server_store=servers, perm_store=agent_grants,
            dept_grant_store=department_grants, risk_store=None,
            ontology=SimpleNamespace(get_agent_department=lambda agent_type: "engineering"),
            agent_registry=SimpleNamespace(
                get=lambda agent_id: SimpleNamespace(agent_type="builder")
                if agent_id in {"agent", "other"} else None
            ),
        )
        access_grant = await permissions.issue_grant(
            "agent", "mcp:offline", permission=ToolPermission.WRITE
        )
        probe = _DispatchProbe()
        registry.register(probe)
        await permissions.issue_grant("agent", probe.tool_id, permission=ToolPermission.READ)
        traces = _TraceRecorder()
        events: list[tuple[str, dict[str, Any]]] = []

        def record_event(event_type: Any, payload: dict[str, Any]) -> None:
            events.append((event_type.name, dict(payload)))

        runtime = SimpleNamespace(
            tool_registry=registry, tool_permission_store=permissions,
            mcp_workbench=workbench, attachment_store=traces, emit_event=record_event,
            config=SimpleNamespace(
                mcp=SimpleNamespace(agent_tools_enabled=True, max_directly_offered_tools=0),
                agentic_loop=SimpleNamespace(structured_tool_messages=True),
            ),
        )
        yield _DispatchEnv(
            workbench, registry, permissions, departments, agent_grants,
            department_grants, access_grant, servers, server, bridge, client,
            probe, traces, events, runtime,
        )


@pytest.fixture
async def dispatch_env(tmp_path: Path) -> AsyncIterator[_DispatchEnv]:
    async with _dispatch_environment(tmp_path) as environment:
        yield environment


@pytest.fixture
async def echo_dispatch_env(tmp_path: Path) -> AsyncIterator[_DispatchEnv]:
    async with _dispatch_environment(tmp_path, echo=True) as environment:
        yield environment


def _offered_names(request: LLMRequest) -> list[str]:
    return [definition["function"]["name"] for definition in request.tools or []]


def _call(name: str, call_id: str, **arguments: Any) -> ToolCallRequest:
    return ToolCallRequest(name=name, arguments=arguments, id=call_id)


def _history(request: LLMRequest) -> str:
    assert request.messages is not None
    return json.dumps(request.messages)


def _assert_script(environment: _DispatchEnv, llm: _BoundaryLLM, requests: int) -> None:
    assert llm.assertions == []
    assert environment.probe.assertions == []
    assert len(llm.requests) == requests


def _assert_trace(
    environment: _DispatchEnv, outcome: WorkItemAgenticOutcome, calls: int
) -> None:
    assert outcome.tool_trace_ref is not None
    blob = environment.traces.blobs[outcome.tool_trace_ref]
    assert len(json.loads(blob)) == calls
    assert MCP_DISPATCH_OFFER_CONTEXT_KEY.encode() not in blob
    assert b"MCPDispatchOffer" not in blob
    assert "MCPDispatchOffer" not in repr(outcome)
    assert MCP_DISPATCH_OFFER_CONTEXT_KEY not in json.dumps(environment.events)


async def _run_dispatch(
    environment: _DispatchEnv,
    llm: _BoundaryLLM,
    *,
    agent_id: str = "agent",
    task_text: str = "AD-1241 boundary task",
    extra_context: dict[str, Any] | None = None,
    executor: WorkItemAgenticExecutor | None = None,
) -> WorkItemAgenticOutcome:
    executor = executor or WorkItemAgenticExecutor(llm_client=llm)
    return await executor.run(
        agent_id=agent_id, instructions="Use the offered tools.", task_text=task_text,
        runtime=environment.runtime, department="engineering", rank="lieutenant",
        max_iterations=8, tier="fast", extra_context=extra_context,
    )


async def _warm_dispatch(environment: _DispatchEnv, count: int = 100) -> list[str]:
    assert environment.client is not None
    assert environment.workbench.pulled_count == 0
    assert environment.workbench.dispatch_tool_ids("agent", candidate_ids=[]) == [
        "find_mcp_tool",
    ]
    pulled: list[bool] = []
    for descriptor in environment.client.tools[:count]:
        pulled.append(await environment.workbench.pull_tool(
            "agent", "offline", descriptor["name"],
            descriptor={
                "name": descriptor["name"], "description": descriptor["description"],
                "input_schema": descriptor["inputSchema"],
            },
        ))
    warm_ids = [_tool_id(index) for index in range(count)]
    assert pulled == [True] * count
    assert environment.workbench.pulled_count == count
    assert all(environment.registry.get(tool_id) is not None for tool_id in warm_ids)
    return warm_ids


@pytest.mark.asyncio
async def test_real_ordinary_refresh_cost_is_bounded_with_one_hundred_warm_adapters(
    dispatch_env: _DispatchEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = dispatch_env
    warm_ids = await _warm_dispatch(environment)
    environment.runtime.config.mcp.max_directly_offered_tools = 24
    assert environment.client is not None
    assert isinstance(environment.bridge, _SearchBridge)
    counting = False
    resolved: list[str] = []
    selections: list[tuple[str, ...]] = []
    assemblies: list[str] = []
    bridge_reads = 0
    enumerations = 0
    real_select = environment.workbench.dispatch_tool_ids
    real_definition = tool_call_module.tool_registration_to_llm_definition

    def count_access(
        grants: list[ToolAccessGrant], server_name: str, tool_name: str,
        *, department_grants: Sequence[ToolAccessGrant] = (),
    ) -> tuple[bool, str]:
        if counting:
            resolved.append(f"mcp:{server_name}:{tool_name}")
        return resolve_mcp_access(
            grants, server_name, tool_name, department_grants=department_grants
        )

    def count_selection(
        agent_id: str, *, candidate_ids: Sequence[str] | None = None
    ) -> list[str]:
        if counting:
            assert candidate_ids is not None
            selections.append(tuple(candidate_ids))
        return real_select(agent_id, candidate_ids=candidate_ids)

    def count_assembly(registration: Any) -> dict[str, Any]:
        if counting:
            assemblies.append(registration.tool.tool_id)
        return real_definition(registration)

    monkeypatch.setattr(workbench_module, "resolve_mcp_access", count_access)
    monkeypatch.setattr(environment.workbench, "dispatch_tool_ids", count_selection)
    monkeypatch.setattr(tool_call_module, "tool_registration_to_llm_definition", count_assembly)

    async def step(index: int, request: LLMRequest) -> list[ToolCallRequest] | None:
        nonlocal counting, bridge_reads, enumerations
        assert _offered_names(request) == [
            "ordinary_probe", "find_mcp_tool",
            *(llm_function_name(tool_id) for tool_id in warm_ids[:24]),
        ]
        if index == 0:
            environment.agent_grants.reads = 0
            environment.department_grants.reads = 0
            bridge_reads = environment.bridge.client_reads
            enumerations = environment.client.list_calls
            assert enumerations == 1
            counting = True
        else:
            assert request.tools is llm.requests[0].tools
            assert len(environment.probe.calls) == index
            assert len(selections) == index
            assert environment.agent_grants.reads == index
            assert environment.department_grants.reads == index
            assert environment.bridge.client_reads == bridge_reads
            assert environment.client.list_calls == enumerations
            assert f"ordinary-{index - 1}" in _history(request)
        if index < 2:
            return [_call("ordinary_probe", f"ordinary-{index}", marker=f"ordinary-{index}")]
        assert index == 2
        return None

    llm = _BoundaryLLM(step)
    outcome = await _run_dispatch(environment, llm)

    _assert_script(environment, llm, 3)
    assert outcome.stopped_reason == "complete"
    assert len(environment.probe.calls) == 2
    assert selections == [tuple(warm_ids[:24])] * 2
    assert environment.agent_grants.reads == 2
    assert environment.department_grants.reads == 2
    assert resolved == warm_ids[:24] * 2
    assert set(resolved).isdisjoint(warm_ids[24:])
    assert assemblies == []
    assert environment.bridge.invocations == []
    _assert_trace(environment, outcome, 2)


@pytest.mark.asyncio
@pytest.mark.parametrize("preload_limit", [0, 24, 32], ids=["zero", "default", "larger"])
async def test_real_warm_offer_policy_raw_grants_and_browser_order(
    dispatch_env: _DispatchEnv, preload_limit: int
) -> None:
    environment = dispatch_env
    warm_ids = await _warm_dispatch(environment)
    environment.runtime.config.mcp.max_directly_offered_tools = preload_limit
    environment.runtime.config.agentic_tools = SimpleNamespace(browser_enabled=True)
    browser = BrowserTool(config=BrowserToolConfig(enabled=True))
    environment.registry.register(browser)
    await environment.permissions.issue_grant("agent", warm_ids[-1], ToolPermission.WRITE)
    await environment.permissions.issue_grant("agent", "find_mcp_tool", ToolPermission.READ)
    assert resolve_mcp_access(
        environment.permissions.get_active_grants_sync("agent"), "offline", "tool_099"
    )[0] is True
    ordinary_registration = environment.registry.get("ordinary_probe")
    browser_registration = environment.registry.get("browser")
    assert ordinary_registration is not None and browser_registration is not None
    ordinary_bytes = json.dumps(tool_call_module.tool_registration_to_llm_definition(
        ordinary_registration
    ))
    browser_bytes = json.dumps(tool_call_module.tool_registration_to_llm_definition(
        browser_registration
    ))
    browser_schema_bytes = json.dumps(browser.input_schema)
    declared_actions = browser.input_schema["properties"]["action"]["enum"]
    assert "click" in declared_actions
    allowed_actions = {"goto", "state", "extract_text", "back", "forward", "wait"}
    initial = warm_ids[:preload_limit]
    capacity = max(24, preload_limit)
    refreshed = [*(initial[1:] if len(initial) == capacity else initial), warm_ids[-1]]

    async def step(index: int, request: LLMRequest) -> list[ToolCallRequest] | None:
        selected = initial if index < 2 else refreshed
        assert _offered_names(request) == [
            "ordinary_probe", "find_mcp_tool",
            *(llm_function_name(tool_id) for tool_id in selected), "browser",
        ]
        assert len(selected) <= capacity
        assert json.dumps(request.tools[0]) == ordinary_bytes
        offered_browser = request.tools[-1]["function"]
        assert offered_browser["parameters"]["properties"]["action"]["enum"] == [
            action for action in declared_actions if action in allowed_actions
        ]
        assert "read-only" in offered_browser["description"].lower()
        if index == 0:
            assert environment.client is not None
            assert environment.client.list_calls == int(preload_limit > 0)
            return [_call("ordinary_probe", "policy-initial", marker="policy-initial")]
        offer = environment.probe.calls[0][1][MCP_DISPATCH_OFFER_CONTEXT_KEY]
        assert type(offer) is MCPDispatchOffer
        assert offer.capacity == capacity
        assert offer.selected_ids == tuple(selected)
        assert offer.pending_ids == ()
        if index == 1:
            assert request.tools is llm.requests[0].tools
            return [_call("find_mcp_tool", "policy-discovery", query="099")]
        if index == 2:
            assert "policy-discovery" in _history(request)
            return [_call("ordinary_probe", "policy-refresh", marker="policy-refresh")]
        assert index == 3
        assert request.tools is llm.requests[2].tools
        return None

    llm = _BoundaryLLM(step)
    outcome = await _run_dispatch(environment, llm)

    _assert_script(environment, llm, 4)
    assert outcome.stopped_reason == "complete"
    assert json.dumps(browser.input_schema) == browser_schema_bytes
    assert json.dumps(tool_call_module.tool_registration_to_llm_definition(
        browser_registration
    )) == browser_bytes
    assert environment.workbench.pulled_count == 100
    _assert_trace(environment, outcome, 3)


@pytest.mark.asyncio
@pytest.mark.parametrize("gate", ["disabled", "missing-workbench"])
async def test_real_mcp_off_does_not_create_read_refresh_or_leak_raw_grants(
    dispatch_env: _DispatchEnv, monkeypatch: pytest.MonkeyPatch, gate: str
) -> None:
    environment = dispatch_env
    warm_ids = await _warm_dispatch(environment)
    await environment.permissions.issue_grant("agent", warm_ids[-1], ToolPermission.WRITE)
    await environment.permissions.issue_grant("agent", "find_mcp_tool", ToolPermission.READ)
    if gate == "disabled":
        environment.runtime.config.mcp.agent_tools_enabled = False
    else:
        environment.runtime.mcp_workbench = None
    activity: list[str] = []
    loop_options: list[set[str]] = []
    real_loop = loop_module.AgenticLoop

    def observe_loop(**kwargs: Any) -> Any:
        loop_options.append(set(kwargs))
        return real_loop(**kwargs)

    async def forbid_factory(agent_id: str, *, preload_limit: int) -> MCPDispatchOffer:
        activity.append("factory")
        raise AssertionError("MCP-off constructed an offer")

    async def forbid_preload(agent_id: str, *, limit: int) -> list[str]:
        activity.append("preload")
        raise AssertionError("MCP-off preloaded adapters")

    def forbid_selection(
        agent_id: str, *, candidate_ids: Sequence[str] | None = None
    ) -> list[str]:
        activity.append("selection")
        raise AssertionError("MCP-off selected adapters")

    def forbid_server_read() -> list[McpServerRecord]:
        activity.append("server-read")
        raise AssertionError("MCP-off read server state")

    monkeypatch.setattr(loop_module, "AgenticLoop", observe_loop)
    monkeypatch.setattr(environment.workbench, "create_dispatch_offer", forbid_factory)
    monkeypatch.setattr(environment.workbench, "preload_open_tools", forbid_preload)
    monkeypatch.setattr(environment.workbench, "dispatch_tool_ids", forbid_selection)
    monkeypatch.setattr(environment.servers, "list_sync", forbid_server_read)
    environment.agent_grants.reads = environment.department_grants.reads = 0

    async def step(index: int, request: LLMRequest) -> list[ToolCallRequest] | None:
        assert _offered_names(request) == ["ordinary_probe"]
        if index == 0:
            return [_call("ordinary_probe", "off-control", marker="off-control")]
        assert index == 1
        assert MCP_DISPATCH_OFFER_CONTEXT_KEY not in environment.probe.calls[0][1]
        assert "off-control" in _history(request)
        return None

    llm = _BoundaryLLM(step)
    outcome = await _run_dispatch(environment, llm)

    _assert_script(environment, llm, 2)
    assert outcome.stopped_reason == "complete"
    assert len(loop_options) == 1 and "refresh_tools" not in loop_options[0]
    assert activity == []
    assert environment.agent_grants.reads == environment.department_grants.reads == 0
    assert environment.client is not None and environment.client.list_calls == 0
    assert isinstance(environment.bridge, _SearchBridge)
    assert environment.bridge.client_reads == 0
    assert environment.bridge.invocations == []
    _assert_trace(environment, outcome, 1)


@pytest.mark.asyncio
async def test_real_dispatch_rejects_hostile_offer_context_before_factory(
    dispatch_env: _DispatchEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = dispatch_env
    warm_ids = await _warm_dispatch(environment)
    protected = MCPDispatchOffer(environment.workbench, "agent", preload_limit=0)
    assert protected.admit(warm_ids[-1]) is True
    factories: list[MCPDispatchOffer] = []
    real_factory = environment.workbench.create_dispatch_offer

    async def record_factory(agent_id: str, *, preload_limit: int) -> MCPDispatchOffer:
        offer = await real_factory(agent_id, preload_limit=preload_limit)
        factories.append(offer)
        return offer

    monkeypatch.setattr(environment.workbench, "create_dispatch_offer", record_factory)

    async def step(index: int, request: LLMRequest) -> list[ToolCallRequest] | None:
        assert _offered_names(request) == ["ordinary_probe", "find_mcp_tool"]
        if index == 0:
            return [_call("ordinary_probe", "trusted-control", marker="trusted-control")]
        assert index == 1
        context = environment.probe.calls[0][1]
        assert (context["agent_id"], context["department"], context["rank"]) == (
            "agent", "engineering", "lieutenant",
        )
        assert context[MCP_DISPATCH_OFFER_CONTEXT_KEY] is factories[0]
        assert factories[0] is not protected
        assert factories[0].selected_ids == factories[0].pending_ids == ()
        return None

    llm = _BoundaryLLM(step)
    for hostile in (None, {}, "serialized-offer", protected):
        with pytest.raises(ValueError, match="agentic_context_invalid"):
            await _run_dispatch(environment, llm, extra_context={
                MCP_DISPATCH_OFFER_CONTEXT_KEY: hostile,
            })
        assert llm.requests == []
        assert factories == []
        assert protected.selected_ids == protected.pending_ids == (warm_ids[-1],)
    outcome = await _run_dispatch(environment, llm, extra_context={
        "agent_id": "other", "department": "other", "rank": "ensign",
    })
    _assert_script(environment, llm, 2)
    assert outcome.stopped_reason == "complete"
    assert protected.selected_ids == protected.pending_ids == (warm_ids[-1],)
    _assert_trace(environment, outcome, 1)


@pytest.mark.asyncio
async def test_real_dispatch_invalid_factory_value_has_no_warm_fallback(
    dispatch_env: _DispatchEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = dispatch_env
    await _warm_dispatch(environment)
    wrong_agent = MCPDispatchOffer(environment.workbench, "other", preload_limit=0)

    async def step(index: int, request: LLMRequest) -> list[ToolCallRequest] | None:
        assert _offered_names(request) == ["ordinary_probe"]
        if index == 0:
            return [_call("ordinary_probe", "invalid-factory", marker="invalid-factory")]
        assert index == 1
        assert MCP_DISPATCH_OFFER_CONTEXT_KEY not in environment.probe.calls[-1][1]
        return None

    for invalid in (None, wrong_agent):
        async def invalid_factory(agent_id: str, *, preload_limit: int) -> Any:
            return invalid

        monkeypatch.setattr(environment.workbench, "create_dispatch_offer", invalid_factory)
        llm = _BoundaryLLM(step)
        outcome = await _run_dispatch(environment, llm)
        _assert_script(environment, llm, 2)
        assert outcome.stopped_reason == "complete"
        _assert_trace(environment, outcome, 1)
    assert wrong_agent.selected_ids == wrong_agent.pending_ids == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    "revoked", "expired", "agent-restriction", "department-restriction",
    "disabled", "reaped", "unregistered",
])
async def test_real_echo_offer_rechecks_mid_iteration_changes_before_invoke_and_refresh(
    echo_dispatch_env: _DispatchEnv, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    environment = echo_dispatch_env
    environment.runtime.config.mcp.max_directly_offered_tools = 2
    target = "mcp:offline:echo"
    alias = llm_function_name(target)
    restored = change in {"department-restriction", "reaped", "unregistered"}
    permission_clock = [2_000_000_000.0]
    idle_clock = [100.0]
    monkeypatch.setattr(workbench_module, "time", SimpleNamespace(monotonic=lambda: idle_clock[0]))
    access_grant = environment.access_grant
    if change == "expired":
        monkeypatch.setattr(permissions_module, "time", SimpleNamespace(time=lambda: permission_clock[0]))
        assert await environment.permissions.revoke_grant(access_grant.id) is True
        access_grant = await environment.permissions.issue_grant(
            "agent", "mcp:offline", ToolPermission.WRITE,
            expires_at=permission_clock[0] + 60,
        )
    assert isinstance(environment.bridge, MCPBridge)
    client = environment.bridge.get_client("offline")
    assert client is not None
    real_list = client.list_tools
    real_invoke = environment.bridge.invoke
    enumerations: list[None] = []
    invocations: list[tuple[str, str, dict[str, Any]]] = []
    mutations: list[str] = []
    registrations: list[Any] = []

    async def record_list() -> list[dict[str, Any]]:
        enumerations.append(None)
        return await real_list()

    async def record_invoke(
        server_url: str, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        invocations.append((server_url, tool_name, dict(arguments)))
        return await real_invoke(server_url, tool_name, arguments)

    monkeypatch.setattr(client, "list_tools", record_list)
    monkeypatch.setattr(environment.bridge, "invoke", record_invoke)

    async def mutate(params: dict[str, Any], context: dict[str, Any]) -> None:
        assert params == {"marker": "change-state"}
        offer = context[MCP_DISPATCH_OFFER_CONTEXT_KEY]
        assert type(offer) is MCPDispatchOffer
        assert target in offer.selected_ids and offer.pending_ids == ()
        assert len(invocations) == 1
        if change == "revoked":
            assert await environment.permissions.revoke_grant(access_grant.id) is True
        elif change == "expired":
            assert any(
                grant.id == access_grant.id
                for grant in environment.permissions.get_active_grants_sync("agent")
            )
            permission_clock[0] += 61
            assert all(
                grant.id != access_grant.id
                for grant in environment.permissions.get_active_grants_sync("agent")
            )
        elif change == "agent-restriction":
            await environment.permissions.issue_grant("agent", target, ToolPermission.WRITE)
            await environment.permissions.issue_grant(
                "agent", target, ToolPermission.NONE, is_restriction=True
            )
        elif change == "department-restriction":
            await environment.departments.issue_grant(
                "engineering", target, ToolPermission.NONE, is_restriction=True
            )
        elif change == "disabled":
            record = await environment.servers.set_enabled(environment.server.id, False)
            assert record is not None and record.enabled is False
        elif change == "reaped":
            idle_clock[0] += 10
            assert await environment.workbench.pull_tool(
                "agent", "offline", "badjson", descriptor={"name": "badjson"}
            ) is True
            assert environment.workbench.idle_tool_ids(5) == [target]
            reaper = McpWorkbenchReaper(
                environment.workbench, idle_ttl_seconds=5, interval_seconds=60
            )
            assert await reaper.sweep_once() == 1
            assert environment.registry.get(target) is None
        else:
            assert change == "unregistered"
            assert environment.registry.unregister(target) is True
        mutations.append(change)

    environment.probe.on_invoke = mutate

    async def step(index: int, request: LLMRequest) -> list[ToolCallRequest] | None:
        names = _offered_names(request)
        assert "ordinary_probe" in names and "find_mcp_tool" in names
        if index == 0:
            assert alias in names
            assert len(enumerations) == 1
            registration = environment.registry.get(target)
            assert registration is not None
            registrations.append(registration)
            return [_call(alias, "authorized-control", q="ad1241-authorized-control")]
        if index == 1:
            assert alias in names
            assert "ad1241-authorized-control" in _history(request)
            assert invocations == [("offline", "echo", {"q": "ad1241-authorized-control"})]
            return [
                _call("ordinary_probe", "state-change", marker="change-state"),
                _call(alias, "denied-after-offer", q="must-not-reach-bridge"),
            ]
        if index == 2:
            assert mutations == [change]
            assert alias not in names
            assert target not in environment.probe.calls[0][1][MCP_DISPATCH_OFFER_CONTEXT_KEY].selected_ids
            assert len(invocations) == 1
            assert len(enumerations) == 1
            assert "state-change" in _history(request) and "denied-after-offer" in _history(request)
            completed = [
                payload["is_error"] for event, payload in environment.events
                if event == "AGENTIC_TOOL_CALL_COMPLETED" and payload["tool_id"] == alias
            ]
            assert completed == [False, True]
            if not restored:
                return None
            if change == "department-restriction":
                assert resolve_mcp_access(
                    environment.permissions.get_active_grants_sync("agent"), "offline", "echo",
                    department_grants=environment.departments.get_active_grants_sync("engineering"),
                ) == (False, "department")
                await environment.permissions.issue_grant("agent", target, ToolPermission.WRITE)
                assert resolve_mcp_access(
                    environment.permissions.get_active_grants_sync("agent"), "offline", "echo",
                    department_grants=environment.departments.get_active_grants_sync("engineering"),
                ) == (True, "tool")
            return [_call("find_mcp_tool", "restore-discovery", query="echo")]
        if index == 3:
            assert restored and alias in names
            offer = environment.probe.calls[0][1][MCP_DISPATCH_OFFER_CONTEXT_KEY]
            assert target in offer.selected_ids and offer.pending_ids == ()
            if change in {"reaped", "unregistered"}:
                registration = environment.registry.get(target)
                assert registration is not None and registration.tool is not registrations[0].tool
            return [_call(alias, "restored-control", q="ad1241-restored-control")]
        assert restored and index == 4
        assert invocations[-1] == ("offline", "echo", {"q": "ad1241-restored-control"})
        assert "ad1241-restored-control" in _history(request)
        return None

    llm = _BoundaryLLM(step)
    outcome = await _run_dispatch(environment, llm)

    _assert_script(environment, llm, 5 if restored else 3)
    assert outcome.stopped_reason == "complete"
    assert len(invocations) == (2 if restored else 1)
    _assert_trace(environment, outcome, 5 if restored else 3)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["grant-store", "assembly"])
async def test_real_refresh_failure_keeps_completed_work_and_pending_admission_until_retry(
    dispatch_env: _DispatchEnv, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    environment = dispatch_env
    await _warm_dispatch(environment)
    target = _tool_id(0)
    alias = llm_function_name(target)
    offers: list[MCPDispatchOffer] = []
    selections: list[tuple[str, ...]] = []
    assembly_failures: list[str] = []
    fail_assembly = False
    real_select = environment.workbench.dispatch_tool_ids
    real_definition = tool_call_module.tool_registration_to_llm_definition

    def record_selection(
        agent_id: str, *, candidate_ids: Sequence[str] | None = None
    ) -> list[str]:
        assert candidate_ids is not None
        selections.append(tuple(candidate_ids))
        return real_select(agent_id, candidate_ids=candidate_ids)

    def assemble(registration: Any) -> dict[str, Any]:
        nonlocal fail_assembly
        if fail_assembly and registration.tool.tool_id == target:
            assert offers[0].pending_ids == (target,)
            fail_assembly = False
            assembly_failures.append(target)
            raise RuntimeError("injected MCP definition assembly failure")
        return real_definition(registration)

    monkeypatch.setattr(environment.workbench, "dispatch_tool_ids", record_selection)
    monkeypatch.setattr(tool_call_module, "tool_registration_to_llm_definition", assemble)

    async def probe(params: dict[str, Any], context: dict[str, Any]) -> None:
        nonlocal fail_assembly
        offer = context[MCP_DISPATCH_OFFER_CONTEXT_KEY]
        assert type(offer) is MCPDispatchOffer
        assert offer.selected_ids == offer.pending_ids == (target,)
        if params["marker"] == "pending-complete":
            assert offers == []
            offers.append(offer)
            if failure == "grant-store":
                environment.agent_grants.fail_next_read = True
            else:
                fail_assembly = True
        else:
            assert params["marker"] == "retry-complete"
            assert offers == [offer]

    environment.probe.on_invoke = probe

    async def step(index: int, request: LLMRequest) -> list[ToolCallRequest] | None:
        if index == 0:
            assert _offered_names(request) == ["ordinary_probe", "find_mcp_tool"]
            return [
                _call("find_mcp_tool", "pending-discovery", query="000"),
                _call("ordinary_probe", "pending-work", marker="pending-complete"),
            ]
        if index == 1:
            assert len(offers) == 1
            assert selections == [(), (target,)]
            assert offers[0].selected_ids == offers[0].pending_ids == (target,)
            assert environment.agent_grants.failures == int(failure == "grant-store")
            assert assembly_failures == ([target] if failure == "assembly" else [])
            assert request.tools is llm.requests[0].tools
            assert _offered_names(request) == ["ordinary_probe", "find_mcp_tool"]
            assert "pending-discovery" in _history(request)
            assert "pending-complete" in _history(request)
            return [_call("ordinary_probe", "retry-work", marker="retry-complete")]
        assert offers[0].selected_ids == (target,)
        assert offers[0].pending_ids == ()
        assert _offered_names(request) == ["ordinary_probe", "find_mcp_tool", alias]
        if index == 2:
            assert "retry-complete" in _history(request)
            return [_call(alias, "published-call", value="published-control")]
        assert index == 3
        assert "published-control" in _history(request)
        return None

    llm = _BoundaryLLM(step)
    outcome = await _run_dispatch(environment, llm)

    _assert_script(environment, llm, 4)
    assert outcome.stopped_reason == "complete"
    assert selections == [(), (target,), (target,), (target,)]
    assert environment.workbench.pulled_count == 100
    assert isinstance(environment.bridge, _SearchBridge)
    assert environment.bridge.invocations == [("offline", "tool_000", {"value": "published-control"})]
    _assert_trace(environment, outcome, 4)


@pytest.mark.asyncio
async def test_real_unchanged_publication_unpins_rediscovered_existing_member(
    dispatch_env: _DispatchEnv,
) -> None:
    environment = dispatch_env
    await _warm_dispatch(environment)
    environment.runtime.config.mcp.max_directly_offered_tools = 1
    target = _tool_id(0)
    observed: list[MCPDispatchOffer] = []

    async def probe(params: dict[str, Any], context: dict[str, Any]) -> None:
        offer = context[MCP_DISPATCH_OFFER_CONTEXT_KEY]
        assert offer.selected_ids == offer.pending_ids == (target,)
        observed.append(offer)

    environment.probe.on_invoke = probe

    async def step(index: int, request: LLMRequest) -> list[ToolCallRequest] | None:
        assert _offered_names(request) == [
            "ordinary_probe", "find_mcp_tool", llm_function_name(target),
        ]
        if index == 0:
            return [
                _call("find_mcp_tool", "rediscover-existing", query="000"),
                _call("ordinary_probe", "observe-pin", marker="existing-pinned"),
            ]
        assert index == 1 and len(observed) == 1
        assert "existing-pinned" in _history(request)
        assert request.tools is llm.requests[0].tools
        assert observed[0].selected_ids == (target,)
        assert observed[0].pending_ids == ()
        return None

    llm = _BoundaryLLM(step)
    outcome = await _run_dispatch(environment, llm)
    _assert_script(environment, llm, 2)
    assert outcome.stopped_reason == "complete"
    _assert_trace(environment, outcome, 2)


@pytest.mark.asyncio
@pytest.mark.parametrize("publication", ["initial", "rebuilt"])
async def test_real_publication_tracks_surviving_objects_and_releases_alias_collision(
    dispatch_env: _DispatchEnv, monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture, publication: str,
) -> None:
    environment = dispatch_env
    caplog.set_level("DEBUG", logger=workbench_module.__name__)
    target = _tool_id(23)
    collision_alias = llm_function_name(target)
    assert collision_alias != target and not collision_alias.startswith("mcp:")
    collision_tool = _DispatchProbe()
    collision_tool.tool_id = collision_alias
    collision_tool.name = "Literal Alias Probe"
    collision_tool.description = "Return a marker from the ordinary literal-alias tool."
    environment.registry.register(collision_tool)
    await environment.permissions.issue_grant("agent", collision_alias, ToolPermission.READ)
    warm_ids = await _warm_dispatch(environment, count=24)
    canonical_registration = environment.registry.get(target)
    collision_registration = environment.registry.get(collision_alias)
    assert canonical_registration is not None and canonical_registration.enabled
    assert collision_registration is not None and collision_registration.enabled
    assert canonical_registration.tool.tool_id == target
    assert canonical_registration.tool.tool_type is ToolType.MCP_SERVER
    assert collision_registration.tool is collision_tool
    assert collision_tool.tool_type is ToolType.UTILITY_AGENT
    assert llm_function_name(collision_tool.tool_id) == collision_alias
    assert environment.registry.count() == 27
    registrations = {
        tool_id: environment.registry.get(tool_id)
        for tool_id in [*warm_ids, "ordinary_probe", collision_alias, "find_mcp_tool"]
    }
    ordinary_ids = [
        grant.tool_id for grant in environment.permissions.get_active_grants_sync("agent")
        if grant.tool_id in {"ordinary_probe", collision_alias}
    ]
    assert len(ordinary_ids) == 2 and set(ordinary_ids) == {"ordinary_probe", collision_alias}
    base_names = [*ordinary_ids, "find_mcp_tool"]
    initial_publication = publication == "initial"
    environment.runtime.config.mcp.max_directly_offered_tools = 24 if initial_publication else 0
    publication_index = 0 if initial_publication else 1
    survivors = tuple(warm_ids[:-1])
    later_ids = (*survivors, _tool_id(24))
    real_definition = tool_call_module.tool_registration_to_llm_definition
    collision_definition = real_definition(collision_registration)
    conversions: list[str] = []
    offers: list[MCPDispatchOffer] = []
    publications: list[tuple[str, ...]] = []
    real_acknowledge = MCPDispatchOffer.acknowledge_published
    search_registration = environment.registry.get("find_mcp_tool")
    assert search_registration is not None
    real_search = search_registration.tool.invoke
    search_results: list[ToolResult] = []

    def record_definition(registration: Any) -> dict[str, Any]:
        conversions.append(registration.tool.tool_id)
        return real_definition(registration)

    def record_publication(offer: MCPDispatchOffer, published_ids: Sequence[str]) -> None:
        real_acknowledge(offer, published_ids)
        offers.append(offer)
        publications.append(tuple(published_ids))

    async def record_search(
        params: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> ToolResult:
        result = await real_search(params, context)
        search_results.append(result)
        return result

    monkeypatch.setattr(tool_call_module, "tool_registration_to_llm_definition", record_definition)
    monkeypatch.setattr(MCPDispatchOffer, "acknowledge_published", record_publication)
    monkeypatch.setattr(search_registration.tool, "invoke", record_search)

    async def probe(params: dict[str, Any], context: dict[str, Any]) -> None:
        offer = context[MCP_DISPATCH_OFFER_CONTEXT_KEY]
        assert type(offer) is MCPDispatchOffer and offer is offers[0]
        assert offer.belongs_to(environment.workbench, "agent")
        assert offer.capacity == 24
        marker = params["marker"]
        if marker == "ordinary-control":
            assert offer.selected_ids == (survivors if initial_publication else ())
            assert offer.pending_ids == ()
        elif marker == "rebuild-pinned":
            assert offer.selected_ids == offer.pending_ids == tuple(warm_ids)
        elif marker == "collision-pinned":
            assert offer.selected_ids == tuple(warm_ids)
            assert offer.pending_ids == (target,)
        elif marker in {"normalize-input", "stable-input"}:
            assert offer.selected_ids == survivors and offer.pending_ids == ()
        else:
            assert marker == "capacity-pinned"
            assert offer.selected_ids == offer.pending_ids == later_ids
            assert len(offer.selected_ids) == offer.capacity

    environment.probe.on_invoke = probe

    async def step(index: int, request: LLMRequest) -> list[ToolCallRequest] | None:
        assert offers and len(publications) == index + 1
        offer = offers[0]
        assert all(observed is offer for observed in offers)
        expected = (
            () if not initial_publication and index == 0
            else later_ids if index >= publication_index + 4 else survivors
        )
        assert _offered_names(request) == [
            *base_names, *(llm_function_name(tool_id) for tool_id in expected),
        ]
        assert [
            definition for definition in request.tools or []
            if definition["function"]["name"] == collision_alias
        ] == [collision_definition]
        assert all(tool_id not in json.dumps(request.tools) for tool_id in warm_ids)
        assert offer.selected_ids == expected and offer.pending_ids == ()
        assert all(target not in published for published in publications)
        assert collision_tool.calls == []
        if not initial_publication and index == 0:
            assert publications == [()]
            assert conversions.count("ordinary_probe") == 1
            return [
                _call("ordinary_probe", "ordinary-control", marker="ordinary-control"),
                *[
                    _call("find_mcp_tool", f"fill-{start}", query=_query(start, 8))
                    for start in (0, 8, 16)
                ],
                _call("ordinary_probe", "rebuild-pinned", marker="rebuild-pinned"),
            ]
        if index == publication_index:
            assert publications[-1] == survivors
            assert conversions.count("ordinary_probe") == publication_index + 1
            assert conversions.count(target) == 1
            control = [
                _call("ordinary_probe", "ordinary-control", marker="ordinary-control")
            ] if initial_publication else []
            return [
                *control,
                _call("find_mcp_tool", "rediscover-collision", query="023"),
                _call("ordinary_probe", "collision-pinned", marker="collision-pinned"),
            ]
        assert environment.probe.calls[0][0] == {"marker": "ordinary-control"}
        assert "ordinary-control" in _history(request)
        if index == publication_index + 1:
            assert request.tools is llm.requests[publication_index].tools
            assert conversions.count("ordinary_probe") == publication_index + 1
            assert _matched_ids(search_results[-1]) == [target]
            _assert_counts(search_results[-1])
            assert len(offer.selected_ids) == offer.capacity - 1
            return [_call("ordinary_probe", "normalize-input", marker="normalize-input")]
        if index == publication_index + 2:
            # AgenticLoop retains equal offers; conversion counts prove reassembly.
            assert request.tools is llm.requests[index - 1].tools
            assert request.tools == llm.requests[index - 1].tools
            assert conversions.count("ordinary_probe") == publication_index + 2
            return [_call("ordinary_probe", "stable-input", marker="stable-input")]
        if index == publication_index + 3:
            assert request.tools is llm.requests[index - 1].tools
            assert conversions.count("ordinary_probe") == publication_index + 2
            return [
                *[
                    _call("find_mcp_tool", f"pin-{start}", query=_query(start, count))
                    for start, count in ((0, 8), (8, 8), (16, 7))
                ],
                _call("find_mcp_tool", "later-discovery", query="024"),
                _call("ordinary_probe", "capacity-pinned", marker="capacity-pinned"),
                _call(collision_alias, "ambiguous-call", marker="must-not-run"),
            ]
        assert isinstance(environment.bridge, _SearchBridge)
        if index == publication_index + 4:
            assert publications[-1] == later_ids
            assert _matched_ids(search_results[-1]) == [_tool_id(24)]
            assert "ambiguous" in _history(request).lower()
            assert environment.bridge.invocations == []
            assert [
                payload["is_error"] for event, payload in environment.events
                if event == "AGENTIC_TOOL_CALL_COMPLETED" and payload["tool_id"] == collision_alias
            ] == [True]
            return [_call(llm_function_name(_tool_id(24)), "later-call", value="later-control")]
        assert index == publication_index + 5
        assert request.tools is llm.requests[index - 1].tools
        assert conversions.count("ordinary_probe") == publication_index + 3
        assert "later-control" in _history(request)
        assert environment.bridge.invocations == [("offline", "tool_024", {"value": "later-control"})]
        return None

    llm = _BoundaryLLM(step)
    outcome = await _run_dispatch(environment, llm)

    _assert_script(environment, llm, publication_index + 6)
    assert outcome.stopped_reason == "complete"
    assert publications[0] == (survivors if initial_publication else ())
    assert all(target not in published and len(published) <= 24 for published in publications)
    assert offers[0].selected_ids == later_ids and offers[0].pending_ids == ()
    assert collision_tool.calls == []
    assert all(environment.registry.get(tool_id) is registration for tool_id, registration in registrations.items())
    assert environment.workbench.pulled_count == 25
    assert environment.registry.count() == 28
    assert len(search_results) == (5 if initial_publication else 8)
    for search_result in search_results:
        _assert_counts(search_result)
    assert all(
        payload["is_error"] is False for event, payload in environment.events
        if event == "AGENTIC_TOOL_CALL_COMPLETED" and payload["tool_id"] == "ordinary_probe"
    )
    messages = [
        record.getMessage() for record in caplog.records
        if record.name == workbench_module.__name__ and "locally published" in record.getMessage()
    ]
    assert any("withdrew 1 filtered members (1 pending pins)" in message for message in messages)
    if initial_publication:
        assert any("withdrew 1 filtered members (0 pending pins)" in message for message in messages)
    _assert_trace(environment, outcome, 12 if initial_publication else 16)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["revoked", "disabled"])
@pytest.mark.parametrize("failure", ["none", "grant-store", "assembly"])
async def test_real_discovery_withdrawal_releases_pins_only_after_successful_assembly(
    dispatch_env: _DispatchEnv, monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture, change: str, failure: str,
) -> None:
    environment = dispatch_env
    caplog.set_level("DEBUG", logger=workbench_module.__name__)
    assert isinstance(environment.bridge, _SearchBridge)
    target = _tool_id(0)
    alias = llm_function_name(target)
    offers: list[MCPDispatchOffer] = []
    mutations: list[str] = []
    assembly_failures: list[str] = []
    fail_assembly = False
    real_definition = tool_call_module.tool_registration_to_llm_definition

    def assemble(registration: Any) -> dict[str, Any]:
        nonlocal fail_assembly
        if fail_assembly and registration.tool.tool_id == "ordinary_probe":
            fail_assembly = False
            assembly_failures.append("withdrawal")
            raise RuntimeError("injected withdrawal assembly failure")
        return real_definition(registration)

    monkeypatch.setattr(tool_call_module, "tool_registration_to_llm_definition", assemble)

    async def probe(params: dict[str, Any], context: dict[str, Any]) -> None:
        nonlocal fail_assembly
        offer = context[MCP_DISPATCH_OFFER_CONTEXT_KEY]
        assert type(offer) is MCPDispatchOffer
        marker = params["marker"]
        if marker == "discovery-control":
            assert offer.selected_ids == offer.pending_ids == (target,)
            assert offers == []
            offers.append(offer)
        elif marker == "withdraw-before-publication":
            assert offers == [offer]
            assert offer.selected_ids == offer.pending_ids == (target,)
            assert environment.bridge.invocations == [
                ("offline", "tool_000", {"value": "authorized-control"}),
            ]
            if change == "revoked":
                assert await environment.permissions.revoke_grant(environment.access_grant.id) is True
                assert resolve_mcp_access(
                    environment.permissions.get_active_grants_sync("agent"), "offline", "tool_000"
                )[0] is False
            else:
                disabled = await environment.servers.set_enabled(environment.server.id, False)
                assert disabled is not None and disabled.enabled is False
            mutations.append(change)
            assert offer.selected_ids == offer.pending_ids == (target,)
            if failure == "grant-store":
                environment.agent_grants.fail_next_read = True
            elif failure == "assembly":
                fail_assembly = True
        else:
            assert marker == "after-denied-call" and offers == [offer]
            expected = () if failure == "none" else (target,)
            assert offer.selected_ids == offer.pending_ids == expected

    environment.probe.on_invoke = probe

    async def step(index: int, request: LLMRequest) -> list[ToolCallRequest] | None:
        names = _offered_names(request)
        assert names[:2] == ["ordinary_probe", "find_mcp_tool"]
        finder = next(
            definition["function"] for definition in request.tools or []
            if definition["function"]["name"] == "find_mcp_tool"
        )
        assert "next-offer consideration" in finder["description"]
        if index == 0:
            assert alias not in names
            return [
                _call("find_mcp_tool", "discovery-control", query="000"),
                _call("ordinary_probe", "observe-admission", marker="discovery-control"),
            ]
        assert len(offers) == 1
        offer = offers[0]
        if index == 1:
            assert alias in names
            assert offer.selected_ids == (target,) and offer.pending_ids == ()
            assert "tool_000" in _history(request)
            return [_call(alias, "authorized-call", value="authorized-control")]
        if index == 2:
            assert request.tools is llm.requests[1].tools
            assert "authorized-control" in _history(request)
            assert environment.bridge.invocations == [
                ("offline", "tool_000", {"value": "authorized-control"}),
            ]
            return [
                _call("find_mcp_tool", "rediscovery-before-withdrawal", query="000"),
                _call("ordinary_probe", "withdrawal", marker="withdraw-before-publication"),
            ]
        assert mutations == [change]
        assert environment.registry.get(target) is not None
        assert environment.agent_grants.failures == int(failure == "grant-store")
        assert assembly_failures == (["withdrawal"] if failure == "assembly" else [])
        if index == 3:
            assert "rediscovery-before-withdrawal" in _history(request)
            if failure == "none":
                assert alias not in names
                assert offer.selected_ids == offer.pending_ids == ()
            else:
                assert request.tools is llm.requests[2].tools
                assert alias in names
                assert offer.selected_ids == offer.pending_ids == (target,)
            return [
                _call(alias, "denied-after-withdrawal", value="must-not-run"),
                _call("ordinary_probe", "retry-withdrawal", marker="after-denied-call"),
            ]
        assert index == 4
        assert alias not in names
        assert offer.selected_ids == offer.pending_ids == ()
        assert "after-denied-call" in _history(request)
        assert environment.bridge.invocations == [
            ("offline", "tool_000", {"value": "authorized-control"}),
        ]
        assert [
            payload["is_error"] for event, payload in environment.events
            if event == "AGENTIC_TOOL_CALL_COMPLETED" and payload["tool_id"] == alias
        ] == [False, True]
        return None

    llm = _BoundaryLLM(step)
    outcome = await _run_dispatch(environment, llm)

    _assert_script(environment, llm, 5)
    assert outcome.stopped_reason == "complete"
    assert offers[0].selected_ids == offers[0].pending_ids == ()
    assert environment.workbench.pulled_count == 1
    assert [
        payload["is_error"] for event, payload in environment.events
        if event == "AGENTIC_TOOL_CALL_COMPLETED" and payload["tool_id"] == "find_mcp_tool"
    ] == [False, False]
    messages = [
        record.getMessage() for record in caplog.records
        if record.name == workbench_module.__name__ and "locally published" in record.getMessage()
    ]
    assert any(
        "locally published 0 MCP definitions; released 0 published pins and "
        "withdrew 1 filtered members (1 pending pins)" in message
        for message in messages
    )
    assert all("must-not-run" not in message for message in messages)
    _assert_trace(environment, outcome, 7)


@pytest.mark.asyncio
@pytest.mark.parametrize("exit_kind", ["complete", "error", "cancelled"])
async def test_real_dispatch_lifecycle_does_not_carry_selection_or_pins_to_later_runs(
    dispatch_env: _DispatchEnv, exit_kind: str
) -> None:
    environment = dispatch_env
    previous: list[MCPDispatchOffer] = []

    async def first_probe(params: dict[str, Any], context: dict[str, Any]) -> None:
        offer = context[MCP_DISPATCH_OFFER_CONTEXT_KEY]
        assert offer.selected_ids == offer.pending_ids == (_tool_id(0),)
        previous.append(offer)
        if exit_kind != "complete":
            environment.agent_grants.fail_next_read = True

    environment.probe.on_invoke = first_probe

    async def first_step(index: int, request: LLMRequest) -> list[ToolCallRequest] | None:
        if index == 0:
            assert _offered_names(request) == ["ordinary_probe", "find_mcp_tool"]
            return [
                _call("find_mcp_tool", "first-discovery", query="000"),
                _call("ordinary_probe", "first-work", marker="first-complete"),
            ]
        assert index == 1 and len(previous) == 1
        assert "first-complete" in _history(request)
        if exit_kind == "complete":
            assert previous[0].pending_ids == ()
            return None
        assert previous[0].pending_ids == (_tool_id(0),)
        assert environment.agent_grants.failures == 1
        assert llm_function_name(_tool_id(0)) not in _offered_names(request)
        if exit_kind == "cancelled":
            raise asyncio.CancelledError
        raise RuntimeError("intentional scripted run failure after completed work")

    llm = _BoundaryLLM(first_step)
    executor = WorkItemAgenticExecutor(llm_client=llm)
    if exit_kind == "cancelled":
        with pytest.raises(asyncio.CancelledError):
            await _run_dispatch(environment, llm, executor=executor)
        assert environment.traces.blobs == {}
    else:
        outcome = await _run_dispatch(environment, llm, executor=executor)
        assert outcome.stopped_reason == exit_kind
        _assert_trace(environment, outcome, 2)
    _assert_script(environment, llm, 2)
    previous_state = (previous[0].selected_ids, previous[0].pending_ids)
    fresh: list[MCPDispatchOffer] = []

    for agent_id in ("agent", "other"):
        if agent_id == "other":
            await environment.permissions.issue_grant(agent_id, "mcp:offline", ToolPermission.WRITE)
            await environment.permissions.issue_grant(agent_id, "ordinary_probe", ToolPermission.READ)
        assert resolve_mcp_access(
            environment.permissions.get_active_grants_sync(agent_id), "offline", "tool_001"
        )[0] is True

        async def next_probe(params: dict[str, Any], context: dict[str, Any]) -> None:
            offer = context[MCP_DISPATCH_OFFER_CONTEXT_KEY]
            assert offer.belongs_to(environment.workbench, agent_id)
            assert offer is not previous[0]
            assert all(offer is not earlier for earlier in fresh)
            assert offer.selected_ids == offer.pending_ids == ()
            fresh.append(offer)

        environment.probe.on_invoke = next_probe

        async def next_step(index: int, request: LLMRequest) -> list[ToolCallRequest] | None:
            if index == 0:
                assert _offered_names(request) == ["ordinary_probe", "find_mcp_tool"]
                return [
                    _call("ordinary_probe", "fresh-work", marker="fresh-complete"),
                    _call("find_mcp_tool", "fresh-discovery", query="001"),
                ]
            assert _offered_names(request) == [
                "ordinary_probe", "find_mcp_tool", llm_function_name(_tool_id(1)),
            ]
            assert fresh[-1].selected_ids == (_tool_id(1),)
            assert fresh[-1].pending_ids == ()
            assert (previous[0].selected_ids, previous[0].pending_ids) == previous_state
            if index == 1:
                return [_call(llm_function_name(_tool_id(1)), "fresh-call", value=agent_id)]
            assert index == 2 and agent_id in _history(request)
            return None

        llm.step = next_step
        llm.requests = []
        outcome = await _run_dispatch(environment, llm, agent_id=agent_id, executor=executor)
        _assert_script(environment, llm, 3)
        assert outcome.stopped_reason == "complete"
        _assert_trace(environment, outcome, 3)
    assert len(fresh) == 2
    assert isinstance(environment.bridge, _SearchBridge)
    assert environment.bridge.invocations == [
        ("offline", "tool_001", {"value": "agent"}),
        ("offline", "tool_001", {"value": "other"}),
    ]


@pytest.mark.asyncio
async def test_real_concurrent_same_agent_runs_keep_pending_offers_independent(
    dispatch_env: _DispatchEnv,
) -> None:
    environment = dispatch_env
    first_pending = asyncio.Event()
    release = asyncio.Event()
    offers: dict[str, MCPDispatchOffer] = {}
    requests: dict[str, list[LLMRequest]] = {"run-alpha": [], "run-beta": []}
    targets = {"run-alpha": _tool_id(0), "run-beta": _tool_id(1)}

    async def probe(params: dict[str, Any], context: dict[str, Any]) -> None:
        label = params["marker"]
        offer = context[MCP_DISPATCH_OFFER_CONTEXT_KEY]
        assert offer.belongs_to(environment.workbench, "agent")
        assert offer.selected_ids == offer.pending_ids == (targets[label],)
        offers[label] = offer
        if label == "run-alpha":
            first_pending.set()
        else:
            assert set(offers) == set(targets)
            assert offers["run-alpha"] is not offers["run-beta"]
            assert offers["run-alpha"].pending_ids == (targets["run-alpha"],)
            release.set()
        await release.wait()

    environment.probe.on_invoke = probe

    async def step(index: int, request: LLMRequest) -> list[ToolCallRequest] | None:
        assert request.messages is not None
        label = request.messages[0]["content"]
        local_index = len(requests[label])
        requests[label].append(request)
        alias = llm_function_name(targets[label])
        if local_index == 0:
            assert _offered_names(request) == ["ordinary_probe", "find_mcp_tool"]
            return [
                _call("find_mcp_tool", f"{label}-find", query="000" if label == "run-alpha" else "001"),
                _call("ordinary_probe", f"{label}-pin", marker=label),
            ]
        assert _offered_names(request) == ["ordinary_probe", "find_mcp_tool", alias]
        assert offers[label].selected_ids == (targets[label],)
        assert offers[label].pending_ids == ()
        if local_index == 1:
            return [_call(alias, f"{label}-call", value=label)]
        assert local_index == 2
        return None

    llm = _BoundaryLLM(step)
    executor = WorkItemAgenticExecutor(llm_client=llm)
    tasks = [asyncio.create_task(_run_dispatch(
        environment, llm, task_text="run-alpha", executor=executor
    ))]
    try:
        await asyncio.wait_for(first_pending.wait(), timeout=5)
        assert not tasks[0].done()
        tasks.append(asyncio.create_task(_run_dispatch(
            environment, llm, task_text="run-beta", executor=executor
        )))
        outcomes = await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)
    finally:
        release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    _assert_script(environment, llm, 6)
    assert all(len(run_requests) == 3 for run_requests in requests.values())
    for outcome in outcomes:
        assert outcome.stopped_reason == "complete"
        _assert_trace(environment, outcome, 3)
    assert isinstance(environment.bridge, _SearchBridge)
    assert sorted(environment.bridge.invocations) == [
        ("offline", "tool_000", {"value": "run-alpha"}),
        ("offline", "tool_001", {"value": "run-beta"}),
    ]


@pytest.mark.asyncio
async def test_offer_sequence_boundaries_reject_malformed_values_without_mutation(
    offer_env: _OfferEnv,
) -> None:
    offer = await offer_env.workbench.create_dispatch_offer("agent", preload_limit=1)
    assert offer.admit(_tool_id(0)) is True
    before = (offer.selected_ids, offer.pending_ids)
    malformed_sequences: list[Any] = [None, _tool_id(0), b"mcp:offline:tool_000", 1, {_tool_id(0): None}]
    for malformed in malformed_sequences:
        with pytest.raises(TypeError, match="sequence"):
            MCPDispatchOffer(
                offer_env.workbench, "agent", preload_limit=1, preloaded_ids=malformed
            )
        with pytest.raises(TypeError, match="sequence"):
            offer.acknowledge_published(malformed)
        assert (offer.selected_ids, offer.pending_ids) == before
    for malformed_member in (None, {}, [], False, 1):
        assert offer.admit(malformed_member) is False
        with pytest.raises(ValueError, match="current offer"):
            offer.acknowledge_published([_tool_id(0), malformed_member])
        assert (offer.selected_ids, offer.pending_ids) == before
    empty = MCPDispatchOffer(offer_env.workbench, "agent", preload_limit=0, preloaded_ids=[])
    empty.acknowledge_published(["find_mcp_tool"])
    assert empty.selected_ids == empty.pending_ids == ()
    assert empty.belongs_to(None, "agent") is False
    assert empty.belongs_to(offer_env.workbench, None) is False
    assert empty.belongs_to(offer_env.workbench, "") is False


@pytest.mark.asyncio
async def test_bounded_selector_rejects_non_sequences_and_ignores_malformed_members(
    offer_env: _OfferEnv,
) -> None:
    assert await offer_env.workbench.preload_open_tools("agent", limit=1) == [_tool_id(0)]
    before_reads = offer_env.servers.reads
    before_enumerations = offer_env.client.list_calls
    for malformed in (_tool_id(0), b"mcp:offline:tool_000", 1, {_tool_id(0): None}):
        with pytest.raises(TypeError, match="sequence"):
            offer_env.workbench.dispatch_tool_ids("agent", candidate_ids=malformed)
        assert offer_env.servers.reads == before_reads
    assert offer_env.workbench.dispatch_tool_ids("agent", candidate_ids=[
        None, {}, [], False, _tool_id(0), _tool_id(0), "", "mcp:offline:missing",
    ]) == ["find_mcp_tool", _tool_id(0)]
    assert offer_env.servers.reads == before_reads + 1
    assert offer_env.client.list_calls == before_enumerations
    assert offer_env.bridge.invocations == []


async def _correction_projection(environment: _DispatchEnv) -> _SessionCorrectionRuntime:
    assert environment.workbench.register_search_tool() == "find_mcp_tool"
    await environment.permissions.issue_grant("agent", "find_mcp_tool", ToolPermission.READ)
    return _session_correction_runtime(
        environment.runtime, agent_id="agent", department="engineering", rank="lieutenant"
    )


async def _run_correction(
    runtime: _SessionCorrectionRuntime, llm: _BoundaryLLM
) -> WorkItemAgenticOutcome:
    return await WorkItemAgenticExecutor(llm_client=llm).run(
        agent_id="agent", instructions="Use the offered tools.",
        task_text="Complete the governed correction task.", runtime=runtime,
        department="engineering", rank="lieutenant", max_iterations=8, tier="fast",
    )


@pytest.mark.asyncio
async def test_initial_selection_failure_never_rearms_after_completed_ordinary_work(
    dispatch_env: _DispatchEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = dispatch_env
    real_select = environment.workbench.dispatch_tool_ids
    real_factory = environment.workbench.create_dispatch_offer
    real_loop = loop_module.AgenticLoop
    assert real_select("agent", candidate_ids=()) == ["find_mcp_tool"]
    selections: list[tuple[str, ...]] = []
    offers: list[MCPDispatchOffer] = []
    loop_options: list[set[str]] = []

    async def record_factory(agent_id: str, *, preload_limit: int) -> MCPDispatchOffer:
        offer = await real_factory(agent_id, preload_limit=preload_limit)
        offers.append(offer)
        return offer

    def fail_first_selection(
        agent_id: str, *, candidate_ids: Sequence[str] | None = None
    ) -> list[str]:
        assert candidate_ids is not None
        selections.append(tuple(candidate_ids))
        if len(selections) == 1:
            raise RuntimeError("injected initial selection failure")
        return real_select(agent_id, candidate_ids=candidate_ids)

    def observe_loop(**kwargs: Any) -> Any:
        loop_options.append(set(kwargs))
        return real_loop(**kwargs)

    monkeypatch.setattr(environment.workbench, "create_dispatch_offer", record_factory)
    monkeypatch.setattr(environment.workbench, "dispatch_tool_ids", fail_first_selection)
    monkeypatch.setattr(loop_module, "AgenticLoop", observe_loop)

    async def step(index: int, request: LLMRequest) -> list[ToolCallRequest] | None:
        assert _offered_names(request) == ["ordinary_probe"]
        assert selections == [()]
        assert len(offers) == 1
        if index == 0:
            return [_call("ordinary_probe", "initial-failure-work", marker="work-survived")]
        assert index == 1
        assert "work-survived" in _history(request)
        assert len(environment.probe.calls) == 1
        assert MCP_DISPATCH_OFFER_CONTEXT_KEY not in environment.probe.calls[0][1]
        assert request.tools is llm.requests[0].tools
        return None

    llm = _BoundaryLLM(step)
    outcome = await _run_dispatch(environment, llm)

    _assert_script(environment, llm, 2)
    assert outcome.stopped_reason == "complete"
    assert outcome.final_text == "boundary complete"
    assert selections == [()]
    assert len(loop_options) == 1 and "refresh_tools" not in loop_options[0]
    assert offers[0].selected_ids == offers[0].pending_ids == ()
    _assert_trace(environment, outcome, 1)
    assert fail_first_selection("agent", candidate_ids=()) == ["find_mcp_tool"]
    assert selections == [(), ()]
    assert len(llm.requests) == 2


@pytest.mark.asyncio
async def test_dispatch_sources_require_concrete_original_owner_and_exact_projection_agent(
    dispatch_env: _DispatchEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = dispatch_env
    projection = await _correction_projection(environment)
    facade = projection.mcp_workbench
    assert facade is not None
    source: MCPDispatchSource = environment.workbench
    owned, fresh = await asyncio.gather(
        facade.create_dispatch_offer("agent", preload_limit=0),
        facade.create_dispatch_offer("agent", preload_limit=0),
    )
    assert owned is not fresh
    assert owned.belongs_to(environment.workbench, "agent") is True
    assert owned.belongs_to(facade, "agent") is False

    class _DerivedOffer(MCPDispatchOffer):
        pass

    class _AgentString(str):
        pass

    foreign = _make_offer_env()
    wrong_owner = await foreign.workbench.create_dispatch_offer("agent", preload_limit=0)
    wrong_agent = await source.create_dispatch_offer("other", preload_limit=0)
    derived = _DerivedOffer(environment.workbench, "agent", preload_limit=0)
    invalid_offers: list[Any] = [None, {}, "offer", wrong_owner, wrong_agent, derived]
    for provider in (source, facade):
        assert provider.accepts_dispatch_offer(owned, "agent") is True
        for invalid in invalid_offers:
            assert provider.accepts_dispatch_offer(invalid, "agent") is False
        for agent_id in (None, "", "other", 1, _AgentString("agent")):
            assert provider.accepts_dispatch_offer(owned, agent_id) is False
    for agent_id in (None, "", "other", _AgentString("agent")):
        with pytest.raises(ValueError, match="mcp_agent_invalid"):
            await facade.create_dispatch_offer(agent_id, preload_limit=0)
    for limit in (None, True, "24"):
        with pytest.raises(TypeError, match="integer"):
            await facade.create_dispatch_offer("agent", preload_limit=limit)
    assert facade.dispatch_tool_ids("other", candidate_ids=[]) == []
    for missing in (replace(facade, source=None), replace(facade, synchronize=None)):
        with pytest.raises(ValueError, match="mcp_unavailable"):
            await missing.create_dispatch_offer("agent", preload_limit=0)
        assert missing.dispatch_tool_ids("agent", candidate_ids=[]) == []
    assert replace(facade, source=None).accepts_dispatch_offer(owned, "agent") is False

    for invalid in invalid_offers:
        async def invalid_factory(agent_id: str, *, preload_limit: int) -> Any:
            return invalid

        monkeypatch.setattr(environment.workbench, "create_dispatch_offer", invalid_factory)
        with pytest.raises(ValueError, match="mcp_offer_invalid"):
            await facade.create_dispatch_offer("agent", preload_limit=0)

    async def cancel_factory(agent_id: str, *, preload_limit: int) -> MCPDispatchOffer:
        raise asyncio.CancelledError

    monkeypatch.setattr(environment.workbench, "create_dispatch_offer", cancel_factory)
    with pytest.raises(asyncio.CancelledError):
        await facade.create_dispatch_offer("agent", preload_limit=0)
    assert owned.selected_ids == fresh.selected_ids == wrong_owner.selected_ids == ()
    assert environment.client is not None and environment.client.list_calls == 0
    assert environment.events == []


@pytest.mark.asyncio
async def test_correction_projection_discovers_detached_echo_and_invokes_original_adapter(
    echo_dispatch_env: _DispatchEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = echo_dispatch_env
    environment.runtime.config.mcp.max_directly_offered_tools = 24
    target = "mcp:offline:echo"
    alias = llm_function_name(target)
    arguments = {"q": "projected-echo-roundtrip"}
    projection = await _correction_projection(environment)
    facade = projection.mcp_workbench
    assert facade is not None
    assert projection.config.mcp.agent_tools_enabled is True
    assert getattr(projection.config.mcp, "max_directly_offered_tools", 0) == 0
    assert environment.registry.get(target) is None
    assert projection.tool_registry.get(target) is None
    assert projection.tool_registry.get("find_mcp_tool") is not None
    assert environment.registry.check_permission("agent", "find_mcp_tool", ToolPermission.READ)
    assert any(
        grant.tool_id == "find_mcp_tool" and grant.permission is ToolPermission.READ
        for grant in environment.permissions.get_active_grants_sync("agent")
    )
    originals = {
        tool_id: environment.registry.get(tool_id)
        for tool_id in environment.registry.list_ids()
    }
    finder = environment.registry.get_tool("find_mcp_tool")
    assert finder is not None
    offers: list[MCPDispatchOffer] = []
    limits: list[int] = []
    source_calls: list[str] = []
    projected_calls: list[str] = []
    bridge_calls: list[tuple[str, str, dict[str, Any], dict[str, Any]]] = []
    source_events: list[tuple[str, dict[str, Any]]] = []
    environment.registry.set_event_callback(
        lambda event, payload: source_events.append((event, dict(payload)))
    )
    real_factory = environment.workbench.create_dispatch_offer
    real_source_invoke = environment.registry.check_and_invoke
    real_projected_invoke = projection.tool_registry.check_and_invoke
    real_bridge_invoke = environment.bridge.invoke

    async def record_factory(agent_id: str, *, preload_limit: int) -> MCPDispatchOffer:
        offer = await real_factory(agent_id, preload_limit=preload_limit)
        limits.append(preload_limit)
        offers.append(offer)
        return offer

    async def source_invoke(
        agent_id: str, tool_id: str, params: dict[str, Any], **kwargs: Any
    ) -> ToolResult:
        source_calls.append(tool_id)
        return await real_source_invoke(agent_id, tool_id, params, **kwargs)

    async def projected_invoke(
        agent_id: str, tool_id: str, params: dict[str, Any], **kwargs: Any
    ) -> ToolResult:
        projected_calls.append(tool_id)
        return await real_projected_invoke(agent_id, tool_id, params, **kwargs)

    async def bridge_invoke(
        server_url: str, tool_name: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        output = await real_bridge_invoke(server_url, tool_name, params)
        bridge_calls.append((server_url, tool_name, dict(params), output))
        return output

    monkeypatch.setattr(environment.workbench, "create_dispatch_offer", record_factory)
    monkeypatch.setattr(environment.registry, "check_and_invoke", source_invoke)
    monkeypatch.setattr(projection.tool_registry, "check_and_invoke", projected_invoke)
    monkeypatch.setattr(environment.bridge, "invoke", bridge_invoke)

    async def step(index: int, request: LLMRequest) -> list[ToolCallRequest] | None:
        assert request.messages is None
        assert "MCPDispatchOffer" not in request.prompt
        if index < 2:
            assert _offered_names(request) == ["ordinary_probe", "find_mcp_tool"]
            assert limits == [0] and len(offers) == 1
            assert offers[0].capacity == 24
            assert offers[0].selected_ids == offers[0].pending_ids == ()
            assert offers[0].belongs_to(environment.workbench, "agent") is True
            assert facade.accepts_dispatch_offer(offers[0], "agent") is True
            assert environment.workbench.pulled_count == 0
            assert projection.tool_registry.get(target) is None
            if index == 0:
                return [_call("ordinary_probe", "projection-control", marker="projection-control")]
            assert "projection-control" in request.prompt
            assert environment.probe.calls[0][1][MCP_DISPATCH_OFFER_CONTEXT_KEY] is offers[0]
            return [_call("find_mcp_tool", "projection-find", query="echo")]
        assert _offered_names(request) == ["ordinary_probe", "find_mcp_tool", alias]
        assert alias != target
        assert offers[0].selected_ids == (target,) and offers[0].pending_ids == ()
        original = environment.registry.get(target)
        detached = projection.tool_registry.get(target)
        assert original is not None and detached is not None
        assert detached.tool is not original.tool
        assert detached.tool.input_schema == original.tool.input_schema
        assert detached.tool.input_schema["properties"] is not original.tool.input_schema["properties"]
        parameters = request.tools[-1]["function"]["parameters"]
        assert parameters["required"] == ["q"]
        assert parameters["properties"]["q"]["type"] == "string"
        if index == 2:
            assert "projection-find" in request.prompt
            assert "capacity_deferred_count" in request.prompt
            assert bridge_calls == []
            definition_only = await detached.tool.invoke(arguments, {"agent_id": "agent"})
            assert definition_only.error is not None and "no local executor" in definition_only.error
            return [_call(alias, "projection-echo", **arguments)]
        assert index == 3
        assert len(bridge_calls) == 1
        assert bridge_calls[0][:3] == ("offline", "echo", arguments)
        assert json.loads(bridge_calls[0][3]["content"][0]["text"]) == arguments
        assert arguments["q"] in request.prompt
        assert "[tool_result:projection-echo error=False]" in request.prompt
        return None

    llm = _BoundaryLLM(step)
    outcome = await _run_correction(projection, llm)

    _assert_script(environment, llm, 4)
    assert outcome.stopped_reason == "complete" and outcome.denied_tools == []
    assert source_calls == projected_calls == ["ordinary_probe", "find_mcp_tool", target]
    assert environment.workbench.pulled_count == 1
    assert environment.registry.get_tool("find_mcp_tool") is finder
    assert all(environment.registry.get(tool_id) is original for tool_id, original in originals.items())
    assert environment.events == source_events == []
    _assert_trace(environment, outcome, 3)
    assert b"_SessionMcpToolIds" not in environment.traces.blobs[outcome.tool_trace_ref]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    "revoked", "restriction", "registration-disabled", "registration-missing",
    "server-disabled", "server-missing", "loto",
])
async def test_correction_alias_keeps_current_source_authority_and_loto(
    echo_dispatch_env: _DispatchEnv, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    environment = echo_dispatch_env
    projection = await _correction_projection(environment)
    target = "mcp:offline:echo"
    alias = llm_function_name(target)
    invocations: list[tuple[str, str, dict[str, Any]]] = []
    mutations: list[str] = []
    source_events: list[tuple[str, dict[str, Any]]] = []
    environment.registry.set_event_callback(
        lambda event, payload: source_events.append((event, dict(payload)))
    )
    real_invoke = environment.bridge.invoke

    async def record_invoke(
        server_url: str, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        invocations.append((server_url, tool_name, dict(arguments)))
        return await real_invoke(server_url, tool_name, arguments)

    monkeypatch.setattr(environment.bridge, "invoke", record_invoke)

    async def mutate(params: dict[str, Any], context: dict[str, Any]) -> None:
        assert params == {"marker": "source-change"}
        assert len(invocations) == 1
        assert context[MCP_DISPATCH_OFFER_CONTEXT_KEY].selected_ids == (target,)
        registration = environment.registry.get(target)
        assert registration is not None and registration.enabled is True
        if change == "revoked":
            assert await environment.permissions.revoke_grant(environment.access_grant.id) is True
        elif change == "restriction":
            await environment.permissions.issue_grant(
                "agent", target, ToolPermission.NONE, is_restriction=True
            )
        elif change == "registration-disabled":
            environment.registry.register(registration.tool, enabled=False)
        elif change == "registration-missing":
            assert environment.registry.unregister(target) is True
        elif change == "server-disabled":
            disabled = await environment.servers.set_enabled(environment.server.id, False)
            assert disabled is not None and disabled.enabled is False
        elif change == "server-missing":
            monkeypatch.setattr(environment.servers, "list_sync", lambda: [])
            assert environment.servers.list_sync() == []
        else:
            assert change == "loto"
            environment.registry.register(registration.tool, concurrency="exclusive")
            assert environment.registry.acquire_lock(target, "operator", "correction-control")
        mutations.append(change)

    environment.probe.on_invoke = mutate

    async def step(index: int, request: LLMRequest) -> list[ToolCallRequest] | None:
        if index == 0:
            assert alias not in _offered_names(request)
            return [_call("find_mcp_tool", "source-find", query="echo")]
        if index == 1:
            assert alias in _offered_names(request)
            return [_call(alias, "source-positive", q="source-positive")]
        if index == 2:
            assert "source-positive" in request.prompt
            assert invocations == [("offline", "echo", {"q": "source-positive"})]
            return [
                _call("ordinary_probe", "source-change", marker="source-change"),
                _call(alias, "source-denied", q="must-not-invoke"),
            ]
        assert index == 3 and mutations == [change]
        assert (alias in _offered_names(request)) is (change == "loto")
        assert "[tool_result:source-denied error=True]" in request.prompt
        assert len(invocations) == 1
        assert environment.events == []
        if change in {"restriction", "registration-disabled"}:
            assert [event for event, payload in source_events] == ["TOOL_PERMISSION_DENIED"]
            assert source_events[0][1]["tool_id"] == target
        elif change == "loto":
            assert len(source_events) == 1
            assert source_events[0][1]["tool_id"] == target
            assert "locked by operator" in request.prompt
        else:
            assert source_events == []
        return None

    llm = _BoundaryLLM(step)
    outcome = await _run_correction(projection, llm)

    _assert_script(environment, llm, 4)
    assert outcome.stopped_reason == "complete"
    assert mutations == [change] and len(invocations) == 1
    assert environment.events == []
    assert MCP_DISPATCH_OFFER_CONTEXT_KEY not in json.dumps(source_events)
    _assert_trace(environment, outcome, 4)


@pytest.mark.asyncio
@pytest.mark.parametrize("restore_search", [False, True])
async def test_correction_missing_search_denial_is_not_recreated_or_upgraded(
    dispatch_env: _DispatchEnv, monkeypatch: pytest.MonkeyPatch, restore_search: bool
) -> None:
    environment = dispatch_env
    assert environment.workbench.register_search_tool() == "find_mcp_tool"
    await environment.permissions.issue_grant("agent", "find_mcp_tool", ToolPermission.READ)
    assert environment.registry.unregister("find_mcp_tool") is True
    projection = _session_correction_runtime(
        environment.runtime, agent_id="agent", department="engineering", rank="lieutenant"
    )
    denied_definition = projection.tool_registry.get("find_mcp_tool")
    assert denied_definition is not None
    assert environment.registry.get("find_mcp_tool") is None
    if restore_search:
        assert environment.workbench.register_search_tool() == "find_mcp_tool"
    source_definition = environment.registry.get("find_mcp_tool")
    factories: list[str] = []
    real_factory = environment.workbench.create_dispatch_offer

    async def record_factory(agent_id: str, *, preload_limit: int) -> MCPDispatchOffer:
        factories.append(agent_id)
        return await real_factory(agent_id, preload_limit=preload_limit)

    monkeypatch.setattr(environment.workbench, "create_dispatch_offer", record_factory)

    async def step(index: int, request: LLMRequest) -> list[ToolCallRequest] | None:
        assert _offered_names(request) == ["ordinary_probe"]
        if index == 0:
            return [
                _call("ordinary_probe", "missing-search-control", marker="missing-search-control"),
                _call("find_mcp_tool", "missing-search-denial", query="000"),
            ]
        assert index == 1
        assert "missing-search-control" in request.prompt
        assert "[tool_result:missing-search-denial error=True]" in request.prompt
        assert MCP_DISPATCH_OFFER_CONTEXT_KEY not in environment.probe.calls[0][1]
        return None

    llm = _BoundaryLLM(step)
    outcome = await _run_correction(projection, llm)

    _assert_script(environment, llm, 2)
    assert outcome.stopped_reason == "complete"
    assert outcome.denied_tools == ["find_mcp_tool"]
    assert factories == []
    assert projection.tool_registry.get("find_mcp_tool") is denied_definition
    assert environment.registry.get("find_mcp_tool") is source_definition
    assert environment.client is not None and environment.client.list_calls == 0
    assert isinstance(environment.bridge, _SearchBridge) and environment.bridge.invocations == []
    assert environment.events == []
    _assert_trace(environment, outcome, 2)


@pytest.mark.asyncio
async def test_correction_discovery_never_upgrades_frozen_adapter_denial(
    dispatch_env: _DispatchEnv,
) -> None:
    environment = dispatch_env
    target = _tool_id(0)
    alias = llm_function_name(target)
    await environment.permissions.issue_grant("agent", target, ToolPermission.WRITE)
    assert environment.registry.get(target) is None
    projection = await _correction_projection(environment)
    denied_definition = projection.tool_registry.get(target)
    assert denied_definition is not None

    async def step(index: int, request: LLMRequest) -> list[ToolCallRequest] | None:
        assert alias not in _offered_names(request)
        if index == 0:
            return [
                _call("find_mcp_tool", "frozen-find", query="000"),
                _call("ordinary_probe", "frozen-control", marker="frozen-control"),
            ]
        assert environment.registry.get(target) is not None
        assert environment.workbench.pulled_count == 1
        assert projection.tool_registry.get(target) is denied_definition
        offer = environment.probe.calls[0][1][MCP_DISPATCH_OFFER_CONTEXT_KEY]
        assert offer.selected_ids == offer.pending_ids == ()
        if index == 1:
            assert "frozen-control" in request.prompt and "frozen-find" in request.prompt
            return [_call(alias, "frozen-denial", value="must-not-invoke")]
        assert index == 2
        assert "[tool_result:frozen-denial error=True]" in request.prompt
        return None

    llm = _BoundaryLLM(step)
    outcome = await _run_correction(projection, llm)

    _assert_script(environment, llm, 3)
    assert outcome.stopped_reason == "complete" and outcome.denied_tools
    assert isinstance(environment.bridge, _SearchBridge) and environment.bridge.invocations == []
    assert environment.events == []
    _assert_trace(environment, outcome, 3)


@pytest.mark.asyncio
async def test_correction_malformed_discovered_metadata_is_not_installed_or_invoked(
    dispatch_env: _DispatchEnv,
) -> None:
    environment = dispatch_env
    projection = await _correction_projection(environment)
    target = _tool_id(0)
    alias = llm_function_name(target)
    corrupted: list[str] = []

    async def corrupt_metadata(params: dict[str, Any], context: dict[str, Any]) -> None:
        registration = environment.registry.get(target)
        assert registration is not None
        assert projection.tool_registry.get(target) is None
        assert context[MCP_DISPATCH_OFFER_CONTEXT_KEY].pending_ids == (target,)
        invalid_tag: Any = object()
        registration.tags.append(invalid_tag)
        corrupted.append(target)

    environment.probe.on_invoke = corrupt_metadata

    async def step(index: int, request: LLMRequest) -> list[ToolCallRequest] | None:
        assert _offered_names(request) == ["ordinary_probe", "find_mcp_tool"]
        if index == 0:
            return [
                _call("find_mcp_tool", "malformed-find", query="000"),
                _call("ordinary_probe", "malformed-control", marker="malformed-control"),
            ]
        assert corrupted == [target]
        assert projection.tool_registry.get(target) is None
        assert environment.registry.get(target) is not None
        assert environment.workbench.pulled_count == 1
        if index == 1:
            assert "malformed-control" in request.prompt
            return [_call(alias, "malformed-denial", value="must-not-invoke")]
        assert index == 2
        assert "[tool_result:malformed-denial error=True]" in request.prompt
        return None

    llm = _BoundaryLLM(step)
    outcome = await _run_correction(projection, llm)

    _assert_script(environment, llm, 3)
    assert outcome.stopped_reason == "complete"
    assert isinstance(environment.bridge, _SearchBridge) and environment.bridge.invocations == []
    assert environment.events == []
    _assert_trace(environment, outcome, 3)


@pytest.mark.asyncio
async def test_correction_synchronization_validates_batches_and_selects_only_supplied_ids(
    dispatch_env: _DispatchEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = dispatch_env
    projection = await _correction_projection(environment)
    facade = projection.mcp_workbench
    assert facade is not None
    legacy = facade.dispatch_tool_ids("agent")
    assert legacy == ["find_mcp_tool"]
    warm_ids = await _warm_dispatch(environment, count=3)
    assert all(projection.tool_registry.get(tool_id) is None for tool_id in warm_ids)
    initial_count = projection.tool_registry.count()
    real_select = environment.workbench.dispatch_tool_ids
    selections: list[tuple[str, ...]] = []
    enumerations: list[None] = []

    def select(agent_id: str, *, candidate_ids: Sequence[str] | None = None) -> list[str]:
        assert candidate_ids is not None
        selections.append(tuple(candidate_ids))
        return real_select(agent_id, candidate_ids=candidate_ids)

    def forbid_catalog(**kwargs: Any) -> list[Any]:
        enumerations.append(None)
        raise AssertionError("Correction refresh must not enumerate the source catalog")

    monkeypatch.setattr(environment.workbench, "dispatch_tool_ids", select)
    monkeypatch.setattr(environment.registry, "list_tools", forbid_catalog)
    malformed_batches: list[Any] = [
        warm_ids[0], b"mcp:offline:tool_000", 1, {},
        [warm_ids[0], None], [warm_ids[0], "x" * 257], ["find_mcp_tool"] * 1001,
    ]
    for invalid in malformed_batches:
        with pytest.raises(ValueError, match="mcp_selection_invalid"):
            facade.dispatch_tool_ids("agent", candidate_ids=invalid)
        with pytest.raises(ValueError, match="mcp_selection_invalid"):
            projection.tool_registry.synchronize_mcp_definitions(invalid)
        assert projection.tool_registry.count() == initial_count
        assert selections == []
    with pytest.raises(ValueError, match="mcp_selection_invalid"):
        projection.tool_registry.synchronize_mcp_definitions(None)
    assert projection.tool_registry.synchronize_mcp_definitions([]) == []
    assert projection.tool_registry.synchronize_mcp_definitions(["ordinary_probe", "mcp::bad"]) == []
    assert facade.dispatch_tool_ids("agent", candidate_ids=[]) == ["find_mcp_tool"]
    missing = "mcp:offline:missing"
    assert facade.dispatch_tool_ids("agent", candidate_ids=[missing]) == ["find_mcp_tool"]
    requested = (warm_ids[1], warm_ids[0], warm_ids[1])
    assert facade.dispatch_tool_ids("agent", candidate_ids=requested) == [
        "find_mcp_tool", warm_ids[1], warm_ids[0],
    ]
    assert selections == [(), (missing,), requested]
    assert enumerations == []
    assert projection.tool_registry.count() == initial_count + 2
    assert projection.tool_registry.get(warm_ids[2]) is None
    for tool_id in warm_ids[:2]:
        original = environment.registry.get(tool_id)
        detached = projection.tool_registry.get(tool_id)
        assert original is not None and detached is not None
        assert detached.tool is not original.tool
        assert detached.tool.input_schema == original.tool.input_schema
    assert facade.dispatch_tool_ids("agent") == legacy
    assert environment.events == []


@pytest.mark.asyncio
@pytest.mark.parametrize(("limit_name", "limit"), [
    ("_MAX_SESSION_PROJECTION_SOURCE_TOOLS", 3),
    ("_MAX_SESSION_PROJECTED_TOOLS", 4),
])
async def test_correction_synchronization_rejects_cardinality_before_any_batch_installation(
    dispatch_env: _DispatchEnv, monkeypatch: pytest.MonkeyPatch,
    limit_name: str, limit: int,
) -> None:
    environment = dispatch_env
    projection = await _correction_projection(environment)
    assert environment.registry.count() == 2
    assert projection.tool_registry.count() == 3
    warm_ids = await _warm_dispatch(environment, count=2)
    facade = projection.mcp_workbench
    assert facade is not None
    with monkeypatch.context() as bounded:
        bounded.setattr(verifier_module, limit_name, limit)
        assert facade.dispatch_tool_ids("agent", candidate_ids=warm_ids) == []
        assert projection.tool_registry.count() == 3
        assert all(projection.tool_registry.get(tool_id) is None for tool_id in warm_ids)
    assert facade.dispatch_tool_ids("agent", candidate_ids=warm_ids) == [
        "find_mcp_tool", *warm_ids,
    ]
    assert projection.tool_registry.count() == 5
    assert environment.workbench.pulled_count == 2
    assert environment.events == []


@pytest.mark.asyncio
@pytest.mark.parametrize("owner", ["source", "projection"])
async def test_correction_synchronization_never_replaces_non_mcp_definitions(
    dispatch_env: _DispatchEnv, owner: str
) -> None:
    environment = dispatch_env
    projection = await _correction_projection(environment)
    target = (await _warm_dispatch(environment, count=1))[0]
    ordinary = _DispatchProbe()
    ordinary.tool_id = target
    registry = environment.registry if owner == "source" else projection.tool_registry
    registration = registry.register(ordinary)
    facade = projection.mcp_workbench
    assert facade is not None

    assert facade.dispatch_tool_ids("agent", candidate_ids=[target]) == ["find_mcp_tool"]

    assert registry.get(target) is registration
    assert ordinary.calls == []
    if owner == "source":
        assert projection.tool_registry.get(target) is None
    assert environment.events == []


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["read-error", "wrong-id", "disabled"])
async def test_correction_synchronization_rejects_unavailable_source_metadata(
    dispatch_env: _DispatchEnv, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    environment = dispatch_env
    projection = await _correction_projection(environment)
    targets = await _warm_dispatch(environment, count=2)
    target = targets[0]
    selected = environment.workbench.dispatch_tool_ids("agent", candidate_ids=[target])
    assert selected == ["find_mcp_tool", target]
    real_get = environment.registry.get
    original = real_get(target)
    assert original is not None
    reads: list[str] = []

    def read(tool_id: str) -> Any:
        if tool_id == target:
            reads.append(tool_id)
            if failure == "read-error":
                raise RuntimeError("injected source metadata read failure")
            if failure == "wrong-id":
                return real_get(targets[1])
            return replace(original, enabled=False)
        return real_get(tool_id)

    with monkeypatch.context() as unavailable:
        unavailable.setattr(environment.registry, "get", read)
        assert projection.tool_registry.synchronize_mcp_definitions(selected) == ["find_mcp_tool"]
        assert reads == [target]
        assert projection.tool_registry.get(target) is None
    assert projection.tool_registry.synchronize_mcp_definitions(selected) == selected
    assert environment.registry.get(target) is original
    assert projection.tool_registry.get(target).tool is not original.tool
    assert environment.events == []


@pytest.mark.asyncio
async def test_correction_facade_rejects_source_results_outside_explicit_candidates(
    dispatch_env: _DispatchEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = dispatch_env
    projection = await _correction_projection(environment)
    target = (await _warm_dispatch(environment, count=1))[0]
    facade = projection.mcp_workbench
    assert facade is not None
    assert projection.tool_registry.get(target) is None
    for response in (None, "find_mcp_tool", ["find_mcp_tool", target], [None]):
        selections: list[Sequence[str] | None] = []

        def select(agent_id: str, *, candidate_ids: Sequence[str] | None = None) -> Any:
            selections.append(candidate_ids)
            return response

        monkeypatch.setattr(environment.workbench, "dispatch_tool_ids", select)
        with pytest.raises(ValueError, match="mcp_selection_invalid"):
            facade.dispatch_tool_ids("agent", candidate_ids=())
        assert selections == [()]
        assert projection.tool_registry.get(target) is None
    assert environment.workbench.pulled_count == 1
    assert environment.events == []


@pytest.mark.asyncio
@pytest.mark.parametrize("response_kind", ["outside-selection", "not-list", "invalid-member"])
async def test_invalid_initial_selection_preserves_non_mcp_work(
    response_kind: str, dispatch_env: _DispatchEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = dispatch_env
    target = (await _warm_dispatch(environment, count=1))[0]
    assert environment.registry.get(target) is not None
    assert environment.runtime.config.mcp.max_directly_offered_tools == 0
    real_select = environment.workbench.dispatch_tool_ids
    assert real_select("agent", candidate_ids=()) == ["find_mcp_tool"]
    responses: dict[str, Any] = {
        "outside-selection": ["find_mcp_tool", target],
        "not-list": ("find_mcp_tool",),
        "invalid-member": ["find_mcp_tool", {}],
    }
    selections: list[tuple[str, ...]] = []
    loop_options: list[set[str]] = []
    real_loop = loop_module.AgenticLoop

    def invalid_selection(
        agent_id: str, *, candidate_ids: Sequence[str] | None = None
    ) -> Any:
        assert agent_id == "agent" and candidate_ids == ()
        selections.append(tuple(candidate_ids))
        return responses[response_kind]

    def observe_loop(**kwargs: Any) -> Any:
        loop_options.append(set(kwargs))
        return real_loop(**kwargs)

    monkeypatch.setattr(environment.workbench, "dispatch_tool_ids", invalid_selection)
    monkeypatch.setattr(loop_module, "AgenticLoop", observe_loop)

    async def step(index: int, request: LLMRequest) -> list[ToolCallRequest] | None:
        assert _offered_names(request) == ["ordinary_probe"]
        assert selections == [()]
        if index == 0:
            return [_call("ordinary_probe", "invalid-selection-work", marker="survived")]
        assert index == 1 and "survived" in _history(request)
        assert len(environment.probe.calls) == 1
        assert MCP_DISPATCH_OFFER_CONTEXT_KEY not in environment.probe.calls[0][1]
        return None

    llm = _BoundaryLLM(step)
    outcome = await _run_dispatch(environment, llm)

    _assert_script(environment, llm, 2)
    assert outcome.stopped_reason == "complete"
    assert selections == [()]
    assert len(loop_options) == 1 and "refresh_tools" not in loop_options[0]
    _assert_trace(environment, outcome, 1)
