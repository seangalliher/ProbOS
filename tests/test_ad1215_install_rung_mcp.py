"""AD-1215 (#1172): the install rung means "enable a registered MCP server".

Before this, ``skill_known`` was resolved from ``runtime.extension_registry`` —
an attribute nothing in ``src/`` ever assigned — so ``triage()`` could never
return ``install``, and ``fulfil_install`` would have pip-installed a package
named after an extension id. Selection and fulfilment now agree, and both
resolve against ``runtime.mcp_server_store``, which startup/finalize.py really
does assign.
"""
from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import replace
from typing import Any

import pytest

from probos.capability_request import (
    CapabilityRequest, CapabilityRequestStore, validate_install_payload,
)
from probos.cognitive.capability_triage import (
    fulfil_install,
    resolve_installable_mcp_server,
    triage_and_file,
)
from probos.integrations.mcp_bridge.store import McpServerRecord


def _McpRecord(*, id: str, name: str, enabled: bool) -> McpServerRecord:
    """Real registration fields with stable test identities."""
    return McpServerRecord(
        id=id, name=name, enabled=enabled, type="http",
        url=f"https://example.test/{id}",
    )


class _McpServerStore:
    """Stands in for McpServerStore with its real ``list_sync`` / ``set_enabled``."""

    def __init__(self, records: list[McpServerRecord]) -> None:
        self._records = records
        self.set_enabled_calls: list[tuple[str, bool]] = []

    def list_sync(self) -> list[McpServerRecord]:
        return list(self._records)

    async def set_enabled(self, server_id: str, enabled: bool) -> McpServerRecord | None:
        self.set_enabled_calls.append((server_id, enabled))
        for index, record in enumerate(self._records):
            if record.id == server_id:
                updated = replace(record, enabled=enabled)
                self._records[index] = updated
                return updated
        return None


class _RaisingMcpServerStore:
    def list_sync(self):
        raise RuntimeError("cache unavailable")


class _VanishingMcpServerStore:
    """Resolves a record, then reports it gone — a delete racing the approval."""

    def __init__(self, record: McpServerRecord) -> None:
        self._record = record
        self.set_enabled_calls: list[tuple[str, bool]] = []

    def list_sync(self) -> list[McpServerRecord]:
        return [self._record]

    async def set_enabled(self, server_id: str, enabled: bool) -> None:
        self.set_enabled_calls.append((server_id, enabled))
        return None


class _EnsureDependencyResult:
    def __init__(self, success: bool, error: str | None = None) -> None:
        self.success = success
        self.error = error


class _FakeBridge:
    def __init__(self) -> None:
        self.clients: dict[str, object] = {}
        self.register_calls: list[str] = []
        self.unregister_calls: list[str] = []
        self.accept = True
        self.expose_client = True
        self.error: BaseException | None = None
        self.configurations: dict[str, dict[str, str]] = {}

    def register_server(
        self, url: str, headers: dict[str, str] | None = None,
        *, reuse_if_matching: bool = False,
    ) -> bool:
        self.register_calls.append(url)
        if self.error is not None:
            raise self.error
        if url in self.clients:
            return self.accept and reuse_if_matching and self.configurations.get(url) == dict(headers or {})
        if self.accept and self.expose_client:
            self.clients[url] = object()
            self.configurations[url] = dict(headers or {})
        return self.accept

    def get_client(self, key: str) -> object | None:
        return self.clients.get(key)

    async def unregister_server(self, key: str) -> bool:
        self.unregister_calls.append(key)
        self.configurations.pop(key, None)
        return self.clients.pop(key, None) is not None


class _Runtime:
    """Runtime double with an observable registration boundary."""

    def __init__(
        self, *, mcp_server_store: Any = None,
        ensure_result: _EnsureDependencyResult | None = None,
    ) -> None:
        self.mcp_server_store = mcp_server_store
        self.mcp_bridge: _FakeBridge | None = _FakeBridge()
        self._ensure_result = ensure_result
        self.ensure_calls: list[tuple[str, bool]] = []

    async def ensure_dependency(
        self, target: str, *, pre_approved: bool = False
    ) -> _EnsureDependencyResult | None:
        self.ensure_calls.append((target, pre_approved))
        return self._ensure_result


class _RuntimeWithoutEnsure:
    def __init__(self, *, mcp_server_store=None) -> None:
        self.mcp_server_store = mcp_server_store


