"""Tests for AD-429b: Skills Ontology Domain."""

from __future__ import annotations

import pytest
import shutil
from pathlib import Path

from probos.ontology import (
    VesselOntologyService,
    RoleTemplate,
    SkillRequirement,
    QualificationPath,
    QualificationRequirement,
)
from probos.skill_framework import (
    QualificationRecord,
    AgentSkillService,
    SkillRegistry,
    ProficiencyLevel,
    SkillCategory,
    SkillDefinition,
)


@pytest.fixture
def ontology_dir(tmp_path: Path) -> Path:
    """Copy ontology YAML files to a temp directory."""
    src = Path(__file__).resolve().parent.parent / "config" / "ontology"
    dst = tmp_path / "ontology"
    shutil.copytree(src, dst)
    return dst


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
async def service(ontology_dir: Path, data_dir: Path) -> VesselOntologyService:
    svc = VesselOntologyService(ontology_dir, data_dir=data_dir)
    await svc.initialize()
    return svc


# -----------------------------------------------------------------------
# 1. Skills YAML loading
# -----------------------------------------------------------------------

class TestSkillsSchemaLoading:
    @pytest.mark.asyncio
    async def test_skills_yaml_loaded(self, service: VesselOntologyService):
        """Load skills.yaml, verify role templates parsed."""
        assert len(service._role_templates) == 11
        assert len(service._qualification_paths) == 3


# -----------------------------------------------------------------------
# 2. Role template query
# -----------------------------------------------------------------------

class TestRoleTemplateQuery:
    @pytest.mark.asyncio
    async def test_get_role_template(self, service: VesselOntologyService):
        """get_role_template('chief_security') returns Worf's requirements."""
        template = service.get_role_template("chief_security")
        assert template is not None
        assert template.post_id == "chief_security"
        required_ids = {r.skill_id for r in template.required_skills}
        assert "threat_assessment" in required_ids
        assert "access_control" in required_ids


# -----------------------------------------------------------------------
# 3. Role template for agent
# -----------------------------------------------------------------------

class TestRoleTemplateForAgent:
    @pytest.mark.asyncio
    async def test_get_role_template_for_agent(self, service: VesselOntologyService):
        """get_role_template_for_agent('security_officer') returns chief_security template."""
        template = service.get_role_template_for_agent("security_officer")
        assert template is not None
        assert template.post_id == "chief_security"


# -----------------------------------------------------------------------
# 4. Unknown post template
# -----------------------------------------------------------------------

class TestUnknownTemplate:
    @pytest.mark.asyncio
    async def test_unknown_post_template(self, service: VesselOntologyService):
        """get_role_template('nonexistent') returns None."""
        assert service.get_role_template("nonexistent") is None


# -----------------------------------------------------------------------
# 5. Required skills count
# -----------------------------------------------------------------------

class TestRequiredSkillsCount:
    @pytest.mark.asyncio
    async def test_chief_security_skill_counts(self, service: VesselOntologyService):
        """chief_security has 5 required, 1 optional."""
        template = service.get_role_template("chief_security")
        assert template is not None
        assert len(template.required_skills) == 5
        assert len(template.optional_skills) == 1


# -----------------------------------------------------------------------
# 6. Qualification path loading
# -----------------------------------------------------------------------

class TestQualificationPathLoading:
    @pytest.mark.asyncio
    async def test_qualification_paths_loaded(self, service: VesselOntologyService):
        """3 paths loaded (ensign→lt, lt→cmdr, cmdr→senior)."""
        paths = service.get_all_qualification_paths()
        assert len(paths) == 3
        path_keys = {f"{p.from_rank}_to_{p.to_rank}" for p in paths}
        assert "ensign_to_lieutenant" in path_keys
        assert "lieutenant_to_commander" in path_keys
        assert "commander_to_senior" in path_keys


# -----------------------------------------------------------------------
# 7. Qualification path query
# -----------------------------------------------------------------------

class TestQualificationPathQuery:
    @pytest.mark.asyncio
    async def test_get_qualification_path(self, service: VesselOntologyService):
        """get_qualification_path('ensign', 'lieutenant') returns correct requirements."""
        path = service.get_qualification_path("ensign", "lieutenant")
        assert path is not None
        assert path.from_rank == "ensign"
        assert path.to_rank == "lieutenant"
        assert len(path.requirements) == 2
        req_types = {r.type for r in path.requirements}
        assert "pcc_minimum" in req_types
        assert "role_minimum" in req_types


# -----------------------------------------------------------------------
# 8. Unknown qualification path
# -----------------------------------------------------------------------

