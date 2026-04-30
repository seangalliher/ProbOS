from __future__ import annotations

from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.activation.task_router import RouteDecision, TaskRouter
from probos.events import EventType
from probos.routers.deps import get_runtime
from probos.routers.system import router


@dataclass(frozen=True)
class _FakePost:
    id: str


@dataclass(frozen=True)
class _FakeAssignment:
    post_id: str
    agent_id: str


class _FakeOntology:
    def __init__(
        self,
        posts: dict[str, list[_FakePost]],
        assignments: list[_FakeAssignment],
    ) -> None:
        self._posts = posts
        self._assignments = assignments

    def get_posts(self, department_id: str | None = None) -> list[_FakePost]:
        if department_id is None:
            return [post for posts in self._posts.values() for post in posts]
        return self._posts.get(department_id, [])

    def get_all_assignments(self) -> list[_FakeAssignment]:
        return list(self._assignments)


class _FakeRuntime:
    def __init__(self, task_router: TaskRouter | None = None) -> None:
        if task_router is not None:
            self._task_router = task_router


def _client_for(runtime: _FakeRuntime) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app)


def test_route_decision_creation() -> None:
    decision = RouteDecision(
        intent_type="threat_analysis",
        strategy="directed",
        department="security",
        agent_ids=["agent-1"],
        reason="Ontology: threat_analysis → security",
    )

    assert decision.intent_type == "threat_analysis"
    assert decision.strategy == "directed"
    assert decision.department == "security"
    assert decision.agent_ids == ["agent-1"]
    assert "security" in decision.reason


def test_default_mappings_exist() -> None:
    task_router = TaskRouter()
    mappings = task_router.list_mappings()

    assert mappings["threat_analysis"] == "security"
    assert mappings["power_diagnostic"] == "engineering"


def test_resolve_known_intent_no_ontology() -> None:
    task_router = TaskRouter()

    decision = task_router.resolve("threat_analysis")

    assert decision.strategy == "broadcast"
    assert decision.department == "security"
    assert decision.agent_ids == []


def test_resolve_unknown_intent() -> None:
    task_router = TaskRouter()

    decision = task_router.resolve("unknown_intent")

    assert decision.strategy == "broadcast"
    assert decision.department is None
    assert decision.agent_ids == []


def test_resolve_directed_with_ontology() -> None:
    ontology = _FakeOntology(
        posts={"security": [_FakePost("security-chief")]},
        assignments=[_FakeAssignment("security-chief", "worf")],
    )
    task_router = TaskRouter(ontology=ontology)

    decision = task_router.resolve("threat_analysis")

    assert decision.strategy == "directed"
    assert decision.department == "security"
    assert decision.agent_ids == ["worf"]


def test_register_custom_mapping() -> None:
    ontology = _FakeOntology(
        posts={"science": [_FakePost("science-officer")]},
        assignments=[_FakeAssignment("science-officer", "data")],
    )
    task_router = TaskRouter(ontology=ontology)

    task_router.register_mapping("custom_intent", "science")
    decision = task_router.resolve("custom_intent")

    assert decision.strategy == "directed"
    assert decision.department == "science"
    assert decision.agent_ids == ["data"]


def test_broadcast_reason_includes_no_mapping() -> None:
    task_router = TaskRouter()

    decision = task_router.resolve("unknown_intent")

    assert "No ontology mapping" in decision.reason


def test_directed_reason_includes_department() -> None:
    ontology = _FakeOntology(
        posts={"engineering": [_FakePost("engineer")]},
        assignments=[_FakeAssignment("engineer", "scotty")],
    )
    task_router = TaskRouter(ontology=ontology)

    decision = task_router.resolve("power_diagnostic")

    assert "engineering" in decision.reason


def test_list_mappings_returns_all() -> None:
    task_router = TaskRouter()

    mappings = task_router.list_mappings()

    assert isinstance(mappings, dict)
    assert len(mappings) >= 13
    assert mappings["scheduling"] == "operations"


def test_task_routed_event_type_exists() -> None:
    assert EventType.TASK_ROUTED.value == "task_routed"


def test_get_task_router_enabled_returns_mappings() -> None:
    client = _client_for(_FakeRuntime(TaskRouter()))

    response = client.get("/api/task-router")
    payload = response.json()

    assert response.status_code == 200
    assert payload["status"] == "active"
    assert payload["mappings"]["threat_analysis"] == "security"


def test_get_task_router_disabled_returns_empty_mappings() -> None:
    client = _client_for(_FakeRuntime())

    response = client.get("/api/task-router")

    assert response.status_code == 200
    assert response.json() == {"status": "disabled", "mappings": {}}
