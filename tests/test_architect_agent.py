"""Tests for ArchitectAgent and ArchitectProposal (AD-306)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.architect import ArchitectAgent, ArchitectProposal
from probos.cognitive.builder import BuildSpec
from probos.cognitive.codebase_index import CodebaseIndex
from probos.types import IntentDescriptor, IntentMessage


# ---------------------------------------------------------------------------
# Sample proposal block for reuse across tests
# ---------------------------------------------------------------------------

SAMPLE_PROPOSAL = """
Some preamble text from the LLM...

===PROPOSAL===
TITLE: Add Network Egress Policy
SUMMARY: Implement a network egress policy system that controls outbound connections from ProbOS agents.
RATIONALE: Phase 31 Security roadmap requires outbound traffic control before federation.
ROADMAP_REF: Phase 31 — Security Team
PRIORITY: high
AD_NUMBER: AD-310

TARGET_FILES:
- src/probos/security/egress.py
- src/probos/security/policy.py

REFERENCE_FILES:
- src/probos/consensus/trust.py
- src/probos/mesh/routing.py

TEST_FILES:
- tests/test_egress_policy.py

CONSTRAINTS:
- Do NOT modify existing trust scoring
- Do NOT add external dependencies

DEPENDENCIES:
- TrustNetwork must be operational
- SecurityAgent pool must exist

RISKS:
- May increase latency on outbound requests
- Policy evaluation could race with agent lifecycle

DESCRIPTION:
Create an EgressPolicy class in src/probos/security/egress.py that controls
outbound network connections from ProbOS agents.

The policy engine should:
- Maintain an allowlist of approved domains per agent type
- Check trust score before allowing egress (min threshold 0.6)
- Log all egress attempts to the event log

class EgressPolicy:
    def __init__(self, trust_network, event_log):
        ...
    async def check_egress(self, agent_id, target_url) -> bool:
        ...
===END PROPOSAL===

Some trailing text.
"""


MINIMAL_PROPOSAL = """===PROPOSAL===
TITLE: Simple Feature
AD_NUMBER: 400

