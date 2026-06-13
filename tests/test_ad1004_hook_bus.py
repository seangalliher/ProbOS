"""AD-1004: lifecycle-hook bus tests.

The substrate for the per-agent capability gate (epic #944) + Capability Packs
(AD-1003). Covers registration, gate-event aggregation (deny > ask > allow),
observational events, async + sync handlers, honest-degrade on a raising
handler, and the default-OFF config flag.
"""
from __future__ import annotations

import pytest

from probos.config import HooksConfig, SystemConfig
from probos.hooks import (
    AggregateDecision,
    HookBus,
    HookDecision,
    HookEvent,
    HookResult,
)


def _allow() -> HookResult:
    return HookResult(HookDecision.ALLOW)


def _deny(reason="nope", hid="denier") -> HookResult:
    return HookResult(HookDecision.DENY, reason=reason, handler_id=hid)


def _ask(reason="check", hid="asker") -> HookResult:
    return HookResult(HookDecision.ASK, reason=reason, handler_id=hid)


# ---------------------------------------------------------------------------
# config — default OFF
# ---------------------------------------------------------------------------


def test_hooks_config_default_off():
    assert HooksConfig().enabled is False
    assert SystemConfig().hooks.enabled is False


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------


def test_register_and_count():
    bus = HookBus()
    assert bus.handler_count(HookEvent.PRE_DISPATCH) == 0
    hid = bus.register(HookEvent.PRE_DISPATCH, lambda ctx: None, handler_id="h1")
    assert hid == "h1"
    assert bus.handler_count(HookEvent.PRE_DISPATCH) == 1


def test_register_derives_id_from_name():
    bus = HookBus()

    def my_hook(ctx):
        return None

    hid = bus.register(HookEvent.PRE_TOOL_USE, my_hook)
    assert hid == "my_hook"


def test_unregister():
    bus = HookBus()
    bus.register(HookEvent.PRE_DISPATCH, lambda ctx: None, handler_id="h1")
    bus.register(HookEvent.PRE_DISPATCH, lambda ctx: None, handler_id="h2")
    assert bus.unregister(HookEvent.PRE_DISPATCH, "h1") is True
    assert bus.handler_count(HookEvent.PRE_DISPATCH) == 1
    assert bus.unregister(HookEvent.PRE_DISPATCH, "missing") is False


# ---------------------------------------------------------------------------
# empty / unwired bus is inert
# ---------------------------------------------------------------------------


async def test_fire_no_handlers_allows():
    bus = HookBus()
    res = await bus.fire(HookEvent.PRE_DISPATCH, {"intent": "run_python"})
    assert isinstance(res, AggregateDecision)
    assert res.allowed is True
    assert res.decision == HookDecision.ALLOW
    assert res.reasons == []


# ---------------------------------------------------------------------------
# gate aggregation — deny > ask > allow
# ---------------------------------------------------------------------------


async def test_single_allow():
    bus = HookBus()
    bus.register(HookEvent.PRE_DISPATCH, lambda ctx: _allow())
    res = await bus.fire(HookEvent.PRE_DISPATCH)
    assert res.allowed


async def test_deny_wins_over_allow_and_ask():
    bus = HookBus()
    bus.register(HookEvent.PRE_DISPATCH, lambda ctx: _allow(), handler_id="a")
    bus.register(HookEvent.PRE_DISPATCH, lambda ctx: _ask(), handler_id="b")
    bus.register(HookEvent.PRE_DISPATCH, lambda ctx: _deny("blocked", "grant_gate"), handler_id="c")
    res = await bus.fire(HookEvent.PRE_DISPATCH)
    assert res.denied
    assert "blocked" in res.reasons
    assert "grant_gate" in res.handler_ids


async def test_ask_wins_over_allow():
    bus = HookBus()
    bus.register(HookEvent.PRE_TOOL_USE, lambda ctx: _allow())
    bus.register(HookEvent.PRE_TOOL_USE, lambda ctx: _ask("confirm", "consensus"))
    res = await bus.fire(HookEvent.PRE_TOOL_USE)
    assert res.asked
    assert res.decision == HookDecision.ASK
    assert "confirm" in res.reasons


async def test_abstain_none_does_not_block():
    bus = HookBus()
    bus.register(HookEvent.PRE_DISPATCH, lambda ctx: None)   # abstains
    bus.register(HookEvent.PRE_DISPATCH, lambda ctx: _allow())
    res = await bus.fire(HookEvent.PRE_DISPATCH)
    assert res.allowed


# ---------------------------------------------------------------------------
# observational events ignore verdicts
# ---------------------------------------------------------------------------


async def test_observational_event_ignores_deny():
    bus = HookBus()
    seen = []
    bus.register(HookEvent.POST_DISPATCH, lambda ctx: seen.append(ctx) or _deny())
    res = await bus.fire(HookEvent.POST_DISPATCH, {"intent": "x"})
    # Handler ran (side effect recorded) but its deny is ignored on a non-gate event.
    assert seen == [{"intent": "x"}]
    assert res.allowed


# ---------------------------------------------------------------------------
# async + sync handlers
# ---------------------------------------------------------------------------


async def test_async_handler():
    bus = HookBus()

    async def deny_async(ctx):
        return _deny("async-deny", "ah")

    bus.register(HookEvent.PRE_DISPATCH, deny_async)
    res = await bus.fire(HookEvent.PRE_DISPATCH)
    assert res.denied
    assert "async-deny" in res.reasons


async def test_mixed_sync_async_most_restrictive():
    bus = HookBus()

    async def ask_async(ctx):
        return _ask()

    bus.register(HookEvent.PRE_DISPATCH, lambda ctx: _allow())
    bus.register(HookEvent.PRE_DISPATCH, ask_async)
    res = await bus.fire(HookEvent.PRE_DISPATCH)
    assert res.asked


# ---------------------------------------------------------------------------
# honest-degrade — a raising handler contributes no verdict
# ---------------------------------------------------------------------------


async def test_raising_handler_skipped_others_decide():
    bus = HookBus()

    def boom(ctx):
        raise RuntimeError("handler bug")

    bus.register(HookEvent.PRE_DISPATCH, boom, handler_id="broken")
    bus.register(HookEvent.PRE_DISPATCH, lambda ctx: _deny("real", "real_gate"))
    res = await bus.fire(HookEvent.PRE_DISPATCH)
    # The broken handler is skipped; the real gate still denies.
    assert res.denied
    assert "real" in res.reasons


async def test_only_raising_handler_defaults_allow():
    bus = HookBus()

    def boom(ctx):
        raise RuntimeError("handler bug")

    bus.register(HookEvent.PRE_DISPATCH, boom)
    res = await bus.fire(HookEvent.PRE_DISPATCH)
    # No verdict contributed -> bus does not block (consensus is the real gate).
    assert res.allowed


# ---------------------------------------------------------------------------
# context passthrough + ordering
# ---------------------------------------------------------------------------


async def test_context_passed_and_order_preserved():
    bus = HookBus()
    order: list[str] = []
    bus.register(HookEvent.PRE_DISPATCH, lambda ctx: order.append(f"1:{ctx['intent']}") or _allow())
    bus.register(HookEvent.PRE_DISPATCH, lambda ctx: order.append("2") or _allow())
    await bus.fire(HookEvent.PRE_DISPATCH, {"intent": "run_python"})
    assert order == ["1:run_python", "2"]
