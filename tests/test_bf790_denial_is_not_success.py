"""BF-790 (#1254): a pre-intent denial must not be recorded as success.

BF-771 closed the producer-side authorization bypass and deliberately gave a
denial each entry point's PRE-EXISTING refusal shape (``send`` -> ``None``,
``broadcast`` -> ``[]``, ``dispatch_async`` -> no-op), with
``raise_on_denial=True`` as the opt-in for consumers that must tell a refusal
apart from silence.

Type-compatible is not the same as semantically safe. Six consumers took the
compatible default and then recorded success anyway -- most damagingly a
one-shot Captain watch order, which was counted executed and DEACTIVATED after
being refused, permanently consuming an order that never ran.

Every test here drives the REAL consumer with a REAL bus and a REAL denying
hook, EXCEPT ``TestADeniedFanOutIsNotRetried``, which is explicitly structural
and says so in its own docstring -- driving ``thread_fanout``'s handler needs a
thread store, a facilitator and a resolved agent.

SCOPE. This covers the watch path, the fan-out retry gate, gap remediation and
DM pacing. The two chat routes and the proactive observer are NOT here: review
found their downstream consumers do not yet accept a refusal (the HXI renders a
403 as "(No response)", one Ward Room path re-posts a denied ``direct_message``
as a ``ward_room_notification``, and the observer spends its emission budget
before dispatch). Opting those in without fixing the consumer would move the
lie rather than remove it.
"""

from __future__ import annotations

import asyncio
import ast
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.extensions import overlay
from probos.mesh.intent import IntentBus
from probos.mesh.pre_intent_auth import IntentAuthorizationDenied, IntentNoSubscriber
from probos.mesh.signal import SignalManager
from probos.runtime import ProbOSRuntime
from probos.types import IntentMessage
from probos.watch_rotation import CaptainOrder, StandingTask, WatchManager


@pytest.fixture(autouse=True)
def _clean_overlay():
    overlay.reset_for_tests()
    yield
    overlay.reset_for_tests()


def _deny_all(_intent) -> bool:
    return False


def _real_watch_bridge() -> tuple[Any, list[str]]:
    """The REAL `ProbOSRuntime._dispatch_watch_intent`, bound to a stub self.

    Not a reimplementation -- the production method is what carries the
    `raise_on_denial=True` this issue is about, so a hand-written bridge would
    prove nothing.
    """
    calls: list[str] = []

    def _counting(intent) -> bool:
        calls.append(intent.intent)
        return False

    overlay.register_pre_intent_authorization_hook("rbac", _counting)
    runtime = MagicMock()
    runtime.intent_bus = IntentBus(SignalManager())
    return ProbOSRuntime._dispatch_watch_intent.__get__(runtime), calls


# ── 1. The Captain's order survives a refusal ────────────────────


class TestADeniedWatchOrderIsNotConsumed:
    async def test_a_refused_one_shot_order_stays_active_and_uncounted(self):
        bridge, calls = _real_watch_bridge()
        wm = WatchManager(dispatch_fn=bridge)
        order = CaptainOrder(
            id="ord-1",
            target="science",
            target_type="department",
            intent_type="scan_sector",
            intent_params={"sector": "gamma"},
            one_shot=True,
        )
        wm._captain_orders.append(order)

        await wm._dispatch_due_orders()

        assert calls == ["scan_sector"], "the hook must actually have run"
        assert order.executed_count == 0, "a refused order was counted executed"
        assert order.active is True, (
            "a refused one-shot order was deactivated -- it is gone for good "
            "and never ran"
        )

    async def test_an_allowed_order_is_still_counted_and_consumed(self):
        overlay.register_pre_intent_authorization_hook("allow", lambda _i: True)
        runtime = MagicMock()
        bus = IntentBus(SignalManager())
        runtime.intent_bus = bus
        delivered: list[str] = []

        async def _handler(intent: IntentMessage):
            delivered.append(intent.intent)
            return None

        # A REAL subscriber. Without one, "executed" would be asserted for an
        # order that reached nobody -- pinning a second false-success case
        # inside a test about false success.
        bus.subscribe("scan_sector", _handler)
        bridge = ProbOSRuntime._dispatch_watch_intent.__get__(runtime)
        wm = WatchManager(dispatch_fn=bridge)
        order = CaptainOrder(
            id="ord-2",
            target="science",
            target_type="department",
            intent_type="scan_sector",
            one_shot=True,
        )
        wm._captain_orders.append(order)

        await wm._dispatch_due_orders()

        assert delivered == ["scan_sector"]
        assert order.executed_count == 1
        assert order.active is False

    async def test_a_refused_standing_task_stays_due(self):
        """`last_executed` gates `is_due`, so stamping it delays the retry."""
        bridge, _calls = _real_watch_bridge()
        wm = WatchManager(dispatch_fn=bridge)
        wm._duty_roster[wm._current_watch] = ["sci-1"]
        task = StandingTask(
            id="task-1",
            intent_type="sensor_sweep",
            interval_seconds=0.0,
        )
        wm._standing_tasks.append(task)

        await wm._dispatch_due_tasks()

        assert task.last_executed == 0.0, (
            "a refused standing task was stamped executed and will now wait a "
            "full interval before retrying"
        )
        assert task.is_due()

    async def test_a_genuine_dispatch_failure_is_still_distinct(self):
        """The denial branch must not swallow ordinary failures."""

        async def _boom(_intent_type, _params):
            raise RuntimeError("bus exploded")

        wm = WatchManager(dispatch_fn=_boom)
        order = CaptainOrder(
            id="ord-3", target="science", target_type="department",
            intent_type="scan_sector", one_shot=True,
        )
        wm._captain_orders.append(order)

        await wm._dispatch_due_orders()

        assert order.executed_count == 0
        assert order.active is True


