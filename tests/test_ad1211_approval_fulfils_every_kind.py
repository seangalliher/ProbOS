"""AD-1211: approving a request must actually fulfil it.

Approving a pending ``grant``, ``install`` or ``build`` recorded the decision
and did nothing else. The card vanished, no grant was issued, no package
installed, no agent built, no FULFILLED event fired — and
``CapabilityGapDriver.on_capability_event`` resumes a blocked work item on
FULFILLED **only** (``capability_gap_driver.py``: *"approved" -> no-op; resume
fires on the FULFILLED event*). So the linked work item stayed blocked forever.

Enumerated before the fix, not recalled: ``rg '\\.mark_fulfilled\\(' src/``
returned three call sites — two in ``capability_triage`` that run at FILE time
(the grant fast path and the build route) and one in the router gated to
``continue`` alone (AD-1204). No actor existed on the approval path for any of
the three kinds.

**Every chain test here spans the whole seam**: a pending request linked to a
blocked work item -> the real route -> the real fulfiller -> FULFILLED across a
real event bus -> the driver resuming and re-dispatching the item. A test that
stops at "the fulfiller was called" is exactly how this defect class survives:
each half passes and the chain is dead. That is what BF-722 found, and what
AD-1204 found before it.

The install path carries the second defect this AD closes. ``ensure_dependency``
has its OWN approval gate, so routing a Captain-approved install straight there
asks the same human for the same package a second time.
``TestInstallDoesNotAskTwice`` wires a REAL approval callback and asserts it is
never awaited.
"""

from __future__ import annotations

import asyncio
import functools
import sys
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.api_models import CapabilityRequestDecideRequest
from probos.capability_request import CapabilityRequest, CapabilityRequestStore
from probos.cognitive import capability_triage
from probos.cognitive.capability_gap_driver import CapabilityGapDriver
from probos.cognitive.dependency_resolver import DependencyResolver
from probos.cognitive.mcp_workbench import MCPWorkbench
from probos.events import EventType
from probos.integrations.mcp_bridge import MCPBridge
from probos.integrations.mcp_bridge.store import McpServerRecord, McpServerStore
from probos.routers import capability_requests as router_mod
from probos.routers.capability_requests import (
    _APPROVAL_FULFILLERS,
    decide_capability_request,
)
from probos.runtime import ProbOSRuntime
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolPermission
from probos.tools.registry import ToolRegistry
from probos.workforce import WorkItemStore
from tests.test_ad1215_install_rung_mcp import _FakeBridge

_PKG = "feedparser"


# ── Test doubles ───────────────────────────────────────────────────────────


class _RecordingRouter:
    """Stub WorkItemRouter that records re-dispatch calls (AD-855's shape)."""

    def __init__(self) -> None:
        self.dispatched: list[dict[str, Any]] = []

    async def on_work_item_created(self, event: dict[str, Any]) -> None:
        self.dispatched.append(event)


class _EventBus:
    """The runtime's local event dispatch, faithfully enough to prove the chain.

    ``EventEmitterMixin._emit`` calls its hook SYNCHRONOUSLY and
    ``runtime._emit_event_local`` spawns a task for a coroutine listener while
    holding the reference (BF-639). Both are mirrored here, so FULFILLED really
    travels store -> listener -> driver instead of being hand-delivered. An
    async ``emit`` would never be awaited and every downstream assertion would
    pass vacuously.
    """

    def __init__(self) -> None:
        self._listeners: list[Any] = []
        self._tasks: set[asyncio.Task[Any]] = set()
        self.emitted: list[str] = []
        self.on_fulfilled: Callable[[], None] | None = None

    def add_event_listener(self, fn: Any) -> None:
        self._listeners.append(fn)

    def emit(self, event_type: Any, data: dict[str, Any]) -> None:
        type_str = str(getattr(event_type, "value", event_type))
        self.emitted.append(type_str)
        if type_str == EventType.CAPABILITY_REQUEST_FULFILLED.value:
            if self.on_fulfilled is not None:
                self.on_fulfilled()
        event = {"type": type_str, "data": dict(data or {}), "timestamp": time.time()}
        for fn in self._listeners:
            task = asyncio.create_task(fn(event))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        """Await every listener task, including ones they spawn in turn."""
        while self._tasks:
            pending = tuple(self._tasks)
            try:
                await asyncio.gather(*pending)
            finally:
                self._tasks.difference_update(task for task in pending if task.done())


class _Runtime(SimpleNamespace):
    """Exactly the attributes the route, the fulfillers and the driver read."""


class _ToolRegistry:
    def __init__(self, registrations: dict[str, Any]) -> None:
        self._registrations = registrations

    def get(self, tool_id: str) -> Any:
        return self._registrations.get(tool_id)


def _registration(default_permissions: dict[str, str]) -> SimpleNamespace:
    """Only ``default_permissions`` is read by ``_derive_tool_permission``."""
    return SimpleNamespace(default_permissions=default_permissions)


class _SelfMod:
    """Records the pipeline call and returns a canned record."""

    def __init__(self, record: Any) -> None:
        self._record = record
        self.calls: list[tuple[str, str]] = []

    async def handle_unhandled_intent(
        self,
        intent_name: str,
        description: str,
        _params: dict[str, str],
        # BF-744: the real signature also takes requires_consensus and
        # execution_context. A double narrower than the thing it stands in for
        # fails the moment production starts passing them -- which is what
        # happened here, and is why it is widened rather than pinned.
        **_kw: Any,
    ) -> Any:
        self.calls.append((intent_name, description))
        return self._record


class _RaisingSelfMod:
    async def handle_unhandled_intent(self, *_a: Any, **_kw: Any) -> Any:
        raise RuntimeError("AD-1211: simulated design failure")


class _EventLog:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    async def log(self, *, category: str, event: str, detail: str = "", **_kw: Any) -> None:
        self.events.append((category, event))

    def names(self) -> list[str]:
        return [e for _c, e in self.events]


# ── The wired system ───────────────────────────────────────────────────────


class _Wired:
    """The AD-855 loop wired the way startup wires it, plus the route."""

    def __init__(self, runtime, driver, router, bus, work_items, requests, perms):
        self.runtime = runtime
        self.driver = driver
        self.router = router
        self.bus = bus
        self.work_items = work_items
        self.requests = requests
        self.perms = perms


@pytest.fixture
async def wired(tmp_path):
    work_items = WorkItemStore(db_path=str(tmp_path / "wis.db"), tick_interval=1000)
    await work_items.start()
    perms = ToolPermissionStore(db_path=str(tmp_path / "perms.db"))
    await perms.start()
    bus = _EventBus()
    trust = MagicMock()
    requests = CapabilityRequestStore(
        db_path=str(tmp_path / "cap.db"), emit_event=bus.emit, trust_network=trust
    )
    await requests.start()
    router = _RecordingRouter()
    runtime = _Runtime(
        work_item_router=router,
        work_item_store=work_items,
        capability_request_store=requests,
        tool_permission_store=perms,
        trust_network=trust,
        tool_registry=_ToolRegistry({}),
        self_mod_pipeline=None,
        dependency_resolver=None,
        event_log=_EventLog(),
        config=SimpleNamespace(
            self_mod=SimpleNamespace(allowed_imports=[]),
            # AD-1222: ensure_dependency now reads its auto-approve tier from
            # config.dependency, not from the self-mod import allowlist. Empty
            # here preserves what this fixture always meant: nothing is
            # auto-approved, so the no-callback refusal is what gets tested.
            dependency=SimpleNamespace(auto_approve_imports=[]),
        ),
    )
    runtime.ensure_dependency = functools.partial(
        ProbOSRuntime.ensure_dependency, runtime
    )
    driver = CapabilityGapDriver(
        runtime=runtime,
        work_item_store=work_items,
        capability_request_store=requests,
    )
    runtime.capability_gap_driver = driver
    bus.add_event_listener(driver.on_capability_event)
    try:
        yield _Wired(runtime, driver, router, bus, work_items, requests, perms)
    finally:
        await bus.drain()
        await requests.stop()
        await perms.stop()
        await work_items.stop()