DESCRIPTION:
Just a basic feature with minimal fields.
===END PROPOSAL==="""


# ---------------------------------------------------------------------------
# ArchitectProposal dataclass tests
# ---------------------------------------------------------------------------


class TestArchitectProposalDefaults:
    def test_default_fields(self):
        """ArchitectProposal has correct defaults for optional fields."""
        spec = BuildSpec(title="T", description="D")
        p = ArchitectProposal(title="T", summary="S", rationale="R", build_spec=spec)
        assert p.roadmap_ref == ""
        assert p.priority == "medium"
        assert p.dependencies == []
        assert p.risks == []

    def test_required_fields(self):
        """ArchitectProposal requires title, summary, rationale, build_spec."""
        spec = BuildSpec(title="T", description="D")
        p = ArchitectProposal(
            title="My Feature",
            summary="A feature",
            rationale="Needed now",
            build_spec=spec,
        )
        assert p.title == "My Feature"
        assert p.summary == "A feature"
        assert p.rationale == "Needed now"
        assert p.build_spec is spec


class TestArchitectProposalPopulation:
    def test_full_population(self):
        """ArchitectProposal populates all fields."""
        spec = BuildSpec(
            title="Full",
            description="Full desc",
            target_files=["src/a.py"],
            ad_number=999,
        )
        p = ArchitectProposal(
            title="Full",
            summary="Full summary",
            rationale="Full rationale",
            build_spec=spec,
            roadmap_ref="Phase 99",
            priority="high",
            dependencies=["dep1", "dep2"],
            risks=["risk1"],
        )
        assert p.priority == "high"
        assert p.roadmap_ref == "Phase 99"
        assert len(p.dependencies) == 2
        assert len(p.risks) == 1
        assert p.build_spec.ad_number == 999


# ---------------------------------------------------------------------------
# ArchitectAgent class tests
# ---------------------------------------------------------------------------


class TestArchitectAgentClass:
    def test_inherits_from_cognitive_agent(self):
        """ArchitectAgent inherits from CognitiveAgent."""
        from probos.cognitive.cognitive_agent import CognitiveAgent

        assert issubclass(ArchitectAgent, CognitiveAgent)

    def test_agent_type(self):
        """ArchitectAgent has agent_type='architect'."""
        assert ArchitectAgent.agent_type == "architect"

    def test_tier(self):
        """ArchitectAgent has tier='domain'."""
        assert ArchitectAgent.tier == "domain"


class TestArchitectAgentAttributes:
    def test_handled_intents(self):
        """ArchitectAgent handles 'design_feature' intent."""
        assert "design_feature" in ArchitectAgent._handled_intents

    def test_intent_descriptors(self):
        """ArchitectAgent has a single intent descriptor for design_feature."""
        assert len(ArchitectAgent.intent_descriptors) >= 1
        desc = ArchitectAgent.intent_descriptors[0]
        assert isinstance(desc, IntentDescriptor)
        assert desc.name == "design_feature"
        assert desc.requires_consensus is False
        assert desc.requires_reflect is True

    def test_instructions_non_empty(self):
        """ArchitectAgent has non-empty instructions."""
        assert ArchitectAgent.instructions
        assert "===PROPOSAL===" in ArchitectAgent.instructions


class TestArchitectAgentTier:
    def test_resolve_tier_returns_deep(self):
        """_resolve_tier() returns 'deep'."""
        agent = ArchitectAgent(
            agent_id="test-arch-1",
            llm_client=MagicMock(),
        )
        assert agent._resolve_tier() == "deep"


# ---------------------------------------------------------------------------
# Proposal parsing tests
# ---------------------------------------------------------------------------


class TestProposalParsingComplete:
    def test_parse_full_proposal(self):
        """Parse a complete ===PROPOSAL=== block with all fields."""
        proposal = ArchitectAgent._parse_proposal(SAMPLE_PROPOSAL)
        assert proposal is not None
        assert proposal.title == "Add Network Egress Policy"
        assert "network egress policy" in proposal.summary.lower()
        assert "Phase 31" in proposal.rationale
        assert proposal.roadmap_ref == "Phase 31 — Security Team"
        assert proposal.priority == "high"
        assert proposal.build_spec.ad_number == 310
        assert "src/probos/security/egress.py" in proposal.build_spec.target_files
        assert "src/probos/consensus/trust.py" in proposal.build_spec.reference_files
        assert "tests/test_egress_policy.py" in proposal.build_spec.test_files
        assert len(proposal.build_spec.constraints) == 2
        assert len(proposal.dependencies) == 2
        assert len(proposal.risks) == 2
        assert "EgressPolicy" in proposal.build_spec.description


class TestProposalParsingMinimal:
    def test_parse_minimal_proposal(self):
        """Parse a block with only required fields, verify defaults."""
        proposal = ArchitectAgent._parse_proposal(MINIMAL_PROPOSAL)
        assert proposal is not None
        assert proposal.title == "Simple Feature"
        assert proposal.summary == ""
        assert proposal.rationale == ""
        assert proposal.roadmap_ref == ""
        assert proposal.priority == "medium"
        assert proposal.dependencies == []
        assert proposal.risks == []
        assert proposal.build_spec.ad_number == 400
        assert "basic feature" in proposal.build_spec.description.lower()


class TestProposalParsingNoBlock:
    def test_no_proposal_block(self):
        """Returns None when no ===PROPOSAL=== found."""
        result = ArchitectAgent._parse_proposal("Just some text without markers.")
        assert result is None

    def test_incomplete_block(self):
        """Returns None when ===END PROPOSAL=== is missing."""
        result = ArchitectAgent._parse_proposal("===PROPOSAL===\nTITLE: Foo\n")
        assert result is None


class TestProposalParsingAdFormats:
    def test_ad_with_prefix(self):
        """Handle 'AD-306' format."""
        text = "===PROPOSAL===\nTITLE: T\nAD_NUMBER: AD-306\n\nDESCRIPTION:\nd\n===END PROPOSAL==="
        p = ArchitectAgent._parse_proposal(text)
        assert p is not None
        assert p.build_spec.ad_number == 306

    def test_ad_numeric_only(self):
        """Handle '306' format."""
        text = "===PROPOSAL===\nTITLE: T\nAD_NUMBER: 306\n\nDESCRIPTION:\nd\n===END PROPOSAL==="
        p = ArchitectAgent._parse_proposal(text)
        assert p is not None
        assert p.build_spec.ad_number == 306

    def test_ad_with_range(self):
        """Handle 'AD-306/307' format — takes first number."""
        text = "===PROPOSAL===\nTITLE: T\nAD_NUMBER: AD-306/307\n\nDESCRIPTION:\nd\n===END PROPOSAL==="
        p = ArchitectAgent._parse_proposal(text)
        assert p is not None
        assert p.build_spec.ad_number == 306

    def test_ad_missing(self):
        """Missing AD_NUMBER defaults to 0."""
        text = "===PROPOSAL===\nTITLE: T\n\nDESCRIPTION:\nd\n===END PROPOSAL==="
        p = ArchitectAgent._parse_proposal(text)
        assert p is not None
        assert p.build_spec.ad_number == 0


# ---------------------------------------------------------------------------
# User message formatting tests
# ---------------------------------------------------------------------------


class TestUserMessageFormatting:
    def test_includes_feature_and_context(self):
        """_build_user_message includes feature, phase, and codebase context."""
        agent = ArchitectAgent(
            agent_id="test-arch-2",
            llm_client=MagicMock(),
        )
        obs = {
            "params": {"feature": "Network Egress", "phase": "31"},
            "codebase_context": "## Relevant Files\n- src/probos/mesh/routing.py",
        }
        msg = agent._build_user_message(obs)
        assert "Network Egress" in msg
        assert "Phase: 31" in msg
        assert "Relevant Files" in msg
        assert "verify all file paths" in msg

    def test_no_context(self):
        """_build_user_message handles missing codebase context."""
        agent = ArchitectAgent(
            agent_id="test-arch-3",
            llm_client=MagicMock(),
        )
        obs = {
            "params": {"feature": "Something"},
            "codebase_context": "",
        }
        msg = agent._build_user_message(obs)
        assert "Something" in msg
        assert "no codebase context available" in msg


# ---------------------------------------------------------------------------
# Perceive tests
# ---------------------------------------------------------------------------


class TestPerceiveWithRuntime:
    @pytest.mark.asyncio
    async def test_perceive_gathers_context(self):
        """perceive() populates codebase_context from runtime's codebase_index."""
        mock_index = MagicMock()
        mock_index.query.return_value = {
            "matching_files": [
                {"path": "src/probos/mesh/routing.py", "relevance": 5, "docstring": "Routing"},
            ],
            "matching_methods": [],
        }
        mock_index.get_agent_map.return_value = [
            {"type": "builder", "tier": "domain", "module": "cognitive.builder", "bases": ["CognitiveAgent"]},
        ]
        mock_index.read_doc_sections.return_value = "## Phase 31\nSecurity stuff"
        mock_index.read_source.return_value = "| AD-305 | Last decision |\n"
        mock_index.get_layer_map.return_value = {"cognitive": ["cognitive/builder.py", "cognitive/architect.py"]}
        mock_index.find_tests_for.return_value = []
        mock_index.find_callers.return_value = []
        mock_index.get_api_surface.return_value = []
        mock_index.get_full_api_surface.return_value = {}
        mock_index.get_imports.return_value = []
        mock_index.find_importers.return_value = []
        mock_index._file_tree = {
            "src/probos/mesh/routing.py": {"classes": [], "docstring": "Routing"},
        }

        mock_runtime = MagicMock()
        mock_runtime.codebase_index = mock_index

        mock_llm = AsyncMock()
        mock_llm.complete.return_value = MagicMock(content="src/probos/mesh/routing.py")

        agent = ArchitectAgent(
            agent_id="test-arch-4",
            llm_client=mock_llm,
            runtime=mock_runtime,
        )

        intent = IntentMessage(
            intent="design_feature",
            params={"feature": "security policy", "phase": "31"},
        )
        obs = await agent.perceive(intent)

        assert "codebase_context" in obs
        ctx = obs["codebase_context"]
        assert "Relevant Files" in ctx
        assert "routing.py" in ctx
        assert "Registered Agents" in ctx
        assert "builder" in ctx
        assert "File Tree" in ctx
        assert "cognitive" in ctx


