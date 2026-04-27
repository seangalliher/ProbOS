"""BF-244: Ontology callsign sync after naming ceremony."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from probos.crew_profile import CallsignRegistry
from probos.ontology import Assignment, Department, Post, VesselOntologyService
from probos.ontology.departments import DepartmentService
from probos.ontology.loader import OntologyLoader
from probos.ontology.ranks import RankService
from probos.startup.finalize import _sync_ontology_callsigns


def _build_ontology() -> VesselOntologyService:
    ontology = VesselOntologyService.__new__(VesselOntologyService)

    loader = OntologyLoader.__new__(OntologyLoader)
    loader.departments = {
        "bridge": Department(id="bridge", name="Bridge", description=""),
        "engineering": Department(id="engineering", name="Engineering", description=""),
    }
    loader.posts = {
        "first_officer": Post(
            id="first_officer",
            title="First Officer",
            department_id="bridge",
            reports_to=None,
            authority_over=["engineering_officer"],
            tier="crew",
        ),
        "engineering_officer": Post(
            id="engineering_officer",
            title="Engineering Officer",
            department_id="engineering",
            reports_to="first_officer",
            authority_over=["software_engineer", "scout", "data_analyst"],
            tier="crew",
        ),
        "software_engineer": Post(
            id="software_engineer",
            title="Software Engineer",
            department_id="engineering",
            reports_to="engineering_officer",
            tier="crew",
        ),
        "scout": Post(
            id="scout",
            title="Scout",
            department_id="engineering",
            reports_to="engineering_officer",
            tier="crew",
        ),
        "data_analyst": Post(
            id="data_analyst",
            title="Data Analyst",
            department_id="engineering",
            reports_to="engineering_officer",
            tier="crew",
        ),
    }
    loader.assignments = {
        "first_officer": Assignment(
            agent_type="first_officer",
            post_id="first_officer",
            callsign="Number One",
            agent_id="agent-first-officer",
        ),
        "engineering_officer": Assignment(
            agent_type="engineering_officer",
            post_id="engineering_officer",
            callsign="LaForge",
            agent_id="agent-engineering-officer",
        ),
        "builder": Assignment(
            agent_type="builder",
            post_id="software_engineer",
            callsign="Forge",
            agent_id="agent-builder",
        ),
        "scout": Assignment(
            agent_type="scout",
            post_id="scout",
            callsign="Wesley",
            agent_id="agent-scout",
        ),
        "data_analyst": Assignment(
            agent_type="data_analyst",
            post_id="data_analyst",
            callsign="Rahda",
            agent_id="agent-data-analyst",
        ),
    }
    loader.vessel_identity = None
    loader.alert_condition = "GREEN"
    loader.valid_alert_conditions = ["GREEN", "YELLOW", "RED"]
    loader._started_at = 0.0
    loader.role_templates = {}
    loader.qualification_paths = {}
    loader.alert_procedures = {}
    loader.message_patterns = []
    loader.knowledge_tiers = []

    ontology._loader = loader
    ontology._dept = DepartmentService(loader.departments, loader.posts, loader.assignments)
    ontology._ranks = RankService(loader.role_templates, loader.qualification_paths, loader.assignments)
    ontology._billet_registry = None
    return ontology


def _registry(callsigns: dict[str, str]) -> CallsignRegistry:
    registry = CallsignRegistry()
    for agent_type, callsign in callsigns.items():
        registry.set_callsign(agent_type, callsign)
    return registry


def _runtime(ontology: VesselOntologyService, callsigns: dict[str, str]) -> SimpleNamespace:
    return SimpleNamespace(ontology=ontology, callsign_registry=_registry(callsigns))


def test_finalize_syncs_renamed_callsign() -> None:
    ontology = _build_ontology()
    runtime = _runtime(ontology, {"builder": "Anvil"})

    _sync_ontology_callsigns(runtime)

    assignment = ontology.get_assignment_for_agent("builder")
    assert assignment is not None
    assert assignment.callsign == "Anvil"


def test_finalize_skips_unchanged_callsign() -> None:
    ontology = _build_ontology()
    runtime = _runtime(ontology, {"builder": "Forge"})

    with patch.object(ontology, "update_assignment_callsign") as mock_update:
        _sync_ontology_callsigns(runtime)

    mock_update.assert_not_called()



def test_finalize_syncs_multiple_renamed_agents() -> None:
    ontology = _build_ontology()
    runtime = _runtime(
        ontology,
        {
            "builder": "Anvil",
            "scout": "Horizon",
            "data_analyst": "Kira",
        },
    )

    _sync_ontology_callsigns(runtime)

    assert ontology.get_assignment_for_agent("builder").callsign == "Anvil"
    assert ontology.get_assignment_for_agent("scout").callsign == "Horizon"
    assert ontology.get_assignment_for_agent("data_analyst").callsign == "Kira"


def test_finalize_sync_tolerates_missing_assignment() -> None:
    ontology = _build_ontology()
    runtime = _runtime(ontology, {"nonexistent_test_agent": "Ghost"})

    _sync_ontology_callsigns(runtime)

    assert ontology.get_assignment_for_agent("nonexistent_test_agent") is None


def test_get_crew_context_returns_synced_callsign() -> None:
    ontology = _build_ontology()
    runtime = _runtime(ontology, {"builder": "Anvil"})

    _sync_ontology_callsigns(runtime)
    context = ontology.get_crew_context("builder")

    assert context is not None
    assert context["identity"]["callsign"] == "Anvil"
    assert context["identity"]["callsign"] != "Forge"


def test_peer_callsigns_reflect_sync() -> None:
    ontology = _build_ontology()
    runtime = _runtime(ontology, {"builder": "Anvil"})

    _sync_ontology_callsigns(runtime)
    context = ontology.get_crew_context("engineering_officer")

    assert context is not None
    assert any("Anvil" in peer for peer in context["peers"])
    assert not any("Forge" in peer for peer in context["peers"])


def test_reports_to_reflects_synced_callsign() -> None:
    ontology = _build_ontology()
    runtime = _runtime(ontology, {"engineering_officer": "Nova"})

    _sync_ontology_callsigns(runtime)
    context = ontology.get_crew_context("builder")

    assert context is not None
    assert "Nova" in context["reports_to"]
    assert "LaForge" not in context["reports_to"]


def test_sync_idempotent() -> None:
    ontology = _build_ontology()
    runtime = _runtime(ontology, {"builder": "Anvil"})

    _sync_ontology_callsigns(runtime)
    with patch.object(ontology, "update_assignment_callsign") as mock_update:
        _sync_ontology_callsigns(runtime)

    mock_update.assert_not_called()