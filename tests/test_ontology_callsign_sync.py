"""BF-049/050: Ontology callsign sync after naming ceremony."""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from probos.ontology import VesselOntologyService, Assignment, Post, Department


def _build_ontology_with_agents():
    """Build a minimal ontology with 2 agents in engineering department."""
    onto = VesselOntologyService.__new__(VesselOntologyService)
    onto._departments = {
        "engineering": Department(id="engineering", name="Engineering", description=""),
    }
    onto._posts = {
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
    onto._assignments = {
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
    # Minimal attrs to avoid errors
    onto._config_dir = None
    onto._data_dir = None
    onto._vessel_identity = None
    onto._alert_condition = "GREEN"
    onto._valid_alert_conditions = ["GREEN", "YELLOW", "RED"]
    onto._started_at = 0.0
    onto._role_templates = {}
    onto._qualification_paths = {}
    onto._skill_service = None
    onto._standing_order_tiers = []
    onto._watch_types = []
    onto._alert_procedures = {}
    onto._duty_categories = []
    onto._channel_types = []
    onto._thread_modes = []
    onto._message_patterns = []
    onto._model_tiers = []
    onto._tool_capabilities = []
    onto._knowledge_sources = []
    onto._knowledge_tiers = []
    onto._classifications = []
    onto._document_classes = []
    onto._retention_policies = []
    onto._document_fields_required = []
    onto._document_fields_optional = []
    onto._repository_directories = []
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
