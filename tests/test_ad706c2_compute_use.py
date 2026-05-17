"""AD-706c-2: coordinate-aware ``compute_use_click`` action tests.

All vision/compute_use LLM calls stubbed. AD-731 invariant: screenshot
bytes flow through AttachmentStore.write keyed by SHA-256. BF-269: no
fallback chain. BF-272: no cache. BF-273: ModelRouter bypass. BF-287:
real Pydantic config (SystemConfig, BrowserToolConfig) + dataclass fakes
at the substrate boundary.
"""
from __future__ import annotations

import hashlib
import inspect
from pathlib import Path
from typing import Any

import pytest

from probos.config import BrowserToolConfig, SystemConfig
from probos.events import EventType
from probos.tools.browser import actions as actions_module
from probos.tools.browser import compute_use as compute_use_module
from probos.tools.browser.actions import _HANDLERS, classify_action
from probos.tools.browser.compute_use import action_compute_use_click
from probos.tools.browser.session import BrowserSession


# -- Fakes ----------------------------------------------------------------


class _FakeMouse:
    def __init__(self) -> None:
        self.clicks: list[tuple[int, int]] = []

    async def click(self, x: int, y: int) -> None:
        self.clicks.append((x, y))


class _FakePage:
    def __init__(self, *, screenshot_bytes: bytes = b"\x89PNGfake") -> None:
        self._png = screenshot_bytes
        self.url = "https://example.com/canvas"
        self.viewport_size = {"width": 1024, "height": 768}
        self.mouse = _FakeMouse()

    async def screenshot(self) -> bytes:
        return self._png


class _FakeAttachmentStore:
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
        self.tier = "compute_use"
        self.latency_ms = 12.0


class _FakeLLMClient:
    def __init__(
        self,
        *,
        compute_use_responses: list[str] | None = None,
        vision_response: str = '{"ok": true, "observation": "near target"}',
        raise_compute_use: bool = False,
    ) -> None:
        self._compute_use_responses = list(compute_use_responses or [
            '{"x": 100, "y": 200, "confidence": 0.9}',
        ])
        self._vision_response = vision_response
        self._raise_compute_use = raise_compute_use
        self.calls: list[Any] = []

    async def complete(self, request: Any, *, priority: Any = None) -> _FakeLLMResponse:
        self.calls.append(request)
        if request.tier == "compute_use":
            if self._raise_compute_use:
                raise RuntimeError("compute_use offline")
            if not self._compute_use_responses:
                return _FakeLLMResponse('{"x": 0, "y": 0, "confidence": 0.0}')
            return _FakeLLMResponse(self._compute_use_responses.pop(0))
        # vision-tier verify call
        return _FakeLLMResponse(self._vision_response)


class _FakeRuntime:
    def __init__(
        self,
        *,
        compute_use_configured: bool = True,
        vision_configured: bool = True,
        compute_use_responses: list[str] | None = None,
        vision_response: str = '{"ok": true, "observation": "near target"}',
        raise_compute_use: bool = False,
        store: _FakeAttachmentStore | None = None,
    ) -> None:
        self.config = SystemConfig()
        if vision_configured:
            self.config.cognitive.llm_model_vision = "qwen3.6:27b"
            self.config.cognitive.llm_base_url_vision = "http://localhost:11434"
        if compute_use_configured:
            self.config.cognitive.llm_model_compute_use = "qwen3.6:27b-cu"
            self.config.cognitive.llm_base_url_compute_use = "http://localhost:11434"
        self.config.browser_tool.enabled = True
        self.llm_client = _FakeLLMClient(
            compute_use_responses=compute_use_responses,
            vision_response=vision_response,
            raise_compute_use=raise_compute_use,
        )
        self._attachment_store = store or _FakeAttachmentStore()


def _patch_store(monkeypatch: Any, store: _FakeAttachmentStore) -> None:
    from probos.routers import chat as _chat
    monkeypatch.setattr(_chat, "_get_attachment_store", lambda rt: store)


def _make_session(*, browser_cfg: BrowserToolConfig | None = None, page: _FakePage | None = None) -> BrowserSession:
    cfg = browser_cfg or BrowserToolConfig(enabled=True)
    sess = BrowserSession(session_id="s-cu-1", agent_id="a1", config=cfg)
    sess._page = page or _FakePage()  # noqa: SLF001 — test fixture
    return sess