@pytest.fixture
async def store(tmp_path):
    s = CapabilityRequestStore(db_path=str(tmp_path / "caps.db"))
    await s.start()
    try:
        yield s
    finally:
        await s.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"install_kind": "mcp", "mcp_server_id": "selected-server"},
    {"install_kind": "python"},
    None,
], ids=["mcp", "python", "legacy-null"])
async def test_review_regression_install_payload_survives_store_restart(
    store: CapabilityRequestStore, payload: dict[str, Any] | None,
) -> None:
    request = await store.file_request(
        agent_id="agent-1", kind="install", target="feedparser", payload=payload,
    )
    assert request.id and request.kind == "install"
    assert request.payload == payload
    before_restart = await store.get(request.id)
    assert before_restart is not None and before_restart.payload == payload

    await store.stop()
    await store.start()

    restored = await store.get(request.id)
    assert restored is not None
    assert (restored.kind, restored.target, restored.status) == (
        "install", "feedparser", "pending"
    )
    assert restored.payload == payload


# --------------------------------------------------------------------------- #
# resolve_installable_mcp_server — the shared selection predicate
# --------------------------------------------------------------------------- #
class TestResolveInstallableMcpServer:
    def test_disabled_server_matched_by_id_is_installable(self) -> None:
        store = _McpServerStore([_McpRecord(id="pdf", name="pdf-tools", enabled=False)])
        assert resolve_installable_mcp_server(store, "pdf") is not None

    def test_disabled_server_matched_by_name_is_installable(self) -> None:
        store = _McpServerStore([_McpRecord(id="srv-1", name="pdf-tools", enabled=False)])
        rec = resolve_installable_mcp_server(store, "pdf-tools")
        assert rec is not None and rec.id == "srv-1"

    def test_already_enabled_server_is_not_installable(self) -> None:
        store = _McpServerStore([_McpRecord(id="pdf", name="pdf-tools", enabled=True)])
        assert resolve_installable_mcp_server(store, "pdf") is None

    def test_unknown_target_is_not_installable(self) -> None:
        store = _McpServerStore([_McpRecord(id="pdf", name="pdf-tools", enabled=False)])
        assert resolve_installable_mcp_server(store, "something_else") is None

    def test_absent_store_is_not_installable(self) -> None:
        assert resolve_installable_mcp_server(None, "pdf") is None

    def test_empty_store_is_not_installable(self) -> None:
        assert resolve_installable_mcp_server(_McpServerStore([]), "pdf") is None

    def test_raising_store_degrades_to_not_installable(self, caplog) -> None:
        import logging

        with caplog.at_level(logging.WARNING):
            assert resolve_installable_mcp_server(_RaisingMcpServerStore(), "pdf") is None
        assert any("list_sync" in r.message for r in caplog.records)

    def test_absent_store_is_silent(self, caplog) -> None:
        """No MCP store is the ordinary case, not a fault — it must not log."""
        import logging

        with caplog.at_level(logging.WARNING):
            assert resolve_installable_mcp_server(None, "pdf") is None
        assert [r.message for r in caplog.records] == []

    def test_exact_id_match_beats_an_earlier_enabled_name_match(self) -> None:
        """A name is not unique across the id axis; the exact id must win.

        One record's ``name`` may equal another record's ``id`` (the store's
        UNIQUE constraints are per-column). A single id-OR-name pass returned
        ``None`` here because the enabled name-match came first, so a genuinely
        installable server was triaged to ``build``.
        """
        store = _McpServerStore(
            [
                _McpRecord(id="a1", name="target-id", enabled=True),
                _McpRecord(id="target-id", name="other", enabled=False),
            ]
        )
        rec = resolve_installable_mcp_server(store, "target-id")
        assert rec is not None and rec.id == "target-id"

    def test_enabled_exact_id_match_is_not_installable_despite_a_disabled_name_match(
        self,
    ) -> None:
        """The id axis is decisive both ways — it does not fall back to names."""
        store = _McpServerStore(
            [
                _McpRecord(id="target-id", name="other", enabled=True),
                _McpRecord(id="a1", name="target-id", enabled=False),
            ]
        )
        assert resolve_installable_mcp_server(store, "target-id") is None

    def test_disabled_match_wins_over_an_earlier_enabled_match_on_the_same_axis(
        self,
    ) -> None:
        """Within one axis, first-match-wins must not mask a later disabled row."""
        store = _McpServerStore(
            [
                _McpRecord(id="srv-1", name="pdf-tools", enabled=True),
                _McpRecord(id="srv-2", name="pdf-tools", enabled=False),
            ]
        )
        rec = resolve_installable_mcp_server(store, "pdf-tools")
        assert rec is not None and rec.id == "srv-2"


