"""AD-895: Skill Library CRUD — delete verb, validated create/update, HTTP surface.

Tests use REAL ``SkillRegistry`` / ``AgentSkillService`` instances backed by a
temporary SQLite file (BF-287: no MagicMock at the substrate boundary). HTTP
tests drive the FastAPI app through a lifespan context manager so the aiosqlite
connections live in the TestClient's event loop (AD-894 cross-loop lesson).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.routers import skills as skills_router
from probos.routers.deps import get_runtime
from probos.skill_framework import (
    AgentSkillService,
    BUILTIN_PCCS,
    SkillCategory,
    SkillDefinition,
    SkillRegistry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_skill(skill_id: str, *, prerequisites: list[str] | None = None) -> SkillDefinition:
    return SkillDefinition(
        skill_id=skill_id,
        name=skill_id.replace("_", " ").title(),
        category=SkillCategory.ACQUIRED,
        description="test skill",
        domain="*",
        prerequisites=list(prerequisites or []),
        origin="designed",
    )


@dataclass
class _Runtime:
    skill_registry: SkillRegistry | None
    skill_service: AgentSkillService | None


def _client_for(runtime: _Runtime) -> TestClient:
    @asynccontextmanager
    async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if runtime.skill_registry is not None:
            await runtime.skill_registry.start()
        if runtime.skill_service is not None:
            await runtime.skill_service.start()
        yield
        if runtime.skill_service is not None:
            await runtime.skill_service.stop()
        if runtime.skill_registry is not None:
            await runtime.skill_registry.stop()

    app = FastAPI(lifespan=_lifespan)
    app.include_router(skills_router.router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app)


# ---------------------------------------------------------------------------
# Registry-level: create / update / delete / validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_list_round_trip(tmp_path) -> None:
    reg = SkillRegistry(db_path=str(tmp_path / "skills.db"))
    await reg.start()
    try:
        await reg.update_skill_definition(_make_skill("custom_alpha"), create=True)
        ids = {s.skill_id for s in reg.list_skills()}
        assert "custom_alpha" in ids
    finally:
        await reg.stop()


@pytest.mark.asyncio
async def test_create_duplicate_rejected(tmp_path) -> None:
    reg = SkillRegistry(db_path=str(tmp_path / "skills.db"))
    await reg.start()
    try:
        await reg.update_skill_definition(_make_skill("custom_alpha"), create=True)
        with pytest.raises(ValueError, match="already exists"):
            await reg.update_skill_definition(_make_skill("custom_alpha"), create=True)
    finally:
        await reg.stop()


@pytest.mark.asyncio
async def test_update_existing_skill(tmp_path) -> None:
    reg = SkillRegistry(db_path=str(tmp_path / "skills.db"))
    await reg.start()
    try:
        await reg.update_skill_definition(_make_skill("custom_alpha"), create=True)
        renamed = SkillDefinition(
            skill_id="custom_alpha", name="Renamed", category=SkillCategory.ACQUIRED,
        )
        result = await reg.update_skill_definition(renamed, create=False)
        assert result.name == "Renamed"
        assert reg.get_skill("custom_alpha").name == "Renamed"
    finally:
        await reg.stop()


@pytest.mark.asyncio
async def test_dangling_prerequisite_rejected(tmp_path) -> None:
    reg = SkillRegistry(db_path=str(tmp_path / "skills.db"))
    await reg.start()
    try:
        with pytest.raises(ValueError, match="Dangling prerequisite"):
            await reg.update_skill_definition(
                _make_skill("needs_missing", prerequisites=["does_not_exist"]),
                create=True,
            )
    finally:
        await reg.stop()


@pytest.mark.asyncio
async def test_delete_round_trip(tmp_path) -> None:
    reg = SkillRegistry(db_path=str(tmp_path / "skills.db"))
    await reg.start()
    try:
        await reg.update_skill_definition(_make_skill("custom_alpha"), create=True)
        await reg.delete_skill_definition("custom_alpha")
        assert reg.get_skill("custom_alpha") is None
    finally:
        await reg.stop()


@pytest.mark.asyncio
async def test_delete_builtin_pcc_rejected(tmp_path) -> None:
    reg = SkillRegistry(db_path=str(tmp_path / "skills.db"))
    await reg.start()
    await reg.register_builtins()
    try:
        builtin_id = BUILTIN_PCCS[0].skill_id
        with pytest.raises(ValueError, match="built-in PCC"):
            await reg.delete_skill_definition(builtin_id)
        assert reg.get_skill(builtin_id) is not None
    finally:
        await reg.stop()


@pytest.mark.asyncio
async def test_delete_in_use_rejected(tmp_path) -> None:
    db_path = str(tmp_path / "skills.db")
    reg = SkillRegistry(db_path=db_path)
    service = AgentSkillService(db_path=db_path, registry=reg)
    await reg.start()
    await service.start()
    try:
        await reg.update_skill_definition(_make_skill("custom_alpha"), create=True)
        await service.acquire_skill("agent-1", "custom_alpha")
        with pytest.raises(ValueError, match="in use"):
            await reg.delete_skill_definition("custom_alpha", skill_service=service)
        assert reg.get_skill("custom_alpha") is not None
    finally:
        await service.stop()
        await reg.stop()


@pytest.mark.asyncio
async def test_persistence_survives_reload(tmp_path) -> None:
    db_path = str(tmp_path / "skills.db")
    reg = SkillRegistry(db_path=db_path)
    await reg.start()
    await reg.update_skill_definition(_make_skill("custom_alpha"), create=True)
    await reg.stop()

    reg2 = SkillRegistry(db_path=db_path)
    await reg2.start()
    try:
        assert reg2.get_skill("custom_alpha") is not None
    finally:
        await reg2.stop()


@pytest.mark.asyncio
async def test_count_agents_with_skill_no_store_returns_zero() -> None:
    service = AgentSkillService()  # no db_path → no backing store
    assert await service.count_agents_with_skill("custom_alpha") == 0


# ---------------------------------------------------------------------------
# HTTP surface
# ---------------------------------------------------------------------------


def test_http_list_definitions_empty_when_no_registry() -> None:
    runtime = _Runtime(skill_registry=None, skill_service=None)
    with _client_for(runtime) as client:
        resp = client.get("/api/skills/definitions")
    assert resp.status_code == 200
    assert resp.json() == {"definitions": [], "count": 0}


def test_http_create_and_list(tmp_path) -> None:
    db_path = str(tmp_path / "skills.db")
    runtime = _Runtime(
        skill_registry=SkillRegistry(db_path=db_path),
        skill_service=AgentSkillService(db_path=db_path),
    )
    with _client_for(runtime) as client:
        create = client.post(
            "/api/skills/definitions",
            json={"skill_id": "custom_alpha", "name": "Custom Alpha", "category": "acquired"},
        )
        assert create.status_code == 200
        listing = client.get("/api/skills/definitions")
    ids = {d["skill_id"] for d in listing.json()["definitions"]}
    assert "custom_alpha" in ids


def test_http_create_duplicate_returns_400(tmp_path) -> None:
    db_path = str(tmp_path / "skills.db")
    runtime = _Runtime(
        skill_registry=SkillRegistry(db_path=db_path),
        skill_service=AgentSkillService(db_path=db_path),
    )
    body = {"skill_id": "custom_alpha", "name": "Custom Alpha", "category": "acquired"}
    with _client_for(runtime) as client:
        assert client.post("/api/skills/definitions", json=body).status_code == 200
        dup = client.post("/api/skills/definitions", json=body)
    assert dup.status_code == 400


def test_http_create_missing_name_returns_400(tmp_path) -> None:
    db_path = str(tmp_path / "skills.db")
    runtime = _Runtime(
        skill_registry=SkillRegistry(db_path=db_path),
        skill_service=AgentSkillService(db_path=db_path),
    )
    with _client_for(runtime) as client:
        resp = client.post(
            "/api/skills/definitions",
            json={"skill_id": "custom_alpha", "category": "acquired"},
        )
    assert resp.status_code == 400


def test_http_update_existing(tmp_path) -> None:
    db_path = str(tmp_path / "skills.db")
    runtime = _Runtime(
        skill_registry=SkillRegistry(db_path=db_path),
        skill_service=AgentSkillService(db_path=db_path),
    )
    with _client_for(runtime) as client:
        client.post(
            "/api/skills/definitions",
            json={"skill_id": "custom_alpha", "name": "Custom Alpha", "category": "acquired"},
        )
        resp = client.put(
            "/api/skills/definitions/custom_alpha",
            json={"name": "Renamed", "category": "acquired"},
        )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Renamed"


def test_http_update_unknown_returns_404(tmp_path) -> None:
    db_path = str(tmp_path / "skills.db")
    runtime = _Runtime(
        skill_registry=SkillRegistry(db_path=db_path),
        skill_service=AgentSkillService(db_path=db_path),
    )
    with _client_for(runtime) as client:
        resp = client.put(
            "/api/skills/definitions/nope",
            json={"name": "X", "category": "acquired"},
        )
    assert resp.status_code == 404


def test_http_delete_happy_path(tmp_path) -> None:
    db_path = str(tmp_path / "skills.db")
    runtime = _Runtime(
        skill_registry=SkillRegistry(db_path=db_path),
        skill_service=AgentSkillService(db_path=db_path),
    )
    with _client_for(runtime) as client:
        client.post(
            "/api/skills/definitions",
            json={"skill_id": "custom_alpha", "name": "Custom Alpha", "category": "acquired"},
        )
        resp = client.delete("/api/skills/definitions/custom_alpha")
    assert resp.status_code == 200
    assert resp.json() == {"deleted": True, "skill_id": "custom_alpha"}


def test_http_delete_builtin_returns_400(tmp_path) -> None:
    db_path = str(tmp_path / "skills.db")
    reg = SkillRegistry(db_path=db_path)
    runtime = _Runtime(skill_registry=reg, skill_service=AgentSkillService(db_path=db_path))

    @asynccontextmanager
    async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await reg.start()
        await reg.register_builtins()
        await runtime.skill_service.start()
        yield
        await runtime.skill_service.stop()
        await reg.stop()

    app = FastAPI(lifespan=_lifespan)
    app.include_router(skills_router.router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as client:
        builtin_id = BUILTIN_PCCS[0].skill_id
        resp = client.delete(f"/api/skills/definitions/{builtin_id}")
    assert resp.status_code == 400


def test_http_delete_unknown_returns_404(tmp_path) -> None:
    db_path = str(tmp_path / "skills.db")
    runtime = _Runtime(
        skill_registry=SkillRegistry(db_path=db_path),
        skill_service=AgentSkillService(db_path=db_path),
    )
    with _client_for(runtime) as client:
        resp = client.delete("/api/skills/definitions/nope")
    assert resp.status_code == 404
