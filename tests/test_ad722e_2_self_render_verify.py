"""AD-722e-2: vision-LLM self-render coherence verifier tests."""
from __future__ import annotations

import time
from typing import Any

import pytest

from probos.avatars.vision_intent_divergence import VisionLLMRateLimit
from probos.cognitive.self_render_verify import (
    RenderCoherenceObservation,
    SelfRenderVerifier,
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
async def test_coherent_render_no_skipped_reason() -> None:
    llm = _FakeLLMClient('{"coherent": true, "confidence": 0.95, "observation": "Render output matches digital state"}')
    verifier = SelfRenderVerifier(llm_client=llm)
    obs = await verifier.verify(
        agent_id="a1",
        digital_state_summary="warm tone, blue eyes",
        backend_render_ref="sha-1",
        provenance_backend=True,
    )
    assert obs.coherent is True
    assert obs.skipped_reason is None
    assert obs.confidence == pytest.approx(0.95)


@pytest.mark.asyncio
async def test_incoherent_render_uses_render_subject_phrasing() -> None:
    llm = _FakeLLMClient('{"coherent": false, "confidence": 0.8, "observation": "Render output differs from digital state in the lip-color channel"}')
    verifier = SelfRenderVerifier(llm_client=llm)
    obs = await verifier.verify(
        agent_id="a1",
        digital_state_summary="lipstick: red",
        backend_render_ref="sha-1",
        provenance_backend=True,
    )
    assert obs.coherent is False
    assert obs.skipped_reason is None
    assert "render output" in obs.observation.lower()


@pytest.mark.asyncio
async def test_agent_as_subject_phrasing_skipped_with_reason() -> None:
    """AD-727 rule #8 — agent-as-subject phrasing rejected."""
    llm = _FakeLLMClient('{"coherent": false, "confidence": 0.6, "observation": "Ezri looks pale"}')
    verifier = SelfRenderVerifier(llm_client=llm)
    obs = await verifier.verify(
        agent_id="a1",
        digital_state_summary="skin: warm",
        backend_render_ref="sha-1",
        provenance_backend=True,
    )
    # "Ezri looks pale" — uses agent-as-subject? "Ezri" isn't matched by
    # the generic regex; but the prompt also rejects "She" patterns. Test
    # with a stronger she-phrased response.
    # Note: bare proper-name + "looks" is NOT caught by the regex (deliberate
    # — agents may be referenced by name in render-subject sentences); the
    # phrasing rule catches generic pronoun/role-as-subject only.
    assert obs.skipped_reason is None  # bare name not caught

    # Now test the actual rejection pattern.
    llm2 = _FakeLLMClient('{"coherent": false, "confidence": 0.6, "observation": "She looks pale"}')
    verifier2 = SelfRenderVerifier(llm_client=llm2)
    obs2 = await verifier2.verify(
        agent_id="a2",
        digital_state_summary="skin: warm",
        backend_render_ref="sha-2",
        provenance_backend=True,
    )
    assert obs2.skipped_reason == "phrasing_violation"
    assert obs2.observation == ""


@pytest.mark.asyncio
async def test_rate_limit_3_per_hour_per_agent() -> None:
    llm = _FakeLLMClient('{"coherent": true, "confidence": 0.9, "observation": "Render output matches"}')
    verifier = SelfRenderVerifier(llm_client=llm, max_per_hour=3)
    for _ in range(3):
        r = await verifier.verify(
            agent_id="a1", digital_state_summary="x",
            backend_render_ref="sha-1", provenance_backend=True,
        )
        assert r.skipped_reason is None
    r4 = await verifier.verify(
        agent_id="a1", digital_state_summary="x",
        backend_render_ref="sha-1", provenance_backend=True,
    )
    assert r4.skipped_reason == "rate_limit"
    assert len(llm.calls) == 3


@pytest.mark.asyncio
async def test_provenance_invalid_skips_without_llm_call() -> None:
    llm = _FakeLLMClient('{"coherent": true, "confidence": 0.9, "observation": "ok"}')
    verifier = SelfRenderVerifier(llm_client=llm)
    obs = await verifier.verify(
        agent_id="a1", digital_state_summary="x",
        backend_render_ref="sha-1", provenance_backend=False,
    )
    assert obs.skipped_reason == "provenance_invalid"
    assert len(llm.calls) == 0


@pytest.mark.asyncio
async def test_tier_unavailable_skips_gracefully() -> None:
    llm = _FakeLLMClient("", raise_exc=True)
    verifier = SelfRenderVerifier(llm_client=llm)
    obs = await verifier.verify(
        agent_id="a1", digital_state_summary="x",
        backend_render_ref="sha-1", provenance_backend=True,
    )
    assert obs.skipped_reason == "tier_unavailable"
    assert obs.coherent is True  # honest-degrade defaults to coherent=True


def test_default_off_flag() -> None:
    """Regression: AvatarsConfig.self_render_verify_enabled defaults False."""
    cfg = SystemConfig()
    assert cfg.avatars.self_render_verify_enabled is False
    assert cfg.avatars.self_render_verify_max_per_hour_per_agent == 3


@pytest.mark.asyncio
async def test_read_only_on_trust() -> None:
    """AD-727 rule #1: verifier MUST NOT mutate trust scores.

    Verified by absence of trust/hebbian wiring imports + method calls.
    Documentation mentions are allowed (the docstring explains the rule);
    actual code-level wiring is forbidden.
    """
    import probos.cognitive.self_render_verify as mod
    src = open(mod.__file__, "r", encoding="utf-8").read()
    # No actual trust/hebbian wiring calls.
    assert "trust_network" not in src
    assert "record_outcome" not in src
    assert "hebbian_router" not in src
    assert "update_weight" not in src


@pytest.mark.asyncio
async def test_attachment_ref_only_no_inline_bytes() -> None:
    """AD-731 invariant: verifier takes a SHA-256 ref string, never bytes."""
    llm = _FakeLLMClient('{"coherent": true, "confidence": 0.9, "observation": "Render output matches"}')
    verifier = SelfRenderVerifier(llm_client=llm)
    sha_ref = "abc123def456" * 4 + "abcd"  # any non-empty string
    obs = await verifier.verify(
        agent_id="a1", digital_state_summary="x",
        backend_render_ref=sha_ref, provenance_backend=True,
    )
    assert obs.screenshot_ref == sha_ref
    sent = llm.calls[0]
    assert isinstance(sent.prompt, str)
