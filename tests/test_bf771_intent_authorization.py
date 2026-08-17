"""BF-771: pre-intent authorization must not be skippable by entry point.

AD-698 put an authorization seam in ``IntentBus.broadcast()`` -- but BELOW the
targeted-dispatch branch, and nowhere else. So:

* setting ``target_agent_id`` skipped it (broadcast delegates to ``send``),
* calling ``send()`` directly skipped it (14 production callers),
* calling ``dispatch_async()`` directly skipped it.

RBAC or rate limiting registered through AD-698 could be bypassed by choosing
the entry point. Latent rather than live -- no hook is registered in either
source tree today (verified: one definition and zero call sites in OSS, zero
references across the commercial tree).

DENIAL SHAPE. A denial keeps each entry point's PRE-EXISTING refusal shape by
default -- ``send`` -> ``None``, ``broadcast`` -> ``[]``, ``dispatch_async``
-> no-op -- so none of the 35 call seams sees a type it did not already
handle (14 ``send``, 19 ``broadcast``, one ``dispatch_async``, one
``publish``). Raising by default was built and rejected:
``IntentAuthorizationDenied`` subclasses ``PermissionError``, and 14 of those
seams sit inside a broad ``except Exception`` that swallows it, so raising
relocated the defect instead of fixing it -- one seam renders a refusal as
"the lookup didn't finish in time".

Type compatibility is not the same as semantic safety: a consumer that records
success after a refused dispatch still needs the opt-in. Outstanding cases are
tracked as BF-790 (#1254).

``accept_notification`` is the consumer that must tell a denial apart from
"nobody answered": it reported ``{"dispatched": true, "responders": 0}`` and
acknowledged a notification whose handler never ran. It, and every other
consumer that needs the distinction, opts in with ``raise_on_denial=True``.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from probos.extensions import overlay
from probos.mesh.intent import IntentAuthorizationDenied, IntentBus
from probos.mesh.signal import SignalManager
from probos.types import IntentMessage, IntentResult


@pytest.fixture(autouse=True)
def _clean_hooks():
    """AD-698's registry is module-level; leaking a hook would poison the suite."""
    before = list(overlay._PRE_INTENT_AUTH_HOOKS)
    overlay._PRE_INTENT_AUTH_HOOKS.clear()
    yield
    overlay._PRE_INTENT_AUTH_HOOKS.clear()
    overlay._PRE_INTENT_AUTH_HOOKS.extend(before)


class _Handler:
    """Records whether the handler actually ran -- the thing a bypass proves."""

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, intent: IntentMessage) -> IntentResult:
        self.calls += 1
        return IntentResult(
            intent_id=intent.id, agent_id="agent-1", success=True, confidence=1.0,
        )


def _deny_all(_intent: Any) -> bool:
    return False


def _bus_with(handler: _Handler) -> IntentBus:
    bus = IntentBus(SignalManager())
    bus.subscribe("agent-1", handler)
    return bus


def _targeted() -> IntentMessage:
    return IntentMessage(intent="probe", params={}, target_agent_id="agent-1")


# ── the three entry points: the default refusal shape ──────────────────────

@pytest.mark.asyncio
async def test_broadcast_fanout_denial_returns_the_empty_list():
    handler = _Handler()
    bus = _bus_with(handler)
    overlay.register_pre_intent_authorization_hook("deny_all", _deny_all)

    assert await bus.broadcast(IntentMessage(intent="probe", params={})) == []

    assert handler.calls == 0


@pytest.mark.asyncio
async def test_broadcast_targeted_denial_returns_the_empty_list():
    """The original hole: the check sat BELOW the targeted branch."""
    handler = _Handler()
    bus = _bus_with(handler)
    overlay.register_pre_intent_authorization_hook("deny_all", _deny_all)

    assert await bus.broadcast(_targeted()) == []

    assert handler.calls == 0


@pytest.mark.asyncio
async def test_send_called_directly_denial_returns_none():
    """`send` is public with 14 production callers and had no check at all."""
    handler = _Handler()
    bus = _bus_with(handler)
    overlay.register_pre_intent_authorization_hook("deny_all", _deny_all)

    assert await bus.send(_targeted()) is None

    assert handler.calls == 0