class TestPerceiveWithoutRuntime:
    @pytest.mark.asyncio
    async def test_perceive_without_runtime(self):
        """perceive() works gracefully when no runtime is set."""
        agent = ArchitectAgent(
            agent_id="test-arch-5",
            llm_client=MagicMock(),
        )

        intent = IntentMessage(
            intent="design_feature",
            params={"feature": "some feature"},
        )
        obs = await agent.perceive(intent)
        assert obs["codebase_context"] == ""


# ---------------------------------------------------------------------------
# Act tests
# ---------------------------------------------------------------------------


class TestActSuccess:
    @pytest.mark.asyncio
    async def test_act_parses_proposal(self):
        """act() parses valid LLM output into structured proposal."""
        agent = ArchitectAgent(
            agent_id="test-arch-6",
            llm_client=MagicMock(),
        )
        decision = {"action": "execute", "llm_output": SAMPLE_PROPOSAL}
        result = await agent.act(decision)

        assert result["success"] is True
        assert "proposal" in result["result"]
        p = result["result"]["proposal"]
        assert p["title"] == "Add Network Egress Policy"
        assert p["priority"] == "high"
        assert "build_spec" in p
        assert p["build_spec"]["ad_number"] == 310


class TestActError:
    @pytest.mark.asyncio
    async def test_act_error_decision(self):
        """act() handles error decisions."""
        agent = ArchitectAgent(
            agent_id="test-arch-7",
            llm_client=MagicMock(),
        )
        decision = {"action": "error", "reason": "No LLM client"}
        result = await agent.act(decision)
        assert result["success"] is False
        assert result["error"] == "No LLM client"


class TestActNoProposalBlock:
    @pytest.mark.asyncio
    async def test_act_no_proposal_in_output(self):
        """act() returns error when LLM output lacks ===PROPOSAL===."""
        agent = ArchitectAgent(
            agent_id="test-arch-8",
            llm_client=MagicMock(),
        )
        decision = {"action": "execute", "llm_output": "Just some text, no markers."}
        result = await agent.act(decision)
        assert result["success"] is False
        assert "No ===PROPOSAL=== block" in result["error"]
        assert result["llm_output"] == "Just some text, no markers."


# ---------------------------------------------------------------------------
# Perceive quality tests (AD-310)
# ---------------------------------------------------------------------------


def _make_mock_index(**overrides):
    """Helper to build a MagicMock codebase_index with sensible defaults."""
    mock = MagicMock(spec=CodebaseIndex)
    mock.query.return_value = overrides.get("query", {"matching_files": [], "matching_methods": []})
    mock.get_agent_map.return_value = overrides.get("agent_map", [])
    mock.get_layer_map.return_value = overrides.get("layer_map", {})
    mock.read_doc_sections.return_value = overrides.get("doc_sections", "")
    mock.read_source.return_value = overrides.get("read_source", "")
    mock.find_tests_for.return_value = overrides.get("find_tests_for", [])
    mock.find_callers.return_value = overrides.get("find_callers", [])
    mock.get_api_surface.return_value = overrides.get("api_surface", [])
    mock.get_full_api_surface.return_value = overrides.get("full_api_surface", {})
    mock.get_imports.return_value = overrides.get("get_imports", [])
    mock.find_importers.return_value = overrides.get("find_importers", [])
    mock._file_tree = overrides.get("file_tree", {})
    return mock


def _make_agent(mock_index, mock_runtime=None):
    """Helper to build an ArchitectAgent with mock runtime."""
    if mock_runtime is None:
        mock_runtime = MagicMock()
    mock_runtime.codebase_index = mock_index
    mock_llm = AsyncMock()
    mock_llm.complete.return_value = MagicMock(content="")
    return ArchitectAgent(
        agent_id="test-arch-q",
        llm_client=mock_llm,
        runtime=mock_runtime,
    )


def _make_intent(feature="test feature"):
    return IntentMessage(
        intent="design_feature",
        params={"feature": feature, "phase": ""},
    )


