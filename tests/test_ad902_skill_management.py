"""AD-902 — Per-agent developmental (T3) skill management HTTP surface.

BF-287 discipline: a real ``AgentSkillService`` (tmp-file SQLite) and a real
``SkillRegistry`` — no MagicMock at the substrate boundary. The services run in
the test coroutine's event loop; the suite drives the crew router in-process via
``httpx.ASGITransport``/``AsyncClient`` with a small runtime stub that exposes
the real ``skill_service`` and ``skill_registry`` as attributes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from probos.routers import crew as crew_router
from probos.routers.deps import get_runtime
from probos.skill_framework import (
    AgentSkillService,
    ProficiencyLevel,
    SkillCategory,
    SkillDefinition,
    SkillRegistry,
)


@dataclass
class _Runtime:
    skill_service: Any = None
    skill_registry: Any = None


async def _make_services(tmp_path: Any) -> tuple[SkillRegistry, AgentSkillService]:
    registry = SkillRegistry(db_path=str(tmp_path / "skills.db"))
    await registry.start()
    await registry.register_skill(
        SkillDefinition(
            skill_id="basic", name="Basic Skill",
            category=SkillCategory.ACQUIRED, origin="acquired",
        )
    )
    await registry.register_skill(
        SkillDefinition(
            skill_id="advanced", name="Advanced Skill",
            category=SkillCategory.ACQUIRED, origin="acquired",
            prerequisites=["basic"],
        )
    )
    service = AgentSkillService(
        db_path=str(tmp_path / "agent_skills.db"), registry=registry,
    )
    await service.start()
    return registry, service


def _client_for(runtime: _Runtime) -> AsyncClient:
    app = FastAPI()
    app.include_router(crew_router.router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture
async def services(tmp_path: Any):
    registry, service = await _make_services(tmp_path)
    try:
        yield registry, service
    finally:
        await service.stop()
        await registry.stop()


# ----------------------------------------------------------------------
# Section 1 — suspend_skill verb (real service, no HTTP)
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_suspend_skill_toggles_and_is_reversible(services: Any) -> None:
    registry, service = services
    await service.acquire_skill("a1", "basic", proficiency=ProficiencyLevel.APPLY)
    await service.update_proficiency(
        "a1", "basic", ProficiencyLevel.ENABLE, notes="assessed",
    )

    suspended = await service.suspend_skill("a1", "basic", suspended=True)
    assert suspended is not None
    assert suspended.suspended is True
    # Proficiency + assessment_history preserved across suspension.
    assert suspended.proficiency == ProficiencyLevel.ENABLE
    assert len(suspended.assessment_history) >= 1

    reinstated = await service.suspend_skill("a1", "basic", suspended=False)
    assert reinstated is not None
    assert reinstated.suspended is False
    assert reinstated.proficiency == ProficiencyLevel.ENABLE
    assert len(reinstated.assessment_history) >= 1


@pytest.mark.asyncio
async def test_suspend_skill_unheld_returns_none(services: Any) -> None:
    _registry, service = services
    result = await service.suspend_skill("ghost", "basic", suspended=True)
    assert result is None


# ----------------------------------------------------------------------
# Section 2 — crew skill endpoints (real services, ASGI)
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_skills_lists_records_with_name_and_category(services: Any) -> None:
    _registry, service = services
    await service.acquire_skill("a1", "basic", proficiency=ProficiencyLevel.APPLY)
    await service.suspend_skill("a1", "basic", suspended=True)
    runtime = _Runtime(skill_service=service, skill_registry=_registry)
    async with _client_for(runtime) as client:
        resp = await client.get("/api/crew/a1/skills")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    record = data["skills"][0]
    assert record["skill_id"] == "basic"
    assert record["name"] == "Basic Skill"
    assert record["category"] == "acquired"
    # Suspended records are included so the console can offer reinstatement.
    assert record["suspended"] is True


@pytest.mark.asyncio
async def test_get_skills_honest_degrades_without_service(services: Any) -> None:
    runtime = _Runtime(skill_service=None, skill_registry=None)
    async with _client_for(runtime) as client:
        resp = await client.get("/api/crew/a1/skills")
    assert resp.status_code == 200
    assert resp.json() == {"agent_id": "a1", "skills": [], "count": 0}


@pytest.mark.asyncio
async def test_post_skills_acquires_at_requested_level(services: Any) -> None:
    registry, service = services
    runtime = _Runtime(skill_service=service, skill_registry=registry)
    async with _client_for(runtime) as client:
        resp = await client.post(
            "/api/crew/a1/skills", json={"skill_id": "basic", "proficiency": 3},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["skill_id"] == "basic"
    assert data["proficiency"] == 3
    record = await service._get_record("a1", "basic")
    assert record is not None
    assert record.proficiency == ProficiencyLevel.APPLY


@pytest.mark.asyncio
async def test_post_skills_error_cases(services: Any) -> None:
    registry, service = services
    runtime = _Runtime(skill_service=service, skill_registry=registry)
    async with _client_for(runtime) as client:
        # Unknown skill → 404.
        unknown = await client.post("/api/crew/a1/skills", json={"skill_id": "nope"})
        assert unknown.status_code == 404
        # Missing skill_id → 400.
        missing = await client.post("/api/crew/a1/skills", json={})
        assert missing.status_code == 400
        # Unmet prerequisite → 400 with the service message.
        prereq = await client.post("/api/crew/a1/skills", json={"skill_id": "advanced"})
        assert prereq.status_code == 400
        assert "Prerequisite" in prereq.json()["detail"]


@pytest.mark.asyncio
async def test_patch_skills_relevel_suspend_reinstate(services: Any) -> None:
    registry, service = services
    await service.acquire_skill("a1", "basic", proficiency=ProficiencyLevel.FOLLOW)
    runtime = _Runtime(skill_service=service, skill_registry=registry)
    async with _client_for(runtime) as client:
        # Re-level happy path.
        leveled = await client.patch(
            "/api/crew/a1/skills/basic", json={"proficiency": 4},
        )
        assert leveled.status_code == 200
        assert leveled.json()["proficiency"] == 4
        # Unheld skill → 404.
        absent = await client.patch(
            "/api/crew/a1/skills/advanced", json={"proficiency": 2},
        )
        assert absent.status_code == 404
        # Suspend via PATCH.
        suspended = await client.patch(
            "/api/crew/a1/skills/basic", json={"suspended": True},
        )
        assert suspended.status_code == 200
        assert suspended.json()["suspended"] is True
        # Reinstate via PATCH.
        reinstated = await client.patch(
            "/api/crew/a1/skills/basic", json={"suspended": False},
        )
        assert reinstated.status_code == 200
        assert reinstated.json()["suspended"] is False
        # Neither field → 400.
        empty = await client.patch("/api/crew/a1/skills/basic", json={})
        assert empty.status_code == 400


@pytest.mark.asyncio
async def test_delete_skills_suspends_softly(services: Any) -> None:
    registry, service = services
    await service.acquire_skill("a1", "basic", proficiency=ProficiencyLevel.APPLY)
    runtime = _Runtime(skill_service=service, skill_registry=registry)
    async with _client_for(runtime) as client:
        # Suspend an unheld skill → 404.
        absent = await client.delete("/api/crew/a1/skills/advanced")
        assert absent.status_code == 404
        # Soft-suspend the held skill.
        deleted = await client.delete("/api/crew/a1/skills/basic")
        assert deleted.status_code == 200
        assert deleted.json() == {
            "suspended": True, "agent_id": "a1", "skill_id": "basic",
        }
        # The record is still present, just suspended.
        listing = await client.get("/api/crew/a1/skills")
        records = listing.json()["skills"]
        assert len(records) == 1
        assert records[0]["suspended"] is True