@pytest.mark.asyncio
async def test_dispatch_async_denial_is_a_no_op():
    handler = _Handler()
    bus = _bus_with(handler)
    overlay.register_pre_intent_authorization_hook("deny_all", _deny_all)

    await bus.dispatch_async(_targeted())
    # Fire-and-forget: the allow path would have spawned a task by now.
    await asyncio.sleep(0.05)

    assert handler.calls == 0


# ── the same entry points, opted in to the raise ───────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "entry_point",
    ["broadcast_fanout", "broadcast_targeted", "send", "dispatch_async"],
)
async def test_every_entry_point_raises_when_opted_in(entry_point: str):
    """A consumer that must tell a refusal from silence can ask for one.

    ``broadcast_targeted`` is included because the opt-in has to survive the
    delegation to ``send`` -- that delegation is the path the original bypass
    hid behind.
    """
    handler = _Handler()
    bus = _bus_with(handler)
    overlay.register_pre_intent_authorization_hook("deny_all", _deny_all)

    with pytest.raises(IntentAuthorizationDenied) as caught:
        if entry_point == "broadcast_fanout":
            await bus.broadcast(
                IntentMessage(intent="probe", params={}), raise_on_denial=True,
            )
        elif entry_point == "broadcast_targeted":
            await bus.broadcast(_targeted(), raise_on_denial=True)
        elif entry_point == "send":
            await bus.send(_targeted(), raise_on_denial=True)
        else:
            await bus.dispatch_async(_targeted(), raise_on_denial=True)

    assert caught.value.intent_name == "probe"
    assert caught.value.reason == "deny_all"
    assert handler.calls == 0


# ── evaluated once, not twice ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_targeted_broadcast_evaluates_hooks_exactly_once():
    """`broadcast` delegates to `send`, which authorizes.

    Checking in both would run every hook twice per intent -- and a rate
    limiter is a hook, so double-counting would silently halve its budget.
    """
    calls: list[str] = []

    def _counting(_intent: Any) -> bool:
        calls.append("x")
        return True

    handler = _Handler()
    bus = _bus_with(handler)
    overlay.register_pre_intent_authorization_hook("counting", _counting)

    await bus.broadcast(_targeted())

    assert len(calls) == 1
    assert handler.calls == 1


@pytest.mark.asyncio
async def test_a_fanout_broadcast_evaluates_hooks_exactly_once():
    calls: list[str] = []

    def _counting(_intent: Any) -> bool:
        calls.append("x")
        return True

    handler = _Handler()
    bus = _bus_with(handler)
    overlay.register_pre_intent_authorization_hook("counting", _counting)

    await bus.broadcast(IntentMessage(intent="probe", params={}))

    assert len(calls) == 1


# ── the allow path is unchanged ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_hooks_registered_allows_every_entry_point():
    """The default registry is empty; none of this may cost anything."""
    handler = _Handler()
    bus = _bus_with(handler)

    results = await bus.broadcast(IntentMessage(intent="probe", params={}))
    assert len(results) == 1

    assert await bus.send(_targeted()) is not None
    await bus.dispatch_async(_targeted())
    # dispatch_async is fire-and-forget (create_task), so the handler has not
    # run when it returns.
    await asyncio.sleep(0.05)

    assert handler.calls == 3


@pytest.mark.asyncio
async def test_an_allowing_hook_does_not_block():
    handler = _Handler()
    bus = _bus_with(handler)
    overlay.register_pre_intent_authorization_hook("allow_all", lambda _i: True)

    assert await bus.send(_targeted()) is not None
    assert handler.calls == 1


# ── a broken evaluator must not authorize ──────────────────────────────────

@pytest.mark.asyncio
async def test_a_hook_that_raises_denies():
    """AD-698's evaluator already fails closed; pinned so it stays that way."""
    def _explode(_intent: Any) -> bool:
        raise RuntimeError("hook is broken")

    handler = _Handler()
    bus = _bus_with(handler)
    overlay.register_pre_intent_authorization_hook("exploding", _explode)

    assert await bus.send(_targeted()) is None
    with pytest.raises(IntentAuthorizationDenied):
        await bus.send(_targeted(), raise_on_denial=True)

    assert handler.calls == 0