class TestPerceiveFileTree:
    @pytest.mark.asyncio
    async def test_file_tree_appears_in_context(self):
        """Layer 1: Full file tree with actual paths appears in context."""
        mock_index = _make_mock_index(layer_map={
            "cognitive": ["cognitive/builder.py", "cognitive/architect.py"],
            "mesh": ["mesh/routing.py"],
        })
        agent = _make_agent(mock_index)
        obs = await agent.perceive(_make_intent())
        ctx = obs["codebase_context"]
        assert "## File Tree" in ctx
        assert "cognitive/builder.py" in ctx
        assert "cognitive/architect.py" in ctx
        assert "mesh/routing.py" in ctx

    @pytest.mark.asyncio
    async def test_file_tree_shows_layer_counts(self):
        """Layer 1: File tree shows file count per layer."""
        mock_index = _make_mock_index(layer_map={
            "cognitive": ["cognitive/a.py", "cognitive/b.py", "cognitive/c.py"],
        })
        agent = _make_agent(mock_index)
        obs = await agent.perceive(_make_intent())
        assert "cognitive (3 files)" in obs["codebase_context"]


class TestPerceiveSourceSnippets:
    @pytest.mark.asyncio
    async def test_source_code_in_context(self):
        """Layer 2: Source code of matching files appears with python fencing."""
        mock_index = _make_mock_index(
            query={"matching_files": [
                {"path": "cognitive/builder.py", "relevance": 8, "docstring": "Builder stuff"},
            ], "matching_methods": []},
            file_tree={"cognitive/builder.py": {"classes": [], "docstring": "Builder stuff"}},
        )
        mock_index.read_source.return_value = "class BuilderAgent:\n    pass\n"
        agent = _make_agent(mock_index)
        obs = await agent.perceive(_make_intent())
        ctx = obs["codebase_context"]
        assert "Relevant Files" in ctx
        assert "```python" in ctx
        assert "class BuilderAgent" in ctx

    @pytest.mark.asyncio
    async def test_relevance_shown(self):
        """Layer 2: Files selected by LLM appear in context (fallback path)."""
        mock_index = _make_mock_index(
            query={"matching_files": [
                {"path": "foo.py", "relevance": 12, "docstring": ""},
            ], "matching_methods": []},
            file_tree={"foo.py": {"classes": [], "docstring": ""}},
        )
        mock_index.read_source.return_value = "# foo"
        agent = _make_agent(mock_index)
        obs = await agent.perceive(_make_intent())
        assert "foo.py" in obs["codebase_context"]


class TestPerceiveSlashCommands:
    @pytest.mark.asyncio
    async def test_shell_commands_in_context(self):
        """Layer 3: Existing slash commands from shell.py appear in context."""
        mock_index = _make_mock_index()

        # Make read_source return shell commands when asked for shell.py
        def _read_source(path, **kwargs):
            if "shell.py" in str(path):
                return 'COMMANDS = {\n    "/status": ...,\n    "/health": ...,\n}'
            return ""
        mock_index.read_source.side_effect = _read_source

        agent = _make_agent(mock_index)
        obs = await agent.perceive(_make_intent())
        ctx = obs["codebase_context"]
        assert "Existing Slash Commands" in ctx
        assert "/status" in ctx

    @pytest.mark.asyncio
    async def test_inline_api_commands_always_present(self):
        """Layer 3: Inline API commands (/build, /design) always listed."""
        mock_index = _make_mock_index()
        agent = _make_agent(mock_index)
        obs = await agent.perceive(_make_intent())
        ctx = obs["codebase_context"]
        assert "Inline API Commands" in ctx
        assert "/build" in ctx
        assert "/design" in ctx


class TestPerceiveApiRoutes:
    @pytest.mark.asyncio
    async def test_api_routes_extracted(self):
        """Layer 4: API routes extracted from @app decorators."""
        mock_index = _make_mock_index()

        def _read_source(path, **kwargs):
            if path == "api.py":
                return (
                    '    @app.post("/api/build/submit")\n'
                    '    async def submit_build(req: BuildRequest):\n'
                    '        pass\n'
                )
            return ""
        mock_index.read_source.side_effect = _read_source

        agent = _make_agent(mock_index)
        obs = await agent.perceive(_make_intent())
        ctx = obs["codebase_context"]
        assert "Existing API Routes" in ctx
        assert "/api/build/submit" in ctx
        assert "submit_build" in ctx


class TestPerceivePoolGroups:
    @pytest.mark.asyncio
    async def test_pool_groups_in_context(self):
        """Layer 5: Pool group crew structure appears in context."""
        mock_index = _make_mock_index()
        mock_runtime = MagicMock()
        mock_runtime.codebase_index = mock_index
        mock_runtime.pool_groups.status.return_value = {
            "engineering": {
                "display_name": "Engineering",
                "pools": {"builder": {}},
            },
            "science": {
                "display_name": "Science",
                "pools": {"architect": {}},
            },
        }

        agent = _make_agent(mock_index, mock_runtime)
        obs = await agent.perceive(_make_intent())
        ctx = obs["codebase_context"]
        assert "Pool Groups (Crew Structure)" in ctx
        assert "Engineering" in ctx
        assert "Science" in ctx


