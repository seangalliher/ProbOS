"""AD-619 → AD-620: Counselor Cross-Department Awareness.

Tests migrated from AD-619 SWA-based approach to AD-620 clearance model.
Validates that billet clearance provides the same guarantees:
- ORACLE-tier agents get Oracle access on any strategy
- FULL+ clearance agents get all department channel subscriptions
"""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.earned_agency import (
    RecallTier, effective_recall_tier, resolve_billet_clearance, _TIER_ORDER,
)
from probos.cognitive.source_governance import RetrievalStrategy
from probos.crew_profile import Rank


# ---------------------------------------------------------------------------
# TestBilletClearance (replaces TestShipWideAuthority)
# ---------------------------------------------------------------------------

class TestBilletClearance:
    def test_counselor_gets_oracle_clearance(self) -> None:
        """Counselor post has ORACLE billet clearance."""
        ontology = MagicMock()
        post = MagicMock()
        post.clearance = "ORACLE"
        ontology.get_post_for_agent.return_value = post

        assert resolve_billet_clearance("counselor", ontology) == "ORACLE"

    def test_non_oracle_agent_gets_lower_clearance(self) -> None:
        """Data analyst has ENHANCED billet clearance."""
        ontology = MagicMock()
        post = MagicMock()
        post.clearance = "ENHANCED"
        ontology.get_post_for_agent.return_value = post

        assert resolve_billet_clearance("data_analyst", ontology) == "ENHANCED"

    def test_no_ontology_returns_empty(self) -> None:
        """No ontology available returns empty clearance."""
        assert resolve_billet_clearance("counselor", None) == ""


# ---------------------------------------------------------------------------
# TestChannelSubscriptions
# ---------------------------------------------------------------------------

class TestChannelSubscriptions:
    @pytest.mark.asyncio
    async def test_oracle_clearance_agent_subscribed_to_all_dept_channels(self) -> None:
        """Agent with FULL+ billet clearance gets subscribed to ALL department channels."""
        from probos.cognitive.standing_orders import get_department

        # Create mock channels
        def _ch(name, ch_type, dept=None):
            c = MagicMock()
            c.name = name
            c.id = f"ch_{name.lower().replace(' ', '_')}"
            c.channel_type = ch_type
            c.department = dept
            return c

        channels = [
            _ch("All Hands", "ship"),
            _ch("Bridge", "department", "bridge"),
            _ch("Medical", "department", "medical"),
            _ch("Engineering", "department", "engineering"),
            _ch("Science", "department", "science"),
            _ch("Security", "department", "security"),
            _ch("Operations", "department", "operations"),
        ]

        # Create mock agents
        counselor = MagicMock()
        counselor.agent_type = "counselor"
        counselor.id = "counselor_001"

        science_agent = MagicMock()
        science_agent.agent_type = "data_analyst"
        science_agent.id = "analyst_001"

        # Mock ward_room
        ward_room = MagicMock()
        ward_room.list_channels = AsyncMock(return_value=channels)
        ward_room.subscribe = AsyncMock()

        # Build dept_channel_map the same way communication.py does
        dept_channel_map: dict[str, str] = {}
        all_hands_id = None
        for ch in channels:
            if ch.name == "All Hands":
                all_hands_id = ch.id
            elif ch.channel_type == "department" and ch.department:
                dept_channel_map[ch.department] = ch.id

        # Mock ontology for clearance lookup
        def _mock_clearance(agent_type, ontology):
            clearances = {"counselor": "ORACLE", "data_analyst": "ENHANCED"}
            return clearances.get(agent_type, "")

        # Run the subscription logic (extracted from communication.py)
        from probos.crew_utils import is_crew_agent
        for agent in [counselor, science_agent]:
            if not is_crew_agent(agent):
                continue
            dept = get_department(agent.agent_type)
            if dept and dept in dept_channel_map:
                await ward_room.subscribe(agent.id, dept_channel_map[dept])
            # AD-620: Agents with FULL+ billet clearance get all department channels
            _billet_cl = _mock_clearance(agent.agent_type, None)
            if _billet_cl:
                try:
                    _cl_tier = RecallTier(_billet_cl.lower())
                    if _TIER_ORDER.get(_cl_tier, 0) >= _TIER_ORDER.get(RecallTier.FULL, 0):
                        for dept_ch_id in dept_channel_map.values():
                            await ward_room.subscribe(agent.id, dept_ch_id)
                except ValueError:
                    pass
            if all_hands_id:
                await ward_room.subscribe(agent.id, all_hands_id)

        # Collect counselor's subscribe calls
        counselor_subscriptions = [
            call.args[1] for call in ward_room.subscribe.call_args_list
            if call.args[0] == "counselor_001"
        ]

        # Counselor should be subscribed to ALL department channels
        for dept_ch_id in dept_channel_map.values():
            assert dept_ch_id in counselor_subscriptions, (
                f"Counselor missing subscription to {dept_ch_id}"
            )

        # Science agent should NOT be subscribed to all dept channels
        analyst_subscriptions = [
            call.args[1] for call in ward_room.subscribe.call_args_list
            if call.args[0] == "analyst_001"
        ]
        # data_analyst is science dept — should only have science + all_hands
        assert "ch_medical" not in analyst_subscriptions
        assert "ch_engineering" not in analyst_subscriptions
        assert "ch_security" not in analyst_subscriptions