# --------------------------------------------------------------------------- #
# Selection: triage_and_file now reaches the install rung
# --------------------------------------------------------------------------- #
class TestInstallRungIsReachable:
    @pytest.mark.asyncio
    async def test_registered_disabled_mcp_server_files_an_install(self, store) -> None:
        mcp = _McpServerStore([_McpRecord(id="pdf", name="pdf-tools", enabled=False)])
        req = await triage_and_file(
            gap_target="pdf", agent_id="agent-1", store=store, mcp_server_store=mcp
        )
        assert req.kind == "install"
        assert req.status == "pending"
        assert req.payload == {"install_kind": "mcp", "mcp_server_id": "pdf"}

    @pytest.mark.asyncio
    async def test_enabled_mcp_server_does_not_file_an_install(self, store) -> None:
        mcp = _McpServerStore([_McpRecord(id="pdf", name="pdf-tools", enabled=True)])
        req = await triage_and_file(
            gap_target="pdf", agent_id="agent-1", store=store, mcp_server_store=mcp
        )
        assert req.kind == "build"

    @pytest.mark.asyncio
    async def test_unknown_target_still_lands_on_build(self, store) -> None:
        mcp = _McpServerStore([_McpRecord(id="pdf", name="pdf-tools", enabled=False)])
        req = await triage_and_file(
            gap_target="nothing_like_it",
            agent_id="agent-1",
            store=store,
            mcp_server_store=mcp,
        )
        assert req.kind == "build"

    @pytest.mark.asyncio
    async def test_grant_still_outranks_install(self, store) -> None:
        """A registered tool the agent lacks permission for stays a grant."""

        class _Registration:
            def __init__(self) -> None:
                self.default_permissions: dict = {}

        class _ToolRegistry:
            def get(self, tool_id: str):
                return _Registration() if tool_id == "pdf" else None

        mcp = _McpServerStore([_McpRecord(id="pdf", name="pdf-tools", enabled=False)])
        req = await triage_and_file(
            gap_target="pdf",
            agent_id="agent-1",
            store=store,
            tool_registry=_ToolRegistry(),
            mcp_server_store=mcp,
        )
        assert req.kind == "grant"
        assert req.payload is None


