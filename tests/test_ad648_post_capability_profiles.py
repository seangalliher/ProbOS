"""AD-648: Post Capability Profiles — Tests.

Verifies PostCapability dataclass, loader parsing, service methods,
prompt injection, and full organization.yaml loading with capability profiles.
"""

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from probos.ontology.models import Post, PostCapability
from probos.ontology.loader import OntologyLoader
from probos.ontology.service import VesselOntologyService
from probos.cognitive.cognitive_agent import CognitiveAgent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent(**kwargs) -> CognitiveAgent:
    agent = CognitiveAgent(agent_id="test-agent", instructions="Test agent.")
    agent.callsign = "Wesley"
    agent.agent_type = "scout"
    agent._runtime = kwargs.get("runtime", None)
    return agent


def _make_runtime(*, capabilities=None, does_not_have=None):
    rt = MagicMock()
    rt.trust_network.get_score.return_value = 0.65
    crew_ctx = {
        "identity": {"callsign": "Wesley", "post": "Scout", "agent_type": "scout"},
        "department": {"name": "Science"},
        "reports_to": "Chief Science Officer",
        "direct_reports": [],
        "peers": ["Data Analyst"],
        "vessel": {"name": "ProbOS", "version": "0.4", "alert_condition": "GREEN"},
    }
    if capabilities is not None:
        crew_ctx["capabilities"] = capabilities
    if does_not_have is not None:
        crew_ctx["does_not_have"] = does_not_have
    rt.ontology.get_crew_context.return_value = crew_ctx
    rt.is_cold_start = False
    return rt


# ---------------------------------------------------------------------------
# Test 1: PostCapability dataclass fields
# ---------------------------------------------------------------------------

class TestPostCapabilityFields:

    def test_fields_accessible(self):
        cap = PostCapability(
            id="scout_search",
            summary="Search GitHub",
            tools=["search_github"],
            outputs=["github_search_results"],
        )
        assert cap.id == "scout_search"
        assert cap.summary == "Search GitHub"
        assert cap.tools == ["search_github"]
        assert cap.outputs == ["github_search_results"]


# ---------------------------------------------------------------------------
# Test 2: Post with capabilities parses from constructor
# ---------------------------------------------------------------------------

class TestPostWithCapabilities:

    def test_post_with_capabilities(self):
        cap = PostCapability(id="test", summary="Test cap")
        post = Post(
            id="test_post",
            title="Test",
            department_id="science",
            reports_to=None,
            capabilities=[cap],
            does_not_have=["sensors"],
        )
        assert len(post.capabilities) == 1
        assert isinstance(post.capabilities[0], PostCapability)
        assert post.does_not_have == ["sensors"]


# ---------------------------------------------------------------------------
# Test 3: Loader parses capabilities from YAML
# ---------------------------------------------------------------------------

class TestLoaderParsesCapabilities:

    @pytest.mark.asyncio
    async def test_parses_capabilities(self, tmp_path):
        org_yaml = tmp_path / "organization.yaml"
        org_yaml.write_text("""
departments:
  - id: science
    name: Science
    description: Research

posts:
  - id: scout_officer
    title: Scout
    department: science
    reports_to: null
    capabilities:
      - id: scout_search
        summary: "Search GitHub repos"
        tools: [search_github]
        outputs: [github_search_results]
    does_not_have:
      - "sensors"
      - "telemetry streams"

assignments: []
""", encoding="utf-8")
        # Need vessel.yaml for loader
        vessel_yaml = tmp_path / "vessel.yaml"
        vessel_yaml.write_text("""
vessel:
  identity:
    name: TestShip
    version: "0.1"
    description: Test
""", encoding="utf-8")

        loader = OntologyLoader(tmp_path)
        await loader.initialize()

        post = loader.posts["scout_officer"]
        assert len(post.capabilities) == 1
        assert post.capabilities[0].id == "scout_search"
        assert post.capabilities[0].summary == "Search GitHub repos"
        assert post.capabilities[0].tools == ["search_github"]
        assert post.capabilities[0].outputs == ["github_search_results"]
        assert post.does_not_have == ["sensors", "telemetry streams"]


# ---------------------------------------------------------------------------
# Test 4: Loader handles posts without capabilities (backward compat)
# ---------------------------------------------------------------------------

class TestLoaderBackwardCompat:

    @pytest.mark.asyncio
    async def test_no_capabilities_defaults_empty(self, tmp_path):
        org_yaml = tmp_path / "organization.yaml"
        org_yaml.write_text("""
departments:
  - id: bridge
    name: Bridge
    description: Command

posts:
  - id: captain
    title: Captain
    department: bridge
    reports_to: null

assignments: []
""", encoding="utf-8")
        vessel_yaml = tmp_path / "vessel.yaml"
        vessel_yaml.write_text("""
vessel:
  identity:
    name: TestShip
    version: "0.1"
    description: Test
""", encoding="utf-8")

        loader = OntologyLoader(tmp_path)
        await loader.initialize()

        post = loader.posts["captain"]
        assert post.capabilities == []
        assert post.does_not_have == []


