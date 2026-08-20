"""AD-581 v1 hybrid dispatch tests.

Covers:
- DepartmentDispatcher (AD-581a + AD-581d): 12 tests
- WorkItemRouter (AD-581a wiring): 8 tests
- Order Protocol decline/refuse (AD-581b): 8 tests
- Config + finalize wirer (AD-581d): 2 tests
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.orders import (
    Order,
    OrderManager,
    OrderState,
    StandingOrderPredicate,
    _default_standing_order_predicate,
)
from probos.config import HybridDispatchConfig
from probos.events import EventType
from probos.mesh.department_dispatcher import (
    DepartmentDispatcher,
    RoutingDecision,
    RoutingMode,
)
from probos.mesh.work_item_router import WorkItemRouter
from probos.types import Priority


# ─── Fakes ────────────────────────────────────────────────────────


@dataclass
class _FakeAssignment:
    agent_type: str
    post_id: str


@dataclass
class _FakePost:
    id: str
    reports_to: str | None
    authority_over: list[str]


class _FakeAgent:
    def __init__(self, agent_id: str, agent_type: str) -> None:
        self.id = agent_id
        self.agent_type = agent_type


class _FakeRegistry:
    def __init__(self, agents: list[_FakeAgent]) -> None:
        self._agents = agents

    def all(self) -> list[_FakeAgent]:
        return list(self._agents)


class _FakeOntology:
    def __init__(
        self,
        assignments: dict[str, _FakeAssignment] | None = None,
        posts: dict[str, _FakePost] | None = None,
        agent_departments: dict[str, str] | None = None,
    ) -> None:
        self._assignments = assignments or {}
        self._posts = posts or {}
        self._agent_departments = agent_departments or {}

    def get_assignment_for_agent(self, agent_type: str) -> _FakeAssignment | None:
        return self._assignments.get(agent_type)

    def get_post(self, post_id: str) -> _FakePost | None:
        return self._posts.get(post_id)

    def get_agent_department(self, agent_type: str) -> str | None:
        return self._agent_departments.get(agent_type)


class _FakeHebbian:
    def __init__(self, weights: dict[tuple[str, str], float] | None = None) -> None:
        self._weights = weights or {}

    def get_weight(
        self, source: str, target: str, rel_type: Any = None,
    ) -> float:
        return float(self._weights.get((source, target), 0.0))


class _FakeDispatcher:
    def __init__(self) -> None:
        self.events: list[Any] = []
        self.raise_on_dispatch = False

    async def dispatch(self, event: Any) -> Any:
        if self.raise_on_dispatch:
            raise RuntimeError("boom")
        self.events.append(event)
        # BF-810: the router reads `.accepted`; `success` was never its field,
        # and the missing attribute was swallowed by on_work_item_created.
        return SimpleNamespace(accepted=1, rejected=0, unroutable=0, agent_ids=[])


# ─── DepartmentDispatcher ─────────────────────────────────────────


def _make_dispatcher(
    *,
    weights: dict[tuple[str, str], float] | None = None,
    ontology: _FakeOntology | None = None,
    hebbian: _FakeHebbian | None = None,
    config: HybridDispatchConfig | None = None,
) -> DepartmentDispatcher:
    return DepartmentDispatcher(
        hebbian_router=hebbian if hebbian is not None else _FakeHebbian(weights),
        ontology=ontology,
        config=config or HybridDispatchConfig(),
    )


def test_route_empty_candidates_returns_broadcast_no_candidates() -> None:
    dispatcher = _make_dispatcher()
    decision = dispatcher.route(intent="i.foo", candidates=[])
    assert decision.mode == RoutingMode.BROADCAST
    assert decision.reason == "broadcast_no_candidates"
    assert decision.agent_id is None


def test_route_no_router_returns_broadcast_no_router() -> None:
    dispatcher = DepartmentDispatcher(
        hebbian_router=None, ontology=None, config=HybridDispatchConfig(),
    )
    decision = dispatcher.route(intent="i.foo", candidates=["a"])
    assert decision.mode == RoutingMode.BROADCAST
    assert decision.reason == "broadcast_no_router"


def test_route_assigned_to_forces_direct() -> None:
    ontology = _FakeOntology(agent_departments={"a-1": "engineering"})
    dispatcher = _make_dispatcher(ontology=ontology)
    wi = SimpleNamespace(assigned_to="a-1")
    decision = dispatcher.route(intent="i.foo", candidates=["other"], work_item=wi)
    assert decision.mode == RoutingMode.DIRECT
    assert decision.agent_id == "a-1"
    assert decision.confidence == 1.0
    assert decision.reason == "direct_assigned_hint"
    assert decision.department_id == "engineering"


def test_route_below_floor_broadcasts() -> None:
    weights = {("i.foo", "a"): 0.01, ("i.foo", "b"): 0.005}
    dispatcher = _make_dispatcher(weights=weights)
    decision = dispatcher.route(intent="i.foo", candidates=["a", "b"])
    assert decision.mode == RoutingMode.BROADCAST
    assert decision.reason == "broadcast_below_floor"


def test_route_below_threshold_broadcasts() -> None:
    weights = {("i.foo", "a"): 0.2, ("i.foo", "b"): 0.1}
    dispatcher = _make_dispatcher(weights=weights)
    decision = dispatcher.route(intent="i.foo", candidates=["a", "b"])
    assert decision.mode == RoutingMode.BROADCAST
    assert decision.reason == "broadcast_below_threshold"
    assert decision.confidence == pytest.approx(0.2)


def test_route_no_margin_broadcasts() -> None:
    weights = {("i.foo", "a"): 0.6, ("i.foo", "b"): 0.59}
    dispatcher = _make_dispatcher(weights=weights)
    decision = dispatcher.route(intent="i.foo", candidates=["a", "b"])
    assert decision.mode == RoutingMode.BROADCAST
    assert decision.reason == "broadcast_no_margin"


def test_route_high_confidence_direct() -> None:
    weights = {("i.foo", "a"): 0.8, ("i.foo", "b"): 0.2}
    dispatcher = _make_dispatcher(weights=weights)
    decision = dispatcher.route(intent="i.foo", candidates=["a", "b"])
    assert decision.mode == RoutingMode.DIRECT
    assert decision.agent_id == "a"
    assert decision.reason == "direct_high_confidence"
    assert decision.runner_up_weight == pytest.approx(0.2)


def test_route_is_pure() -> None:
    weights = {("i.foo", "a"): 0.8, ("i.foo", "b"): 0.2}
    dispatcher = _make_dispatcher(weights=weights)
    d1 = dispatcher.route(intent="i.foo", candidates=["a", "b"])
    d2 = dispatcher.route(intent="i.foo", candidates=["a", "b"])
    assert d1 == d2


def test_route_populates_department_id() -> None:
    ontology = _FakeOntology(agent_departments={"a": "ops"})
    weights = {("i.foo", "a"): 0.8, ("i.foo", "b"): 0.2}
    dispatcher = _make_dispatcher(weights=weights, ontology=ontology)
    decision = dispatcher.route(intent="i.foo", candidates=["a", "b"])
    assert decision.department_id == "ops"


def test_route_department_id_none_when_ontology_missing() -> None:
    weights = {("i.foo", "a"): 0.8, ("i.foo", "b"): 0.2}
    dispatcher = _make_dispatcher(weights=weights, ontology=None)
    decision = dispatcher.route(intent="i.foo", candidates=["a", "b"])
    assert decision.department_id is None
    assert decision.mode == RoutingMode.DIRECT


def test_record_outcome_and_get_success_rate_round_trip() -> None:
    cfg = HybridDispatchConfig(success_rate_window=10, min_samples_for_routing=3)
    dispatcher = _make_dispatcher(config=cfg)
    for _ in range(8):
        dispatcher.record_outcome(intent="i.x", agent_id="a", success=True)
    for _ in range(2):
        dispatcher.record_outcome(intent="i.x", agent_id="a", success=False)
    rate, n = dispatcher.get_success_rate(intent="i.x", agent_id="a")
    assert n == 10
    assert rate == pytest.approx(0.8)


def test_get_success_rate_below_min_samples_returns_zero() -> None:
    cfg = HybridDispatchConfig(min_samples_for_routing=5)
    dispatcher = _make_dispatcher(config=cfg)
    dispatcher.record_outcome(intent="i.x", agent_id="a", success=True)
    dispatcher.record_outcome(intent="i.x", agent_id="a", success=True)
    rate, n = dispatcher.get_success_rate(intent="i.x", agent_id="a")
    assert n == 2
    assert rate == 0.0


# ─── WorkItemRouter ────────────────────────────────────────────────


def _make_router(
    *,
    dispatcher: _FakeDispatcher | None = None,
    dept_dispatcher: DepartmentDispatcher | None = None,
    registry: _FakeRegistry | None = None,
    config: HybridDispatchConfig | None = None,
    emit_event: Any | None = None,
) -> WorkItemRouter:
    return WorkItemRouter(
        dispatcher=dispatcher or _FakeDispatcher(),
        department_dispatcher=dept_dispatcher or _make_dispatcher(),
        registry=registry or _FakeRegistry([]),
        config=config or HybridDispatchConfig(),
        emit_event=emit_event,
    )


def test_is_dispatchable_tag_match() -> None:
    router = _make_router()
    assert router.is_dispatchable({"tags": ["consultation"]}) is True


def test_is_dispatchable_metadata_flag() -> None:
    router = _make_router()
    assert router.is_dispatchable({"metadata": {"dispatchable": True}}) is True


def test_is_dispatchable_neither_returns_false() -> None:
    router = _make_router()
    assert router.is_dispatchable({"tags": ["misc"], "metadata": {}}) is False


def test_on_work_item_created_skips_non_dispatchable() -> None:
    fake_d = _FakeDispatcher()
    router = _make_router(dispatcher=fake_d)
    event = {
        "type": "work_item_created",
        "data": {"work_item": {"id": "w1", "tags": ["misc"], "work_type": "duty"}},
        "timestamp": 0.0,
    }
    asyncio.run(router.on_work_item_created(event))
    assert fake_d.events == []


def test_on_work_item_created_assigned_to_dispatches_direct() -> None:
    fake_d = _FakeDispatcher()
    emitted: list[tuple[Any, dict[str, Any]]] = []
    router = _make_router(
        dispatcher=fake_d,
        emit_event=lambda et, data: emitted.append((et, data)),
    )
    event = {
        "type": "work_item_created",
        "data": {"work_item": {
            "id": "w1",
            "tags": ["consultation"],
            "work_type": "duty",
            "assigned_to": "alice",
            "priority": 3,
        }},
        "timestamp": 0.0,
    }
    asyncio.run(router.on_work_item_created(event))
    assert len(fake_d.events) == 1
    te = fake_d.events[0]
    assert te.target.agent_id == "alice"
    assert any(et == EventType.HYBRID_DISPATCH_DIRECT for et, _ in emitted)


def test_on_work_item_created_low_hebbian_broadcasts() -> None:
    fake_d = _FakeDispatcher()
    registry = _FakeRegistry([_FakeAgent("a", "ta"), _FakeAgent("b", "tb")])
    dept = _make_dispatcher()  # no weights -> below floor
    emitted: list[tuple[Any, dict[str, Any]]] = []
    router = _make_router(
        dispatcher=fake_d,
        dept_dispatcher=dept,
        registry=registry,
        emit_event=lambda et, data: emitted.append((et, data)),
    )
    event = {
        "type": "work_item_created",
        "data": {"work_item": {
            "id": "w1",
            "tags": ["consultation"],
            "work_type": "duty",
            "priority": 3,
        }},
        "timestamp": 0.0,
    }
    asyncio.run(router.on_work_item_created(event))
    assert len(fake_d.events) == 1
    assert fake_d.events[0].target.broadcast is True
    assert any(et == EventType.HYBRID_DISPATCH_BROADCAST for et, _ in emitted)


def test_on_work_item_created_swallows_dispatcher_exception() -> None:
    fake_d = _FakeDispatcher()
    fake_d.raise_on_dispatch = True
    router = _make_router(dispatcher=fake_d)
    event = {
        "type": "work_item_created",
        "data": {"work_item": {
            "id": "w1",
            "tags": ["consultation"],
            "work_type": "duty",
            "assigned_to": "alice",
            "priority": 3,
        }},
        "timestamp": 0.0,
    }
    # Must not raise.
    asyncio.run(router.on_work_item_created(event))


def test_priority_from_int_mapping() -> None:
    assert WorkItemRouter._priority_from_int(1) == Priority.CRITICAL
    assert WorkItemRouter._priority_from_int(3) == Priority.NORMAL
    assert WorkItemRouter._priority_from_int(5) == Priority.LOW


# ─── Order Protocol decline / refuse ──────────────────────────────


def _build_chain() -> tuple[_FakeOntology, _FakeRegistry]:
    chief = _FakeAgent("chief-1", "chief_engineer")
    sub = _FakeAgent("sub-1", "engineering_officer")
    assignments = {
        "chief_engineer": _FakeAssignment("chief_engineer", "chief_engineer"),
        "engineering_officer": _FakeAssignment("engineering_officer", "engineering_officer"),
    }
    posts = {
        "chief_engineer": _FakePost(
            "chief_engineer", "first_officer", ["engineering_officer"],
        ),
        "engineering_officer": _FakePost("engineering_officer", "chief_engineer", []),
    }
    return _FakeOntology(assignments, posts), _FakeRegistry([chief, sub])


def _issue(mgr: OrderManager) -> Order:
    order = mgr.issue_order(
        from_agent_id="chief-1",
        to_post_id="engineering_officer",
        directive="Run diagnostics",
    )
    assert order is not None
    return order


def test_order_state_decline_refuse_values() -> None:
    assert OrderState.DECLINED.value == "declined"
    assert OrderState.REFUSED.value == "refused"


def test_event_type_decline_refuse_values() -> None:
    assert EventType.ORDER_DECLINED.value == "order_declined"
    assert EventType.ORDER_REFUSED.value == "order_refused"


def test_decline_transitions_pending_to_declined() -> None:
    ontology, registry = _build_chain()
    emitted: list[tuple[Any, dict[str, Any]]] = []
    mgr = OrderManager(
        ontology=ontology, registry=registry,
        emit_event=lambda et, data: emitted.append((et, data)),
    )
    order = _issue(mgr)
    assert mgr.decline(order.id, "sub-1", reason="overcapacity") is True
    updated = mgr._orders[order.id]
    assert updated.state == OrderState.DECLINED
    assert updated.declined_by == "sub-1"
    assert updated.decline_reason == "overcapacity"
    assert any(et == EventType.ORDER_DECLINED for et, _ in emitted)


def test_decline_empty_reason_returns_false() -> None:
    ontology, registry = _build_chain()
    mgr = OrderManager(ontology=ontology, registry=registry)
    order = _issue(mgr)
    assert mgr.decline(order.id, "sub-1", reason="   ") is False
    assert mgr._orders[order.id].state == OrderState.PENDING


def test_decline_wrong_post_holder_returns_false() -> None:
    ontology, registry = _build_chain()
    mgr = OrderManager(ontology=ontology, registry=registry)
    order = _issue(mgr)
    # chief-1 is not the post holder for engineering_officer.
    assert mgr.decline(order.id, "chief-1", reason="nope") is False
    assert mgr._orders[order.id].state == OrderState.PENDING


def test_decline_invokes_reassignment_callback_swallows_exception() -> None:
    ontology, registry = _build_chain()
    mgr = OrderManager(ontology=ontology, registry=registry)
    order = _issue(mgr)
    calls: list[tuple[Any, ...]] = []

    def _cb(*, order: Order, declined_by: str, reason: str) -> None:
        calls.append((order.id, declined_by, reason))
        raise RuntimeError("cb fail")

    mgr.register_reassignment_callback(order.id, _cb)
    assert mgr.decline(order.id, "sub-1", reason="busy") is True
    assert calls == [(order.id, "sub-1", "busy")]


def test_refuse_with_explicit_violation_transitions() -> None:
    ontology, registry = _build_chain()
    emitted: list[tuple[Any, dict[str, Any]]] = []
    mgr = OrderManager(
        ontology=ontology, registry=registry,
        emit_event=lambda et, data: emitted.append((et, data)),
    )
    order = _issue(mgr)
    assert mgr.refuse(order.id, "sub-1", violation="prime_directive") is True
    updated = mgr._orders[order.id]
    assert updated.state == OrderState.REFUSED
    assert updated.refuse_violation == "prime_directive"
    assert any(et == EventType.ORDER_REFUSED for et, _ in emitted)


def test_refuse_default_predicate_returns_false_custom_predicate_transitions() -> None:
    ontology, registry = _build_chain()
    # Default predicate path: no violation -> False.
    mgr_default = OrderManager(ontology=ontology, registry=registry)
    o1 = _issue(mgr_default)
    assert mgr_default.refuse(o1.id, "sub-1") is False
    assert mgr_default._orders[o1.id].state == OrderState.PENDING

    # Custom predicate that flags violation -> True with predicate reason.
    def _pred(*, order: Order, by_agent_id: str) -> tuple[bool, str]:
        return True, "fed_violation"

    mgr_custom = OrderManager(
        ontology=ontology, registry=registry, standing_order_predicate=_pred,
    )
    o2 = _issue(mgr_custom)
    assert mgr_custom.refuse(o2.id, "sub-1") is True
    assert mgr_custom._orders[o2.id].refuse_violation == "fed_violation"


def test_default_standing_order_predicate_returns_no_violation() -> None:
    order = Order(
        id="x", from_agent_id="a", from_post_id="p1", to_post_id="p2",
        directive="d", issued_at=time.time(), expires_at=time.time() + 60,
    )
    violates, reason = _default_standing_order_predicate(order=order, by_agent_id="b")
    assert violates is False
    assert reason == ""
    # Protocol class is exported.
    assert StandingOrderPredicate is not None


# ─── Config + finalize wirer ──────────────────────────────────────


def test_hybrid_dispatch_config_defaults_and_validators() -> None:
    cfg = HybridDispatchConfig()
    assert cfg.enabled is True
    assert cfg.confidence_threshold == 0.4
    assert cfg.confidence_margin == 0.05
    assert cfg.min_hebbian_weight == 0.05
    assert cfg.success_rate_window == 50
    assert cfg.min_samples_for_routing == 3
    assert cfg.dispatchable_tags == ["consultation"]
    with pytest.raises(Exception):
        HybridDispatchConfig(confidence_threshold=2.0)
    with pytest.raises(Exception):
        HybridDispatchConfig(success_rate_window=0)


def test_wire_hybrid_dispatch_skip_and_success() -> None:
    from probos.config import SystemConfig
    from probos.startup.finalize import _wire_hybrid_dispatch

    config = SystemConfig()

    # Skip path: hebbian_router missing.
    rt_skip = SimpleNamespace(
        hebbian_router=None,
        ontology=object(),
        dispatcher=object(),
        registry=_FakeRegistry([]),
        emit_event=None,
    )
    assert _wire_hybrid_dispatch(runtime=rt_skip, config=config) is False

    # Success path: all four deps present.
    listener_calls: list[Any] = []

    def _add_listener(fn: Any, event_types: Any = None) -> None:
        listener_calls.append((fn, event_types))

    rt_ok = SimpleNamespace(
        hebbian_router=_FakeHebbian(),
        ontology=_FakeOntology(),
        dispatcher=_FakeDispatcher(),
        registry=_FakeRegistry([]),
        emit_event=None,
        add_event_listener=_add_listener,
    )
    assert _wire_hybrid_dispatch(runtime=rt_ok, config=config) is True
    assert isinstance(rt_ok.department_dispatcher, DepartmentDispatcher)
    assert isinstance(rt_ok.work_item_router, WorkItemRouter)
    assert listener_calls and listener_calls[0][1] == ["work_item_created"]