async def _blocked_on(wired, *, kind: str, target: str) -> tuple[Any, Any]:
    """A work item parked ``blocked`` on a linked pending request of ``kind``."""
    item = await wired.work_items.create_work_item(
        title=f"Work needing {target}",
        description=f"Work needing {target}",
        work_type="task",
        assigned_to="agent-1",
        created_by="captain",
    )
    await wired.work_items.transition_work_item(
        item.id, "in_progress", source="agent-1"
    )
    req = await wired.requests.file_request(
        agent_id="agent-1",
        kind=kind,
        target=target,
        rationale=f"work item {item.id} blocked on capability: {target}",
        work_item_id=item.id,
    )
    parked = await wired.driver.block_on_request(
        work_item_id=item.id, request_id=req.id, reason=target
    )
    assert parked is True
    refreshed = await wired.work_items.get_work_item(item.id)
    assert refreshed is not None and refreshed.status == "blocked"
    return item, req


async def _approve(wired, request_id: str, *, approve: bool = True) -> dict[str, Any]:
    response = await decide_capability_request(
        request_id,
        # A reason is REQUIRED on denial (``CapabilityRequestDecideRequest``
        # validates it), so it cannot be omitted here.
        CapabilityRequestDecideRequest(
            approve=approve, reason="" if approve else "not needed"
        ),
        runtime=wired.runtime,
    )
    await wired.bus.drain()
    return response


@pytest.mark.asyncio
@pytest.mark.parametrize("vault_failure", ["missing", "raising"])
async def test_review_regression_missing_vault_approval_stays_disabled_after_boot(
    wired, tmp_path: Path, vault_failure: str,
) -> None:
    from probos.integrations.mcp_bridge.registration import register_record

    mcp_store = McpServerStore(db_path=str(tmp_path / "review-mcp.db"))
    bridge = MCPBridge()
    await mcp_store.start()
    try:
        record = await mcp_store.create(McpServerRecord(
            name="protected", type="http", url="https://example.test/protected",
            auth_kind="static", credential_ref="mcp:missing", enabled=False,
        ))
        control = await mcp_store.create(McpServerRecord(
            name="boot-control", type="http", url="https://example.test/boot-control",
            enabled=True,
        ))
        assert record.id and record.auth_kind == "static" and not record.enabled
        assert control.id != record.id and control.enabled
        wired.runtime.mcp_server_store = mcp_store
        wired.runtime.mcp_bridge = bridge
        wired.runtime.credential_vault = None
        if vault_failure == "raising":
            class _RaisingVault:
                async def read(self, *, ref: str, requesting_agent_id: str) -> str:
                    raise OSError("vault unavailable")

            wired.runtime.credential_vault = _RaisingVault()
        request = await capability_triage.triage_and_file(
            gap_target=record.id, agent_id="agent-1", store=wired.requests,
            mcp_server_store=mcp_store,
        )
        assert (request.kind, request.target, request.status) == (
            "install", record.id, "pending"
        )
        assert bridge.list_servers() == []

        await _approve(wired, request.id)

        approved = await wired.requests.get(request.id)
        assert approved is not None and approved.status == "approved"
        assert bridge.get_client(record.url) is None
        after_approval = next(row for row in mcp_store.list_sync() if row.id == record.id)
        await mcp_store.stop()
        await mcp_store.start()
        rows = mcp_store.list_sync()
        assert {row.id for row in rows} == {record.id, control.id}
        restored = next(row for row in rows if row.id == record.id)
        assert restored.auth_kind == "static"
        assert restored.credential_ref == "mcp:missing"

        for row in rows:
            if row.enabled:
                await register_record(wired.runtime, row)

        assert bridge.get_client(control.url) is not None
        assert bridge.get_client(record.url) is None
        assert after_approval.enabled is False
        assert restored.enabled is False
        assert bridge.list_servers() == [control.url]
        unfulfilled = await wired.requests.get(request.id)
        assert unfulfilled is not None and unfulfilled.status == "approved"
    finally:
        await wired.bus.drain()
        await bridge.close_all()
        await mcp_store.stop()


def _install_resolver(
    state: dict[str, bool],
    *,
    approval_fn: Any = None,
    allowed: list[str] | None = None,
    deny: list[str] | None = None,
) -> DependencyResolver:
    async def install(_pkg: str) -> tuple[bool, str]:
        state["installed"] = True
        return (True, "ok")

    return DependencyResolver(
        allowed_imports=allowed if allowed is not None else [_PKG],
        install_fn=install,
        approval_fn=approval_fn,
        policy="prompt_unlisted",
        deny_imports=deny,
    )


def _find_spec_after_install(state: dict[str, bool]):
    """``find_spec`` that reports the package only once the install has run."""

    def side_effect(name: str):
        if name == _PKG:
            return MagicMock() if state.get("installed") else None
        return MagicMock()

    return patch(
        "probos.cognitive.dependency_resolver.importlib.util.find_spec",
        side_effect=side_effect,
    )


# ══ 1. GRANT: the whole chain ══════════════════════════════════════════════


class TestGrantChain:
    @pytest.mark.asyncio
    async def test_approving_a_grant_issues_it_and_unblocks_the_item(self, wired):
        """route -> issue_grant -> mark_fulfilled -> FULFILLED -> item resumes.

        Before AD-1211 this stopped at the first arrow: status ``approved``,
        no grant, no event, work item blocked forever.
        """
        # Arrange
        wired.runtime.tool_registry = _ToolRegistry(
            {"calc_tool": _registration({"ensign": "read"})}
        )
        item, req = await _blocked_on(wired, kind="grant", target="calc_tool")

        # Act
        response = await _approve(wired, req.id)

        # Assert — the route says it fulfilled...
        assert response["fulfilled"] is True
        assert response["request"]["status"] == "fulfilled"
        # ...the store agrees...
        stored = await wired.requests.get(req.id)
        assert stored is not None and stored.status == "fulfilled"
        # ...FULFILLED really crossed the bus...
        assert EventType.CAPABILITY_REQUEST_FULFILLED.value in wired.bus.emitted
        # ...the agent holds the grant it asked for...
        held = wired.perms.get_active_grants_sync("agent-1", "calc_tool")
        assert [g.permission for g in held if not g.is_restriction] == [
            ToolPermission.READ
        ]
        # ...and the work item left ``blocked`` and was re-dispatched.
        resumed = await wired.work_items.get_work_item(item.id)
        assert resumed is not None and resumed.status == "in_progress"
        assert len(wired.router.dispatched) == 1

    @pytest.mark.asyncio
    async def test_the_permission_comes_from_the_tool_not_the_approval(self, wired):
        """Minimal Authority: approving cannot widen what the tool declares."""
        # Arrange — highest declared level across the matrix is WRITE.
        wired.runtime.tool_registry = _ToolRegistry(
            {"edit_tool": _registration({"ensign": "read", "commander": "write"})}
        )
        _item, req = await _blocked_on(wired, kind="grant", target="edit_tool")

        # Act
        await _approve(wired, req.id)

        # Assert — WRITE, not FULL.
        held = wired.perms.get_active_grants_sync("agent-1", "edit_tool")
        assert [g.permission for g in held] == [ToolPermission.WRITE]

    @pytest.mark.asyncio
    async def test_an_unregistered_tool_still_grants_the_ship_default(self, wired):
        """An empty/absent matrix means READ (``ToolRegistration`` semantics)."""
        # Arrange — the registry knows nothing about this target.
        _item, req = await _blocked_on(wired, kind="grant", target="mystery_tool")

        # Act
        response = await _approve(wired, req.id)

        # Assert
        assert response["fulfilled"] is True
        held = wired.perms.get_active_grants_sync("agent-1", "mystery_tool")
        assert [g.permission for g in held] == [ToolPermission.READ]

    @pytest.mark.asyncio
    async def test_no_permission_store_is_reported_and_stays_retriable(self, wired):
        """Nothing to issue into: say so, do not claim fulfilment."""
        # Arrange
        wired.runtime.tool_permission_store = None
        item, req = await _blocked_on(wired, kind="grant", target="calc_tool")

        # Act
        response = await _approve(wired, req.id)

        # Assert — 200, honest ``fulfilled=False``, item still waiting.
        assert response["fulfilled"] is False
        assert response["request"]["status"] == "approved"
        assert EventType.CAPABILITY_REQUEST_FULFILLED.value not in wired.bus.emitted
        blocked = await wired.work_items.get_work_item(item.id)
        assert blocked is not None and blocked.status == "blocked"
        assert wired.router.dispatched == []

    @pytest.mark.asyncio
    async def test_a_retry_after_a_failure_fulfils_and_unblocks(self, wired):
        """BF-722's retry path carries the new fulfillers too."""
        # Arrange — first approval has nowhere to issue the grant.
        wired.runtime.tool_permission_store = None
        item, req = await _blocked_on(wired, kind="grant", target="calc_tool")
        first = await _approve(wired, req.id)
        assert first["fulfilled"] is False

        # Act — the Captain clicks again with the store back.
        wired.runtime.tool_permission_store = wired.perms
        second = await _approve(wired, req.id)

        # Assert — the whole chain completes on the retry.
        assert second["fulfilled"] is True
        assert wired.perms.get_active_grants_sync("agent-1", "calc_tool")
        resumed = await wired.work_items.get_work_item(item.id)
        assert resumed is not None and resumed.status == "in_progress"
        assert len(wired.router.dispatched) == 1


