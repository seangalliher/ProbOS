"""Tests for CrewProfile + Personality System (AD-376)."""

from __future__ import annotations

import time
import pytest


class TestRank:
    def test_from_trust_ensign(self) -> None:
        from probos.crew_profile import Rank
        assert Rank.from_trust(0.3) == Rank.ENSIGN

    def test_from_trust_lieutenant(self) -> None:
        from probos.crew_profile import Rank
        assert Rank.from_trust(0.6) == Rank.LIEUTENANT

    def test_from_trust_commander(self) -> None:
        from probos.crew_profile import Rank
        assert Rank.from_trust(0.75) == Rank.COMMANDER

    def test_from_trust_senior(self) -> None:
        from probos.crew_profile import Rank
        assert Rank.from_trust(0.9) == Rank.SENIOR

    def test_boundary_050(self) -> None:
        from probos.crew_profile import Rank
        assert Rank.from_trust(0.5) == Rank.LIEUTENANT

    def test_boundary_085(self) -> None:
        from probos.crew_profile import Rank
        assert Rank.from_trust(0.85) == Rank.SENIOR


class TestPersonalityTraits:
    def test_default_neutral(self) -> None:
        from probos.crew_profile import PersonalityTraits
        p = PersonalityTraits()
        assert p.openness == 0.5

    def test_validation_rejects_out_of_range(self) -> None:
        from probos.crew_profile import PersonalityTraits
        with pytest.raises(ValueError):
            PersonalityTraits(openness=1.5)

    def test_distance_from_self_is_zero(self) -> None:
        from probos.crew_profile import PersonalityTraits
        p = PersonalityTraits(openness=0.8, conscientiousness=0.9)
        assert p.distance_from(p) == 0.0

    def test_distance_from_different(self) -> None:
        from probos.crew_profile import PersonalityTraits
        a = PersonalityTraits(openness=0.0, conscientiousness=0.0,
                              extraversion=0.0, agreeableness=0.0, neuroticism=0.0)
        b = PersonalityTraits(openness=1.0, conscientiousness=1.0,
                              extraversion=1.0, agreeableness=1.0, neuroticism=1.0)
        dist = a.distance_from(b)
        assert dist > 2.0  # sqrt(5) ≈ 2.236

    def test_roundtrip_dict(self) -> None:
        from probos.crew_profile import PersonalityTraits
        p = PersonalityTraits(openness=0.8, neuroticism=0.2)
        restored = PersonalityTraits.from_dict(p.to_dict())
        assert restored.openness == 0.8
        assert restored.neuroticism == 0.2


class TestCrewProfile:
    def test_personality_drift_zero_at_creation(self) -> None:
        from probos.crew_profile import CrewProfile, PersonalityTraits
        p = PersonalityTraits(openness=0.8)
        profile = CrewProfile(personality=p, personality_baseline=p)
        assert profile.personality_drift() == 0.0

    def test_personality_drift_nonzero(self) -> None:
        from probos.crew_profile import CrewProfile, PersonalityTraits
        baseline = PersonalityTraits(openness=0.5)
        current = PersonalityTraits(openness=0.9)
        profile = CrewProfile(personality=current, personality_baseline=baseline)
        assert profile.personality_drift() > 0.0

    def test_add_review(self) -> None:
        from probos.crew_profile import CrewProfile, PerformanceReview
        profile = CrewProfile(agent_id="test")
        review = PerformanceReview(trust_score=0.8, tasks_completed=10)
        profile.add_review(review)
        assert len(profile.reviews) == 1
        assert profile.latest_review() is review

    def test_promotion_velocity(self) -> None:
        from probos.crew_profile import CrewProfile
        profile = CrewProfile(
            commissioned=time.time() - 86400,  # 1 day ago
            promotions=2,
        )
        vel = profile.promotion_velocity()
        assert 1.5 < vel < 2.5  # ~2.0 per day

    def test_roundtrip_dict(self) -> None:
        from probos.crew_profile import CrewProfile, PersonalityTraits, Rank
        profile = CrewProfile(
            agent_id="test-001",
            agent_type="builder",
            display_name="Builder",
            callsign="Scotty",
            rank=Rank.COMMANDER,
        )
        restored = CrewProfile.from_dict(profile.to_dict())
        assert restored.agent_id == "test-001"
        assert restored.rank == Rank.COMMANDER
        assert restored.callsign == "Scotty"


class TestProfileStore:
    def test_get_or_create(self) -> None:
        from probos.crew_profile import ProfileStore
        store = ProfileStore()
        p = store.get_or_create("agent-1", agent_type="builder")
        assert p.agent_id == "agent-1"
        assert p.agent_type == "builder"

    def test_get_existing(self) -> None:
        from probos.crew_profile import ProfileStore
        store = ProfileStore()
        store.get_or_create("agent-1", agent_type="builder")
        p2 = store.get("agent-1")
        assert p2 is not None
        assert p2.agent_type == "builder"

    def test_update_persists(self) -> None:
        from probos.crew_profile import ProfileStore, Rank
        store = ProfileStore()
        p = store.get_or_create("agent-1")
        p.rank = Rank.COMMANDER
        store.update(p)
        # Re-fetch
        p2 = store.get("agent-1")
        assert p2 is not None
        assert p2.rank == Rank.COMMANDER

    def test_by_department(self) -> None:
        from probos.crew_profile import ProfileStore
        store = ProfileStore()
        store.get_or_create("a1", department="medical")
        store.get_or_create("a2", department="engineering")
        store.get_or_create("a3", department="medical")
        med = store.by_department("medical")
        assert len(med) == 2

    def test_all_profiles(self) -> None:
        from probos.crew_profile import ProfileStore
        store = ProfileStore()
        store.get_or_create("a1")
        store.get_or_create("a2")
        assert len(store.all_profiles()) == 2

    def test_close(self) -> None:
        from probos.crew_profile import ProfileStore
        store = ProfileStore()
        store.close()
        assert store._conn is None


class TestSeedProfiles:
    def test_load_seed_builder(self) -> None:
        from probos.crew_profile import load_seed_profile
        seed = load_seed_profile("builder")
        assert seed.get("callsign") == "Scotty"
        assert seed["personality"]["conscientiousness"] == 0.9

    def test_load_seed_unknown_falls_back_to_default(self) -> None:
        from probos.crew_profile import load_seed_profile
        seed = load_seed_profile("nonexistent_agent_type")
        # Should fall back to _default.yaml
        assert seed.get("role") == "crew"

    def test_load_seed_architect(self) -> None:
        from probos.crew_profile import load_seed_profile
        seed = load_seed_profile("architect")
        assert seed.get("callsign") == "Number One"