class TestUnknownQualificationPath:
    @pytest.mark.asyncio
    async def test_unknown_qualification_path(self, service: VesselOntologyService):
        """get_qualification_path('ensign', 'admiral') returns None."""
        assert service.get_qualification_path("ensign", "admiral") is None


# -----------------------------------------------------------------------
# 9. QualificationRecord model — is_complete() empty
# -----------------------------------------------------------------------

class TestQualificationRecordModel:
    def test_qualification_record_empty(self):
        """Empty requirement_status → is_complete() returns False."""
        record = QualificationRecord(
            agent_id="test-agent",
            path_id="ensign_to_lieutenant",
            started_at=1000.0,
        )
        assert record.is_complete() is False


# -----------------------------------------------------------------------
# 10. QualificationRecord all met
# -----------------------------------------------------------------------

class TestQualificationRecordComplete:
    def test_all_requirements_met(self):
        """All requirements True → is_complete() returns True."""
        record = QualificationRecord(
            agent_id="test-agent",
            path_id="ensign_to_lieutenant",
            started_at=1000.0,
            requirement_status={
                "pcc_minimum_all_pccs": True,
                "role_minimum_role_skills": True,
            },
        )
        assert record.is_complete() is True


# -----------------------------------------------------------------------
# 11. QualificationRecord partial
# -----------------------------------------------------------------------

class TestQualificationRecordPartial:
    def test_partial_requirements(self):
        """Some False → is_complete() returns False."""
        record = QualificationRecord(
            agent_id="test-agent",
            path_id="ensign_to_lieutenant",
            started_at=1000.0,
            requirement_status={
                "pcc_minimum_all_pccs": True,
                "role_minimum_role_skills": False,
            },
        )
        assert record.is_complete() is False


# -----------------------------------------------------------------------
# 12. QualificationRecord to_dict
# -----------------------------------------------------------------------

class TestQualificationRecordToDict:
    def test_to_dict(self):
        """Verify serialization."""
        record = QualificationRecord(
            agent_id="test-agent",
            path_id="ensign_to_lieutenant",
            started_at=1000.0,
            completed_at=2000.0,
            requirement_status={"pcc_minimum_all_pccs": True},
        )
        d = record.to_dict()
        assert d["agent_id"] == "test-agent"
        assert d["path_id"] == "ensign_to_lieutenant"
        assert d["started_at"] == 1000.0
        assert d["completed_at"] == 2000.0
        assert d["is_complete"] is True
        assert d["requirements"] == {"pcc_minimum_all_pccs": True}


# -----------------------------------------------------------------------
# 13. Assignment by agent_id
# -----------------------------------------------------------------------

class TestAssignmentByAgentId:
    @pytest.mark.asyncio
    async def test_get_assignment_for_agent_by_id(self, service: VesselOntologyService):
        """get_assignment_for_agent_by_id() after wire_agent()."""
        service.wire_agent("security_officer", "worf-runtime-id")
        assignment = service.get_assignment_for_agent_by_id("worf-runtime-id")
        assert assignment is not None
        assert assignment.callsign == "Worf"
        assert assignment.post_id == "chief_security"

    @pytest.mark.asyncio
    async def test_assignment_by_id_unknown(self, service: VesselOntologyService):
        """Unknown agent_id returns None."""
        assert service.get_assignment_for_agent_by_id("unknown-id") is None


# -----------------------------------------------------------------------
# 14. Crew context includes role requirements
# -----------------------------------------------------------------------

class TestCrewContextRoleRequirements:
    @pytest.mark.asyncio
    async def test_crew_context_has_role_requirements(self, service: VesselOntologyService):
        """get_crew_context() now has role_requirements key."""
        ctx = service.get_crew_context("security_officer")
        assert ctx is not None
        assert "role_requirements" in ctx
        assert "required" in ctx["role_requirements"]
        assert "optional" in ctx["role_requirements"]
        # Verify structure
        required = ctx["role_requirements"]["required"]
        assert len(required) == 5
        skill_ids = {r["skill"] for r in required}
        assert "threat_assessment" in skill_ids


# -----------------------------------------------------------------------
# 15. Skill service wiring
# -----------------------------------------------------------------------

class TestSkillServiceWiring:
    @pytest.mark.asyncio
    async def test_set_skill_service(self, service: VesselOntologyService):
        """set_skill_service() stores reference and enables skills_note."""
        assert service._skill_service is None
        # Without skill service, no skills_note
        ctx = service.get_crew_context("security_officer")
        assert "skills_note" not in ctx

        # Wire skill service
        service.set_skill_service("mock_skill_service")
        assert service._skill_service == "mock_skill_service"

        # Now skills_note should appear
        ctx = service.get_crew_context("security_officer")
        assert "skills_note" in ctx
        assert "Skill Framework" in ctx["skills_note"]
