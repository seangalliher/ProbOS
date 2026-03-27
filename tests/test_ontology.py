"""Tests for AD-429a: Vessel Ontology Foundation."""

from __future__ import annotations

import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from probos.ontology import VesselOntologyService, Department, Post, Assignment


@pytest.fixture
def ontology_dir(tmp_path: Path) -> Path:
    """Copy ontology YAML files to a temp directory."""
    src = Path(__file__).resolve().parent.parent / "config" / "ontology"
    dst = tmp_path / "ontology"
    shutil.copytree(src, dst)
    return dst


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """Temp data directory for persistence tests."""
    return tmp_path / "data"


@pytest.fixture
async def service(ontology_dir: Path, data_dir: Path) -> VesselOntologyService:
    """Initialized ontology service."""
    svc = VesselOntologyService(ontology_dir, data_dir=data_dir)
    await svc.initialize()
    return svc


# -----------------------------------------------------------------------
# 1. Schema loading
# -----------------------------------------------------------------------

class TestSchemaLoading:
    @pytest.mark.asyncio
    async def test_loads_all_schemas(self, service: VesselOntologyService):
        """Load all three YAML files, verify parsing."""
        assert service._vessel_identity is not None
        assert len(service._departments) > 0
        assert len(service._posts) > 0
        assert len(service._assignments) > 0


# -----------------------------------------------------------------------
# 2. Department queries
# -----------------------------------------------------------------------

class TestDepartmentQueries:
    @pytest.mark.asyncio
    async def test_get_departments(self, service: VesselOntologyService):
        """get_departments() returns all departments."""
        depts = service.get_departments()
        assert len(depts) == 6
        dept_ids = {d.id for d in depts}
        assert "bridge" in dept_ids
        assert "engineering" in dept_ids
        assert "medical" in dept_ids
        assert "security" in dept_ids

    @pytest.mark.asyncio
    async def test_get_department_by_id(self, service: VesselOntologyService):
        """get_department('security') returns Security department."""
        dept = service.get_department("security")
        assert dept is not None
        assert dept.name == "Security"
        assert "integrity" in dept.description.lower() or "threat" in dept.description.lower()

    @pytest.mark.asyncio
    async def test_get_department_unknown(self, service: VesselOntologyService):
        """get_department('nonexistent') returns None."""
        assert service.get_department("nonexistent") is None


# -----------------------------------------------------------------------
# 3. Post queries
# -----------------------------------------------------------------------

class TestPostQueries:
    @pytest.mark.asyncio
    async def test_get_all_posts(self, service: VesselOntologyService):
        """get_posts() returns all posts."""
        posts = service.get_posts()
        assert len(posts) >= 14  # At least 14 posts defined

    @pytest.mark.asyncio
    async def test_get_posts_by_department(self, service: VesselOntologyService):
        """get_posts(department_id='medical') returns medical posts."""
        medical_posts = service.get_posts(department_id="medical")
        assert len(medical_posts) == 4  # CMO, surgeon, pharmacist, pathologist
        titles = {p.title for p in medical_posts}
        assert "Chief Medical Officer" in titles
        assert "Surgeon" in titles

    @pytest.mark.asyncio
    async def test_get_post_by_id(self, service: VesselOntologyService):
        """get_post('chief_security') returns Chief of Security."""
        post = service.get_post("chief_security")
        assert post is not None
        assert post.title == "Chief of Security"
        assert post.department_id == "security"
        assert post.reports_to == "first_officer"


# -----------------------------------------------------------------------
# 4. Chain of command
# -----------------------------------------------------------------------

class TestChainOfCommand:
    @pytest.mark.asyncio
    async def test_chain_of_command(self, service: VesselOntologyService):
        """get_chain_of_command('chief_security') returns [chief_security, first_officer, captain]."""
        chain = service.get_chain_of_command("chief_security")
        assert len(chain) == 3
        assert chain[0].id == "chief_security"
        assert chain[1].id == "first_officer"
        assert chain[2].id == "captain"

    @pytest.mark.asyncio
    async def test_chain_of_command_captain(self, service: VesselOntologyService):
        """Captain's chain is just [captain]."""
        chain = service.get_chain_of_command("captain")
        assert len(chain) == 1
        assert chain[0].id == "captain"


