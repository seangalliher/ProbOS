"""AD-1154: the approval inbox — park an unattended ask instead of acting.

No live network and no real Chromium: the ``_FakePage`` / ``_make_session_factory``
stubs come from ``tests/test_ad706_browser_tool.py`` via the AD-1153 suite, so
every assertion here runs offline. Real ``ToolRegistry`` / ``BrowserTool`` /
``CapabilityRequestStore`` / ``ActionApprovalStore`` throughout (BF-287) — the
column order, the migration and the tier ladder are exactly what a mock would
paper over.

Three properties are load-bearing and each has a dedicated section below:

* **Fail CLOSED.** Every failure mode of the wrapper degrades to a refusal,
  never to an admission. The ``is_approved_sync``-raising case is the important
  one: failing open there would admit precisely the action the Captain has not
  approved.
* **The real DB is exercised.** A cache-only suite (``db_path=""``) never runs
  ``_row_to_request``, never runs the migration, and would not catch a column
  order slip — the exact defect class this change introduces.
* **Consensus is not routable around this.** Asserted directly for mesh intents
  and for MCP ``CONSENSUS``-tier tools, not inferred from the tool-id set.
"""

from __future__ import annotations

import inspect
import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

import pytest

from probos.api_models import CapabilityRequestDecideRequest
from probos.capability_request import (
    _ACTION_PAYLOAD_MAX_CHARS,
    CapabilityRequestStore,
    action_dedup_key,
    validate_action_payload,
)
from probos.cognitive.agentic_dispatch import (
    _ALWAYS_TIER_3_ACTIONS,
    _APPROVAL_CREDENTIAL_REFUSAL,
    _APPROVAL_INBOX_FULL_REFUSAL,
    _APPROVAL_INBOX_TOOL_IDS,
    _APPROVAL_PARKED_REFUSAL,
    _APPROVAL_PARKED_REFUSAL_NO_ID,
    _APPROVAL_STANDING_DISPOSITION,
    _BROWSER_LOOP_ACTIONS,
    _NEVER_PARK_ACTIONS,
    DispatchToolExecutor,
    _McpTool,
    _MeshIntentTool,
)
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.cognitive.swe_harness.tool_call import ToolCallResult
from probos.config import ApprovalInboxConfig, BrowserToolConfig, SystemConfig
from probos.integrations.mcp_bridge.risk import McpToolRisk
from probos.routers.capability_requests import (
    _serialize,
    decide_capability_request,
)
from probos.security.audit import AuditLog
from probos.tools.action_approvals import ActionApproval, ActionApprovalStore
from probos.tools.browser.actions import classify_action
from probos.tools.browser.tool import BrowserTool
from probos.tools.protocol import ToolResult
from probos.tools.registry import ToolRegistry

from tests.test_ad706_browser_tool import _FakePage, _make_session_factory

_TIER_3_URL = "https://bank.example/transfer"
_TIER_2_URL = "https://example.com/docs"

# The pre-AD-1154 11-column table, verbatim. Used by the migration test.
_LEGACY_SCHEMA = """
CREATE TABLE IF NOT EXISTS capability_requests (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    target TEXT NOT NULL DEFAULT '',
    rationale TEXT NOT NULL DEFAULT '',
    work_item_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at REAL NOT NULL,
    decided_at REAL,
    decided_by TEXT NOT NULL DEFAULT '',
    decision_reason TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_caprequests_status ON capability_requests(status);
CREATE INDEX IF NOT EXISTS idx_caprequests_agent ON capability_requests(agent_id);
"""


# -- Harness --------------------------------------------------------------


class _CountingBrowserTool(BrowserTool):
    """A REAL ``BrowserTool`` that records every entry into ``invoke``.

    The acceptance criterion is a CALL COUNT, not a result shape: a result-shape
    assertion passes even when the tool actually ran and returned its
    success-shaped ``intervention_required`` no-op.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.invocations: list[dict[str, Any]] = []

    async def invoke(
        self,
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        self.invocations.append(dict(params))
        return await super().invoke(params, context)


def _make_tool(page: _FakePage | None = None) -> _CountingBrowserTool:
    tool = _CountingBrowserTool(
        config=BrowserToolConfig(enabled=True),
        audit_log=AuditLog(),
        emit_event=None,
    )
    tool._session_factory = _make_session_factory(
        page=page or _FakePage(title="Fixture", url="")
    )
    return tool


def _registry_with_browser(tool: BrowserTool) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        tool,
        domain="*",
        tags=["browser", "computer_use"],
        provider="ship_computer",
        enabled=True,
        default_permissions={
            "ensign": "none",
            "lieutenant": "read",
            "commander": "write",
            "senior_officer": "full",
        },
        concurrency="concurrent",
    )
    return registry


def _cfg(**overrides: Any) -> ApprovalInboxConfig:
    base: dict[str, Any] = {"enabled": True}
    base.update(overrides)
    return ApprovalInboxConfig(**base)


async def _store(tmp_path: Path, name: str = "cap.db") -> CapabilityRequestStore:
    store = CapabilityRequestStore(db_path=str(tmp_path / name))
    await store.start()
    return store


async def _approvals(tmp_path: Path, name: str = "aa.db") -> ActionApprovalStore:
    store = ActionApprovalStore(db_path=str(tmp_path / name))
    await store.start()
    return store


async def _armed(
    tmp_path: Path,
    *,
    enabled: bool = True,
    approval_store: Any = None,
    request_store: Any = None,
    page: _FakePage | None = None,
    **cfg_overrides: Any,
) -> tuple[DispatchToolExecutor, _CountingBrowserTool, CapabilityRequestStore]:
    """An executor armed exactly as ``WorkItemAgenticExecutor.run`` arms it."""
    tool = _make_tool(page=page)
    executor = DispatchToolExecutor(registry=_registry_with_browser(tool))
    store = request_store if request_store is not None else await _store(tmp_path)
    if enabled:
        executor.arm_approval_inbox(
            request_store=store,
            approval_store=approval_store,
            config=_cfg(**cfg_overrides),
        )
    return executor, tool, store


async def _open_session(
    executor: DispatchToolExecutor, tool: _CountingBrowserTool, url: str
) -> str:
    """Navigate once so a real session exists with ``last_url == url``."""
    nav = await tool.invoke({"action": "goto", "url": url}, {"agent_id": "agent-a"})
    tool.invocations.clear()
    return nav.metadata["session_id"]


async def _invoke(
    executor: DispatchToolExecutor,
    params: dict[str, Any],
    *,
    agent_id: str = "agent-a",
    tool_id: str = "browser",
) -> ToolResult:
    return await executor.invoke(
        agent_id,
        tool_id,
        params,
        agent_department="engineering",
        agent_rank="commander",
    )


def _payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "tool_id": "browser",
        "action": "click",
        "params": {"index": 0},
        "scope_key": "github.com",
        "session_id": "sess-1",
        "thread_id": "thread-1",
    }
    base.update(overrides)
    return base


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class _FakeRuntime:
    """Minimal runtime double for the router's standing-rule branch."""

    def __init__(self, *, store: Any, approvals: Any = None, config: Any = None) -> None:
        self.capability_request_store = store
        self.action_approval_store = approvals
        self.config = config


# -- Headline: park, refuse honestly, never enter the tool ----------------


class TestHeadline:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("enabled", [True, False])
    async def test_tier_3_click_parks_only_when_the_flag_is_on(
        self, tmp_path, enabled
    ):
        """Same body, one flag flipped — the whole feature in one test."""
        # Arrange
        page = _FakePage(list_elements=[{"role": "button", "text": "Pay now"}])
        executor, tool, store = await _armed(tmp_path, enabled=enabled, page=page)
        try:
            sid = await _open_session(executor, tool, _TIER_3_URL)
            # Act
            result = await _invoke(
                executor, {"action": "click", "index": 0, "session_id": sid}
            )
            pending = await store.list_pending()
            # Assert
            if enabled:
                assert len(pending) == 1
                assert pending[0].kind == "action"
                assert pending[0].payload["tool_id"] == "browser"
                assert pending[0].payload["action"] == "click"
                assert pending[0].payload["scope_key"] == "bank.example"
                assert pending[0].payload["params"] == {"index": 0, "session_id": sid}
                assert result.error is not None
                assert ToolCallResult.from_tool_result(
                    "call-1", result, 1.0
                ).is_error is True
                # The load-bearing assertion: a call COUNT, not a result shape.
                assert tool.invocations == []
            else:
                assert pending == []
                assert len(tool.invocations) == 1
                # HEAD's behaviour: a SUCCESS-shaped intervention_required no-op.
                assert result.error is None
                assert result.output["intervention_required"] is True
        finally:
            await store.stop()
            await tool.stop()

    @pytest.mark.asyncio
    async def test_tier_2_action_is_never_parked(self, tmp_path):
        # Arrange
        executor, tool, store = await _armed(tmp_path)
        try:
            sid = await _open_session(executor, tool, _TIER_2_URL)
            # Act
            result = await _invoke(
                executor, {"action": "extract_text", "session_id": sid}
            )
            # Assert
            assert await store.list_pending() == []
            assert len(tool.invocations) == 1
            assert result.error is None
        finally:
            await store.stop()
            await tool.stop()


