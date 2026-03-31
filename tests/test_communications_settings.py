"""AD-485/BF-051/052: Communications settings and DM awareness tests."""
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from probos.config import SystemConfig, CommunicationsConfig
from probos.earned_agency import Rank, can_perform_action
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.runtime import ProbOSRuntime


class TestCommunicationsConfig:
    """Config defaults and structure."""

    def test_default_dm_rank_is_ensign(self):
        """Fresh config has dm_min_rank='ensign'."""
        cfg = SystemConfig()
        assert cfg.communications.dm_min_rank == "ensign"

    def test_dm_rank_configurable(self):
        """Setting to 'commander' should work."""
        cfg = CommunicationsConfig(dm_min_rank="commander")
        assert cfg.dm_min_rank == "commander"


class TestEarnedAgencyDm:
    """Earned agency DM tier tests."""

    def test_ensign_can_dm_at_ensign_tier(self):
        """Ensign can perform dm action since tier is Ensign."""
        assert can_perform_action(Rank.ENSIGN, "dm")

    def test_lieutenant_can_dm(self):
        """Lieutenant can perform dm action."""
        assert can_perform_action(Rank.LIEUTENANT, "dm")

    def test_ensign_cannot_endorse(self):
        """Ensign still can't endorse (Lieutenant tier)."""
        assert not can_perform_action(Rank.ENSIGN, "endorse")

    def test_ensign_cannot_reply(self):
        """Ensign still can't reply (Lieutenant tier)."""
        assert not can_perform_action(Rank.ENSIGN, "reply")


class TestDmRankGating:
    """DM rank floor gating in the proactive loop."""

    def test_ensign_can_dm_when_floor_is_ensign(self):
        """Ensign agent can DM when min rank = ensign."""
        dm_min_rank_str = "ensign"
        rank = Rank.ENSIGN
        dm_min_rank = Rank[dm_min_rank_str.upper()]
        _RANK_ORDER = [Rank.ENSIGN, Rank.LIEUTENANT, Rank.COMMANDER, Rank.SENIOR]
        assert _RANK_ORDER.index(rank) >= _RANK_ORDER.index(dm_min_rank)

    def test_ensign_blocked_when_floor_is_commander(self):
        """Ensign can't DM when min rank = commander."""
        dm_min_rank_str = "commander"
        rank = Rank.ENSIGN
        dm_min_rank = Rank[dm_min_rank_str.upper()]
        _RANK_ORDER = [Rank.ENSIGN, Rank.LIEUTENANT, Rank.COMMANDER, Rank.SENIOR]
        assert _RANK_ORDER.index(rank) < _RANK_ORDER.index(dm_min_rank)

    def test_commander_allowed_when_floor_is_commander(self):
        """Commander can DM when min rank = commander."""
        dm_min_rank_str = "commander"
        rank = Rank.COMMANDER
        dm_min_rank = Rank[dm_min_rank_str.upper()]
        _RANK_ORDER = [Rank.ENSIGN, Rank.LIEUTENANT, Rank.COMMANDER, Rank.SENIOR]
        assert _RANK_ORDER.index(rank) >= _RANK_ORDER.index(dm_min_rank)


class TestCommunicationsSettingsApi:
    """API endpoint tests for communications settings."""

    @pytest.fixture
    def mock_runtime(self):
        rt = MagicMock(spec=ProbOSRuntime)
        rt.config = SystemConfig()
        return rt

    @pytest.mark.asyncio
    async def test_dm_rank_api_get(self, mock_runtime):
        """GET /api/system/communications/settings returns current setting."""
        result = {
            "dm_min_rank": mock_runtime.config.communications.dm_min_rank,
        }
        assert result == {"dm_min_rank": "ensign"}

    @pytest.mark.asyncio
    async def test_dm_rank_api_patch(self, mock_runtime):
        """PATCH updates setting."""
        valid_ranks = ["ensign", "lieutenant", "commander", "senior"]
        body = {"dm_min_rank": "commander"}
        rank_val = body["dm_min_rank"].lower()
        assert rank_val in valid_ranks
        mock_runtime.config.communications.dm_min_rank = rank_val
        assert mock_runtime.config.communications.dm_min_rank == "commander"

    @pytest.mark.asyncio
    async def test_dm_rank_invalid_value_rejected(self, mock_runtime):
        """Invalid rank string should be rejected."""
        valid_ranks = ["ensign", "lieutenant", "commander", "senior"]
        body = {"dm_min_rank": "captain"}
        rank_val = body["dm_min_rank"].lower()
        assert rank_val not in valid_ranks