# -----------------------------------------------------------------------
# 5. Direct reports
# -----------------------------------------------------------------------

class TestDirectReports:
    @pytest.mark.asyncio
    async def test_first_officer_direct_reports(self, service: VesselOntologyService):
        """get_direct_reports('first_officer') returns all department chiefs."""
        reports = service.get_direct_reports("first_officer")
        report_ids = {r.id for r in reports}
        assert "chief_engineer" in report_ids
        assert "chief_science" in report_ids
        assert "chief_medical" in report_ids
        assert "chief_security" in report_ids
        assert "chief_operations" in report_ids

    @pytest.mark.asyncio
    async def test_leaf_post_no_reports(self, service: VesselOntologyService):
        """Leaf post has no direct reports."""
        reports = service.get_direct_reports("scout_officer")
        assert len(reports) == 0


# -----------------------------------------------------------------------
# 6. Assignment lookups
# -----------------------------------------------------------------------

class TestAssignments:
    @pytest.mark.asyncio
    async def test_assignment_for_agent(self, service: VesselOntologyService):
        """get_assignment_for_agent('security_officer') returns Worf."""
        assignment = service.get_assignment_for_agent("security_officer")
        assert assignment is not None
        assert assignment.callsign == "Worf"
        assert assignment.post_id == "chief_security"

    @pytest.mark.asyncio
    async def test_assignment_unknown_agent(self, service: VesselOntologyService):
        """Unknown agent_type returns None."""
        assert service.get_assignment_for_agent("nonexistent") is None


# -----------------------------------------------------------------------
# 7. Agent department
# -----------------------------------------------------------------------

class TestAgentDepartment:
    @pytest.mark.asyncio
    async def test_agent_department(self, service: VesselOntologyService):
        """get_agent_department('security_officer') returns 'security'."""
        dept = service.get_agent_department("security_officer")
        assert dept == "security"

    @pytest.mark.asyncio
    async def test_agent_department_unknown(self, service: VesselOntologyService):
        """Unknown agent_type returns None."""
        assert service.get_agent_department("nonexistent") is None


# -----------------------------------------------------------------------
# 8. Crew set
# -----------------------------------------------------------------------

class TestCrewSet:
    @pytest.mark.asyncio
    async def test_crew_agent_types(self, service: VesselOntologyService):
        """get_crew_agent_types() returns all crew agent types."""
        crew = service.get_crew_agent_types()
        assert "security_officer" in crew
        assert "architect" in crew
        assert "counselor" in crew
        assert "diagnostician" in crew
        assert "builder" in crew
        # Captain post is tier=external, not in crew set
        # (no agent_type is assigned to captain in assignments)


# -----------------------------------------------------------------------
# 9. Wire agent
# -----------------------------------------------------------------------

class TestWireAgent:
    @pytest.mark.asyncio
    async def test_wire_agent(self, service: VesselOntologyService):
        """wire_agent() associates runtime agent_id with post."""
        service.wire_agent("security_officer", "worf-abc123")
        assignment = service.get_assignment_for_agent("security_officer")
        assert assignment is not None
        assert assignment.agent_id == "worf-abc123"

    @pytest.mark.asyncio
    async def test_wire_unknown_agent(self, service: VesselOntologyService):
        """wire_agent() for unknown type is a no-op."""
        service.wire_agent("nonexistent", "xyz")  # Should not raise


# -----------------------------------------------------------------------
# 10. Crew context assembly
# -----------------------------------------------------------------------