# ── 1a. The bridge must actually reach the bus (BF-790a) ─────────


class TestTheWatchBridgeIsNotDead:
    """`_dispatch_watch_intent` imported `probos.intent`, which does not exist.

    Every order and every standing task therefore raised ModuleNotFoundError,
    was swallowed by WatchManager's `except Exception`, and logged as
    "captain-order failed". Nothing the Captain ordered through the watch
    system had ever been delivered.
    """

    def test_there_is_no_probos_intent_module(self):
        """The enumeration behind the claim, kept executable."""
        import probos

        root = Path(probos.__file__).parent
        assert not list(root.glob("intent*.py")), (
            "a top-level probos.intent module now exists -- re-check which "
            "IntentMessage the watch bridge should import"
        )

    async def test_the_bridge_reaches_the_bus_instead_of_raising(self):
        seen: list[str] = []

        overlay.register_pre_intent_authorization_hook(
            "spy", lambda i: (seen.append(i.intent), True)[1]
        )
        runtime = MagicMock()
        runtime.intent_bus = IntentBus(SignalManager())
        bridge = ProbOSRuntime._dispatch_watch_intent.__get__(runtime)

        # BF-814: this bus has no subscribers, so the bridge now refuses AFTER
        # publishing. The property this test owns -- that it reaches the bus --
        # is unchanged and still asserted below; only the return path differs.
        # The refusal is deliberately ordered after publish precisely so this
        # guard keeps working.
        with pytest.raises(IntentNoSubscriber):
            await bridge("scan_sector", {"sector": "gamma"})

        assert seen == ["scan_sector"], (
            "the watch bridge did not reach the bus -- it is raising before "
            "publish, which is how the whole path went silent"
        )

    async def test_order_params_become_intent_params_not_envelope_kwargs(self):
        """A real order's params are payload keys, not IntentMessage fields.

        Splatting them as ``**params`` raised TypeError for every realistic
        order, so fixing only the import would have left the path just as dead
        for a different reason.
        """
        seen: list[IntentMessage] = []

        overlay.register_pre_intent_authorization_hook(
            "spy", lambda i: (seen.append(i), True)[1]
        )
        runtime = MagicMock()
        runtime.intent_bus = IntentBus(SignalManager())
        bridge = ProbOSRuntime._dispatch_watch_intent.__get__(runtime)

        # BF-814: no subscribers on this bus, so the bridge refuses after
        # publishing. The params assertion below is untouched.
        with pytest.raises(IntentNoSubscriber):
            await bridge("remediate", {"agent_id": "a1", "gap_id": "g7"})

        assert seen, "the bridge raised before reaching the bus"
        assert seen[0].params == {"agent_id": "a1", "gap_id": "g7"}

    async def test_a_captain_order_is_delivered_end_to_end(self):
        """WatchManager -> real bridge -> real bus -> a real subscriber."""
        delivered: list[str] = []
        bus = IntentBus(SignalManager())

        async def _handler(intent: IntentMessage):
            delivered.append(intent.intent)
            return None

        bus.subscribe("scan_sector", _handler)
        runtime = MagicMock()
        runtime.intent_bus = bus
        wm = WatchManager(
            dispatch_fn=ProbOSRuntime._dispatch_watch_intent.__get__(runtime)
        )
        wm._captain_orders.append(
            CaptainOrder(
                id="ord-live", target="science", target_type="department",
                intent_type="scan_sector", one_shot=True,
            )
        )

        await wm._dispatch_due_orders()

        assert delivered == ["scan_sector"], (
            "a Captain's order never reached a subscriber"
        )