# ══ 2. INSTALL: the whole chain ════════════════════════════════════════════


class TestInstallChain:
    @pytest.mark.asyncio
    async def test_approving_an_install_installs_it_and_unblocks_the_item(self, wired):
        """route -> ensure_dependency -> mark_fulfilled -> FULFILLED -> resume."""
        # Arrange — the REAL resolver and the REAL ensure_dependency.
        state: dict[str, bool] = {"installed": False}
        wired.runtime.dependency_resolver = _install_resolver(state)
        item, req = await _blocked_on(wired, kind="install", target=_PKG)

        # Act
        with _find_spec_after_install(state):
            response = await _approve(wired, req.id)

        # Assert
        assert state["installed"] is True
        assert response["fulfilled"] is True
        stored = await wired.requests.get(req.id)
        assert stored is not None and stored.status == "fulfilled"
        assert EventType.CAPABILITY_REQUEST_FULFILLED.value in wired.bus.emitted
        resumed = await wired.work_items.get_work_item(item.id)
        assert resumed is not None and resumed.status == "in_progress"
        assert len(wired.router.dispatched) == 1

    @pytest.mark.asyncio
    async def test_the_install_is_still_written_to_the_event_log(self, wired):
        """Pre-approval must not make an install invisible to the audit trail."""
        # Arrange
        state: dict[str, bool] = {"installed": False}
        wired.runtime.dependency_resolver = _install_resolver(state)
        _item, req = await _blocked_on(wired, kind="install", target=_PKG)

        # Act
        with _find_spec_after_install(state):
            await _approve(wired, req.id)

        # Assert — the same rows AD-838c has always written.
        logged = wired.runtime.event_log.names()
        assert "dependency_check" in logged
        assert "dependency_install_approved" in logged
        assert "dependency_install_success" in logged

    @pytest.mark.asyncio
    async def test_a_missing_dependency_subsystem_is_reported_honestly(self, wired):
        """Dynamic install disabled: no resolver, so nothing is claimed."""
        # Arrange — the fixture default: ``dependency_resolver=None``.
        item, req = await _blocked_on(wired, kind="install", target=_PKG)

        # Act
        response = await _approve(wired, req.id)

        # Assert
        assert response["fulfilled"] is False
        assert response["request"]["status"] == "approved"
        assert EventType.CAPABILITY_REQUEST_FULFILLED.value not in wired.bus.emitted
        blocked = await wired.work_items.get_work_item(item.id)
        assert blocked is not None and blocked.status == "blocked"

    @pytest.mark.asyncio
    async def test_a_runtime_without_ensure_dependency_is_reported_honestly(
        self, wired
    ):
        """The fulfiller reaches for a method that may not be there at all."""
        # Arrange
        del wired.runtime.ensure_dependency
        _item, req = await _blocked_on(wired, kind="install", target=_PKG)

        # Act
        response = await _approve(wired, req.id)

        # Assert
        assert response["fulfilled"] is False
        assert response["request"]["status"] == "approved"

    @pytest.mark.asyncio
    async def test_a_failed_install_is_reported_honestly(self, wired):
        """pip said no: the approval stands, the request does not."""
        # Arrange — install "succeeds" but the module never appears.
        async def install(_pkg: str) -> tuple[bool, str]:
            return (False, "pip exploded")

        wired.runtime.dependency_resolver = DependencyResolver(
            allowed_imports=[_PKG], install_fn=install, policy="prompt_unlisted"
        )
        item, req = await _blocked_on(wired, kind="install", target=_PKG)

        # Act
        with patch(
            "probos.cognitive.dependency_resolver.importlib.util.find_spec",
            return_value=None,
        ):
            response = await _approve(wired, req.id)

        # Assert
        assert response["fulfilled"] is False
        stored = await wired.requests.get(req.id)
        assert stored is not None and stored.status == "approved"
        blocked = await wired.work_items.get_work_item(item.id)
        assert blocked is not None and blocked.status == "blocked"

    @pytest.mark.asyncio
    async def test_the_deny_list_still_applies_to_a_pre_approved_install(self, wired):
        """``pre_approved`` suppresses the PROMPT, never the policy.

        A denied import is excluded by ``detect_missing`` before approval is
        ever reached, so it stays excluded. Nothing installs, and because
        nothing was missing the resolver reports success with an empty install
        list — which is the honest answer: the package the Captain approved is
        not one this ship will install.
        """
        # Arrange
        state: dict[str, bool] = {"installed": False}
        wired.runtime.dependency_resolver = _install_resolver(
            state, allowed=[], deny=[_PKG]
        )
        _item, req = await _blocked_on(wired, kind="install", target=_PKG)

        # Act
        with _find_spec_after_install(state):
            await _approve(wired, req.id)

        # Assert — the deny list held.
        assert state["installed"] is False


@pytest.fixture
async def mcp_store(tmp_path: Path) -> AsyncIterator[McpServerStore]:
    store = McpServerStore(db_path=str(tmp_path / "mcp.db"))
    await store.start()
    try:
        yield store
    finally:
        await store.stop()


async def _mcp_gap(wired: _Wired, record: McpServerRecord) -> CapabilityRequest:
    item = await wired.work_items.create_work_item(
        title="Work needing MCP", description="Use the registered MCP server",
        work_type="task", assigned_to="agent-1", created_by="captain",
    )
    await wired.work_items.transition_work_item(
        item.id, "in_progress", source="agent-1"
    )
    request = await wired.driver.on_capability_gap(
        work_item_id=item.id, gap_target=record.id, agent_id="agent-1"
    )
    await wired.bus.drain()
    assert request is not None
    assert request.kind == "install" and request.status == "pending"
    assert request.work_item_id == item.id
    stored = await wired.runtime.mcp_server_store.get(record.id)
    assert stored is not None and stored.enabled is False
    blocked = await wired.work_items.get_work_item(item.id)
    assert blocked is not None and blocked.status == "blocked"
    assert blocked.metadata["capability_request_id"] == request.id
    assert wired.router.dispatched == []
    return request


class _PausingMcpBridge(MCPBridge):
    """Pause at explicit registration boundaries without replacing transport I/O."""

    def __init__(self, pause_at: str | None) -> None:
        super().__init__(
            request_timeout=5.0, stdio_enabled=True,
            command_allowlist=[sys.executable], consent_fn=self._consent,
        )
        self.pause_at = pause_at
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.registration_attempts = 0

    async def _consent(self, context: dict[str, Any]) -> bool:
        assert context["tool_name"] == "mcp_stdio_spawn"
        if self.pause_at == "consent":
            self.entered.set()
            await self.release.wait()
        return True

    async def register_stdio_server(
        self, name: str, command: str, args: list[str], env: dict[str, str],
        cwd: str, *, timeout: float | None = None, reuse_if_matching: bool = False,
    ) -> bool:
        self.registration_attempts += 1
        registered = await super().register_stdio_server(
            name, command, args, env, cwd, timeout=timeout, reuse_if_matching=reuse_if_matching,
        )
        if registered and self.pause_at == "registered":
            self.entered.set()
            await self.release.wait()
        return registered


