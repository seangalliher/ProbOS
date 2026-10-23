"""BF-915 (#1623): the Yeoman and the Training Officer have role templates, the doctor reports a crew post without
one, and BF-917's trigger applies a new template to a crew member commissioned without one, keeping its PCCs.

Real loader, ontology service, stores and AD-889 chain (``tests/fixtures/crew_template_world.py``).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from probos.crew_enrollment import template_fingerprint
from probos.doctor.checks.role_template_check import _RoleTemplateCheck
from probos.doctor.protocol import CheckOutcome, DoctorContext
from probos.ontology import VesselOntologyService
from probos.ontology.loader import OntologyLoader
from probos.role_template_audit import crew_posts_without_template, unregistered_template_skills
from probos.skill_framework import (
    BUILTIN_PCCS,
    ONTOLOGY_TEMPLATE_SKILLS,
    ProficiencyLevel,
    builtin_skill_definitions,
)
from tests.fixtures.crew_template_world import (
    ONTOLOGY_DIR,
    CrewAgent,
    boot_enroller,
    crew_world,
    edit_skills_yaml,
    recommission_rows,
    skill_records,
)

_NEW_ROLE_SKILLS = {
    "yeoman": {"captain_briefing", "schedule_coordination", "correspondence_triage", "crew_delegation"},
    "chief_training": {"drill_planning", "readiness_assessment", "onboarding_mentorship", "limited_duty_planning"},
}
_PCC_IDS = frozenset(p.skill_id for p in BUILTIN_PCCS)


@pytest.mark.asyncio
async def test_every_assigned_crew_post_resolves_a_role_template(tmp_path: Path) -> None:
    """B1: no assigned crew-tier post lacks a template, through the loader and through the ontology service."""
    loader = OntologyLoader(ONTOLOGY_DIR)
    await loader.initialize()
    assert crew_posts_without_template(loader.posts, loader.assignments.values(), loader.role_templates) == ()
    ontology = VesselOntologyService(ONTOLOGY_DIR, data_dir=tmp_path)
    await ontology.initialize()
    crew = ontology.get_crew_agent_types()
    assert {"yeoman", "training_officer"} <= crew and len(crew) >= 16  # premise: the assigned crew
    assert [t for t in sorted(crew) if ontology.get_role_template_for_agent(t) is None] == []


@pytest.mark.asyncio
async def test_the_yeoman_and_training_templates_name_only_registered_operations_skills() -> None:
    """B2: each template has its four new role skills plus PCCs; all are registered operations definitions."""
    loader = OntologyLoader(ONTOLOGY_DIR)
    await loader.initialize()
    by_id = {d.skill_id: d for d in ONTOLOGY_TEMPLATE_SKILLS}
    for post_id, new in _NEW_ROLE_SKILLS.items():
        required = {r.skill_id for r in loader.role_templates[post_id].required_skills}
        assert required - _PCC_IDS == new, post_id
        assert all(by_id[s].domain == "operations" for s in new), post_id
    registered = frozenset(d.skill_id for d in builtin_skill_definitions())
    assert unregistered_template_skills(loader.role_templates, registered) == ()


@pytest.mark.asyncio
async def test_the_doctor_warns_for_an_assigned_crew_post_without_a_template(tmp_path: Path) -> None:
    """B3: the yeoman's post without its template is one WARN line naming the post and the agent type."""
    copy = tmp_path / "ontology"
    shutil.copytree(ONTOLOGY_DIR, copy)
    path = copy / "skills.yaml"
    text = path.read_text(encoding="utf-8")
    assert text.count("  yeoman:\n") == 1  # premise
    path.write_text(text.replace("  yeoman:\n", "  yeoman_retired:\n"), encoding="utf-8")
    context = DoctorContext(config=None, home_dir=tmp_path, data_dir=tmp_path / "data", config_path=None)

    result = await _RoleTemplateCheck(ontology_dir=copy).run(context)

    assert result.outcome is CheckOutcome.WARN
    assert result.detail.splitlines() == ["yeoman (yeoman): an assigned crew post has no role template"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("agent_type", "post_id"),
    [("yeoman", "yeoman"), ("training_officer", "chief_training")],
    ids=["yeoman", "training_officer"],
)
async def test_a_crew_member_commissioned_without_a_template_gains_it_keeping_its_pccs(
    tmp_path: Path, agent_type: str, post_id: str,
) -> None:
    """B4 (the seam): PCCs-only commissioning -> this change's template -> re-commissioned once, PCCs unchanged,
    the four role skills at their floors, the record names the post, no tool; stable afterwards."""
    async with crew_world(tmp_path) as world:
        shipped = (world.ontology_dir / "skills.yaml").read_text(encoding="utf-8")
        edit_skills_yaml(world, f"  {post_id}:\n", f"  {post_id}_before_bf915:\n")
        agent = CrewAgent(f"{agent_type}-b4", agent_type)
        enroller, ontology = await boot_enroller(world)
        assert ontology.get_role_template_for_agent(agent_type) is None  # premise: the vessel before BF-915
        first = await enroller.enroll(agent, source="birth")
        assert first is not None and first.commissioned is True and first.role_template is None
        await world.skill_service.update_proficiency(agent.id, "communication", ProficiencyLevel.LEAD, source="bf915-test")
        held = await skill_records(world.skill_service, agent.id)
        assert set(held) == _PCC_IDS  # premise: the nine PCCs only
        history = await world.acm.get_transition_history(agent.id)

        (world.ontology_dir / "skills.yaml").write_text(shipped, encoding="utf-8")  # this change's templates
        enroller, ontology = await boot_enroller(world)
        template = ontology.get_role_template_for_agent(agent_type)
        assert template is not None
        again = await enroller.enroll(agent, source="backfill")

        assert again is not None and again.recommissioned is True
        assert set(again.skills_granted) == _NEW_ROLE_SKILLS[post_id]
        after = await skill_records(world.skill_service, agent.id)
        assert {skill: after[skill] for skill in held} == held  # communication stays at LEAD, every PCC as it was
        floors = {r.skill_id: r.min_proficiency for r in template.required_skills}
        assert {s: after[s][0] for s in _NEW_ROLE_SKILLS[post_id]} == {s: floors[s] for s in _NEW_ROLE_SKILLS[post_id]}
        record = await world.acm.get_commissioning_record(agent.id)
        assert record is not None and record.role_template == post_id
        assert record.template_fingerprint == template_fingerprint(template)
        assert len(recommission_rows(history, await world.acm.get_transition_history(agent.id))) == 1
        assert await world.permission_store.list_grants(active_only=True) == []
        third = await enroller.enroll(agent, source="backfill")
        assert third is not None and third.recommissioned is False
