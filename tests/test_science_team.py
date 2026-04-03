"""Tests for AD-560: Science Department Expansion — Analytical Pyramid.

Tests cover:
- Agent class instantiation and attributes (7a)
- Organization ontology validation (7b)
- Standing orders / crew profiles validation (7c)
- Integration: Ward Room membership, department mapping, chain of command (7d)
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from probos.agents.science import (
    DataAnalystAgent,
    ResearchSpecialistAgent,
    SystemsAnalystAgent,
)
from probos.agents.science.data_analyst import DataAnalystAgent as DA_Direct
from probos.agents.science.systems_analyst import SystemsAnalystAgent as SA_Direct
from probos.agents.science.research_specialist import (
    ResearchSpecialistAgent as RS_Direct,
)

# Config root for ontology / standing orders files
_CONFIG_ROOT = Path(__file__).resolve().parent.parent / "config"
_ONTOLOGY_DIR = _CONFIG_ROOT / "ontology"
_STANDING_ORDERS_DIR = _CONFIG_ROOT / "standing_orders"
_CREW_PROFILES_DIR = _STANDING_ORDERS_DIR / "crew_profiles"


@pytest.fixture(autouse=True)
def _clear_decision_cache():
    """Clear CognitiveAgent decision cache between tests to prevent pollution."""
    from probos.cognitive.cognitive_agent import _DECISION_CACHES

    _DECISION_CACHES.clear()
    yield
    _DECISION_CACHES.clear()


# -----------------------------------------------------------------------
# 7a. Unit tests for each agent class
# -----------------------------------------------------------------------


class TestDataAnalystAgent:
    """DataAnalystAgent class attributes and instantiation."""

    def test_instantiation(self):
        agent = DataAnalystAgent(agent_id="da-1")
        assert agent is not None

    def test_agent_type(self):
        agent = DataAnalystAgent(agent_id="da-1")
        assert agent.agent_type == "data_analyst"

    def test_tier(self):
        agent = DataAnalystAgent(agent_id="da-1")
        assert agent.tier == "domain"

    def test_default_capabilities(self):
        agent = DataAnalystAgent(agent_id="da-1")
        caps = {c.can for c in agent.default_capabilities}
        assert "analyze_telemetry" in caps
        assert "flag_anomalies" in caps

    def test_intent_descriptors(self):
        agent = DataAnalystAgent(agent_id="da-1")
        names = {d.name for d in agent.intent_descriptors}
        assert "telemetry_report" in names
        assert "baseline_update" in names
        assert "anomaly_flag" in names

    def test_handled_intents_match_descriptors(self):
        agent = DataAnalystAgent(agent_id="da-1")
        descriptor_names = {d.name for d in agent.intent_descriptors}
        assert agent._handled_intents == descriptor_names

    def test_pool_defaults_to_science(self):
        agent = DataAnalystAgent(agent_id="da-1")
        assert agent.pool == "science"


class TestSystemsAnalystAgent:
    """SystemsAnalystAgent class attributes and instantiation."""

    def test_instantiation(self):
        agent = SystemsAnalystAgent(agent_id="sa-1")
        assert agent is not None

    def test_agent_type(self):
        agent = SystemsAnalystAgent(agent_id="sa-1")
        assert agent.agent_type == "systems_analyst"

    def test_tier(self):
        agent = SystemsAnalystAgent(agent_id="sa-1")
        assert agent.tier == "domain"

    def test_default_capabilities(self):
        agent = SystemsAnalystAgent(agent_id="sa-1")
        caps = {c.can for c in agent.default_capabilities}
        assert "analyze_emergence" in caps
        assert "synthesize_cross_system" in caps

    def test_intent_descriptors(self):
        agent = SystemsAnalystAgent(agent_id="sa-1")
        names = {d.name for d in agent.intent_descriptors}
        assert "emergence_analysis" in names
        assert "system_synthesis" in names
        assert "pattern_advisory" in names

    def test_handled_intents_match_descriptors(self):
        agent = SystemsAnalystAgent(agent_id="sa-1")
        descriptor_names = {d.name for d in agent.intent_descriptors}
        assert agent._handled_intents == descriptor_names

    def test_pool_defaults_to_science(self):
        agent = SystemsAnalystAgent(agent_id="sa-1")
        assert agent.pool == "science"


class TestResearchSpecialistAgent:
    """ResearchSpecialistAgent class attributes and instantiation."""

    def test_instantiation(self):
        agent = ResearchSpecialistAgent(agent_id="rs-1")
        assert agent is not None

    def test_agent_type(self):
        agent = ResearchSpecialistAgent(agent_id="rs-1")
        assert agent.agent_type == "research_specialist"

    def test_tier(self):
        agent = ResearchSpecialistAgent(agent_id="rs-1")
        assert agent.tier == "domain"

    def test_default_capabilities(self):
        agent = ResearchSpecialistAgent(agent_id="rs-1")
        caps = {c.can for c in agent.default_capabilities}
        assert "investigate" in caps
        assert "review_literature" in caps

    def test_intent_descriptors(self):
        agent = ResearchSpecialistAgent(agent_id="rs-1")
        names = {d.name for d in agent.intent_descriptors}
        assert "research_investigation" in names
        assert "literature_review" in names
        assert "research_proposal" in names

    def test_handled_intents_match_descriptors(self):
        agent = ResearchSpecialistAgent(agent_id="rs-1")
        descriptor_names = {d.name for d in agent.intent_descriptors}
        assert agent._handled_intents == descriptor_names

    def test_pool_defaults_to_science(self):
        agent = ResearchSpecialistAgent(agent_id="rs-1")
        assert agent.pool == "science"


class TestPackageReExports:
    """Package __init__.py re-exports work correctly."""

    def test_data_analyst_re_export(self):
        assert DA_Direct is DataAnalystAgent

    def test_systems_analyst_re_export(self):
        assert SA_Direct is SystemsAnalystAgent

    def test_research_specialist_re_export(self):
        assert RS_Direct is ResearchSpecialistAgent


# -----------------------------------------------------------------------
# 7b. Organization ontology validation
# -----------------------------------------------------------------------


class TestOrganizationOntology:
    """Validate organization.yaml has the three new posts and assignments."""

    @pytest.fixture
    def org_data(self) -> dict:
        with open(_ONTOLOGY_DIR / "organization.yaml") as f:
            return yaml.safe_load(f)

    def test_data_analyst_post_exists(self, org_data):
        post_ids = {p["id"] for p in org_data["posts"]}
        assert "data_analyst_officer" in post_ids

    def test_systems_analyst_post_exists(self, org_data):
        post_ids = {p["id"] for p in org_data["posts"]}
        assert "systems_analyst_officer" in post_ids

    def test_research_specialist_post_exists(self, org_data):
        post_ids = {p["id"] for p in org_data["posts"]}
        assert "research_specialist_officer" in post_ids

    def test_posts_report_to_chief_science(self, org_data):
        new_post_ids = {
            "data_analyst_officer",
            "systems_analyst_officer",
            "research_specialist_officer",
        }
        for post in org_data["posts"]:
            if post["id"] in new_post_ids:
                assert post["reports_to"] == "chief_science"

    def test_posts_are_science_department(self, org_data):
        new_post_ids = {
            "data_analyst_officer",
            "systems_analyst_officer",
            "research_specialist_officer",
        }
        for post in org_data["posts"]:
            if post["id"] in new_post_ids:
                assert post["department"] == "science"

    def test_chief_science_authority_includes_new_posts(self, org_data):
        for post in org_data["posts"]:
            if post["id"] == "chief_science":
                auth = post["authority_over"]
                assert "data_analyst_officer" in auth
                assert "systems_analyst_officer" in auth
                assert "research_specialist_officer" in auth
                break
        else:
            pytest.fail("chief_science post not found")

    def test_data_analyst_assignment(self, org_data):
        found = [a for a in org_data["assignments"] if a["agent_type"] == "data_analyst"]
        assert len(found) == 1
        assert found[0]["callsign"] == "Rahda"
        assert found[0]["post_id"] == "data_analyst_officer"

    def test_systems_analyst_assignment(self, org_data):
        found = [a for a in org_data["assignments"] if a["agent_type"] == "systems_analyst"]
        assert len(found) == 1
        assert found[0]["callsign"] == "Dax"
        assert found[0]["post_id"] == "systems_analyst_officer"

    def test_research_specialist_assignment(self, org_data):
        found = [a for a in org_data["assignments"] if a["agent_type"] == "research_specialist"]
        assert len(found) == 1
        assert found[0]["callsign"] == "Brahms"
        assert found[0]["post_id"] == "research_specialist_officer"


# -----------------------------------------------------------------------
# 7c. Standing orders and crew profiles validation
# -----------------------------------------------------------------------


class TestCrewProfiles:
    """Validate crew profile YAML files for Science agents."""

    @pytest.mark.parametrize(
        "filename,callsign,department",
        [
            ("data_analyst.yaml", "Rahda", "science"),
            ("systems_analyst.yaml", "Dax", "science"),
            ("research_specialist.yaml", "Brahms", "science"),
        ],
    )
    def test_profile_exists_and_parses(self, filename, callsign, department):
        path = _CREW_PROFILES_DIR / filename
        assert path.exists(), f"{filename} not found"
        with open(path) as f:
            data = yaml.safe_load(f)
        assert data["callsign"] == callsign
        assert data["department"] == department

    @pytest.mark.parametrize(
        "filename",
        ["data_analyst.yaml", "systems_analyst.yaml", "research_specialist.yaml"],
    )
    def test_personality_traits_in_range(self, filename):
        with open(_CREW_PROFILES_DIR / filename) as f:
            data = yaml.safe_load(f)
        personality = data["personality"]
        for trait, value in personality.items():
            assert 0.0 <= value <= 1.0, f"{filename}: {trait}={value} out of range"


class TestStandingOrders:
    """Validate personal standing orders markdown files exist."""

    @pytest.mark.parametrize(
        "filename", ["data_analyst.md", "systems_analyst.md", "research_specialist.md"]
    )
    def test_standing_orders_exist(self, filename):
        path = _STANDING_ORDERS_DIR / filename
        assert path.exists(), f"{filename} not found"
        content = path.read_text()
        assert len(content) > 100, f"{filename} looks too short"


class TestDepartmentProtocols:
    """Validate science.md department protocols include new agents."""

    def test_science_md_mentions_analytical_pyramid(self):
        content = (_STANDING_ORDERS_DIR / "science.md").read_text()
        assert "Analytical Pyramid" in content

    def test_science_md_mentions_all_agents(self):
        content = (_STANDING_ORDERS_DIR / "science.md").read_text()
        assert "Rahda" in content
        assert "Dax" in content
        assert "Brahms" in content
        assert "Horizon" in content


class TestSkillsTemplates:
    """Validate skills.yaml includes role templates for new posts."""

    @pytest.fixture
    def skills_data(self) -> dict:
        with open(_ONTOLOGY_DIR / "skills.yaml") as f:
            return yaml.safe_load(f)

    def test_data_analyst_template(self, skills_data):
        assert "data_analyst_officer" in skills_data["role_templates"]

    def test_systems_analyst_template(self, skills_data):
        assert "systems_analyst_officer" in skills_data["role_templates"]

    def test_research_specialist_template(self, skills_data):
        assert "research_specialist_officer" in skills_data["role_templates"]


# -----------------------------------------------------------------------
# 7d. Integration tests — Ward Room, department mapping, chain of command
# -----------------------------------------------------------------------


class TestWardRoomMembership:
    """New agents should be eligible for Ward Room participation."""

    def test_data_analyst_in_ward_room_crew(self):
        from probos.crew_utils import _WARD_ROOM_CREW

        assert "data_analyst" in _WARD_ROOM_CREW

    def test_systems_analyst_in_ward_room_crew(self):
        from probos.crew_utils import _WARD_ROOM_CREW

        assert "systems_analyst" in _WARD_ROOM_CREW

    def test_research_specialist_in_ward_room_crew(self):
        from probos.crew_utils import _WARD_ROOM_CREW

        assert "research_specialist" in _WARD_ROOM_CREW

    def test_is_crew_agent_recognizes_new_agents(self):
        from probos.crew_utils import is_crew_agent

        class _FakeAgent:
            def __init__(self, t):
                self.agent_type = t

        assert is_crew_agent(_FakeAgent("data_analyst"))
        assert is_crew_agent(_FakeAgent("systems_analyst"))
        assert is_crew_agent(_FakeAgent("research_specialist"))


class TestDepartmentMapping:
    """New agents map to the science department."""

    def test_data_analyst_department(self):
        from probos.cognitive.standing_orders import _AGENT_DEPARTMENTS

        assert _AGENT_DEPARTMENTS.get("data_analyst") == "science"

    def test_systems_analyst_department(self):
        from probos.cognitive.standing_orders import _AGENT_DEPARTMENTS

        assert _AGENT_DEPARTMENTS.get("systems_analyst") == "science"

    def test_research_specialist_department(self):
        from probos.cognitive.standing_orders import _AGENT_DEPARTMENTS

        assert _AGENT_DEPARTMENTS.get("research_specialist") == "science"


class TestChainOfCommand:
    """Validate chain: new agents → chief_science → first_officer → captain."""

    @pytest.fixture
    def org_data(self) -> dict:
        with open(_ONTOLOGY_DIR / "organization.yaml") as f:
            return yaml.safe_load(f)

    def _get_post(self, org_data, post_id):
        for p in org_data["posts"]:
            if p["id"] == post_id:
                return p
        return None

    def test_chain_data_analyst(self, org_data):
        post = self._get_post(org_data, "data_analyst_officer")
        assert post["reports_to"] == "chief_science"
        chief = self._get_post(org_data, "chief_science")
        assert chief["reports_to"] == "first_officer"
        fo = self._get_post(org_data, "first_officer")
        assert fo["reports_to"] == "captain"

    def test_chain_systems_analyst(self, org_data):
        post = self._get_post(org_data, "systems_analyst_officer")
        assert post["reports_to"] == "chief_science"

    def test_chain_research_specialist(self, org_data):
        post = self._get_post(org_data, "research_specialist_officer")
        assert post["reports_to"] == "chief_science"