class TestMcpInstallApprovalChain:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("failure", ["registration", "fulfilment"])
    async def test_retry_registers_before_event_and_resumes_once(
        self, wired: _Wired, mcp_store: McpServerStore, failure: str,
    ) -> None:
        bridge = _FakeBridge()
        wired.runtime.mcp_server_store = mcp_store
        wired.runtime.mcp_bridge = bridge
        dependency = AsyncMock()
        wired.runtime.ensure_dependency = dependency
        record = await mcp_store.create(McpServerRecord(
            name="retry-mcp", type="http", url="https://example.test/mcp",
            enabled=False,
        ))
        request = await _mcp_gap(wired, record)
        assert bridge.register_calls == []
        assert bridge.get_client(record.url) is None
        clients_at_event: list[object | None] = []
        wired.bus.on_fulfilled = lambda: clients_at_event.append(
            bridge.get_client(record.url)
        )
        if failure == "registration":
            bridge.accept = False
        with patch.object(wired.requests, "decide", wraps=wired.requests.decide) as decide:
            with patch.object(
                wired.requests, "mark_fulfilled",
                wraps=wired.requests.mark_fulfilled,
            ) as fulfil:
                if failure == "fulfilment":
                    fulfil.side_effect = RuntimeError("durable fulfilment unavailable")
                first = await _approve(wired, request.id)
                assert first["fulfilled"] is False
                assert first["request"]["status"] == "approved"
                assert fulfil.await_count == (1 if failure == "fulfilment" else 0)
            stored = await mcp_store.get(record.id)
            assert stored is not None and stored.enabled == (failure == "fulfilment"), (
                "registration refusal must not persist enablement; later persistence failures retain it"
            )
            assert bridge.register_calls == [record.url]
            assert (bridge.get_client(record.url) is not None) == (failure == "fulfilment")
            blocked = await wired.work_items.get_work_item(request.work_item_id)
            assert blocked is not None and blocked.status == "blocked"
            assert clients_at_event == []
            assert wired.router.dispatched == []
            wired.runtime.trust_network.record_outcome.assert_called_once()
            bridge.accept = True
            second = await _approve(wired, request.id)
            decide.assert_awaited_once()
        assert second["fulfilled"] is True
        assert second["request"]["status"] == "fulfilled"
        assert bridge.register_calls == [record.url, record.url]
        assert bridge.unregister_calls == [], "strict retry reuses; it never tears down a target"
        assert clients_at_event == [bridge.get_client(record.url)]
        assert clients_at_event[0] is not None
        assert wired.bus.emitted.count(EventType.CAPABILITY_REQUEST_FULFILLED.value) == 1
        assert wired.bus.emitted.count(EventType.CAPABILITY_REQUEST_DECIDED.value) == 1
        wired.runtime.trust_network.record_outcome.assert_called_once()
        dependency.assert_not_awaited()
        resumed = await wired.work_items.get_work_item(request.work_item_id)
        assert resumed is not None and resumed.status == "in_progress"
        assert len(wired.router.dispatched) == 1
        assert wired.router.dispatched[0]["data"]["work_item"]["id"] == request.work_item_id

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cancel_at", [None, "consent", "registered", "restart"])
    async def test_approved_stdio_is_callable_and_cancellation_is_retryable(
        self, wired: _Wired, mcp_store: McpServerStore, cancel_at: str | None,
    ) -> None:
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from probos.routers.deps import get_runtime

        app = FastAPI()
        app.include_router(router_mod.router)
        app.dependency_overrides[get_runtime] = lambda: wired.runtime
        fixture = Path(__file__).parent / "fixtures" / "echo_mcp_server.py"
        assert fixture.is_file()
        bridge = _PausingMcpBridge(cancel_at)
        registry = ToolRegistry()
        wired.runtime.mcp_server_store = mcp_store
        wired.runtime.mcp_bridge = bridge
        wired.runtime.tool_registry = registry
        dependency = AsyncMock()
        wired.runtime.ensure_dependency = dependency
        record = await mcp_store.create(McpServerRecord(
            name="echo", type="stdio", command=sys.executable,
            args=[str(fixture)], timeout_seconds=5.0, enabled=False,
            default_risk="open",
        ))
        await wired.perms.issue_grant(
            "agent-1", "mcp:echo:echo", ToolPermission.WRITE,
            reason="independent pre-existing tool grant",
        )
        grants_before = await wired.perms.list_grants(active_only=True)
        assert len(grants_before) == 1
        consensus = AsyncMock(side_effect=AssertionError("open echo requires no consensus"))
        episodes = AsyncMock()
        workbench = MCPWorkbench(
            tool_registry=registry, bridge=bridge, consensus_invoke=consensus,
            episode_writer=episodes, server_store=mcp_store, perm_store=wired.perms,
            dept_grant_store=None, risk_store=None, ontology=None, agent_registry=None,
        )
        clients_at_event: list[object | None] = []
        wired.bus.on_fulfilled = lambda: clients_at_event.append(
            bridge.get_client(record.name)
        )
        processes: list[asyncio.subprocess.Process] = []
        spawn = asyncio.create_subprocess_exec

        async def record_spawn(*args: Any, **kwargs: Any) -> asyncio.subprocess.Process:
            process = await spawn(*args, **kwargs)
            processes.append(process)
            return process

        async def approve_over_http() -> dict[str, Any]:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
                response = await api.post(
                    f"/api/capability-requests/{request.id}/decide", json={"approve": True},
                )
            assert response.status_code == 200
            await wired.bus.drain()
            return response.json()

        approval_task: asyncio.Task[dict[str, Any]] | None = None
        try:
            with patch(
                "probos.integrations.mcp_bridge.transport.asyncio.create_subprocess_exec",
                new=record_spawn,
            ):
                request = await _mcp_gap(wired, record)
                assert bridge.registration_attempts == 0
                assert bridge.list_servers() == []
                assert processes == []
                assert await workbench.find_mcp_tool("agent-1", "echo") == []
                assert await workbench.pull_tool("agent-1", "echo", "echo") is False
                with patch.object(
                    wired.requests, "decide", wraps=wired.requests.decide,
                ) as decide:
                    if cancel_at == "restart":
                        with patch.object(
                            mcp_store, "set_enabled",
                            side_effect=RuntimeError("controlled durable enablement failure"),
                        ):
                            first = await approve_over_http()
                        assert first["fulfilled"] is False
                        assert first["request"]["status"] == "approved"
                        assert first["request"]["can_retry_fulfilment"] is True
                        assert bridge.registration_attempts == 1
                        assert len(processes) == 1 and processes[0].returncode is None
                        assert (await mcp_store.get(record.id)).enabled is False
                        assert clients_at_event == [] and wired.router.dispatched == []
                        assert (await wired.work_items.get_work_item(request.work_item_id)).status == "blocked"
                        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
                            pending = await api.get("/api/capability-requests?status=pending")
                            actionable = await api.get("/api/capability-requests/actionable")
                        assert pending.status_code == actionable.status_code == 200
                        assert pending.json()["requests"] == []
                        assert actionable.json()["view"] == "actionable"
                        assert actionable.json()["requests"] == [first["request"]]
                        before_reopen = await wired.requests.get(request.id)
                        await wired.requests.stop()
                        await mcp_store.stop()
                        await mcp_store.start()
                        await wired.requests.start()
                        restored = await wired.requests.get(request.id)
                        assert restored is not before_reopen
                        assert restored.status == "approved" and restored.payload == request.payload
                        assert (await mcp_store.get(record.id)).enabled is False
                        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
                            rediscovered = await api.get("/api/capability-requests/actionable")
                        assert rediscovered.status_code == 200
                        assert rediscovered.json() == actionable.json()
                    elif cancel_at is not None:
                        approval_task = asyncio.create_task(approve_over_http())
                        await asyncio.wait_for(bridge.entered.wait(), timeout=10.0)
                        assert not approval_task.done()
                        assert bridge.registration_attempts == 1
                        current = await wired.requests.get(request.id)
                        assert current is not None and current.status == "approved"
                        enabled = await mcp_store.get(record.id)
                        assert enabled is not None and enabled.enabled is False
                        assert clients_at_event == []
                        if cancel_at == "registered":
                            assert len(processes) == 1 and processes[0].returncode is None
                            assert bridge.get_client(record.name) is not None
                        else:
                            assert processes == []
                            assert bridge.get_client(record.name) is None
                        approval_task.cancel()
                        with pytest.raises(asyncio.CancelledError):
                            await approval_task
                        await wired.bus.drain()
                        assert bridge.list_servers() == ([record.name] if cancel_at == "registered" else [])
                        assert all(process.returncode is None for process in processes), (
                            "a published client remains bridge-owned for exact retry, not registrar cleanup"
                        )
                        current = await wired.requests.get(request.id)
                        assert current is not None and current.status == "approved"
                        blocked = await wired.work_items.get_work_item(request.work_item_id)
                        assert blocked is not None and blocked.status == "blocked"
                        assert wired.router.dispatched == []
                        assert clients_at_event == []
                        bridge.pause_at = None
                    response = await approve_over_http()
                    decide.assert_awaited_once()
                assert response["fulfilled"] is True
                assert response["request"]["status"] == "fulfilled"
                assert response["request"]["can_retry_fulfilment"] is False
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
                    completed = await api.get("/api/capability-requests/actionable")
                assert completed.status_code == 200
                assert completed.json() == {"view": "actionable", "requests": []}
                client = bridge.get_client(record.name)
                assert client is not None
                assert len(processes) == 1, "retry must reuse a published subprocess"
                assert clients_at_event == [client]
                assert bridge.registration_attempts == (1 if cancel_at is None else 2)
                assert wired.bus.emitted.count(EventType.CAPABILITY_REQUEST_FULFILLED.value) == 1
                assert wired.bus.emitted.count(EventType.CAPABILITY_REQUEST_DECIDED.value) == 1
                wired.runtime.trust_network.record_outcome.assert_called_once()
                resumed = await wired.work_items.get_work_item(request.work_item_id)
                assert resumed is not None and resumed.status == "in_progress"
                assert len(wired.router.dispatched) == 1
                assert wired.router.dispatched[0]["data"]["work_item"]["id"] == request.work_item_id
                matches = await workbench.find_mcp_tool("agent-1", "echo back arguments")
                assert [(match["server"], match["tool"]) for match in matches] == [("echo", "echo")]
                assert await workbench.find_mcp_tool("unauthorized-agent", "echo") == []
                assert await workbench.pull_tool("unauthorized-agent", "echo", "echo") is False
                assert await workbench.pull_tool("agent-1", "echo", "echo") is True
                registration = registry.get("mcp:echo:echo")
                assert registration is not None
                with patch.object(bridge, "invoke", wraps=bridge.invoke) as invoke:
                    denied = await registration.tool.invoke(
                        {"q": "denied"}, {"agent_id": "unauthorized-agent"}
                    )
                    assert denied.success is False
                    assert "not authorized" in denied.error
                    invoke.assert_not_awaited()
                    result = await registration.tool.invoke(
                        {"q": "approved"}, {"agent_id": "agent-1"}
                    )
                    assert result.success is True
                    assert result.output["content"][0]["text"] == '{"q": "approved"}'
                    invoke.assert_awaited_once_with("echo", "echo", {"q": "approved"})
                episodes.assert_awaited_once()
                consensus.assert_not_awaited()
                assert bridge.get_client(record.name) is client
                assert await wired.perms.list_grants(active_only=True) == grants_before
                dependency.assert_not_awaited()
        finally:
            if approval_task is not None:
                if not approval_task.done():
                    approval_task.cancel()
                await asyncio.gather(approval_task, return_exceptions=True)
            await bridge.close_all()
            await wired.bus.drain()
        assert bridge.list_servers() == []
        assert processes and all(process.returncode is not None for process in processes)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("replacement_failure", ["spawn-failed", "dead-on-arrival"])
    async def test_dead_stdio_retry_stays_actionable_until_live_replacement(
        self, wired: _Wired, mcp_store: McpServerStore, replacement_failure: str,
    ) -> None:
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from probos.routers.deps import get_runtime

        app = FastAPI()
        app.include_router(router_mod.router)
        app.dependency_overrides[get_runtime] = lambda: wired.runtime
        fixture = Path(__file__).parent / "fixtures" / "echo_mcp_server.py"
        assert fixture.is_file()
        bridge = _PausingMcpBridge(None)
        registry = ToolRegistry()
        wired.runtime.mcp_server_store = mcp_store
        wired.runtime.mcp_bridge = bridge
        wired.runtime.tool_registry = registry
        dependency = AsyncMock()
        wired.runtime.ensure_dependency = dependency
        record = await mcp_store.create(McpServerRecord(
            name="echo", type="stdio", command=sys.executable,
            args=[str(fixture)], timeout_seconds=5.0, enabled=False,
            default_risk="open",
        ))
        await wired.perms.issue_grant(
            "agent-1", "mcp:echo:echo", ToolPermission.WRITE,
            reason="independent pre-existing tool grant",
        )
        grants_before = await wired.perms.list_grants(active_only=True)
        assert len(grants_before) == 1
        consensus = AsyncMock(side_effect=AssertionError("open echo requires no consensus"))
        episodes = AsyncMock()
        workbench = MCPWorkbench(
            tool_registry=registry, bridge=bridge, consensus_invoke=consensus,
            episode_writer=episodes, server_store=mcp_store, perm_store=wired.perms,
            dept_grant_store=None, risk_store=None, ontology=None, agent_registry=None,
        )
        clients_at_event: list[object | None] = []
        wired.bus.on_fulfilled = lambda: clients_at_event.append(bridge.get_client(record.name))
        processes: list[asyncio.subprocess.Process] = []
        spawn = asyncio.create_subprocess_exec
        mode: str | None = None
        spawn_attempts = 0

        async def record_spawn(*args: Any, **kwargs: Any) -> asyncio.subprocess.Process:
            nonlocal spawn_attempts
            spawn_attempts += 1
            if mode == "spawn-failed":
                raise FileNotFoundError("controlled replacement spawn failure")
            process = await spawn(*args, **kwargs)
            processes.append(process)
            if mode == "dead-on-arrival":
                process.terminate()
                await asyncio.wait_for(process.wait(), timeout=10.0)
                assert process.returncode is not None
            return process

        async def fail_enable(server_id: str, enabled: bool) -> McpServerRecord | None:
            assert server_id == record.id and enabled is True
            assert len(processes) == 1 and processes[0].returncode is None
            result = await bridge.invoke(record.name, "echo", {"q": "before failure"})
            assert result["content"][0]["text"] == '{"q": "before failure"}'
            raise OSError("controlled durable enablement failure")

        async def approve_over_http() -> dict[str, Any]:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
                response = await api.post(
                    f"/api/capability-requests/{request.id}/decide", json={"approve": True},
                )
            assert response.status_code == 200
            await wired.bus.drain()
            return response.json()

        async def assert_still_actionable(response: dict[str, Any]) -> None:
            assert response["fulfilled"] is False
            assert response["request"]["status"] == "approved"
            assert response["request"]["can_retry_fulfilment"] is True
            assert (await mcp_store.get(record.id)).enabled is False
            assert (await wired.requests.get(request.id)).status == "approved"
            assert (await wired.work_items.get_work_item(request.work_item_id)).status == "blocked"
            assert clients_at_event == [] and wired.router.dispatched == []
            assert wired.bus.emitted.count(EventType.CAPABILITY_REQUEST_FULFILLED.value) == 0
            assert wired.bus.emitted.count(EventType.CAPABILITY_REQUEST_DECIDED.value) == 1
            wired.runtime.trust_network.record_outcome.assert_called_once()
            assert await wired.perms.list_grants(active_only=True) == grants_before
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
                actionable = await api.get("/api/capability-requests/actionable")
            assert actionable.status_code == 200
            assert actionable.json() == {"view": "actionable", "requests": [response["request"]]}

        try:
            with patch(
                "probos.integrations.mcp_bridge.transport.asyncio.create_subprocess_exec",
                new=record_spawn,
            ), patch.object(wired.requests, "decide", wraps=wired.requests.decide) as decide:
                request = await _mcp_gap(wired, record)
                assert processes == [] and bridge.list_servers() == []
                with patch.object(mcp_store, "set_enabled", side_effect=fail_enable) as enable:
                    first = await approve_over_http()
                    enable.assert_awaited_once_with(record.id, True)
                await assert_still_actionable(first)
                original = bridge.get_client(record.name)
                assert original is not None
                assert len(processes) == 1 and processes[0].returncode is None
                processes[0].terminate()
                await asyncio.wait_for(processes[0].wait(), timeout=10.0)
                assert processes[0].returncode is not None
                assert bridge.get_client(record.name) is original

                mode = replacement_failure
                with patch.object(mcp_store, "set_enabled", wraps=mcp_store.set_enabled) as enable:
                    failed_retry = await approve_over_http()
                    await assert_still_actionable(failed_retry)
                    enable.assert_not_awaited()
                assert failed_retry["request"] == first["request"]
                assert spawn_attempts == 2
                assert len(processes) == (2 if replacement_failure == "dead-on-arrival" else 1)
                assert all(process.returncode is not None for process in processes)
                assert bridge.get_client(record.name) is None
                await wired.requests.stop()
                await mcp_store.stop()
                await mcp_store.start()
                await wired.requests.start()
                await assert_still_actionable(failed_retry)

                mode = None
                response = await approve_over_http()
                decide.assert_awaited_once()
                assert response["fulfilled"] is True
                assert response["request"]["status"] == "fulfilled"
                assert response["request"]["can_retry_fulfilment"] is False
                client = bridge.get_client(record.name)
                assert client is not None and client is not original and client.is_alive is True
                assert spawn_attempts == bridge.registration_attempts == 3
                assert processes[-1].returncode is None
                assert clients_at_event == [client]
                assert (await mcp_store.get(record.id)).enabled is True
                assert wired.bus.emitted.count(EventType.CAPABILITY_REQUEST_FULFILLED.value) == 1
                assert wired.bus.emitted.count(EventType.CAPABILITY_REQUEST_DECIDED.value) == 1
                wired.runtime.trust_network.record_outcome.assert_called_once()
                resumed = await wired.work_items.get_work_item(request.work_item_id)
                assert resumed is not None and resumed.status == "in_progress"
                assert len(wired.router.dispatched) == 1
                assert wired.router.dispatched[0]["data"]["work_item"]["id"] == request.work_item_id
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
                    completed = await api.get("/api/capability-requests/actionable")
                assert completed.status_code == 200
                assert completed.json() == {"view": "actionable", "requests": []}

                matches = await workbench.find_mcp_tool("agent-1", "echo back arguments")
                assert [(match["server"], match["tool"]) for match in matches] == [("echo", "echo")]
                assert await workbench.find_mcp_tool("unauthorized-agent", "echo") == []
                assert await workbench.pull_tool("unauthorized-agent", "echo", "echo") is False
                assert await workbench.pull_tool("agent-1", "echo", "echo") is True
                registration = registry.get("mcp:echo:echo")
                assert registration is not None
                with patch.object(bridge, "invoke", wraps=bridge.invoke) as invoke:
                    denied = await registration.tool.invoke(
                        {"q": "denied"}, {"agent_id": "unauthorized-agent"},
                    )
                    assert denied.success is False and "not authorized" in denied.error
                    invoke.assert_not_awaited()
                    result = await registration.tool.invoke(
                        {"q": "replacement"}, {"agent_id": "agent-1"},
                    )
                    assert result.success is True
                    assert result.output["content"][0]["text"] == '{"q": "replacement"}'
                    invoke.assert_awaited_once_with("echo", "echo", {"q": "replacement"})
                episodes.assert_awaited_once()
                consensus.assert_not_awaited()
                dependency.assert_not_awaited()
                assert bridge.get_client(record.name) is client and client.is_alive is True
                assert await wired.perms.list_grants(active_only=True) == grants_before
        finally:
            try:
                await bridge.close_all()
                await wired.bus.drain()
                assert bridge.list_servers() == []
                assert all(process.returncode is not None for process in processes)
            finally:
                for process in processes:
                    if process.returncode is None:
                        process.terminate()
                        await asyncio.wait_for(process.wait(), timeout=10.0)


