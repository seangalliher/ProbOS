"""AD-706c-1: BrowserTool 'verify' action — vision-LLM verification tests.

All vision LLM calls are stubbed via _FakeRuntime. AD-731 invariant
verified: the screenshot bytes flow through AttachmentStore.write keyed by
SHA-256, never inline through the bus.
"""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any

import pytest

from probos.config import (
    AttachmentsConfig,
    BrowserToolConfig,
    CognitiveConfig,
    SystemConfig,
)
from probos.events import EventType
from probos.security.audit import AuditLog
from probos.tools.browser.actions import (
    _parse_verify_response,
    classify_action,
)
from probos.tools.browser.session import BrowserSession
from probos.tools.browser.tool import BrowserTool


# -- Fakes ----------------------------------------------------------------


class _FakePage:
    def __init__(self, *, screenshot_bytes: bytes = b"\x89PNGfake") -> None:
        self._png = screenshot_bytes
        self.url = "https://example.com/dashboard"
        self.viewport_size = {"width": 1024, "height": 768}

    def set_default_timeout(self, ms: int) -> None: ...
    async def goto(self, url: str) -> None: self.url = url
    async def title(self) -> str: return "Dashboard"
    async def list_elements(self) -> list[dict[str, Any]]: return []
    async def click(self, selector: str) -> None: ...
    async def fill(self, selector: str, text: str) -> None: ...
    async def type(self, selector: str, text: str) -> None: ...
    async def evaluate(self, expr: str) -> None: ...
    async def screenshot(self) -> bytes: return self._png
    async def wait_for_selector(self, selector: str) -> None: ...
    async def go_back(self) -> None: ...
    async def go_forward(self) -> None: ...
    async def inner_text(self, selector: str) -> str: return ""
    async def close(self) -> None: ...


class _FakeContext:
    def __init__(self, page: _FakePage) -> None: self._page = page
    async def new_page(self) -> _FakePage: return self._page
    async def close(self) -> None: ...


class _FakeBrowser:
    def __init__(self, page: _FakePage) -> None: self._page = page
    async def new_context(self) -> _FakeContext: return _FakeContext(self._page)
    async def close(self) -> None: ...


def _session_factory(page: _FakePage) -> Any:
    class _FakeSession(BrowserSession):
        async def start(self) -> None:  # type: ignore[override]
            self._browser = _FakeBrowser(page)
            self._context = _FakeContext(page)
            self._page = page
    return _FakeSession


class _FakeAttachmentStore:
    """In-memory AttachmentStore matching the Protocol shape (write/read)."""
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}
        self.mimes: dict[str, str] = {}

    async def write(self, content_hash: str, blob: bytes, mime: str) -> Path:
        self.blobs[content_hash] = blob
        self.mimes[content_hash] = mime
        return Path(f"/fake/{content_hash}")

    async def read(self, content_hash: str) -> bytes:
        return self.blobs[content_hash]

    async def exists(self, content_hash: str) -> bool:
        return content_hash in self.blobs

    async def get_path(self, content_hash: str) -> Path:
        return Path(f"/fake/{content_hash}")

    async def size(self, content_hash: str) -> int:
        return len(self.blobs.get(content_hash, b""))


class _FakeLLMResponse:
    def __init__(self, text: str) -> None:
        self.text = text
        self.tier = "vision"
        self.latency_ms = 10.0


class _FakeLLMClient:
    def __init__(self, response_text: str = '{"ok": true, "observation": "Banner visible"}',
                 raise_exc: bool = False) -> None:
        self._response_text = response_text
        self._raise_exc = raise_exc
        self.calls: list[Any] = []

    async def complete(self, request: Any, *, priority: Any = None) -> _FakeLLMResponse:
        self.calls.append(request)
        if self._raise_exc:
            raise RuntimeError("vision tier offline")
        return _FakeLLMResponse(self._response_text)