# ---------------------------------------------------------------------------
# Test 5: get_post_capabilities() returns capabilities
# ---------------------------------------------------------------------------

class TestGetPostCapabilities:

    @pytest.mark.asyncio
    async def test_returns_capabilities(self, tmp_path):
        org_yaml = tmp_path / "organization.yaml"
        org_yaml.write_text("""
departments:
  - id: science
    name: Science
    description: Research

posts:
  - id: scout_officer
    title: Scout
    department: science
    reports_to: null
    capabilities:
      - id: cap1
        summary: "Cap one"
      - id: cap2
        summary: "Cap two"

assignments: []
""", encoding="utf-8")
        vessel_yaml = tmp_path / "vessel.yaml"
        vessel_yaml.write_text("""
vessel:
  identity:
    name: TestShip
    version: "0.1"
    description: Test
""", encoding="utf-8")

        svc = VesselOntologyService(tmp_path)
        await svc.initialize()

        caps = svc.get_post_capabilities("scout_officer")
        assert len(caps) == 2
        assert all(isinstance(c, PostCapability) for c in caps)


# ---------------------------------------------------------------------------
# Test 6: get_post_capabilities() returns empty for unknown post
# ---------------------------------------------------------------------------

class TestGetPostCapabilitiesUnknown:

    @pytest.mark.asyncio
    async def test_unknown_post(self, tmp_path):
        org_yaml = tmp_path / "organization.yaml"
        org_yaml.write_text("""
departments: []
posts: []
assignments: []
""", encoding="utf-8")
        vessel_yaml = tmp_path / "vessel.yaml"
        vessel_yaml.write_text("""
vessel:
  identity:
    name: TestShip
    version: "0.1"
    description: Test
""", encoding="utf-8")

        svc = VesselOntologyService(tmp_path)
        await svc.initialize()

        assert svc.get_post_capabilities("nonexistent") == []


# ---------------------------------------------------------------------------
# Test 7: get_agent_capabilities() resolves through assignment
# ---------------------------------------------------------------------------

class TestGetAgentCapabilities:

    @pytest.mark.asyncio
    async def test_resolves_through_assignment(self, tmp_path):
        org_yaml = tmp_path / "organization.yaml"
        org_yaml.write_text("""
departments:
  - id: science
    name: Science
    description: Research

posts:
  - id: scout_officer
    title: Scout
    department: science
    reports_to: null
    capabilities:
      - id: scout_search
        summary: "Search GitHub"

assignments:
  - agent_type: scout
    post_id: scout_officer
    callsign: Wesley
""", encoding="utf-8")
        vessel_yaml = tmp_path / "vessel.yaml"
        vessel_yaml.write_text("""
vessel:
  identity:
    name: TestShip
    version: "0.1"
    description: Test
""", encoding="utf-8")

        svc = VesselOntologyService(tmp_path)
        await svc.initialize()

        caps = svc.get_agent_capabilities("scout")
        assert len(caps) == 1
        assert caps[0].id == "scout_search"


# ---------------------------------------------------------------------------
# Test 8: get_post_negative_grounding() returns does_not_have
# ---------------------------------------------------------------------------

class TestGetNegativeGrounding:

    @pytest.mark.asyncio
    async def test_returns_negatives(self, tmp_path):
        org_yaml = tmp_path / "organization.yaml"
        org_yaml.write_text("""
departments:
  - id: science
    name: Science
    description: Research

posts:
  - id: scout_officer
    title: Scout
    department: science
    reports_to: null
    does_not_have:
      - "sensors"
      - "telemetry"

assignments: []
""", encoding="utf-8")
        vessel_yaml = tmp_path / "vessel.yaml"
        vessel_yaml.write_text("""
vessel:
  identity:
    name: TestShip
    version: "0.1"
    description: Test
""", encoding="utf-8")

        svc = VesselOntologyService(tmp_path)
        await svc.initialize()

        negatives = svc.get_post_negative_grounding("scout_officer")
        assert negatives == ["sensors", "telemetry"]


# ---------------------------------------------------------------------------
# Test 9: get_crew_context() includes capabilities
# ---------------------------------------------------------------------------

class TestCrewContextCapabilities:

    @pytest.mark.asyncio
    async def test_includes_capabilities(self, tmp_path):
        org_yaml = tmp_path / "organization.yaml"
        org_yaml.write_text("""
departments:
  - id: science
    name: Science
    description: Research

posts:
  - id: scout_officer
    title: Scout
    department: science
    reports_to: null
    capabilities:
      - id: scout_search
        summary: "Search GitHub"
        tools: [search_github]
        outputs: [results]

assignments:
  - agent_type: scout
    post_id: scout_officer
    callsign: Wesley
""", encoding="utf-8")
        vessel_yaml = tmp_path / "vessel.yaml"
        vessel_yaml.write_text("""
vessel:
  identity:
    name: TestShip
    version: "0.1"
    description: Test
""", encoding="utf-8")

        svc = VesselOntologyService(tmp_path)
        await svc.initialize()

        ctx = svc.get_crew_context("scout")
        assert "capabilities" in ctx
        assert len(ctx["capabilities"]) == 1
        assert ctx["capabilities"][0]["id"] == "scout_search"
        assert ctx["capabilities"][0]["tools"] == ["search_github"]