# -- Durability (DD-1): the real DB, the migration, the payload -----------


class TestDurability:
    @pytest.mark.asyncio
    async def test_real_db_round_trip_preserves_payload_byte_identically(
        self, tmp_path
    ):
        """The mandatory round trip: it is what exercises _row_to_request."""
        # Arrange
        db = str(tmp_path / "persist.db")
        payload = _payload(params={"index": 3, "selector": "#pay", "note": "é"})
        s1 = CapabilityRequestStore(db_path=db)
        await s1.start()
        req = await s1.file_action_request("agent-a", dict(payload))
        await s1.stop()
        # Act — a SECOND store instance on the same file
        s2 = CapabilityRequestStore(db_path=db)
        await s2.start()
        try:
            restored = await s2.get(req.id)
            # Assert
            assert restored is not None
            assert restored.kind == "action"
            assert _canonical(restored.payload) == _canonical(payload)
        finally:
            await s2.stop()

    @pytest.mark.asyncio
    async def test_legacy_eleven_column_schema_migrates_on_start(self, tmp_path):
        """CREATE TABLE IF NOT EXISTS is a no-op here; the ALTER is required."""
        # Arrange — a DB carrying the pre-AD-1154 11-column table and one row
        db = str(tmp_path / "legacy.db")
        conn = sqlite3.connect(db)
        conn.executescript(_LEGACY_SCHEMA)
        conn.execute(
            "INSERT INTO capability_requests VALUES "
            "('old-1','agent-z','grant','shell','needs it',NULL,'pending',1.0,"
            "NULL,'','')"
        )
        conn.commit()
        conn.close()
        # Act
        store = CapabilityRequestStore(db_path=db)
        await store.start()
        try:
            columns = [
                row[1]
                for row in sqlite3.connect(db).execute(
                    "PRAGMA table_info(capability_requests)"
                )
            ]
            legacy = await store.get("old-1")
            # A write must now succeed against the migrated table.
            fresh = await store.file_action_request("agent-a", _payload())
            # Assert
            assert columns[-1] == "payload"
            assert len(columns) == 12
            assert legacy is not None
            assert legacy.payload is None
            assert legacy.status == "pending"
            assert fresh is not None
            assert fresh.payload["action"] == "click"
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_migration_is_idempotent_across_restarts(self, tmp_path):
        # Arrange
        db = str(tmp_path / "twice.db")
        s1 = CapabilityRequestStore(db_path=db)
        await s1.start()
        await s1.stop()
        # Act
        s2 = CapabilityRequestStore(db_path=db)
        await s2.start()
        try:
            columns = [
                row[1]
                for row in sqlite3.connect(db).execute(
                    "PRAGMA table_info(capability_requests)"
                )
            ]
            # Assert
            assert columns.count("payload") == 1
        finally:
            await s2.stop()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "raw",
        [
            "{not json",
            '"a string"',
            '["a", "list"]',
            '{"tool_id":"browser","action":"click","params":{},"scope_key":""}',
            '{"tool_id":"browser","action":"click","params":{},"scope_key":"",'
            '"session_id":null,"thread_id":"t","extra":1}',
            '{"tool_id":"BROWSER!","action":"click","params":{},"scope_key":"",'
            '"session_id":null,"thread_id":"t"}',
        ],
        ids=[
            "invalid_json",
            "non_dict_string",
            "non_dict_list",
            "missing_key",
            "extra_key",
            "bad_tool_id",
        ],
    )
    async def test_corrupt_payload_row_loads_as_none_without_blocking_start(
        self, tmp_path, caplog, raw
    ):
        """A hand-edited DB is an untrusted input; it must not stop the store."""
        # Arrange
        db = str(tmp_path / "corrupt.db")
        seed = CapabilityRequestStore(db_path=db)
        await seed.start()
        good = await seed.file_action_request("agent-good", _payload())
        bad = await seed.file_request("agent-bad", "grant", "shell")
        await seed.stop()
        conn = sqlite3.connect(db)
        conn.execute(
            "UPDATE capability_requests SET kind='action', payload=? WHERE id=?",
            (raw, bad.id),
        )
        conn.commit()
        conn.close()
        # Act
        store = CapabilityRequestStore(db_path=db)
        with caplog.at_level(logging.WARNING):
            await store.start()
        try:
            # Assert
            assert (await store.get(bad.id)).payload is None
            assert _canonical((await store.get(good.id)).payload) == _canonical(
                _payload()
            )
            assert any("payload" in r.message for r in caplog.records)
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_oversized_params_row_loads_as_none(self, tmp_path):
        # Arrange
        db = str(tmp_path / "oversize.db")
        seed = CapabilityRequestStore(db_path=db)
        await seed.start()
        row = await seed.file_request("agent-bad", "grant", "shell")
        await seed.stop()
        oversized = _canonical(_payload(params={"blob": "x" * 5000}))
        conn = sqlite3.connect(db)
        conn.execute(
            "UPDATE capability_requests SET kind='action', payload=? WHERE id=?",
            (oversized, row.id),
        )
        conn.commit()
        conn.close()
        # Act
        store = CapabilityRequestStore(db_path=db)
        await store.start()
        try:
            # Assert
            assert len(oversized) > _ACTION_PAYLOAD_MAX_CHARS
            assert (await store.get(row.id)).payload is None
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_confirmation_token_is_absent_from_the_persisted_payload(
        self, tmp_path
    ):
        """Asserted on the RELOADED row, not on the in-memory object."""
        # Arrange
        page = _FakePage(list_elements=[{"role": "button", "text": "Pay now"}])
        db = str(tmp_path / "token.db")
        store = CapabilityRequestStore(db_path=db)
        await store.start()
        executor, tool, _ = await _armed(
            tmp_path, request_store=store, page=page
        )
        try:
            sid = await _open_session(executor, tool, _TIER_3_URL)
            # Act
            await _invoke(
                executor,
                {
                    "action": "click",
                    "index": 0,
                    "session_id": sid,
                    "confirmation_token": "tok-secret-value",
                },
            )
            await store.stop()
            reopened = CapabilityRequestStore(db_path=db)
            await reopened.start()
            pending = await reopened.list_pending()
            raw = sqlite3.connect(db).execute(
                "SELECT payload FROM capability_requests"
            ).fetchone()[0]
            # Assert
            assert len(pending) == 1
            assert "confirmation_token" not in pending[0].payload["params"]
            assert "tok-secret-value" not in raw
            await reopened.stop()
        finally:
            await tool.stop()

    @pytest.mark.asyncio
    async def test_existing_kinds_still_write_a_null_payload(self, tmp_path):
        # Arrange
        db = str(tmp_path / "nulls.db")
        store = CapabilityRequestStore(db_path=db)
        await store.start()
        try:
            # Act
            for kind, target in (
                ("grant", "shell"),
                ("install", "httpx"),
                ("build", "WeatherAgent"),
            ):
                await store.file_request("agent-a", kind, target)
            rows = sqlite3.connect(db).execute(
                "SELECT kind, payload FROM capability_requests"
            ).fetchall()
            # Assert
            assert len(rows) == 3
            assert all(payload is None for _kind, payload in rows)
        finally:
            await store.stop()


# -- Dedup (DD-1) ---------------------------------------------------------


