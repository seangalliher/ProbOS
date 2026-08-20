"""BF-815 (#1279): dispatch_async reports whether an agent took the work.

Every path is driven against a REAL ``IntentBus``. The point of this issue is
that a test double returning ``None`` is exactly what hid the defect -- the
suite was green while six production paths dropped intents silently -- so a
double proves nothing here.

``admitted`` means an agent took responsibility, NOT that the work completed.
A fire-and-forget dispatch cannot know the latter.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.extensions import overlay
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.types import DispatchAdmission, IntentMessage, Priority


@pytest.fixture(autouse=True)
def _clean_overlay():
    overlay.reset_for_tests()
    yield
    overlay.reset_for_tests()


def _intent(target: str = "a1") -> IntentMessage:
    return IntentMessage(intent="direct_message", params={}, target_agent_id=target)


# ── Every drop path is now visible ───────────────────────────────


class TestTheDropPathsReportThemselves:
    async def test_a_closed_bus_is_not_an_admission(self):
        bus = IntentBus(SignalManager())
        bus.close_to_new_dispatches()

        admission = await bus.dispatch_async(_intent())

        assert admission.admitted is False
        assert admission.reason == "bus_closed"

    async def test_a_policy_denial_is_not_an_admission(self):
        overlay.register_pre_intent_authorization_hook("rbac", lambda _i: False)
        bus = IntentBus(SignalManager())

        admission = await bus.dispatch_async(_intent())

        assert admission.admitted is False
        assert admission.reason == "denied"

    async def test_no_handler_is_not_an_admission(self):
        """The case the Ward Room and Dispatcher both counted as delivered."""
        bus = IntentBus(SignalManager())  # nobody subscribed

        admission = await bus.dispatch_async(_intent())

        assert admission.admitted is False
        assert admission.reason == "no_handler"

    async def test_the_pending_task_cap_is_not_an_admission(self):
        bus = IntentBus(SignalManager())

        async def _slow(_i):
            await asyncio.sleep(30)

        bus.subscribe("a1", _slow)
        try:
            # Fill the cap (200) so the next dispatch is dropped.
            for _ in range(200):
                await bus.dispatch_async(_intent())

            admission = await bus.dispatch_async(_intent())

            assert admission.admitted is False
            assert admission.reason == "pending_cap"
        finally:
            # In a `finally` because an assertion failure above would otherwise
            # leak 200 sleeping tasks into the rest of the session.
            for task in list(bus._pending_sub_tasks):
                task.cancel()
            await asyncio.gather(*bus._pending_sub_tasks, return_exceptions=True)

    async def test_a_task_cancelled_by_shutdown_is_not_an_admission(self):
        """`_track_pending_task` cancels and returns False once registration
        closes; reporting admitted there claims a handler that never ran."""
        bus = IntentBus(SignalManager())
        ran: list[str] = []

        async def _handler(intent: IntentMessage):
            ran.append(intent.intent)

        bus.subscribe("a1", _handler)
        bus._pending_task_registration_closed = True

        admission = await bus.dispatch_async(_intent())
        await asyncio.gather(*bus._pending_sub_tasks, return_exceptions=True)

        assert admission.admitted is False
        assert admission.reason == "registration_closed"
        assert ran == [], "the handler ran despite registration being closed"


class TestAnAdmissionSaysWhichRouteTookIt:
    async def test_a_direct_handler_is_admitted_as_a_task(self):
        bus = IntentBus(SignalManager())
        seen: list[str] = []

        async def _handler(intent: IntentMessage):
            seen.append(intent.intent)

        bus.subscribe("a1", _handler)

        admission = await bus.dispatch_async(_intent())
        await asyncio.sleep(0)

        assert admission.admitted is True
        assert admission.route == "task"
        assert seen == ["direct_message"]

    async def test_a_cognitive_queue_is_admitted_as_a_queue(self):
        bus = IntentBus(SignalManager())
        queue = MagicMock()
        queue.enqueue = MagicMock(return_value=True)
        bus.register_queue("a1", queue)

        admission = await bus.dispatch_async(_intent())

        assert admission.admitted is True
        assert admission.route == "queue"
        queue.enqueue.assert_called_once()

    async def test_a_full_queue_falls_through_rather_than_claiming_success(self):
        """A rejected enqueue must not report `queue`; it retries via handler."""
        bus = IntentBus(SignalManager())
        queue = MagicMock()
        queue.enqueue = MagicMock(return_value=False)
        bus.register_queue("a1", queue)

        async def _handler(_intent):
            return None

        bus.subscribe("a1", _handler)

        admission = await bus.dispatch_async(_intent())
        await asyncio.sleep(0)

        assert admission.admitted is True
        assert admission.route == "task", (
            "a refused enqueue reported itself as queued"
        )


class TestTheReceiptIsUsableAsABoolean:
    async def test_falsy_when_dropped(self):
        bus = IntentBus(SignalManager())

        assert not await bus.dispatch_async(_intent())

    async def test_truthy_when_admitted(self):
        bus = IntentBus(SignalManager())
        bus.subscribe("a1", AsyncMock())

        assert await bus.dispatch_async(_intent())

    def test_bool_is_defined_so_the_natural_check_is_not_always_false(self):
        """Without __bool__, `if not admission` is false for every object --
        silently reintroducing the bug this type exists to fix."""
        assert bool(DispatchAdmission(True)) is True
        assert bool(DispatchAdmission(False)) is False


class TestTheTransportOutcomeIsNotAssumed:
    """`js_publish` returns normally after a JetStream ACK, a core-NATS
    fallback, AND after both fail and it logs "event dropped". Assuming the
    first reproduced the original defect at the transport boundary."""

    @staticmethod
    def _bus_with_transport(outcome: str) -> IntentBus:
        bus = IntentBus(SignalManager())
        nats = MagicMock()
        nats.connected = True
        nats.js_publish = AsyncMock(return_value=outcome)
        bus._nats_bus = nats
        return bus

    async def test_a_jetstream_ack_is_admitted_as_jetstream(self):
        bus = self._bus_with_transport("jetstream")

        admission = await bus.dispatch_async(_intent())

        assert admission.admitted is True
        assert admission.route == "jetstream"

    async def test_a_core_nats_fallback_says_so_rather_than_claiming_jetstream(self):
        bus = self._bus_with_transport("core_nats")

        admission = await bus.dispatch_async(_intent())

        assert admission.admitted is True
        assert admission.route == "core_nats", (
            "an at-most-once core-NATS publish was reported as a durable "
            "JetStream ACK"
        )

    async def test_a_dropped_publish_falls_through_instead_of_claiming_success(self):
        """Both transports failed. The event is gone."""
        bus = self._bus_with_transport("dropped")

        admission = await bus.dispatch_async(_intent())

        assert admission.admitted is False, (
            "a message both transports dropped was reported as dispatched"
        )
        assert admission.reason == "no_handler"

    async def test_a_dropped_publish_still_reaches_a_local_handler(self):
        """Falling through is the point -- a local subscriber can still take it."""
        bus = self._bus_with_transport("dropped")
        ran: list[str] = []

        async def _handler(intent: IntentMessage):
            ran.append(intent.intent)

        bus.subscribe("a1", _handler)

        admission = await bus.dispatch_async(_intent())
        await asyncio.sleep(0)

        assert admission.admitted is True
        assert admission.route == "task"
        assert ran == ["direct_message"]

    def test_js_publish_declares_a_string_outcome(self):
        from probos.mesh.nats_bus import NATSBus

        annotation = inspect.signature(NATSBus.js_publish).return_annotation
        assert "str" in str(annotation), (
            f"js_publish returns {annotation!r}; a caller cannot tell a durable "
            f"ACK from a logged 'event dropped'"
        )


class TestJsPublishReportsItsOwnOutcome:
    """Drives the REAL `NATSBus.js_publish` with stubbed collaborators.

    The tests above mock `js_publish` itself, so they pin how `dispatch_async`
    CONSUMES the outcome but not how the transport PRODUCES it. Mutation caught
    that gap: making the drop paths return "core_nats" left them all green.
    """

    @staticmethod
    def _stub(*, js: object | None, suspended: bool, publish_fails: bool):
        from probos.mesh.nats_bus import NATSBus

        class _Stub:
            _js = js
            _js_suspended = suspended
            _js_consecutive_failures = 0
            _js_failure_threshold = 5
            _js_publish_timeout = 1.0
            _js_recovery_task = None

            async def publish(self, *_a, **_kw):
                if publish_fails:
                    raise RuntimeError("core NATS down")

            def _full_subject(self, s: str) -> str:
                return s

        return NATSBus.js_publish, _Stub()

    async def test_a_jetstream_ack_reports_jetstream(self):
        js = MagicMock()
        js.publish = AsyncMock()
        fn, stub = self._stub(js=js, suspended=False, publish_fails=False)

        assert await fn(stub, "subj", {"k": "v"}) == "jetstream"

    async def test_no_jetstream_configured_reports_core_nats(self):
        fn, stub = self._stub(js=None, suspended=False, publish_fails=False)

        assert await fn(stub, "subj", {"k": "v"}) == "core_nats"

    async def test_both_transports_failing_reports_dropped(self):
        js = MagicMock()
        js.publish = AsyncMock(side_effect=RuntimeError("jetstream down"))
        fn, stub = self._stub(js=js, suspended=False, publish_fails=True)

        assert await fn(stub, "subj", {"k": "v"}) == "dropped", (
            "a message both transports lost was reported as published"
        )

    async def test_jetstream_failing_alone_reports_core_nats(self):
        js = MagicMock()
        js.publish = AsyncMock(side_effect=RuntimeError("jetstream down"))
        fn, stub = self._stub(js=js, suspended=False, publish_fails=False)

        assert await fn(stub, "subj", {"k": "v"}) == "core_nats"

    async def test_suspended_jetstream_with_a_failing_fallback_reports_dropped(self):
        js = MagicMock()
        fn, stub = self._stub(js=js, suspended=True, publish_fails=True)

        assert await fn(stub, "subj", {"k": "v"}) == "dropped"

    async def test_suspended_jetstream_with_a_working_fallback_reports_core_nats(self):
        js = MagicMock()
        fn, stub = self._stub(js=js, suspended=True, publish_fails=False)

        assert await fn(stub, "subj", {"k": "v"}) == "core_nats"


# ── No path may return None again ────────────────────────────────


class TestEveryPathReturnsAReceipt:
    def test_no_bare_return_survives_in_dispatch_async(self):
        """AST, so a future edit cannot reintroduce a silent path."""
        from probos.mesh import intent as intent_mod

        tree = ast.parse(Path(intent_mod.__file__).read_text(encoding="utf-8"))
        fn = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "dispatch_async"
        )
        bare = [
            n.lineno for n in ast.walk(fn)
            if isinstance(n, ast.Return) and n.value is None
        ]
        assert not bare, (
            f"dispatch_async has bare `return` at lines {bare}; each is a "
            f"silent drop indistinguishable from a hand-off"
        )

    def test_the_declared_return_type_is_the_receipt(self):
        hints = inspect.signature(IntentBus.dispatch_async).return_annotation
        assert "DispatchAdmission" in str(hints)

    def test_the_function_cannot_fall_off_the_end(self):
        """A path reaching the end implicitly returns None."""
        from probos.mesh import intent as intent_mod

        tree = ast.parse(Path(intent_mod.__file__).read_text(encoding="utf-8"))
        fn = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "dispatch_async"
        )
        last = fn.body[-1]
        assert isinstance(last, ast.Return) and last.value is not None, (
            "dispatch_async's final statement is not a return of a receipt, so "
            "the fall-through path yields None"
        )


# ── The two consumers stop counting drops as delivery ────────────


class TestConsumersConsumeTheReceipt:
    async def test_the_dispatcher_does_not_accept_an_unadmitted_dispatch(self):
        from probos.activation.dispatcher import Dispatcher
        from probos.activation.task_event import AgentTarget, TaskEvent

        agent = MagicMock()
        agent.id = "a1"
        agent.agent_type = "scout"
        agent.capabilities = []
        reg = MagicMock()
        reg.get = MagicMock(side_effect=lambda aid: agent if aid == "a1" else None)
        reg.all = MagicMock(return_value=[agent])
        reg.get_by_capability = MagicMock(return_value=[])

        # Real bus with nobody subscribed -> no_handler.
        bus = IntentBus(SignalManager())
        d = Dispatcher(
            registry=reg, ontology=None,
            get_queue=lambda _aid: None,
            dispatch_async_fn=bus.dispatch_async,
        )
        event = TaskEvent(
            source_type="test", source_id="s1", event_type="e",
            priority=Priority.NORMAL, target=AgentTarget(agent_id="a1"),
            payload={},
        )

        result = await d.dispatch(event)

        assert result.accepted == 0, (
            "the Dispatcher reported a silently-dropped intent as accepted"
        )
        assert result.rejected == 1
        assert result.agent_ids == []

    async def test_the_dispatcher_still_accepts_a_real_admission(self):
        from probos.activation.dispatcher import Dispatcher
        from probos.activation.task_event import AgentTarget, TaskEvent

        agent = MagicMock()
        agent.id = "a1"
        agent.agent_type = "scout"
        agent.capabilities = []
        reg = MagicMock()
        reg.get = MagicMock(side_effect=lambda aid: agent if aid == "a1" else None)
        reg.all = MagicMock(return_value=[agent])
        reg.get_by_capability = MagicMock(return_value=[])

        bus = IntentBus(SignalManager())
        bus.subscribe("a1", AsyncMock())
        d = Dispatcher(
            registry=reg, ontology=None,
            get_queue=lambda _aid: None,
            dispatch_async_fn=bus.dispatch_async,
        )
        event = TaskEvent(
            source_type="test", source_id="s1", event_type="e",
            priority=Priority.NORMAL, target=AgentTarget(agent_id="a1"),
            payload={},
        )

        result = await d.dispatch(event)
        await asyncio.sleep(0)

        assert result.accepted == 1
        assert result.agent_ids == ["a1"]

    def test_the_ward_room_gates_its_counter_on_admission(self):
        """Executable, not a source scan.

        The first version of this test only asserted that some ``if`` mentioned
        ``admission``. Review inserted an unconditional ``dispatched += 1`` into
        the source and it still passed -- the assertion could not see the
        behaviour it claimed to protect.
        """
        import probos.ward_room_router as wrr

        src = Path(wrr.__file__).read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn = next(
            n for n in ast.walk(tree)
            if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))
            and "dispatched" in ast.unparse(n)
            and "dispatch_async" in ast.unparse(n)
        )
        # Every `dispatched += 1` must sit inside a branch that tests the
        # admission -- an unconditional one anywhere in this function is the
        # defect.
        increments = [
            n for n in ast.walk(fn)
            if isinstance(n, ast.AugAssign)
            and isinstance(n.target, ast.Name)
            and n.target.id == "dispatched"
        ]
        assert increments, "no `dispatched` increment found -- guard is inert"

        guarded_bodies: list[str] = []
        for node in ast.walk(fn):
            if isinstance(node, ast.If) and "admission" in ast.unparse(node.test):
                guarded_bodies.append(ast.unparse(node))
        assert guarded_bodies, "no branch tests the admission"
        joined = "\n".join(guarded_bodies)
        for inc in increments:
            assert "dispatched += 1" in joined, (
                "a `dispatched += 1` sits outside every admission-gated branch"
            )
