"""AD-706: BrowserTool tests.

Most tests run without a real browser by mocking the Playwright client via
``_FakePage``/``_FakeContext``/``_FakeBrowser``/``_FakePlaywright`` stubs.
A single integration test gated on ``PROBOS_PLAYWRIGHT_REAL=1`` exercises a
real Chromium navigate; skipped by default.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import pytest

from probos.config import BrowserToolConfig
from probos.events import EventType
from probos.security.audit import AuditLog
from probos.tools.browser.session import BrowserSession
from probos.tools.browser.tool import BrowserTool
from probos.tools.protocol import Tool, ToolType


# -- Fakes ----------------------------------------------------------------


class _FakePage:
    def __init__(self, *, list_elements: list[dict[str, Any]] | None = None,
                 inner_text: str = "", title: str = "", url: str = "",
                 viewport: dict[str, int] | None = None) -> None:
        self._list_elements = list_elements or []
        self._inner_text = inner_text
        self._title = title
        self.url = url
        self.viewport_size = viewport or {"width": 1024, "height": 768}
        self.calls: list[tuple[str, tuple, dict]] = []

    def _record(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))

    def set_default_timeout(self, ms: int) -> None:
        self._record("set_default_timeout", ms)

    async def goto(self, url: str) -> None:
        self._record("goto", url)
        self.url = url

    async def title(self) -> str:
        return self._title

    async def list_elements(self) -> list[dict[str, Any]]:
        return list(self._list_elements)

    async def click(self, selector: str) -> None:
        self._record("click", selector)

    async def fill(self, selector: str, text: str) -> None:
        self._record("fill", selector, text)

    async def type(self, selector: str, text: str) -> None:
        self._record("type", selector, text)

    async def evaluate(self, expr: str) -> None:
        self._record("evaluate", expr)

    async def screenshot(self) -> bytes:
        return b"\x89PNGfake"

    async def wait_for_selector(self, selector: str) -> None:
        self._record("wait_for_selector", selector)

    async def go_back(self) -> None:
        self._record("go_back")

    async def go_forward(self) -> None:
        self._record("go_forward")

    async def inner_text(self, selector: str) -> str:
        self._record("inner_text", selector)
        return self._inner_text

    async def close(self) -> None:
        self._record("close")


class _FakeContext:
    def __init__(self, page: _FakePage) -> None:
        self._page = page
        self.closed = False

    async def new_page(self) -> _FakePage:
        return self._page

    async def close(self) -> None:
        self.closed = True


class _FakeBrowser:
    def __init__(self, page: _FakePage) -> None:
        self._page = page
        self.closed = False

    async def new_context(self) -> _FakeContext:
        return _FakeContext(self._page)

    async def close(self) -> None:
        self.closed = True


def _make_session_factory(*, page: _FakePage, headless_log: list[bool] | None = None) -> Any:
    class _FakeSession(BrowserSession):
        async def start(self) -> None:  # type: ignore[override]
            self._browser = _FakeBrowser(page)
            self._context = _FakeContext(page)
            self._page = page
            if headless_log is not None:
                headless_log.append(self._config.headless)
    return _FakeSession


# -- Helpers --------------------------------------------------------------


def _make_tool(
    *,
    config: BrowserToolConfig | None = None,
    audit: AuditLog | None = None,
    emit_log: list[tuple[Any, Any]] | None = None,
    page: _FakePage | None = None,
    headless_log: list[bool] | None = None,
) -> tuple[BrowserTool, _FakePage, AuditLog, list[tuple[Any, Any]]]:
    cfg = config or BrowserToolConfig(enabled=True)
    audit_log = audit if audit is not None else AuditLog()
    events = emit_log if emit_log is not None else []

    def _emit(et: Any, data: Any) -> None:
        events.append((et, data))

    fp = page or _FakePage()
    tool = BrowserTool(config=cfg, audit_log=audit_log, emit_event=_emit)
    tool._session_factory = _make_session_factory(page=fp, headless_log=headless_log)
    return tool, fp, audit_log, events


# -- Tests ----------------------------------------------------------------


def test_browser_tool_satisfies_protocol() -> None:
    tool, _, _, _ = _make_tool()
    assert isinstance(tool, Tool)
    assert tool.tool_type is ToolType.BROWSER
    assert tool.tool_id == "browser"


@pytest.mark.asyncio
async def test_invoke_unknown_action_returns_error() -> None:
    tool, _, _, _ = _make_tool()
    res = await tool.invoke({"action": "nope"}, {"agent_id": "a1"})
    assert res.error is not None
    assert "unknown" in res.error.lower()
    await tool.stop()


@pytest.mark.asyncio
async def test_invoke_goto_writes_audit_entry() -> None:
    tool, page, audit, _ = _make_tool(page=_FakePage(title="Hello"))
    res = await tool.invoke(
        {"action": "goto", "url": "https://example.com/path?token=secret"},
        {"agent_id": "a1"},
    )
    assert res.error is None
    assert audit.entries, "audit log should have at least one entry"
    last = audit.entries[-1]
    assert last.category == "browser_tool"
    assert "goto" in last.detail
    detail = json.loads(last.detail)
    # url_sanitized must drop the query string (D5).
    assert detail["url_sanitized"] == "https://example.com/path"
    assert "token=secret" not in last.detail
    await tool.stop()


@pytest.mark.asyncio
async def test_domain_denylist_blocks_navigation() -> None:
    cfg = BrowserToolConfig(enabled=True, domain_denylist=["evil.example"])
    tool, _, _, _ = _make_tool(config=cfg)
    res = await tool.invoke(
        {"action": "goto", "url": "https://evil.example/x"},
        {"agent_id": "a1"},
    )
    assert res.error is not None
    assert "in denylist" in res.error
    await tool.stop()


@pytest.mark.asyncio
async def test_domain_allowlist_blocks_unknown_host() -> None:
    cfg = BrowserToolConfig(enabled=True, domain_allowlist=["good.example"])
    tool, _, _, _ = _make_tool(config=cfg)
    res = await tool.invoke(
        {"action": "goto", "url": "https://other.example/"},
        {"agent_id": "a1"},
    )
    assert res.error is not None
    assert "not in allowlist" in res.error
    await tool.stop()


@pytest.mark.asyncio
async def test_state_returns_indexed_elements() -> None:
    page = _FakePage(list_elements=[
        {"role": "button", "text": "Submit", "selector": "#submit"},
        {"role": "link", "text": "Home", "selector": "a.home"},
    ])
    tool, _, _, _ = _make_tool(page=page)
    res = await tool.invoke({"action": "state"}, {"agent_id": "a1"})
    assert res.error is None
    elements = res.output["elements"]
    assert isinstance(elements, list)
    assert len(elements) == 2
    assert elements[0]["index"] == 0
    assert elements[0]["role"] == "button"
    assert elements[1]["index"] == 1
    await tool.stop()


@pytest.mark.asyncio
async def test_click_by_index_resolves_via_last_state() -> None:
    page = _FakePage(list_elements=[
        {"role": "button", "text": "Boring", "selector": "#a"},
        {"role": "button", "text": "Boring2", "selector": "#b"},
        {"role": "link", "text": "Other", "selector": ".c"},
    ])
    tool, _, _, _ = _make_tool(page=page)
    state_res = await tool.invoke({"action": "state"}, {"agent_id": "a1"})
    sid = state_res.metadata["session_id"]
    res = await tool.invoke(
        {"action": "click", "index": 2, "session_id": sid},
        {"agent_id": "a1"},
    )
    assert res.error is None, res.error
    click_calls = [c for c in page.calls if c[0] == "click"]
    assert click_calls, "click was not invoked on the page"
    assert click_calls[0][1] == (".c",)
    await tool.stop()


@pytest.mark.asyncio
async def test_tier_3_action_emits_intervention_required() -> None:
    page = _FakePage(list_elements=[
        {"role": "button", "text": "Pay now", "selector": "#pay"},
    ])
    tool, _, _, events = _make_tool(page=page)
    # Navigate first to a tier-3 host.
    nav = await tool.invoke(
        {"action": "goto", "url": "https://bank.example/transfer"},
        {"agent_id": "a1"},
    )
    sid = nav.metadata["session_id"]
    await tool.invoke({"action": "state", "session_id": sid}, {"agent_id": "a1"})
    res = await tool.invoke(
        {"action": "click", "index": 0, "session_id": sid},
        {"agent_id": "a1"},
    )
    assert res.error is None
    assert res.output is not None
    assert res.output["intervention_required"] is True
    assert res.output["tier"] == 3
    # Token must NOT be surfaced in agent-visible output (D6 #2).
    assert "confirmation_token" not in res.output
    # BF-682: the event carries a NON-REDEEMABLE 8-hex correlator, never the
    # bearer token — possession of the log line must not be possession of the
    # approval.
    intervention_events = [
        (et, data) for et, data in events if et == EventType.TOOL_INTERVENTION_REQUIRED
    ]
    assert intervention_events
    payload = intervention_events[0][1]
    assert "confirmation_token" not in payload
    minted = [t for t in tool._pending_confirmations if t.startswith(payload["confirmation_id"])]
    assert len(minted) == 1
    assert payload["confirmation_id"] == minted[0][:8]
    assert len(payload["confirmation_id"]) == 8
    assert payload["session_id"] == sid
    assert payload["tier"] == 3
    await tool.stop()


@pytest.mark.asyncio
async def test_tier_3_with_confirmation_token_proceeds() -> None:
    page = _FakePage(list_elements=[
        {"role": "button", "text": "Pay now", "selector": "#pay"},
    ])
    tool, _, _, _ = _make_tool(page=page)
    nav = await tool.invoke(
        {"action": "goto", "url": "https://stripe.example/checkout"},
        {"agent_id": "a1"},
    )
    sid = nav.metadata["session_id"]
    await tool.invoke({"action": "state", "session_id": sid}, {"agent_id": "a1"})
    tool.seed_confirmation_token(
        token="tok-abc", session_id=sid, action="click",
    )
    res = await tool.invoke(
        {"action": "click", "index": 0, "session_id": sid, "confirmation_token": "tok-abc"},
        {"agent_id": "a1"},
    )
    assert res.error is None, res.error
    assert res.output is not None
    # Tier-3 action proceeded — output is the click result, not intervention payload.
    assert res.output.get("intervention_required") is not True
    # Token consumed (single-use).
    assert "tok-abc" not in tool._pending_confirmations
    await tool.stop()


@pytest.mark.asyncio
async def test_screenshot_xga_scaling() -> None:
    page = _FakePage(viewport={"width": 1920, "height": 1080})
    tool, _, _, _ = _make_tool(page=page)
    res = await tool.invoke({"action": "screenshot"}, {"agent_id": "a1"})
    assert res.error is None
    assert res.output["width"] <= 1024
    assert res.output["height"] <= 768
    assert res.output["screenshot_b64"]
    await tool.stop()


@pytest.mark.asyncio
async def test_session_expiry_reaped() -> None:
    cfg = BrowserToolConfig(enabled=True, session_max_duration_seconds=0)
    tool, _, _, events = _make_tool(config=cfg)
    nav = await tool.invoke(
        {"action": "goto", "url": "https://example.com/"},
        {"agent_id": "a1"},
    )
    sid = nav.metadata["session_id"]
    assert tool.get_session(sid) is not None
    # session_max_duration_seconds=0 means is_expired() is True immediately.
    closed = await tool.reap_expired()
    assert closed >= 1
    assert tool.get_session(sid) is None
    closed_events = [et for et, _ in events if et == EventType.BROWSER_SESSION_CLOSED]
    assert closed_events
    await tool.stop()


@pytest.mark.asyncio
async def test_headless_flag_respected() -> None:
    cfg = BrowserToolConfig(enabled=True, headless=False)
    log: list[bool] = []
    tool, _, _, _ = _make_tool(config=cfg, headless_log=log)
    await tool.invoke({"action": "goto", "url": "https://example.com/"}, {"agent_id": "a1"})
    assert log and log[0] is False
    await tool.stop()


@pytest.mark.asyncio
async def test_unknown_action_does_not_create_session() -> None:
    tool, _, _, _ = _make_tool()
    assert tool.session_count == 0
    await tool.invoke({"action": "bogus"}, {"agent_id": "a1"})
    # Unknown action short-circuits before session creation.
    assert tool.session_count == 0
    await tool.stop()


@pytest.mark.skipif(
    os.environ.get("PROBOS_PLAYWRIGHT_REAL") != "1",
    reason="Requires real Playwright + Chromium (set PROBOS_PLAYWRIGHT_REAL=1).",
)
@pytest.mark.asyncio
async def test_real_chromium_goto_about_blank() -> None:
    cfg = BrowserToolConfig(enabled=True, headless=True)
    tool = BrowserTool(config=cfg)
    try:
        res = await tool.invoke(
            {"action": "goto", "url": "about:blank"},
            {"agent_id": "real-test"},
        )
        assert res.error is None, res.error
    finally:
        await tool.stop()


# -- Per-action boundary coverage (#15-#20) ------------------------------


@pytest.mark.asyncio
async def test_type_writes_text_to_indexed_input() -> None:
    page = _FakePage(list_elements=[
        {"role": "textbox", "text": "", "selector": "input.q"},
    ])
    tool, _, _, _ = _make_tool(page=page)
    s = await tool.invoke({"action": "state"}, {"agent_id": "a1"})
    sid = s.metadata["session_id"]
    res = await tool.invoke(
        {"action": "type", "index": 0, "text": "hello", "session_id": sid},
        {"agent_id": "a1"},
    )
    assert res.error is None, res.error
    fill_calls = [c for c in page.calls if c[0] == "fill"]
    assert fill_calls
    assert fill_calls[0][1] == ("input.q", "hello")
    await tool.stop()


@pytest.mark.asyncio
async def test_scroll_invokes_page_scroll() -> None:
    page = _FakePage()
    tool, _, _, _ = _make_tool(page=page)
    res = await tool.invoke(
        {"action": "scroll", "direction": "down", "amount": 400},
        {"agent_id": "a1"},
    )
    assert res.error is None, res.error
    eval_calls = [c for c in page.calls if c[0] == "evaluate"]
    assert eval_calls
    assert "400" in eval_calls[0][1][0]
    await tool.stop()


@pytest.mark.asyncio
async def test_wait_blocks_for_configured_duration() -> None:
    page = _FakePage()
    tool, _, _, _ = _make_tool(page=page)
    res = await tool.invoke({"action": "wait", "milliseconds": 50}, {"agent_id": "a1"})
    assert res.error is None
    assert res.output is not None
    assert res.output.get("waited_ms", 0) >= 40  # tolerance for sleep jitter
    await tool.stop()


@pytest.mark.asyncio
async def test_back_navigates_history_backward() -> None:
    page = _FakePage()
    tool, _, _, _ = _make_tool(page=page)
    nav = await tool.invoke({"action": "goto", "url": "https://example.com/"}, {"agent_id": "a1"})
    sid = nav.metadata["session_id"]
    res = await tool.invoke({"action": "back", "session_id": sid}, {"agent_id": "a1"})
    assert res.error is None, res.error
    assert any(c[0] == "go_back" for c in page.calls)
    await tool.stop()


@pytest.mark.asyncio
async def test_forward_navigates_history_forward() -> None:
    page = _FakePage()
    tool, _, _, _ = _make_tool(page=page)
    nav = await tool.invoke({"action": "goto", "url": "https://example.com/"}, {"agent_id": "a1"})
    sid = nav.metadata["session_id"]
    res = await tool.invoke({"action": "forward", "session_id": sid}, {"agent_id": "a1"})
    assert res.error is None, res.error
    assert any(c[0] == "go_forward" for c in page.calls)
    await tool.stop()


@pytest.mark.asyncio
async def test_extract_text_returns_visible_text() -> None:
    page = _FakePage(inner_text="Welcome aboard.")
    tool, _, audit, _ = _make_tool(page=page)
    res = await tool.invoke(
        {"action": "extract_text", "selector": "main"},
        {"agent_id": "a1"},
    )
    assert res.error is None, res.error
    assert res.output["text"] == "Welcome aboard."
    assert audit.entries[-1].category == "browser_tool"
    await tool.stop()


# -- Extra coverage --------------------------------------------------------


@pytest.mark.asyncio
async def test_get_streaming_url_returns_none_in_v1() -> None:
    cfg = BrowserToolConfig(enabled=True)
    session = BrowserSession(session_id="s1", config=cfg, agent_id="a1")
    assert session.get_streaming_url() is None


@pytest.mark.asyncio
async def test_audit_detail_obeys_strict_allowlist() -> None:
    """D5: detail JSON must contain only the 7 allowlisted keys, no others."""
    page = _FakePage(title="T")
    tool, _, audit, _ = _make_tool(page=page)
    await tool.invoke(
        {"action": "goto", "url": "https://example.com/?token=abc"},
        {"agent_id": "a1"},
    )
    detail = json.loads(audit.entries[-1].detail)
    allowed = {"session_id", "action", "agent_id", "success", "error", "tier", "url_sanitized"}
    extra = set(detail.keys()) - allowed
    assert not extra, f"audit detail leaked unexpected keys: {extra}"
    # Forbidden value contents must not appear.
    assert "token=abc" not in audit.entries[-1].detail


@pytest.mark.asyncio
async def test_default_disabled_invariant() -> None:
    """Default config must have enabled=False (Wave 10 convention #14)."""
    cfg = BrowserToolConfig()
    assert cfg.enabled is False
    assert cfg.headless is True
    assert cfg.session_max_duration_seconds == 1800
    assert "*bank*" in cfg.tier_3_domain_patterns