class TestDedup:
    @pytest.mark.asyncio
    async def test_three_identical_parks_file_one_row_and_share_an_id(
        self, tmp_path
    ):
        # Arrange
        page = _FakePage(list_elements=[{"role": "button", "text": "Pay now"}])
        db = str(tmp_path / "dedup.db")
        store = CapabilityRequestStore(db_path=db)
        await store.start()
        executor, tool, _ = await _armed(tmp_path, request_store=store, page=page)
        try:
            sid = await _open_session(executor, tool, _TIER_3_URL)
            params = {"action": "click", "index": 0, "session_id": sid}
            # Act
            results = [await _invoke(executor, dict(params)) for _ in range(3)]
            rows = sqlite3.connect(db).execute(
                "SELECT COUNT(*) FROM capability_requests"
            ).fetchone()[0]
            request_id = (await store.list_pending())[0].id
            # Assert
            assert rows == 1
            assert all(request_id in r.error for r in results)
            assert tool.invocations == []
        finally:
            await store.stop()
            await tool.stop()

    @pytest.mark.asyncio
    async def test_differing_scope_key_does_not_collapse(self, tmp_path):
        # Arrange
        store = await _store(tmp_path)
        try:
            # Act
            a = await store.file_action_request("agent-a", _payload())
            b = await store.file_action_request(
                "agent-a", _payload(scope_key="docs.github.com")
            )
            # Assert
            assert a.id != b.id
            assert len(await store.list_pending()) == 2
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_differing_params_does_not_collapse(self, tmp_path):
        # Arrange
        store = await _store(tmp_path)
        try:
            # Act
            a = await store.file_action_request("agent-a", _payload())
            b = await store.file_action_request(
                "agent-a", _payload(params={"index": 7})
            )
            # Assert
            assert a.id != b.id
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_an_approved_request_does_not_absorb_a_new_ask(self, tmp_path):
        # Arrange
        store = await _store(tmp_path)
        try:
            first = await store.file_action_request("agent-a", _payload())
            await store.decide(first.id, approve=True, reason="ok")
            # Act
            second = await store.file_action_request("agent-a", _payload())
            # Assert
            assert second.id != first.id
            assert second.status == "pending"
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_a_denied_request_does_not_absorb_a_new_ask(self, tmp_path):
        # Arrange
        store = await _store(tmp_path)
        try:
            first = await store.file_action_request("agent-a", _payload())
            await store.decide(first.id, approve=False, reason="no")
            # Act
            second = await store.file_action_request("agent-a", _payload())
            # Assert
            assert second.id != first.id
        finally:
            await store.stop()

    def test_dedup_key_is_stable_and_scope_sensitive(self):
        # Arrange / Act
        base = action_dedup_key(
            agent_id="a", payload=_payload(), work_item_id=None
        )
        same = action_dedup_key(
            agent_id="a", payload=_payload(), work_item_id=None
        )
        other_scope = action_dedup_key(
            agent_id="a", payload=_payload(scope_key="x.com"), work_item_id=None
        )
        other_work_item = action_dedup_key(
            agent_id="a", payload=_payload(), work_item_id="wi-1"
        )
        # Assert
        assert base == same
        assert base != other_scope
        assert base != other_work_item

    def test_dedup_key_degrades_rather_than_raising_on_bad_params(self):
        # Arrange / Act
        key = action_dedup_key(
            agent_id="a",
            payload={"tool_id": "browser", "action": "click", "params": {1: object()}},
            work_item_id=None,
        )
        # Assert
        assert len(key) == 64


# -- Payload bounds (DD-1) ------------------------------------------------


class TestPayloadBounds:
    @pytest.mark.parametrize(
        "payload",
        [
            _payload(params={f"k{i}": i for i in range(21)}),
            _payload(params={1: "a"}),
            _payload(params={"v": object()}),
            _payload(params={"blob": "x" * 5000}),
            _payload(tool_id="BROWSER!"),
            _payload(tool_id=""),
            _payload(action="Click"),
            _payload(action=""),
            _payload(scope_key="x" * 254),
            _payload(session_id="s" * 65),
            _payload(thread_id="t" * 65),
            _payload(params="not-a-dict"),
            _payload(tool_id=None),
            "not-a-dict",
        ],
        ids=[
            "21_param_keys",
            "non_str_param_key",
            "non_serialisable_value",
            "oversized_serialised_form",
            "tool_id_fails_regex",
            "empty_tool_id",
            "action_uppercase",
            "empty_action",
            "scope_key_too_long",
            "session_id_too_long",
            "thread_id_too_long",
            "params_not_a_dict",
            "tool_id_not_a_str",
            "payload_not_a_dict",
        ],
    )
    def test_invalid_payloads_are_rejected_without_raising(self, payload):
        # Act
        result = validate_action_payload(payload)
        # Assert
        assert result is None

    def test_a_well_formed_payload_validates(self):
        assert validate_action_payload(_payload()) is not None

    def test_a_null_session_id_is_accepted(self):
        assert validate_action_payload(_payload(session_id=None)) is not None

    @pytest.mark.asyncio
    async def test_an_invalid_payload_files_nothing_and_returns_none(
        self, tmp_path
    ):
        # Arrange
        store = await _store(tmp_path)
        try:
            # Act
            result = await store.file_action_request(
                "agent-a", _payload(tool_id="NOPE!")
            )
            # Assert
            assert result is None
            assert await store.list_pending() == []
        finally:
            await store.stop()


# -- Agent-facing text (DD-2) ---------------------------------------------


class TestAgentFacingText:
    @pytest.mark.parametrize(
        "rendered",
        [
            _APPROVAL_PARKED_REFUSAL.format(
                request_id="3f2b1c9e-2a44-4c19-9c6f-77b0d1e5a812"
            ),
            _APPROVAL_PARKED_REFUSAL_NO_ID,
            _APPROVAL_INBOX_FULL_REFUSAL,
            _APPROVAL_CREDENTIAL_REFUSAL,
            _APPROVAL_STANDING_DISPOSITION.format(expiry="2026-07-27 14:05 UTC"),
        ],
        ids=["parked", "parked_no_id", "inbox_full", "credential", "standing"],
    )
    def test_every_authored_string_is_clean_under_the_real_gap_regex(
        self, rendered
    ):
        """The REAL imported regex, never a re-typed copy, which would drift.

        BF-707 narrowed this from a substring match to whole words, so an
        ordinary word like ``blacklist`` no longer trips it. The guard still
        matters: a genuine refusal phrasing in authored text would.
        """
        # Assert
        assert _CAPABILITY_GAP_RE.search(rendered) is None

    def test_the_gap_regex_would_catch_a_careless_reword(self):
        """Proves the guard above has teeth rather than always passing.

        BF-707: this used to assert that ``the browser blacklist refused it``
        matched -- true only because ``lack`` matched inside ``blacklist``. A
        teeth test resting on that defect passes a broken regex and fails the
        fix. A real reword is the honest proof, and ``blacklist`` now
        demonstrates the opposite half of the property.
        """
        assert _CAPABILITY_GAP_RE.search("the browser cannot reach that page")
        assert _CAPABILITY_GAP_RE.search("it lacks permission for that")
        assert _CAPABILITY_GAP_RE.search("the browser blacklist refused it") is None

    @pytest.mark.asyncio
    async def test_a_parked_refusal_names_the_request_and_never_says_success(
        self, tmp_path
    ):
        # Arrange
        page = _FakePage(list_elements=[{"role": "button", "text": "Pay now"}])
        executor, tool, store = await _armed(tmp_path, page=page)
        try:
            sid = await _open_session(executor, tool, _TIER_3_URL)
            # Act
            result = await _invoke(
                executor, {"action": "click", "index": 0, "session_id": sid}
            )
            request_id = (await store.list_pending())[0].id
            # Assert
            assert request_id in result.error
            assert "intervention_required" not in result.error
            assert result.output is None
        finally:
            await store.stop()
            await tool.stop()

    @pytest.mark.asyncio
    async def test_the_parked_result_is_error_shaped_through_the_real_adapter(
        self, tmp_path
    ):
        # Arrange
        page = _FakePage(list_elements=[{"role": "button", "text": "Pay now"}])
        executor, tool, store = await _armed(tmp_path, page=page)
        try:
            sid = await _open_session(executor, tool, _TIER_3_URL)
            # Act
            result = await _invoke(
                executor, {"action": "click", "index": 0, "session_id": sid}
            )
            adapted = ToolCallResult.from_tool_result("call-9", result, 1.0)
            # Assert
            assert adapted.is_error is True
        finally:
            await store.stop()
            await tool.stop()


# -- Credentials are never parked (DD-1) ----------------------------------


class TestCredentials:
    @pytest.mark.asyncio
    async def test_fill_credential_is_refused_without_filing(self, tmp_path):
        # Arrange
        executor, tool, store = await _armed(tmp_path)
        try:
            # Act — no session needed: fill_credential is ALWAYS tier 3.
            result = await _invoke(
                executor, {"action": "fill_credential", "selector": "#pw"}
            )
            # Assert
            assert result.error == _APPROVAL_CREDENTIAL_REFUSAL
            assert await store.list_pending() == []
            assert tool.invocations == []
        finally:
            await store.stop()
            await tool.stop()

    @pytest.mark.asyncio
    async def test_a_standing_rule_cannot_cover_fill_credential(self, tmp_path):
        """A per-call human gate must never become a stored credential grant."""
        # Arrange
        approvals = await _approvals(tmp_path)
        await approvals.issue_approval(
            "agent-a", "browser", "fill_credential", scope_key="", ttl_seconds=3600
        )
        executor, tool, store = await _armed(
            tmp_path,
            approval_store=approvals,
            standing_rules_enabled=True,
        )
        try:
            # Act
            result = await _invoke(executor, {"action": "fill_credential"})
            # Assert
            assert result.error == _APPROVAL_CREDENTIAL_REFUSAL
            assert tool.invocations == []
            assert await store.list_pending() == []
        finally:
            await approvals.stop()
            await store.stop()
            await tool.stop()

    def test_never_park_actions_is_the_credential_verb_only(self):
        assert _NEVER_PARK_ACTIONS == frozenset({"fill_credential"})


