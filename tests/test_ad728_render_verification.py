"""AD-728: vision-LLM render-coherence mirror function tests."""
from __future__ import annotations

import inspect
from typing import Any

import pytest

from probos.avatars import render_verification as rv
from probos.avatars.render_verification import (
    RenderCoherenceResult,
    verify_render_coherence,
)
from probos.avatars.vision_intent_divergence import VisionLLMRateLimit
from probos.config import SystemConfig
from probos.events import EventType


class _FakeLLMResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeLLMClient:
    def __init__(self, response_text: str | list[str], raise_exc: bool = False) -> None:
        if isinstance(response_text, str):
            self._queue = [response_text]
        else:
            self._queue = list(response_text)
        self._raise = raise_exc
        self.requests: list[Any] = []

    async def complete(self, request: Any, *, priority: Any = None) -> _FakeLLMResponse:
        self.requests.append(request)
        if self._raise:
            raise RuntimeError("vision tier offline")
        if not self._queue:
            return _FakeLLMResponse("")
        return _FakeLLMResponse(self._queue.pop(0))


class _FakeRuntime:
    """Minimal runtime stub for AD-728. Provides the public API the function
    actually reads — config, llm_client, attachment_store, emit_event."""

    def __init__(
        self,
        *,
        config: SystemConfig,
        llm_client: Any,
        attachment_store: Any = None,
    ) -> None:
        self.config = config
        self.llm_client = llm_client
        self.attachment_store = attachment_store
        self.emitted: list[tuple[EventType, dict[str, Any]]] = []

    async def emit_event(self, event_type: EventType, payload: dict[str, Any]) -> None:
        self.emitted.append((event_type, dict(payload)))


def _config_enabled() -> SystemConfig:
    cfg = SystemConfig()
    cfg.avatars.render_verification_enabled = True
    cfg.avatars.render_verification_max_per_hour_per_agent = 3
    return cfg


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    VisionLLMRateLimit.reset_all()
    yield
    VisionLLMRateLimit.reset_all()


# 1. Coherent happy path (no event emission).
@pytest.mark.asyncio
async def test_coherent_no_event_emitted() -> None:
    llm = _FakeLLMClient(
        '{"coherent": true, "analog_description": "Render output for Ezri shows warm amber tone", "divergence_summary": ""}'
    )
    rt = _FakeRuntime(config=_config_enabled(), llm_client=llm)
    result = await verify_render_coherence(
        runtime=rt, agent_id="ezri", trigger="captain_command",
        digital_state_summary="warm amber tone",
        backend_render_ref="sha256:abc",
    )
    assert result.coherent is True
    assert result.skipped_reason is None
    assert rt.emitted == []


# 2. Divergent emits RENDER_DIVERGENCE_OBSERVED.
@pytest.mark.asyncio
async def test_divergent_emits_render_divergence_event() -> None:
    llm = _FakeLLMClient(
        '{"coherent": false, "analog_description": "Render output for Ezri shows pale skin tone", '
        '"divergence_summary": "Render output for Ezri differs from her digital state in skin-tone channel"}'
    )
    rt = _FakeRuntime(config=_config_enabled(), llm_client=llm)
    result = await verify_render_coherence(
        runtime=rt, agent_id="ezri", trigger="captain_command",
        digital_state_summary="warm amber tone",
        backend_render_ref="sha256:abc",
    )
    assert result.coherent is False
    assert len(rt.emitted) == 1
    event_type, payload = rt.emitted[0]
    assert event_type is EventType.RENDER_DIVERGENCE_OBSERVED
    assert payload["agent_id"] == "ezri"
    assert payload["trigger"] == "captain_command"
    assert "Render output" in payload["divergence_summary"]


# 3. Disabled → honest-degrade.
@pytest.mark.asyncio
async def test_disabled_honest_degrades() -> None:
    cfg = SystemConfig()
    # default render_verification_enabled = False
    llm = _FakeLLMClient("unused")
    rt = _FakeRuntime(config=cfg, llm_client=llm)
    result = await verify_render_coherence(
        runtime=rt, agent_id="ezri", trigger="captain_command",
        digital_state_summary="warm",
        backend_render_ref="sha256:abc",
    )
    assert result.coherent is None
    assert result.skipped_reason == "disabled"
    assert llm.requests == []