@pytest.mark.parametrize("change", ["unchanged", "rename", "delete"])
async def test_real_mcp_identity_survives_restart_and_name_collision(
    wired: _Wired, mcp_store: McpServerStore, change: str,
) -> None:
    bridge = MCPBridge()
    wired.runtime.mcp_server_store = mcp_store
    wired.runtime.mcp_bridge = bridge
    dependency = AsyncMock(side_effect=AssertionError("MCP provenance must not reach pip"))
    wired.runtime.ensure_dependency = dependency
    wanted = await mcp_store.create(McpServerRecord(
        name="wanted", type="http", url="https://example.test/wanted", enabled=False,
    ))
    masking = await mcp_store.create(McpServerRecord(
        name=wanted.id, type="http", url="https://example.test/masking", enabled=False,
    ))
    try:
        assert masking.name == wanted.id and masking.id != wanted.id
        request = await _mcp_gap(wired, wanted)
        assert request.payload == {"install_kind": "mcp", "mcp_server_id": wanted.id}
        await wired.bus.drain()
        await wired.requests.stop()
        await wired.requests.start()
        assert (await wired.requests.get(request.id)).payload == request.payload
        if change == "rename":
            renamed = await mcp_store.update(wanted.id, name="renamed")
            assert renamed is not None and renamed.id == wanted.id
        elif change == "delete":
            assert await mcp_store.delete(wanted.id) is True
        response = await _approve(wired, request.id)
        assert response["fulfilled"] == (change != "delete")
        assert bridge.get_client(masking.url) is None
        assert (await mcp_store.get(masking.id)).enabled is False
        assert (bridge.get_client(wanted.url) is not None) == (change != "delete")
        assert len(wired.router.dispatched) == (0 if change == "delete" else 1)
        assert wired.bus.emitted.count(EventType.CAPABILITY_REQUEST_FULFILLED.value) == (0 if change == "delete" else 1)
        dependency.assert_not_awaited()
    finally:
        await wired.bus.drain()
        await bridge.close_all()


