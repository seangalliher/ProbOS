"""Tests for AD-730-3: agent image generation in DM replies.

Real ``SystemConfig()`` per BF-287. Hand-rolled ``_FakeAttachmentStore``
(in-memory dict), ``_FakeRuntime``. ``httpx.MockTransport`` for the
image_gen endpoint.

Eight-guard regressions (per AD-732 lesson, user-memory 2026-05-12):
``image_gen`` MUST be in ``_LLM_TIERS``, MUST NOT be in ``_TIER_ORDER``,
``tier_config("image_gen")`` MUST resolve, and ``dm/reply_pipeline.py``
MUST NOT contain inline base64 (AD-731 invariant).
"""

from __future__ import annotations

import base64
import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest

from probos.cognitive.dm_sanity_gate import DmSanityGate
from probos.cognitive.image_gen_dispatch import (
    IMAGE_GEN_DISABLED_MESSAGE,
    IMAGE_GEN_FAILED_MESSAGE,
    IMAGE_GEN_TOO_LARGE_MESSAGE,
    IMAGE_GEN_UNCONFIGURED_MESSAGE,
    _WELLNESS_REVIEW_SEEN,
    dispatch_image_gen,
    is_image_gen_tier_configured,
)
from probos.cognitive.llm_client import _LLM_TIERS, _TIER_ORDER
from probos.config import SystemConfig
from probos.cognitive.dm.reply_value import DmReply  # AD-1248


PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c63000000000000050001f4f5f5070000000049454e"
    "44ae426082"
)


@dataclass
class _FakeAttachmentStore:
    items: dict[str, tuple[bytes, str]] = field(default_factory=dict)
    raise_on_write: bool = False

    async def write(self, content_hash: str, blob: bytes, mime: str) -> Path:
        if self.raise_on_write:
            raise RuntimeError("simulated store failure")
        self.items[content_hash] = (blob, mime)
        return Path("/fake") / content_hash


@dataclass
class _FakeRuntime:
    config: Any
    attachment_store: Any
    episodic_memory: Any | None = None


def _runtime(
    *,
    enabled: bool = True,
    configured: bool = True,
    wellness_required: bool = True,
    max_bytes: int = 4 * 1024 * 1024,
) -> _FakeRuntime:
    cfg = SystemConfig()
    cfg.avatars.image_gen_enabled = enabled
    cfg.avatars.image_gen_wellness_review_required = wellness_required
    cfg.avatars.image_gen_max_image_bytes = max_bytes
    if configured:
        cfg.cognitive.llm_base_url_image_gen = "https://images.test"
        cfg.cognitive.llm_model_image_gen = "dall-e-3"
        cfg.cognitive.llm_api_key_image_gen = "sk-test"
        cfg.cognitive.llm_timeout_image_gen = 5.0
    return _FakeRuntime(config=cfg, attachment_store=_FakeAttachmentStore())


def _install_mock_transport(
    monkeypatch: pytest.MonkeyPatch,
    handler: "callable[[httpx.Request], httpx.Response]",
) -> None:
    transport = httpx.MockTransport(handler)
    original_init = httpx.AsyncClient.__init__

    def patched_init(self: httpx.AsyncClient, *args: Any, **kwargs: Any) -> None:
        kwargs["transport"] = transport
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)


@pytest.fixture(autouse=True)
def _reset_wellness_seen() -> None:
    _WELLNESS_REVIEW_SEEN.clear()
    yield
    _WELLNESS_REVIEW_SEEN.clear()


@pytest.mark.asyncio
async def test_dispatch_unconfigured_returns_honest_degrade() -> None:
    runtime = _runtime(configured=False)
    result = await dispatch_image_gen(runtime, agent_id="diagnostician", prompt="chart")
    assert result == {
        "ok": False,
        "reason": "image_gen_unconfigured",
        "message": IMAGE_GEN_UNCONFIGURED_MESSAGE,
    }


@pytest.mark.asyncio
async def test_dispatch_master_switch_off_returns_honest_degrade() -> None:
    runtime = _runtime(enabled=False)
    result = await dispatch_image_gen(runtime, agent_id="diagnostician", prompt="x")
    assert result["ok"] is False
    assert result["reason"] == "image_gen_disabled"
    assert result["message"] == IMAGE_GEN_DISABLED_MESSAGE


@pytest.mark.asyncio
async def test_dispatch_happy_path_writes_to_store_returns_sha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/images/generations")
        body = {"data": [{"b64_json": base64.b64encode(PNG_1x1).decode("ascii")}]}
        return httpx.Response(200, json=body)

    _install_mock_transport(monkeypatch, handler)

    result = await dispatch_image_gen(runtime, agent_id="diagnostician", prompt="chart")
    assert result["ok"] is True
    expected_sha = hashlib.sha256(PNG_1x1).hexdigest()
    assert result["attachment_id"] == expected_sha
    assert result["mime"] == "image/png"
    assert result["size_bytes"] == len(PNG_1x1)
    assert expected_sha in runtime.attachment_store.items
    stored_blob, stored_mime = runtime.attachment_store.items[expected_sha]
    assert stored_blob == PNG_1x1
    assert stored_mime == "image/png"