# -- Resolution (DD-3): a decision, never a replay ------------------------


class TestResolution:
    @pytest.mark.asyncio
    async def test_approving_an_action_never_touches_the_browser(self, tmp_path):
        """The C-8 property, and the one a future refactor will try to improve
        away: approval unblocks the NEXT run, not this one."""
        # Arrange
        store = await _store(tmp_path)
        tool = _make_tool()
        runtime = _FakeRuntime(store=store, config=SystemConfig())
        request = await store.file_action_request("agent-a", _payload())
        try:
            # Act
            response = await decide_capability_request(
                request.id,
                CapabilityRequestDecideRequest(approve=True, reason="ok"),
                runtime=runtime,
            )
            # Assert
            assert response["request"]["status"] == "approved"
            assert response["request"]["payload"]["session_id"] == "sess-1"
            # No browser call at all — so the recorded session_id was never used.
            assert tool.invocations == []
            assert tool.session_count == 0
        finally:
            await store.stop()
            await tool.stop()

    @pytest.mark.asyncio
    async def test_approving_does_not_redispatch_the_work_item(self, tmp_path):
        # Arrange
        store = await _store(tmp_path)
        runtime = _FakeRuntime(store=store, config=SystemConfig())
        request = await store.file_action_request(
            "agent-a", _payload(), work_item_id="wi-1"
        )
        calls: list[Any] = []

        from probos.cognitive import agentic_dispatch as module

        original = module.WorkItemAgenticExecutor.run

        async def _spy(self: Any, **kwargs: Any) -> Any:  # pragma: no cover
            calls.append(kwargs)
            return await original(self, **kwargs)

        module.WorkItemAgenticExecutor.run = _spy
        try:
            # Act
            await decide_capability_request(
                request.id,
                CapabilityRequestDecideRequest(approve=True, reason="ok"),
                runtime=runtime,
            )
            # Assert
            assert calls == []
        finally:
            module.WorkItemAgenticExecutor.run = original
            await store.stop()

    @pytest.mark.asyncio
    async def test_grant_standing_issues_one_scoped_expiring_rule(self, tmp_path):
        # Arrange
        store = await _store(tmp_path)
        approvals = await _approvals(tmp_path)
        config = SystemConfig()
        config.approval_inbox = _cfg(standing_rules_enabled=True)
        runtime = _FakeRuntime(store=store, approvals=approvals, config=config)
        request = await store.file_action_request("agent-a", _payload())
        before = time.time()
        try:
            # Act
            response = await decide_capability_request(
                request.id,
                CapabilityRequestDecideRequest(
                    approve=True, reason="ok", grant_standing=True
                ),
                runtime=runtime,
            )
            issued = await approvals.list_approvals(active_only=True)
            # Assert
            assert response["standing_rule"] is not None
            assert len(issued) == 1
            assert issued[0].agent_id == "agent-a"
            assert issued[0].tool_id == "browser"
            assert issued[0].action == "click"
            assert issued[0].scope_key == "github.com"
            assert issued[0].expires_at > before
            assert issued[0].expires_at <= (
                before + config.approval_inbox.standing_rule_max_ttl_hours * 3600 + 5
            )
        finally:
            await approvals.stop()
            await store.stop()

    @pytest.mark.asyncio
    async def test_an_oversized_ttl_is_clamped_to_the_max(self, tmp_path):
        # Arrange
        store = await _store(tmp_path)
        approvals = await _approvals(tmp_path)
        config = SystemConfig()
        config.approval_inbox = _cfg(
            standing_rules_enabled=True, standing_rule_max_ttl_hours=2
        )
        runtime = _FakeRuntime(store=store, approvals=approvals, config=config)
        request = await store.file_action_request("agent-a", _payload())
        ceiling = time.time() + 2 * 3600 + 5
        try:
            # Act
            await decide_capability_request(
                request.id,
                CapabilityRequestDecideRequest(
                    approve=True,
                    reason="ok",
                    grant_standing=True,
                    standing_ttl_hours=720,
                ),
                runtime=runtime,
            )
            issued = await approvals.list_approvals(active_only=True)
            # Assert
            assert issued[0].expires_at <= ceiling
        finally:
            await approvals.stop()
            await store.stop()

    @pytest.mark.asyncio
    async def test_grant_standing_is_a_200_noop_when_the_flag_is_off(
        self, tmp_path
    ):
        # Arrange
        store = await _store(tmp_path)
        approvals = await _approvals(tmp_path)
        config = SystemConfig()
        config.approval_inbox = _cfg(standing_rules_enabled=False)
        runtime = _FakeRuntime(store=store, approvals=approvals, config=config)
        request = await store.file_action_request("agent-a", _payload())
        try:
            # Act
            response = await decide_capability_request(
                request.id,
                CapabilityRequestDecideRequest(
                    approve=True, reason="ok", grant_standing=True
                ),
                runtime=runtime,
            )
            # Assert
            assert response["standing_rule"] is None
            assert response["request"]["status"] == "approved"
            assert await approvals.list_approvals(active_only=False) == []
        finally:
            await approvals.stop()
            await store.stop()

    @pytest.mark.asyncio
    async def test_a_missing_store_degrades_to_200_and_no_rule(self, tmp_path):
        # Arrange
        store = await _store(tmp_path)
        config = SystemConfig()
        config.approval_inbox = _cfg(standing_rules_enabled=True)
        runtime = _FakeRuntime(store=store, approvals=None, config=config)
        request = await store.file_action_request("agent-a", _payload())
        try:
            # Act
            response = await decide_capability_request(
                request.id,
                CapabilityRequestDecideRequest(
                    approve=True, reason="ok", grant_standing=True
                ),
                runtime=runtime,
            )
            # Assert
            assert response["standing_rule"] is None
            assert response["request"]["status"] == "approved"
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_grant_standing_on_a_grant_kind_is_ignored(self, tmp_path):
        # Arrange
        store = await _store(tmp_path)
        approvals = await _approvals(tmp_path)
        config = SystemConfig()
        config.approval_inbox = _cfg(standing_rules_enabled=True)
        runtime = _FakeRuntime(store=store, approvals=approvals, config=config)
        request = await store.file_request("agent-a", "grant", "shell")
        try:
            # Act
            response = await decide_capability_request(
                request.id,
                CapabilityRequestDecideRequest(
                    approve=True, reason="ok", grant_standing=True
                ),
                runtime=runtime,
            )
            # Assert
            assert response["standing_rule"] is None
            assert response["request"]["status"] == "approved"
            assert response["request"]["payload"] is None
            assert await approvals.list_approvals(active_only=False) == []
        finally:
            await approvals.stop()
            await store.stop()

    @pytest.mark.asyncio
    async def test_a_denial_issues_no_rule_even_with_grant_standing(
        self, tmp_path
    ):
        # Arrange
        store = await _store(tmp_path)
        approvals = await _approvals(tmp_path)
        config = SystemConfig()
        config.approval_inbox = _cfg(standing_rules_enabled=True)
        runtime = _FakeRuntime(store=store, approvals=approvals, config=config)
        request = await store.file_action_request("agent-a", _payload())
        try:
            # Act
            response = await decide_capability_request(
                request.id,
                CapabilityRequestDecideRequest(
                    approve=False, reason="not this one", grant_standing=True
                ),
                runtime=runtime,
            )
            # Assert
            assert response["request"]["status"] == "denied"
            assert response["standing_rule"] is None
            assert await approvals.list_approvals(active_only=False) == []
        finally:
            await approvals.stop()
            await store.stop()

    def test_a_denial_still_requires_a_reason(self):
        # Act / Assert
        with pytest.raises(ValueError):
            CapabilityRequestDecideRequest(approve=False, reason="   ")

    def test_the_decide_body_defaults_are_backward_compatible(self):
        # Act
        body = CapabilityRequestDecideRequest(approve=True)
        # Assert
        assert body.grant_standing is False
        assert body.standing_ttl_hours is None

    @pytest.mark.asyncio
    async def test_deciding_an_already_decided_request_still_returns_400(
        self, tmp_path
    ):
        # BF-722 UPDATED THIS TEST. It used to approve the request and then
        # assert that re-approving it raised 400 — which pinned the defect as
        # the contract. ``_maybe_fulfil_on_approval`` honest-degrades to False
        # when fulfilment fails, so a blanket already-decided guard consumed
        # the only retry the Captain had for an approval that never took
        # effect. Re-approving an ``approved`` request is now a retry of the
        # FULFILMENT (200), not a re-decision.
        #
        # The guard itself still has teeth, so the case moved to ``denied``:
        # a denial is not re-decidable here, and re-approving one would be a
        # reversal rather than a retry.
        from fastapi import HTTPException

        # Arrange
        store = await _store(tmp_path)
        runtime = _FakeRuntime(store=store, config=SystemConfig())
        request = await store.file_action_request("agent-a", _payload())
        await store.decide(request.id, approve=False, reason="no")
        try:
            # Act / Assert
            with pytest.raises(HTTPException) as excinfo:
                await decide_capability_request(
                    request.id,
                    CapabilityRequestDecideRequest(approve=True, reason="again"),
                    runtime=runtime,
                )
            assert excinfo.value.status_code == 400
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_re_approving_an_approved_request_retries_the_fulfilment(
        self, tmp_path
    ):
        """BF-722: the case the blanket guard used to refuse.

        An ``action`` request has no fulfiller, so the retry reports
        ``fulfilled=False`` — 'approved, fulfilment pending' — rather than 400.
        """
        # Arrange
        store = await _store(tmp_path)
        runtime = _FakeRuntime(store=store, config=SystemConfig())
        request = await store.file_action_request("agent-a", _payload())
        await store.decide(request.id, approve=True, reason="ok")
        try:
            # Act
            response = await decide_capability_request(
                request.id,
                CapabilityRequestDecideRequest(approve=True, reason="again"),
                runtime=runtime,
            )
            # Assert
            assert response["request"]["status"] == "approved"
            assert response["fulfilled"] is False
            # The retry must not re-decide: the original decision stands.
            assert response["request"]["decision_reason"] == "ok"
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_serialize_carries_the_payload_for_the_captain(self, tmp_path):
        # Arrange
        store = await _store(tmp_path)
        try:
            request = await store.file_action_request("agent-a", _payload())
            # Act
            wire = _serialize(request)
            # Assert
            assert wire["kind"] == "action"
            assert wire["payload"]["action"] == "click"
            assert wire["target"] == "browser.click @ github.com"
        finally:
            await store.stop()