class TestPerceiveDecisionsTail:
    @pytest.mark.asyncio
    async def test_decisions_tail_40_lines(self):
        """Layer 6: DECISIONS.md tail is 40 lines."""
        mock_index = _make_mock_index()

        # Build a DECISIONS file with 100 lines
        lines = [f"| AD-{i} | Decision {i} |" for i in range(100)]
        full_content = "\n".join(lines)

        def _read_source(path, **kwargs):
            if "DECISIONS" in str(path):
                return full_content
            return ""
        mock_index.read_source.side_effect = _read_source

        agent = _make_agent(mock_index)
        obs = await agent.perceive(_make_intent())
        ctx = obs["codebase_context"]
        assert "last 40 lines" in ctx
        # Should contain AD-99 (last line) but not AD-59 (line 60, excluded)
        assert "AD-99" in ctx
        assert "AD-59" not in ctx


class TestPerceiveGracefulDegradation:
    @pytest.mark.asyncio
    async def test_layer_failures_dont_crash(self):
        """All layers wrapped in try/except — failures don't crash perceive."""
        mock_index = MagicMock()
        mock_index.get_layer_map.side_effect = RuntimeError("boom")
        mock_index.query.side_effect = RuntimeError("boom")
        mock_index.get_agent_map.side_effect = RuntimeError("boom")
        mock_index.read_source.side_effect = RuntimeError("boom")
        mock_index.read_doc_sections.side_effect = RuntimeError("boom")
        mock_index.find_tests_for.side_effect = RuntimeError("boom")
        mock_index.find_callers.side_effect = RuntimeError("boom")
        mock_index.get_api_surface.side_effect = RuntimeError("boom")
        mock_index.get_full_api_surface.side_effect = RuntimeError("boom")
        mock_index.get_imports.side_effect = RuntimeError("boom")
        mock_index.find_importers.side_effect = RuntimeError("boom")
        mock_index._file_tree = {}

        mock_llm = AsyncMock()
        mock_llm.complete.side_effect = RuntimeError("boom")

        mock_runtime = MagicMock()
        mock_runtime.codebase_index = mock_index

        agent = ArchitectAgent(
            agent_id="test-arch-degrade",
            llm_client=mock_llm,
            runtime=mock_runtime,
        )
        obs = await agent.perceive(_make_intent())

        # Should still return valid obs with codebase_context
        assert "codebase_context" in obs
        # Inline API commands are always present (no try/except needed)
        assert "/build" in obs["codebase_context"]

    @pytest.mark.asyncio
    async def test_partial_failure_keeps_other_layers(self):
        """If one layer fails, other layers still contribute to context."""
        mock_index = MagicMock()
        mock_index.get_layer_map.side_effect = RuntimeError("layer boom")
        mock_index.query.return_value = {"matching_files": [], "matching_methods": []}
        mock_index.get_agent_map.return_value = [
            {"type": "builder", "tier": "domain", "module": "m", "bases": []},
        ]
        mock_index.read_source.return_value = ""
        mock_index.read_doc_sections.return_value = ""
        mock_index.find_tests_for.return_value = []
        mock_index.find_callers.return_value = []
        mock_index.get_api_surface.return_value = []
        mock_index.get_full_api_surface.return_value = {}
        mock_index.get_imports.return_value = []
        mock_index.find_importers.return_value = []
        mock_index._file_tree = {}

        mock_llm = AsyncMock()
        mock_llm.complete.return_value = MagicMock(content="")

        mock_runtime = MagicMock()
        mock_runtime.codebase_index = mock_index

        agent = ArchitectAgent(
            agent_id="test-arch-partial",
            llm_client=mock_llm,
            runtime=mock_runtime,
        )
        obs = await agent.perceive(_make_intent())
        ctx = obs["codebase_context"]
        # File tree failed but agents should still be present
        assert "File Tree" not in ctx
        assert "Registered Agents" in ctx
        assert "builder" in ctx


# ---------------------------------------------------------------------------
# Deep localize pipeline tests (AD-311)
# ---------------------------------------------------------------------------


def _make_mock_index_with_source(**overrides):
    """Helper to build a MagicMock codebase_index with deep-localize methods."""
    mock = MagicMock(spec=CodebaseIndex)
    mock.query.return_value = overrides.get("query", {"matching_files": [], "matching_methods": []})
    mock.get_agent_map.return_value = overrides.get("agent_map", [])
    mock.get_layer_map.return_value = overrides.get("layer_map", {})
    mock.read_doc_sections.return_value = overrides.get("doc_sections", "")
    mock.read_source.return_value = overrides.get("read_source", "")
    mock.find_tests_for.return_value = overrides.get("find_tests_for", [])
    mock.find_callers.return_value = overrides.get("find_callers", [])
    mock.get_api_surface.return_value = overrides.get("api_surface", [])
    mock.get_full_api_surface.return_value = overrides.get("full_api_surface", {})
    mock.get_imports.return_value = overrides.get("get_imports", [])
    mock.find_importers.return_value = overrides.get("find_importers", [])
    mock._file_tree = overrides.get("file_tree", {})
    return mock