def _events_recorder() -> tuple[list[tuple[Any, Any]], Any]:
    events: list[tuple[Any, Any]] = []
    def _emit(et: Any, data: Any) -> None:
        events.append((et, data))
    return events, _emit


# -- Tests ----------------------------------------------------------------


def test_compute_use_action_registered_in_handlers() -> None:
    """The new verb is wired into the late-bind _HANDLERS dict."""
    assert "compute_use_click" in _HANDLERS
    assert _HANDLERS["compute_use_click"] is action_compute_use_click
    assert callable(_HANDLERS["compute_use_click"])


def test_compute_use_always_tier_3() -> None:
    """classify_action returns 3 unconditionally for compute_use_click."""
    sess = _make_session()
    assert classify_action(sess, "compute_use_click", {}) == 3
    assert classify_action(sess, "compute_use_click", {"intent": "click button"}) == 3


def test_compute_use_llm_classifier_short_circuits() -> None:
    """AD-706d companion: rule_tier=3 short-circuits before any LLM call."""
    from probos.tools.browser.llm_classifier import classify_action_with_llm

    runtime = _FakeRuntime()
    result = classify_action_with_llm(
        runtime=runtime,
        rule_tier=3,
        action="compute_use_click",
        url="https://example.com/x",
        element_text="",
        page_title="X",
    )
    assert result == 3
    # Short-circuit means no LLM call ran.
    assert len(runtime.llm_client.calls) == 0


def test_no_fallback_chain_module_level() -> None:
    """BF-269 enforcement: module-level _TIER_ORDER excludes vision + compute_use."""
    from probos.cognitive.llm_client import _TIER_ORDER

    assert "compute_use" not in _TIER_ORDER
    assert "vision" not in _TIER_ORDER
    assert set(_TIER_ORDER) == {"fast", "standard", "deep"}


def test_compute_use_in_llm_tiers() -> None:
    """compute_use is the fifth peer in _LLM_TIERS."""
    from probos.cognitive.llm_client import _LLM_TIERS

    assert "compute_use" in _LLM_TIERS
    assert _LLM_TIERS == ("fast", "standard", "deep", "vision", "compute_use")


@pytest.mark.asyncio
async def test_compute_use_unconfigured_honest_degrades(monkeypatch: Any) -> None:
    runtime = _FakeRuntime(compute_use_configured=False)
    _patch_store(monkeypatch, runtime._attachment_store)
    sess = _make_session()
    events, emit = _events_recorder()

    result = await action_compute_use_click(
        sess,
        {"intent": "click the play button"},
        runtime=runtime,
        emit_event=emit,
    )
    assert result["ok"] is False
    assert result["skipped_reason"] == "compute_use_unconfigured"
    assert len(runtime.llm_client.calls) == 0
    assert events == []


@pytest.mark.asyncio
async def test_compute_use_missing_intent(monkeypatch: Any) -> None:
    runtime = _FakeRuntime()
    _patch_store(monkeypatch, runtime._attachment_store)
    sess = _make_session()
    events, emit = _events_recorder()

    result = await action_compute_use_click(
        sess,
        {"intent": "   "},
        runtime=runtime,
        emit_event=emit,
    )
    assert result["ok"] is False
    assert result["skipped_reason"] == "missing_intent"
    assert len(runtime.llm_client.calls) == 0


