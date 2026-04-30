from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.events import EventType
from probos.mesh.disclosure import DEFAULT_CLEARANCES, DisclosureLevel, DisclosureRouter
from probos.routers.deps import get_runtime
from probos.routers.system import router


class _FakeRuntime:
    def __init__(self, disclosure_router: DisclosureRouter | None = None) -> None:
        if disclosure_router is not None:
            self._disclosure_router = disclosure_router


def _client_for(runtime: _FakeRuntime) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app)


def test_disclosure_level_ordering() -> None:
    assert DisclosureLevel.PUBLIC < DisclosureLevel.INTERNAL
    assert DisclosureLevel.INTERNAL < DisclosureLevel.RESTRICTED
    assert DisclosureLevel.RESTRICTED < DisclosureLevel.CONFIDENTIAL
    assert DisclosureLevel.CONFIDENTIAL < DisclosureLevel.CLASSIFIED


def test_default_clearances() -> None:
    assert DEFAULT_CLEARANCES["bridge"] is DisclosureLevel.CONFIDENTIAL
    assert DEFAULT_CLEARANCES["security"] is DisclosureLevel.RESTRICTED
    assert DEFAULT_CLEARANCES["utility"] is DisclosureLevel.PUBLIC


def test_check_recipients_permits_high_clearance() -> None:
    router_instance = DisclosureRouter()

    decisions = router_instance.check_recipients(
        content_level=DisclosureLevel.INTERNAL,
        candidates=["worf"],
        agent_departments={"worf": "security"},
    )

    assert decisions[0].permitted is True
    assert decisions[0].agent_clearance is DisclosureLevel.RESTRICTED


def test_check_recipients_blocks_low_clearance() -> None:
    router_instance = DisclosureRouter()

    decisions = router_instance.check_recipients(
        content_level=DisclosureLevel.RESTRICTED,
        candidates=["utility-1"],
        agent_departments={"utility-1": "utility"},
    )

    assert decisions[0].permitted is False
    assert decisions[0].agent_clearance is DisclosureLevel.PUBLIC


def test_agent_override_takes_precedence() -> None:
    router_instance = DisclosureRouter()

    router_instance.set_agent_clearance("captain", DisclosureLevel.CLASSIFIED)

    assert router_instance.get_clearance("captain", "utility") is DisclosureLevel.CLASSIFIED


def test_filter_permitted_returns_only_allowed() -> None:
    router_instance = DisclosureRouter()

    permitted = router_instance.filter_permitted(
        content_level=DisclosureLevel.RESTRICTED,
        candidates=["worf", "data", "utility-1"],
        agent_departments={
            "worf": "security",
            "data": "bridge",
            "utility-1": "utility",
        },
    )

    assert permitted == ["worf", "data"]


def test_disclosure_decision_reason_text() -> None:
    router_instance = DisclosureRouter()

    decisions = router_instance.check_recipients(
        content_level=DisclosureLevel.RESTRICTED,
        candidates=["worf", "utility-1"],
        agent_departments={"worf": "security", "utility-1": "utility"},
    )

    reasons = {decision.agent_id: decision.reason for decision in decisions}
    assert ">=" in reasons["worf"]
    assert "<" in reasons["utility-1"]


def test_disclosure_filtered_event_exists() -> None:
    assert EventType.DISCLOSURE_FILTERED.value == "disclosure_filtered"


def test_get_disclosure_clearances_enabled_returns_map() -> None:
    client = _client_for(_FakeRuntime(DisclosureRouter()))

    response = client.get("/api/disclosure-clearances")

    assert response.status_code == 200
    assert response.json()["status"] == "active"
    assert response.json()["department_clearances"]["bridge"] == "CONFIDENTIAL"


def test_get_disclosure_clearances_disabled_returns_status() -> None:
    client = _client_for(_FakeRuntime())

    response = client.get("/api/disclosure-clearances")

    assert response.status_code == 200
    assert response.json() == {"status": "disabled"}


def test_get_disclosure_clearances_reflects_department_override() -> None:
    disclosure_router = DisclosureRouter()
    disclosure_router.set_department_clearance("engineering", DisclosureLevel.RESTRICTED)
    client = _client_for(_FakeRuntime(disclosure_router))

    response = client.get("/api/disclosure-clearances")
    payload: dict[str, Any] = response.json()

    assert response.status_code == 200
    assert payload["department_clearances"]["engineering"] == "RESTRICTED"
