"""AD-889 — ACM commission chain: Role → Skills → Tools (capstone).

Verifies the composed front door `AgentCapitalService.commission(agent_id,
agent_type, runtime)` walks the full capability spine against real subsystems
(BF-287 discipline — no MagicMock at the substrate boundary): a real
`SkillRegistry` + `AgentSkillService` on a tmp DB, a real `ToolPermissionStore`,
a real `ToolRegistry`, and a real `AgentCapitalService`. The ontology is a tiny
real stub exposing only the read-only `get_role_template_for_agent` method (it
returns genuine `RoleTemplate`/`SkillRequirement` dataclasses).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from probos.acm import AgentCapitalService
from probos.ontology.models import RoleTemplate, SkillRequirement
from probos.skill_framework import (
    AgentSkillService,
    ProficiencyLevel,
    SkillCategory,
    SkillDefinition,
    SkillRegistry,
)
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolPreference, ToolType
from probos.tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# Minimal real stubs (not MagicMock — concrete objects returning real data)
# ---------------------------------------------------------------------------


class _FakeTool:
    """Minimal Tool-protocol implementation for registry registration."""

    def __init__(self, tool_id: str, name: str = "") -> None:
        self._tool_id = tool_id
        self._name = name or tool_id

    @property
    def tool_id(self) -> str:
        return self._tool_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def tool_type(self) -> ToolType:
        return ToolType.DETERMINISTIC_FUNCTION

    @property
    def description(self) -> str:
        return f"fake tool {self._tool_id}"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {}

    @property
    def output_schema(self) -> dict[str, Any]:
        return {}

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None):  # pragma: no cover - never invoked
        raise NotImplementedError


class _StubOntology:
    """Read-only ontology stub exposing only `get_role_template_for_agent`.

    Returns genuine `RoleTemplate` dataclasses (or `None`) — the method name
    matches the real `VesselOntologyService` API exactly.
    """

    def __init__(self, templates: dict[str, RoleTemplate]) -> None:
        self._templates = templates

    def get_role_template_for_agent(self, agent_type: str) -> RoleTemplate | None:
        return self._templates.get(agent_type)


class _StubRuntime:
    """Plain attribute holder — `commission` reads collaborators via getattr."""

    def __init__(
        self,
        *,
        skill_service: Any = None,
        tool_permission_store: Any = None,
        tool_registry: Any = None,
        skill_registry: Any = None,
        ontology: Any = None,
    ) -> None:
        self.skill_service = skill_service
        self.tool_permission_store = tool_permission_store
        self.tool_registry = tool_registry
        self.skill_registry = skill_registry
        self.ontology = ontology


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


async def _build_skill_service(
    tmp_path: Path, *, skill: SkillDefinition | None = None,
) -> tuple[AgentSkillService, SkillRegistry]:
    registry = SkillRegistry(db_path=str(tmp_path / "registry.db"))
    await registry.start()
    if skill is not None:
        await registry.register_skill(skill)
    service = AgentSkillService(db_path=str(tmp_path / "skills.db"), registry=registry)
    await service.start()
    return service, registry


async def _build_permission_store(tmp_path: Path) -> ToolPermissionStore:
    store = ToolPermissionStore(db_path=str(tmp_path / "grants.db"))
    await store.start()
    return store


def _scanner_skill() -> SkillDefinition:
    return SkillDefinition(
        skill_id="tactical_debug",
        name="Tactical Debug",
        category=SkillCategory.ROLE,
        description="role skill",
        domain="*",
        preferred_tools=[ToolPreference(tool_id="scanner", priority=1)],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_commission_acquires_template_skills_and_grants_tools(tmp_path: Path) -> None:
    service, registry = await _build_skill_service(tmp_path, skill=_scanner_skill())
    store = await _build_permission_store(tmp_path)
    tool_registry = ToolRegistry()
    tool_registry.register(_FakeTool("scanner"))  # unrestricted → ship-wide READ
    ontology = _StubOntology({
        "science_officer": RoleTemplate(
            post_id="science_officer",
            required_skills=[SkillRequirement(skill_id="tactical_debug", min_proficiency=3)],
        ),
    })
    runtime = _StubRuntime(
        skill_service=service,
        tool_permission_store=store,
        tool_registry=tool_registry,
        skill_registry=registry,
        ontology=ontology,
    )
    acm = AgentCapitalService(data_dir=tmp_path)

    summary = await acm.commission("ensign-1", "science_officer", runtime)

    # Skill acquired at the template's declared proficiency (APPLY = 3), not FOLLOW.
    profile = await service.get_profile("ensign-1")
    by_id = {r.skill_id: r for r in profile.all_skills}
    assert "tactical_debug" in by_id
    assert by_id["tactical_debug"].proficiency == ProficiencyLevel.APPLY
    # Tool resolved from the skill's preferred_tools was granted.
    grants = store.get_active_grants_sync("ensign-1", "scanner")
    assert [g for g in grants if not g.is_restriction]
    assert "scanner" in summary["tools_granted"]

    await store.stop()


@pytest.mark.asyncio
async def test_commission_falls_back_to_legacy_when_no_template(tmp_path: Path) -> None:
    service, registry = await _build_skill_service(tmp_path)
    store = await _build_permission_store(tmp_path)
    ontology = _StubOntology({})  # no template for this agent_type
    runtime = _StubRuntime(
        skill_service=service,
        tool_permission_store=store,
        tool_registry=ToolRegistry(),
        skill_registry=registry,
        ontology=ontology,
    )
    acm = AgentCapitalService(data_dir=tmp_path)

    summary = await acm.commission("ensign-2", "unknown_role", runtime)

    # commission_agent still ran (PCCs assigned) — the legacy path is the fallback.
    profile = await service.get_profile("ensign-2")
    assert profile.all_skills  # PCCs at minimum
    assert summary["skills_acquired"]

    await store.stop()


@pytest.mark.asyncio
async def test_commission_is_idempotent(tmp_path: Path) -> None:
    service, registry = await _build_skill_service(tmp_path, skill=_scanner_skill())
    store = await _build_permission_store(tmp_path)
    tool_registry = ToolRegistry()
    tool_registry.register(_FakeTool("scanner"))
    ontology = _StubOntology({
        "science_officer": RoleTemplate(
            post_id="science_officer",
            required_skills=[SkillRequirement(skill_id="tactical_debug", min_proficiency=3)],
        ),
    })
    runtime = _StubRuntime(
        skill_service=service,
        tool_permission_store=store,
        tool_registry=tool_registry,
        skill_registry=registry,
        ontology=ontology,
    )
    acm = AgentCapitalService(data_dir=tmp_path)

    await acm.commission("ensign-3", "science_officer", runtime)
    await acm.commission("ensign-3", "science_officer", runtime)

    # No duplicate skill rows (acquire_skill upserts).
    profile = await service.get_profile("ensign-3")
    skill_ids = [r.skill_id for r in profile.all_skills]
    assert len(skill_ids) == len(set(skill_ids))
    # No duplicate non-restriction grants for the resolved tool.
    grants = [g for g in store.get_active_grants_sync("ensign-3", "scanner") if not g.is_restriction]
    assert len(grants) == 1

    await store.stop()


@pytest.mark.asyncio
async def test_commission_skill_without_preferred_tool_is_clean(tmp_path: Path) -> None:
    plain = SkillDefinition(
        skill_id="diplomacy",
        name="Diplomacy",
        category=SkillCategory.ROLE,
        description="no preferred tools",
        domain="*",
        preferred_tools=[],
    )
    service, registry = await _build_skill_service(tmp_path, skill=plain)
    store = await _build_permission_store(tmp_path)
    ontology = _StubOntology({
        "diplomat": RoleTemplate(
            post_id="diplomat",
            required_skills=[SkillRequirement(skill_id="diplomacy", min_proficiency=2)],
        ),
    })
    runtime = _StubRuntime(
        skill_service=service,
        tool_permission_store=store,
        tool_registry=ToolRegistry(),
        skill_registry=registry,
        ontology=ontology,
    )
    acm = AgentCapitalService(data_dir=tmp_path)

    summary = await acm.commission("ensign-4", "diplomat", runtime)

    assert summary["tools_granted"] == []
    profile = await service.get_profile("ensign-4")
    assert "diplomacy" in {r.skill_id for r in profile.all_skills}

    await store.stop()


@pytest.mark.asyncio
async def test_commission_degrades_without_permission_store(tmp_path: Path) -> None:
    service, registry = await _build_skill_service(tmp_path, skill=_scanner_skill())
    tool_registry = ToolRegistry()
    tool_registry.register(_FakeTool("scanner"))
    ontology = _StubOntology({
        "science_officer": RoleTemplate(
            post_id="science_officer",
            required_skills=[SkillRequirement(skill_id="tactical_debug", min_proficiency=3)],
        ),
    })
    runtime = _StubRuntime(
        skill_service=service,
        tool_permission_store=None,  # absent → tool-grant step must skip, not raise
        tool_registry=tool_registry,
        skill_registry=registry,
        ontology=ontology,
    )
    acm = AgentCapitalService(data_dir=tmp_path)

    summary = await acm.commission("ensign-5", "science_officer", runtime)

    # Skills still acquired; no tools granted (store absent); no exception raised.
    assert summary["tools_granted"] == []
    profile = await service.get_profile("ensign-5")
    assert "tactical_debug" in {r.skill_id for r in profile.all_skills}


@pytest.mark.asyncio
async def test_commission_without_skill_service_returns_empty_summary(tmp_path: Path) -> None:
    runtime = _StubRuntime(skill_service=None)
    acm = AgentCapitalService(data_dir=tmp_path)

    summary = await acm.commission("ensign-6", "science_officer", runtime)

    assert summary == {
        "agent_id": "ensign-6",
        "agent_type": "science_officer",
        "skills_acquired": [],
        "tools_granted": [],
    }