# 4. Backend renderer unavailable.
@pytest.mark.asyncio
async def test_backend_render_unavailable() -> None:
    llm = _FakeLLMClient("unused")
    rt = _FakeRuntime(config=_config_enabled(), llm_client=llm)
    result = await verify_render_coherence(
        runtime=rt, agent_id="ezri", trigger="captain_command",
        digital_state_summary="warm",
        backend_render_ref=None,
    )
    assert result.coherent is None
    assert result.skipped_reason == "backend_render_unavailable"


# 5. Vision LLM failure.
@pytest.mark.asyncio
async def test_vision_llm_failure_honest_degrades() -> None:
    llm = _FakeLLMClient("unused", raise_exc=True)
    rt = _FakeRuntime(config=_config_enabled(), llm_client=llm)
    result = await verify_render_coherence(
        runtime=rt, agent_id="ezri", trigger="captain_command",
        digital_state_summary="warm",
        backend_render_ref="sha256:abc",
    )
    assert result.coherent is None
    assert result.skipped_reason == "tier_unavailable"


# 6. Rate-limit exhaustion.
@pytest.mark.asyncio
async def test_rate_limit_exhaustion_honest_degrades() -> None:
    llm = _FakeLLMClient(
        ['{"coherent": true, "analog_description": "Render output ok", "divergence_summary": ""}'] * 4
    )
    rt = _FakeRuntime(config=_config_enabled(), llm_client=llm)
    for _ in range(3):
        r = await verify_render_coherence(
            runtime=rt, agent_id="ezri", trigger="captain_command",
            digital_state_summary="x", backend_render_ref="sha256:1",
        )
        assert r.skipped_reason is None
    r4 = await verify_render_coherence(
        runtime=rt, agent_id="ezri", trigger="captain_command",
        digital_state_summary="x", backend_render_ref="sha256:1",
    )
    assert r4.skipped_reason == "rate_limited"


# 7a. captain_command trigger happy.
@pytest.mark.asyncio
async def test_captain_command_trigger_happy() -> None:
    llm = _FakeLLMClient(
        '{"coherent": true, "analog_description": "Render output ok", "divergence_summary": ""}'
    )
    rt = _FakeRuntime(config=_config_enabled(), llm_client=llm)
    r = await verify_render_coherence(
        runtime=rt, agent_id="ezri", trigger="captain_command",
        digital_state_summary="x", backend_render_ref="sha256:1",
    )
    assert r.trigger == "captain_command"
    assert r.skipped_reason is None


# 7b. divergence_followup trigger requires followup_enabled flag.
@pytest.mark.asyncio
async def test_divergence_followup_disabled_by_default() -> None:
    llm = _FakeLLMClient(
        '{"coherent": true, "analog_description": "Render output ok", "divergence_summary": ""}'
    )
    rt = _FakeRuntime(config=_config_enabled(), llm_client=llm)
    # followup_enabled default-False even when render_verification_enabled True.
    r = await verify_render_coherence(
        runtime=rt, agent_id="ezri", trigger="divergence_followup",
        digital_state_summary="x", backend_render_ref="sha256:1",
    )
    assert r.skipped_reason == "followup_disabled"


@pytest.mark.asyncio
async def test_divergence_followup_enabled_passes_through() -> None:
    cfg = _config_enabled()
    cfg.avatars.render_verification_followup_enabled = True
    llm = _FakeLLMClient(
        '{"coherent": true, "analog_description": "Render output ok", "divergence_summary": ""}'
    )
    rt = _FakeRuntime(config=cfg, llm_client=llm)
    r = await verify_render_coherence(
        runtime=rt, agent_id="ezri", trigger="divergence_followup",
        digital_state_summary="x", backend_render_ref="sha256:1",
    )
    assert r.skipped_reason is None
    assert r.trigger == "divergence_followup"