@pytest.mark.asyncio
async def test_a_broken_evaluator_denies_rather_than_allowing(monkeypatch):
    """The evaluator itself failing is not a licence to proceed.

    The old code caught the import AND the call in one ``except`` that set
    ``allowed = True``, so an evaluator that crashed authorized everything.
    Those two failures mean opposite things and now have opposite outcomes.
    """
    import probos.extensions.overlay as ov

    def _boom(_intent: Any) -> Any:
        raise RuntimeError("evaluator itself is broken")

    monkeypatch.setattr(ov, "evaluate_pre_intent_authorization", _boom)

    handler = _Handler()
    bus = _bus_with(handler)

    # Fails closed on BOTH shapes. The default must deny too, not only the
    # opt-in path that can name the reason.
    assert await bus.send(_targeted()) is None
    with pytest.raises(IntentAuthorizationDenied) as caught:
        await bus.send(_targeted(), raise_on_denial=True)

    assert "evaluator" in caught.value.reason
    assert handler.calls == 0


@pytest.mark.asyncio
async def test_a_failed_overlay_import_denies(monkeypatch):
    """An ImportError here means BROKEN CORE, not "no overlay installed".

    An earlier version of this fix allowed on import failure, reasoning that a
    missing overlay should not cost the bus. That reasoning was wrong:
    ``probos.extensions.overlay`` is OSS core, and the absence of an external
    overlay is already represented by an EMPTY HOOK REGISTRY, which returns
    ``(True, "")`` through the normal path. So an ImportError means missing
    core code, version skew, or a failed module init -- and allowing then
    removes policy enforcement at exactly the moment the code is untrustworthy.
    """
    import builtins

    real_import = builtins.__import__

    def _no_overlay(name, *args, **kwargs):
        if name == "probos.extensions.overlay":
            raise ImportError("core module is broken")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_overlay)

    handler = _Handler()
    bus = _bus_with(handler)

    assert await bus.send(_targeted()) is None
    with pytest.raises(IntentAuthorizationDenied) as caught:
        await bus.send(_targeted(), raise_on_denial=True)

    assert "import" in caught.value.reason
    assert handler.calls == 0


@pytest.mark.asyncio
async def test_an_empty_registry_allows():
    """The real "no overlay" state: the module imports, and has no hooks."""
    handler = _Handler()
    bus = _bus_with(handler)
    assert overlay.registered_pre_intent_auth_hook_names() == ()

    assert await bus.send(_targeted()) is not None
    assert handler.calls == 1


# ── the denial carries what a caller needs ─────────────────────────────────

@pytest.mark.asyncio
async def test_the_denial_names_the_hook_and_the_entry_point():
    handler = _Handler()
    bus = _bus_with(handler)
    overlay.register_pre_intent_authorization_hook("rbac", _deny_all)

    with pytest.raises(IntentAuthorizationDenied) as caught:
        await bus.send(_targeted(), raise_on_denial=True)

    assert caught.value.reason == "rbac"
    assert caught.value.entry_point == "send"
    assert caught.value.intent_name == "probe"


@pytest.mark.asyncio
async def test_a_denial_is_distinguishable_only_when_a_caller_opts_in():
    """States the trade honestly rather than overclaiming it away.

    By DEFAULT a denial and "nobody answered" are the same value -- both `[]`.
    That indistinguishability is deliberate: it is what keeps all 34 call seams
    unchanged, 14 of which sit behind a broad ``except Exception`` and would
    have swallowed an exception anyway. The distinction is available, but a
    consumer has to ask for it.

    An earlier version of this test asserted a denial was ALWAYS
    distinguishable. That held for the raising design and is false for this
    one, so the assertion is inverted rather than deleted -- the trade stays
    visible to the next reader instead of being quietly dropped.
    """
    handler = _Handler()
    bus = _bus_with(handler)
    overlay.register_pre_intent_authorization_hook("deny_all", _deny_all)

    denied = await bus.broadcast(IntentMessage(intent="probe", params={}))

    # The opt-in is the whole difference.
    with pytest.raises(IntentAuthorizationDenied):
        await bus.broadcast(
            IntentMessage(intent="probe", params={}), raise_on_denial=True,
        )

    # Measured with NO hook registered, so this empty list is genuinely "no
    # responders" and not a second denial. A bus with no subscribers at all,
    # because an un-indexed subscriber is a FALLBACK subscriber and receives
    # every intent.
    overlay._PRE_INTENT_AUTH_HOOKS.clear()
    empty = IntentBus(SignalManager())
    unhandled = await empty.broadcast(IntentMessage(intent="nobody-handles-this"))

    assert denied == unhandled == []
    assert handler.calls == 0


