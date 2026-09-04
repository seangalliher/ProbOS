"""BF-811 (#1275): the Dispatcher delegate must BE this bus's dispatch_async.

`Dispatcher.dispatch` has three arms. The queue arm authorizes, the create_task
fallback authorizes, and the delegating arm deliberately does NOT -- checking
there too would charge a stateful hook (rate limiter, quota) twice per intent.
Its safety therefore rests on the prerequisite that the injected delegate has
already evaluated AD-698, and `Dispatcher.__init__` types that delegate as
`Callable[..., Any] | None`, so nothing enforced it.

Three successive static-AST guard designs were built and rejected during review,
each defeated in BOTH directions -- new bypasses (import alias, qualified name,
assignment alias, `functools.partial`, subclass, `**kwargs` splat, `AnnAssign`
rebinding, walrus, long alias chains) AND false failures on legitimate code.
Deciding "does this expression evaluate to that bound method" is type inference,
which a source scan cannot do.

These tests exercise the PRODUCTION predicate directly rather than asserting a
shape over source text, because review also defeated an AST-shaped test: it
accepted an inverted guard, a guard placed after construction, and a comparison
against an unrelated name.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from types import MethodType
from typing import Any

from probos.mesh.intent import IntentBus
from probos.startup import finalize as finalize_mod
from probos.startup.finalize import is_authorizing_dispatch_delegate


def _bus() -> IntentBus:
    """A real IntentBus without running its __init__ side effects."""
    return IntentBus.__new__(IntentBus)


class TestThePredicateAcceptsOnlyTheRealDelegate:
    def test_the_authorizing_bound_method_is_accepted(self):
        bus = _bus()
        assert is_authorizing_dispatch_delegate(bus.dispatch_async, bus) is True

    def test_a_bound_method_of_a_different_bus_is_rejected(self):
        """Review measured this delivering through the WRONG bus.

        A `__func__`-only check passes here, because both objects share the same
        underlying function. Only `__self__` separates them, and the observed
        result was `other_policy_calls 1`: the intent was authorized and
        delivered by a bus the Dispatcher was not wired to.
        """
        expected, other = _bus(), _bus()
        assert other.dispatch_async.__func__ is expected.dispatch_async.__func__
        assert is_authorizing_dispatch_delegate(other.dispatch_async, expected) is False

    def test_a_callable_with_a_forged_dunder_func_is_rejected(self):
        """Also measured passing before `isinstance(..., MethodType)` was added.

        The forgery must be an INSTANCE attribute. Assigning the function at
        class level makes it a descriptor, so the attribute reads back as a
        bound method of the spoof and the forgery never lands.
        """

        class _Spoof:
            def __init__(self) -> None:
                self.__func__ = IntentBus.dispatch_async

            async def __call__(self, *a: Any, **k: Any) -> None:
                return None

        spoof = _Spoof()
        assert spoof.__func__ is IntentBus.dispatch_async, "control: forgery is real"
        assert is_authorizing_dispatch_delegate(spoof, _bus()) is False

    def test_a_different_method_with_the_same_name_is_rejected(self):
        """The acceptance criterion for #1275.

        A guard that only rejects `None` or a missing kwarg passes against the
        exact bypass this issue exists to prevent, so the impostor must be a
        *different* method that is also called `dispatch_async`.
        """

        class _Lookalike:
            async def dispatch_async(self, *a: Any, **k: Any) -> None:
                return None

        impostor = _Lookalike().dispatch_async
        assert impostor.__name__ == "dispatch_async", "control: same spelling"
        assert isinstance(impostor, MethodType), "control: a real bound method"
        assert is_authorizing_dispatch_delegate(impostor, _bus()) is False

    def test_a_subclass_override_is_rejected(self):
        """An override is a different function, so it is not the audited one."""

        class _Overriding(IntentBus):
            async def dispatch_async(self, *a: Any, **k: Any) -> None:
                return None

        sub = _Overriding.__new__(_Overriding)
        assert is_authorizing_dispatch_delegate(sub.dispatch_async, sub) is False

    def test_plain_callables_and_none_are_rejected(self):
        bus = _bus()

        async def dispatch_async(*a: Any, **k: Any) -> None:
            return None

        assert is_authorizing_dispatch_delegate(dispatch_async, bus) is False
        assert is_authorizing_dispatch_delegate(None, bus) is False
        assert is_authorizing_dispatch_delegate(object(), bus) is False


class TestTheWiringSiteUsesThePredicate:
    """The predicate is worthless if finalize does not actually apply it."""

    @staticmethod
    def _finalize_tree() -> ast.Module:
        source = Path(inspect.getfile(finalize_mod)).read_text(encoding="utf-8")
        return ast.parse(source, filename="finalize.py")

    def test_the_dispatcher_is_constructed_with_the_checked_value(self):
        delegates = [
            ast.unparse(kw.value)
            for node in ast.walk(self._finalize_tree())
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Dispatcher"
            for kw in node.keywords
            if kw.arg == "dispatch_async_fn"
        ]
        assert delegates, "no production Dispatcher(dispatch_async_fn=...) found"
        for expr in delegates:
            assert expr == "_dispatch_async", (
                f"Dispatcher is wired with {expr!r}, which bypasses the identity "
                "check performed on `_dispatch_async`"
            )

    def test_the_check_runs_before_construction_and_raises(self):
        """Ordering matters: review defeated an earlier version of this test
        with a guard placed AFTER the Dispatcher was already built."""
        tree = self._finalize_tree()
        guard_lines = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.If)
            and "is_authorizing_dispatch_delegate" in ast.unparse(node.test)
            and isinstance(node.test, ast.UnaryOp)
            and isinstance(node.test.op, ast.Not)
            and [n for n in node.body if isinstance(n, ast.Raise)]
        ]
        construction_lines = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Dispatcher"
        ]
        assert guard_lines, (
            "finalize.py must guard with `if not "
            "is_authorizing_dispatch_delegate(...)` and raise in that branch"
        )
        assert construction_lines, "no Dispatcher construction found"
        assert min(guard_lines) < min(construction_lines), (
            f"the guard at line {min(guard_lines)} must precede the Dispatcher "
            f"construction at line {min(construction_lines)}"
        )


def test_the_other_two_arms_still_authorize_on_their_own():
    """An omitted or None delegate must stay legal.

    With `_dispatch_async_fn` unset, `dispatch` falls through to the create_task
    arm, which authorizes itself. Any guard that rejects that path is wrong.
    """
    from probos.activation import dispatcher as dispatcher_mod

    source = Path(inspect.getfile(dispatcher_mod)).read_text(encoding="utf-8")
    dispatch_fn = next(
        node
        for node in ast.walk(ast.parse(source, filename="dispatcher.py"))
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "dispatch"
    )
    authorize_calls = [
        node
        for node in ast.walk(dispatch_fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "authorize_intent"
    ]
    assert len(authorize_calls) == 2, (
        "expected the queue arm and the create_task arm to authorize; the "
        f"delegating arm must not. Found {len(authorize_calls)}."
    )