class TestDeepLocalize:
    """Tests for AD-311 three-step localize pipeline."""

    @pytest.mark.asyncio
    async def test_perceive_reads_full_source(self):
        """Layer 2b reads full file source, not first 80 lines."""
        long_source = "\n".join(f"line {i}" for i in range(200))
        mock_index = _make_mock_index_with_source(
            query={
                "matching_files": [
                    {"path": "cognitive/builder.py", "relevance": 8, "docstring": "Builder"},
                ],
                "matching_methods": [],
            },
            file_tree={"cognitive/builder.py": {"classes": [], "docstring": "Builder"}},
        )
        mock_index.read_source.return_value = long_source

        # Mock the LLM client to return a file selection
        mock_llm = AsyncMock()
        mock_llm.complete.return_value = MagicMock(content="cognitive/builder.py")

        mock_runtime = MagicMock()
        mock_runtime.codebase_index = mock_index

        agent = ArchitectAgent(
            agent_id="test-deep-1",
            llm_client=mock_llm,
            runtime=mock_runtime,
        )

        intent = IntentMessage(
            intent="design_feature",
            params={"feature": "test feature", "phase": ""},
        )
        obs = await agent.perceive(intent)
        ctx = obs["codebase_context"]

        # Should contain content from beyond line 80
        assert "line 150" in ctx

    @pytest.mark.asyncio
    async def test_perceive_includes_api_surface(self):
        """Context includes API Surface section with method signatures for classes in selected files."""
        mock_index = _make_mock_index_with_source(
            query={"matching_files": [
                {"path": "mesh/registry.py", "relevance": 8, "docstring": "Agent registry"},
            ], "matching_methods": []},
            file_tree={
                "mesh/registry.py": {"classes": ["AgentRegistry"], "functions": []},
            },
            full_api_surface={
                "AgentRegistry": [
                    {"method": "all", "signature": "def all() -> list[BaseAgent]"},
                    {"method": "get", "signature": "def get(agent_id: AgentID) -> BaseAgent | None"},
                ],
            },
        )

        mock_llm = AsyncMock()
        mock_llm.complete.return_value = MagicMock(content="mesh/registry.py")

        mock_runtime = MagicMock()
        mock_runtime.codebase_index = mock_index

        agent = ArchitectAgent(
            agent_id="test-deep-2",
            llm_client=mock_llm,
            runtime=mock_runtime,
        )
        obs = await agent.perceive(_make_intent())
        ctx = obs["codebase_context"]
        assert "API Surface (verified method signatures)" in ctx
        assert "AgentRegistry" in ctx
        assert "all" in ctx

    @pytest.mark.asyncio
    async def test_perceive_includes_test_files(self):
        """Context includes discovered test file paths."""
        mock_index = _make_mock_index_with_source(
            query={
                "matching_files": [
                    {"path": "experience/panels.py", "relevance": 5, "docstring": "Panels"},
                ],
                "matching_methods": [],
            },
            file_tree={"experience/panels.py": {"classes": [], "docstring": "Panels"}},
            find_tests_for=["experience/test_panels.py"],
        )
        mock_index.read_source.return_value = "# test file header"

        mock_llm = AsyncMock()
        mock_llm.complete.return_value = MagicMock(content="experience/panels.py")

        mock_runtime = MagicMock()
        mock_runtime.codebase_index = mock_index

        agent = ArchitectAgent(
            agent_id="test-deep-3",
            llm_client=mock_llm,
            runtime=mock_runtime,
        )
        obs = await agent.perceive(_make_intent())
        ctx = obs["codebase_context"]
        assert "Associated Test Files" in ctx
        assert "test_panels" in ctx

    @pytest.mark.asyncio
    async def test_perceive_includes_callers(self):
        """Context includes caller analysis for relevant methods."""
        mock_index = _make_mock_index_with_source(
            query={
                "matching_files": [
                    {"path": "substrate/registry.py", "relevance": 5, "docstring": "Registry"},
                ],
                "matching_methods": [],
            },
            file_tree={"substrate/registry.py": {"classes": ["AgentRegistry"], "docstring": "Registry"}},
            api_surface=[{"method": "all", "signature": "def all()"}],
            find_callers=[{"path": "runtime.py", "lines": [100, 200]}],
        )
        mock_index.read_source.return_value = "class AgentRegistry:\n    pass"

        mock_llm = AsyncMock()
        mock_llm.complete.return_value = MagicMock(content="substrate/registry.py")

        mock_runtime = MagicMock()
        mock_runtime.codebase_index = mock_index

        agent = ArchitectAgent(
            agent_id="test-deep-4",
            llm_client=mock_llm,
            runtime=mock_runtime,
        )
        obs = await agent.perceive(_make_intent())
        ctx = obs["codebase_context"]
        assert "Caller Analysis" in ctx
        assert "AgentRegistry.all()" in ctx
        assert "runtime.py" in ctx

    @pytest.mark.asyncio
    async def test_perceive_falls_back_on_llm_failure(self):
        """If fast-tier selection fails, falls back to keyword top-5."""
        mock_index = _make_mock_index_with_source(
            query={
                "matching_files": [
                    {"path": "cognitive/builder.py", "relevance": 8, "docstring": "Builder"},
                    {"path": "cognitive/architect.py", "relevance": 6, "docstring": "Architect"},
                ],
                "matching_methods": [],
            },
            file_tree={
                "cognitive/builder.py": {"classes": [], "docstring": "Builder"},
                "cognitive/architect.py": {"classes": [], "docstring": "Architect"},
            },
        )
        mock_index.read_source.return_value = "# source"

        # Mock LLM to raise an exception on fast-tier call
        mock_llm = AsyncMock()
        mock_llm.complete.side_effect = RuntimeError("LLM unavailable")

        mock_runtime = MagicMock()
        mock_runtime.codebase_index = mock_index

        agent = ArchitectAgent(
            agent_id="test-deep-5",
            llm_client=mock_llm,
            runtime=mock_runtime,
        )
        obs = await agent.perceive(_make_intent())
        ctx = obs["codebase_context"]
        # Should still have relevant files from fallback
        assert "Relevant Files" in ctx
        assert "builder.py" in ctx

    @pytest.mark.asyncio
    async def test_perceive_caps_source_at_budget(self):
        """Total source lines capped at 4000 across all files."""
        huge_source = "\n".join(f"line {i}" for i in range(3000))
        mock_index = _make_mock_index_with_source(
            query={
                "matching_files": [
                    {"path": f"file{i}.py", "relevance": 5, "docstring": f"File {i}"}
                    for i in range(5)
                ],
                "matching_methods": [],
            },
            file_tree={f"file{i}.py": {"classes": [], "docstring": f"File {i}"} for i in range(5)},
        )
        mock_index.read_source.return_value = huge_source

        mock_llm = AsyncMock()
        mock_llm.complete.side_effect = RuntimeError("skip")

        mock_runtime = MagicMock()
        mock_runtime.codebase_index = mock_index

        agent = ArchitectAgent(
            agent_id="test-deep-6",
            llm_client=mock_llm,
            runtime=mock_runtime,
        )
        obs = await agent.perceive(_make_intent())
        ctx = obs["codebase_context"]
        # With 5 files of 3000 lines each and budget of 4000, we should not
        # include all 15000 lines. Check that not all 5 files are fully present.
        # line 2999 is the last line of each huge file — if budget works,
        # it shouldn't appear for most files.
        assert ctx.count("line 2999") < 5  # not all 5 files fully included

    def test_instructions_have_rule_6(self):
        """System prompt includes API verification rule."""
        assert "UNVERIFIED" in ArchitectAgent.instructions

    def test_instructions_describe_full_source(self):
        """System prompt mentions full source code, not first 80 lines."""
        assert "FULL source" in ArchitectAgent.instructions or "full source" in ArchitectAgent.instructions


