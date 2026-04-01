"""BF-049/050: Ontology callsign sync after naming ceremony."""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from probos.ontology import VesselOntologyService, Assignment, Post, Department
from probos.ontology.loader import OntologyLoader
from probos.ontology.departments import DepartmentService
from probos.ontology.ranks import RankService


def _build_ontology_with_agents():
    """Build a minimal ontology with 2 agents in engineering department."""
    onto = VesselOntologyService.__new__(VesselOntologyService)

    # Build loader with data attributes
    loader = OntologyLoader.__new__(OntologyLoader)
    loader.departments = {
        "engineering": Department(id="engineering", name="Engineering", description=""),
    }
    loader.posts = {
        "chief_engineer": Post(
            id="chief_engineer", title="Chief Engineer",
            department_id="engineering", reports_to="first_officer",
            authority_over=["engineer"], tier="crew",
        ),
        "engineer": Post(
            id="engineer", title="Engineer",
            department_id="engineering", reports_to="chief_engineer",
            authority_over=[], tier="crew",
        ),
        "first_officer": Post(
            id="first_officer", title="First Officer",
            department_id="bridge", reports_to=None,
            authority_over=["chief_engineer"], tier="crew",
        ),
    }
    loader.assignments = {
        "engineering_agent": Assignment(
            agent_type="engineering_agent", post_id="chief_engineer",
            callsign="LaForge", agent_id="eng-001",
        ),
        "engineer_agent": Assignment(
            agent_type="engineer_agent", post_id="engineer",
            callsign="Scotty", agent_id="eng-002",
        ),
        "architect_agent": Assignment(
            agent_type="architect_agent", post_id="first_officer",
            callsign="Number One", agent_id="fo-001",
        ),
    }
    loader.vessel_identity = None
    loader.alert_condition = "GREEN"
    loader.valid_alert_conditions = ["GREEN", "YELLOW", "RED"]
    loader._started_at = 0.0
    loader.role_templates = {}
    loader.qualification_paths = {}
    loader.standing_order_tiers = []
    loader.watch_types = []
    loader.alert_procedures = {}
    loader.duty_categories = []
    loader.channel_types = []
    loader.thread_modes = []
    loader.message_patterns = []
    loader.model_tiers = []
    loader.tool_capabilities = []
    loader.knowledge_sources = []
    loader.knowledge_tiers = []
    loader.classifications = []
    loader.document_classes = []
    loader.retention_policies = []
    loader.document_fields_required = []
    loader.document_fields_optional = []
    loader.repository_directories = []

    onto._loader = loader
    onto._dept = DepartmentService(loader.departments, loader.posts, loader.assignments)
    onto._ranks = RankService(loader.role_templates, loader.qualification_paths, loader.assignments)
    return onto


class TestOntologyCallsignSync:
    """BF-049/050: update_assignment_callsign keeps ontology in sync."""

    def test_update_assignment_callsign_updates_peer_context(self):
        """After updating LaForge → Forge, Scotty's peers should show 'Forge'."""
        onto = _build_ontology_with_agents()
        assert onto.update_assignment_callsign("engineering_agent", "Forge")

        # Scotty should see Forge (not LaForge) in peers
        ctx = onto.get_crew_context("engineer_agent")
        assert ctx is not None
        peers = ctx["peers"]
        assert any("Forge" in p for p in peers)
        assert not any("LaForge" in p for p in peers)

    def test_update_assignment_callsign_updates_reports_to(self):
        """After updating Number One → Sage, LaForge's reports_to should show Sage."""
        onto = _build_ontology_with_agents()
        assert onto.update_assignment_callsign("architect_agent", "Sage")

        ctx = onto.get_crew_context("engineering_agent")
        assert ctx is not None
        assert "Sage" in ctx["reports_to"]
        assert "Number One" not in ctx["reports_to"]

    def test_update_assignment_callsign_nonexistent_agent(self):
        """Returns False for unknown agent_type."""
        onto = _build_ontology_with_agents()
        assert not onto.update_assignment_callsign("nonexistent_agent", "Ghost")

    def test_naming_ceremony_syncs_ontology(self):
        """Verify runtime naming ceremony flow calls ontology sync."""
        onto = _build_ontology_with_agents()
        # Simulate what runtime.py does after naming ceremony
        new_callsign = "Forge"
        old_assignment = onto.get_assignment_for_agent("engineering_agent")
        assert old_assignment.callsign == "LaForge"

        # This is the sync call runtime.py now makes
        onto.update_assignment_callsign("engineering_agent", new_callsign)

        updated = onto.get_assignment_for_agent("engineering_agent")
        assert updated.callsign == "Forge"
        assert updated.agent_id == "eng-001"  # Preserved