# ── shutdown ordering is unchanged ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_closed_bus_still_short_circuits_before_authorization():
    """BF-296's gate must stay ahead of the check.

    A shutdown no-op is not a denial, and turning it into one would make every
    in-flight intent raise during shutdown.
    """
    handler = _Handler()
    bus = _bus_with(handler)
    bus.close_to_new_dispatches()
    overlay.register_pre_intent_authorization_hook("deny_all", _deny_all)

    # raise_on_denial=True gives these assertions teeth. If the BF-296 gate
    # ever moved BELOW authorization they would raise instead of returning the
    # shutdown no-op; without the opt-in both orderings produce the same value
    # and the test would prove nothing.
    assert await bus.broadcast(
        IntentMessage(intent="probe"), raise_on_denial=True,
    ) == []
    assert await bus.send(_targeted(), raise_on_denial=True) is None
    await bus.dispatch_async(_targeted(), raise_on_denial=True)

    assert handler.calls == 0


# ── the consumer the issue named ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_accept_notification_does_not_acknowledge_a_denied_dispatch():
    """The concrete harm: the Captain watched a pending action recede.

    ``accept_notification`` reported ``{"dispatched": true, "responders": 0}``
    and acknowledged the notification, because a denial and an unhandled intent
    were the same value. It must now report the denial AND leave the
    notification actionable.
    """
    from probos.routers.system import accept_notification

    acknowledged: list[str] = []

    class _Queue:
        def get(self, _nid: str) -> Any:
            return SimpleNamespace(
                suggested_action={"intent": "probe", "target_agent_id": "agent-1"},
            )

        def acknowledge(self, nid: str) -> None:
            acknowledged.append(nid)

    handler = _Handler()
    bus = _bus_with(handler)
    overlay.register_pre_intent_authorization_hook("rbac", _deny_all)
    runtime = SimpleNamespace(notification_queue=_Queue(), intent_bus=bus)

    out = await accept_notification("n-1", runtime=runtime)

    assert out["dispatched"] is False
    assert out["reason"] == "denied"
    assert acknowledged == [], "a refused action must stay actionable"
    assert handler.calls == 0


@pytest.mark.asyncio
async def test_accept_notification_still_acknowledges_an_allowed_dispatch():
    """The allow path is untouched -- the fix must not break normal accepts."""
    from probos.routers.system import accept_notification

    acknowledged: list[str] = []

    class _Queue:
        def get(self, _nid: str) -> Any:
            return SimpleNamespace(
                suggested_action={"intent": "probe", "target_agent_id": "agent-1"},
            )

        def acknowledge(self, nid: str) -> None:
            acknowledged.append(nid)

    handler = _Handler()
    bus = _bus_with(handler)
    runtime = SimpleNamespace(notification_queue=_Queue(), intent_bus=bus)

    out = await accept_notification("n-1", runtime=runtime)

    assert out["dispatched"] is True
    assert out["responders"] == 1
    assert acknowledged == ["n-1"]
    assert handler.calls == 1


# ── a denial is a policy outcome, not a server fault ───────────────────────

