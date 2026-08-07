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
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.api_models import CapabilityRequestDecideRequest
from probos.capability_request import CapabilityRequestStore
from probos.cognitive import capability_triage
from probos.cognitive.capability_gap_driver import CapabilityGapDriver
from probos.cognitive.dependency_resolver import DependencyResolver
from probos.events import EventType
from probos.routers import capability_requests as router_mod
from probos.routers.capability_requests import (
    _APPROVAL_FULFILLERS,
    decide_capability_request,
)
from probos.runtime import ProbOSRuntime
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolPermission
from probos.workforce import WorkItemStore

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

    def add_event_listener(self, fn: Any) -> None:
        self._listeners.append(fn)

    def emit(self, event_type: Any, data: dict[str, Any]) -> None:
        type_str = str(getattr(event_type, "value", event_type))
        self.emitted.append(type_str)
        event = {"type": type_str, "data": dict(data or {}), "timestamp": time.time()}
        for fn in self._listeners:
            task = asyncio.create_task(fn(event))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        """Await every listener task, including ones they spawn in turn."""
        while self._tasks:
            await asyncio.gather(*tuple(self._tasks))


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
        self, intent_name: str, description: str, _params: dict[str, str]
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
    requests = CapabilityRequestStore(
        db_path=str(tmp_path / "cap.db"), emit_event=bus.emit
    )
    await requests.start()
    router = _RecordingRouter()
    runtime = _Runtime(
        work_item_router=router,
        work_item_store=work_items,
        capability_request_store=requests,
        tool_permission_store=perms,
        tool_registry=_ToolRegistry({}),
        self_mod_pipeline=None,
        dependency_resolver=None,
        event_log=_EventLog(),
        config=SimpleNamespace(self_mod=SimpleNamespace(allowed_imports=[])),
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
            config=SimpleNamespace(self_mod=SimpleNamespace(allowed_imports=[])),
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
            config=SimpleNamespace(self_mod=SimpleNamespace(allowed_imports=[_PKG])),
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
