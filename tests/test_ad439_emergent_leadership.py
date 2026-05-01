"""AD-439: Emergent Leadership Detection tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from probos.cognitive.emergent_leadership import (
    EmergentLeadershipDetector,
    LeadershipDivergence,
    LeadershipReport,
)
from probos.config import EmergentLeadershipConfig
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
    def __init__(self, agent_id: str, agent_type: str, alive: bool = True) -> None:
        self.id = agent_id
        self.agent_type = agent_type
        self.is_alive = alive


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
        agents_for_post: dict[str, list[_FakeAssignment]] | None = None,
    ) -> None:
        self._assignments = assignments
        self._posts = posts
        self._agents_for_post = agents_for_post or {}

    def get_assignment_for_agent(self, agent_type: str) -> _FakeAssignment | None:
        return self._assignments.get(agent_type)

    def get_post(self, post_id: str) -> _FakePost | None:
        return self._posts.get(post_id)

    def get_agents_for_post(self, post_id: str) -> list[_FakeAssignment]:
        return list(self._agents_for_post.get(post_id, []))


class _FakeHebbian:
    def __init__(self, weights: dict[str, dict[str, float]]) -> None:
        self._weights = weights

    def get_agent_weights(self, agent_id: str) -> dict[str, float]:
        return dict(self._weights.get(agent_id, {}))


def test_event_type_leadership_divergence_exists() -> None:
    assert EventType.LEADERSHIP_DIVERGENCE.value == "leadership_divergence"


def test_config_defaults() -> None:
    cfg = EmergentLeadershipConfig()
    assert cfg.enabled is True
    assert cfg.min_weight == 0.10
    assert cfg.min_ratio == 1.5


def test_analyze_no_agents_returns_empty_report() -> None:
    detector = EmergentLeadershipDetector(
        ontology=_FakeOntology({}, {}),
        hebbian=_FakeHebbian({}),
        registry=_FakeRegistry([]),
    )
    report = detector.analyze()
    assert isinstance(report, LeadershipReport)
    assert report.divergences == []
    assert report.sample_size == 0
    assert report.skipped == 0


def test_analyze_aligned_chain_no_divergence() -> None:
    sub = _FakeAgent("sub-1", "engineering_officer")
    sup = _FakeAgent("chief-1", "chief_engineer")
    assignments = {
        "engineering_officer": _FakeAssignment("engineering_officer", "engineering_officer"),
        "chief_engineer": _FakeAssignment("chief_engineer", "chief_engineer"),
    }
    posts = {
        "engineering_officer": _FakePost("engineering_officer", "chief_engineer", []),
        "chief_engineer": _FakePost("chief_engineer", "first_officer", ["engineering_officer"]),
    }
    agents_for_post = {"chief_engineer": [_FakeAssignment("chief_engineer", "chief_engineer")]}
    detector = EmergentLeadershipDetector(
        ontology=_FakeOntology(assignments, posts, agents_for_post),
        hebbian=_FakeHebbian({"sub-1": {"chief-1": 0.9, "peer-X": 0.2}}),
        registry=_FakeRegistry([sub, sup]),
    )
    report = detector.analyze()
    assert report.divergences == []
    assert report.sample_size == 1


def test_analyze_divergent_chain_emits_event() -> None:
    sub = _FakeAgent("sub-1", "engineering_officer")
    sup = _FakeAgent("chief-1", "chief_engineer")
    peer = _FakeAgent("peer-1", "operations_officer")
    assignments = {
        "engineering_officer": _FakeAssignment("engineering_officer", "engineering_officer"),
        "chief_engineer": _FakeAssignment("chief_engineer", "chief_engineer"),
        "operations_officer": _FakeAssignment("operations_officer", "operations_officer"),
    }
    posts = {
        "engineering_officer": _FakePost("engineering_officer", "chief_engineer", []),
        "chief_engineer": _FakePost("chief_engineer", "first_officer", []),
        "operations_officer": _FakePost("operations_officer", "first_officer", []),
    }
    agents_for_post = {"chief_engineer": [_FakeAssignment("chief_engineer", "chief_engineer")]}
    emitted: list[tuple[Any, dict[str, Any]]] = []
    detector = EmergentLeadershipDetector(
        ontology=_FakeOntology(assignments, posts, agents_for_post),
        hebbian=_FakeHebbian({"sub-1": {"peer-1": 0.9, "chief-1": 0.2}}),
        registry=_FakeRegistry([sub, sup, peer]),
        emit_event=lambda et, data: emitted.append((et, data)),
    )
    report = detector.analyze()
    assert len(report.divergences) == 1
    d = report.divergences[0]
    assert d.agent_id == "sub-1"
    assert d.emergent_target_id == "peer-1"
    assert d.designed_superior_post == "chief_engineer"
    assert len(emitted) == 1
    assert emitted[0][0] == EventType.LEADERSHIP_DIVERGENCE


def test_analyze_below_min_weight_skipped() -> None:
    sub = _FakeAgent("sub-1", "engineering_officer")
    assignments = {"engineering_officer": _FakeAssignment("engineering_officer", "engineering_officer")}
    posts = {"engineering_officer": _FakePost("engineering_officer", "chief_engineer", [])}
    detector = EmergentLeadershipDetector(
        ontology=_FakeOntology(assignments, posts),
        hebbian=_FakeHebbian({"sub-1": {"peer": 0.05}}),
        registry=_FakeRegistry([sub]),
        min_weight=0.10,
    )
    report = detector.analyze()
    assert report.divergences == []
    assert report.skipped == 1


def test_analyze_no_reports_to_skipped() -> None:
    sub = _FakeAgent("captain-1", "captain")
    assignments = {"captain": _FakeAssignment("captain", "captain")}
    posts = {"captain": _FakePost("captain", None, [])}
    detector = EmergentLeadershipDetector(
        ontology=_FakeOntology(assignments, posts),
        hebbian=_FakeHebbian({"captain-1": {"someone": 0.9}}),
        registry=_FakeRegistry([sub]),
    )
    report = detector.analyze()
    assert report.divergences == []
    assert report.skipped == 1


def test_analyze_no_assignment_skipped() -> None:
    agent = _FakeAgent("rogue-1", "unmapped_role")
    detector = EmergentLeadershipDetector(
        ontology=_FakeOntology({}, {}),
        hebbian=_FakeHebbian({"rogue-1": {"x": 0.9}}),
        registry=_FakeRegistry([agent]),
    )
    report = detector.analyze()
    assert report.divergences == []
    assert report.skipped == 1


def test_analyze_emit_failure_logs_and_continues(caplog: pytest.LogCaptureFixture) -> None:
    sub = _FakeAgent("sub-1", "engineering_officer")
    sup = _FakeAgent("chief-1", "chief_engineer")
    peer = _FakeAgent("peer-1", "operations_officer")
    assignments = {
        "engineering_officer": _FakeAssignment("engineering_officer", "engineering_officer"),
        "chief_engineer": _FakeAssignment("chief_engineer", "chief_engineer"),
        "operations_officer": _FakeAssignment("operations_officer", "operations_officer"),
    }
    posts = {
        "engineering_officer": _FakePost("engineering_officer", "chief_engineer", []),
        "chief_engineer": _FakePost("chief_engineer", "first_officer", []),
        "operations_officer": _FakePost("operations_officer", "first_officer", []),
    }
    agents_for_post = {"chief_engineer": [_FakeAssignment("chief_engineer", "chief_engineer")]}

    def _broken_emit(et: Any, data: dict[str, Any]) -> None:
        raise RuntimeError("emit broken")

    detector = EmergentLeadershipDetector(
        ontology=_FakeOntology(assignments, posts, agents_for_post),
        hebbian=_FakeHebbian({"sub-1": {"peer-1": 0.9, "chief-1": 0.2}}),
        registry=_FakeRegistry([sub, sup, peer]),
        emit_event=_broken_emit,
    )
    with caplog.at_level("WARNING", logger="probos.cognitive.emergent_leadership"):
        report = detector.analyze()
    assert len(report.divergences) == 1
    assert any("AD-439: emit failed" in rec.message for rec in caplog.records)


def test_endpoint_returns_404_when_disabled() -> None:
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from probos.routers.emergent_leadership import router

    class _RuntimeNoDetector:
        pass

    app = FastAPI()
    app.include_router(router)
    app.state.runtime = _RuntimeNoDetector()
    # Provide get_runtime dependency override
    from probos.routers.deps import get_runtime
    app.dependency_overrides[get_runtime] = lambda: _RuntimeNoDetector()

    with TestClient(app) as client:
        resp = client.get("/api/emergent-leadership")
    assert resp.status_code == 404


def test_endpoint_returns_report_when_enabled() -> None:
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from probos.routers.emergent_leadership import router

    detector = EmergentLeadershipDetector(
        ontology=_FakeOntology({}, {}),
        hebbian=_FakeHebbian({}),
        registry=_FakeRegistry([]),
    )

    class _Runtime:
        emergent_leadership_detector = detector

    app = FastAPI()
    app.include_router(router)
    from probos.routers.deps import get_runtime
    app.dependency_overrides[get_runtime] = lambda: _Runtime()

    with TestClient(app) as client:
        resp = client.get("/api/emergent-leadership")
    assert resp.status_code == 200
    body = resp.json()
    assert body["divergences"] == []
    assert body["sample_size"] == 0