class _FakeRuntime:
    def __init__(
        self,
        *,
        vision_configured: bool = True,
        llm_response_text: str = '{"ok": true, "observation": "Banner visible"}',
        llm_raises: bool = False,
        store: _FakeAttachmentStore | None = None,
    ) -> None:
        self.config = SystemConfig()
        if vision_configured:
            self.config.cognitive.llm_model_vision = "qwen3.6:27b"
            self.config.cognitive.llm_base_url_vision = "http://localhost:11434"
        self.llm_client = _FakeLLMClient(llm_response_text, raise_exc=llm_raises)
        self._attachment_store = store or _FakeAttachmentStore()


def _patch_attachment_store_lookup(monkeypatch: Any, store: _FakeAttachmentStore) -> None:
    """Patch _get_attachment_store(runtime) to return our fake."""
    from probos.routers import chat as _chat
    monkeypatch.setattr(_chat, "_get_attachment_store", lambda rt: store)


def _make_tool(runtime: _FakeRuntime, page: _FakePage) -> tuple[BrowserTool, list[tuple[Any, Any]]]:
    events: list[tuple[Any, Any]] = []
    def _emit(et: Any, data: Any) -> None:
        events.append((et, data))
    cfg = BrowserToolConfig(enabled=True)
    tool = BrowserTool(
        config=cfg,
        audit_log=AuditLog(),
        emit_event=_emit,
        runtime=runtime,
    )
    tool._session_factory = _session_factory(page)
    return tool, events


# -- Tests ----------------------------------------------------------------


def test_verify_classified_as_tier_1() -> None:
    """AD-706c-1: verify is silent / observation-only — tier 1."""
    page = _FakePage()
    sess = BrowserSession(session_id="s1", agent_id="a1", config=BrowserToolConfig(enabled=True))
    tier = classify_action(sess, "verify", {"expectation": "x"})
    assert tier == 1


@pytest.mark.asyncio
async def test_verify_happy_path_ok_true(monkeypatch: Any) -> None:
    page = _FakePage()
    runtime = _FakeRuntime(llm_response_text='{"ok": true, "observation": "Banner visible"}')
    _patch_attachment_store_lookup(monkeypatch, runtime._attachment_store)
    tool, events = _make_tool(runtime, page)
    result = await tool.invoke(
        {"action": "verify", "expectation": "Banner is visible"},
        {"agent_id": "a1"},
    )
    assert result.error is None, result.error
    payload = result.metadata or {}
    # invoke wraps the action output into ToolResult.metadata or returns it.
    # Real invoke returns the dict via .data — handle both.
    body = result.output if result.output else payload
    assert body.get("ok") is True
    assert "Banner" in body.get("observation", "")
    assert body.get("screenshot_ref")
    assert body.get("skipped_reason") is None


@pytest.mark.asyncio
async def test_verify_happy_path_ok_false(monkeypatch: Any) -> None:
    page = _FakePage()
    runtime = _FakeRuntime(llm_response_text='{"ok": false, "observation": "Spinner still showing"}')
    _patch_attachment_store_lookup(monkeypatch, runtime._attachment_store)
    tool, _events = _make_tool(runtime, page)
    result = await tool.invoke(
        {"action": "verify", "expectation": "Spinner gone"},
        {"agent_id": "a1"},
    )
    body = result.output if result.output else {}
    assert body.get("ok") is False


@pytest.mark.asyncio
async def test_verify_missing_expectation_returns_skipped(monkeypatch: Any) -> None:
    page = _FakePage()
    runtime = _FakeRuntime()
    _patch_attachment_store_lookup(monkeypatch, runtime._attachment_store)
    tool, _events = _make_tool(runtime, page)
    result = await tool.invoke(
        {"action": "verify", "expectation": ""},
        {"agent_id": "a1"},
    )
    body = result.output if result.output else {}
    assert body.get("ok") is None
    assert body.get("skipped_reason") == "missing_expectation"
    assert len(runtime.llm_client.calls) == 0  # no LLM call


