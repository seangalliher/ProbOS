"""Tests for Earned Agency — trust-tiered behavioral gating (AD-357)."""

import pytest
from probos.earned_agency import AgencyLevel, agency_from_rank, can_respond_ambient
from probos.crew_profile import Rank


class TestAgencyLevel:
    """AgencyLevel enum basics."""

    def test_enum_values(self):
        assert AgencyLevel.REACTIVE == "reactive"
        assert AgencyLevel.SUGGESTIVE == "suggestive"
        assert AgencyLevel.AUTONOMOUS == "autonomous"
        assert AgencyLevel.UNRESTRICTED == "unrestricted"

    def test_string_conversion(self):
        assert AgencyLevel.REACTIVE.value == "reactive"


class TestAgencyFromRank:
    """agency_from_rank() mapping."""

    def test_ensign_maps_to_reactive(self):
        assert agency_from_rank(Rank.ENSIGN) == AgencyLevel.REACTIVE

    def test_lieutenant_maps_to_suggestive(self):
        assert agency_from_rank(Rank.LIEUTENANT) == AgencyLevel.SUGGESTIVE

    def test_commander_maps_to_autonomous(self):
        assert agency_from_rank(Rank.COMMANDER) == AgencyLevel.AUTONOMOUS

    def test_senior_maps_to_unrestricted(self):
        assert agency_from_rank(Rank.SENIOR) == AgencyLevel.UNRESTRICTED


class TestCanRespondAmbient:
    """can_respond_ambient() — the core enforcement function."""

    # --- Ensign: never responds ambient ---
    def test_ensign_captain_same_dept(self):
        assert can_respond_ambient(Rank.ENSIGN, is_captain_post=True, same_department=True) is False

    def test_ensign_captain_other_dept(self):
        assert can_respond_ambient(Rank.ENSIGN, is_captain_post=True, same_department=False) is False

    def test_ensign_agent_same_dept(self):
        assert can_respond_ambient(Rank.ENSIGN, is_captain_post=False, same_department=True) is False

    # --- Lieutenant: captain + own department only ---
    def test_lieutenant_captain_same_dept(self):
        assert can_respond_ambient(Rank.LIEUTENANT, is_captain_post=True, same_department=True) is True

    def test_lieutenant_captain_ship_wide(self):
        assert can_respond_ambient(Rank.LIEUTENANT, is_captain_post=True, same_department=False) is False

    def test_lieutenant_agent_same_dept(self):
        assert can_respond_ambient(Rank.LIEUTENANT, is_captain_post=False, same_department=True) is False

    # --- Commander: all captain + own department agent ---
    def test_commander_captain_ship_wide(self):
        assert can_respond_ambient(Rank.COMMANDER, is_captain_post=True, same_department=False) is True

    def test_commander_captain_same_dept(self):
        assert can_respond_ambient(Rank.COMMANDER, is_captain_post=True, same_department=True) is True

    def test_commander_agent_same_dept(self):
        assert can_respond_ambient(Rank.COMMANDER, is_captain_post=False, same_department=True) is True

    def test_commander_agent_other_dept(self):
        assert can_respond_ambient(Rank.COMMANDER, is_captain_post=False, same_department=False) is False

    # --- Senior: unrestricted ---
    def test_senior_captain_ship_wide(self):
        assert can_respond_ambient(Rank.SENIOR, is_captain_post=True, same_department=False) is True

    def test_senior_agent_other_dept(self):
        assert can_respond_ambient(Rank.SENIOR, is_captain_post=False, same_department=False) is True


class TestWardRoomGating:
    """Integration tests: agency gating in Ward Room routing context.

    These test the gating logic with trust scores rather than Rank enums,
    simulating what happens in runtime._find_ward_room_targets.
    """

    def test_trust_0_3_is_ensign_reactive(self):
        """Trust 0.3 → Ensign → cannot respond ambient."""
        rank = Rank.from_trust(0.3)
        assert rank == Rank.ENSIGN
        assert can_respond_ambient(rank, is_captain_post=True, same_department=True) is False

    def test_trust_0_5_is_lieutenant_suggestive(self):
        """Trust 0.5 → Lieutenant → responds to Captain in own dept."""
        rank = Rank.from_trust(0.5)
        assert rank == Rank.LIEUTENANT
        assert can_respond_ambient(rank, is_captain_post=True, same_department=True) is True
        assert can_respond_ambient(rank, is_captain_post=True, same_department=False) is False

    def test_trust_0_7_is_commander_autonomous(self):
        """Trust 0.7 → Commander → full Captain response, dept agent response."""
        rank = Rank.from_trust(0.7)
        assert rank == Rank.COMMANDER
        assert can_respond_ambient(rank, is_captain_post=True, same_department=False) is True
        assert can_respond_ambient(rank, is_captain_post=False, same_department=True) is True
        assert can_respond_ambient(rank, is_captain_post=False, same_department=False) is False

    def test_trust_0_85_is_senior_unrestricted(self):
        """Trust 0.85 → Senior → unrestricted ambient response."""
        rank = Rank.from_trust(0.85)
        assert rank == Rank.SENIOR
        assert can_respond_ambient(rank, is_captain_post=False, same_department=False) is True

    def test_trust_0_99_is_senior(self):
        """Trust 0.99 → still Senior."""
        rank = Rank.from_trust(0.99)
        assert rank == Rank.SENIOR


class TestAgencyRegression:
    """Trust regression → agency reduction."""

    def test_trust_drop_reduces_agency(self):
        """Agent at Commander trust drops to Ensign → agency drops."""
        # Before: Commander
        assert agency_from_rank(Rank.from_trust(0.75)) == AgencyLevel.AUTONOMOUS
        # After trust drop: Ensign
        assert agency_from_rank(Rank.from_trust(0.35)) == AgencyLevel.REACTIVE

    def test_trust_drop_within_tier_no_change(self):
        """Trust drop within same tier → no agency change."""
        assert agency_from_rank(Rank.from_trust(0.8)) == AgencyLevel.AUTONOMOUS
        assert agency_from_rank(Rank.from_trust(0.72)) == AgencyLevel.AUTONOMOUS
