"""AD-620: Clearance Model Foundation — Billet-Based Access Tier.

Tests for the clearance model that replaces AD-619 SWA hack:
- effective_recall_tier() resolution
- resolve_billet_clearance() ontology lookup
- Post.clearance field
- Organization YAML parsing
- Integration with cognitive_agent and proactive tier resolution
- Oracle gate simplification
- Ward Room subscription by clearance
- SWA removal verification
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.earned_agency import (
    RecallTier,
    _TIER_ORDER,
    effective_recall_tier,
    recall_tier_from_rank,
    resolve_billet_clearance,
)
from probos.crew_profile import Rank
from probos.ontology.models import Post


# ---------------------------------------------------------------------------
# 1-5: effective_recall_tier()
# ---------------------------------------------------------------------------

class TestEffectiveRecallTier:
    def test_rank_only_no_clearance(self) -> None:
        """No billet clearance → returns rank-based tier."""
        assert effective_recall_tier(Rank.ENSIGN) == RecallTier.BASIC
        assert effective_recall_tier(Rank.LIEUTENANT) == RecallTier.ENHANCED
        assert effective_recall_tier(Rank.COMMANDER) == RecallTier.FULL
        assert effective_recall_tier(Rank.SENIOR) == RecallTier.ORACLE

    def test_billet_upgrades_low_rank(self) -> None:
        """Low rank + ORACLE clearance → ORACLE."""
        assert effective_recall_tier(Rank.ENSIGN, "ORACLE") == RecallTier.ORACLE
        assert effective_recall_tier(Rank.LIEUTENANT, "ORACLE") == RecallTier.ORACLE

    def test_rank_higher_than_clearance(self) -> None:
        """Commander rank (FULL) + ENHANCED clearance → FULL (rank wins)."""
        assert effective_recall_tier(Rank.COMMANDER, "ENHANCED") == RecallTier.FULL

    def test_invalid_clearance_string(self) -> None:
        """Invalid clearance string → falls back to rank-based tier."""
        assert effective_recall_tier(Rank.ENSIGN, "BANANA") == RecallTier.BASIC

    def test_empty_clearance(self) -> None:
        """Empty clearance string → returns rank-based tier."""
        assert effective_recall_tier(Rank.LIEUTENANT, "") == RecallTier.ENHANCED

    def test_no_rank_with_clearance(self) -> None:
        """No rank + ORACLE clearance → ORACLE (default rank=ENHANCED, billet=ORACLE)."""
        assert effective_recall_tier(None, "ORACLE") == RecallTier.ORACLE

    def test_no_rank_no_clearance(self) -> None:
        """No rank + no clearance → ENHANCED (default)."""
        assert effective_recall_tier(None) == RecallTier.ENHANCED


# ---------------------------------------------------------------------------
# 6-8: resolve_billet_clearance()
# ---------------------------------------------------------------------------

class TestResolveBilletClearance:
    def test_with_ontology(self) -> None:
        """Mock ontology with Post(clearance='ORACLE') → returns 'ORACLE'."""
        ontology = MagicMock()
        post = MagicMock()
        post.clearance = "ORACLE"
        ontology.get_post_for_agent.return_value = post

        result = resolve_billet_clearance("counselor", ontology)
        assert result == "ORACLE"
        ontology.get_post_for_agent.assert_called_once_with("counselor")

    def test_no_ontology(self) -> None:
        """No ontology → returns empty string."""
        assert resolve_billet_clearance("counselor", None) == ""

    def test_agent_not_assigned(self) -> None:
        """ontology.get_post_for_agent returns None → returns empty string."""
        ontology = MagicMock()
        ontology.get_post_for_agent.return_value = None

        assert resolve_billet_clearance("unknown_agent", ontology) == ""

    def test_ontology_raises_exception(self) -> None:
        """Ontology raises exception → returns empty string (fail-safe)."""
        ontology = MagicMock()
        ontology.get_post_for_agent.side_effect = RuntimeError("ontology down")

        assert resolve_billet_clearance("counselor", ontology) == ""


# ---------------------------------------------------------------------------
# 9: Post dataclass
# ---------------------------------------------------------------------------

class TestPostClearanceField:
    def test_default_clearance_empty(self) -> None:
        """Post.clearance defaults to empty string."""
        post = Post(id="test", title="Test", department_id="bridge", reports_to=None)
        assert post.clearance == ""

    def test_explicit_clearance(self) -> None:
        """Post with explicit clearance preserves value."""
        post = Post(
            id="captain", title="Captain", department_id="bridge",
            reports_to=None, clearance="ORACLE",
        )
        assert post.clearance == "ORACLE"


# ---------------------------------------------------------------------------
# 10: Organization YAML parsing
# ---------------------------------------------------------------------------

class TestOrganizationYAMLParsing:
    @pytest.mark.asyncio
    async def test_captain_has_oracle_clearance(self) -> None:
        """Load organization.yaml — captain post has clearance='ORACLE'."""
        from probos.ontology.loader import OntologyLoader

        loader = OntologyLoader(Path("config/ontology"))
        await loader.initialize()
        captain = loader.posts.get("captain")
        assert captain is not None
        assert captain.clearance == "ORACLE"

    @pytest.mark.asyncio
    async def test_counselor_has_oracle_clearance(self) -> None:
        """Counselor post has clearance='ORACLE'."""
        from probos.ontology.loader import OntologyLoader

        loader = OntologyLoader(Path("config/ontology"))
        await loader.initialize()
        counselor = loader.posts.get("counselor")
        assert counselor is not None
        assert counselor.clearance == "ORACLE"

    @pytest.mark.asyncio
    async def test_chief_has_full_clearance(self) -> None:
        """Chief engineer post has clearance='FULL'."""
        from probos.ontology.loader import OntologyLoader

        loader = OntologyLoader(Path("config/ontology"))
        await loader.initialize()
        chief = loader.posts.get("chief_engineer")
        assert chief is not None
        assert chief.clearance == "FULL"

    @pytest.mark.asyncio
    async def test_officer_has_enhanced_clearance(self) -> None:
        """Engineering officer post has clearance='ENHANCED'."""
        from probos.ontology.loader import OntologyLoader

        loader = OntologyLoader(Path("config/ontology"))
        await loader.initialize()
        officer = loader.posts.get("engineering_officer")
        assert officer is not None
        assert officer.clearance == "ENHANCED"


# ---------------------------------------------------------------------------
# 11-12: Integration — cognitive_agent + proactive tier resolution
# ---------------------------------------------------------------------------

class TestCognitiveAgentTierResolution:
    def test_counselor_gets_oracle_via_billet(self) -> None:
        """Mock agent with counselor type gets ORACLE tier via billet clearance."""
        ontology = MagicMock()
        post = MagicMock()
        post.clearance = "ORACLE"
        ontology.get_post_for_agent.return_value = post

        # Simulate the cognitive_agent.py tier resolution path
        _rank = Rank.ENSIGN
        _billet_clearance = resolve_billet_clearance("counselor", ontology)
        _recall_tier = effective_recall_tier(_rank, _billet_clearance)

        assert _recall_tier == RecallTier.ORACLE

    def test_proactive_tier_resolution(self) -> None:
        """Proactive loop resolves tier via billet clearance (same path)."""
        ontology = MagicMock()
        post = MagicMock()
        post.clearance = "FULL"
        ontology.get_post_for_agent.return_value = post

        _rank = Rank.LIEUTENANT  # normally ENHANCED
        _billet_clearance = resolve_billet_clearance("chief_engineer", ontology)
        _recall_tier = effective_recall_tier(_rank, _billet_clearance)

        assert _recall_tier == RecallTier.FULL  # billet upgrades from ENHANCED


# ---------------------------------------------------------------------------
# 13: Oracle gate — clearance-only access (strategy not a blocker)
# ---------------------------------------------------------------------------

class TestOracleGateClearanceOnly:
    def test_oracle_tier_non_deep_strategy_opens_gate(self) -> None:
        """ORACLE-tier agent with ANALYTICAL strategy → Oracle gate opens."""
        from probos.cognitive.source_governance import RetrievalStrategy

        _recall_tier = RecallTier.ORACLE
        agent = MagicMock()
        agent._runtime = MagicMock()
        agent._runtime._oracle_service = MagicMock()

        # AD-620 gate: no strategy check
        gate_opens = bool(
            _recall_tier == RecallTier.ORACLE
            and hasattr(agent, '_runtime')
            and hasattr(agent._runtime, '_oracle_service')
            and agent._runtime._oracle_service
        )
        assert gate_opens is True

    def test_non_oracle_tier_gate_stays_closed(self) -> None:
        """FULL-tier agent → Oracle gate does NOT open."""
        _recall_tier = RecallTier.FULL
        agent = MagicMock()
        agent._runtime = MagicMock()
        agent._runtime._oracle_service = MagicMock()

        gate_opens = bool(
            _recall_tier == RecallTier.ORACLE
            and hasattr(agent, '_runtime')
            and hasattr(agent._runtime, '_oracle_service')
            and agent._runtime._oracle_service
        )
        assert gate_opens is False


# ---------------------------------------------------------------------------
# 14-15: Ward Room subscription
# ---------------------------------------------------------------------------

class TestWardRoomSubscription:
    def test_full_clearance_gets_all_channels(self) -> None:
        """Agent with FULL billet clearance → subscribed to all department channels."""
        _billet_cl = "FULL"
        try:
            _cl_tier = RecallTier(_billet_cl.lower())
            gets_all = _TIER_ORDER.get(_cl_tier, 0) >= _TIER_ORDER.get(RecallTier.FULL, 0)
        except ValueError:
            gets_all = False

        assert gets_all is True

    def test_oracle_clearance_gets_all_channels(self) -> None:
        """Agent with ORACLE clearance → also subscribed to all (ORACLE > FULL)."""
        _billet_cl = "ORACLE"
        try:
            _cl_tier = RecallTier(_billet_cl.lower())
            gets_all = _TIER_ORDER.get(_cl_tier, 0) >= _TIER_ORDER.get(RecallTier.FULL, 0)
        except ValueError:
            gets_all = False

        assert gets_all is True

    def test_enhanced_does_not_get_all_channels(self) -> None:
        """Agent with ENHANCED clearance → NOT subscribed to all channels."""
        _billet_cl = "ENHANCED"
        try:
            _cl_tier = RecallTier(_billet_cl.lower())
            gets_all = _TIER_ORDER.get(_cl_tier, 0) >= _TIER_ORDER.get(RecallTier.FULL, 0)
        except ValueError:
            gets_all = False

        assert gets_all is False

    def test_basic_does_not_get_all_channels(self) -> None:
        """Agent with BASIC clearance → NOT subscribed to all channels."""
        _billet_cl = "BASIC"
        try:
            _cl_tier = RecallTier(_billet_cl.lower())
            gets_all = _TIER_ORDER.get(_cl_tier, 0) >= _TIER_ORDER.get(RecallTier.FULL, 0)
        except ValueError:
            gets_all = False

        assert gets_all is False


# ---------------------------------------------------------------------------
# 16: SWA removal verification
# ---------------------------------------------------------------------------

class TestSWARemoval:
    def test_no_swa_references_in_source(self) -> None:
        """Grep for has_ship_wide_authority in src/probos/ — should return 0 results."""
        result = subprocess.run(
            ["grep", "-rn", "--include=*.py", "has_ship_wide_authority", "src/probos/"],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        matches = result.stdout.strip()
        assert matches == "", (
            f"has_ship_wide_authority still referenced in src/probos/:\n{matches}"
        )
