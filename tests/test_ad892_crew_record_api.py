"""Tests for AD-892 — Crew service record + roster HTTP.

Substrate boundary (the agent registry) uses the REAL ``AgentRegistry`` per
BF-287; the agents registered into it are lightweight stubs that satisfy the
three attributes the registry reads (``id``, ``agent_type``, ``pool``). The
ontology and ACM-side services are explicit hand-written fakes (NOT MagicMock)
so phantom-attribute access raises rather than silently passing.

The roster test deliberately exercises the registry/manifest divergence: a
crew-recognized agent that the ontology manifest does not bill must surface as
``assigned: false`` / ``billet_state: "unbilleted"`` so the manning gap is
visible.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.acm import LifecycleState
from probos.routers.crew import router
from probos.routers.deps import get_runtime
from probos.substrate.registry import AgentRegistry


# ----------------------------------------------------------------------
# Lightweight substrate stubs
# ----------------------------------------------------------------------


@dataclass
class _Agent:
    id: str
    agent_type: str
    pool: str = "crew"
    callsign: str = ""


@dataclass
class _Assignment:
    post_id: str


@dataclass
class _Holder:
    title: str | None
    department: str | None


@dataclass
class _Grant:
    is_restriction: bool


@dataclass
class _Profile:
    all_skills: list[Any] = field(default_factory=list)


@dataclass
class _WorkItem:
    id: str
    title: str
    work_type: str
    status: str
    priority: int


class _FakeOntology:
    """Crew types ⊋ manifest, to model the unbilleted manning gap."""

    def __init__(self) -> None:
        self._manifest = [
            {
                "agent_type": "architect",
                "callsign": "ARCH",
                "department": "engineering",
                "post": "Chief Architect",
                "rank": "commander",
                "agent_id": "agent-arch",
            },
            {
                "agent_type": "scout",
                "callsign": "SCOUT",
                "department": "science",
                "post": "Recon Lead",
                "rank": "lieutenant",
                "agent_id": "agent-scout",
            },
        ]

    def get_crew_agent_types(self) -> set[str]:
        # "ghost" is crew-recognized but absent from the manifest -> unbilleted.
        return {"architect", "scout", "ghost"}

    def get_crew_manifest(self, **_kwargs: Any) -> list[dict[str, Any]]:
        return [dict(e) for e in self._manifest]

    def get_assignment_for_agent(self, agent_type: str) -> _Assignment | None:
        if agent_type == "architect":
            return _Assignment(post_id="post-arch")
        return None


class _FakeAcm:
    def __init__(self) -> None:
        self.consolidated: dict[str, Any] = {}

    async def get_lifecycle_state(self, agent_id: str) -> LifecycleState:
        return LifecycleState.ACTIVE

    async def get_consolidated_profile(
        self, agent_id: str, runtime: Any,
    ) -> dict[str, Any]:
        return {"agent_id": agent_id, "agent_type": "architect", "duties": []}


class _FakeSkillService:
    async def get_profile(self, agent_id: str) -> _Profile:
        return _Profile(all_skills=["s1", "s2", "s3"])


class _FakeToolPerms:
    def get_active_grants_sync(self, agent_id: str) -> list[_Grant]:
        return [_Grant(is_restriction=False), _Grant(is_restriction=True),
                _Grant(is_restriction=False)]


class _FakeWorkItemStore:
    async def list_work_items(self, *, assigned_to: str, limit: int = 50) -> list[_WorkItem]:
        return [
            _WorkItem("w1", "Open task", "build", "open", 3),
            _WorkItem("w2", "Running task", "build", "in_progress", 2),
            _WorkItem("w3", "Closed task", "build", "done", 1),
        ]


class _FakeBilletRegistry:
    def resolve(self, post_id: str) -> _Holder | None:
        return _Holder(title="Chief Architect", department="engineering")

    async def check_qualifications(
        self, billet_id: str, agent_type: str, agent_id: str = "",
    ) -> tuple[bool, list[str]]:
        return (False, ["warp-theory-101"])


class _Runtime:
    def __init__(self, *, with_acm: bool = True) -> None:
        self.registry = AgentRegistry()
        self.ontology = _FakeOntology()
        self.acm = _FakeAcm() if with_acm else None
        self.skill_service = _FakeSkillService()
        self.tool_permission_store = _FakeToolPerms()
        self.work_item_store = _FakeWorkItemStore()
        self.billet_registry = _FakeBilletRegistry()
        self.trust_network = None
        self.callsign_registry = None


async def _register_all(rt: _Runtime) -> None:
    await rt.registry.register(_Agent("agent-arch", "architect", callsign="ARCH"))
    await rt.registry.register(_Agent("agent-scout", "scout", callsign="SCOUT"))
    await rt.registry.register(_Agent("agent-ghost", "ghost", callsign="GHOST"))
    # Non-crew agent — must be excluded from the roster entirely.
    await rt.registry.register(_Agent("agent-hf", "http_fetch", pool="http"))


def _build_runtime(*, with_acm: bool = True) -> _Runtime:
    rt = _Runtime(with_acm=with_acm)
    asyncio.run(_register_all(rt))
    return rt


def _client_for(runtime: _Runtime) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app)


# ----------------------------------------------------------------------
# Roster
# ----------------------------------------------------------------------


def test_roster_wraps_manifest_facets_for_billeted_agent() -> None:
    client = _client_for(_build_runtime())
    body = client.get("/api/crew/roster").json()
    by_type = {e["agent_type"]: e for e in body["crew"]}

    arch = by_type["architect"]
    assert arch["assigned"] is True
    assert arch["billet_state"] == "billeted"
    assert arch["post"] == "Chief Architect"
    assert arch["department"] == "engineering"
    assert arch["rank"] == "commander"


def test_roster_carries_lifecycle_skill_and_tool_counts() -> None:
    client = _client_for(_build_runtime())
    body = client.get("/api/crew/roster").json()
    arch = {e["agent_type"]: e for e in body["crew"]}["architect"]

    assert arch["lifecycle_state"] == "active"
    assert arch["skill_count"] == 3
    assert arch["tool_count"] == 2  # two non-restriction grants


def test_roster_includes_unbilleted_agent_with_assigned_false() -> None:
    client = _client_for(_build_runtime())
    body = client.get("/api/crew/roster").json()
    by_type = {e["agent_type"]: e for e in body["crew"]}

    ghost = by_type["ghost"]
    assert ghost["assigned"] is False
    assert ghost["billet_state"] == "unbilleted"
    assert ghost["post"] is None
    assert ghost["department"] is None
    assert ghost["rank"] is None
    assert ghost["callsign"] == "GHOST"


def test_roster_excludes_non_crew_agents() -> None:
    client = _client_for(_build_runtime())
    body = client.get("/api/crew/roster").json()
    types = {e["agent_type"] for e in body["crew"]}

    assert "http_fetch" not in types
    assert body["count"] == 3


def test_roster_empty_when_registry_absent() -> None:
    rt = _Runtime()
    rt.registry = None  # type: ignore[assignment]
    body = _client_for(rt).get("/api/crew/roster").json()
    assert body == {"crew": [], "count": 0}


# ----------------------------------------------------------------------
# Service record
# ----------------------------------------------------------------------


def test_record_returns_consolidated_profile_with_assignments_and_billet() -> None:
    client = _client_for(_build_runtime())
    body = client.get("/api/crew/agent-arch/record").json()

    assert body["agent_id"] == "agent-arch"
    # active_assignments filtered to open + in_progress (done dropped).
    statuses = {a["status"] for a in body["active_assignments"]}
    assert statuses == {"open", "in_progress"}
    assert len(body["active_assignments"]) == 2

    billet = body["billet"]
    assert billet["billet_id"] == "post-arch"
    assert billet["title"] == "Chief Architect"
    assert billet["qualified"] is False
    assert billet["missing_qualifications"] == ["warp-theory-101"]


def test_record_omits_billet_when_agent_has_no_assignment() -> None:
    client = _client_for(_build_runtime())
    # scout has no assignment in the fake ontology.
    body = client.get("/api/crew/agent-scout/record").json()
    assert "billet" not in body


def test_record_unknown_agent_returns_404() -> None:
    client = _client_for(_build_runtime())
    resp = client.get("/api/crew/nope/record")
    assert resp.status_code == 404


def test_record_returns_503_when_acm_absent() -> None:
    client = _client_for(_build_runtime(with_acm=False))
    resp = client.get("/api/crew/agent-arch/record")
    assert resp.status_code == 503
