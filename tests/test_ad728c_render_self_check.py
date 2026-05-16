"""AD-728c: agent-initiated render self-check tests.

Two-budget contextual rate limit (hourly OR per-active-conversation, never
additive) + working-memory ingress via AgentWorkingMemory.record_observation.

Test scaffolding: real SystemConfig() fixtures (BF-287, no MagicMock at the
config boundary). Hand-rolled @dataclass agent stub (BF-287 retrospective:
MagicMock(spec=...) silently auto-creates phantom attributes; AD-722b-4 was
the canonical break).
"""
from __future__ import annotations

import dataclasses
import inspect
from typing import Any

import pytest

from probos.avatars import render_verification as rv
from probos.avatars.render_verification import verify_render_coherence
from probos.avatars.vision_intent_divergence import VisionLLMRateLimit
from probos.cognitive.agent_working_memory import AgentWorkingMemory
from probos.config import SystemConfig
from probos.events import EventType


class _FakeLLMResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeLLMClient:
    def __init__(self, response_text: str | list[str]) -> None:
        if isinstance(response_text, str):
            self._queue = [response_text]
        else:
            self._queue = list(response_text)
        self.requests: list[Any] = []

    async def complete(self, request: Any, *, priority: Any = None) -> _FakeLLMResponse:
        self.requests.append(request)
        if not self._queue:
            return _FakeLLMResponse("")
        return _FakeLLMResponse(self._queue.pop(0))


@dataclasses.dataclass
class _AgentStub:
    """Hand-rolled stub — NOT MagicMock(spec=CognitiveAgent).

    BF-287: MagicMock auto-attribute behavior silently passes tests against
    phantom attribute names. Hand-rolled dataclass forces a real attribute
    lookup that fails fast if production code reads the wrong name.
    """

    id: str
    last_reply_emitted_at: float = 0.0


class _AgentRegistryStub:
    """Real `.get(...)` method — BF-287 requires public registry API."""

    def __init__(self, agents: dict[str, _AgentStub] | None = None) -> None:
        self._agents = agents or {}

    def get(self, agent_id: str) -> _AgentStub | None:
        return self._agents.get(agent_id)


class _FakeRuntime:
    def __init__(
        self,
        *,
        config: SystemConfig,
        llm_client: Any,
        registry: _AgentRegistryStub | None = None,
        attachment_store: Any = None,
    ) -> None:
        self.config = config
        self.llm_client = llm_client
        self.registry = registry or _AgentRegistryStub()
        self.attachment_store = attachment_store
        self.emitted: list[tuple[EventType, dict[str, Any]]] = []

    async def emit_event(self, event_type: EventType, payload: dict[str, Any]) -> None:
        self.emitted.append((event_type, dict(payload)))


def _config_self_check_enabled() -> SystemConfig:
    """Real Pydantic SystemConfig with AD-728 + AD-728c flags ON."""
    cfg = SystemConfig()
    cfg.avatars.render_verification_enabled = True
    cfg.avatars.render_verification_max_per_hour_per_agent = 3
    cfg.avatars.render_self_check_enabled = True
    cfg.avatars.render_self_check_max_per_hour_per_agent = 3
    cfg.avatars.render_self_check_max_per_active_conversation = 2
    cfg.avatars.render_self_check_active_window_seconds = 600
    return cfg


def _coherent_payload() -> str:
    return (
        '{"coherent": true, "analog_description": '
        '"Render output for Ezri shows warm amber tone", '
        '"divergence_summary": ""}'
    )


def _divergent_payload() -> str:
    return (
        '{"coherent": false, "analog_description": '
        '"Render output for Ezri shows pale skin tone", '
        '"divergence_summary": "Render output for Ezri differs from her '
        'digital state in skin-tone channel"}'
    )


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    VisionLLMRateLimit.reset_all()
    yield
    VisionLLMRateLimit.reset_all()


# 1. Trigger flipped: with self-check enabled, agent_initiated_stub no longer
#    returns "agent_initiated_disabled".
@pytest.mark.asyncio
async def test_self_check_enabled_no_longer_hard_rejected() -> None:
    cfg = _config_self_check_enabled()
    llm = _FakeLLMClient(_coherent_payload())
    rt = _FakeRuntime(config=cfg, llm_client=llm)
    result = await verify_render_coherence(
        runtime=rt, agent_id="ezri", trigger="agent_initiated_stub",
        digital_state_summary="warm amber tone",
        backend_render_ref="sha256:abc",
    )
    assert result.skipped_reason is None
    assert result.coherent is True