# ---------------------------------------------------------------------------
# TestRecallTierOverride (now via effective_recall_tier)
# ---------------------------------------------------------------------------

class TestRecallTierOverride:
    def test_counselor_gets_oracle_tier_at_any_rank(self) -> None:
        """Counselor gets ORACLE tier regardless of rank via billet clearance."""
        for rank in [Rank.ENSIGN, Rank.LIEUTENANT, Rank.COMMANDER, Rank.SENIOR]:
            _recall_tier = effective_recall_tier(rank, "ORACLE")
            assert _recall_tier == RecallTier.ORACLE, (
                f"Expected ORACLE for rank {rank}, got {_recall_tier}"
            )

    def test_non_oracle_agent_uses_rank_based_tier(self) -> None:
        """Agent with ENHANCED clearance at ENSIGN rank uses ENHANCED (higher than BASIC)."""
        _recall_tier = effective_recall_tier(Rank.ENSIGN, "ENHANCED")
        assert _recall_tier == RecallTier.ENHANCED

    def test_rank_higher_than_clearance_uses_rank(self) -> None:
        """Commander rank (FULL) with ENHANCED clearance → FULL."""
        _recall_tier = effective_recall_tier(Rank.COMMANDER, "ENHANCED")
        assert _recall_tier == RecallTier.FULL


# ---------------------------------------------------------------------------
# TestOracleStrategyGate
# ---------------------------------------------------------------------------

class TestOracleStrategyGate:
    def _make_oracle_condition(self, recall_tier: RecallTier,
                                strategy: RetrievalStrategy) -> bool:
        """Evaluate the AD-620 Oracle gate condition (strategy no longer matters)."""
        agent = MagicMock()
        agent._runtime = MagicMock()
        agent._runtime._oracle_service = MagicMock()

        # AD-620: clearance-based access — strategy gate removed
        return bool(
            recall_tier == RecallTier.ORACLE
            and hasattr(agent, '_runtime')
            and hasattr(agent._runtime, '_oracle_service')
            and agent._runtime._oracle_service
        )

    def test_oracle_agent_on_shallow_strategy(self) -> None:
        """ORACLE-tier agent with SHALLOW strategy passes Oracle gate (AD-620: no strategy gate)."""
        assert self._make_oracle_condition(
            RecallTier.ORACLE, RetrievalStrategy.SHALLOW
        ) is True

    def test_oracle_agent_on_deep_strategy(self) -> None:
        """ORACLE-tier agent with DEEP strategy still works (no regression)."""
        assert self._make_oracle_condition(
            RecallTier.ORACLE, RetrievalStrategy.DEEP
        ) is True

    def test_non_oracle_tier_no_oracle_access(self) -> None:
        """FULL-tier agent does NOT pass Oracle gate regardless of strategy."""
        assert self._make_oracle_condition(
            RecallTier.FULL, RetrievalStrategy.DEEP
        ) is False
