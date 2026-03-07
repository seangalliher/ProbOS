"""Tests for TrustNetwork."""

import pytest

from probos.consensus.trust import TrustNetwork, TrustRecord


class TestTrustRecord:
    def test_default_score(self):
        rec = TrustRecord(agent_id="a1")
        # alpha=2, beta=2 → score = 0.5
        assert rec.score == 0.5

    def test_score_increases_with_success(self):
        rec = TrustRecord(agent_id="a1", alpha=3.0, beta=2.0)
        assert rec.score == 0.6

    def test_score_decreases_with_failure(self):
        rec = TrustRecord(agent_id="a1", alpha=2.0, beta=3.0)
        assert rec.score == 0.4

    def test_uncertainty_decreases_with_observations(self):
        low_obs = TrustRecord(agent_id="a1", alpha=2.0, beta=2.0)
        high_obs = TrustRecord(agent_id="a2", alpha=20.0, beta=20.0)
        assert high_obs.uncertainty < low_obs.uncertainty

    def test_observations_count(self):
        rec = TrustRecord(agent_id="a1", alpha=5.0, beta=3.0)
        # Observations = (5-2) + (3-2) = 4
        assert rec.observations == 4.0


class TestTrustNetwork:
    def test_get_or_create(self):
        tn = TrustNetwork()
        rec = tn.get_or_create("a1")
        assert rec.agent_id == "a1"
        assert rec.score == 0.5

    def test_get_or_create_idempotent(self):
        tn = TrustNetwork()
        r1 = tn.get_or_create("a1")
        r2 = tn.get_or_create("a1")
        assert r1 is r2

    def test_record_success_increases_score(self):
        tn = TrustNetwork()
        initial = tn.get_or_create("a1").score
        tn.record_outcome("a1", success=True)
        assert tn.get_score("a1") > initial

    def test_record_failure_decreases_score(self):
        tn = TrustNetwork()
        initial = tn.get_or_create("a1").score
        tn.record_outcome("a1", success=False)
        assert tn.get_score("a1") < initial

    def test_repeated_failure_tanks_score(self):
        tn = TrustNetwork()
        tn.get_or_create("a1")
        for _ in range(20):
            tn.record_outcome("a1", success=False)
        assert tn.get_score("a1") < 0.15

    def test_repeated_success_boosts_score(self):
        tn = TrustNetwork()
        tn.get_or_create("a1")
        for _ in range(20):
            tn.record_outcome("a1", success=True)
        assert tn.get_score("a1") > 0.85

    def test_weighted_outcome(self):
        tn = TrustNetwork()
        tn.get_or_create("a1")
        tn.record_outcome("a1", success=True, weight=5.0)
        # alpha went from 2 to 7, beta stays at 2 → score = 7/9 ≈ 0.78
        assert tn.get_score("a1") > 0.7

    def test_decay_all_pulls_toward_prior(self):
        tn = TrustNetwork(decay_rate=0.5)
        tn.get_or_create("a1")
        for _ in range(10):
            tn.record_outcome("a1", success=True)
        score_before = tn.get_score("a1")
        tn.decay_all()
        score_after = tn.get_score("a1")
        # Score should move toward 0.5 (prior)
        assert abs(score_after - 0.5) < abs(score_before - 0.5)

    def test_remove(self):
        tn = TrustNetwork()
        tn.get_or_create("a1")
        tn.remove("a1")
        assert tn.get_record("a1") is None

    def test_all_scores(self):
        tn = TrustNetwork()
        tn.get_or_create("a1")
        tn.get_or_create("a2")
        scores = tn.all_scores()
        assert "a1" in scores
        assert "a2" in scores

    def test_summary(self):
        tn = TrustNetwork()
        tn.get_or_create("a1")
        tn.record_outcome("a1", success=True)
        summary = tn.summary()
        assert len(summary) == 1
        assert summary[0]["agent_id"] == "a1"
        assert "score" in summary[0]
        assert "uncertainty" in summary[0]

    @pytest.mark.asyncio
    async def test_sqlite_persistence(self, tmp_path):
        db_path = str(tmp_path / "trust.db")
        tn = TrustNetwork(db_path=db_path)
        await tn.start()
        tn.get_or_create("a1")
        for _ in range(5):
            tn.record_outcome("a1", success=True)
        score = tn.get_score("a1")
        await tn.stop()

        # Reload
        tn2 = TrustNetwork(db_path=db_path)
        await tn2.start()
        assert abs(tn2.get_score("a1") - score) < 0.001
        await tn2.stop()

    def test_unknown_agent_score_returns_prior(self):
        tn = TrustNetwork(prior_alpha=3.0, prior_beta=1.0)
        # No record for "unknown"
        score = tn.get_score("unknown")
        assert score == 0.75  # 3/(3+1)
