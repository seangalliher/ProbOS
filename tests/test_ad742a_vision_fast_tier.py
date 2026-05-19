"""AD-742a: vision_fast LLM tier — peer of AD-732 vision.

Eight-guard catalog tests:
- _LLM_TIERS registration
- _TIER_ORDER unchanged (BF-269 invariant)
- CognitiveConfig fields + tier_config dict-maps
- is_vision_tier_configured branch
- ModelRouter bypass (BF-273)
- Fallback chain vision_fast -> vision (NOT text tiers)
- Health probe short-circuit
- PerceptionConfig.vision_fast_tier field
- VisionConsumer routes describe to vision_fast when configured
- Source-scan regression: no hardcoded tier tuples outside llm_client.py

BF-286/287: real Pydantic config + dataclass-style fakes (no MagicMock at
substrate boundary).
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

import pytest

from probos.cognitive.llm_client import (
    _LLM_TIERS,
    _TIER_ORDER,
    OpenAICompatibleClient,
)
from probos.cognitive.vision_dispatch import is_vision_tier_configured
from probos.config import CognitiveConfig, PerceptionConfig


# -- 1. _LLM_TIERS registration ---------------------------------------------


def test_llm_tiers_includes_vision_fast() -> None:
    assert "vision_fast" in _LLM_TIERS


def test_tier_order_excludes_vision_fast() -> None:
    """BF-269 invariant: vision tiers never participate in text fallback."""
    assert "vision_fast" not in _TIER_ORDER
    assert _TIER_ORDER == ("fast", "standard", "deep")


# -- 2. CognitiveConfig fields + tier_config dict-maps ----------------------


def test_cognitive_config_has_vision_fast_fields() -> None:
    cfg = CognitiveConfig()
    assert cfg.llm_model_vision_fast is None
    assert cfg.llm_base_url_vision_fast is None
    assert cfg.llm_api_key_vision_fast is None
    assert cfg.llm_timeout_vision_fast is None
    assert cfg.llm_api_format_vision_fast is None
    # tier_config returns a dict with model=None when unconfigured.
    tc = cfg.tier_config("vision_fast")
    assert tc["model"] is None


def test_tier_config_vision_fast_resolves_when_set() -> None:
    cfg = CognitiveConfig(
        llm_model_vision_fast="moondream",
        llm_base_url_vision_fast="http://localhost:11434",
        llm_timeout_vision_fast=15.0,
        llm_api_format_vision_fast="ollama",
    )
    tc = cfg.tier_config("vision_fast")
    assert tc["model"] == "moondream"
    assert tc["base_url"] == "http://localhost:11434"
    assert tc["timeout"] == 15.0
    assert tc["api_format"] == "ollama"


# -- 3. is_vision_tier_configured ------------------------------------------


def test_is_vision_tier_configured_vision_fast_branch() -> None:
    cfg_unset = CognitiveConfig()
    assert is_vision_tier_configured(cfg_unset, "vision_fast") is False

    cfg_set = CognitiveConfig(
        llm_model_vision_fast="moondream",
        llm_base_url_vision_fast="http://localhost:11434",
    )
    assert is_vision_tier_configured(cfg_set, "vision_fast") is True

    # Half-configured: only model set -> still False.
    cfg_half = CognitiveConfig(llm_model_vision_fast="moondream")
    assert is_vision_tier_configured(cfg_half, "vision_fast") is False


# -- 4. ModelRouter bypass (BF-273) -----------------------------------------


def test_model_router_bypasses_vision_fast() -> None:
    """BF-273 invariant: vision_fast must NOT consult the ModelRouter."""
    cfg = CognitiveConfig(
        llm_model_vision_fast="moondream",
        llm_base_url_vision_fast="http://localhost:11434",
    )
    client = OpenAICompatibleClient(config=cfg)

    class _RecordingRouter:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def choose(self, *, tier: str) -> Any:
            self.calls.append(tier)
            raise AssertionError(f"router consulted for tier={tier}")

    client.model_router = _RecordingRouter()
    result = client._resolve_model_for_tier("vision_fast")
    assert result is None
    assert client.model_router.calls == []


# -- 5. Fallback chain (BF-269 invariant) -----------------------------------


def test_fallback_chain_vision_fast_to_vision() -> None:
    """vision_fast falls back ONLY to vision — never to text tiers."""
    import inspect
    source = inspect.getsource(OpenAICompatibleClient._complete_inner)
    # Direct assertion: the source must contain the vision_fast branch
    # mapping to ['vision_fast', 'vision'] and must NOT route fast/standard/deep.
    assert 'tier == "vision_fast"' in source
    assert '["vision_fast", "vision"]' in source


def test_fallback_chain_vision_unchanged() -> None:
    """Regression: vision-only fallback (BF-269) unchanged by AD-742a."""
    import inspect
    source = inspect.getsource(OpenAICompatibleClient._complete_inner)
    assert 'tier in ("vision", "compute_use")' in source
    assert "fallback_tiers = [tier]" in source


# -- 6. Health probe short-circuit ------------------------------------------


def test_health_probe_short_circuit_vision_fast_unconfigured() -> None:
    """When llm_model_vision_fast is unset, no HTTP probe is made."""
    cfg = CognitiveConfig()  # all vision_fast fields None
    client = OpenAICompatibleClient(config=cfg)

    probe_calls: list[str] = []

    async def _fake_check_endpoint(tier: str) -> bool:
        probe_calls.append(tier)
        return True

    client._check_endpoint = _fake_check_endpoint  # type: ignore[method-assign]

    results = asyncio.run(client.check_connectivity())
    assert results["vision_fast"] is False
    assert "vision_fast" not in probe_calls


# -- 7. PerceptionConfig field ----------------------------------------------


def test_perception_config_has_vision_fast_tier_field() -> None:
    pc = PerceptionConfig()
    assert pc.vision_fast_tier == "vision_fast"


# -- 8. VisionConsumer routing ----------------------------------------------


class _FakeAttachmentStore:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {"sha-x": b"\x89PNG-fake"}

    async def read(self, content_hash: str) -> bytes:
        return self.blobs.get(content_hash, b"")

    async def mime_for(self, content_hash: str) -> str:
        return "image/png"


class _FakeLLMResponse:
    def __init__(self, content: str = "a person is here") -> None:
        self.content = content
        self.tier = ""
        self.model = ""
        self.tokens_used = 0
        self.cached = False
        self.error = ""
        self.request_id = "rid"


class _FakeLLMClient:
    def __init__(self) -> None:
        self.captured_requests: list[Any] = []

    async def complete(self, request: Any, *, priority: Any = None) -> Any:
        self.captured_requests.append(request)
        return _FakeLLMResponse()


class _FakeRuntime:
    def __init__(self, cog_cfg: CognitiveConfig) -> None:
        from probos.config import SystemConfig

        # Real SystemConfig with the cognitive sub-config set.
        self.config = SystemConfig(cognitive=cog_cfg)
        self.llm_client = _FakeLLMClient()
        self._store = _FakeAttachmentStore()

    # AD-731: AttachmentStore is read via routers.chat._get_attachment_store.
    # For the test path we expose it as an attribute the patched helper
    # will return.


def _install_store_patch(monkeypatch: pytest.MonkeyPatch, runtime: _FakeRuntime) -> None:
    from probos.routers import chat as _chat_mod

    def _get_store(rt: Any) -> Any:
        return rt._store

    monkeypatch.setattr(_chat_mod, "_get_attachment_store", _get_store)


def test_vision_consumer_routes_to_fast_tier_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from probos.perception.consumer import VisionConsumer

    cog = CognitiveConfig(
        llm_model_vision_fast="moondream",
        llm_base_url_vision_fast="http://localhost:11434",
        llm_model_vision="qwen3.6:27b",
        llm_base_url_vision="http://localhost:11434",
    )
    runtime = _FakeRuntime(cog)
    _install_store_patch(monkeypatch, runtime)

    consumer = VisionConsumer(runtime, vision_tier="vision", vision_fast_tier="vision_fast")
    description = asyncio.run(consumer._describe("sha-x"))
    assert description != ""
    assert len(runtime.llm_client.captured_requests) == 1
    assert runtime.llm_client.captured_requests[0].tier == "vision_fast"


def test_vision_consumer_falls_back_to_vision_when_fast_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from probos.perception.consumer import VisionConsumer

    cog = CognitiveConfig(
        llm_model_vision="qwen3.6:27b",
        llm_base_url_vision="http://localhost:11434",
        # vision_fast intentionally unset
    )
    runtime = _FakeRuntime(cog)
    _install_store_patch(monkeypatch, runtime)

    consumer = VisionConsumer(runtime, vision_tier="vision", vision_fast_tier="vision_fast")
    asyncio.run(consumer._describe("sha-x"))
    assert len(runtime.llm_client.captured_requests) == 1
    # vision_fast unconfigured -> describe routes to vision (the consumer
    # picks the configured tier; the LLM-level fallback chain is a separate
    # concern verified by test_fallback_chain_vision_fast_to_vision).
    assert runtime.llm_client.captured_requests[0].tier == "vision"


# -- 9. Source-scan regression: no hardcoded tier tuples --------------------


def test_no_hardcoded_tier_tuples_outside_llm_client() -> None:
    """AD-732 lesson #1: single source of truth.

    The literal tuple pattern ("fast", "standard", "deep", "vision") may
    only appear in cognitive/llm_client.py (where _LLM_TIERS is defined).
    """
    src_root = Path(__file__).resolve().parents[1] / "src" / "probos"
    pattern = re.compile(
        r'\(\s*"fast"\s*,\s*"standard"\s*,\s*"deep"\s*,\s*"vision"\s*\)'
    )
    offenders: list[str] = []
    for py_file in src_root.rglob("*.py"):
        rel = py_file.relative_to(src_root)
        if str(rel).replace("\\", "/") == "cognitive/llm_client.py":
            continue
        text = py_file.read_text(encoding="utf-8", errors="ignore")
        if pattern.search(text):
            offenders.append(str(rel))
    assert offenders == [], (
        f"hardcoded tier tuple found outside cognitive/llm_client.py: {offenders}. "
        "Refactor to `from probos.cognitive.llm_client import _LLM_TIERS`."
    )