# ---------------------------------------------------------------------------
# Import tracing tests (AD-315)
# ---------------------------------------------------------------------------


class TestImportTracing:
    """Tests for AD-315 import graph integration in Architect perceive."""

    @pytest.mark.asyncio
    async def test_perceive_expands_selected_files_via_imports(self):
        """Layer 2a+ expands selected files by tracing their imports."""
        mock_index = _make_mock_index_with_source(
            query={
                "matching_files": [
                    {"path": "experience/shell.py", "relevance": 8, "docstring": "Shell"},
                ],
                "matching_methods": [],
            },
            file_tree={
                "experience/shell.py": {"classes": ["Shell"], "docstring": "Shell"},
                "experience/panels.py": {"classes": [], "docstring": "Panel renderers"},
            },
        )
        mock_index.read_source.return_value = "class Shell:\n    pass"
        mock_index.get_imports.return_value = ["experience/panels.py"]
        mock_index.find_importers.return_value = []

        mock_llm = AsyncMock()
        mock_llm.complete.return_value = MagicMock(content="experience/shell.py")

        mock_runtime = MagicMock()
        mock_runtime.codebase_index = mock_index

        agent = ArchitectAgent(
            agent_id="test-import-1",
            llm_client=mock_llm,
            runtime=mock_runtime,
        )
        obs = await agent.perceive(_make_intent("add /agents command"))
        ctx = obs["codebase_context"]
        # panels.py should be included via import tracing
        assert "panels.py" in ctx

    @pytest.mark.asyncio
    async def test_perceive_includes_import_graph_section(self):
        """Context includes Import Graph section."""
        mock_index = _make_mock_index_with_source(
            query={
                "matching_files": [
                    {"path": "experience/shell.py", "relevance": 8, "docstring": "Shell"},
                ],
                "matching_methods": [],
            },
            file_tree={
                "experience/shell.py": {"classes": [], "docstring": "Shell"},
            },
        )
        mock_index.read_source.return_value = "# source"
        mock_index.get_imports.return_value = ["experience/panels.py"]
        mock_index.find_importers.return_value = ["api.py"]

        mock_llm = AsyncMock()
        mock_llm.complete.return_value = MagicMock(content="experience/shell.py")

        mock_runtime = MagicMock()
        mock_runtime.codebase_index = mock_index

        agent = ArchitectAgent(
            agent_id="test-import-2",
            llm_client=mock_llm,
            runtime=mock_runtime,
        )
        obs = await agent.perceive(_make_intent())
        ctx = obs["codebase_context"]
        assert "Import Graph" in ctx

    def test_instructions_mention_imports(self):
        """System prompt mentions import graph in context description."""
        assert "Import graph" in ArchitectAgent.instructions


# ---------------------------------------------------------------------------
# Proposal validation tests (AD-316a)
# ---------------------------------------------------------------------------


def _make_valid_proposal(**overrides):
    """Helper to create a valid ArchitectProposal for validation tests."""
    spec_defaults = {
        "title": "Test Feature",
        "description": "A" * 120,  # Over 100 chars minimum
        "target_files": ["src/probos/security/egress.py"],
        "reference_files": ["src/probos/consensus/trust.py"],
        "test_files": ["tests/test_egress_policy.py"],
        "ad_number": 400,
        "constraints": ["Do NOT modify trust"],
    }
    spec_defaults.update(overrides.pop("build_spec_overrides", {}))
    spec = BuildSpec(**spec_defaults)

    proposal_defaults = {
        "title": "Test Feature",
        "summary": "A test feature",
        "rationale": "Testing",
        "build_spec": spec,
        "priority": "medium",
    }
    proposal_defaults.update(overrides)
    return ArchitectProposal(**proposal_defaults)


