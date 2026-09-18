"""AD-1220 (#1181): a missing library files an install request the Captain can see.

The Captain asked why the sandbox cannot install other Python libraries. The
machinery was already complete — AD-838c built approval-gated install, AD-1073
wired it into the sandbox, AD-1178 made the missing set legible, and AD-1211
made ``fulfil_install`` call straight back into ``ensure_dependency`` with
``pre_approved=True``. Every piece worked. Nothing connected them.

``runtime.dependency_resolver._approval_fn`` is assigned in exactly ONE place —
``experience/shell.py:163`` — and what it wires is a **Rich console prompt**.
On the HXI/API vessel the callback is ``None``, so ``ensure_dependency`` took
the hard-decline branch and stopped. No ``install`` capability request was ever
filed, so the Captain was never shown the choice that ``fulfil_install`` was
waiting to act on.

That is this repo's most-repeated defect shape: the producer fires, the
consumer works, and nothing crosses the seam. So the headline test here is the
CROSSING one — missing import, request filed, Captain approves, package
installs — not a test of either half.

Design points worth pinning:

* **Attribution is required, not defaulted.** An unattributed install request
  cannot answer the only question that matters when approving one: who wants
  this, and for what. With no requester the ask is skipped and the previous
  decline-only behaviour stands.
* **Dedup by (agent, target).** A script that fails the same import on every
  run must not bury the Captain under identical cards.
* **``pre_approved`` must never file.** That is ``fulfil_install`` re-entering
  after the Captain already said yes; filing there would loop.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import sqlite3
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.capability_request import CapabilityRequestStore, validate_python_install_target
from probos.cognitive.dependency_resolver import DependencyResolver, DependencyResult
from probos.events import EventType
from probos.integrations.mcp_bridge import MCPBridge
from probos.integrations.mcp_bridge.store import McpServerRecord, McpServerStore
from probos.runtime import ProbOSRuntime, file_dependency_install_requests
from tests.test_ad1211_approval_fulfils_every_kind import _approve, wired


@pytest.mark.asyncio
@pytest.mark.parametrize("mcp_enabled", [None, False, True], ids=["no-collision", "disabled", "enabled"])
async def test_review_regression_package_approval_ignores_mcp_name_collision(
    wired, mcp_enabled: bool | None,
) -> None:
    from probos.runtime import file_dependency_install_requests
    from tests.test_ad1215_install_rung_mcp import (
        _FakeBridge,
        _McpRecord,
        _McpServerStore,
    )

    records = [] if mcp_enabled is None else [
        _McpRecord(id="package-collision", name="feedparser", enabled=mcp_enabled)
    ]
    mcp = _McpServerStore(records)
    bridge = _FakeBridge()
    wired.runtime.mcp_server_store = mcp
    wired.runtime.mcp_bridge = bridge
    ensure_calls: list[tuple[str, bool]] = []
    filed = await file_dependency_install_requests(
        wired.requests, ["feedparser"], "agent-1"
    )
    assert filed == ["feedparser"]
    pending = await wired.requests.list_pending()
    assert len(pending) == 1
    request = pending[0]
    assert (request.kind, request.target, request.status) == (
        "install", "feedparser", "pending"
    )
    assert mcp.list_sync() == records
    assert bridge.clients == {}

    async def ensure_dependency(
        target: str, *, pre_approved: bool = False,
    ) -> DependencyResult:
        approved = await wired.requests.get(request.id)
        assert approved is not None and approved.status == "approved"
        ensure_calls.append((target, pre_approved))
        return DependencyResult(success=True, installed=[target])

    wired.runtime.ensure_dependency = ensure_dependency
    await _approve(wired, request.id)

    result = await wired.requests.get(request.id)
    assert result is not None and result.status == "fulfilled"
    assert ensure_calls == [("feedparser", True)]
    assert mcp.set_enabled_calls == []
    assert mcp.list_sync() == records
    assert bridge.register_calls == []
    assert bridge.unregister_calls == []
    assert bridge.clients == {}


class _Resolver:
    """Stands in for DependencyResolver with no approval callback wired —
    the state of every API/HXI vessel."""

    def __init__(self, missing: list[str], *, approval_fn: Any = None) -> None:
        self._missing = missing
        self._approval_fn = approval_fn
        self.resolved: list[str] = []

    def detect_missing(self, source: str) -> list[str]:
        return list(self._missing)

    async def resolve(self, source: str, *, pre_approved: bool = False):
        self.resolved.append(source)
        return DependencyResult(success=True, installed=list(self._missing))


def _runtime(store: CapabilityRequestStore | None, resolver: Any) -> Any:
    """Minimal stand-in carrying only what ensure_dependency reads."""
    return SimpleNamespace(
        config=SimpleNamespace(
            dependency=SimpleNamespace(
                dynamic_install_enabled=True,
                # AD-1222: the auto-approve tier is declared here now, not
                # borrowed from self_mod.allowed_imports.
                auto_approve_imports=["json", "os"],
            ),
            self_mod=SimpleNamespace(allowed_imports=["json", "os"]),
        ),
        dependency_resolver=resolver,
        capability_request_store=store,
        event_log=None,
    )


async def _store(tmp_path) -> CapabilityRequestStore:
    store = CapabilityRequestStore(db_path=str(tmp_path / "reqs.db"))
    await store.start()
    return store


@pytest.fixture
async def request_store(tmp_path: Path) -> AsyncIterator[CapabilityRequestStore]:
    store = await _store(tmp_path)
    try:
        yield store
    finally:
        await store.stop()


# ── (1) the gap this closes: the ask is filed, not swallowed ───────────────
@pytest.mark.asyncio
async def test_no_approver_files_an_install_request(request_store: CapabilityRequestStore) -> None:
    """The headline. Before AD-1220 this branch declined and told nobody."""
    store = request_store
    rt = _runtime(store, _Resolver(["matplotlib"]))

    result = await ProbOSRuntime.ensure_dependency(
        rt, "matplotlib", requested_by="counselor_0"
    )

    assert not result.success
    assert result.declined == ["matplotlib"]
    pending = await store.list_pending()
    assert [(r.kind, r.target, r.agent_id) for r in pending] == [
        ("install", "matplotlib", "counselor_0")
    ]


@pytest.mark.asyncio
async def test_the_error_says_approval_was_requested_not_unavailable(
    request_store: CapabilityRequestStore,
) -> None:
    """The old wording ('approval callback unavailable') described the vessel's
    plumbing. The agent needs to know an ask is now pending, because that is
    what determines whether waiting is worth anything."""
    store = request_store
    rt = _runtime(store, _Resolver(["matplotlib"]))

    result = await ProbOSRuntime.ensure_dependency(
        rt, "matplotlib", requested_by="counselor_0"
    )

    assert result.error == "approval requested"


@pytest.mark.asyncio
async def test_one_request_per_missing_package(request_store: CapabilityRequestStore) -> None:
    store = request_store
    rt = _runtime(store, _Resolver(["matplotlib", "seaborn"]))

    await ProbOSRuntime.ensure_dependency(
        rt, ["matplotlib", "seaborn"], requested_by="counselor_0"
    )

    pending = await store.list_pending()
    assert sorted(r.target for r in pending) == ["matplotlib", "seaborn"]


# ── (2) the guards ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_a_repeated_failure_does_not_file_a_duplicate(request_store: CapabilityRequestStore) -> None:
    """A script re-run must not produce a second identical card. The one
    pending request already IS the ask."""
    store = request_store
    rt = _runtime(store, _Resolver(["matplotlib"]))

    await ProbOSRuntime.ensure_dependency(rt, "matplotlib", requested_by="counselor_0")
    await ProbOSRuntime.ensure_dependency(rt, "matplotlib", requested_by="counselor_0")
    await ProbOSRuntime.ensure_dependency(rt, "matplotlib", requested_by="counselor_0")

    pending = await store.list_pending()
    assert len(pending) == 1


@pytest.mark.asyncio
async def test_a_different_agent_wanting_the_same_library_does_file(
    request_store: CapabilityRequestStore,
) -> None:
    """Dedup is per (agent, target), not per target. Two agents blocked on the
    same library are two facts the Captain may want to act on separately —
    and collapsing them would hide the second agent entirely."""
    store = request_store
    rt = _runtime(store, _Resolver(["matplotlib"]))

    await ProbOSRuntime.ensure_dependency(rt, "matplotlib", requested_by="counselor_0")
    await ProbOSRuntime.ensure_dependency(rt, "matplotlib", requested_by="scout_0")

    pending = await store.list_pending()
    assert sorted(r.agent_id for r in pending) == ["counselor_0", "scout_0"]


@pytest.mark.asyncio
async def test_without_a_requester_nothing_is_filed(request_store: CapabilityRequestStore) -> None:
    """Default-OFF byte-identity: every caller that does not name an agent
    behaves exactly as it did before AD-1220."""
    store = request_store
    rt = _runtime(store, _Resolver(["matplotlib"]))

    result = await ProbOSRuntime.ensure_dependency(rt, "matplotlib")

    assert not result.success
    assert result.error == "approval callback unavailable"
    assert await store.list_pending() == []


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("collision", ["name", "id", "id-and-name"])
async def test_real_package_producer_and_approval_ignore_mcp_identity_collisions(
    wired, tmp_path, monkeypatch, enabled: bool, collision: str,
) -> None:
    mcp_store = McpServerStore(db_path=str(tmp_path / "package-mcp.db"))
    bridge = MCPBridge()
    await mcp_store.start()
    try:
        # Random UUIDs can begin with a digit, which is not a Python import.
        # Keep the ID/name collision assertions on a legal canonical target.
        with monkeypatch.context() as context:
            context.setattr(
                "probos.integrations.mcp_bridge.store.uuid.uuid4",
                lambda: uuid.UUID("abcdef0123456789abcdef0123456789"),
            )
            record = await mcp_store.create(McpServerRecord(
                name="feedparser", type="http", url="https://example.test/package", enabled=enabled,
            ))
        target = record.name if collision == "name" else record.id
        assert validate_python_install_target(target) == target
        if collision == "id-and-name":
            other = await mcp_store.create(McpServerRecord(
                name=record.id, type="http", url="https://example.test/other", enabled=not enabled,
            ))
            assert other.name == record.id and other.id != record.id
        before = mcp_store.list_sync()
        assert any(row.id == target or row.name == target for row in before)
        wired.runtime.mcp_server_store = mcp_store
        wired.runtime.mcp_bridge = bridge
        resolver = _Resolver([target])
        runtime = _runtime(wired.requests, resolver)
        declined = await ProbOSRuntime.ensure_dependency(runtime, target, requested_by="agent-1")
        assert not declined.success and declined.declined == [target]
        pending = await wired.requests.list_pending()
        assert len(pending) == 1
        request = pending[0]
        assert request.target == target and request.payload == {"install_kind": "python"}
        ensure_calls: list[tuple[str, bool]] = []

        async def ensure_dependency(package: str, *, pre_approved: bool = False) -> DependencyResult:
            assert (await wired.requests.get(request.id)).status == "approved"
            ensure_calls.append((package, pre_approved))
            return await ProbOSRuntime.ensure_dependency(runtime, package, pre_approved=pre_approved)

        wired.runtime.ensure_dependency = ensure_dependency
        assert (await _approve(wired, request.id))["fulfilled"] is True
        assert ensure_calls == [(target, True)] and len(resolver.resolved) == 1
        assert mcp_store.list_sync() == before
        assert bridge.list_servers() == []
        assert await wired.requests.list_pending() == []
    finally:
        await wired.bus.drain()
        await bridge.close_all()
        await mcp_store.stop()


@pytest.mark.parametrize("existing_kind", ["python", "mcp", "legacy", "malformed"])
async def test_package_dedup_only_reuses_validated_python_provenance(
    tmp_path, existing_kind: str,
) -> None:
    store = await _store(tmp_path)
    try:
        payload = {"install_kind": "python"} if existing_kind == "python" else (
            {"install_kind": "mcp", "mcp_server_id": "selected"} if existing_kind == "mcp" else None
        )
        seed = await store.file_request("agent-1", "install", "feedparser", payload=payload)
        if existing_kind == "malformed":
            await store.stop()
            with sqlite3.connect(store.db_path) as connection:
                connection.execute(
                    "UPDATE capability_requests SET payload='{}' WHERE id=?", (seed.id,)
                )
            await store.start()
            assert (await store.get(seed.id)).payload == {}
        first = await file_dependency_install_requests(store, ["feedparser", "feedparser"], "agent-1")
        second = await file_dependency_install_requests(store, ["feedparser"], "agent-1")
        assert first == ([] if existing_kind == "python" else ["feedparser"])
        assert second == []
        pending = await store.list_pending()
        assert len(pending) == (1 if existing_kind == "python" else 2)
        typed = [request for request in pending if request.payload == {"install_kind": "python"}]
        assert len(typed) == 1
        assert (typed[0].agent_id, typed[0].target) == ("agent-1", "feedparser")
        assert (typed[0].id == seed.id) == (existing_kind == "python")
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_pre_approved_never_files_a_request(request_store: CapabilityRequestStore) -> None:
    """`fulfil_install` re-enters here with pre_approved=True after the Captain
    has already said yes. Filing there would ask for permission to do the
    thing permission was just granted for — and each approval would mint the
    next request."""
    store = request_store
    resolver = _Resolver(["matplotlib"])
    rt = _runtime(store, resolver)

    result = await ProbOSRuntime.ensure_dependency(
        rt, "matplotlib", pre_approved=True, requested_by="counselor_0"
    )

    assert result.success
    assert resolver.resolved, "pre_approved should reach the resolver"
    assert await store.list_pending() == []


@pytest.mark.asyncio
async def test_an_allowlisted_package_is_not_asked_about(request_store: CapabilityRequestStore) -> None:
    """The whitelist tier auto-approves. Only the prompt tier becomes an ask."""
    store = request_store
    rt = _runtime(store, _Resolver(["json"]))

    await ProbOSRuntime.ensure_dependency(rt, "json", requested_by="counselor_0")

    assert await store.list_pending() == []


# ── (3) honest-degrade: filing must never cost the turn ────────────────────
@pytest.mark.asyncio
async def test_no_store_still_declines_cleanly(tmp_path) -> None:
    rt = _runtime(None, _Resolver(["matplotlib"]))

    result = await ProbOSRuntime.ensure_dependency(
        rt, "matplotlib", requested_by="counselor_0"
    )

    assert not result.success
    assert result.declined == ["matplotlib"]


@pytest.mark.asyncio
async def test_a_failing_store_does_not_raise(tmp_path) -> None:
    """Losing the ask is bad; losing the agent's partial work because the ask
    failed to write would be worse."""

    class _Exploding:
        async def list_actionable(self):
            raise RuntimeError("db is gone")

    rt = _runtime(_Exploding(), _Resolver(["matplotlib"]))

    result = await ProbOSRuntime.ensure_dependency(
        rt, "matplotlib", requested_by="counselor_0"
    )

    assert not result.success
    assert result.declined == ["matplotlib"]


# ── (4) THE CROSSING TEST: missing import → ask → approve → installed ──────
@pytest.mark.asyncio
async def test_the_whole_chain_from_missing_import_to_installed(request_store: CapabilityRequestStore) -> None:
    """One test spanning the seam that was dead.

    Deliberately NOT four tests of four links. Every link here was already
    correct and individually covered before AD-1220 — that is precisely why
    the feature could be complete and inert at the same time. Only an
    assertion that crosses the whole chain can tell the two apart.
    """
    from probos.cognitive.capability_triage import fulfil_install

    store = request_store
    resolver = _Resolver(["matplotlib"])
    rt = _runtime(store, resolver)

    # 1. an agent's script needs a library the sandbox does not have
    first = await ProbOSRuntime.ensure_dependency(
        rt, "matplotlib", requested_by="counselor_0"
    )
    assert not first.success

    # 2. the Captain is shown an ask (this is the step that did not exist)
    pending = await store.list_pending()
    assert len(pending) == 1
    request = pending[0]
    assert request.kind == "install"
    assert request.target == "matplotlib"

    # 3. the Captain approves it
    await store.decide(request.id, approve=True, decided_by="captain")

    # 4. approval fulfils — installing without asking a second time
    rt.ensure_dependency = lambda *a, **k: ProbOSRuntime.ensure_dependency(rt, *a, **k)
    fulfilled = await fulfil_install(
        request.id, store=store, target=request.target, runtime=rt
    )

    assert fulfilled is not None, "the approved install did not fulfil"
    assert fulfilled.status == "fulfilled"
    assert resolver.resolved, "nothing was ever actually installed"

    # 5. and the queue is clear — the ask is answered, not re-filed
    assert await store.list_pending() == []


@pytest.mark.parametrize("packages", [None, "numpy", {"numpy"}, {"name": "numpy"}, ("numpy",), 7])
async def test_python_filing_rejects_malformed_containers(request_store, packages, caplog):
    assert await file_dependency_install_requests(request_store, packages, "agent") == []
    assert await request_store.list_actionable() == []
    assert "non-list package container" in caplog.text


async def test_python_filing_keeps_valid_neighbors_and_empty_input_is_noop(request_store, caplog):
    assert await file_dependency_install_requests(request_store, [], "agent") == []
    assert not caplog.records
    packages = ["numpy.linalg", [], "not-a-package", "pandas; import scipy", None, {}, "match", "numpy.linalg"]
    filed = await file_dependency_install_requests(request_store, packages, "agent")
    assert filed == ["numpy.linalg", "match"]
    assert [row.target for row in await request_store.list_actionable()] == ["numpy.linalg", "match"]
    assert sum("not one canonical import" in record.message for record in caplog.records) == 5


async def test_python_filing_rejects_invalid_targets_before_reading_or_hashing(request_store, monkeypatch, caplog):
    calls = []

    async def read_queue():
        calls.append("read")
        raise AssertionError("invalid targets must be rejected before dedup")

    monkeypatch.setattr(request_store, "list_actionable", read_queue)
    assert await file_dependency_install_requests(
        request_store, [[], {}, "not-a-package", "numpy; import scipy"], "agent",
    ) == []
    assert calls == []
    assert len(caplog.records) == 4


@pytest.mark.parametrize("agent", [None, "", 7])
async def test_python_filing_requires_a_valid_requester(request_store, agent, caplog):
    assert await file_dependency_install_requests(request_store, ["numpy"], agent) == []
    assert await request_store.list_actionable() == []
    assert "no valid requesting agent" in caplog.text


@pytest.mark.parametrize("status", ["pending", "approved", "denied", "fulfilled", "failed"])
@pytest.mark.parametrize("kind", ["python", "mcp", "legacy", "malformed"])
async def test_python_filing_dedups_only_valid_pending_or_approved_unfulfilled_requests(
    request_store, status, kind,
):
    payload = {"install_kind": "python"} if kind == "python" else (
        {"install_kind": "mcp", "mcp_server_id": "selected"} if kind == "mcp" else None
    )
    seed = await request_store.file_request("agent", "install", "numpy", payload=payload)
    await request_store.stop()
    with sqlite3.connect(request_store.db_path) as connection:
        connection.execute("UPDATE capability_requests SET status=? WHERE id=?", (status, seed.id))
        if kind == "malformed":
            connection.execute("UPDATE capability_requests SET payload='{}' WHERE id=?", (seed.id,))
    await request_store.start()
    assert (await request_store.get(seed.id)).status == status

    filed = await file_dependency_install_requests(request_store, ["numpy", "numpy"], "agent")

    suppressed = kind == "python" and status in {"pending", "approved"}
    assert filed == ([] if suppressed else ["numpy"])
    assert await file_dependency_install_requests(request_store, ["numpy"], "agent") == []
    typed = [
        row for row in await request_store.list_actionable()
        if row.payload == {"install_kind": "python"}
    ]
    assert len(typed) == 1
    assert (typed[0].id == seed.id) == suppressed


async def test_python_filing_rejects_bad_targets_before_dedup_and_continues_after_write_failure(request_store, monkeypatch, caplog):
    original = request_store.file_request
    calls = []

    async def fail_one(*args, **kwargs):
        calls.append(kwargs["target"])
        if kwargs["target"] == "numpy":
            raise RuntimeError("controlled write failure")
        return await original(*args, **kwargs)

    monkeypatch.setattr(request_store, "file_request", fail_one)
    assert await file_dependency_install_requests(request_store, [[], "numpy", "pandas"], "agent") == ["pandas"]
    assert calls == ["numpy", "pandas"]
    assert "filing the install request" in caplog.text
    assert [row.target for row in await request_store.list_actionable()] == ["pandas"]


def _real_install_consumer(wired, monkeypatch):
    installed = set()
    calls = []
    find_spec = importlib.util.find_spec

    def controlled_spec(name, *args, **kwargs):
        if name.startswith("ordinary1205_"):
            return importlib.machinery.ModuleSpec(name, loader=None) if name in installed else None
        return find_spec(name, *args, **kwargs)

    async def install(package):
        calls.append(package)
        installed.add(package)
        return True, "installed in the controlled resolver fixture"

    monkeypatch.setattr(importlib.util, "find_spec", controlled_spec)
    resolver = DependencyResolver(
        allowed_imports=[], policy="prompt_unlisted", install_fn=install,
    )
    wired.runtime.dependency_resolver = resolver
    assert resolver.detect_missing("import ordinary1205_pkg.submodule") == ["ordinary1205_pkg"]
    return calls


@pytest.mark.parametrize("target", [
    "not-a-package", "ordinary1205_pkg; import ordinary1205_other",
    "ordinary1205_pkg, ordinary1205_other", "ordinary1205_pkg as alias",
    " ordinary1205_pkg", "ordinary1205_pkg # comment", "for",
])
@pytest.mark.parametrize("provenance", ["python", "legacy"])
async def test_fulfil_install_revalidates_tampered_python_target_after_restart(
    wired, monkeypatch, target, provenance, caplog,
):
    calls = _real_install_consumer(wired, monkeypatch)
    payload = {"install_kind": "python"} if provenance == "python" else None
    request = await wired.requests.file_request("agent", "install", "ordinary1205_pkg", payload=payload)
    await wired.requests.decide(request.id, True)
    await wired.bus.drain()
    await wired.requests.stop()
    with sqlite3.connect(wired.requests.db_path) as connection:
        connection.execute("UPDATE capability_requests SET target=? WHERE id=?", (target, request.id))
    await wired.requests.start()
    assert (await wired.requests.get(request.id)).target == target
    assert (await wired.requests.get(request.id)).payload == payload

    result = await _approve(wired, request.id)

    assert result["fulfilled"] is False
    assert result["request"]["status"] == "approved"
    assert calls == [], "invalid or compound approval reached the real resolver installer"
    assert wired.bus.emitted.count(EventType.CAPABILITY_REQUEST_FULFILLED.value) == 0
    assert "does not name one canonical import" in caplog.text


async def test_dotted_python_approval_attempts_one_root_package(wired, monkeypatch):
    calls = _real_install_consumer(wired, monkeypatch)
    assert await file_dependency_install_requests(
        wired.requests, ["ordinary1205_pkg.submodule"], "agent",
    ) == ["ordinary1205_pkg.submodule"]
    request, = await wired.requests.list_actionable()

    result = await _approve(wired, request.id)

    assert result["fulfilled"] is True
    assert result["request"]["target"] == "ordinary1205_pkg.submodule"
    assert calls == ["ordinary1205_pkg"]
    assert wired.bus.emitted.count(EventType.CAPABILITY_REQUEST_FULFILLED.value) == 1


async def test_general_runtime_multi_import_behavior_is_unchanged(wired, monkeypatch):
    calls = _real_install_consumer(wired, monkeypatch)
    result = await wired.runtime.ensure_dependency(
        "ordinary1205_pkg; import ordinary1205_other", pre_approved=True,
    )
    assert result.success is True
    assert set(calls) == {"ordinary1205_pkg", "ordinary1205_other"}
    assert len(calls) == 2
    assert await wired.requests.list_actionable() == []
