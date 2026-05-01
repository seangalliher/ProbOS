"""AD-440: Chain of Command Delegation tests."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import pytest

from probos.cognitive.orders import (
    Order,
    OrderManager,
    OrderState,
)
from probos.config import OrdersConfig
from probos.events import EventType


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
        assignments: dict[str, _FakeAssignment],
        posts: dict[str, _FakePost],
    ) -> None:
        self._assignments = assignments
        self._posts = posts

    def get_assignment_for_agent(self, agent_type: str) -> _FakeAssignment | None:
        return self._assignments.get(agent_type)

    def get_post(self, post_id: str) -> _FakePost | None:
        return self._posts.get(post_id)


def _build_chief_chain() -> tuple[_FakeOntology, _FakeRegistry]:
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


def test_event_type_order_issued_exists() -> None:
    assert EventType.ORDER_ISSUED.value == "order_issued"


def test_event_type_order_rejected_exists() -> None:
    assert EventType.ORDER_REJECTED.value == "order_rejected"


def test_event_type_order_acknowledged_exists() -> None:
    assert EventType.ORDER_ACKNOWLEDGED.value == "order_acknowledged"


def test_orders_config_defaults() -> None:
    cfg = OrdersConfig()
    assert cfg.enabled is True
    assert cfg.max_active_per_post == 8
    assert cfg.default_ttl_seconds == 3600.0


def test_issue_order_in_chain_succeeds() -> None:
    ontology, registry = _build_chief_chain()
    emitted: list[tuple[Any, dict[str, Any]]] = []
    mgr = OrderManager(
        ontology=ontology, registry=registry,
        emit_event=lambda et, data: emitted.append((et, data)),
    )
    order = mgr.issue_order(
        from_agent_id="chief-1",
        to_post_id="engineering_officer",
        directive="Run diagnostics",
    )
    assert order is not None
    assert order.from_post_id == "chief_engineer"
    assert order.to_post_id == "engineering_officer"
    assert order.state == OrderState.PENDING
    assert any(et == EventType.ORDER_ISSUED for et, _ in emitted)


def test_issue_order_out_of_chain_rejected() -> None:
    ontology, registry = _build_chief_chain()
    emitted: list[tuple[Any, dict[str, Any]]] = []
    mgr = OrderManager(
        ontology=ontology, registry=registry,
        emit_event=lambda et, data: emitted.append((et, data)),
    )
    # engineering_officer attempts to order chief_engineer -> out_of_chain
    order = mgr.issue_order(
        from_agent_id="sub-1",
        to_post_id="chief_engineer",
        directive="No",
    )
    assert order is None
    rej = [d for et, d in emitted if et == EventType.ORDER_REJECTED]
    assert len(rej) == 1
    assert rej[0]["reason"] == "out_of_chain"


def test_issue_order_empty_directive_rejected() -> None:
    ontology, registry = _build_chief_chain()
    emitted: list[tuple[Any, dict[str, Any]]] = []
    mgr = OrderManager(
        ontology=ontology, registry=registry,
        emit_event=lambda et, data: emitted.append((et, data)),
    )
    order = mgr.issue_order(
        from_agent_id="chief-1",
        to_post_id="engineering_officer",
        directive="   ",
    )
    assert order is None
    rej = [d for et, d in emitted if et == EventType.ORDER_REJECTED]
    assert rej[0]["reason"] == "empty_directive"


def test_issue_order_unknown_issuer_rejected() -> None:
    ontology, registry = _build_chief_chain()
    emitted: list[tuple[Any, dict[str, Any]]] = []
    mgr = OrderManager(
        ontology=ontology, registry=registry,
        emit_event=lambda et, data: emitted.append((et, data)),
    )
    order = mgr.issue_order(
        from_agent_id="ghost",
        to_post_id="engineering_officer",
        directive="hi",
    )
    assert order is None
    rej = [d for et, d in emitted if et == EventType.ORDER_REJECTED]
    assert rej[0]["reason"] == "unknown_issuer"


def test_queue_full_rejection() -> None:
    ontology, registry = _build_chief_chain()
    emitted: list[tuple[Any, dict[str, Any]]] = []
    mgr = OrderManager(
        ontology=ontology, registry=registry,
        emit_event=lambda et, data: emitted.append((et, data)),
        max_active_per_post=2,
    )
    for i in range(2):
        assert mgr.issue_order(
            from_agent_id="chief-1", to_post_id="engineering_officer",
            directive=f"task {i}",
        ) is not None
    blocked = mgr.issue_order(
        from_agent_id="chief-1", to_post_id="engineering_officer", directive="extra",
    )
    assert blocked is None
    rej = [d for et, d in emitted if et == EventType.ORDER_REJECTED]
    assert any(r["reason"] == "queue_full" for r in rej)


def test_acknowledge_by_correct_subordinate_succeeds() -> None:
    ontology, registry = _build_chief_chain()
    mgr = OrderManager(ontology=ontology, registry=registry)
    order = mgr.issue_order(
        from_agent_id="chief-1", to_post_id="engineering_officer",
        directive="x",
    )
    assert order is not None
    assert mgr.acknowledge(order.id, "sub-1") is True
    fresh = mgr.all_orders()[0]
    assert fresh.state == OrderState.ACKNOWLEDGED
    assert fresh.acknowledged_by == "sub-1"


def test_acknowledge_by_wrong_agent_fails() -> None:
    ontology, registry = _build_chief_chain()
    mgr = OrderManager(ontology=ontology, registry=registry)
    order = mgr.issue_order(
        from_agent_id="chief-1", to_post_id="engineering_officer",
        directive="x",
    )
    assert order is not None
    # Chief tries to ack their own order — wrong post_id
    assert mgr.acknowledge(order.id, "chief-1") is False


def test_list_active_filters_by_post() -> None:
    chief = _FakeAgent("chief-1", "chief_engineer")
    sub = _FakeAgent("sub-1", "engineering_officer")
    sub2 = _FakeAgent("sub-2", "builder_officer")
    assignments = {
        "chief_engineer": _FakeAssignment("chief_engineer", "chief_engineer"),
        "engineering_officer": _FakeAssignment("engineering_officer", "engineering_officer"),
        "builder_officer": _FakeAssignment("builder_officer", "builder_officer"),
    }
    posts = {
        "chief_engineer": _FakePost(
            "chief_engineer", "first_officer",
            ["engineering_officer", "builder_officer"],
        ),
        "engineering_officer": _FakePost("engineering_officer", "chief_engineer", []),
        "builder_officer": _FakePost("builder_officer", "chief_engineer", []),
    }
    ontology = _FakeOntology(assignments, posts)
    registry = _FakeRegistry([chief, sub, sub2])
    mgr = OrderManager(ontology=ontology, registry=registry)
    mgr.issue_order(from_agent_id="chief-1", to_post_id="engineering_officer", directive="A")
    mgr.issue_order(from_agent_id="chief-1", to_post_id="builder_officer", directive="B")
    eng = mgr.list_active_for_post("engineering_officer")
    bld = mgr.list_active_for_post("builder_officer")
    assert len(eng) == 1
    assert len(bld) == 1
    assert eng[0].directive == "A"
    assert bld[0].directive == "B"


def test_ttl_expiration_marks_expired() -> None:
    ontology, registry = _build_chief_chain()
    mgr = OrderManager(
        ontology=ontology, registry=registry,
        default_ttl=0.05,
    )
    order = mgr.issue_order(
        from_agent_id="chief-1", to_post_id="engineering_officer", directive="x",
    )
    assert order is not None
    time.sleep(0.15)
    all_orders = mgr.all_orders()
    assert len(all_orders) == 1
    assert all_orders[0].state == OrderState.EXPIRED


def test_issuer_resolution_failed_when_assignment_missing() -> None:
    chief = _FakeAgent("chief-1", "chief_engineer")
    # Registry has the agent but ontology has no assignment for chief_engineer
    ontology = _FakeOntology({}, {})
    registry = _FakeRegistry([chief])
    emitted: list[tuple[Any, dict[str, Any]]] = []
    mgr = OrderManager(
        ontology=ontology, registry=registry,
        emit_event=lambda et, data: emitted.append((et, data)),
    )
    order = mgr.issue_order(
        from_agent_id="chief-1", to_post_id="engineering_officer", directive="x",
    )
    assert order is None
    rej = [d for et, d in emitted if et == EventType.ORDER_REJECTED]
    assert rej[0]["reason"] == "issuer_resolution_failed"


def test_list_active_for_agent() -> None:
    ontology, registry = _build_chief_chain()
    mgr = OrderManager(ontology=ontology, registry=registry)
    mgr.issue_order(
        from_agent_id="chief-1", to_post_id="engineering_officer", directive="A",
    )
    pending = mgr.list_active_for_agent("sub-1")
    assert len(pending) == 1
    assert pending[0].directive == "A"


def test_order_dataclass_shape() -> None:
    order = Order(
        id="x",
        from_agent_id="a",
        from_post_id="b",
        to_post_id="c",
        directive="d",
        issued_at=0.0,
        expires_at=1.0,
    )
    assert order.state == OrderState.PENDING
    assert order.metadata == {}