# 2. Default-OFF: preserves AD-728 baseline.
@pytest.mark.asyncio
async def test_self_check_default_off_returns_agent_initiated_disabled() -> None:
    cfg = SystemConfig()
    cfg.avatars.render_verification_enabled = True
    cfg.avatars.render_verification_max_per_hour_per_agent = 3
    # render_self_check_enabled default = False
    rt = _FakeRuntime(config=cfg, llm_client=_FakeLLMClient("unused"))
    result = await verify_render_coherence(
        runtime=rt, agent_id="ezri", trigger="agent_initiated_stub",
        digital_state_summary="x", backend_render_ref="sha256:1",
    )
    assert result.skipped_reason == "agent_initiated_disabled"


# 3. Hourly budget enforced when agent NOT in an active conversation.
#    Budget default = 3; 4th call returns rate_limited_self_check.
@pytest.mark.asyncio
async def test_hourly_budget_enforced_when_not_active() -> None:
    cfg = _config_self_check_enabled()
    llm = _FakeLLMClient([_coherent_payload()] * 4)
    # registry returns an agent with last_reply_emitted_at=0.0 → NOT active
    registry = _AgentRegistryStub({"ezri": _AgentStub(id="ezri", last_reply_emitted_at=0.0)})
    rt = _FakeRuntime(config=cfg, llm_client=llm, registry=registry)
    for _ in range(3):
        r = await verify_render_coherence(
            runtime=rt, agent_id="ezri", trigger="agent_initiated_stub",
            digital_state_summary="x", backend_render_ref="sha256:1",
        )
        assert r.skipped_reason is None
    r4 = await verify_render_coherence(
        runtime=rt, agent_id="ezri", trigger="agent_initiated_stub",
        digital_state_summary="x", backend_render_ref="sha256:1",
    )
    assert r4.skipped_reason == "rate_limited_self_check"


# 4. Active-conversation budget enforced.
#    Budget default = 2; 3rd call returns rate_limited_self_check.
@pytest.mark.asyncio
async def test_active_conversation_budget_enforced() -> None:
    import time as _time
    cfg = _config_self_check_enabled()
    llm = _FakeLLMClient([_coherent_payload()] * 3)
    # last_reply_emitted_at = now → in active window
    registry = _AgentRegistryStub({
        "ezri": _AgentStub(id="ezri", last_reply_emitted_at=_time.time()),
    })
    rt = _FakeRuntime(config=cfg, llm_client=llm, registry=registry)
    for _ in range(2):
        r = await verify_render_coherence(
            runtime=rt, agent_id="ezri", trigger="agent_initiated_stub",
            digital_state_summary="x", backend_render_ref="sha256:1",
        )
        assert r.skipped_reason is None
    r3 = await verify_render_coherence(
        runtime=rt, agent_id="ezri", trigger="agent_initiated_stub",
        digital_state_summary="x", backend_render_ref="sha256:1",
    )
    assert r3.skipped_reason == "rate_limited_self_check"


# 5. Budget-switch correctness: agent in active conversation does NOT
#    consume the hourly bucket. After the active window closes, the hourly
#    bucket is independent of any per-conversation calls made earlier.
@pytest.mark.asyncio
async def test_active_conversation_does_not_consume_hourly_bucket() -> None:
    import time as _time
    cfg = _config_self_check_enabled()
    llm = _FakeLLMClient([_coherent_payload()] * 5)
    # Phase 1: agent IS in an active conversation. Exhaust the per-
    # conversation budget (default 2).
    now = _time.time()
    agent = _AgentStub(id="ezri", last_reply_emitted_at=now)
    registry = _AgentRegistryStub({"ezri": agent})
    rt = _FakeRuntime(config=cfg, llm_client=llm, registry=registry)
    for _ in range(2):
        r = await verify_render_coherence(
            runtime=rt, agent_id="ezri", trigger="agent_initiated_stub",
            digital_state_summary="x", backend_render_ref="sha256:1",
        )
        assert r.skipped_reason is None

    # Phase 2: simulate "active window closed" by zeroing the agent's
    # last_reply_emitted_at. The hourly bucket should be untouched by the
    # phase-1 conversation budget consumption, so 3 fresh calls succeed.
    agent.last_reply_emitted_at = 0.0
    for _ in range(3):
        r = await verify_render_coherence(
            runtime=rt, agent_id="ezri", trigger="agent_initiated_stub",
            digital_state_summary="x", backend_render_ref="sha256:1",
        )
        assert r.skipped_reason is None, (
            "Phase-1 per-conversation budget MUST NOT consume hourly "
            "bucket (two-budget rule: INSTEAD OF, never additive)."
        )

    # 4th hourly call exhausts the hourly budget.
    r_exhaust = await verify_render_coherence(
        runtime=rt, agent_id="ezri", trigger="agent_initiated_stub",
        digital_state_summary="x", backend_render_ref="sha256:1",
    )
    assert r_exhaust.skipped_reason == "rate_limited_self_check"


