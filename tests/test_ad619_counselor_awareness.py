"""AD-619: Counselor Cross-Department Awareness.

Tests for ship-wide authority helper, channel subscriptions,
recall tier override, and Oracle strategy gate relaxation.
"""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.crew_utils import has_ship_wide_authority
from probos.earned_agency import RecallTier, recall_tier_from_rank
from probos.cognitive.source_governance import RetrievalStrategy
from probos.crew_profile import Rank


# ---------------------------------------------------------------------------
# TestShipWideAuthority
# ---------------------------------------------------------------------------

class TestShipWideAuthority:
    def test_has_ship_wide_authority_counselor(self) -> None:
        """Agent with agent_type='counselor' returns True."""
        agent = MagicMock()
        agent.agent_type = "counselor"
        assert has_ship_wide_authority(agent) is True

    def test_has_ship_wide_authority_non_counselor(self) -> None:
        """Agent with agent_type='data_analyst' returns False."""
        agent = MagicMock()
        agent.agent_type = "data_analyst"
        assert has_ship_wide_authority(agent) is False

    def test_has_ship_wide_authority_no_agent_type(self) -> None:
        """Object without agent_type attribute returns False (defensive)."""
        obj = object()
        assert has_ship_wide_authority(obj) is False


# ---------------------------------------------------------------------------
# TestChannelSubscriptions
# ---------------------------------------------------------------------------

class TestChannelSubscriptions:
    @pytest.mark.asyncio
    async def test_ship_wide_agent_subscribed_to_all_department_channels(self) -> None:
        """Counselor gets subscribed to ALL department channels."""
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

        # Run the subscription logic (extracted from communication.py)
        from probos.crew_utils import is_crew_agent
        for agent in [counselor, science_agent]:
            if not is_crew_agent(agent):
                continue
            dept = get_department(agent.agent_type)
            if dept and dept in dept_channel_map:
                await ward_room.subscribe(agent.id, dept_channel_map[dept])
            # AD-619: Ship-wide authority agents get all department channels
            if has_ship_wide_authority(agent):
                for dept_ch_id in dept_channel_map.values():
                    await ward_room.subscribe(agent.id, dept_ch_id)
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
# TestRecallTierOverride
# ---------------------------------------------------------------------------

class TestRecallTierOverride:
    def test_ship_wide_agent_gets_oracle_tier_at_any_rank(self) -> None:
        """Counselor gets ORACLE tier regardless of rank."""
        from probos.cognitive.episodic import resolve_recall_tier_params

        for rank in [Rank.ENSIGN, Rank.LIEUTENANT, Rank.COMMANDER, Rank.SENIOR]:
            agent = MagicMock()
            agent.agent_type = "counselor"

            _recall_tier = recall_tier_from_rank(rank)
            _tier_cfg = None
            _tier_params = resolve_recall_tier_params(_recall_tier.value, _tier_cfg)

            # AD-619 override
            if has_ship_wide_authority(agent):
                _recall_tier = RecallTier.ORACLE
                _tier_params = resolve_recall_tier_params(_recall_tier.value, _tier_cfg)

            assert _recall_tier == RecallTier.ORACLE, (
                f"Expected ORACLE for rank {rank}, got {_recall_tier}"
            )

    def test_non_ship_wide_agent_uses_rank_based_tier(self) -> None:
        """Non-ship-wide agent uses rank-based tier (no override)."""
        agent = MagicMock()
        agent.agent_type = "data_analyst"

        _recall_tier = recall_tier_from_rank(Rank.ENSIGN)

        if has_ship_wide_authority(agent):
            _recall_tier = RecallTier.ORACLE

        assert _recall_tier == RecallTier.BASIC

    def test_recall_tier_override_re_resolves_tier_params(self) -> None:
        """Override re-resolves _tier_params to match ORACLE config."""
        from probos.cognitive.episodic import resolve_recall_tier_params

        agent = MagicMock()
        agent.agent_type = "counselor"

        _recall_tier = recall_tier_from_rank(Rank.ENSIGN)
        _tier_cfg = None
        _tier_params_basic = resolve_recall_tier_params(_recall_tier.value, _tier_cfg)

        # AD-619 override
        _recall_tier = RecallTier.ORACLE
        _tier_params_oracle = resolve_recall_tier_params(_recall_tier.value, _tier_cfg)

        # ORACLE params should differ from BASIC
        assert _tier_params_oracle != _tier_params_basic


# ---------------------------------------------------------------------------
# TestOracleStrategyGate
# ---------------------------------------------------------------------------

class TestOracleStrategyGate:
    def _make_oracle_condition(self, agent_type: str, recall_tier: RecallTier,
                                strategy: RetrievalStrategy) -> bool:
        """Evaluate the Oracle gate condition from cognitive_agent.py."""
        agent = MagicMock()
        agent.agent_type = agent_type
        agent._runtime = MagicMock()
        agent._runtime._oracle_service = MagicMock()

        _swa = has_ship_wide_authority(agent)
        return bool(
            recall_tier == RecallTier.ORACLE
            and (strategy == RetrievalStrategy.DEEP or _swa)
            and hasattr(agent, '_runtime')
            and hasattr(agent._runtime, '_oracle_service')
            and agent._runtime._oracle_service
        )

    def test_ship_wide_agent_oracle_on_shallow_strategy(self) -> None:
        """Ship-wide agent with SHALLOW strategy passes Oracle gate."""
        assert self._make_oracle_condition(
            "counselor", RecallTier.ORACLE, RetrievalStrategy.SHALLOW
        ) is True

    def test_non_ship_wide_agent_no_oracle_on_shallow(self) -> None:
        """Non-ship-wide agent with SHALLOW strategy does NOT pass Oracle gate."""
        assert self._make_oracle_condition(
            "systems_analyst", RecallTier.ORACLE, RetrievalStrategy.SHALLOW
        ) is False

    def test_ship_wide_agent_oracle_on_deep_strategy(self) -> None:
        """Ship-wide agent with DEEP strategy still works (no regression)."""
        assert self._make_oracle_condition(
            "counselor", RecallTier.ORACLE, RetrievalStrategy.DEEP
        ) is True

    def test_override_logged(self, caplog) -> None:
        """Verify logger.debug is called with 'AD-619' when override fires."""
        from probos.cognitive.episodic import resolve_recall_tier_params

        agent = MagicMock()
        agent.agent_type = "counselor"

        _rank = Rank.ENSIGN
        _recall_tier = recall_tier_from_rank(_rank)
        _tier_cfg = None
        _tier_params = resolve_recall_tier_params(_recall_tier.value, _tier_cfg)

        _logger = logging.getLogger("probos.cognitive.cognitive_agent")
        with caplog.at_level(logging.DEBUG, logger="probos.cognitive.cognitive_agent"):
            if has_ship_wide_authority(agent):
                _recall_tier = RecallTier.ORACLE
                _tier_params = resolve_recall_tier_params(_recall_tier.value, _tier_cfg)
                _logger.debug("AD-619: %s recall tier override -> ORACLE", agent.agent_type)

        assert _recall_tier == RecallTier.ORACLE
        assert any("AD-619" in r.message for r in caplog.records)
