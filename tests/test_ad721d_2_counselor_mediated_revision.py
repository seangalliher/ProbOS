"""AD-721d-2: Counselor-mediated avatar revision — boundary tests."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from probos.config import AuthConfig
from probos.events import EventType


# ── Fakes ───────────────────────────────────────────────────────


class _FakeLLMResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeLLMClient:
    def __init__(self, refined_text: str = "Soften the formal lines, keep the warmth.") -> None:
        self._text = refined_text
        self.calls: list[Any] = []

    async def complete(self, request: Any, *, priority: Any = None) -> _FakeLLMResponse:
        self.calls.append(request)
        return _FakeLLMResponse(self._text)


class _FakeAppearance:
    def __init__(self, dsl: dict | None) -> None:
        self.dsl = dsl


class _FakeTargetAgent:
    def __init__(
        self,
        *,
        agent_id: str = "ezri",
        dsl: dict | None = None,
        proposable: bool = True,
        propose_raises: bool = False,
        proposed_dsl: dict | None = None,
    ) -> None:
        self.id = agent_id
        self.appearance = _FakeAppearance(dsl)
        self._proposable = proposable
        self._raises = propose_raises
        self._proposed = proposed_dsl or {"warmth": 0.8}
        self.propose_calls: list[str] = []
        if not proposable:
            return

    async def propose_appearance(self, *, captain_note: str) -> Any:
        self.propose_calls.append(captain_note)
        if self._raises:
            raise RuntimeError("LLM proposal failed")
        # Return an object exposing model_dump (like real AvatarDSL).
        obj = MagicMock()
        obj.model_dump.return_value = self._proposed
        return obj


class _FakeRegistry:
    def __init__(self, agents: dict[str, Any]) -> None:
        self._agents = agents

    def get(self, aid: str) -> Any:
        return self._agents.get(aid)


def _make_runtime(
    *,
    target_dsl: dict | None = {"warmth": 0.3},
    refined_text: str = "Soften the formal lines, keep the warmth.",
    target_proposable: bool = True,
    target_propose_raises: bool = False,
) -> MagicMock:
    target = _FakeTargetAgent(
        agent_id="ezri",
        dsl=target_dsl,
        proposable=target_proposable,
        propose_raises=target_propose_raises,
    )
    counselor = MagicMock()
    counselor.id = "counselor"
    counselor.agent_type = "counselor"

    runtime = MagicMock()
    runtime.registry = _FakeRegistry({"ezri": target, "counselor": counselor})
    runtime.llm_client = _FakeLLMClient(refined_text=refined_text)
    runtime.emit_event = MagicMock()
    runtime._emit_event_fn = runtime.emit_event
    runtime.profile_store = None

    cfg = MagicMock()
    cfg.auth = AuthConfig()
    runtime.config = cfg
    runtime._target = target  # expose for assertions
    return runtime


@pytest.mark.asyncio
async def test_mediate_happy_path() -> None:
    runtime = _make_runtime()
    from probos.cognitive.counselor import CounselorAgent
    # Directly invoke the handler (no full agent boot).
    handler = CounselorAgent._mediate_appearance_revision.__get__(MagicMock(_runtime=runtime, _emit_event_fn=runtime.emit_event))
    result = await handler(
        target_agent_id="ezri",
        captain_hint="Echo's avatar feels too formal, work with her on something warmer",
    )
    assert result["ok"] is True
    assert result["refined_hint"] == "Soften the formal lines, keep the warmth."
    assert result["proposed_dsl"] == {"warmth": 0.8}
    assert runtime._target.propose_calls == ["Soften the formal lines, keep the warmth."]
    runtime.emit_event.assert_called_once()
    et, payload = runtime.emit_event.call_args[0]
    assert et == EventType.APPEARANCE_REVISION_MEDIATED
    assert payload["target_agent_id"] == "ezri"


@pytest.mark.asyncio
async def test_mediate_empty_hint_returns_error() -> None:
    runtime = _make_runtime()
    from probos.cognitive.counselor import CounselorAgent
    handler = CounselorAgent._mediate_appearance_revision.__get__(MagicMock(_runtime=runtime, _emit_event_fn=runtime.emit_event))
    result = await handler(target_agent_id="ezri", captain_hint="")
    assert result == {"ok": False, "reason": "invalid_hint_length"}


@pytest.mark.asyncio
async def test_mediate_hint_over_280_returns_error() -> None:
    runtime = _make_runtime()
    from probos.cognitive.counselor import CounselorAgent
    handler = CounselorAgent._mediate_appearance_revision.__get__(MagicMock(_runtime=runtime, _emit_event_fn=runtime.emit_event))
    result = await handler(target_agent_id="ezri", captain_hint="x" * 281)
    assert result == {"ok": False, "reason": "invalid_hint_length"}


@pytest.mark.asyncio
async def test_mediate_target_unknown_returns_error() -> None:
    runtime = _make_runtime()
    from probos.cognitive.counselor import CounselorAgent
    handler = CounselorAgent._mediate_appearance_revision.__get__(MagicMock(_runtime=runtime, _emit_event_fn=runtime.emit_event))
    result = await handler(target_agent_id="unknown", captain_hint="anything")
    assert result == {"ok": False, "reason": "target_agent_unknown"}


@pytest.mark.asyncio
async def test_mediate_dsl_unavailable_returns_error() -> None:
    runtime = _make_runtime(target_dsl=None)
    from probos.cognitive.counselor import CounselorAgent
    handler = CounselorAgent._mediate_appearance_revision.__get__(MagicMock(_runtime=runtime, _emit_event_fn=runtime.emit_event))
    result = await handler(target_agent_id="ezri", captain_hint="anything")
    assert result == {"ok": False, "reason": "target_dsl_unavailable"}


@pytest.mark.asyncio
async def test_mediate_refinement_empty_returns_error() -> None:
    runtime = _make_runtime(refined_text="")
    from probos.cognitive.counselor import CounselorAgent
    handler = CounselorAgent._mediate_appearance_revision.__get__(MagicMock(_runtime=runtime, _emit_event_fn=runtime.emit_event))
    result = await handler(target_agent_id="ezri", captain_hint="anything")
    assert result == {"ok": False, "reason": "refinement_empty"}


@pytest.mark.asyncio
async def test_mediate_propose_failure_returns_error() -> None:
    runtime = _make_runtime(target_propose_raises=True)
    from probos.cognitive.counselor import CounselorAgent
    handler = CounselorAgent._mediate_appearance_revision.__get__(MagicMock(_runtime=runtime, _emit_event_fn=runtime.emit_event))
    result = await handler(target_agent_id="ezri", captain_hint="anything")
    assert result == {"ok": False, "reason": "propose_failed"}


@pytest.mark.asyncio
async def test_api_endpoint_uses_intent_bus_send_with_target_agent_id() -> None:
    """Pass-1 fix: endpoint MUST use intent_bus.send(IntentMessage(target_agent_id=...)),
    NOT broadcast. Verify via a stub bus that records the call shape."""
    from probos.api import create_app
    from probos.types import IntentMessage, IntentResult

    captured: list[IntentMessage] = []

    async def _send(msg: IntentMessage) -> IntentResult:
        captured.append(msg)
        return IntentResult(
            intent_id=msg.id,
            agent_id="counselor",
            success=True,
            result={"ok": True, "refined_hint": "x", "proposal_iteration": 1, "proposed_dsl": {}},
        )

    runtime = _make_runtime()
    runtime.intent_bus = MagicMock()
    runtime.intent_bus.send = _send
    # Fill out minimum runtime surface for create_app.
    runtime.callsign_registry = MagicMock()
    runtime.callsign_registry.get_callsign.return_value = "Counselor"
    runtime.callsign_registry.resolve.return_value = None
    runtime.callsign_registry.all_callsigns.return_value = {}
    runtime.hebbian_router = MagicMock()
    runtime.hebbian_router.all_weights_typed.return_value = {}
    runtime._start_time = 0.0
    runtime.episodic_memory = None
    runtime.work_item_store = None
    runtime.proactive_loop = None
    runtime.ontology = None
    runtime.add_event_listener = MagicMock()

    client = TestClient(create_app(runtime))
    resp = client.post(
        "/api/agent/counselor/appearance/mediate",
        json={"target_agent_id": "ezri", "captain_hint": "warmer please"},
    )
    assert resp.status_code == 200, resp.text
    assert len(captured) == 1
    sent = captured[0]
    assert sent.intent == "mediate_appearance_revision"
    assert sent.target_agent_id == "counselor"
    assert sent.params["target_agent_id"] == "ezri"
    assert sent.params["captain_hint"] == "warmer please"
