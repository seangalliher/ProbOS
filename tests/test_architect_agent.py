"""Tests for ArchitectAgent and ArchitectProposal (AD-306)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.architect import ArchitectAgent, ArchitectProposal
from probos.cognitive.builder import BuildSpec
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
        assert "===PROPOSAL===" in msg

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
                {"path": "src/probos/mesh/routing.py", "score": 5, "docstring": "Routing"},
            ],
        }
        mock_index.get_agent_map.return_value = [
            {"type": "builder", "tier": "domain", "bases": ["CognitiveAgent"]},
        ]
        mock_index.read_doc_sections.return_value = "## Phase 31\nSecurity stuff"
        mock_index.read_source.return_value = "| AD-305 | Last decision |\n"
        mock_index.get_layer_map.return_value = {"cognitive": ["a.py", "b.py"]}

        mock_runtime = MagicMock()
        mock_runtime.codebase_index = mock_index

        agent = ArchitectAgent(
            agent_id="test-arch-4",
            llm_client=MagicMock(),
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
        assert "Existing Agents" in ctx
        assert "builder" in ctx
        assert "Architecture Layers" in ctx
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
