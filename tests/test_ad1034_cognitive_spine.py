"""AD-1034: tests for the ``CognitiveSpine`` — the agent's synchronous nervous system.

BF-287 discipline: real objects at the agent/organ boundary — a real ``CognitiveSpine``,
real ``_FakeOrgan(BaseCognitiveOrgan)`` subclasses, and a minimal real
``CognitiveAgent`` subclass; NO ``MagicMock`` where a column/attribute typo could pass.

Coverage maps to the issue #982 acceptance criteria:
* zero-organ byte-identical — the lifecycle hook never invokes ``drive_cycle`` with no
  organs, and the agent's lifecycle still completes in order;
* a registered organ receives ``perceive → decide → act`` in order during the cycle;
* ``detach_all`` on agent teardown releases organs;
* an intra-organ signal is delivered synchronously within the same cycle;
* sovereignty — no spine path reaches the intent bus (source + held-state inspection);
* no ``await`` on a bus/network call on the synchronous cycle path (source inspection).
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import textwrap
from typing import Any

import pytest

from probos.cognitive.organ import BaseCognitiveOrgan
from probos.cognitive.spine import EXOGENOUS_SIGNAL_KIND, CognitiveSpine
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.types import IntentMessage, IntentResult


# ----------------------------------------------------------------------------
# Test doubles (real small objects — BF-287)
# ----------------------------------------------------------------------------


class _StubParent:
    """Minimal stand-in for a parent agent — exposes only the public id attributes the
    spine reads. A real small object, not a ``MagicMock``."""

    def __init__(self, runtime_id: str = "agent-x", sovereign_id: str = "") -> None:
        self.id = runtime_id
        self.sovereign_id = sovereign_id


class _FakeOrgan(BaseCognitiveOrgan):
    """A real organ that records every cycle step and signal it receives."""

    default_name = "fake"

    def __init__(self, *, name: str | None = None, trace: list | None = None) -> None:
        super().__init__(name=name)
        self.calls: list[str] = []
        self.perceived_contexts: list[Any] = []
        self.signals: list[tuple[str, Any]] = []
        self.attach_count = 0
        self.detach_count = 0
        self._trace = trace  # optional shared list for cross-organ ordering

    def on_attach(self, parent: Any) -> None:
        self.attach_count += 1

    def on_detach(self) -> None:
        self.detach_count += 1

    def perceive(self, context: Any) -> Any:
        self.calls.append("perceive")
        self.perceived_contexts.append(context)
        if self._trace is not None:
            self._trace.append((self.name, "perceive"))
        return {"observed": context}

    def decide(self, observation: Any) -> Any:
        self.calls.append("decide")
        if self._trace is not None:
            self._trace.append((self.name, "decide"))
        return {"decided": observation}

    def act(self, decision: Any) -> Any:
        self.calls.append("act")
        if self._trace is not None:
            self._trace.append((self.name, "act"))
        return {"acted": decision}

    def on_signal(self, kind: str, payload: Any) -> None:
        self.signals.append((kind, payload))


class _EmitterOrgan(BaseCognitiveOrgan):
    """An organ that emits an intra-organ signal during its ``act`` step."""

    default_name = "emitter"

    def __init__(self, *, name: str | None = None, spine: CognitiveSpine, kind: str, payload: Any) -> None:
        super().__init__(name=name)
        self._spine = spine
        self._kind = kind
        self._payload = payload

    def act(self, decision: Any) -> Any:
        self._spine.emit_signal(self._kind, self._payload)
        return None


class _RaisingOrgan(BaseCognitiveOrgan):
    """An organ that raises in ``perceive`` — used to prove cycle isolation."""

    default_name = "raiser"

    def perceive(self, context: Any) -> Any:
        raise RuntimeError("organ cycle boom")


class _SignalRaiser(BaseCognitiveOrgan):
    """A subscriber whose ``on_signal`` raises — used to prove emit isolation."""

    default_name = "signal_raiser"

    def on_signal(self, kind: str, payload: Any) -> None:
        raise RuntimeError("signal boom")


class _SpineLifecycleAgent(CognitiveAgent):
    """A minimal real ``CognitiveAgent`` whose lifecycle steps are stubbed so the
    AD-1034 guarded hook can be exercised without an LLM or runtime. Real agent, real
    spine — BF-287."""

    agent_type = "spine_test"
    instructions = "Spine lifecycle test agent."

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.lifecycle_calls: list[str] = []

    async def perceive(self, intent: Any) -> dict:
        self.lifecycle_calls.append("perceive")
        return {"params": {}, "correlation_id": "", "memories": []}

    async def _recall_relevant_memories(self, intent: Any, observation: dict) -> dict:
        self.lifecycle_calls.append("recall")
        return observation

    async def decide(self, observation: dict) -> dict:
        self.lifecycle_calls.append("decide")
        return {"llm_output": ""}

    async def act(self, decision: dict) -> dict:
        self.lifecycle_calls.append("act")
        return {"success": True, "result": "ok"}

    async def report(self, result: dict) -> dict:
        self.lifecycle_calls.append("report")
        return {"success": True, "result": "ok"}


# ----------------------------------------------------------------------------
# Construction / introspection
# ----------------------------------------------------------------------------


def test_cognitive_agent_constructs_an_empty_spine() -> None:
    agent = _SpineLifecycleAgent()
    assert isinstance(agent._spine, CognitiveSpine)
    assert agent._spine.has_organs is False
    assert agent._spine.organs == ()
    assert agent._spine.organ_names == ()


def test_parent_id_prefers_sovereign_then_id() -> None:
    spine = CognitiveSpine(_StubParent(runtime_id="rt-1", sovereign_id="sov-1"))
    assert spine.parent_id == "sov-1"
    spine_no_sovereign = CognitiveSpine(_StubParent(runtime_id="rt-2", sovereign_id=""))
    assert spine_no_sovereign.parent_id == "rt-2"


# ----------------------------------------------------------------------------
# Zero-organ byte-identical (the hard requirement)
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_zero_organ_lifecycle_does_not_invoke_drive_cycle() -> None:
    """With zero organs, the guarded hook never calls ``drive_cycle`` and the lifecycle
    completes exactly as before — byte-identical."""
    agent = _SpineLifecycleAgent()
    assert agent._spine.has_organs is False

    drove: list[Any] = []
    original = agent._spine.drive_cycle

    def _spy(context: Any) -> None:
        drove.append(context)
        return original(context)

    agent._spine.drive_cycle = _spy  # type: ignore[method-assign]

    intent = IntentMessage(intent="direct_message", params={"text": "hello"})
    result = await agent._run_cognitive_lifecycle(intent)

    assert isinstance(result, IntentResult)
    assert result.success is True
    # The hook is gated on has_organs → drive_cycle is NEVER called with zero organs.
    assert drove == []
    # The agent-level lifecycle order is unchanged.
    assert agent.lifecycle_calls == ["perceive", "recall", "decide", "act", "report"]


@pytest.mark.asyncio
async def test_lifecycle_drives_organ_cycle_when_organ_registered() -> None:
    """When an organ is composed, the hook drives its full cycle in order, and the
    agent-level lifecycle order is still preserved (cycle runs between recall and
    decide)."""
    agent = _SpineLifecycleAgent()
    fake = _FakeOrgan()
    agent._spine.attach_organ(fake)
    assert agent._spine.has_organs is True

    intent = IntentMessage(intent="direct_message", params={"text": "hello"})
    result = await agent._run_cognitive_lifecycle(intent)

    assert isinstance(result, IntentResult)
    assert fake.calls == ["perceive", "decide", "act"]
    assert agent.lifecycle_calls == ["perceive", "recall", "decide", "act", "report"]


@pytest.mark.asyncio
async def test_agent_stop_detaches_all_organs() -> None:
    agent = _SpineLifecycleAgent()
    fake = _FakeOrgan()
    agent._spine.attach_organ(fake)
    assert fake.attached is True

    await agent.stop()

    assert fake.attached is False
    assert fake.detach_count == 1
    assert agent._spine.has_organs is False


# ----------------------------------------------------------------------------
# Cycle
# ----------------------------------------------------------------------------


def test_drive_cycle_runs_perceive_decide_act_in_order() -> None:
    spine = CognitiveSpine(_StubParent("agent-1"))
    fake = _FakeOrgan()
    spine.attach_organ(fake)

    spine.drive_cycle({"turn": 1})

    assert fake.calls == ["perceive", "decide", "act"]
    assert fake.perceived_contexts == [{"turn": 1}]


def test_drive_cycle_runs_organs_in_attach_order() -> None:
    trace: list[tuple[str, str]] = []
    spine = CognitiveSpine(_StubParent("a"))
    spine.attach_organ(_FakeOrgan(name="first", trace=trace))
    spine.attach_organ(_FakeOrgan(name="second", trace=trace))

    spine.drive_cycle({})

    assert trace == [
        ("first", "perceive"), ("first", "decide"), ("first", "act"),
        ("second", "perceive"), ("second", "decide"), ("second", "act"),
    ]


def test_drive_cycle_with_zero_organs_is_noop() -> None:
    spine = CognitiveSpine(_StubParent("a"))
    assert spine.has_organs is False
    assert spine.drive_cycle({"x": 1}) is None  # returns immediately, no error


def test_drive_cycle_isolates_a_raising_organ() -> None:
    trace: list[tuple[str, str]] = []
    spine = CognitiveSpine(_StubParent("a"))
    spine.attach_organ(_RaisingOrgan(name="bad"))
    spine.attach_organ(_FakeOrgan(name="good", trace=trace))

    spine.drive_cycle({})  # bad raises in perceive → swallowed; good still runs

    assert trace == [("good", "perceive"), ("good", "decide"), ("good", "act")]


# ----------------------------------------------------------------------------
# Composition
# ----------------------------------------------------------------------------


def test_attach_organ_registers_and_attaches() -> None:
    spine = CognitiveSpine(_StubParent("agent-9"))
    fake = _FakeOrgan()

    spine.attach_organ(fake)

    assert spine.has_organs is True
    assert spine.organ_names == ("fake",)
    assert spine.organs == (fake,)
    assert spine.get_organ("fake") is fake
    assert fake.attached is True
    assert fake.parent_id == "agent-9"
    assert fake.organ_id == "agent-9.fake"
    assert fake.attach_count == 1


def test_attach_same_instance_twice_is_idempotent() -> None:
    spine = CognitiveSpine(_StubParent("a"))
    fake = _FakeOrgan()

    spine.attach_organ(fake)
    spine.attach_organ(fake)

    assert spine.organ_names == ("fake",)
    assert fake.attach_count == 1  # attach is idempotent


def test_attach_different_organ_same_name_is_refused() -> None:
    spine = CognitiveSpine(_StubParent("a"))
    first = _FakeOrgan(name="dup")
    second = _FakeOrgan(name="dup")

    spine.attach_organ(first)
    spine.attach_organ(second)  # refused (log-and-degrade) — identity stays 1:1

    assert spine.get_organ("dup") is first
    assert second.attached is False
    assert spine.organ_names == ("dup",)


def test_detach_organ_releases_and_returns() -> None:
    spine = CognitiveSpine(_StubParent("a"))
    fake = _FakeOrgan()
    spine.attach_organ(fake)

    returned = spine.detach_organ("fake")

    assert returned is fake
    assert fake.attached is False
    assert fake.detach_count == 1
    assert spine.has_organs is False
    assert spine.get_organ("fake") is None


def test_detach_unknown_name_returns_none() -> None:
    spine = CognitiveSpine(_StubParent("a"))
    assert spine.detach_organ("nope") is None


def test_detach_all_releases_every_organ() -> None:
    spine = CognitiveSpine(_StubParent("a"))
    a = _FakeOrgan(name="a")
    b = _FakeOrgan(name="b")
    spine.attach_organ(a)
    spine.attach_organ(b)

    spine.detach_all()

    assert spine.has_organs is False
    assert a.attached is False and b.attached is False
    assert a.detach_count == 1 and b.detach_count == 1
    assert spine.organs == ()


def test_detach_all_with_zero_organs_is_noop() -> None:
    spine = CognitiveSpine(_StubParent("a"))
    spine.detach_all()  # no error
    assert spine.has_organs is False


# ----------------------------------------------------------------------------
# Signaling (synchronous in-process observer channel)
# ----------------------------------------------------------------------------


def test_subscribe_and_emit_delivers_synchronously() -> None:
    spine = CognitiveSpine(_StubParent("a"))
    listener = _FakeOrgan(name="listener")
    spine.attach_organ(listener)
    spine.subscribe("arousal", listener)

    spine.emit_signal("arousal", {"level": 0.9})

    assert listener.signals == [("arousal", {"level": 0.9})]


def test_emit_with_no_subscribers_is_noop() -> None:
    spine = CognitiveSpine(_StubParent("a"))
    spine.emit_signal("arousal", {"level": 1.0})  # no subscribers, no error


def test_subscribe_without_on_signal_handler_raises() -> None:
    spine = CognitiveSpine(_StubParent("a"))
    bare = BaseCognitiveOrgan(name="bare")  # base organ has NO on_signal
    with pytest.raises(ValueError):
        spine.subscribe("arousal", bare)


def test_resubscribe_same_organ_is_idempotent() -> None:
    spine = CognitiveSpine(_StubParent("a"))
    listener = _FakeOrgan(name="l")

    spine.subscribe("k", listener)
    spine.subscribe("k", listener)
    spine.emit_signal("k", 1)

    assert listener.signals == [("k", 1)]  # delivered exactly once


def test_emit_isolates_a_raising_subscriber() -> None:
    spine = CognitiveSpine(_StubParent("a"))
    good = _FakeOrgan(name="good")
    bad = _SignalRaiser(name="bad")
    spine.subscribe("k", bad)
    spine.subscribe("k", good)

    spine.emit_signal("k", "p")  # bad raises → swallowed; good still receives

    assert good.signals == [("k", "p")]


def test_detach_unsubscribes_from_signals() -> None:
    spine = CognitiveSpine(_StubParent("a"))
    listener = _FakeOrgan(name="l")
    spine.attach_organ(listener)
    spine.subscribe("k", listener)

    spine.detach_organ("l")
    spine.emit_signal("k", "p")  # listener detached → not delivered

    assert listener.signals == []


def test_organ_emits_signal_during_cycle_subscriber_receives_synchronously() -> None:
    """The acceptance criterion: one organ emits during the cycle and a subscribed organ
    receives it synchronously within the same ``drive_cycle`` call."""
    spine = CognitiveSpine(_StubParent("a"))
    listener = _FakeOrgan(name="attention")
    emitter = _EmitterOrgan(name="valuation", spine=spine, kind="arousal", payload={"level": 0.8})
    spine.attach_organ(emitter)
    spine.attach_organ(listener)
    spine.subscribe("arousal", listener)

    spine.drive_cycle({"turn": 1})

    assert listener.signals == [("arousal", {"level": 0.8})]


# ----------------------------------------------------------------------------
# Governed inlet (single agent-owned mesh boundary — STUB)
# ----------------------------------------------------------------------------


def test_deliver_exogenous_stores_and_forwards_to_subscribers() -> None:
    spine = CognitiveSpine(_StubParent("a"))
    listener = _FakeOrgan(name="attention")
    spine.subscribe(EXOGENOUS_SIGNAL_KIND, listener)
    signal = {"type": "mention", "from": "captain"}

    spine.deliver_exogenous(signal)

    assert spine.last_exogenous == signal
    assert listener.signals == [(EXOGENOUS_SIGNAL_KIND, signal)]


def test_deliver_exogenous_with_no_subscribers_just_stores() -> None:
    spine = CognitiveSpine(_StubParent("a"))
    signal = {"type": "alert"}

    spine.deliver_exogenous(signal)  # no subscribers → just stores, no error

    assert spine.last_exogenous == signal


# ----------------------------------------------------------------------------
# Sovereignty + synchronous-cycle discipline (source / state inspection)
# ----------------------------------------------------------------------------


def test_spine_never_touches_the_intent_bus() -> None:
    import probos.cognitive.spine as spine_mod

    src = inspect.getsource(spine_mod)
    # Prose mentions of "intent bus" in docstrings are fine; assert no IMPORT or CALL.
    assert "from probos.mesh" not in src
    assert "IntentMessage" not in src
    assert "IntentBus" not in src
    assert ".broadcast(" not in src
    assert ".publish(" not in src

    # The spine holds NO bus reference — only the parent, organs, subscribers, and the
    # last exogenous signal.
    spine = CognitiveSpine(_StubParent("a"))
    assert set(vars(spine).keys()) == {"_parent", "_organs", "_subscribers", "_last_exogenous"}


def test_deliver_exogenous_is_the_only_mesh_boundary_and_does_not_reach_the_bus() -> None:
    deliver_src = inspect.getsource(CognitiveSpine.deliver_exogenous)
    assert "await" not in deliver_src
    assert "broadcast" not in deliver_src
    assert "publish" not in deliver_src
    # It routes onto the IN-PROCESS channel only.
    assert "emit_signal" in deliver_src


def test_cycle_path_is_synchronous_no_await() -> None:
    import probos.cognitive.spine as spine_mod

    # No actual ``await`` EXPRESSION anywhere in the module — the discipline-erosion
    # guard (§9). Prose in comments/docstrings is not an ``ast.Await`` node, so the AST
    # walk is the precise check (a substring scan would trip on the documentation).
    tree = ast.parse(inspect.getsource(spine_mod))
    assert [node for node in ast.walk(tree) if isinstance(node, ast.Await)] == []

    # The cycle + boundary methods are NOT coroutines.
    for method_name in (
        "drive_cycle",
        "emit_signal",
        "deliver_exogenous",
        "subscribe",
        "attach_organ",
        "detach_organ",
        "detach_all",
    ):
        method = getattr(CognitiveSpine, method_name)
        assert not asyncio.iscoroutinefunction(method), method_name


def test_drive_cycle_has_no_await_expression() -> None:
    drive_src = textwrap.dedent(inspect.getsource(CognitiveSpine.drive_cycle))
    tree = ast.parse(drive_src)
    assert [node for node in ast.walk(tree) if isinstance(node, ast.Await)] == []