# ── 2. The fan-out must not re-submit a refused intent ───────────


class TestADeniedFanOutIsNotRetried:
    """Structural guard on the retry gate.

    Stated plainly: this does NOT drive `thread_fanout`'s handler end to end --
    that path needs a thread store, a facilitator and a resolved agent. It
    pins the two things that make the double-charge possible, by AST so a
    comment cannot satisfy them, and the bus-level evaluate-once property is
    covered by the real-bus test below it.
    """

    @staticmethod
    def _dispatch_intent_fn() -> ast.AsyncFunctionDef:
        from probos.routers import thread_fanout

        tree = ast.parse(Path(thread_fanout.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.AsyncFunctionDef)
                and node.name == "_dispatch_intent"
            ):
                return node
        raise AssertionError("_dispatch_intent not found in thread_fanout")

    def test_the_send_opts_into_the_raising_denial_shape(self):
        fn = self._dispatch_intent_fn()
        sends = [
            n
            for n in ast.walk(fn)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "send"
        ]
        assert sends, "no send() call found in _dispatch_intent"
        for call in sends:
            assert any(
                kw.arg == "raise_on_denial"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value is True
                for kw in call.keywords
            ), "a denial is invisible here without raise_on_denial=True"

    def test_the_denial_branch_reports_denied_true(self):
        fn = self._dispatch_intent_fn()
        denial_handlers = [
            h
            for h in ast.walk(fn)
            if isinstance(h, ast.ExceptHandler)
            and h.type is not None
            and "IntentAuthorizationDenied" in ast.unparse(h.type)
        ]
        assert denial_handlers, "no IntentAuthorizationDenied handler"
        for handler in denial_handlers:
            returns = [
                n for n in ast.walk(handler) if isinstance(n, ast.Return)
            ]
            assert returns, "denial handler does not return"
            for ret in returns:
                assert isinstance(ret.value, ast.Tuple)
                last = ret.value.elts[-1]
                assert isinstance(last, ast.Constant) and last.value is True, (
                    "the denial branch must report denied=True or the retry "
                    "below re-submits the refused intent"
                )

    def test_the_retry_is_gated_on_the_denial_flag(self):
        from probos.routers import thread_fanout

        tree = ast.parse(Path(thread_fanout.__file__).read_text(encoding="utf-8"))
        gated = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.If)
            and "_denied" in ast.unparse(n.test)
            and "_is_addressed" in ast.unparse(n.test)
        ]
        assert gated, (
            "the BF-636 addressed-retry is not gated on the denial flag, so a "
            "refused intent is submitted twice and a stateful hook is charged "
            "twice for one turn"
        )

    async def test_the_bus_itself_evaluates_a_denial_exactly_once(self):
        calls: list[str] = []

        def _counting(intent) -> bool:
            calls.append(intent.target_agent_id or intent.intent)
            return False

        overlay.register_pre_intent_authorization_hook("rbac", _counting)
        bus = IntentBus(SignalManager())
        intent = IntentMessage(
            intent="direct_message", params={}, target_agent_id="bones1"
        )

        with pytest.raises(IntentAuthorizationDenied):
            await bus.send(intent, raise_on_denial=True)

        assert len(calls) == 1


# ── 3. (deferred) chat routes ────────────────────────────────────
#
# `/api/chat` and `/api/agent/{id}/chat` are NOT opted in here. Review proved
# the 403 is reachable through `create_app`, but also that no UI caller accepts
# it: two render the denial as an agent-authored "(No response)", and
# `WardRoomThreadDetail` throws on 403 and its catch re-posts the Captain's
# message through a DIFFERENT intent, which an intent-scoped policy may permit.
# Turning the refusal into a reroute is worse than the empty reply it replaces.
# Tracked separately; see the issues filed from this review.