# 6. Coherent observation injected into working memory via check_own_render.
#    Uses monkeypatch on verify_render_coherence — exercises only the
#    WM-injection plumbing inside check_own_render. (The captain-pattern
#    call shape of check_own_render is verified by tests 3-5 + 11/12 via
#    direct verify_render_coherence calls.)
@pytest.mark.asyncio
async def test_check_own_render_coherent_records_observation(monkeypatch) -> None:
    from probos.cognitive.cognitive_agent import CognitiveAgent
    from probos.avatars.render_verification import RenderCoherenceResult
    import probos.avatars.render_verification as rv_mod

    wm = AgentWorkingMemory()
    rt = _FakeRuntime(config=_config_self_check_enabled(), llm_client=_FakeLLMClient("unused"))

    async def _fake(**kwargs):
        return RenderCoherenceResult(
            agent_id=kwargs["agent_id"], trigger=kwargs["trigger"],
            coherent=True,
            digital_description="warm amber tone",
            analog_description="Render output for Ezri shows warm amber tone",
            divergence_summary=None,
            skipped_reason=None,
            timestamp=0.0,
        )
    monkeypatch.setattr(rv_mod, "verify_render_coherence", _fake)

    surrogate = _AgentSurrogate(agent_id="ezri", runtime=rt, working_memory=wm)
    await CognitiveAgent.check_own_render(surrogate, reason="before_reply")

    obs = list(wm.get_buffers()["observations"])
    assert len(obs) == 1
    entry = obs[0]
    assert entry.category == "observation"
    assert "vision-LLM confirms" in entry.content
    assert entry.metadata["coherent"] is True
    assert entry.metadata["reason"] == "before_reply"
    assert entry.metadata["trigger"] == "agent_initiated_stub"


# 7. Divergent observation injected. Uses monkeypatch — see test 6 rationale.
@pytest.mark.asyncio
async def test_check_own_render_divergent_records_observation(monkeypatch) -> None:
    from probos.cognitive.cognitive_agent import CognitiveAgent
    from probos.avatars.render_verification import RenderCoherenceResult
    import probos.avatars.render_verification as rv_mod

    wm = AgentWorkingMemory()
    rt = _FakeRuntime(config=_config_self_check_enabled(), llm_client=_FakeLLMClient("unused"))

    async def _fake(**kwargs):
        return RenderCoherenceResult(
            agent_id=kwargs["agent_id"], trigger=kwargs["trigger"],
            coherent=False,
            digital_description="warm amber tone",
            analog_description="Render output for Ezri shows pale skin tone",
            divergence_summary="Render output differs in skin-tone channel",
            skipped_reason=None,
            timestamp=0.0,
        )
    monkeypatch.setattr(rv_mod, "verify_render_coherence", _fake)

    surrogate = _AgentSurrogate(agent_id="ezri", runtime=rt, working_memory=wm)
    await CognitiveAgent.check_own_render(surrogate, reason="mid_conversation")

    obs = list(wm.get_buffers()["observations"])
    assert len(obs) == 1
    entry = obs[0]
    assert entry.category == "observation"
    # Content includes analog and digital phrases.
    assert "shows" in entry.content
    assert "intended" in entry.content
    assert entry.metadata["coherent"] is False
    assert entry.metadata["reason"] == "mid_conversation"