async def test_name_selected_mcp_rename_cannot_transfer_approval(
    wired: _Wired, mcp_store: McpServerStore,
) -> None:
    bridge = MCPBridge()
    wired.runtime.mcp_bridge = bridge
    wired.runtime.mcp_server_store = mcp_store
    dependency = AsyncMock(side_effect=AssertionError("MCP request diverted to pip"))
    wired.runtime.ensure_dependency = dependency
    selected = await mcp_store.create(McpServerRecord(
        name="selected-name", type="http", url="https://example.test/original", enabled=False,
    ))
    try:
        request = await capability_triage.triage_and_file(
            gap_target=selected.name, agent_id="agent-1", store=wired.requests,
            mcp_server_store=mcp_store,
        )
        assert request.payload == {"install_kind": "mcp", "mcp_server_id": selected.id}
        renamed = await mcp_store.update(selected.id, name="renamed")
        assert renamed is not None and renamed.name != request.target
        replacement = await mcp_store.create(McpServerRecord(
            name=selected.name, type="http", url="https://example.test/replacement", enabled=False,
        ))
        response = await _approve(wired, request.id)
        assert response["fulfilled"] is True
        assert bridge.get_client(selected.url) is not None
        assert bridge.get_client(replacement.url) is None
        assert (await mcp_store.get(selected.id)).enabled is True
        assert (await mcp_store.get(replacement.id)).enabled is False
        dependency.assert_not_awaited()
    finally:
        await wired.bus.drain()
        await bridge.close_all()