# --------------------------------------------------------------------------- #
# Fulfilment: an approved install enables the server
# --------------------------------------------------------------------------- #
class TestFulfilInstallEnablesMcpServer:
    @pytest.mark.asyncio
    async def test_approved_install_enables_the_server_and_fulfils(
        self, store: CapabilityRequestStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rec = _McpRecord(id="pdf", name="pdf-tools", enabled=False)
        mcp = _McpServerStore([rec])
        runtime = _Runtime(mcp_server_store=mcp)
        bridge = runtime.mcp_bridge
        assert bridge is not None
        mark_fulfilled = store.mark_fulfilled

        async def mark_when_ready(request_id: str) -> CapabilityRequest | None:
            assert bridge.get_client(rec.url) is not None
            assert mcp.list_sync()[0].enabled is True
            return await mark_fulfilled(request_id)

        monkeypatch.setattr(store, "mark_fulfilled", mark_when_ready)
        req = await store.file_request(
            agent_id="agent-1", kind="install", target="pdf", rationale="needs pdf",
            payload={"install_kind": "mcp", "mcp_server_id": rec.id},
        )
        await store.decide(req.id, approve=True, reason="ok", decided_by="captain")

        out = await fulfil_install(
            req.id, store=store, target="pdf", runtime=runtime
        )

        assert mcp.set_enabled_calls == [("pdf", True)]
        assert bridge.register_calls == [rec.url]
        assert runtime.ensure_calls == []
        assert mcp.list_sync()[0].enabled is True
        assert out is not None and out.status == "fulfilled"

    @pytest.mark.asyncio
    async def test_server_matched_by_name_is_enabled_by_its_id(self, store) -> None:
        rec = _McpRecord(id="srv-1", name="pdf-tools", enabled=False)
        mcp = _McpServerStore([rec])
        req = await store.file_request(
            agent_id="agent-1", kind="install", target="pdf-tools", rationale="",
            payload={"install_kind": "mcp", "mcp_server_id": rec.id},
        )
        await store.decide(req.id, approve=True, reason="ok", decided_by="captain")

        out = await fulfil_install(
            req.id, store=store, target="pdf-tools", runtime=_Runtime(mcp_server_store=mcp)
        )

        assert mcp.set_enabled_calls == [("srv-1", True)]
        assert out is not None and out.status == "fulfilled"

    @pytest.mark.asyncio
    async def test_id_name_collision_files_and_enables_the_id_match(self, store) -> None:
        """Crosses the seam: the collision must select AND enable the id-match.

        Selection persists identity rather than repeating the name lookup, so a
        disagreement here would enable a server the Captain did not approve — or
        skip enablement entirely and pip-install the target instead.
        """
        masking = _McpRecord(id="a1", name="target-id", enabled=True)
        wanted = _McpRecord(id="target-id", name="other", enabled=False)
        mcp = _McpServerStore([masking, wanted])

        req = await triage_and_file(
            gap_target="target-id",
            agent_id="agent-1",
            store=store,
            mcp_server_store=mcp,
        )
        assert req.kind == "install"

        await store.decide(req.id, approve=True, reason="ok", decided_by="captain")
        out = await fulfil_install(
            req.id,
            store=store,
            target="target-id",
            runtime=_Runtime(mcp_server_store=mcp),
        )

        assert mcp.set_enabled_calls == [("target-id", True)]
        assert next(record for record in mcp.list_sync() if record.id == wanted.id).enabled is True
        assert masking.enabled is True  # untouched
        assert out is not None and out.status == "fulfilled"

    @pytest.mark.asyncio
    async def test_non_mcp_target_still_goes_to_ensure_dependency(self, store) -> None:
        mcp = _McpServerStore([_McpRecord(id="pdf", name="pdf-tools", enabled=False)])
        runtime = _Runtime(
            mcp_server_store=mcp, ensure_result=_EnsureDependencyResult(True)
        )
        req = await store.file_request(
            agent_id="agent-1", kind="install", target="numpy", rationale=""
        )
        await store.decide(req.id, approve=True, reason="ok", decided_by="captain")

        out = await fulfil_install(
            req.id, store=store, target="numpy", runtime=runtime
        )

        assert runtime.ensure_calls == [("numpy", True)]
        assert mcp.set_enabled_calls == []
        assert out is not None and out.status == "fulfilled"

    @pytest.mark.asyncio
    async def test_typed_enabled_mcp_retry_does_not_install_a_package(self, store) -> None:
        """Partial MCP retries carry identity; package name collisions are a separate case."""
        mcp = _McpServerStore([_McpRecord(id="pdf", name="pdf-tools", enabled=True)])
        runtime = _Runtime(
            mcp_server_store=mcp, ensure_result=_EnsureDependencyResult(False, "no such package")
        )
        req = await store.file_request(
            agent_id="agent-1", kind="install", target="pdf", rationale="",
            payload={"install_kind": "mcp", "mcp_server_id": "pdf"},
        )
        await store.decide(req.id, approve=True, reason="ok", decided_by="captain")

        out = await fulfil_install(req.id, store=store, target="pdf", runtime=runtime)

        assert mcp.set_enabled_calls == [("pdf", True)]
        assert runtime.ensure_calls == []
        assert runtime.mcp_bridge.register_calls == ["https://example.test/pdf"]
        assert out is not None and out.status == "fulfilled"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("failure", ["missing", "rejected", "raises", "no-client"])
    async def test_registration_failure_before_enablement_is_retryable(
        self, store: CapabilityRequestStore, failure: str
    ) -> None:
        record = _McpRecord(id="pdf", name="pdf-tools", enabled=False)
        mcp = _McpServerStore([record])
        runtime = _Runtime(mcp_server_store=mcp)
        bridge = runtime.mcp_bridge
        assert bridge is not None
        if failure == "missing":
            runtime.mcp_bridge = None
        elif failure == "rejected":
            bridge.accept = False
        elif failure == "raises":
            bridge.error = RuntimeError("registration unavailable")
        else:
            bridge.expose_client = False
        request = await store.file_request(
            agent_id="agent-1", kind="install", target="pdf", rationale="",
            payload={"install_kind": "mcp", "mcp_server_id": record.id},
        )
        await store.decide(request.id, approve=True, reason="ok", decided_by="captain")

        result = await fulfil_install(request.id, store=store, target="pdf", runtime=runtime)

        assert result is None
        assert mcp.list_sync()[0].enabled is False, "registration must precede durable enablement"
        assert mcp.set_enabled_calls == []
        assert (await store.get(request.id)).status == "approved"
        assert runtime.ensure_calls == []
        runtime.mcp_bridge = bridge
        bridge.accept = True
        bridge.error = None
        bridge.expose_client = True

        retried = await fulfil_install(request.id, store=store, target="pdf", runtime=runtime)

        assert retried is not None and retried.status == "fulfilled"
        assert mcp.set_enabled_calls == [("pdf", True)]
        assert bridge.get_client(record.url) is not None
        assert runtime.ensure_calls == []

    @pytest.mark.asyncio
    async def test_failed_durable_fulfilment_reuses_target_on_retry(
        self, store: CapabilityRequestStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        record = _McpRecord(id="pdf", name="pdf-tools", enabled=False)
        mcp = _McpServerStore([record])
        runtime = _Runtime(mcp_server_store=mcp)
        bridge = runtime.mcp_bridge
        assert bridge is not None
        unrelated = object()
        bridge.clients["unrelated"] = unrelated
        request = await store.file_request(
            agent_id="agent-1", kind="install", target="pdf", rationale="",
            payload={"install_kind": "mcp", "mcp_server_id": record.id},
        )
        await store.decide(request.id, approve=True, reason="ok", decided_by="captain")
        mark_fulfilled = store.mark_fulfilled

        async def fail_fulfilment(request_id: str) -> CapabilityRequest | None:
            assert bridge.get_client(record.url) is not None
            raise OSError("durable fulfilment unavailable")

        monkeypatch.setattr(store, "mark_fulfilled", fail_fulfilment)
        with pytest.raises(OSError, match="durable fulfilment"):
            await fulfil_install(request.id, store=store, target="pdf", runtime=runtime)
        first_client = bridge.get_client(record.url)
        assert first_client is not None
        assert (await store.get(request.id)).status == "approved"
        monkeypatch.setattr(store, "mark_fulfilled", mark_fulfilled)

        retried = await fulfil_install(request.id, store=store, target="pdf", runtime=runtime)

        assert retried is not None and retried.status == "fulfilled"
        assert bridge.unregister_calls == [], "retry must not destroy a published client"
        assert bridge.get_client(record.url) is first_client
        assert bridge.get_client("unrelated") is unrelated
        assert mcp.set_enabled_calls == [("pdf", True), ("pdf", True)]
        assert runtime.ensure_calls == []

    @pytest.mark.asyncio
    async def test_registration_cancellation_does_not_fulfil_or_install_dependency(
        self, store: CapabilityRequestStore
    ) -> None:
        record = _McpRecord(id="pdf", name="pdf-tools", enabled=False)
        runtime = _Runtime(mcp_server_store=_McpServerStore([record]))
        bridge = runtime.mcp_bridge
        assert bridge is not None
        bridge.error = asyncio.CancelledError()
        request = await store.file_request(
            agent_id="agent-1", kind="install", target="pdf", rationale="",
            payload={"install_kind": "mcp", "mcp_server_id": record.id},
        )
        await store.decide(request.id, approve=True, reason="ok", decided_by="captain")

        with pytest.raises(asyncio.CancelledError):
            await fulfil_install(request.id, store=store, target="pdf", runtime=runtime)

        assert runtime.mcp_server_store.list_sync()[0].enabled is False
        assert (await store.get(request.id)).status == "approved"
        assert runtime.ensure_calls == []
        bridge.error = None
        retried = await fulfil_install(request.id, store=store, target="pdf", runtime=runtime)
        assert retried is not None and retried.status == "fulfilled"

    @pytest.mark.asyncio
    async def test_unreadable_mcp_store_never_confirms_a_dependency_target(
        self, store: CapabilityRequestStore
    ) -> None:
        runtime = _Runtime(
            mcp_server_store=_RaisingMcpServerStore(),
            ensure_result=_EnsureDependencyResult(True),
        )
        request = await store.file_request(
            agent_id="agent-1", kind="install", target="pdf", rationale=""
        )
        await store.decide(request.id, approve=True, reason="ok", decided_by="captain")

        result = await fulfil_install(request.id, store=store, target="pdf", runtime=runtime)

        assert result is None
        assert runtime.ensure_calls == []
        assert (await store.get(request.id)).status == "approved"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("target", ["", "   "])
    async def test_empty_target_never_attempts_installation(
        self, store: CapabilityRequestStore, target: str
    ) -> None:
        runtime = _Runtime(ensure_result=_EnsureDependencyResult(True))
        # Empty typed targets are now rejected at filing. Tamper a persisted row
        # to keep exercising the fulfiller's independent refusal boundary.
        request = await store.file_request(
            "agent-1", "install", "numpy", payload={"install_kind": "python"},
        )
        await store.decide(request.id, approve=True)
        await store.stop()
        with sqlite3.connect(store.db_path) as connection:
            connection.execute("UPDATE capability_requests SET target=? WHERE id=?", (target, request.id))
        await store.start()
        assert (await store.get(request.id)).target == target
        result = await fulfil_install(request.id, store=store, target=target, runtime=runtime)
        assert result is None
        assert runtime.ensure_calls == []
        assert runtime.mcp_bridge.register_calls == []

    @pytest.mark.asyncio
    async def test_no_mcp_store_preserves_genuine_dependency_installation(
        self, store: CapabilityRequestStore
    ) -> None:
        runtime = _Runtime(ensure_result=_EnsureDependencyResult(True))
        del runtime.mcp_server_store
        request = await store.file_request(
            agent_id="agent-1", kind="install", target="numpy", rationale=""
        )
        await store.decide(request.id, approve=True, reason="ok", decided_by="captain")

        result = await fulfil_install(request.id, store=store, target="numpy", runtime=runtime)

        assert result is not None and result.status == "fulfilled"
        assert runtime.ensure_calls == [("numpy", True)]

    @pytest.mark.asyncio
    async def test_no_mcp_match_and_no_ensure_dependency_does_not_fulfil(
        self, store, caplog
    ) -> None:
        import logging

        req = await store.file_request(
            agent_id="agent-1", kind="install", target="pdf", rationale=""
        )
        await store.decide(req.id, approve=True, reason="ok", decided_by="captain")

        with caplog.at_level(logging.WARNING):
            out = await fulfil_install(
                req.id, store=store, target="pdf", runtime=_RuntimeWithoutEnsure()
            )

        assert out is None
        assert any("ensure_dependency" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_server_deleted_between_resolve_and_enable_does_not_fulfil(
        self, store, caplog
    ) -> None:
        """set_enabled returning None means the row went away; do not claim success."""
        import logging

        mcp = _VanishingMcpServerStore(
            _McpRecord(id="pdf", name="pdf-tools", enabled=False)
        )
        req = await store.file_request(
            agent_id="agent-1", kind="install", target="pdf", rationale="",
            payload={"install_kind": "mcp", "mcp_server_id": "pdf"},
        )
        await store.decide(req.id, approve=True, reason="ok", decided_by="captain")

        with caplog.at_level(logging.WARNING):
            out = await fulfil_install(
                req.id, store=store, target="pdf", runtime=_Runtime(mcp_server_store=mcp)
            )

        assert mcp.set_enabled_calls == [("pdf", True)]
        assert out is None
        assert (await store.get(req.id)).status != "fulfilled"


# --------------------------------------------------------------------------- #
# The seam: file -> approve -> fulfil, end to end
# --------------------------------------------------------------------------- #
class TestInstallRungCrossesTheSeam:
    @pytest.mark.asyncio
    async def test_gap_on_disabled_server_becomes_an_enabled_server(self, store) -> None:
        """Triage selects install, the Captain approves, the server ends up enabled.

        Each half of this rung was correct in isolation before AD-1215 and the
        chain was still dead, so the crossing test is the one that matters.
        """
        rec = _McpRecord(id="pdf", name="pdf-tools", enabled=False)
        mcp = _McpServerStore([rec])

        filed = await triage_and_file(
            gap_target="pdf", agent_id="agent-1", store=store, mcp_server_store=mcp
        )
        assert filed.kind == "install"

        await store.decide(
            filed.id, approve=True, reason="approved", decided_by="captain"
        )
        fulfilled = await fulfil_install(
            filed.id, store=store, target="pdf", runtime=_Runtime(mcp_server_store=mcp)
        )

        assert fulfilled is not None and fulfilled.status == "fulfilled"
        assert mcp.list_sync()[0].enabled is True
        # And the rung is now correctly closed: the same gap no longer files an install.
        again = await triage_and_file(
            gap_target="pdf", agent_id="agent-1", store=store, mcp_server_store=mcp
        )
        assert again.kind == "build"


class _StringSubclass(str):
    pass


class _DictSubclass(dict[str, Any]):
    pass


@pytest.mark.parametrize("payload", [
    None, {}, [], "python", {"install_kind": []}, {"install_kind": "unknown"},
    {"install_kind": "python", "target": "numpy"},
    {"install_kind": "mcp"}, {"install_kind": "mcp", "mcp_server_id": None},
    {"install_kind": "mcp", "mcp_server_id": 1},
    {"install_kind": "mcp", "mcp_server_id": ""},
    {"install_kind": "mcp", "mcp_server_id": " leading"},
    {"install_kind": "mcp", "mcp_server_id": "trailing "},
    {"install_kind": "mcp", "mcp_server_id": "line\nbreak"},
    {"install_kind": "mcp", "mcp_server_id": "control\x7f"},
    {"install_kind": "mcp", "mcp_server_id": "control\x85"},
    {"install_kind": "mcp", "mcp_server_id": "bad\ud800"},
    {"install_kind": "mcp", "mcp_server_id": "x" * 129},
    {"install_kind": "mcp", "mcp_server_id": "id", "credentials": "not-allowed"},
    {_StringSubclass("install_kind"): "python"},
    {"install_kind": _StringSubclass("python")},
    {"install_kind": "mcp", "mcp_server_id": _StringSubclass("id")},
    _DictSubclass(install_kind="python"),
])
def test_validate_install_payload_rejects_malformed_and_untrusted_types(payload: Any) -> None:
    assert validate_install_payload(payload) is None


@pytest.mark.parametrize("payload", [
    {"install_kind": "python"},
    {"install_kind": "mcp", "mcp_server_id": "a"},
    {"install_kind": "mcp", "mcp_server_id": "a" * 128},
])
def test_validate_install_payload_accepts_exact_bounded_provenance(payload: dict[str, str]) -> None:
    assert validate_install_payload(payload) == payload


@pytest.mark.parametrize("payload", [{}, [], {"install_kind": "python", "extra": True}])
async def test_file_install_invalid_nonnull_payload_is_not_persisted(
    store: CapabilityRequestStore, payload: Any,
) -> None:
    with pytest.raises(ValueError, match="Invalid install"):
        await store.file_request("agent-1", "install", "numpy", payload=payload)
    assert await store.list_pending() == []
    await store.stop()
    await store.start()
    assert await store.list_pending() == []


@pytest.mark.parametrize("raw", [
    "not-json", "null", "[]", "{}", '{"install_kind":"mcp"}',
    '{"install_kind":"python","extra":true}', 123, b"not-text",
])
async def test_invalid_stored_install_payload_stays_distinct_from_legacy_and_refuses(
    store: CapabilityRequestStore, raw: Any, caplog: pytest.LogCaptureFixture,
) -> None:
    request = await store.file_request("agent-1", "install", "numpy")
    await store.decide(request.id, approve=True)
    await store.stop()
    with sqlite3.connect(store.db_path) as connection:
        connection.execute("UPDATE capability_requests SET payload=? WHERE id=?", (raw, request.id))
        assert connection.execute(
            "SELECT payload IS NOT NULL FROM capability_requests WHERE id=?", (request.id,)
        ).fetchone() == (1,)
    await store.start()
    restored = await store.get(request.id)
    assert restored is not None and restored.payload == {} and restored.payload is not None
    assert "invalid sentinel" in caplog.text
    runtime = _Runtime(ensure_result=_EnsureDependencyResult(True))
    assert await fulfil_install(request.id, store=store, target="numpy", runtime=runtime) is None
    assert runtime.ensure_calls == [] and runtime.mcp_bridge.register_calls == []
    assert (await store.get(request.id)).status == "approved"


@pytest.mark.parametrize("state", ["missing", "pending", "denied", "fulfilled", "wrong-kind", "wrong-target"])
async def test_fulfil_install_requires_approved_install_for_same_target(
    store: CapabilityRequestStore, state: str,
) -> None:
    request = await store.file_request(
        "agent-1", "grant" if state == "wrong-kind" else "install", "numpy",
        payload={"install_kind": "python"},
    )
    if state != "pending":
        await store.decide(request.id, approve=state != "denied")
    if state == "fulfilled":
        await store.mark_fulfilled(request.id)
    runtime = _Runtime(ensure_result=_EnsureDependencyResult(True))
    result = await fulfil_install(
        "missing" if state == "missing" else request.id, store=store,
        target="different" if state == "wrong-target" else "numpy", runtime=runtime,
    )
    assert result is None
    assert runtime.ensure_calls == [] and runtime.mcp_bridge.register_calls == []


@pytest.mark.parametrize("kind", ["python", "mcp", "legacy"])
async def test_unreadable_mcp_store_only_allows_explicit_python_approval(
    store: CapabilityRequestStore, kind: str,
) -> None:
    payload = None if kind == "legacy" else {"install_kind": kind}
    if kind == "mcp":
        payload["mcp_server_id"] = "selected"
    request = await store.file_request("agent-1", "install", "numpy", payload=payload)
    await store.decide(request.id, approve=True)
    runtime = _Runtime(mcp_server_store=_RaisingMcpServerStore(), ensure_result=_EnsureDependencyResult(True))
    result = await fulfil_install(request.id, store=store, target="numpy", runtime=runtime)
    assert (result is not None) == (kind == "python")
    assert runtime.ensure_calls == ([("numpy", True)] if kind == "python" else [])
    assert runtime.mcp_bridge.register_calls == []


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("axis", ["id", "name"])
async def test_legacy_install_collision_requires_new_typed_approval(
    store: CapabilityRequestStore, enabled: bool, axis: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    record = _McpRecord(id="target" if axis == "id" else "other", name="target", enabled=enabled)
    mcp = _McpServerStore([record])
    runtime = _Runtime(mcp_server_store=mcp, ensure_result=_EnsureDependencyResult(True))
    request = await store.file_request("agent-1", "install", "target")
    await store.decide(request.id, approve=True)
    assert await fulfil_install(request.id, store=store, target="target", runtime=runtime) is None
    assert (await store.get(request.id)).payload is None
    assert (await store.get(request.id)).status == "approved"
    assert mcp.set_enabled_calls == [] and runtime.ensure_calls == []
    assert runtime.mcp_bridge.register_calls == []
    assert "fresh approval" in caplog.text


async def test_install_payload_is_copied_before_filing_and_survives_restart(
    store: CapabilityRequestStore,
) -> None:
    payload = {"install_kind": "mcp", "mcp_server_id": "selected"}
    request = await store.file_request("agent-1", "install", "named", payload=payload)
    payload["mcp_server_id"] = "different"
    assert request.payload == {"install_kind": "mcp", "mcp_server_id": "selected"}
    await store.stop()
    await store.start()
    assert (await store.get(request.id)).payload == request.payload


async def test_action_validation_and_non_install_decoding_remain_unchanged(
    store: CapabilityRequestStore,
) -> None:
    payload = {
        "tool_id": "browser", "action": "navigate", "params": {},
        "scope_key": "example.test", "session_id": None, "thread_id": "thread",
    }
    action = await store.file_action_request("agent-1", payload)
    assert action is not None and action.payload == payload
    assert await store.file_action_request("agent-1", {**payload, "extra": True}) is None
    grant = await store.file_request("agent-1", "grant", "tool")
    build = await store.file_request("agent-1", "build", "tool", payload={"intent_description": "unchanged"})
    await store.stop()
    await store.start()
    assert (await store.get(action.id)).payload == payload
    assert (await store.get(grant.id)).payload is None
    assert (await store.get(build.id)).payload is None


@pytest.mark.parametrize("store_present", [False, True])
async def test_missing_record_for_typed_mcp_never_falls_back_to_dependency(
    store: CapabilityRequestStore, store_present: bool,
) -> None:
    runtime = _Runtime(
        mcp_server_store=_McpServerStore([]) if store_present else None,
        ensure_result=_EnsureDependencyResult(True),
    )
    request = await store.file_request(
        "agent-1", "install", "numpy", payload={"install_kind": "mcp", "mcp_server_id": "gone"},
    )
    await store.decide(request.id, approve=True)
    assert await fulfil_install(request.id, store=store, target="numpy", runtime=runtime) is None
    assert runtime.ensure_calls == [] and runtime.mcp_bridge.register_calls == []
    assert (await store.get(request.id)).status == "approved"


async def test_enablement_returning_disabled_record_cannot_fulfil(
    store: CapabilityRequestStore, monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _McpRecord(id="selected", name="selected", enabled=False)
    mcp = _McpServerStore([record])
    runtime = _Runtime(mcp_server_store=mcp)

    async def not_enabled(server_id: str, enabled: bool) -> McpServerRecord:
        assert server_id == record.id and enabled is True
        assert runtime.mcp_bridge.get_client(record.url) is not None
        return record

    monkeypatch.setattr(mcp, "set_enabled", not_enabled)
    request = await triage_and_file(gap_target=record.id, agent_id="agent-1", store=store, mcp_server_store=mcp)
    await store.decide(request.id, approve=True)
    assert await fulfil_install(request.id, store=store, target=record.id, runtime=runtime) is None
    assert (await store.get(request.id)).status == "approved"
    assert mcp.list_sync()[0].enabled is False
    assert runtime.mcp_bridge.get_client(record.url) is not None
