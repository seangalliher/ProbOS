"""BF-789 (#1253): the AD-654c Dispatcher authorizes what nothing else does.

AD-698 pre-intent authorization sat on the ``IntentBus`` entry points. The
``Dispatcher`` does not go through the bus for two of its three delivery arms,
so a TaskEvent reached an agent's ``handle_intent`` with the policy hook never
consulted.

The fix is deliberately NOT "check at the top of the loop". The third arm
delegates to ``IntentBus.dispatch_async``, which already evaluates AD-698, so a
hoisted check would evaluate a hook twice per intent on that arm. For a
stateless RBAC hook that is waste; for a stateful one -- a rate limiter, a
quota -- it silently halves the allowance and nothing reports it. Several tests
here exist purely to keep the check from being hoisted by a later well-meaning
edit.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.activation import dispatcher as dispatcher_mod
from probos.activation.dispatcher import Dispatcher
from probos.activation.task_event import AgentTarget, TaskEvent
from probos.extensions import overlay
from probos.mesh.intent import IntentBus
from probos.mesh.pre_intent_auth import authorize_intent
from probos.mesh.signal import SignalManager
from probos.types import IntentMessage, Priority


@pytest.fixture(autouse=True)
def _clean_overlay():
    overlay.reset_for_tests()
    yield
    overlay.reset_for_tests()


def _make_agent(agent_id: str = "a1"):
    agent = MagicMock()
    agent.id = agent_id
    agent.agent_type = "scout"
    agent.capabilities = []
    agent.handle_intent = AsyncMock()
    return agent


def _make_registry(*agents):
    agent_map = {a.id: a for a in agents}
    reg = MagicMock()
    reg.get = MagicMock(side_effect=lambda aid: agent_map.get(aid))
    reg.all = MagicMock(return_value=list(agents))
    reg.get_by_capability = MagicMock(return_value=[])
    return reg


def _make_event(agent_id: str = "a1") -> TaskEvent:
    return TaskEvent(
        source_type="test",
        source_id="src-1",
        event_type="test_event",
        priority=Priority.NORMAL,
        target=AgentTarget(agent_id=agent_id),
        payload={"key": "value"},
    )


def _deny_all(_intent) -> bool:
    return False


# ── The two unguarded arms now refuse ────────────────────────────


class TestDeniedIntentsDoNotReachAHandler:
    async def test_a_denied_intent_never_enters_the_cognitive_queue(self):
        overlay.register_pre_intent_authorization_hook("deny_all", _deny_all)
        agent = _make_agent()
        queue = MagicMock()
        queue.enqueue = MagicMock(return_value=True)
        d = Dispatcher(
            registry=_make_registry(agent),
            ontology=None,
            get_queue=lambda _aid: queue,
        )

        result = await d.dispatch(_make_event())

        queue.enqueue.assert_not_called()
        assert result.accepted == 0
        assert result.rejected == 1
        assert result.agent_ids == []

    async def test_a_denied_intent_never_reaches_handle_intent(self):
        overlay.register_pre_intent_authorization_hook("deny_all", _deny_all)
        agent = _make_agent()
        d = Dispatcher(
            registry=_make_registry(agent),
            ontology=None,
            get_queue=lambda _aid: None,
            dispatch_async_fn=None,
        )

        result = await d.dispatch(_make_event())
        await asyncio.sleep(0)

        agent.handle_intent.assert_not_called()
        assert result.accepted == 0
        assert result.rejected == 1
        assert result.agent_ids == []

    async def test_one_denial_does_not_cancel_dispatch_to_the_rest(self):
        """Policy about one agent must not become an outage for the others."""
        allowed_id = "a2"

        def _deny_one(intent) -> bool:
            return intent.target_agent_id == allowed_id

        overlay.register_pre_intent_authorization_hook("deny_one", _deny_one)
        a1, a2 = _make_agent("a1"), _make_agent(allowed_id)
        queues = {"a1": MagicMock(), allowed_id: MagicMock()}
        for q in queues.values():
            q.enqueue = MagicMock(return_value=True)
        d = Dispatcher(
            registry=_make_registry(a1, a2),
            ontology=None,
            get_queue=lambda aid: queues[aid],
        )
        # Broadcast so both agents are targets of one dispatch call.
        event = _make_event()
        object.__setattr__(event, "target", AgentTarget(broadcast=True))
        d._resolve_target = lambda _t: ["a1", allowed_id]

        result = await d.dispatch(event)

        queues["a1"].enqueue.assert_not_called()
        queues[allowed_id].enqueue.assert_called_once()
        assert result.accepted == 1
        assert result.rejected == 1
        assert result.agent_ids == [allowed_id]


class TestAllowedIntentsAreUnaffected:
    async def test_an_allowed_intent_still_enters_the_queue(self):
        overlay.register_pre_intent_authorization_hook("allow", lambda _i: True)
        agent = _make_agent()
        queue = MagicMock()
        queue.enqueue = MagicMock(return_value=True)
        d = Dispatcher(
            registry=_make_registry(agent),
            ontology=None,
            get_queue=lambda _aid: queue,
        )

        result = await d.dispatch(_make_event())

        queue.enqueue.assert_called_once()
        assert result.accepted == 1
        assert result.agent_ids == ["a1"]

    async def test_an_allowed_intent_still_reaches_handle_intent(self):
        overlay.register_pre_intent_authorization_hook("allow", lambda _i: True)
        agent = _make_agent()
        d = Dispatcher(
            registry=_make_registry(agent),
            ontology=None,
            get_queue=lambda _aid: None,
            dispatch_async_fn=None,
        )

        result = await d.dispatch(_make_event())
        await asyncio.sleep(0)

        agent.handle_intent.assert_called_once()
        assert result.accepted == 1

    async def test_no_registered_hook_is_an_allow_not_a_deny(self):
        """An empty registry is how "no policy installed" is represented."""
        agent = _make_agent()
        queue = MagicMock()
        queue.enqueue = MagicMock(return_value=True)
        d = Dispatcher(
            registry=_make_registry(agent),
            ontology=None,
            get_queue=lambda _aid: queue,
        )

        result = await d.dispatch(_make_event())

        queue.enqueue.assert_called_once()
        assert result.accepted == 1


# ── The anti-double-charge pins ──────────────────────────────────


class TestTheHookIsEvaluatedExactlyOncePerIntent:
    async def test_the_delegating_arm_evaluates_the_hook_exactly_once(self):
        """Crosses the seam with a REAL bus, not a fake dispatch_async_fn.

        `startup/finalize.py` passes `_intent_bus.dispatch_async` here, and that
        method authorizes. If the Dispatcher also authorized on this arm, a
        counting hook would see 2 -- which is exactly how a rate limiter loses
        half its budget without anything reporting it.
        """
        calls: list[str] = []

        def _counting(intent) -> bool:
            calls.append(intent.intent)
            return True

        overlay.register_pre_intent_authorization_hook("counting", _counting)
        bus = IntentBus(SignalManager())
        agent = _make_agent()
        d = Dispatcher(
            registry=_make_registry(agent),
            ontology=None,
            get_queue=lambda _aid: None,
            dispatch_async_fn=bus.dispatch_async,
        )

        await d.dispatch(_make_event())

        assert len(calls) == 1, (
            f"expected exactly one hook evaluation on the delegating arm, "
            f"got {len(calls)}: {calls}"
        )

    async def test_a_real_bus_denial_is_not_reported_as_dispatched(self):
        """The arm that does not authorize must still not LIE about the result.

        The bus's default denial shape is a silent no-op, and this arm used to
        increment `accepted` on the very next line -- so policy worked and the
        DispatchResult said the work went out anyway. Found in adversarial
        review of this diff; it is the same defect class as BF-790 (#1254).
        """
        calls: list[str] = []

        def _counting_deny(intent) -> bool:
            calls.append(intent.intent)
            return False

        overlay.register_pre_intent_authorization_hook("deny", _counting_deny)
        bus = IntentBus(SignalManager())
        agent = _make_agent()
        d = Dispatcher(
            registry=_make_registry(agent),
            ontology=None,
            get_queue=lambda _aid: None,
            dispatch_async_fn=bus.dispatch_async,
        )

        result = await d.dispatch(_make_event())
        await asyncio.sleep(0)

        assert len(calls) == 1, "hook must still be evaluated exactly once"
        agent.handle_intent.assert_not_called()
        assert result.accepted == 0
        assert result.rejected == 1
        assert result.agent_ids == []

    async def test_the_guarded_arms_also_evaluate_exactly_once(self):
        calls: list[str] = []

        def _counting(intent) -> bool:
            calls.append(intent.intent)
            return True

        overlay.register_pre_intent_authorization_hook("counting", _counting)
        agent = _make_agent()
        queue = MagicMock()
        queue.enqueue = MagicMock(return_value=True)
        d = Dispatcher(
            registry=_make_registry(agent),
            ontology=None,
            get_queue=lambda _aid: queue,
        )

        await d.dispatch(_make_event())

        assert len(calls) == 1


class TestTheCheckIsNotHoistedAboveTheBranch:
    """AST guards. A later edit that "simplifies" this reintroduces BF-789's
    inverse -- double evaluation on the delegating arm."""

    @staticmethod
    def _dispatch_fn_node() -> ast.AsyncFunctionDef:
        tree = ast.parse(Path(dispatcher_mod.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "Dispatcher":
                for item in node.body:
                    if (
                        isinstance(item, ast.AsyncFunctionDef)
                        and item.name == "dispatch"
                    ):
                        return item
        raise AssertionError("Dispatcher.dispatch not found")

    @staticmethod
    def _authorize_calls(node: ast.AST) -> list[ast.Call]:
        return [
            n
            for n in ast.walk(node)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "authorize_intent"
        ]

    def test_exactly_two_authorization_sites_in_dispatch(self):
        found = self._authorize_calls(self._dispatch_fn_node())
        assert len(found) == 2, (
            f"expected 2 authorize_intent calls in Dispatcher.dispatch "
            f"(queue arm + direct arm), found {len(found)}. A third is most "
            f"likely a hoisted check that double-charges the delegating arm."
        )

    def test_the_delegating_arm_contains_no_authorization_call(self):
        """The arm that calls `_dispatch_async_fn` must NOT authorize."""
        dispatch_fn = self._dispatch_fn_node()
        delegating_branches = [
            n
            for n in ast.walk(dispatch_fn)
            if isinstance(n, ast.If)
            and any(
                isinstance(c, ast.Attribute) and c.attr == "_dispatch_async_fn"
                for c in ast.walk(n.test)
            )
        ]
        assert delegating_branches, (
            "could not locate the `_dispatch_async_fn` branch -- this guard is "
            "inert until it is re-pointed at whatever replaced it"
        )
        for branch in delegating_branches:
            in_body = self._authorize_calls(ast.Module(body=branch.body, type_ignores=[]))
            assert not in_body, (
                "the delegating arm authorizes, but IntentBus.dispatch_async "
                "already does -- a stateful hook is now charged twice per intent"
            )

    def test_the_wiring_really_passes_the_authorizing_bus_method(self):
        """Load-bearing: the "it already authorizes" claim rests on this.

        AST, not a substring. A substring check passed when the real wiring was
        replaced and the expected text appended as a COMMENT -- the repo's
        recurring source-scan failure, caught here in review.
        """
        finalize_path = (
            Path(dispatcher_mod.__file__).parents[1] / "startup" / "finalize.py"
        )
        tree = ast.parse(finalize_path.read_text(encoding="utf-8"))
        wirings = []
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "Dispatcher"
            ):
                continue
            for kw in node.keywords:
                if kw.arg == "dispatch_async_fn":
                    wirings.append(ast.unparse(kw.value))
        assert wirings, "no production Dispatcher(dispatch_async_fn=...) wiring found"
        for expr in wirings:
            assert expr == "_dispatch_async", (
                f"Dispatcher is wired with {expr!r}. BF-811 (#1275) replaced the "
                "former '.dispatch_async' suffix assertion here: a suffix proves "
                "spelling, not identity, and an unauthorized lookalike was "
                "measured delivering with zero policy calls and accepted=1. The "
                "delegate must now be the local that finalize.py identity-checks "
                "against IntentBus.dispatch_async before construction; that check "
                "is pinned by tests/test_bf811_dispatcher_delegate_identity.py."
            )

        bus_src = inspect.getsource(IntentBus.dispatch_async)
        code_only = "\n".join(
            line for line in bus_src.splitlines() if not line.lstrip().startswith("#")
        )
        assert "self._authorize(" in code_only


# ── The shared authorizer fails closed ───────────────────────────


class TestSharedAuthorizerFailsClosed:
    def test_a_broken_overlay_import_denies(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "probos.extensions.overlay", object())
        allowed, reason = authorize_intent(
            IntentMessage(intent="x", params={}), entry_point="t"
        )
        assert allowed is False
        assert reason.startswith("import:")

    def test_a_raising_evaluator_denies(self, monkeypatch):
        def _explode(_intent):
            raise RuntimeError("boom")

        monkeypatch.setattr(
            overlay, "evaluate_pre_intent_authorization", _explode
        )
        allowed, reason = authorize_intent(
            IntentMessage(intent="x", params={}), entry_point="t"
        )
        assert allowed is False
        assert reason.startswith("evaluator:")

    def test_a_hook_denial_reports_the_hook_name(self):
        overlay.register_pre_intent_authorization_hook("rbac", _deny_all)
        allowed, reason = authorize_intent(
            IntentMessage(intent="x", params={}), entry_point="t"
        )
        assert allowed is False
        assert reason == "rbac"

    def test_the_bus_still_fails_closed_after_delegating(self, monkeypatch):
        """The bus kept its behaviour when the body moved out of it."""
        monkeypatch.setitem(sys.modules, "probos.extensions.overlay", object())
        bus = IntentBus(SignalManager())
        assert (
            bus._authorize(
                IntentMessage(intent="x", params={}),
                entry_point="t",
                raise_on_denial=False,
            )
            is False
        )

    async def test_the_dispatcher_refuses_when_the_overlay_is_broken(self, monkeypatch):
        """Fail-closed reaches the consumer, not just the helper."""
        monkeypatch.setitem(sys.modules, "probos.extensions.overlay", object())
        agent = _make_agent()
        queue = MagicMock()
        queue.enqueue = MagicMock(return_value=True)
        d = Dispatcher(
            registry=_make_registry(agent),
            ontology=None,
            get_queue=lambda _aid: queue,
        )

        result = await d.dispatch(_make_event())

        queue.enqueue.assert_not_called()
        assert result.accepted == 0
        assert result.rejected == 1