class TestProposalValidation:
    """Tests for AD-316a _validate_proposal() method."""

    def test_valid_proposal_no_warnings(self):
        """A fully valid proposal returns no warnings."""
        mock_index = _make_mock_index(file_tree={
            "src/probos/security/sentinel.py": {"classes": [], "docstring": ""},
            "src/probos/consensus/trust.py": {"classes": [], "docstring": ""},
        })
        agent = _make_agent(mock_index)
        proposal = _make_valid_proposal()
        warnings = agent._validate_proposal(proposal)
        assert warnings == []

    def test_missing_title_warns(self):
        """Empty title triggers warning."""
        mock_index = _make_mock_index()
        agent = _make_agent(mock_index)
        proposal = _make_valid_proposal(title="")
        warnings = agent._validate_proposal(proposal)
        assert any("Missing required field" in w for w in warnings)

    def test_empty_test_files_warns(self):
        """Empty test_files triggers warning."""
        mock_index = _make_mock_index()
        agent = _make_agent(mock_index)
        proposal = _make_valid_proposal(
            build_spec_overrides={"test_files": []}
        )
        warnings = agent._validate_proposal(proposal)
        assert any("No test files specified" in w for w in warnings)

    def test_target_file_unknown_path_warns(self):
        """Target file in non-existent directory triggers warning."""
        mock_index = _make_mock_index(file_tree={
            "src/probos/mesh/routing.py": {"classes": [], "docstring": ""},
        })
        agent = _make_agent(mock_index)
        proposal = _make_valid_proposal(
            build_spec_overrides={"target_files": ["src/probos/web/routes.py"]}
        )
        warnings = agent._validate_proposal(proposal)
        assert any("TARGET_FILE not found" in w for w in warnings)

    def test_target_file_new_in_existing_dir_ok(self):
        """Target file in existing directory does NOT trigger warning."""
        mock_index = _make_mock_index(file_tree={
            "src/probos/mesh/routing.py": {"classes": [], "docstring": ""},
        })
        agent = _make_agent(mock_index)
        proposal = _make_valid_proposal(
            build_spec_overrides={
                "target_files": ["src/probos/mesh/policy.py"],
                "reference_files": [],
            }
        )
        warnings = agent._validate_proposal(proposal)
        assert not any("TARGET_FILE not found" in w for w in warnings)

    def test_short_description_warns(self):
        """Description under 100 chars triggers warning."""
        mock_index = _make_mock_index()
        agent = _make_agent(mock_index)
        proposal = _make_valid_proposal(
            build_spec_overrides={"description": "Too short"}
        )
        warnings = agent._validate_proposal(proposal)
        assert any("Description too short" in w for w in warnings)

    def test_invalid_priority_warns(self):
        """Invalid priority value triggers warning."""
        mock_index = _make_mock_index()
        agent = _make_agent(mock_index)
        proposal = _make_valid_proposal(priority="critical")
        warnings = agent._validate_proposal(proposal)
        assert any("Invalid priority" in w for w in warnings)

    @pytest.mark.asyncio
    async def test_act_includes_warnings_in_result(self):
        """act() includes warnings key when validation finds issues."""
        mock_index = _make_mock_index()
        agent = _make_agent(mock_index)
        # Use MINIMAL_PROPOSAL — has empty test_files and short description
        decision = {"action": "execute", "llm_output": MINIMAL_PROPOSAL}
        result = await agent.act(decision)
        assert result["success"] is True
        assert "warnings" in result["result"]
        assert len(result["result"]["warnings"]) > 0

    @pytest.mark.asyncio
    async def test_act_no_warnings_key_when_valid(self):
        """act() omits warnings key when proposal is fully valid."""
        mock_index = _make_mock_index(file_tree={
            "src/probos/security/sentinel.py": {"classes": [], "docstring": ""},
            "src/probos/consensus/trust.py": {"classes": [], "docstring": ""},
            "src/probos/mesh/routing.py": {"classes": [], "docstring": ""},
        })
        agent = _make_agent(mock_index)
        decision = {"action": "execute", "llm_output": SAMPLE_PROPOSAL}
        result = await agent.act(decision)
        assert result["success"] is True
        # Warnings should be absent (empty list not added)
        assert "warnings" not in result["result"]

    def test_validation_skipped_without_runtime(self):
        """Without runtime, file-tree checks are skipped but other checks run."""
        agent = ArchitectAgent(
            agent_id="test-no-runtime",
            llm_client=MagicMock(),
        )
        proposal = _make_valid_proposal(priority="critical")
        warnings = agent._validate_proposal(proposal)
        # Priority check should still fire
        assert any("Invalid priority" in w for w in warnings)
        # File path checks should NOT fire (no runtime)
        assert not any("TARGET_FILE not found" in w for w in warnings)


class TestPatternRecipes:
    """Tests for AD-316a Pattern Recipes in instructions."""

    def test_instructions_contain_pattern_recipes(self):
        assert "PATTERN RECIPES" in ArchitectAgent.instructions

    def test_recipe_new_agent(self):
        assert "Recipe: NEW AGENT" in ArchitectAgent.instructions
        assert "BaseAgent" in ArchitectAgent.instructions

    def test_recipe_new_slash_command(self):
        assert "Recipe: NEW SLASH COMMAND" in ArchitectAgent.instructions
        assert "shell.py" in ArchitectAgent.instructions

    def test_recipe_new_api_endpoint(self):
        assert "Recipe: NEW API ENDPOINT" in ArchitectAgent.instructions
        assert "api.py" in ArchitectAgent.instructions