# -- Standing rules (DD-4) ------------------------------------------------


class TestStandingRules:
    @pytest.mark.asyncio
    async def test_a_matching_rule_admits_and_carries_the_disposition(
        self, tmp_path
    ):
        # Arrange
        page = _FakePage(list_elements=[{"role": "button", "text": "Pay now"}])
        approvals = await _approvals(tmp_path)
        executor, tool, store = await _armed(
            tmp_path,
            approval_store=approvals,
            standing_rules_enabled=True,
            page=page,
        )
        try:
            sid = await _open_session(executor, tool, _TIER_3_URL)
            await approvals.issue_approval(
                "agent-a",
                "browser",
                "click",
                scope_key="bank.example",
                ttl_seconds=3600,
            )
            # Act
            result = await _invoke(
                executor, {"action": "click", "index": 0, "session_id": sid}
            )
            # Assert — the TOOL IS ENTERED; what it then does is its own business.
            assert len(tool.invocations) == 1
            assert await store.list_pending() == []
            assert "standing approval" in result.output["disposition"]
        finally:
            await approvals.stop()
            await store.stop()
            await tool.stop()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "agent_id,tool_id,action,scope_key",
        [
            ("other-agent", "browser", "click", "bank.example"),
            ("agent-a", "other_tool", "click", "bank.example"),
            ("agent-a", "browser", "type", "bank.example"),
            ("agent-a", "browser", "click", "docs.bank.example"),
        ],
        ids=["agent", "tool", "action", "scope_sibling_domain"],
    )
    async def test_a_mismatch_on_any_one_field_still_parks(
        self, tmp_path, agent_id, tool_id, action, scope_key
    ):
        """Four fields, four tests. The scope case uses a SIBLING domain so a
        suffix match would be caught."""
        # Arrange
        page = _FakePage(list_elements=[{"role": "button", "text": "Pay now"}])
        approvals = await _approvals(tmp_path)
        executor, tool, store = await _armed(
            tmp_path,
            approval_store=approvals,
            standing_rules_enabled=True,
            page=page,
        )
        try:
            sid = await _open_session(executor, tool, _TIER_3_URL)
            await approvals.issue_approval(
                agent_id, tool_id, action, scope_key=scope_key, ttl_seconds=3600
            )
            # Act
            result = await _invoke(
                executor, {"action": "click", "index": 0, "session_id": sid}
            )
            # Assert
            assert tool.invocations == []
            assert len(await store.list_pending()) == 1
            assert result.error is not None
        finally:
            await approvals.stop()
            await store.stop()
            await tool.stop()

    @pytest.mark.asyncio
    async def test_an_empty_scope_rule_is_not_a_wildcard(self, tmp_path):
        # Arrange
        approvals = await _approvals(tmp_path)
        try:
            await approvals.issue_approval(
                "agent-a", "browser", "click", scope_key="", ttl_seconds=3600
            )
            # Act / Assert
            assert approvals.is_approved_sync(
                "agent-a", "browser", "click", ""
            ) is True
            assert approvals.is_approved_sync(
                "agent-a", "browser", "click", "github.com"
            ) is False
        finally:
            await approvals.stop()

    @pytest.mark.asyncio
    async def test_an_expired_rule_does_not_admit(self, tmp_path):
        # Arrange
        approvals = await _approvals(tmp_path)
        try:
            await approvals.issue_approval(
                "agent-a", "browser", "click", scope_key="x.com", ttl_seconds=-1
            )
            # Act / Assert
            assert approvals.is_approved_sync(
                "agent-a", "browser", "click", "x.com"
            ) is False
        finally:
            await approvals.stop()

    @pytest.mark.asyncio
    async def test_a_revoked_rule_does_not_admit(self, tmp_path):
        # Arrange
        approvals = await _approvals(tmp_path)
        try:
            issued = await approvals.issue_approval(
                "agent-a", "browser", "click", scope_key="x.com", ttl_seconds=3600
            )
            # Act
            revoked = await approvals.revoke_approval(issued.id)
            # Assert
            assert revoked is True
            assert approvals.is_approved_sync(
                "agent-a", "browser", "click", "x.com"
            ) is False
        finally:
            await approvals.stop()

    @pytest.mark.asyncio
    async def test_revoking_an_unknown_rule_returns_false(self, tmp_path):
        # Arrange
        approvals = await _approvals(tmp_path)
        try:
            # Act / Assert
            assert await approvals.revoke_approval("nope") is False
        finally:
            await approvals.stop()

    def test_issue_approval_has_no_parameter_that_yields_a_null_expiry(self):
        """The TTL invariant is carried by the type system, not by convention."""
        # Act
        signature = inspect.signature(ActionApprovalStore.issue_approval)
        ttl = signature.parameters["ttl_seconds"]
        # Assert
        assert "expires_at" not in signature.parameters
        assert ttl.kind is inspect.Parameter.KEYWORD_ONLY
        assert ttl.default is inspect.Parameter.empty
        assert ttl.annotation == "float"

    @pytest.mark.asyncio
    async def test_the_schema_declares_expires_at_not_null(self, tmp_path):
        """Enforced in the SCHEMA so a future caller cannot bypass it."""
        # Arrange
        db = str(tmp_path / "notnull.db")
        approvals = ActionApprovalStore(db_path=db)
        await approvals.start()
        try:
            # Act
            columns = {
                row[1]: row[3]
                for row in sqlite3.connect(db).execute(
                    "PRAGMA table_info(action_approvals)"
                )
            }
            # Assert
            assert columns["expires_at"] == 1
            with pytest.raises(sqlite3.IntegrityError):
                conn = sqlite3.connect(db)
                conn.execute(
                    "INSERT INTO action_approvals "
                    "(id, agent_id, tool_id, action, scope_key, reason, "
                    "issued_by, issued_at, expires_at, revoked, revoked_at) "
                    "VALUES ('x','a','browser','click','','','captain',1.0,"
                    "NULL,0,NULL)"
                )
                conn.commit()
        finally:
            await approvals.stop()

    @pytest.mark.asyncio
    async def test_action_approval_store_round_trips_through_a_real_db(
        self, tmp_path
    ):
        # Arrange
        db = str(tmp_path / "aa_persist.db")
        s1 = ActionApprovalStore(db_path=db)
        await s1.start()
        await s1.issue_approval(
            "agent-a", "browser", "click", scope_key="github.com", ttl_seconds=3600
        )
        await s1.stop()
        # Act
        s2 = ActionApprovalStore(db_path=db)
        await s2.start()
        try:
            # Assert
            assert s2.is_approved_sync(
                "agent-a", "browser", "click", "github.com"
            ) is True
        finally:
            await s2.stop()

    @pytest.mark.asyncio
    async def test_expired_rows_are_not_reloaded_into_the_cache(self, tmp_path):
        # Arrange
        db = str(tmp_path / "aa_expired.db")
        s1 = ActionApprovalStore(db_path=db)
        await s1.start()
        await s1.issue_approval(
            "agent-a", "browser", "click", scope_key="x.com", ttl_seconds=-5
        )
        await s1.stop()
        # Act
        s2 = ActionApprovalStore(db_path=db)
        await s2.start()
        try:
            # Assert
            assert s2.is_approved_sync("agent-a", "browser", "click", "x.com") is False
            assert await s2.list_approvals(active_only=True) == []
            assert len(await s2.list_approvals(active_only=False)) == 1
        finally:
            await s2.stop()

    @pytest.mark.asyncio
    async def test_list_approvals_active_only_excludes_expired_and_revoked(
        self, tmp_path
    ):
        # Arrange
        approvals = await _approvals(tmp_path)
        try:
            live = await approvals.issue_approval(
                "agent-a", "browser", "click", scope_key="a.com", ttl_seconds=3600
            )
            await approvals.issue_approval(
                "agent-a", "browser", "click", scope_key="b.com", ttl_seconds=-1
            )
            gone = await approvals.issue_approval(
                "agent-a", "browser", "click", scope_key="c.com", ttl_seconds=3600
            )
            await approvals.revoke_approval(gone.id)
            # Act
            active = await approvals.list_approvals(active_only=True)
            everything = await approvals.list_approvals(active_only=False)
            # Assert
            assert [a.id for a in active] == [live.id]
            assert len(everything) == 3
        finally:
            await approvals.stop()

    @pytest.mark.asyncio
    async def test_get_active_expiry_returns_none_for_an_unknown_shape(
        self, tmp_path
    ):
        # Arrange
        approvals = await _approvals(tmp_path)
        try:
            # Act / Assert
            assert approvals.get_active_expiry_sync("a", "b", "c", "d") is None
        finally:
            await approvals.stop()


