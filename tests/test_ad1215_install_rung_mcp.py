"""AD-1215 (#1172): the install rung means "enable a registered MCP server".

Before this, ``skill_known`` was resolved from ``runtime.extension_registry`` —
an attribute nothing in ``src/`` ever assigned — so ``triage()`` could never
return ``install``, and ``fulfil_install`` would have pip-installed a package
named after an extension id. Selection and fulfilment now agree, and both
resolve against ``runtime.mcp_server_store``, which startup/finalize.py really
does assign.
"""
from __future__ import annotations

import pytest

from probos.capability_request import CapabilityRequestStore
from probos.cognitive.capability_triage import (
    fulfil_install,
    resolve_installable_mcp_server,
    triage_and_file,
)


class _McpRecord:
    """Mirrors the McpServerRecord fields the resolver reads."""

    def __init__(self, *, id: str, name: str, enabled: bool) -> None:
        self.id = id
        self.name = name
        self.enabled = enabled


class _McpServerStore:
    """Stands in for McpServerStore with its real ``list_sync`` / ``set_enabled``."""

    def __init__(self, records: list[_McpRecord]) -> None:
        self._records = records
        self.set_enabled_calls: list[tuple[str, bool]] = []

    def list_sync(self) -> list[_McpRecord]:
        return list(self._records)

    async def set_enabled(self, server_id: str, enabled: bool) -> _McpRecord | None:
        self.set_enabled_calls.append((server_id, enabled))
        for rec in self._records:
            if rec.id == server_id:
                rec.enabled = enabled
                return rec
        return None


class _RaisingMcpServerStore:
    def list_sync(self):
        raise RuntimeError("cache unavailable")


class _VanishingMcpServerStore:
    """Resolves a record, then reports it gone — a delete racing the approval."""

    def __init__(self, record: "_McpRecord") -> None:
        self._record = record
        self.set_enabled_calls: list[tuple[str, bool]] = []

    def list_sync(self) -> list["_McpRecord"]:
        return [self._record]

    async def set_enabled(self, server_id: str, enabled: bool) -> None:
        self.set_enabled_calls.append((server_id, enabled))
        return None


class _EnsureDependencyResult:
    def __init__(self, success: bool, error: str | None = None) -> None:
        self.success = success
        self.error = error


class _Runtime:
    """Runtime double carrying only the two attributes fulfil_install reads."""

    def __init__(self, *, mcp_server_store=None, ensure_result=None) -> None:
        self.mcp_server_store = mcp_server_store
        self._ensure_result = ensure_result
        self.ensure_calls: list[tuple[str, bool]] = []

    async def ensure_dependency(self, target: str, *, pre_approved: bool = False):
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


# --------------------------------------------------------------------------- #
# Fulfilment: an approved install enables the server
# --------------------------------------------------------------------------- #
class TestFulfilInstallEnablesMcpServer:
    @pytest.mark.asyncio
    async def test_approved_install_enables_the_server_and_fulfils(self, store) -> None:
        rec = _McpRecord(id="pdf", name="pdf-tools", enabled=False)
        mcp = _McpServerStore([rec])
        req = await store.file_request(
            agent_id="agent-1", kind="install", target="pdf", rationale="needs pdf"
        )
        await store.decide(req.id, approve=True, reason="ok", decided_by="captain")

        out = await fulfil_install(
            req.id, store=store, target="pdf", runtime=_Runtime(mcp_server_store=mcp)
        )

        assert mcp.set_enabled_calls == [("pdf", True)]
        assert rec.enabled is True
        assert out is not None and out.status == "fulfilled"

    @pytest.mark.asyncio
    async def test_server_matched_by_name_is_enabled_by_its_id(self, store) -> None:
        rec = _McpRecord(id="srv-1", name="pdf-tools", enabled=False)
        mcp = _McpServerStore([rec])
        req = await store.file_request(
            agent_id="agent-1", kind="install", target="pdf-tools", rationale=""
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

        Selection and fulfilment share ``resolve_installable_mcp_server``, so a
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
        assert wanted.enabled is True
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
    async def test_enabled_server_is_not_re_enabled_and_falls_through(self, store) -> None:
        """An already-enabled server is not an install; the dependency actor sees it."""
        mcp = _McpServerStore([_McpRecord(id="pdf", name="pdf-tools", enabled=True)])
        runtime = _Runtime(
            mcp_server_store=mcp, ensure_result=_EnsureDependencyResult(False, "no such package")
        )
        req = await store.file_request(
            agent_id="agent-1", kind="install", target="pdf", rationale=""
        )
        await store.decide(req.id, approve=True, reason="ok", decided_by="captain")

        out = await fulfil_install(req.id, store=store, target="pdf", runtime=runtime)

        assert mcp.set_enabled_calls == []
        assert runtime.ensure_calls == [("pdf", True)]
        assert out is None

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
            agent_id="agent-1", kind="install", target="pdf", rationale=""
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
        assert rec.enabled is True
        # And the rung is now correctly closed: the same gap no longer files an install.
        again = await triage_and_file(
            gap_target="pdf", agent_id="agent-1", store=store, mcp_server_store=mcp
        )
        assert again.kind == "build"