@pytest.mark.parametrize("failure", ["enable-error", "enable-cancel", "after-enable-cancel", "fulfil-error", "fulfil-cancel"])
async def test_published_http_client_survives_persistence_failure_or_cancellation(
    wired: _Wired, mcp_store: McpServerStore, failure: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = MCPBridge()
    wired.runtime.mcp_bridge = bridge
    wired.runtime.mcp_server_store = mcp_store
    dependency = AsyncMock(side_effect=AssertionError("MCP request diverted to pip"))
    wired.runtime.ensure_dependency = dependency
    record = await mcp_store.create(McpServerRecord(
        name="persist-retry", type="http", url="https://example.test/persist", enabled=False,
    ))
    set_enabled = mcp_store.set_enabled
    mark_fulfilled = wired.requests.mark_fulfilled

    async def fail_enable(server_id: str, enabled: bool) -> McpServerRecord | None:
        assert server_id == record.id and enabled is True
        assert bridge.get_client(record.url) is not None
        if failure == "after-enable-cancel":
            await set_enabled(server_id, enabled)
        if "cancel" in failure:
            raise asyncio.CancelledError()
        raise OSError("enablement unavailable")

    async def fail_fulfil(request_id: str) -> CapabilityRequest | None:
        assert bridge.get_client(record.url) is not None
        assert (await mcp_store.get(record.id)).enabled is True
        if "cancel" in failure:
            raise asyncio.CancelledError()
        raise OSError("fulfilment unavailable")

    try:
        request = await _mcp_gap(wired, record)
        if failure.startswith("fulfil"):
            monkeypatch.setattr(wired.requests, "mark_fulfilled", fail_fulfil)
        else:
            monkeypatch.setattr(mcp_store, "set_enabled", fail_enable)
        if "cancel" in failure:
            with pytest.raises(asyncio.CancelledError):
                await _approve(wired, request.id)
        else:
            assert (await _approve(wired, request.id))["fulfilled"] is False
        await wired.bus.drain()
        published = bridge.get_client(record.url)
        assert published is not None
        assert (await wired.requests.get(request.id)).status == "approved"
        durable_enabled = failure.startswith("fulfil") or failure == "after-enable-cancel"
        await mcp_store.stop()
        await mcp_store.start()
        assert (await mcp_store.get(record.id)).enabled == durable_enabled
        assert wired.router.dispatched == []
        assert EventType.CAPABILITY_REQUEST_FULFILLED.value not in wired.bus.emitted
        monkeypatch.setattr(mcp_store, "set_enabled", set_enabled)
        monkeypatch.setattr(wired.requests, "mark_fulfilled", mark_fulfilled)
        response = await _approve(wired, request.id)
        assert response["fulfilled"] is True
        assert bridge.get_client(record.url) is published
        assert len(wired.router.dispatched) == 1
        assert wired.bus.emitted.count(EventType.CAPABILITY_REQUEST_DECIDED.value) == 1
        assert wired.bus.emitted.count(EventType.CAPABILITY_REQUEST_FULFILLED.value) == 1
        wired.runtime.trust_network.record_outcome.assert_called_once()
        dependency.assert_not_awaited()
    finally:
        await wired.bus.drain()
        await bridge.close_all()


# ══ 3. INSTALL: the Captain is asked exactly once ══════════════════════════


class TestInstallDoesNotAskTwice:
    @pytest.mark.asyncio
    async def test_the_approval_callback_is_never_invoked(self, wired):
        """The trap this AD had to avoid.

        ``ensure_dependency`` carries its own gate: unlisted imports go to
        ``resolver._approval_fn`` under ``prompt_unlisted``. Routing a
        Captain-approved install straight there asks the same human for the
        same package a second time — and they would have found that out live.
        """
        # Arrange — a REAL callback, wired exactly as the shell wires it.
        approval = AsyncMock(return_value=True)
        state: dict[str, bool] = {"installed": False}
        wired.runtime.dependency_resolver = _install_resolver(
            state, approval_fn=approval, allowed=[]
        )
        _item, req = await _blocked_on(wired, kind="install", target=_PKG)

        # Act
        with _find_spec_after_install(state):
            response = await _approve(wired, req.id)

        # Assert — installed, fulfilled, and NOT asked again.
        assert response["fulfilled"] is True
        assert state["installed"] is True
        approval.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_callback_wired_no_longer_refuses_an_approved_install(
        self, wired
    ):
        """The no-callback refusal exists because nobody could be asked.

        When the answer is already on record, refusing discards it and strands
        the work item. Every OTHER caller still hits the refusal — see
        ``test_an_unapproved_install_is_still_refused_without_a_callback``.
        """
        # Arrange — unlisted package, no approval callback at all.
        state: dict[str, bool] = {"installed": False}
        wired.runtime.dependency_resolver = _install_resolver(state, allowed=[])
        item, req = await _blocked_on(wired, kind="install", target=_PKG)

        # Act
        with _find_spec_after_install(state):
            response = await _approve(wired, req.id)

        # Assert
        assert response["fulfilled"] is True
        assert state["installed"] is True
        resumed = await wired.work_items.get_work_item(item.id)
        assert resumed is not None and resumed.status == "in_progress"

    @pytest.mark.asyncio
    async def test_an_unapproved_install_is_still_refused_without_a_callback(self):
        """AD-838c's defense in depth is intact for every other caller.

        ``pre_approved`` defaults to ``False``, so nothing that does not opt in
        can install an unlisted package silently.
        """
        # Arrange
        install = AsyncMock(return_value=(True, "ok"))
        runtime = SimpleNamespace(
            dependency_resolver=DependencyResolver(
                allowed_imports=[], install_fn=install, policy="prompt_unlisted"
            ),
            event_log=_EventLog(),
            config=SimpleNamespace(
                self_mod=SimpleNamespace(allowed_imports=[]),
                # AD-1222: empty tier == nothing auto-approves, which is what
                # this case has always meant.
                dependency=SimpleNamespace(auto_approve_imports=[]),
            ),
        )

        # Act
        with patch(
            "probos.cognitive.dependency_resolver.importlib.util.find_spec",
            return_value=None,
        ):
            result = await ProbOSRuntime.ensure_dependency(runtime, _PKG)

        # Assert
        assert result.success is False
        assert result.declined == [_PKG]
        assert "approval callback unavailable" in (result.error or "")
        install.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_normal_caller_is_still_asked(self):
        """The default path is byte-identical: the callback still runs."""
        # Arrange
        approval = AsyncMock(return_value=False)
        install = AsyncMock(return_value=(True, "ok"))
        runtime = SimpleNamespace(
            dependency_resolver=DependencyResolver(
                allowed_imports=[_PKG],
                install_fn=install,
                approval_fn=approval,
                policy="prompt_unlisted",
            ),
            event_log=_EventLog(),
            config=SimpleNamespace(
                self_mod=SimpleNamespace(allowed_imports=[_PKG]),
                # AD-1222: mirrors the resolver's own allowlist, so this case
                # still exercises "the callback still runs" and nothing else.
                dependency=SimpleNamespace(auto_approve_imports=[_PKG]),
            ),
        )

        # Act
        with patch(
            "probos.cognitive.dependency_resolver.importlib.util.find_spec",
            return_value=None,
        ):
            result = await ProbOSRuntime.ensure_dependency(runtime, _PKG)

        # Assert
        approval.assert_awaited_once()
        assert result.success is False
        install.assert_not_awaited()


# ══ 4. BUILD: the whole chain ══════════════════════════════════════════════


class TestBuildChain:
    @pytest.mark.asyncio
    async def test_approving_a_build_runs_the_pipeline_and_unblocks_the_item(
        self, wired
    ):
        """route -> handle_unhandled_intent -> mark_fulfilled -> resume."""
        # Arrange
        self_mod = _SelfMod(SimpleNamespace(status="active"))
        wired.runtime.self_mod_pipeline = self_mod
        item, req = await _blocked_on(wired, kind="build", target="WeatherAgent")

        # Act
        response = await _approve(wired, req.id)

        # Assert — the pipeline saw the target AND the rationale...
        assert self_mod.calls == [("WeatherAgent", req.rationale)]
        # ...and the chain completed.
        assert response["fulfilled"] is True
        stored = await wired.requests.get(req.id)
        assert stored is not None and stored.status == "fulfilled"
        assert EventType.CAPABILITY_REQUEST_FULFILLED.value in wired.bus.emitted
        resumed = await wired.work_items.get_work_item(item.id)
        assert resumed is not None and resumed.status == "in_progress"
        assert len(wired.router.dispatched) == 1

    @pytest.mark.parametrize("status", ["rejected", "shape_rejected", "max_limit"])
    @pytest.mark.asyncio
    async def test_a_non_active_record_does_not_fulfil_and_stays_retriable(
        self, wired, status
    ):
        """Only ``active`` means an agent exists. Anything else is not built."""
        # Arrange
        wired.runtime.self_mod_pipeline = _SelfMod(SimpleNamespace(status=status))
        item, req = await _blocked_on(wired, kind="build", target="WeatherAgent")

        # Act
        response = await _approve(wired, req.id)

        # Assert
        assert response["fulfilled"] is False
        stored = await wired.requests.get(req.id)
        assert stored is not None and stored.status == "approved"
        assert EventType.CAPABILITY_REQUEST_FULFILLED.value not in wired.bus.emitted
        blocked = await wired.work_items.get_work_item(item.id)
        assert blocked is not None and blocked.status == "blocked"

    @pytest.mark.asyncio
    async def test_a_none_record_does_not_fulfil(self, wired):
        """The pipeline returns ``None`` on any failed step."""
        # Arrange
        wired.runtime.self_mod_pipeline = _SelfMod(None)
        _item, req = await _blocked_on(wired, kind="build", target="WeatherAgent")

        # Act
        response = await _approve(wired, req.id)

        # Assert
        assert response["fulfilled"] is False

    @pytest.mark.asyncio
    async def test_no_pipeline_is_reported_honestly(self, wired):
        """Self-modification disabled: say so rather than claiming a build."""
        # Arrange — the fixture default: ``self_mod_pipeline=None``.
        item, req = await _blocked_on(wired, kind="build", target="WeatherAgent")

        # Act
        response = await _approve(wired, req.id)

        # Assert
        assert response["fulfilled"] is False
        blocked = await wired.work_items.get_work_item(item.id)
        assert blocked is not None and blocked.status == "blocked"

    @pytest.mark.asyncio
    async def test_a_retry_after_a_failed_build_fulfils_and_unblocks(self, wired):
        """A build that failed once can be approved again and complete."""
        # Arrange
        wired.runtime.self_mod_pipeline = _SelfMod(SimpleNamespace(status="rejected"))
        item, req = await _blocked_on(wired, kind="build", target="WeatherAgent")
        assert (await _approve(wired, req.id))["fulfilled"] is False

        # Act
        wired.runtime.self_mod_pipeline = _SelfMod(SimpleNamespace(status="active"))
        second = await _approve(wired, req.id)

        # Assert
        assert second["fulfilled"] is True
        resumed = await wired.work_items.get_work_item(item.id)
        assert resumed is not None and resumed.status == "in_progress"
        assert len(wired.router.dispatched) == 1


# ══ 5. A fulfiller that raises ═════════════════════════════════════════════


class TestARaisingFulfillerIsContained:
    @pytest.mark.asyncio
    async def test_it_leaves_the_request_approved_and_retriable(self, wired):
        """The route returns 200 and says ``fulfilled=False`` (BF-722)."""
        # Arrange
        wired.runtime.self_mod_pipeline = _RaisingSelfMod()
        item, req = await _blocked_on(wired, kind="build", target="WeatherAgent")

        # Act
        response = await _approve(wired, req.id)

        # Assert — nothing was claimed, and the card is still retriable.
        assert response["fulfilled"] is False
        stored = await wired.requests.get(req.id)
        assert stored is not None and stored.status == "approved"
        assert stored.decided_by == "captain"
        assert EventType.CAPABILITY_REQUEST_FULFILLED.value not in wired.bus.emitted
        blocked = await wired.work_items.get_work_item(item.id)
        assert blocked is not None and blocked.status == "blocked"

        # Act — the retry, with the pipeline healthy.
        wired.runtime.self_mod_pipeline = _SelfMod(SimpleNamespace(status="active"))
        second = await _approve(wired, req.id)

        # Assert
        assert second["fulfilled"] is True
        resumed = await wired.work_items.get_work_item(item.id)
        assert resumed is not None and resumed.status == "in_progress"

    @pytest.mark.asyncio
    async def test_a_raising_permission_store_does_not_mark_fulfilled(self, wired):
        """The failure must land BEFORE ``mark_fulfilled``, not after."""
        # Arrange
        class _Raising:
            async def issue_grant(self, *_a: Any, **_kw: Any) -> Any:
                raise RuntimeError("AD-1211: simulated grant failure")

        wired.runtime.tool_permission_store = _Raising()
        _item, req = await _blocked_on(wired, kind="grant", target="calc_tool")

        # Act
        response = await _approve(wired, req.id)

        # Assert
        assert response["fulfilled"] is False
        stored = await wired.requests.get(req.id)
        assert stored is not None and stored.status == "approved"
        assert EventType.CAPABILITY_REQUEST_FULFILLED.value not in wired.bus.emitted


# ══ 6. Denial is unchanged ═════════════════════════════════════════════════


class TestDenialStillCancels:
    @pytest.mark.parametrize("kind", ["grant", "install", "build"])
    @pytest.mark.asyncio
    async def test_denying_cancels_the_work_item_and_fulfils_nothing(
        self, wired, kind
    ):
        """The DECIDED path (AD-855) is untouched by this AD."""
        # Arrange — a fulfiller that would succeed if it were ever reached.
        wired.runtime.self_mod_pipeline = _SelfMod(SimpleNamespace(status="active"))
        wired.runtime.tool_registry = _ToolRegistry(
            {"calc_tool": _registration({"ensign": "read"})}
        )
        state: dict[str, bool] = {"installed": False}
        wired.runtime.dependency_resolver = _install_resolver(state)
        target = {"grant": "calc_tool", "install": _PKG, "build": "WeatherAgent"}[kind]
        item, req = await _blocked_on(wired, kind=kind, target=target)

        # Act
        with _find_spec_after_install(state):
            response = await _approve(wired, req.id, approve=False)

        # Assert — denied, nothing fulfilled, nothing performed.
        assert response["fulfilled"] is False
        assert response["request"]["status"] == "denied"
        assert EventType.CAPABILITY_REQUEST_FULFILLED.value not in wired.bus.emitted
        assert state["installed"] is False
        assert wired.perms.get_active_grants_sync("agent-1", "calc_tool") == []
        # ...and the work item was cancelled off the DECIDED event.
        cancelled = await wired.work_items.get_work_item(item.id)
        assert cancelled is not None and cancelled.status == "cancelled"
        assert wired.router.dispatched == []


# ══ 7. ``action`` has no fulfiller, deliberately ═══════════════════════════


class TestActionIsNotFulfilledHere:
    def test_the_dispatcher_has_no_entry_for_action(self):
        """#1166 owns the action contract: standing grant only, no replay."""
        # Assert
        assert "action" not in _APPROVAL_FULFILLERS
        assert sorted(_APPROVAL_FULFILLERS) == ["build", "continue", "grant", "install"]

    @pytest.mark.asyncio
    async def test_approving_an_action_records_the_decision_and_no_more(self, wired):
        """An approved action authorises the NEXT one, never replays this one."""
        # Arrange
        item, req = await _blocked_on(wired, kind="action", target="browser.click")

        # Act
        response = await _approve(wired, req.id)

        # Assert
        assert response["fulfilled"] is False
        assert response["request"]["status"] == "approved"
        assert EventType.CAPABILITY_REQUEST_FULFILLED.value not in wired.bus.emitted
        blocked = await wired.work_items.get_work_item(item.id)
        assert blocked is not None and blocked.status == "blocked"


# ══ 8. One fulfiller, two callers ══════════════════════════════════════════


class TestTheFulfillersAreSharedNotCopied:
    """Two copies of "how a grant is issued" is the defect this epic keeps
    finding. The fast path and the approval path must call one function."""

    def test_the_router_calls_the_same_objects_the_fast_path_defines(self):
        # Assert — identity, not merely same-named.
        assert router_mod.fulfil_grant is capability_triage.fulfil_grant
        assert router_mod.fulfil_build is capability_triage.fulfil_build
        assert router_mod.fulfil_install is capability_triage.fulfil_install

    @pytest.mark.asyncio
    async def test_the_fast_path_routes_through_the_extracted_grant_fulfiller(
        self, wired, monkeypatch
    ):
        """Patching the extracted name diverts the FILE-time path too.

        If ``_route_grant`` still carried its own inline ``issue_grant`` +
        ``mark_fulfilled``, this patch would not be reached and the assertion
        would fail — which is what makes it evidence of the extraction rather
        than a restatement of it.
        """
        # Arrange
        seen: list[str] = []

        async def _spy(request_id: str, **kwargs: Any) -> Any:
            seen.append(kwargs["tool_id"])
            return None

        monkeypatch.setattr(capability_triage, "fulfil_grant", _spy)
        # The fast path only reaches a fulfiller when an in-department peer
        # already holds the grant, so seed that precedent.
        await wired.perms.issue_grant(
            "peer-agent", "calc_tool", ToolPermission.READ, reason="seed precedent"
        )
        req = await wired.requests.file_request(
            agent_id="requester", kind="grant", target="calc_tool"
        )

        # Act
        await capability_triage._route_grant(
            req,
            store=wired.requests,
            agent_id="requester",
            tool_id="calc_tool",
            tool_registration=_registration({"ensign": "read"}),
            permission_store=wired.perms,
            ontology=SimpleNamespace(
                get_agent_department=lambda _a: "science"
            ),
            trust_network=SimpleNamespace(get_score=lambda _a: 1.0),
            config=SimpleNamespace(
                grant_fast_path_enabled=True, grant_trust_floor=0.0
            ),
        )

        # Assert
        assert seen == ["calc_tool"]

    @pytest.mark.asyncio
    async def test_the_fast_path_routes_through_the_extracted_build_fulfiller(
        self, wired, monkeypatch
    ):
        # Arrange
        seen: list[str] = []

        async def _spy(request_id: str, **kwargs: Any) -> Any:
            seen.append(kwargs["gap_target"])
            return None

        monkeypatch.setattr(capability_triage, "fulfil_build", _spy)
        req = await wired.requests.file_request(
            agent_id="requester", kind="build", target="WeatherAgent"
        )

        # Act
        await capability_triage._route_build(
            req,
            store=wired.requests,
            gap_target="WeatherAgent",
            rationale="needs forecast",
            self_mod_pipeline=_SelfMod(SimpleNamespace(status="active")),
        )

        # Assert
        assert seen == ["WeatherAgent"]