def test_a_denial_is_403_through_the_real_app():
    """Drives ``create_app``'s OWN handler, not a reimplementation of it.

    The previous version of this test built a second ``FastAPI`` app and
    registered a copy of the handler onto it, so it proved the shape of a
    handler the test had written itself and nothing whatever about production.
    This posts to a REAL opted-in route on the REAL app with a REAL bus and a
    denying hook, so the 403 comes from the registration in ``api.py``.

    503 would mean the route lost the distinction and reported a policy
    refusal as an unreachable mediator; 500 would mean the handler is not
    registered at all.
    """
    from unittest.mock import MagicMock

    from fastapi.testclient import TestClient

    from probos.api import create_app
    from probos.config import AuthConfig

    class _Registry:
        def __init__(self, agents: dict[str, Any]) -> None:
            self._agents = agents

        def get(self, aid: str) -> Any:
            return self._agents.get(aid)

    counselor = MagicMock()
    counselor.id = "counselor"
    counselor.agent_type = "counselor"

    runtime = MagicMock()
    runtime.registry = _Registry({"counselor": counselor})
    runtime.profile_store = None
    cfg = MagicMock()
    cfg.auth = AuthConfig()
    runtime.config = cfg
    # A REAL bus, so the denial comes from the real authorization path.
    runtime.intent_bus = IntentBus(SignalManager())
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

    overlay.register_pre_intent_authorization_hook("rbac", _deny_all)

    client = TestClient(create_app(runtime), raise_server_exceptions=False)
    resp = client.post(
        "/api/agent/counselor/appearance/mediate",
        json={"target_agent_id": "ezri", "captain_hint": "warmer please"},
    )

    assert resp.status_code == 403, resp.text
    assert resp.json()["error"] == "intent_denied"
    assert resp.json()["reason"] == "rbac"


def test_the_app_registers_the_denial_handler():
    """The handler must be registered app-wide, not per route.

    Per-route handling means a route added later reintroduces the 500 by
    omission, which is how this class of gap returns.
    """
    import inspect

    from probos import api

    source = inspect.getsource(api)
    assert "@app.exception_handler(IntentAuthorizationDenied)" in source
    assert "status_code=403" in source


# ── one denial must not abort a batch ──────────────────────────────────────

class _WardBus:
    """Denies the configured agents, records the rest -- the real bus shape."""

    def __init__(self, denied: set[str]) -> None:
        self.denied = denied
        self.dispatched: list[str] = []

    async def dispatch_async(
        self, intent: IntentMessage, *, raise_on_denial: bool = False,
    ) -> None:
        target = intent.target_agent_id or ""
        if target in self.denied:
            # Faithful to the real bus: a silent no-op unless the caller opted
            # in. So if production stops passing raise_on_denial, the denied
            # agent lands in `dispatched` and these tests fail -- which is
            # exactly the regression worth catching.
            if raise_on_denial:
                raise IntentAuthorizationDenied(
                    intent.intent, "rbac", "dispatch_async",
                )
            return
        self.dispatched.append(target)


def _ward_router(*, denied: set[str]):
    """A real ``WardRoomRouter`` with only the collaborators the path touches."""
    from probos.config import SystemConfig
    from probos.ward_room_router import WardRoomRouter

    bus = _WardBus(denied)
    router = WardRoomRouter.__new__(WardRoomRouter)
    router._intent_bus = bus
    router._config = SystemConfig()
    router._cooldowns = {}
    router._thread_rounds = {}
    router._round_participants = {}
    return router, bus


async def _dispatch(router, agent_ids: list[str]) -> None:
    """Drive the REAL ``_route_to_agents`` dispatch phase.

    Every agent is passed as a MENTIONED direct target, which bypasses the
    cooldown / round / dedup gates so the test exercises the dispatch loop
    rather than the eligibility filter.
    """
    channel = SimpleNamespace(name="ward", channel_type="channel")
    await router._route_to_agents(
        agent_ids, False, True,
        set(agent_ids), channel, "thread-1", "c1",
        "post", "title", "someone-else", {}, "",
        0.0, 0, set(),
    )


@pytest.mark.asyncio
async def test_ward_room_continues_after_a_denied_recipient():
    """A policy about ONE crew member is not an outage for the room.

    Exercises the REAL ``_route_to_agents``. An earlier version of this test
    reimplemented the loop and inspected source, so a mutation inserting
    ``break`` into the production catch passed all 29 tests -- the test named
    the property and did not measure it.
    """
    router, bus = _ward_router(denied={"agent-denied"})

    await _dispatch(router, ["agent-a", "agent-denied", "agent-b"])

    assert bus.dispatched == ["agent-a", "agent-b"]