# -- Bounds (DD-6) --------------------------------------------------------


class TestInboxBounds:
    @pytest.mark.asyncio
    async def test_the_third_ask_at_a_cap_of_two_is_refused_without_filing(
        self, tmp_path, caplog
    ):
        # Arrange
        db = str(tmp_path / "cap.db")
        store = CapabilityRequestStore(db_path=db)
        await store.start()
        page = _FakePage(list_elements=[{"role": "button", "text": "Pay now"}])
        executor, tool, _ = await _armed(
            tmp_path, request_store=store, page=page, max_pending_per_agent=2
        )
        try:
            sid = await _open_session(executor, tool, _TIER_3_URL)
            # Act — three DISTINCT asks (differing params defeat dedup)
            await _invoke(executor, {"action": "click", "index": 0, "session_id": sid})
            await _invoke(executor, {"action": "click", "index": 1, "session_id": sid})
            with caplog.at_level(logging.WARNING):
                third = await _invoke(
                    executor, {"action": "click", "index": 2, "session_id": sid}
                )
            rows = sqlite3.connect(db).execute(
                "SELECT COUNT(*) FROM capability_requests"
            ).fetchone()[0]
            # Assert
            assert third.error == _APPROVAL_INBOX_FULL_REFUSAL
            assert rows == 2
            saturation = [r for r in caplog.records if "saturated" in r.message]
            assert saturation
            assert "agent-a" in saturation[0].getMessage()
            assert "2" in saturation[0].getMessage()
            assert tool.invocations == []
        finally:
            await store.stop()
            await tool.stop()

    @pytest.mark.asyncio
    async def test_the_cap_is_per_agent(self, tmp_path):
        # Arrange
        store = await _store(tmp_path)
        page = _FakePage(list_elements=[{"role": "button", "text": "Pay now"}])
        executor, tool, _ = await _armed(
            tmp_path, request_store=store, page=page, max_pending_per_agent=1
        )
        try:
            sid = await _open_session(executor, tool, _TIER_3_URL)
            await _invoke(executor, {"action": "click", "index": 0, "session_id": sid})
            # Act
            blocked = await _invoke(
                executor, {"action": "click", "index": 1, "session_id": sid}
            )
            other = await _invoke(
                executor,
                {"action": "click", "index": 1, "session_id": sid},
                agent_id="agent-b",
            )
            pending = await store.list_pending()
            # Assert
            assert blocked.error == _APPROVAL_INBOX_FULL_REFUSAL
            assert other.error != _APPROVAL_INBOX_FULL_REFUSAL
            assert {r.agent_id for r in pending} == {"agent-a", "agent-b"}
        finally:
            await store.stop()
            await tool.stop()

    @pytest.mark.asyncio
    async def test_deciding_a_pending_ask_frees_a_slot(self, tmp_path):
        # Arrange
        store = await _store(tmp_path)
        page = _FakePage(list_elements=[{"role": "button", "text": "Pay now"}])
        executor, tool, _ = await _armed(
            tmp_path, request_store=store, page=page, max_pending_per_agent=1
        )
        try:
            sid = await _open_session(executor, tool, _TIER_3_URL)
            first = await _invoke(
                executor, {"action": "click", "index": 0, "session_id": sid}
            )
            assert first.error != _APPROVAL_INBOX_FULL_REFUSAL
            await store.decide(
                (await store.list_pending())[0].id, approve=True, reason="ok"
            )
            # Act
            second = await _invoke(
                executor, {"action": "click", "index": 1, "session_id": sid}
            )
            # Assert
            assert second.error != _APPROVAL_INBOX_FULL_REFUSAL
            assert len(await store.list_pending()) == 1
        finally:
            await store.stop()
            await tool.stop()

    @pytest.mark.asyncio
    async def test_a_stale_ask_leaves_the_count_but_stays_pending(self, tmp_path):
        """Stale is NEITHER auto-approved NOR auto-denied."""
        # Arrange
        store = await _store(tmp_path)
        old = await store.file_action_request("agent-a", _payload())
        old.created_at = time.time() - (100 * 3600)
        # Act
        counted = store.count_pending_sync(
            "agent-a", stale_before=time.time() - (72 * 3600)
        )
        pending = await store.list_pending()
        try:
            # Assert
            assert counted == 0
            assert [r.id for r in pending] == [old.id]
            assert pending[0].status == "pending"
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_count_pending_sync_ignores_other_agents_and_decided_rows(
        self, tmp_path
    ):
        # Arrange
        store = await _store(tmp_path)
        try:
            await store.file_action_request("agent-a", _payload())
            decided = await store.file_action_request(
                "agent-a", _payload(params={"index": 9})
            )
            await store.decide(decided.id, approve=True, reason="ok")
            await store.file_action_request("agent-b", _payload())
            # Act / Assert
            assert store.count_pending_sync("agent-a") == 1
            assert store.count_pending_sync("agent-b") == 1
            assert store.count_pending_sync("agent-c") == 0
        finally:
            await store.stop()


# -- Consensus (DD-7) -----------------------------------------------------


class TestConsensusIsNotRoutableAround:
    @pytest.mark.asyncio
    async def test_a_mesh_intent_tool_is_never_parked(self, tmp_path):
        # Arrange
        class _Bus:
            def __init__(self) -> None:
                self.broadcasts: list[Any] = []

            async def broadcast(self, message: Any) -> list[Any]:
                self.broadcasts.append(message)
                return []

        bus = _Bus()
        mesh_tool = _MeshIntentTool(
            intent_bus=bus,
            tool_id="web_search",
            intent_name="web_search",
            name="Web Search",
            description="search",
            input_schema={"type": "object"},
        )
        registry = ToolRegistry()
        registry.register(mesh_tool, domain="*", provider="ship_computer", enabled=True)
        executor = DispatchToolExecutor(registry=registry)
        store = await _store(tmp_path)
        executor.arm_approval_inbox(
            request_store=store, approval_store=None, config=_cfg()
        )
        try:
            # Act
            await executor.invoke("agent-a", "web_search", {"query": "x"})
            # Assert — the ask never reaches the store, and the bus was used.
            assert await store.list_pending() == []
            assert len(bus.broadcasts) == 1
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_an_mcp_consensus_tier_tool_is_never_parked(self, tmp_path):
        # Arrange
        quorum_calls: list[tuple] = []

        async def _consensus_invoke(url: str, tool_name: str, args: dict) -> dict:
            quorum_calls.append((url, tool_name, args))
            return {"committed": False, "outcome": "rejected"}

        class _NeverInvokedBridge:
            async def invoke(self, *_a: Any, **_k: Any) -> Any:  # pragma: no cover
                raise AssertionError("CONSENSUS must not reach the bridge directly")

        mcp_tool = _McpTool(
            bridge=_NeverInvokedBridge(),
            server_url="http://srv",
            server_name="srv",
            server_id="srv-1",
            tool_name="danger",
            name="Danger",
            description="a consensus-tier MCP tool",
            input_schema={"type": "object"},
            server_default_risk=McpToolRisk.CONSENSUS.value,
            risk_store=None,
            consensus_invoke=_consensus_invoke,
            authorize=lambda _agent_id: True,
        )
        registry = ToolRegistry()
        registry.register(mcp_tool, domain="*", provider="mcp", enabled=True)
        executor = DispatchToolExecutor(registry=registry)
        store = await _store(tmp_path)
        executor.arm_approval_inbox(
            request_store=store, approval_store=None, config=_cfg()
        )
        try:
            # Act
            await executor.invoke("agent-a", mcp_tool.tool_id, {"x": 1})
            # Assert — the quorum ran and the ask never reached the store.
            assert mcp_tool.effective_risk() is McpToolRisk.CONSENSUS
            assert len(quorum_calls) == 1
            assert await store.list_pending() == []
        finally:
            await store.stop()

    def test_the_armed_tool_id_set_is_browser_only(self):
        """Fail-safe drift guard: membership is the ONLY way into the wrapper."""
        assert _APPROVAL_INBOX_TOOL_IDS == frozenset({"browser"})

    @pytest.mark.parametrize("action", sorted(_ALWAYS_TIER_3_ACTIONS))
    def test_always_tier_3_actions_match_the_real_classifier(self, action):
        """``classify_action`` lives in a module the dispatch file deliberately
        does not import at module scope, so the subset relation needs a guard."""
        # Act — these verbs short-circuit BEFORE any session is inspected.
        assert classify_action(None, action, {}) == 3

    def test_is_approved_sync_appears_in_no_consensus_module(self):
        """A standing rule can never satisfy a quorum requirement."""
        # Arrange
        consensus_dir = (
            Path(__file__).resolve().parents[1] / "src" / "probos" / "consensus"
        )
        # Act
        offenders = [
            path.name
            for path in consensus_dir.rglob("*.py")
            if "is_approved_sync" in path.read_text(encoding="utf-8")
        ]
        # Assert
        assert consensus_dir.is_dir()
        assert offenders == []


