"""AD-698: tests for pre-intent authorization hook seam."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from probos.extensions import overlay as ext


@pytest.fixture(autouse=True)
def _reset():
    ext.reset_for_tests()
    yield
    ext.reset_for_tests()


def _intent(name: str = "test_intent") -> SimpleNamespace:
    return SimpleNamespace(intent=name, target_agent_id="", id="i1")


def test_no_hooks_allows_by_default() -> None:
    allowed, reason = ext.evaluate_pre_intent_authorization(_intent())
    assert allowed is True
    assert reason == ""


def test_hook_returning_true_allows() -> None:
    ext.register_pre_intent_authorization_hook("rbac", lambda i: True, provider="ovr")
    allowed, _ = ext.evaluate_pre_intent_authorization(_intent())
    assert allowed is True


def test_hook_returning_false_denies_with_name() -> None:
    ext.register_pre_intent_authorization_hook("rbac", lambda i: False, provider="ovr")
    allowed, reason = ext.evaluate_pre_intent_authorization(_intent())
    assert allowed is False
    assert reason == "rbac"


def test_hook_raising_exception_denies_with_typed_reason() -> None:
    def boom(_i):
        raise ValueError("nope")
    ext.register_pre_intent_authorization_hook("crash", boom, provider="ovr")
    allowed, reason = ext.evaluate_pre_intent_authorization(_intent())
    assert allowed is False
    assert reason == "crash:ValueError"


def test_multiple_hooks_all_must_allow() -> None:
    ext.register_pre_intent_authorization_hook("a", lambda i: True, provider="ovr")
    ext.register_pre_intent_authorization_hook("b", lambda i: False, provider="ovr")
    allowed, reason = ext.evaluate_pre_intent_authorization(_intent())
    assert allowed is False
    assert reason == "b"


def test_register_empty_name_raises() -> None:
    with pytest.raises(ValueError):
        ext.register_pre_intent_authorization_hook("", lambda i: True)


def test_registered_hook_names_snapshot() -> None:
    ext.register_pre_intent_authorization_hook("h1", lambda i: True)
    ext.register_pre_intent_authorization_hook("h2", lambda i: True)
    assert ext.registered_pre_intent_auth_hook_names() == ("h1", "h2")


@pytest.mark.asyncio
async def test_intent_bus_broadcast_skips_when_denied() -> None:
    """End-to-end smoke: a denying hook drops the broadcast."""
    from probos.mesh.intent import IntentBus
    from probos.mesh.signal import SignalManager
    from probos.types import IntentMessage

    received: list[str] = []

    async def handler(msg, agent_id):  # pragma: no cover — should not be called
        received.append(msg.intent)
        return None

    bus = IntentBus(SignalManager())
    bus.subscribe("a1", handler)
    ext.register_pre_intent_authorization_hook("deny", lambda i: False)

    msg = IntentMessage(intent="test_intent", params={})
    results = await bus.broadcast(msg, timeout=0.5)
    assert results == []
    assert received == []
