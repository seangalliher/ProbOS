"""BF-810 (#1274): a consumer must not claim work nobody took.

Follow-on to BF-815 (#1279), which gave ``dispatch_async`` a receipt. With a
trustworthy signal available, the consumers that counted "the call did not
raise" as delivery are corrected.

WHERE THE TESTS LIVE. Behavioural coverage sits beside the emitters it
exercises: ``test_ad654d_internal_emitters.py`` (delegation tags and the four
notification-only warn paths), ``test_ad839_work_item_dispatch.py`` (the
router's bool) and ``test_ad875_quartermaster.py`` (the counter). This file
holds only what has no natural home there.

BF-811 (#1275) is deliberately NOT addressed. Failing closed on a receipt-less
delegate was tried and reverted: this arm INVOKES the delegate before it can
inspect any receipt, so under a deny-all policy the side effect still happened
-- measured ``policy_calls=0, delegate_deliveries=1`` -- and only the
accounting refused. A check after invocation cannot prove authorization
retroactively. That issue needs the delegate authorized BEFORE it is called.
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.activation.dispatcher import Dispatcher
from probos.activation.task_event import AgentTarget, TaskEvent
from probos.types import DispatchAdmission, Priority


def _agent(agent_id: str = "a1"):
    a = MagicMock()
    a.id = agent_id
    a.agent_type = "scout"
    a.capabilities = []
    return a


def _registry(*agents):
    m = {a.id: a for a in agents}
    reg = MagicMock()
    reg.get = MagicMock(side_effect=lambda aid: m.get(aid))
    reg.all = MagicMock(return_value=list(agents))
    reg.get_by_capability = MagicMock(return_value=[])
    return reg


def _event(agent_id: str = "a1") -> TaskEvent:
    return TaskEvent(
        source_type="test", source_id="s1", event_type="e",
        priority=Priority.NORMAL, target=AgentTarget(agent_id=agent_id),
        payload={},
    )


class TestTheDispatcherReadsTheReceipt:
    async def test_a_delegate_reporting_a_drop_is_rejected(self):
        d = Dispatcher(
            registry=_registry(_agent()), ontology=None,
            get_queue=lambda _aid: None,
            dispatch_async_fn=AsyncMock(
                return_value=DispatchAdmission(False, reason="no_handler")
            ),
        )

        result = await d.dispatch(_event())

        assert result.accepted == 0
        assert result.rejected == 1
        assert result.agent_ids == []

    async def test_a_delegate_reporting_an_admission_is_accepted(self):
        d = Dispatcher(
            registry=_registry(_agent()), ontology=None,
            get_queue=lambda _aid: None,
            dispatch_async_fn=AsyncMock(
                return_value=DispatchAdmission(True, route="queue")
            ),
        )

        result = await d.dispatch(_event())

        assert result.accepted == 1
        assert result.agent_ids == ["a1"]


class TestTheWardRoomRoundFollowsAdmission:
    """The AD-654a round counter advances on ``dispatched``. BF-771 stopped a
    denial counting; this stops a silent drop counting. An inflated round drains
    the budget and the thread goes quiet having delivered nothing."""

    @staticmethod
    async def _route(dispatch_return):
        from tests.test_bf201_thread_post_cap import _make_channel, _make_router

        router = _make_router()
        router._intent_bus.dispatch_async = AsyncMock(return_value=dispatch_return)
        await router._route_to_agents(
            target_agent_ids=["agent-1"],
            is_captain=False, is_agent_post=True,
            mentioned_agent_ids=set(),
            channel=_make_channel(),
            thread_id="t-1", channel_id="ch-1",
            event_type="ward_room_post_created",
            title="Test", author_id="agent-2",
            data={"author_callsign": "Other"},
            thread_context="Hello", cooldown=0,
            current_round=0, round_participants=set(),
            thread_detail={"posts": [{"id": "p-1"}]},
        )
        return router

    async def test_a_dropped_dispatch_does_not_advance_the_round(self):
        router = await self._route(DispatchAdmission(False, reason="no_handler"))

        assert router._thread_rounds.get("t-1", 0) == 0, (
            "a dispatch nothing admitted advanced the round budget"
        )

    async def test_a_real_admission_does_advance_the_round(self):
        router = await self._route(DispatchAdmission(True, route="jetstream"))

        assert router._thread_rounds.get("t-1", 0) == 1, (
            "a genuinely admitted dispatch failed to advance the round"
        )


class TestNoTaskEventConsumerDiscardsTheResult:
    """Seven production call sites. A bare ``await x.dispatch(event)`` statement
    discards the outcome and reintroduces BF-810.

    Scoped to the AD-654c Dispatcher contract by requiring the sole positional
    argument to look like a TaskEvent, rather than matching every method named
    ``dispatch``. A parse failure FAILS rather than being skipped -- silently
    skipping unparseable files would make this guard quietly incomplete, and a
    syntax error has already once made a whole mutation run look green.
    """

    def test_every_task_event_dispatch_binds_its_result(self):
        import probos

        src_root = Path(probos.__file__).parent
        bare: list[str] = []
        parse_failures: list[str] = []
        for path in src_root.rglob("*.py"):
            if path.name == "dispatcher.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError as exc:
                parse_failures.append(f"{path.name}: {exc}")
                continue
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Expr)
                    and isinstance(node.value, ast.Await)
                    and isinstance(node.value.value, ast.Call)
                    and isinstance(node.value.value.func, ast.Attribute)
                    and node.value.value.func.attr == "dispatch"
                ):
                    continue
                call = node.value.value
                if len(call.args) != 1 or call.keywords:
                    continue
                arg = ast.unparse(call.args[0])
                if "event" not in arg.lower():
                    continue
                bare.append(
                    f"{path.name}:{node.lineno} {ast.unparse(call.func)}({arg})"
                )
        assert not parse_failures, f"could not parse: {parse_failures}"
        assert not bare, f"TaskEvent dispatch result discarded at: {bare}"