# -- Seam and OFF path (DD-8, DD-10) --------------------------------------


class TestSeamAndOffPath:
    def test_browser_loop_actions_is_byte_identical(self):
        """AD-1153's read-only partition is untouched — widening it is the
        follow-up this AD unblocks, not part of it."""
        assert _BROWSER_LOOP_ACTIONS == frozenset(
            {"goto", "state", "extract_text", "back", "forward", "wait"}
        )

    @pytest.mark.asyncio
    async def test_with_the_flag_off_the_kwargs_reaching_super_are_identical(
        self, tmp_path
    ):
        # Arrange
        captured: list[tuple] = []

        class _Spy(DispatchToolExecutor):
            async def invoke(self, agent_id, tool_id, params, **kwargs):
                captured.append((agent_id, tool_id, dict(params), dict(kwargs)))
                return await super().invoke(agent_id, tool_id, params, **kwargs)

        tool = _make_tool()
        executor = _Spy(registry=_registry_with_browser(tool))
        try:
            # Act — unarmed: never call arm_approval_inbox
            await executor.invoke(
                "agent-a",
                "browser",
                {"action": "goto", "url": _TIER_2_URL},
                agent_department="engineering",
                agent_rank="commander",
            )
            # Assert — key-for-key and value-for-value against a literal
            assert executor._approval_inbox is None
            assert captured[0][0] == "agent-a"
            assert captured[0][1] == "browser"
            assert captured[0][2] == {"action": "goto", "url": _TIER_2_URL}
            assert captured[0][3] == {
                "agent_department": "engineering",
                "agent_rank": "commander",
            }
            assert list(captured[0][3].keys()) == [
                "agent_department",
                "agent_rank",
            ]
        finally:
            await tool.stop()

    @pytest.mark.asyncio
    async def test_an_unarmed_executor_admits_a_tier_3_action_unchanged(
        self, tmp_path
    ):
        # Arrange
        page = _FakePage(list_elements=[{"role": "button", "text": "Pay now"}])
        tool = _make_tool(page=page)
        executor = DispatchToolExecutor(registry=_registry_with_browser(tool))
        try:
            sid = await _open_session(executor, tool, _TIER_3_URL)
            # Act
            result = await _invoke(
                executor, {"action": "click", "index": 0, "session_id": sid}
            )
            # Assert — HEAD's behaviour, verbatim
            assert len(tool.invocations) == 1
            assert result.error is None
            assert result.output["intervention_required"] is True
        finally:
            await tool.stop()

    @pytest.mark.asyncio
    async def test_an_ad1153_refusal_wins_and_files_nothing(self, tmp_path):
        """A refusal is not an ask."""
        # Arrange
        page = _FakePage(list_elements=[{"role": "button", "text": "Pay now"}])
        executor, tool, store = await _armed(tmp_path, page=page)
        executor.restrict_browser_actions(_BROWSER_LOOP_ACTIONS)
        try:
            sid = await _open_session(executor, tool, _TIER_3_URL)
            # Act
            result = await _invoke(
                executor, {"action": "click", "index": 0, "session_id": sid}
            )
            # Assert
            assert "read-only mode" in result.error
            assert await store.list_pending() == []
            assert tool.invocations == []
        finally:
            await store.stop()
            await tool.stop()

    @pytest.mark.asyncio
    async def test_no_session_means_only_always_tier_3_verbs_park(self, tmp_path):
        """The DD-10 step-2 asymmetry: never create a session to classify."""
        # Arrange
        executor, tool, store = await _armed(tmp_path)
        try:
            # Act — no session_id at all
            click = await _invoke(executor, {"action": "click", "index": 0})
            eval_js = await _invoke(executor, {"action": "eval_js", "script": "1"})
            pending = await store.list_pending()
            # Assert
            assert len(pending) == 1
            assert pending[0].payload["action"] == "eval_js"
            # ``click`` fell through to BrowserTool, whose own gate then ran.
            assert len(tool.invocations) == 1
            assert tool.invocations[0]["action"] == "click"
            assert click.error is None or "read-only" not in click.error
            assert eval_js.error is not None
        finally:
            await store.stop()
            await tool.stop()

    @pytest.mark.asyncio
    async def test_classifying_never_creates_a_session(self, tmp_path):
        # Arrange
        executor, tool, store = await _armed(tmp_path)
        try:
            # Act — an always-tier-3 verb naming a session that does not exist
            await _invoke(
                executor, {"action": "eval_js", "session_id": "ghost", "script": "1"}
            )
            # Assert
            assert tool.session_count == 0
            assert tool.invocations == []
        finally:
            await store.stop()
            await tool.stop()

    def test_park_or_admit_keeps_its_pinned_signature(self):
        # Act
        signature = inspect.signature(DispatchToolExecutor._park_or_admit)
        # Assert
        assert list(signature.parameters) == [
            "self",
            "agent_id",
            "tool_id",
            "params",
            "disposition_sink",
        ]
        assert (
            signature.parameters["disposition_sink"].kind
            is inspect.Parameter.KEYWORD_ONLY
        )


# -- Fail CLOSED (DD-10) --------------------------------------------------


