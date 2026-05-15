"""AD-722a-1: vision-LLM intent-vs-render divergence detector tests."""
from __future__ import annotations

import time
from typing import Any

import pytest

from probos.avatars.vision_intent_divergence import (
    VisionIntentDivergenceDetector,
    VisionLLMRateLimit,
    is_render_phrased,
)
from probos.config import SystemConfig


class _FakeLLMResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeLLMClient:
    def __init__(self, response_text: str, raise_exc: bool = False) -> None:
        self._text = response_text
        self._raise = raise_exc
        self.calls: list[Any] = []

    async def complete(self, request: Any, *, priority: Any = None) -> _FakeLLMResponse:
        self.calls.append(request)
        if self._raise:
            raise RuntimeError("vision tier offline")
        return _FakeLLMResponse(self._text)


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    VisionLLMRateLimit.reset_all()
    yield
    VisionLLMRateLimit.reset_all()


@pytest.mark.asyncio
async def test_detect_match_returns_no_divergence() -> None:
    llm = _FakeLLMClient('{"conveys_intent": true, "confidence": 0.9, "observation": "the expression conveys warmth"}')
    detector = VisionIntentDivergenceDetector(llm_client=llm)
    result = await detector.detect(
        agent_id="a1", intent="warm",
        rendered_attachment_ref="sha-1", provenance_backend=True,
    )
    assert result.divergence_detected is False
    assert result.confidence == pytest.approx(0.9)
    assert result.skipped_reason is None


@pytest.mark.asyncio
async def test_detect_mismatch_returns_divergence() -> None:
    llm = _FakeLLMClient('{"conveys_intent": false, "confidence": 0.7, "observation": "the expression appears flat"}')
    detector = VisionIntentDivergenceDetector(llm_client=llm)
    result = await detector.detect(
        agent_id="a1", intent="warm",
        rendered_attachment_ref="sha-1", provenance_backend=True,
    )
    assert result.divergence_detected is True
    assert result.confidence == pytest.approx(0.7)
    assert result.skipped_reason is None


@pytest.mark.asyncio
async def test_rate_limit_enforces_3_per_hour_per_agent() -> None:
    llm = _FakeLLMClient('{"conveys_intent": true, "confidence": 0.8, "observation": "the render is consistent"}')
    detector = VisionIntentDivergenceDetector(llm_client=llm, max_per_hour=3)
    # 3 calls under the cap.
    for _ in range(3):
        r = await detector.detect(
            agent_id="a1", intent="warm",
            rendered_attachment_ref="sha-1", provenance_backend=True,
        )
        assert r.skipped_reason is None
    # 4th call hits the cap.
    r4 = await detector.detect(
        agent_id="a1", intent="warm",
        rendered_attachment_ref="sha-1", provenance_backend=True,
    )
    assert r4.skipped_reason == "rate_limit"
    assert len(llm.calls) == 3


@pytest.mark.asyncio
async def test_rate_limit_expires_after_3600s(monkeypatch: Any) -> None:
    llm = _FakeLLMClient('{"conveys_intent": true, "confidence": 0.8, "observation": "the render is steady"}')
    detector = VisionIntentDivergenceDetector(llm_client=llm, max_per_hour=1)
    await detector.detect(
        agent_id="a1", intent="warm",
        rendered_attachment_ref="sha-1", provenance_backend=True,
    )
    # 2nd call rate-limited.
    r = await detector.detect(
        agent_id="a1", intent="warm",
        rendered_attachment_ref="sha-1", provenance_backend=True,
    )
    assert r.skipped_reason == "rate_limit"
    # Advance the clock past the window and the cap re-opens.
    import probos.avatars.vision_intent_divergence as mod
    real_time = time.time
    monkeypatch.setattr(mod.time, "time", lambda: real_time() + 3700.0)
    r2 = await detector.detect(
        agent_id="a1", intent="warm",
        rendered_attachment_ref="sha-1", provenance_backend=True,
    )
    assert r2.skipped_reason is None


@pytest.mark.asyncio
async def test_provenance_invalid_skips_without_calling_llm() -> None:
    llm = _FakeLLMClient('{"conveys_intent": true, "confidence": 0.9, "observation": "the render looks ok"}')
    detector = VisionIntentDivergenceDetector(llm_client=llm)
    result = await detector.detect(
        agent_id="a1", intent="warm",
        rendered_attachment_ref="sha-1", provenance_backend=False,
    )
    assert result.skipped_reason == "provenance_invalid"
    assert len(llm.calls) == 0


@pytest.mark.asyncio
async def test_tier_unavailable_returns_skipped() -> None:
    llm = _FakeLLMClient("", raise_exc=True)
    detector = VisionIntentDivergenceDetector(llm_client=llm)
    result = await detector.detect(
        agent_id="a1", intent="warm",
        rendered_attachment_ref="sha-1", provenance_backend=True,
    )
    assert result.skipped_reason == "tier_unavailable"
    assert result.divergence_detected is False


@pytest.mark.asyncio
async def test_phrasing_rule_regex_enforced() -> None:
    """AD-727 rule #8: agent-as-subject phrasing must be rejected."""
    llm = _FakeLLMClient('{"conveys_intent": false, "confidence": 0.6, "observation": "She looks sad"}')
    detector = VisionIntentDivergenceDetector(llm_client=llm)
    result = await detector.detect(
        agent_id="a1", intent="warm",
        rendered_attachment_ref="sha-1", provenance_backend=True,
    )
    assert result.skipped_reason == "phrasing_violation"
    assert result.observation == ""


def test_default_off_flag() -> None:
    """Regression: AvatarsConfig.vision_intent_divergence_enabled defaults False."""
    cfg = SystemConfig()
    assert cfg.avatars.vision_intent_divergence_enabled is False
    assert cfg.avatars.vision_intent_divergence_max_per_hour_per_agent == 3


@pytest.mark.asyncio
async def test_attachment_ref_not_inline_bytes() -> None:
    """AD-731 invariant: detector takes a SHA-256 ref string, not bytes."""
    llm = _FakeLLMClient('{"conveys_intent": true, "confidence": 0.8, "observation": "the render is consistent"}')
    detector = VisionIntentDivergenceDetector(llm_client=llm)
    sha_ref = "0703319ff5e017c23fde84094828f0134bea338feb6e5edf3254efe401f4c642"
    result = await detector.detect(
        agent_id="a1", intent="warm",
        rendered_attachment_ref=sha_ref, provenance_backend=True,
    )
    assert result.rendered_attachment_ref == sha_ref
    # The LLM request must not carry inline bytes — only the ref string in prompt.
    sent = llm.calls[0]
    assert isinstance(sent.prompt, str)
    # No bytes payload smuggled through.
    assert "data:" not in sent.prompt or sha_ref not in str(sent.prompt).split("data:")[0]


def test_is_render_phrased_helper() -> None:
    assert is_render_phrased("the expression appears strained") is True
    assert is_render_phrased("the render lacks warmth") is True
    assert is_render_phrased("") is True
    assert is_render_phrased("she looks sad") is False
    assert is_render_phrased("The agent appears agitated") is False
    assert is_render_phrased("They seem uncertain") is False
