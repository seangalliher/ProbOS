"""AD-1012: lifecycle-hook bus PreDispatch wiring (#949 / #944).

The per-agent capability gate becomes a pluggable ``PreDispatch`` hook so
Capability-Pack hooks (#948) and a future consensus handler can gate at the same
lifecycle point. These tests cover the pure handler adapter and its integration
with a REAL :class:`HookBus` + REAL :class:`IntentGrantStore` (BF-287: no
MagicMock at the substrate boundary).
"""

from __future__ import annotations

from probos.cognitive.intent_grants import IntentGrantStore
from probos.hooks.bus import HookBus, HookDecision, HookEvent
from probos.hooks.handlers import make_capability_gate_handler


class _FakeGrants:
    """Explicit ``resolve_sync`` fake for pure-handler tests (BF-287: a named
    fake, not MagicMock, so a renamed method fails loudly rather than
    auto-passing)."""

    def __init__(self, resolution: str) -> None:
        self._resolution = resolution
        self.calls: list[tuple[str, str]] = []

    def resolve_sync(self, agent_id: str, intent_name: str) -> str:
        self.calls.append((agent_id, intent_name))
        return self._resolution


# ---------------------------------------------------------------------------
# pure handler unit tests
# ---------------------------------------------------------------------------


def test_handler_restricted_denies():
    handler = make_capability_gate_handler(_FakeGrants("restricted"))
    res = handler({"agent_id": "ezri", "intent_name": "web_search"})
    assert res is not None
    assert res.decision is HookDecision.DENY
    assert "web_search" in res.reason
    assert res.handler_id == "capability_gate"


def test_handler_granted_allows():
    handler = make_capability_gate_handler(_FakeGrants("granted"))
    res = handler({"agent_id": "ezri", "intent_name": "web_search"})
    assert res is not None
    assert res.decision is HookDecision.ALLOW


def test_handler_no_opinion_allows():
    handler = make_capability_gate_handler(_FakeGrants("no_opinion"))
    res = handler({"agent_id": "ezri", "intent_name": "web_search"})
    assert res is not None
    assert res.decision is HookDecision.ALLOW


def test_handler_accepts_intent_alias():
    grants = _FakeGrants("restricted")
    handler = make_capability_gate_handler(grants)
    res = handler({"agent_id": "ezri", "intent": "read_page"})
    assert res is not None
    assert res.decision is HookDecision.DENY
    assert grants.calls == [("ezri", "read_page")]


def test_handler_missing_agent_abstains():
    handler = make_capability_gate_handler(_FakeGrants("restricted"))
    assert handler({"intent_name": "web_search"}) is None


def test_handler_missing_intent_abstains():
    handler = make_capability_gate_handler(_FakeGrants("restricted"))
    assert handler({"agent_id": "ezri"}) is None


# ---------------------------------------------------------------------------
# integration: real HookBus + real IntentGrantStore (cache-only, db_path="")
# ---------------------------------------------------------------------------


async def test_bus_denies_restricted_capability():
    store = IntentGrantStore(db_path="")
    await store.start()
    await store.issue_grant("ezri", "web_search", is_restriction=True)
    bus = HookBus()
    bus.register(
        HookEvent.PRE_DISPATCH,
        make_capability_gate_handler(store),
        handler_id="capability_gate",
    )
    decision = await bus.fire(
        HookEvent.PRE_DISPATCH,
        {"agent_id": "ezri", "intent_name": "web_search"},
    )
    assert decision.denied
    assert any("web_search" in r for r in decision.reasons)


async def test_bus_allows_ungranted_capability():
    # No grant/restriction issued -> no_opinion -> ALLOW (role/ship default).
    store = IntentGrantStore(db_path="")
    await store.start()
    bus = HookBus()
    bus.register(
        HookEvent.PRE_DISPATCH,
        make_capability_gate_handler(store),
        handler_id="capability_gate",
    )
    decision = await bus.fire(
        HookEvent.PRE_DISPATCH,
        {"agent_id": "worf", "intent_name": "read_page"},
    )
    assert decision.allowed


async def test_bus_allows_explicitly_granted_capability():
    store = IntentGrantStore(db_path="")
    await store.start()
    await store.issue_grant("data", "web_search", is_restriction=False)
    bus = HookBus()
    bus.register(
        HookEvent.PRE_DISPATCH,
        make_capability_gate_handler(store),
        handler_id="capability_gate",
    )
    decision = await bus.fire(
        HookEvent.PRE_DISPATCH,
        {"agent_id": "data", "intent_name": "web_search"},
    )
    assert decision.allowed


async def test_restriction_is_agent_scoped():
    # A restriction on one agent must not gate a different agent.
    store = IntentGrantStore(db_path="")
    await store.start()
    await store.issue_grant("ezri", "web_search", is_restriction=True)
    bus = HookBus()
    bus.register(
        HookEvent.PRE_DISPATCH,
        make_capability_gate_handler(store),
        handler_id="capability_gate",
    )
    denied = await bus.fire(
        HookEvent.PRE_DISPATCH, {"agent_id": "ezri", "intent_name": "web_search"}
    )
    allowed = await bus.fire(
        HookEvent.PRE_DISPATCH, {"agent_id": "worf", "intent_name": "web_search"}
    )
    assert denied.denied
    assert allowed.allowed