class TestFailsClosed:
    @pytest.mark.asyncio
    async def test_a_raising_standing_rule_lookup_parks_rather_than_admits(
        self, tmp_path, caplog
    ):
        """THE important one: failing open here admits the action outright."""
        # Arrange
        class _ExplodingApprovals:
            def is_approved_sync(self, *_args: Any) -> bool:
                raise RuntimeError("cache read blew up")

        page = _FakePage(list_elements=[{"role": "button", "text": "Pay now"}])
        executor, tool, store = await _armed(
            tmp_path,
            approval_store=_ExplodingApprovals(),
            standing_rules_enabled=True,
            page=page,
        )
        try:
            sid = await _open_session(executor, tool, _TIER_3_URL)
            # Act
            with caplog.at_level(logging.WARNING):
                result = await _invoke(
                    executor, {"action": "click", "index": 0, "session_id": sid}
                )
            # Assert — parked, NOT admitted
            assert tool.invocations == []
            assert result.error is not None
            assert len(await store.list_pending()) == 1
            assert any("NOT approved" in r.getMessage() for r in caplog.records)
        finally:
            await store.stop()
            await tool.stop()

    @pytest.mark.asyncio
    async def test_a_raising_file_action_request_refuses_rather_than_admits(
        self, tmp_path, caplog
    ):
        # Arrange
        class _ExplodingStore:
            def count_pending_sync(self, *_a: Any, **_k: Any) -> int:
                return 0

            async def file_action_request(self, *_a: Any, **_k: Any) -> Any:
                raise RuntimeError("disk is gone")

        page = _FakePage(list_elements=[{"role": "button", "text": "Pay now"}])
        tool = _make_tool(page=page)
        executor = DispatchToolExecutor(registry=_registry_with_browser(tool))
        executor.arm_approval_inbox(
            request_store=_ExplodingStore(), approval_store=None, config=_cfg()
        )
        try:
            sid = await _open_session(executor, tool, _TIER_3_URL)
            # Act
            with caplog.at_level(logging.WARNING):
                result = await _invoke(
                    executor, {"action": "click", "index": 0, "session_id": sid}
                )
            # Assert
            assert result.error == _APPROVAL_PARKED_REFUSAL_NO_ID
            assert tool.invocations == []
            assert any("refusing the action" in r.getMessage() for r in caplog.records)
        finally:
            await tool.stop()

    @pytest.mark.asyncio
    async def test_a_none_request_store_refuses_rather_than_admits(self, tmp_path):
        # Arrange
        page = _FakePage(list_elements=[{"role": "button", "text": "Pay now"}])
        tool = _make_tool(page=page)
        executor = DispatchToolExecutor(registry=_registry_with_browser(tool))
        executor.arm_approval_inbox(
            request_store=None, approval_store=None, config=_cfg()
        )
        try:
            sid = await _open_session(executor, tool, _TIER_3_URL)
            # Act
            result = await _invoke(
                executor, {"action": "click", "index": 0, "session_id": sid}
            )
            # Assert
            assert result.error == _APPROVAL_PARKED_REFUSAL_NO_ID
            assert tool.invocations == []
        finally:
            await tool.stop()

    @pytest.mark.asyncio
    async def test_a_raising_pending_count_refuses_rather_than_files(
        self, tmp_path, caplog
    ):
        # Arrange
        class _ExplodingCount:
            def count_pending_sync(self, *_a: Any, **_k: Any) -> int:
                raise RuntimeError("cache is corrupt")

            async def file_action_request(self, *_a: Any, **_k: Any) -> Any:
                raise AssertionError("must not be reached")

        page = _FakePage(list_elements=[{"role": "button", "text": "Pay now"}])
        tool = _make_tool(page=page)
        executor = DispatchToolExecutor(registry=_registry_with_browser(tool))
        executor.arm_approval_inbox(
            request_store=_ExplodingCount(), approval_store=None, config=_cfg()
        )
        try:
            sid = await _open_session(executor, tool, _TIER_3_URL)
            # Act
            with caplog.at_level(logging.WARNING):
                result = await _invoke(
                    executor, {"action": "click", "index": 0, "session_id": sid}
                )
            # Assert
            assert result.error == _APPROVAL_INBOX_FULL_REFUSAL
            assert tool.invocations == []
            assert any("could not count" in r.getMessage() for r in caplog.records)
        finally:
            await tool.stop()

    @pytest.mark.asyncio
    async def test_a_rejected_payload_refuses_rather_than_admits(self, tmp_path):
        """``file_action_request`` returning None must not become an admission."""
        # Arrange
        class _RejectingStore:
            def count_pending_sync(self, *_a: Any, **_k: Any) -> int:
                return 0

            async def file_action_request(self, *_a: Any, **_k: Any) -> Any:
                return None

        page = _FakePage(list_elements=[{"role": "button", "text": "Pay now"}])
        tool = _make_tool(page=page)
        executor = DispatchToolExecutor(registry=_registry_with_browser(tool))
        executor.arm_approval_inbox(
            request_store=_RejectingStore(), approval_store=None, config=_cfg()
        )
        try:
            sid = await _open_session(executor, tool, _TIER_3_URL)
            # Act
            result = await _invoke(
                executor, {"action": "click", "index": 0, "session_id": sid}
            )
            # Assert
            assert result.error == _APPROVAL_PARKED_REFUSAL_NO_ID
            assert tool.invocations == []
        finally:
            await tool.stop()

    @pytest.mark.asyncio
    async def test_a_raising_session_lookup_degrades_without_admitting_more(
        self, tmp_path
    ):
        # Arrange
        class _ExplodingRegistry:
            def get_tool(self, _tool_id: str) -> Any:
                raise RuntimeError("registry is down")

        executor = DispatchToolExecutor(registry=_ExplodingRegistry())
        store = await _store(tmp_path)
        executor.arm_approval_inbox(
            request_store=store, approval_store=None, config=_cfg()
        )
        try:
            # Act — no session resolvable, so only always-tier-3 verbs park
            parked = await executor._park_or_admit(
                "agent-a", "browser", {"action": "eval_js", "session_id": "s1"}
            )
            admitted = await executor._park_or_admit(
                "agent-a", "browser", {"action": "click", "session_id": "s1"}
            )
            # Assert
            assert parked is not None
            assert admitted is None
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_a_non_string_action_is_admitted_to_the_existing_path(
        self, tmp_path
    ):
        # Arrange
        executor, tool, store = await _armed(tmp_path)
        try:
            # Act
            for params in ({"action": None}, {"action": 7}, {}, "not-a-dict"):
                result = await executor._park_or_admit("agent-a", "browser", params)
                # Assert — the wrapper does not classify; the tool's own path runs
                assert result is None
            assert await store.list_pending() == []
        finally:
            await store.stop()
            await tool.stop()


# -- Config (DD-8) --------------------------------------------------------


class TestConfig:
    def test_system_config_constructs_with_the_feature_off(self):
        # Act
        config = SystemConfig()
        # Assert
        assert config.approval_inbox.enabled is False
        assert config.approval_inbox.standing_rules_enabled is False

    def test_the_default_ttl_sits_below_the_max(self):
        # Act
        config = ApprovalInboxConfig()
        # Assert
        assert (
            config.standing_rule_default_ttl_hours
            <= config.standing_rule_max_ttl_hours
        )

    def test_no_model_validator_couples_the_two_ttl_fields(self):
        """A validator here would turn an unrelated POST /config into a 422."""
        # Act — deliberately inverted: default ABOVE the max
        config = ApprovalInboxConfig(
            standing_rule_max_ttl_hours=2, standing_rule_default_ttl_hours=200
        )
        # Assert — accepted; the clamp happens at issue time
        assert config.standing_rule_default_ttl_hours == 200
        assert ApprovalInboxConfig.__pydantic_decorators__.model_validators == {}

    @pytest.mark.parametrize(
        "field,value",
        [
            ("max_pending_per_agent", 0),
            ("max_pending_per_agent", 201),
            ("pending_ask_ttl_hours", 0),
            ("standing_rule_max_ttl_hours", 721),
        ],
    )
    def test_out_of_range_bounds_are_rejected(self, field, value):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ApprovalInboxConfig(**{field: value})

    def test_the_config_reference_records_the_replay_limitation(self):
        """DD-3 and DD-6 must be discoverable by an operator reading the docs."""
        # Arrange
        doc = (
            Path(__file__).resolve().parents[1]
            / "docs"
            / "development"
            / "config-reference.md"
        ).read_text(encoding="utf-8")
        # Assert
        assert "## `approval_inbox`" in doc
        assert "does NOT replay the parked action" in doc
        assert "REFUSES without filing" in doc
        assert "NEITHER auto-approved NOR auto-denied" in doc
        assert "expires_at is NOT NULL in the action_approvals schema" in doc
        assert "No HXI affordance ships with this" in doc


# -- BF-682 (Section 0) ---------------------------------------------------


class TestBf682ConfirmationTokenNotEmitted:
    @pytest.mark.asyncio
    async def test_the_intervention_event_carries_a_prefix_not_the_token(self):
        # Arrange
        events: list[tuple] = []
        page = _FakePage(list_elements=[{"role": "button", "text": "Pay now"}])
        tool = BrowserTool(
            config=BrowserToolConfig(enabled=True),
            audit_log=AuditLog(),
            emit_event=lambda et, data: events.append((et, data)),
        )
        tool._session_factory = _make_session_factory(page=page)
        try:
            nav = await tool.invoke(
                {"action": "goto", "url": _TIER_3_URL}, {"agent_id": "a1"}
            )
            sid = nav.metadata["session_id"]
            await tool.invoke({"action": "state", "session_id": sid}, {"agent_id": "a1"})
            # Act
            await tool.invoke(
                {"action": "click", "index": 0, "session_id": sid},
                {"agent_id": "a1"},
            )
            from probos.events import EventType

            payloads = [
                data
                for et, data in events
                if et == EventType.TOOL_INTERVENTION_REQUIRED
            ]
            # Assert
            assert payloads
            assert "confirmation_token" not in payloads[0]
            correlator = payloads[0]["confirmation_id"]
            minted = [
                t for t in tool._pending_confirmations if t.startswith(correlator)
            ]
            assert len(correlator) == 8
            assert len(minted) == 1
            assert correlator == minted[0][:8]
            # The correlator itself is NOT a key — it cannot be redeemed.
            assert correlator not in tool._pending_confirmations
        finally:
            await tool.stop()

    @pytest.mark.asyncio
    async def test_the_prefix_is_not_redeemable_but_the_full_token_is(self):
        # Arrange
        tool = BrowserTool(
            config=BrowserToolConfig(enabled=True), audit_log=AuditLog()
        )
        token = "0123456789abcdef0123456789abcdef"
        tool.seed_confirmation_token(token=token, session_id="s1", action="click")
        try:
            # Act / Assert — the prefix must NOT satisfy the gate
            assert tool._consume_confirmation_token(
                {"confirmation_token": token[:8]}, "s1", "click"
            ) is False
            # …and the full token still must
            assert tool._consume_confirmation_token(
                {"confirmation_token": token}, "s1", "click"
            ) is True
        finally:
            await tool.stop()