# 8. Rate-limited observation MUST inject a throttle entry — honest-degrade.
#    Uses monkeypatch so the rate-limited path is exercised independently
#    of projection availability.
@pytest.mark.asyncio
async def test_check_own_render_rate_limited_records_throttle_entry(monkeypatch) -> None:
    from probos.cognitive.cognitive_agent import CognitiveAgent
    from probos.avatars.render_verification import RenderCoherenceResult
    import probos.avatars.render_verification as rv_mod

    wm = AgentWorkingMemory()
    rt = _FakeRuntime(config=_config_self_check_enabled(), llm_client=_FakeLLMClient("unused"))

    async def _fake(**kwargs):
        return RenderCoherenceResult(
            agent_id=kwargs["agent_id"], trigger=kwargs["trigger"],
            coherent=None,
            digital_description="",
            analog_description=None,
            divergence_summary=None,
            skipped_reason="rate_limited_self_check",
            timestamp=0.0,
        )
    monkeypatch.setattr(rv_mod, "verify_render_coherence", _fake)

    surrogate = _AgentSurrogate(agent_id="ezri", runtime=rt, working_memory=wm)
    await CognitiveAgent.check_own_render(surrogate, reason="before_reply")

    obs = list(wm.get_buffers()["observations"])
    assert len(obs) == 1
    entry = obs[0]
    assert entry.category == "observation"
    assert "throttled" in entry.content.lower()
    assert entry.metadata["skipped_reason"] == "rate_limited_self_check"
    assert entry.metadata["coherent"] is None


# 9. check_own_render MUST be a coroutine function (regression guard).
def test_check_own_render_is_coroutine() -> None:
    from probos.cognitive.cognitive_agent import CognitiveAgent
    assert inspect.iscoroutinefunction(CognitiveAgent.check_own_render)


# 10. AD-731 invariant preserved: no inline base64 in render_verification.py.
def test_ad731_invariant_no_inline_base64_after_ad728c() -> None:
    source = inspect.getsource(rv)
    assert "b64encode" not in source
    assert "base64.b64" not in source
    # Ref-based attachment path remains.
    assert "attachment_ids=[backend_render_ref]" in source


# 11. RENDER_DIVERGENCE_OBSERVED still emitted exactly once on agent-initiated
#     divergent calls (AD-728c does not break AD-728's event contract).
@pytest.mark.asyncio
async def test_agent_initiated_divergent_still_emits_event() -> None:
    cfg = _config_self_check_enabled()
    llm = _FakeLLMClient(_divergent_payload())
    registry = _AgentRegistryStub({"ezri": _AgentStub(id="ezri")})
    rt = _FakeRuntime(config=cfg, llm_client=llm, registry=registry)
    result = await verify_render_coherence(
        runtime=rt, agent_id="ezri", trigger="agent_initiated_stub",
        digital_state_summary="warm tone",
        backend_render_ref="sha256:abc",
    )
    assert result.coherent is False
    assert len(rt.emitted) == 1
    event_type, payload = rt.emitted[0]
    assert event_type is EventType.RENDER_DIVERGENCE_OBSERVED
    assert payload["trigger"] == "agent_initiated_stub"


# 12. Agent-initiated coherent calls do NOT emit (cost-discipline preserved
#     on the event-bus side, even though the agent's WM IS updated).
@pytest.mark.asyncio
async def test_agent_initiated_coherent_does_not_emit() -> None:
    cfg = _config_self_check_enabled()
    llm = _FakeLLMClient(_coherent_payload())
    registry = _AgentRegistryStub({"ezri": _AgentStub(id="ezri")})
    rt = _FakeRuntime(config=cfg, llm_client=llm, registry=registry)
    result = await verify_render_coherence(
        runtime=rt, agent_id="ezri", trigger="agent_initiated_stub",
        digital_state_summary="warm tone",
        backend_render_ref="sha256:abc",
    )
    assert result.coherent is True
    assert rt.emitted == []


# --- Surrogate for check_own_render unit tests ----------------------------

@dataclasses.dataclass
class _AgentSurrogate:
    """Minimal duck-typed surrogate exposing the attributes
    CognitiveAgent.check_own_render reads:
      * .id
      * ._runtime
      * ._working_memory
    BF-287: NOT MagicMock(spec=CognitiveAgent).
    """

    agent_id: str
    runtime: Any
    working_memory: Any

    # check_own_render reads ``self.id`` and ``self._runtime`` /
    # ``self._working_memory``; expose them as properties.
    @property
    def id(self) -> str:
        return self.agent_id

    @property
    def _runtime(self) -> Any:
        return self.runtime

    @property
    def _working_memory(self) -> Any:
        return self.working_memory
