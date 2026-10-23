"""BF-917 (#1625) / BF-915 (#1623): a crew-enrollment world on real stores and a copy of the shipped ontology.

Real ``SkillRegistry`` + ``AgentSkillService``, ``ToolPermissionStore``, ``ToolRegistry`` and
``AgentCapitalService`` on SQLite files under ``tmp_path``; the ontology is the real
``VesselOntologyService`` over a copy of ``config/ontology`` that a test may edit, and each
``boot_enroller`` call builds what one boot builds. The only stand-in is the wired agent.
"""

from __future__ import annotations

import contextlib
import json
import shutil
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace as _Namespace
from typing import Any

from probos.acm import AgentCapitalService
from probos.crew_enrollment import CrewEnrollmentService
from probos.ontology import VesselOntologyService
from probos.skill_framework import AgentSkillService, SkillRegistry
from probos.tools.adapters import DirectServiceAdapter
from probos.tools.permissions import ToolPermissionStore
from probos.tools.registry import ToolRegistry

ONTOLOGY_DIR = Path(__file__).resolve().parents[2] / "config" / "ontology"
PROBE_TOOL = "engineering_probe"


async def _noop(**kwargs: Any) -> None:
    return None


@dataclass(frozen=True)
class CrewAgent:
    """The attributes crew enrollment reads from a wired agent."""

    id: str
    agent_type: str
    pool: str = "bf917_pool"
    sovereign_id: str = ""


@dataclass(frozen=True)
class CrewWorld:
    tmp_path: Path
    ontology_dir: Path
    skill_registry: SkillRegistry
    skill_service: AgentSkillService
    permission_store: ToolPermissionStore
    tool_registry: ToolRegistry
    acm: AgentCapitalService


@contextlib.asynccontextmanager
async def crew_world(tmp_path: Path) -> AsyncIterator[CrewWorld]:
    """The stores, started and stopped; the tool registry holds one readable tool tagged ``engineering``."""
    ontology_dir = tmp_path / "ontology"
    shutil.copytree(ONTOLOGY_DIR, ontology_dir)
    skills_db = str(tmp_path / "skills.db")
    skill_registry = SkillRegistry(db_path=skills_db)
    skill_service = AgentSkillService(db_path=skills_db, registry=skill_registry)
    permission_store = ToolPermissionStore(db_path=str(tmp_path / "tool_permissions.db"))
    acm = AgentCapitalService(data_dir=tmp_path / "acm")
    await skill_registry.start()
    await skill_registry.register_builtins()
    await skill_service.start()
    await permission_store.start()
    await acm.start()
    tool_registry = ToolRegistry()
    tool_registry.set_permission_store(permission_store)
    tool_registry.register(
        DirectServiceAdapter(tool_id=PROBE_TOOL, name="Engineering probe", description="BF-917 test tool", handler=_noop),
        provider="bf917", tags=["engineering"],
    )
    try:
        yield CrewWorld(
            tmp_path=tmp_path, ontology_dir=ontology_dir, skill_registry=skill_registry,
            skill_service=skill_service, permission_store=permission_store,
            tool_registry=tool_registry, acm=acm,
        )
    finally:
        await acm.stop()
        await permission_store.stop()
        await skill_service.stop()
        await skill_registry.stop()


async def boot_enroller(world: CrewWorld) -> tuple[CrewEnrollmentService, VesselOntologyService]:
    """What one boot builds over the world's stores: the ontology from its copy, and an enroller over it."""
    ontology = VesselOntologyService(world.ontology_dir, data_dir=world.tmp_path / "ontology_data")
    await ontology.initialize()
    context = _Namespace(
        skill_service=world.skill_service, skill_registry=world.skill_registry,
        tool_registry=world.tool_registry, tool_permission_store=world.permission_store,
        ontology=ontology,
    )
    enroller = CrewEnrollmentService(
        acm=world.acm, ontology=ontology, skill_service=world.skill_service, identity_registry=None,
        event_log=None, commission_context=context, boot_started_at=0.0,
    )
    return enroller, ontology


def edit_skills_yaml(world: CrewWorld, old: str, new: str) -> None:
    """Replace the one occurrence of ``old`` in the world's copy of skills.yaml."""
    path = world.ontology_dir / "skills.yaml"
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, f"premise: {old!r} occurs once in the copied skills.yaml"
    path.write_text(text.replace(old, new), encoding="utf-8")


async def skill_records(skill_service: AgentSkillService, agent_id: str) -> dict[str, tuple[Any, ...]]:
    """Each record's proficiency, exercise count, timestamps, source, suspension and history."""
    return {
        r.skill_id: (
            r.proficiency, r.exercise_count, r.acquired_at, r.last_exercised,
            r.acquisition_source, r.suspended, json.dumps(r.assessment_history, sort_keys=True),
        )
        for r in await skill_service.get_all_records(agent_id)
    }


def recommission_rows(before: list[Any], after: list[Any]) -> list[Any]:
    """The re-commission history rows ``after`` adds to ``before``, picked by predicate."""
    return [
        t for t in after
        if t not in before and t.from_state == t.to_state and "re-commissioned" in t.reason
    ]