# ---------------------------------------------------------------------------
# Test 10: get_crew_context() includes does_not_have
# ---------------------------------------------------------------------------

class TestCrewContextDoesNotHave:

    @pytest.mark.asyncio
    async def test_includes_does_not_have(self, tmp_path):
        org_yaml = tmp_path / "organization.yaml"
        org_yaml.write_text("""
departments:
  - id: science
    name: Science
    description: Research

posts:
  - id: scout_officer
    title: Scout
    department: science
    reports_to: null
    does_not_have:
      - "sensors"

assignments:
  - agent_type: scout
    post_id: scout_officer
    callsign: Wesley
""", encoding="utf-8")
        vessel_yaml = tmp_path / "vessel.yaml"
        vessel_yaml.write_text("""
vessel:
  identity:
    name: TestShip
    version: "0.1"
    description: Test
""", encoding="utf-8")

        svc = VesselOntologyService(tmp_path)
        await svc.initialize()

        ctx = svc.get_crew_context("scout")
        assert "does_not_have" in ctx
        assert ctx["does_not_have"] == ["sensors"]


# ---------------------------------------------------------------------------
# Test 11: get_crew_context() omits capabilities when empty
# ---------------------------------------------------------------------------

class TestCrewContextOmitsEmpty:

    @pytest.mark.asyncio
    async def test_omits_when_empty(self, tmp_path):
        org_yaml = tmp_path / "organization.yaml"
        org_yaml.write_text("""
departments:
  - id: bridge
    name: Bridge
    description: Command

posts:
  - id: captain
    title: Captain
    department: bridge
    reports_to: null

assignments:
  - agent_type: captain_agent
    post_id: captain
    callsign: Captain
""", encoding="utf-8")
        vessel_yaml = tmp_path / "vessel.yaml"
        vessel_yaml.write_text("""
vessel:
  identity:
    name: TestShip
    version: "0.1"
    description: Test
""", encoding="utf-8")

        svc = VesselOntologyService(tmp_path)
        await svc.initialize()

        ctx = svc.get_crew_context("captain_agent")
        assert "capabilities" not in ctx
        assert "does_not_have" not in ctx


# ---------------------------------------------------------------------------
# Test 12: Ontology context renders capabilities into prompt text
# ---------------------------------------------------------------------------

class TestOntologyRendersCapabilities:

    def test_renders_capabilities(self):
        rt = _make_runtime(
            capabilities=[
                {"id": "scout_search", "summary": "Search GitHub", "tools": [], "outputs": []},
            ],
        )
        agent = _make_agent(runtime=rt)
        with patch.object(agent, '_build_temporal_context', return_value=""):
            result = agent._build_cognitive_baseline({})
        onto = result.get("_ontology_context", "")
        assert "Your post capabilities (what you actually do):" in onto
        assert "Search GitHub" in onto


# ---------------------------------------------------------------------------
# Test 13: Ontology context renders negative grounding into prompt text
# ---------------------------------------------------------------------------

class TestOntologyRendersNegativeGrounding:

    def test_renders_negative_grounding(self):
        rt = _make_runtime(
            does_not_have=[
                "sensors or sensory arrays of any kind",
                "telemetry streams",
            ],
        )
        agent = _make_agent(runtime=rt)
        with patch.object(agent, '_build_temporal_context', return_value=""):
            result = agent._build_cognitive_baseline({})
        onto = result.get("_ontology_context", "")
        assert "You do NOT have (do not claim or reference these):" in onto
        assert "sensors or sensory arrays of any kind" in onto
        assert "telemetry streams" in onto


# ---------------------------------------------------------------------------
# Test 14: Full organization.yaml loads without errors
# ---------------------------------------------------------------------------

class TestFullOrganizationYaml:

    @pytest.mark.asyncio
    async def test_full_yaml_loads(self):
        config_dir = Path(__file__).resolve().parent.parent / "config" / "ontology"
        if not (config_dir / "organization.yaml").exists():
            pytest.skip("organization.yaml not found")

        svc = VesselOntologyService(config_dir)
        await svc.initialize()

        # All 17 posts should parse
        assert len(svc._loader.posts) == 17

        # Scout should have capabilities and negative grounding
        scout = svc._loader.posts.get("scout_officer")
        assert scout is not None
        assert len(scout.capabilities) >= 2
        assert len(scout.does_not_have) >= 4