@pytest.mark.asyncio
async def test_compute_use_happy_path_writes_ref_and_executes(monkeypatch: Any) -> None:
    """End-to-end: screenshot -> AttachmentStore -> LLM -> verify -> mouse.click."""
    png = b"PNG-canvas-frame-bytes"
    page = _FakePage(screenshot_bytes=png)
    runtime = _FakeRuntime(
        compute_use_responses=['{"x": 100, "y": 200, "confidence": 0.92}'],
        vision_response='{"ok": true, "observation": "Play button at (100,200)"}',
    )
    store = runtime._attachment_store
    _patch_store(monkeypatch, store)
    sess = _make_session(page=page)
    events, emit = _events_recorder()

    result = await action_compute_use_click(
        sess,
        {"intent": "click the play button"},
        runtime=runtime,
        emit_event=emit,
    )
    assert result["ok"] is True, result
    assert result["x"] == 100
    assert result["y"] == 200
    assert result["verified"] is True
    # Mouse click executed.
    assert page.mouse.clicks == [(100, 200)]
    # Screenshot persisted to AttachmentStore keyed by SHA-256.
    expected_sha = hashlib.sha256(png).hexdigest()
    assert expected_sha in store.blobs
    # Events: PROPOSED, VERIFY_OBSERVED (from action_verify), VERIFIED, EXECUTED.
    types = [et for et, _ in events]
    assert EventType.BROWSER_COMPUTE_USE_CLICK_PROPOSED in types
    assert EventType.BROWSER_COMPUTE_USE_CLICK_VERIFIED in types
    assert EventType.BROWSER_COMPUTE_USE_CLICK_EXECUTED in types
    # Counters incremented.
    assert sess.compute_use_total_calls == 1
    assert sess.compute_use_consecutive_autonomous == 1


@pytest.mark.asyncio
async def test_compute_use_verification_disagreement_aborts_click(monkeypatch: Any) -> None:
    runtime = _FakeRuntime(
        compute_use_responses=['{"x": 50, "y": 60, "confidence": 0.8}'],
        vision_response='{"ok": false, "observation": "no element at (50,60)"}',
    )
    _patch_store(monkeypatch, runtime._attachment_store)
    page = _FakePage()
    sess = _make_session(page=page)
    events, emit = _events_recorder()

    result = await action_compute_use_click(
        sess,
        {"intent": "open menu"},
        runtime=runtime,
        emit_event=emit,
    )
    assert result["ok"] is False
    assert result["skipped_reason"] == "verification_failed"
    assert result["verified"] is False
    assert page.mouse.clicks == []  # NOT executed
    types = [et for et, _ in events]
    assert EventType.BROWSER_COMPUTE_USE_CLICK_PROPOSED in types
    assert EventType.BROWSER_COMPUTE_USE_CLICK_ABORTED in types
    assert EventType.BROWSER_COMPUTE_USE_CLICK_EXECUTED not in types


@pytest.mark.asyncio
async def test_compute_use_parse_error_honest_degrades(monkeypatch: Any) -> None:
    runtime = _FakeRuntime(compute_use_responses=["not json at all"])
    _patch_store(monkeypatch, runtime._attachment_store)
    page = _FakePage()
    sess = _make_session(page=page)
    events, emit = _events_recorder()

    result = await action_compute_use_click(
        sess,
        {"intent": "click submit"},
        runtime=runtime,
        emit_event=emit,
    )
    assert result["ok"] is False
    assert result["skipped_reason"] == "parse_error"
    assert page.mouse.clicks == []
    # Failed attempts still consume the budget.
    assert sess.compute_use_total_calls == 1


@pytest.mark.asyncio
async def test_compute_use_no_cache_two_calls_two_llm_hits(monkeypatch: Any) -> None:
    """BF-272 enforcement: identical screenshots produce two LLM calls
    (compute_use bypasses any cache; multimodal cache key would collide)."""
    runtime = _FakeRuntime(
        compute_use_responses=[
            '{"x": 10, "y": 10, "confidence": 0.9}',
            '{"x": 20, "y": 20, "confidence": 0.9}',
        ],
    )
    _patch_store(monkeypatch, runtime._attachment_store)
    page = _FakePage()
    sess = _make_session(page=page)
    _events, emit = _events_recorder()

    await action_compute_use_click(sess, {"intent": "first"}, runtime=runtime, emit_event=emit)
    await action_compute_use_click(sess, {"intent": "second"}, runtime=runtime, emit_event=emit)
    # Two compute_use calls AND two verify (vision) calls = 4 total.
    compute_use_calls = [c for c in runtime.llm_client.calls if c.tier == "compute_use"]
    assert len(compute_use_calls) == 2


@pytest.mark.asyncio
async def test_compute_use_model_router_bypass() -> None:
    """BF-273 enforcement: ModelRouter bypassed for compute_use exactly as vision."""
    from probos.cognitive.llm_client import OpenAICompatibleClient

    # Construct via __new__ to skip __init__ (no live router needed).
    client = OpenAICompatibleClient.__new__(OpenAICompatibleClient)
    assert client._resolve_model_for_tier("compute_use") is None
    assert client._resolve_model_for_tier("vision") is None