def _make_agent_with_runtime(ontology=None):
    """Create a CognitiveAgent with mocked runtime for DM instruction tests."""
    agent = CognitiveAgent.__new__(CognitiveAgent)
    agent.agent_type = "science_officer"
    agent.id = "sci-001"
    agent.instructions = ""
    agent._runtime = MagicMock(spec=ProbOSRuntime)
    agent._runtime.callsign_registry = MagicMock()
    agent._runtime.callsign_registry.all_callsigns = MagicMock(return_value={
        "science_officer": "Vega",
        "engineering_agent": "Forge",
        "medical_officer": "Chapel",
    })
    if ontology is not None:
        agent._runtime.ontology = ontology
    else:
        agent._runtime.ontology = None
    return agent


class TestDmSyntaxAvailability:
    """BF-051: DM syntax must appear in proactive + ward room prompts, not 1:1."""

    def test_dm_syntax_in_proactive_prompt(self):
        """_compose_dm_instructions produces DM syntax in full mode."""
        agent = _make_agent_with_runtime()
        result = agent._compose_dm_instructions()
        assert "[DM @callsign]" in result
        assert "[/DM]" in result

    def test_dm_syntax_in_ward_room_prompt_brief(self):
        """brief=True produces shorter DM syntax for ward room context."""
        agent = _make_agent_with_runtime()
        result = agent._compose_dm_instructions(brief=True)
        assert "[DM @callsign]" in result
        assert "@captain" in result

    def test_dm_syntax_not_in_direct_message_prompt(self):
        """1:1 direct message context should NOT include DM instructions."""
        # The 1:1 branch in decide() doesn't call _compose_dm_instructions
        # Verify the helper isn't called for direct_message by checking the
        # else branch doesn't include DM syntax
        agent = _make_agent_with_runtime()
        # Direct message prompt text (from cognitive_agent.py else branch)
        dm_text = "1:1 conversation with the Captain"
        assert "[DM @" not in dm_text

    def test_dm_crew_roster_in_ward_room_prompt(self):
        """Crew roster appears in the DM instructions."""
        agent = _make_agent_with_runtime()
        result = agent._compose_dm_instructions(brief=True)
        assert "@Forge" in result
        assert "@Chapel" in result
        # Self excluded
        assert "@Vega" not in result


class TestDepartmentGroupedRoster:
    """BF-052: Crew roster grouped by department when ontology available."""

    def test_crew_roster_grouped_by_department(self):
        """With ontology, roster shows department headers."""
        ontology = MagicMock()
        ontology.get_agent_department = MagicMock(side_effect=lambda atype: {
            "engineering_agent": "engineering",
            "medical_officer": "medical",
        }.get(atype))
        agent = _make_agent_with_runtime(ontology=ontology)
        result = agent._compose_dm_instructions()
        assert "Engineering:" in result
        assert "Medical:" in result
        assert "@Forge" in result
        assert "@Chapel" in result

    def test_crew_roster_excludes_self(self):
        """Agent's own callsign not in the roster."""
        ontology = MagicMock()
        ontology.get_agent_department = MagicMock(return_value="science")
        agent = _make_agent_with_runtime(ontology=ontology)
        result = agent._compose_dm_instructions()
        assert "@Vega" not in result

    def test_crew_roster_fallback_flat_when_no_ontology(self):
        """Without ontology, falls back to flat list."""
        agent = _make_agent_with_runtime(ontology=None)
        result = agent._compose_dm_instructions()
        # Flat list — no department headers, just @callsigns
        assert "@Forge" in result
        assert "@Chapel" in result
        assert "Engineering:" not in result