class TestCrewContext:
    @pytest.mark.asyncio
    async def test_crew_context(self, service: VesselOntologyService):
        """get_crew_context('security_officer') returns full context dict."""
        ctx = service.get_crew_context("security_officer")
        assert ctx is not None

        # Vessel
        assert ctx["vessel"]["name"] == "ProbOS"
        assert ctx["vessel"]["alert_condition"] == "GREEN"

        # Identity
        assert ctx["identity"]["callsign"] == "Worf"
        assert ctx["identity"]["post"] == "Chief of Security"
        assert ctx["identity"]["agent_type"] == "security_officer"

        # Department
        assert ctx["department"]["id"] == "security"
        assert ctx["department"]["name"] == "Security"

        # Chain of command
        assert "Chief of Security" in ctx["chain_of_command"]
        assert "Captain" in ctx["chain_of_command"]

        # Reports to
        assert "First Officer" in ctx["reports_to"]

    @pytest.mark.asyncio
    async def test_crew_context_with_peers(self, service: VesselOntologyService):
        """Medical officer sees peers in same department."""
        ctx = service.get_crew_context("surgeon")
        assert ctx is not None
        # Surgeon is in medical, should see CMO, pharmacist, pathologist as peers
        assert len(ctx["peers"]) >= 2  # At least CMO and one other

    @pytest.mark.asyncio
    async def test_crew_context_unknown(self, service: VesselOntologyService):
        """get_crew_context('nonexistent') returns None."""
        assert service.get_crew_context("nonexistent") is None


# -----------------------------------------------------------------------
# 11. Vessel identity
# -----------------------------------------------------------------------

class TestVesselIdentity:
    @pytest.mark.asyncio
    async def test_vessel_identity(self, service: VesselOntologyService):
        """get_vessel_identity() returns name, version, instance_id."""
        identity = service.get_vessel_identity()
        assert identity.name == "ProbOS"
        assert identity.version == "0.4.0"
        assert len(identity.instance_id) > 0  # UUID generated


# -----------------------------------------------------------------------
# 12. Alert condition
# -----------------------------------------------------------------------

class TestAlertCondition:
    @pytest.mark.asyncio
    async def test_default_alert_condition(self, service: VesselOntologyService):
        """Default alert condition is GREEN."""
        assert service.get_alert_condition() == "GREEN"

    @pytest.mark.asyncio
    async def test_set_alert_condition(self, service: VesselOntologyService):
        """set_alert_condition('YELLOW') changes it."""
        service.set_alert_condition("YELLOW")
        assert service.get_alert_condition() == "YELLOW"

    @pytest.mark.asyncio
    async def test_invalid_alert_condition(self, service: VesselOntologyService):
        """Invalid alert condition raises ValueError."""
        with pytest.raises(ValueError, match="Invalid alert condition"):
            service.set_alert_condition("PURPLE")


# -----------------------------------------------------------------------
# 13. Vessel state
# -----------------------------------------------------------------------

class TestVesselState:
    @pytest.mark.asyncio
    async def test_vessel_state(self, service: VesselOntologyService):
        """get_vessel_state() returns current state."""
        state = service.get_vessel_state()
        assert state.alert_condition == "GREEN"
        assert state.uptime_seconds >= 0
        assert state.active_crew_count == 0  # No agents wired yet

    @pytest.mark.asyncio
    async def test_vessel_state_after_wire(self, service: VesselOntologyService):
        """Active crew count increases after wiring agents."""
        service.wire_agent("security_officer", "worf-1")
        state = service.get_vessel_state()
        assert state.active_crew_count == 1


# -----------------------------------------------------------------------
# 14. Instance ID persistence
# -----------------------------------------------------------------------

class TestInstancePersistence:
    @pytest.mark.asyncio
    async def test_instance_id_persisted(self, ontology_dir: Path, data_dir: Path):
        """Generate, save, reload, verify same UUID."""
        svc1 = VesselOntologyService(ontology_dir, data_dir=data_dir)
        await svc1.initialize()
        id1 = svc1.get_vessel_identity().instance_id

        # Create a second service from the same data_dir
        svc2 = VesselOntologyService(ontology_dir, data_dir=data_dir)
        await svc2.initialize()
        id2 = svc2.get_vessel_identity().instance_id

        assert id1 == id2
        assert len(id1) == 36  # UUID format


# -----------------------------------------------------------------------
# 15. Post for agent
# -----------------------------------------------------------------------

class TestPostForAgent:
    @pytest.mark.asyncio
    async def test_get_post_for_agent(self, service: VesselOntologyService):
        """get_post_for_agent() returns the correct post."""
        post = service.get_post_for_agent("architect")
        assert post is not None
        assert post.id == "first_officer"
        assert post.title == "First Officer"

    @pytest.mark.asyncio
    async def test_get_post_for_unknown_agent(self, service: VesselOntologyService):
        """Unknown agent returns None."""
        assert service.get_post_for_agent("nonexistent") is None