@pytest.mark.asyncio
async def test_dispatch_http_500_returns_honest_degrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="upstream busted")

    _install_mock_transport(monkeypatch, handler)
    result = await dispatch_image_gen(runtime, agent_id="a1", prompt="x")
    assert result["ok"] is False
    assert result["reason"] == "http_500"
    assert result["message"] == IMAGE_GEN_FAILED_MESSAGE


@pytest.mark.asyncio
async def test_dispatch_parse_error_returns_honest_degrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    _install_mock_transport(monkeypatch, handler)
    result = await dispatch_image_gen(runtime, agent_id="a1", prompt="x")
    assert result["ok"] is False
    assert result["reason"] == "parse_error"


@pytest.mark.asyncio
async def test_dispatch_too_large_returns_honest_degrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime(max_bytes=64 * 1024)
    big_blob = b"\x00" * (128 * 1024)

    def handler(request: httpx.Request) -> httpx.Response:
        body = {"data": [{"b64_json": base64.b64encode(big_blob).decode("ascii")}]}
        return httpx.Response(200, json=body)

    _install_mock_transport(monkeypatch, handler)
    result = await dispatch_image_gen(runtime, agent_id="a1", prompt="x")
    assert result["ok"] is False
    assert result["reason"] == "too_large"
    assert result["message"] == IMAGE_GEN_TOO_LARGE_MESSAGE


@pytest.mark.asyncio
async def test_dispatch_transport_error_returns_honest_degrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime()

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _install_mock_transport(monkeypatch, handler)
    result = await dispatch_image_gen(runtime, agent_id="a1", prompt="x")
    assert result["ok"] is False
    assert result["reason"] == "transport_error"