@pytest.mark.asyncio
async def test_compute_use_trust_budget_consecutive_cap(monkeypatch: Any) -> None:
    """Calls beyond compute_use_max_consecutive_autonomous_actions honest-degrade."""
    cfg = BrowserToolConfig(
        enabled=True,
        compute_use_max_consecutive_autonomous_actions=2,
        compute_use_max_per_session=50,
    )
    runtime = _FakeRuntime(
        compute_use_responses=[
            '{"x": 1, "y": 1, "confidence": 0.9}',
            '{"x": 2, "y": 2, "confidence": 0.9}',
            '{"x": 3, "y": 3, "confidence": 0.9}',
        ],
    )
    runtime.config.browser_tool = cfg
    _patch_store(monkeypatch, runtime._attachment_store)
    page = _FakePage()
    sess = _make_session(browser_cfg=cfg, page=page)
    _events, emit = _events_recorder()

    # Call 1 + 2: succeed.
    r1 = await action_compute_use_click(sess, {"intent": "a"}, runtime=runtime, emit_event=emit)
    r2 = await action_compute_use_click(sess, {"intent": "b"}, runtime=runtime, emit_event=emit)
    assert r1["ok"] is True
    assert r2["ok"] is True
    # Call 3: budget exhausted.
    r3 = await action_compute_use_click(sess, {"intent": "c"}, runtime=runtime, emit_event=emit)
    assert r3["ok"] is False
    assert r3["skipped_reason"] == "trust_budget_exhausted"
    # ACK refreshes the budget.
    sess.note_captain_ack()
    r4 = await action_compute_use_click(sess, {"intent": "d"}, runtime=runtime, emit_event=emit)
    assert r4["ok"] is True


@pytest.mark.asyncio
async def test_compute_use_trust_budget_per_session_cap(monkeypatch: Any) -> None:
    """Per-session total cap independent of consecutive cap."""
    cfg = BrowserToolConfig(
        enabled=True,
        compute_use_max_consecutive_autonomous_actions=20,
        compute_use_max_per_session=3,
    )
    runtime = _FakeRuntime(
        compute_use_responses=[
            '{"x": 1, "y": 1, "confidence": 0.9}',
            '{"x": 2, "y": 2, "confidence": 0.9}',
            '{"x": 3, "y": 3, "confidence": 0.9}',
            '{"x": 4, "y": 4, "confidence": 0.9}',
        ],
    )
    runtime.config.browser_tool = cfg
    _patch_store(monkeypatch, runtime._attachment_store)
    page = _FakePage()
    sess = _make_session(browser_cfg=cfg, page=page)
    _events, emit = _events_recorder()

    for i in range(3):
        r = await action_compute_use_click(sess, {"intent": f"call-{i}"}, runtime=runtime, emit_event=emit)
        assert r["ok"] is True, (i, r)
    r4 = await action_compute_use_click(sess, {"intent": "call-3"}, runtime=runtime, emit_event=emit)
    assert r4["ok"] is False
    assert r4["skipped_reason"] == "trust_budget_exhausted"


def test_compute_use_source_uses_attachment_store_refs_not_inline() -> None:
    """AD-731 invariant: source has no base64 inline encoding."""
    src = inspect.getsource(compute_use_module)
    assert "b64encode" not in src
    assert "base64.b64" not in src
    # Positive: must use sha256 ref + AttachmentStore.
    assert "hashlib.sha256" in src
    assert "store.write" in src


def test_compute_use_source_uses_openai_shape_resolver() -> None:
    """BF-268 lesson: compute_use uses build_multimodal_messages which feeds
    into ``_resolve_attachment_refs_for_openai`` at the OpenAI client. The
    source must import build_multimodal_messages from vision_dispatch."""
    src = inspect.getsource(compute_use_module)
    assert "build_multimodal_messages" in src
    # Must NOT use Anthropic source.base64 shape.
    assert "source.base64" not in src
    assert '"type": "image"' not in src or "image_url" in src  # if hand-rolled