@pytest.mark.asyncio
async def test_verify_expectation_truncated_at_500_chars(monkeypatch: Any) -> None:
    page = _FakePage()
    runtime = _FakeRuntime()
    _patch_attachment_store_lookup(monkeypatch, runtime._attachment_store)
    tool, _events = _make_tool(runtime, page)
    long_expect = "x" * 600
    result = await tool.invoke(
        {"action": "verify", "expectation": long_expect},
        {"agent_id": "a1"},
    )
    assert result.error is None
    # The LLM call payload should contain only the first 500 chars of expectation.
    sent_request = runtime.llm_client.calls[0]
    assert "x" * 500 in sent_request.prompt
    assert "x" * 501 not in sent_request.prompt


@pytest.mark.asyncio
async def test_verify_vision_tier_unconfigured_returns_none(monkeypatch: Any) -> None:
    page = _FakePage()
    runtime = _FakeRuntime(vision_configured=False)
    _patch_attachment_store_lookup(monkeypatch, runtime._attachment_store)
    tool, _events = _make_tool(runtime, page)
    result = await tool.invoke(
        {"action": "verify", "expectation": "anything"},
        {"agent_id": "a1"},
    )
    body = result.output if result.output else {}
    assert body.get("ok") is None
    assert body.get("skipped_reason") == "vision_unconfigured"
    assert len(runtime.llm_client.calls) == 0


@pytest.mark.asyncio
async def test_verify_llm_call_raises_returns_none(monkeypatch: Any) -> None:
    page = _FakePage()
    runtime = _FakeRuntime(llm_raises=True)
    _patch_attachment_store_lookup(monkeypatch, runtime._attachment_store)
    tool, _events = _make_tool(runtime, page)
    result = await tool.invoke(
        {"action": "verify", "expectation": "anything"},
        {"agent_id": "a1"},
    )
    body = result.output if result.output else {}
    assert body.get("ok") is None
    assert body.get("skipped_reason") == "vision_unavailable"


@pytest.mark.asyncio
async def test_verify_screenshot_stored_as_ref_not_inline(monkeypatch: Any) -> None:
    """AD-731 invariant: screenshot bytes go through AttachmentStore.write,
    keyed by sha256 of the bytes; the returned ref is that hex digest."""
    png = b"\x89PNGfake-image-bytes"
    page = _FakePage(screenshot_bytes=png)
    runtime = _FakeRuntime()
    store = runtime._attachment_store
    _patch_attachment_store_lookup(monkeypatch, store)
    tool, _events = _make_tool(runtime, page)
    result = await tool.invoke(
        {"action": "verify", "expectation": "anything"},
        {"agent_id": "a1"},
    )
    body = result.output if result.output else {}
    expected_hash = hashlib.sha256(png).hexdigest()
    assert body.get("screenshot_ref") == expected_hash
    assert store.blobs[expected_hash] == png
    assert store.mimes[expected_hash] == "image/png"


@pytest.mark.asyncio
async def test_verify_emits_browser_verify_observed(monkeypatch: Any) -> None:
    page = _FakePage()
    runtime = _FakeRuntime(llm_response_text='{"ok": true, "observation": "Form submitted"}')
    _patch_attachment_store_lookup(monkeypatch, runtime._attachment_store)
    tool, events = _make_tool(runtime, page)
    await tool.invoke(
        {"action": "verify", "expectation": "Form submitted"},
        {"agent_id": "a1"},
    )
    verify_events = [e for e in events if e[0] == EventType.BROWSER_VERIFY_OBSERVED]
    action_events = [e for e in events if e[0] == EventType.BROWSER_ACTION_EXECUTED]
    assert len(verify_events) == 1
    assert verify_events[0][1].get("ok") is True
    assert "Form submitted" in verify_events[0][1].get("observation", "")
    assert len(action_events) == 1


def test_parse_verify_response_handles_malformed_json() -> None:
    """Tier-2 honest-degrade: bad JSON -> ok=None, observation=clipped raw."""
    out = _parse_verify_response("not json at all")
    assert out["ok"] is None
    assert "not json" in out["observation"]