@pytest.mark.asyncio
async def test_wellness_review_emitted_on_first_call_only(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    runtime = _runtime()

    def handler(request: httpx.Request) -> httpx.Response:
        body = {"data": [{"b64_json": base64.b64encode(PNG_1x1).decode("ascii")}]}
        return httpx.Response(200, json=body)

    _install_mock_transport(monkeypatch, handler)
    with caplog.at_level(logging.WARNING, logger="probos.cognitive.image_gen_dispatch"):
        await dispatch_image_gen(runtime, agent_id="diag", prompt="chart")
        first_count = sum(1 for r in caplog.records if "WELLNESS REVIEW" in r.message)
        await dispatch_image_gen(runtime, agent_id="diag", prompt="chart2")
        total_count = sum(1 for r in caplog.records if "WELLNESS REVIEW" in r.message)
    assert first_count == 1
    assert total_count == 1


def test_is_image_gen_tier_configured_negative_when_base_url_missing() -> None:
    cfg = SystemConfig()
    assert is_image_gen_tier_configured(cfg.cognitive) is False
    cfg.cognitive.llm_model_image_gen = "dall-e-3"
    assert is_image_gen_tier_configured(cfg.cognitive) is False


def test_is_image_gen_tier_configured_positive_when_both_set() -> None:
    cfg = SystemConfig()
    cfg.cognitive.llm_base_url_image_gen = "https://images.test"
    cfg.cognitive.llm_model_image_gen = "dall-e-3"
    assert is_image_gen_tier_configured(cfg.cognitive) is True


def test_extract_gen_image_returns_first_valid_prompt() -> None:
    gate = DmSanityGate()
    text = "Here is the chart: [GEN_IMAGE bar chart of sensor data]"
    assert gate.extract_gen_image(text) == ["bar chart of sensor data"]


def test_extract_gen_image_truncated_when_exceeds_max_chars() -> None:
    gate = DmSanityGate()
    long_prompt = "x" * 100
    text = f"reply [GEN_IMAGE {long_prompt}]"
    # max_chars below the prompt length → excluded from result.
    assert gate.extract_gen_image(text, max_chars=50) == []
    # But still stripped from text.
    assert "[GEN_IMAGE" not in gate.strip_gen_image(text)


def test_strip_gen_image_removes_well_and_malformed_markers() -> None:
    gate = DmSanityGate()
    text = "ok [GEN_IMAGE proper] and [GEN_IMAGE oops missing close text"
    out = gate.strip_gen_image(text)
    assert "[GEN_IMAGE" not in out
    assert out.startswith("ok")


@pytest.mark.asyncio
async def test_pipeline_step_4c_attaches_sha_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from probos.cognitive.dm.reply_pipeline import DmReplyContext, DmReplyPipeline

    runtime = _runtime()

    def handler(request: httpx.Request) -> httpx.Response:
        body = {"data": [{"b64_json": base64.b64encode(PNG_1x1).decode("ascii")}]}
        return httpx.Response(200, json=body)

    _install_mock_transport(monkeypatch, handler)

    gate = DmSanityGate()
    ctx = DmReplyContext(
        runtime=runtime,
        agent=None,
        agent_id="diag",
        callsign="DIAG",
        req_message="show me",
        reply=DmReply(body="Here you go: [GEN_IMAGE sensor chart]"),
        has_image_attachment=False,
        per_attachment=[],
        sanity_gate=gate,
        params={},
        message_text="show me",
        sampling_state=None,
        avatar_event_bus=None,
    )
    pipeline = DmReplyPipeline(ctx)
    await pipeline.step_4c_image_gen_parse()

    expected_sha = hashlib.sha256(PNG_1x1).hexdigest()
    assert ctx.generated_attachment_ids == [expected_sha]
    assert "[GEN_IMAGE" not in ctx.response_text
    response = pipeline.build_response()
    assert response["attachment_ids"] == [expected_sha]


@pytest.mark.asyncio
async def test_pipeline_step_4c_strips_marker_when_disabled() -> None:
    from probos.cognitive.dm.reply_pipeline import DmReplyContext, DmReplyPipeline

    runtime = _runtime(enabled=False)
    gate = DmSanityGate()
    ctx = DmReplyContext(
        runtime=runtime,
        agent=None,
        agent_id="diag",
        callsign="DIAG",
        req_message="show me",
        reply=DmReply(body="text [GEN_IMAGE chart]"),
        has_image_attachment=False,
        per_attachment=[],
        sanity_gate=gate,
        params={},
        message_text="show me",
        sampling_state=None,
        avatar_event_bus=None,
    )
    pipeline = DmReplyPipeline(ctx)
    await pipeline.step_4c_image_gen_parse()
    assert "[GEN_IMAGE" not in ctx.response_text
    assert ctx.generated_attachment_ids == []
    response = pipeline.build_response()
    assert "attachment_ids" not in response
    assert IMAGE_GEN_DISABLED_MESSAGE in ctx.response_text


# --- Eight-guard regression tests (AD-732 lesson) ---


def test_image_gen_in_LLM_TIERS() -> None:
    assert "image_gen" in _LLM_TIERS


def test_image_gen_NOT_in_TIER_ORDER() -> None:
    assert "image_gen" not in _TIER_ORDER


def test_tier_config_image_gen_resolves() -> None:
    cfg = SystemConfig()
    cfg.cognitive.llm_base_url_image_gen = "https://images.test"
    cfg.cognitive.llm_model_image_gen = "dall-e-3"
    cfg.cognitive.llm_api_key_image_gen = "sk-test"
    cfg.cognitive.llm_timeout_image_gen = 30.0
    resolved = cfg.cognitive.tier_config("image_gen")
    for key in (
        "base_url", "api_key", "model", "timeout",
        "api_format", "temperature", "top_p", "max_tokens",
    ):
        assert key in resolved
    assert resolved["base_url"] == "https://images.test"
    assert resolved["model"] == "dall-e-3"
    assert resolved["api_key"] == "sk-test"
    assert resolved["timeout"] == 30.0


def test_no_inline_base64_in_reply_pipeline_source() -> None:
    """AD-731 invariant: reply pipeline carries SHA refs, not bytes.

    ``b64encode`` and ``b64_json`` are allowed only at the API boundary
    inside ``image_gen_dispatch.py``; they MUST NOT appear in the
    pipeline module's source.
    """
    pipeline_path = (
        Path(__file__).resolve().parents[1]
        / "src" / "probos" / "cognitive" / "dm" / "reply_pipeline.py"
    )
    source = pipeline_path.read_text(encoding="utf-8")
    assert "b64encode" not in source
    assert "b64_json" not in source
    # The bytes path in the pipeline is `attachment_ids` — refs only.
    assert "attachment_ids" in source


def test_image_gen_dispatch_does_not_invoke_model_router_or_cache() -> None:
    """BF-272/BF-273: image_gen MUST NOT consult ModelRouter or the
    LLMResponseCache. Source-scan asserts no import or invocation;
    docstring mentions of the bypass are allowed.
    """
    dispatch_path = (
        Path(__file__).resolve().parents[1]
        / "src" / "probos" / "cognitive" / "image_gen_dispatch.py"
    )
    source = dispatch_path.read_text(encoding="utf-8")
    # No import of the routing/cache modules.
    assert "from probos.cognitive.model_router" not in source
    assert "import model_router" not in source
    assert "from probos.cognitive.llm_cache" not in source
    assert "from probos.cognitive.llm_response_cache" not in source
    # No invocation of the routing or cache methods.
    assert ".by_tier(" not in source
    assert "ModelRouter(" not in source
    assert "LLMResponseCache(" not in source
    # And no participation in the text-tier fallback chain.
    assert "_TIER_ORDER" not in source