# 7c. agent_initiated_stub default-OFF preserves AD-728 baseline behavior.
#     AD-728c flips this trigger to a gated path when
#     render_self_check_enabled=True; with the gate OFF the AD-728 baseline
#     ("agent_initiated_disabled") is preserved exactly.
@pytest.mark.asyncio
async def test_agent_initiated_stub_default_off_preserves_baseline() -> None:
    cfg = _config_enabled()
    # AD-728c gate explicitly OFF (also the Pydantic default).
    cfg.avatars.render_self_check_enabled = False
    rt = _FakeRuntime(config=cfg, llm_client=_FakeLLMClient("unused"))
    r = await verify_render_coherence(
        runtime=rt, agent_id="ezri", trigger="agent_initiated_stub",
        digital_state_summary="x", backend_render_ref="sha256:1",
    )
    assert r.skipped_reason == "agent_initiated_disabled"


# 8. RENDER_DIVERGENCE_OBSERVED payload integrity.
@pytest.mark.asyncio
async def test_render_divergence_payload_integrity() -> None:
    llm = _FakeLLMClient(
        '{"coherent": false, "analog_description": "Render output for Ezri shows pale", '
        '"divergence_summary": "Render output for Ezri differs from her digital state"}'
    )
    rt = _FakeRuntime(config=_config_enabled(), llm_client=llm)
    await verify_render_coherence(
        runtime=rt, agent_id="ezri", trigger="captain_command",
        digital_state_summary="warm tone",
        backend_render_ref="sha256:abc",
    )
    _, payload = rt.emitted[0]
    assert payload["agent_id"] == "ezri"
    assert payload["trigger"] == "captain_command"
    assert payload["digital_description"] == "warm tone"
    assert "Render output" in payload["divergence_summary"]
    assert payload["severity"] in {"low", "high"}
    assert "timestamp" in payload


# 9. Phrasing rejection: agent-as-subject in analog → re-prompt, then drop.
@pytest.mark.asyncio
async def test_phrasing_rejected_after_reprompt() -> None:
    # First response uses agent-as-subject; retry also bad → drop.
    llm = _FakeLLMClient([
        '{"coherent": false, "analog_description": "She looks tired", "divergence_summary": "Render output differs"}',
        '{"coherent": false, "analog_description": "She looks tired again", "divergence_summary": "Render output differs"}',
    ])
    rt = _FakeRuntime(config=_config_enabled(), llm_client=llm)
    r = await verify_render_coherence(
        runtime=rt, agent_id="ezri", trigger="captain_command",
        digital_state_summary="warm",
        backend_render_ref="sha256:abc",
    )
    assert r.skipped_reason == "phrasing_rejected"
    # No divergence event emitted on phrasing-rejected.
    assert rt.emitted == []


# 10. AD-731 invariant: no inline base64 in IntentMessage / LLMRequest.
@pytest.mark.asyncio
async def test_ad731_invariant_no_inline_base64() -> None:
    """The function reads source code: 'attachment_ids=[backend_render_ref]'
    means refs flow as IDs, not bytes. Sanity-grep the module source for
    base64 inlining patterns."""
    source = inspect.getsource(rv)
    # Forbidden: encoding bytes to base64 in the IntentMessage params path.
    assert "b64encode" not in source
    assert "base64.b64" not in source
    # Required: ref-based attachment_ids parameter.
    assert "attachment_ids=[backend_render_ref]" in source


# 11. AD-727 rule #1: source-scan for trust_network / hebbian → empty.
def test_ad727_trust_isolation_source_scan() -> None:
    source = inspect.getsource(rv)
    lower = source.lower()
    assert "trust_network" not in lower
    assert "hebbian" not in lower


# 12. Coherent observations are NOT logged (cost discipline).
@pytest.mark.asyncio
async def test_coherent_does_not_emit_event() -> None:
    llm = _FakeLLMClient(
        '{"coherent": true, "analog_description": "Render output for Ezri shows warm tone", "divergence_summary": ""}'
    )
    rt = _FakeRuntime(config=_config_enabled(), llm_client=llm)
    r = await verify_render_coherence(
        runtime=rt, agent_id="ezri", trigger="captain_command",
        digital_state_summary="warm",
        backend_render_ref="sha256:abc",
    )
    assert r.coherent is True
    # No event emitted for coherent observations.
    assert all(et is not EventType.RENDER_DIVERGENCE_OBSERVED for et, _ in rt.emitted)
    assert rt.emitted == []