@pytest.mark.asyncio
async def test_an_all_denied_ward_room_batch_does_not_advance_the_round():
    """Eligibility is not delivery.

    The round counter was keyed on ``eligible``. Once denials stopped
    propagating out of the loop, a batch where EVERY recipient was refused
    still looked like a round -- so the budget drained and the thread went
    quiet having delivered nothing.
    """
    router, bus = _ward_router(denied={"agent-a", "agent-b"})

    await _dispatch(router, ["agent-a", "agent-b"])

    assert bus.dispatched == []
    assert router._thread_rounds.get("thread-1") in (None, 0)


@pytest.mark.asyncio
async def test_a_partially_denied_batch_still_advances_the_round():
    """The other half: one real delivery IS a round."""
    router, bus = _ward_router(denied={"agent-a"})

    await _dispatch(router, ["agent-a", "agent-b"])

    assert bus.dispatched == ["agent-b"]
    assert router._thread_rounds.get("thread-1") == 1


# ── a denial is not an outage ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_denied_mediation_is_not_reported_as_an_unreachable_mediator():
    """403 "you may not", not 503 "the mediator is down".

    ``mediate_appearance_revision`` wraps ``intent_bus.send`` in a broad catch
    that renders 503 ``mediator_unreachable``. Without the re-raise above it,
    a policy denial sends the operator to diagnose an outage that is not
    happening -- and the Counselor looks broken rather than out of scope.
    """
    from probos.routers.agents import (
        MediateAppearanceRevision,
        mediate_appearance_revision,
    )

    async def _denied_send(msg, *, raise_on_denial: bool = False):
        # Faithful to the real bus: None unless the caller opted in, so this
        # test fails if the route stops asking for the distinction.
        if raise_on_denial:
            raise IntentAuthorizationDenied(msg.intent, "rbac", "send")
        return None

    runtime = SimpleNamespace(intent_bus=SimpleNamespace(send=_denied_send))
    req = MediateAppearanceRevision(
        target_agent_id="agent-b", captain_hint="taller",
    )

    with pytest.raises(IntentAuthorizationDenied) as caught:
        await mediate_appearance_revision("counselor", req, runtime=runtime)

    assert caught.value.reason == "rbac"


@pytest.mark.asyncio
async def test_an_unreachable_mediator_is_still_reported_as_503():
    """The teeth of the test above: the 503 branch must still exist.

    A re-raise that swallowed every failure into 403 would pass the previous
    test and lose the real outage signal.
    """
    from fastapi import HTTPException

    from probos.routers.agents import (
        MediateAppearanceRevision,
        mediate_appearance_revision,
    )

    async def _broken_send(msg, *, raise_on_denial: bool = False):
        raise RuntimeError("transport is down")

    runtime = SimpleNamespace(intent_bus=SimpleNamespace(send=_broken_send))
    req = MediateAppearanceRevision(
        target_agent_id="agent-b", captain_hint="taller",
    )

    with pytest.raises(HTTPException) as caught:
        await mediate_appearance_revision("counselor", req, runtime=runtime)

    assert caught.value.status_code == 503


# ── a hook must be identifiable ─────────────────────────────────────────────

def test_a_hook_registered_under_a_non_string_name_is_rejected():
    """An unnameable hook cannot be reported in a denial, or removed.

    ``reason`` is rendered to the operator and the name is the only handle
    for unregistering. A hook keyed on ``None`` or ``object()`` is a policy
    nobody can attribute, audit, or turn off.
    """
    def _hook(intent):
        return True

    for bad in (None, object(), 42, b"bytes", ""):
        with pytest.raises(ValueError):
            overlay.register_pre_intent_authorization_hook(bad, _hook)

    assert overlay._PRE_INTENT_AUTH_HOOKS == []

    overlay.register_pre_intent_authorization_hook("rbac", _hook)
    assert [n for n, _ in overlay._PRE_INTENT_AUTH_HOOKS] == ["rbac"]
