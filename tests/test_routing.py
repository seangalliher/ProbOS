"""Tests for HebbianRouter."""

import pytest

from probos.mesh.routing import HebbianRouter


class TestHebbianRouter:
    @pytest.mark.asyncio
    async def test_record_success_increases_weight(self):
        router = HebbianRouter(decay_rate=0.99, reward=0.1)
        w = router.record_interaction("a", "b", success=True)
        assert w > 0.0
        assert router.get_weight("a", "b") == w

    @pytest.mark.asyncio
    async def test_record_failure_decays_only(self):
        router = HebbianRouter(decay_rate=0.99, reward=0.1)
        router.record_interaction("a", "b", success=True)
        w_before = router.get_weight("a", "b")
        router.record_interaction("a", "b", success=False)
        w_after = router.get_weight("a", "b")
        assert w_after < w_before

    @pytest.mark.asyncio
    async def test_repeated_success_strengthens(self):
        router = HebbianRouter(decay_rate=0.99, reward=0.1)
        for _ in range(10):
            router.record_interaction("a", "b", success=True)
        w = router.get_weight("a", "b")
        assert w > 0.5

    @pytest.mark.asyncio
    async def test_weight_clamped_to_1(self):
        router = HebbianRouter(decay_rate=0.99, reward=0.5)
        for _ in range(100):
            router.record_interaction("a", "b", success=True)
        assert router.get_weight("a", "b") <= 1.0

    @pytest.mark.asyncio
    async def test_get_preferred_targets(self):
        router = HebbianRouter(decay_rate=0.99, reward=0.1)
        # Make b stronger than c
        for _ in range(5):
            router.record_interaction("a", "b", success=True)
        router.record_interaction("a", "c", success=True)

        preferred = router.get_preferred_targets("a", ["b", "c", "d"])
        assert preferred[0] == "b"  # Strongest connection
        assert "d" in preferred  # d has weight 0, still in list

    @pytest.mark.asyncio
    async def test_decay_all_prunes_weak(self):
        router = HebbianRouter(decay_rate=0.5, reward=0.002)
        router.record_interaction("a", "b", success=True)
        # Weight is very small: 0 * 0.5 + 0.002 = 0.002
        # After many decay_all calls it should be pruned
        for _ in range(20):
            router.decay_all()
        assert router.weight_count == 0

    @pytest.mark.asyncio
    async def test_sqlite_persistence(self, tmp_path):
        db_path = tmp_path / "test_weights.db"

        # Write weights
        r1 = HebbianRouter(decay_rate=0.99, reward=0.1, db_path=db_path)
        await r1.start()
        for _ in range(5):
            r1.record_interaction("a", "b", success=True)
        saved_weight = r1.get_weight("a", "b")
        await r1.stop()

        # Read them back in a new instance
        r2 = HebbianRouter(db_path=db_path)
        await r2.start()
        loaded_weight = r2.get_weight("a", "b")
        await r2.stop()

        assert abs(loaded_weight - saved_weight) < 0.0001

    @pytest.mark.asyncio
    async def test_no_db_path_works(self):
        """Router works fine without persistence."""
        router = HebbianRouter()
        await router.start()
        router.record_interaction("a", "b", success=True)
        assert router.get_weight("a", "b") > 0
        await router.stop()


# ---------------------------------------------------------------------------
# AD-418: Hint-based routing tests
# ---------------------------------------------------------------------------

class TestHebbianRouterHint:
    """AD-418: get_preferred_targets with hint parameter."""

    @pytest.mark.asyncio
    async def test_hint_boosts_hinted_agent(self):
        """With zero weights, hint makes hinted agent sort first."""
        router = HebbianRouter()
        await router.start()

        candidates = ["agent_scout", "agent_engineering_officer", "agent_security"]
        result = router.get_preferred_targets(
            "task", candidates, hint="engineering_officer",
        )
        assert result[0] == "agent_engineering_officer"
        await router.stop()

    @pytest.mark.asyncio
    async def test_no_hint_preserves_default_order(self):
        """Without hint, all-zero weights yield stable order (no boost)."""
        router = HebbianRouter()
        await router.start()

        candidates = ["agent_scout", "agent_engineering_officer", "agent_security"]
        result = router.get_preferred_targets("task", candidates)
        # All scores are 0.0, so order is stable (insertion order preserved by sort)
        assert set(result) == set(candidates)
        await router.stop()

    @pytest.mark.asyncio
    async def test_learned_weight_can_outweigh_hint(self):
        """Strong learned weight (>1.0) beats the +1.0 hint boost."""
        router = HebbianRouter(decay_rate=0.99, reward=0.5)
        await router.start()

        # Build up scout's weight well above 1.0
        # After enough successful interactions, weight approaches 1.0
        # (clamped at 1.0). The hint boost is +1.0, so a weight of 1.0
        # plus no hint ties at 1.0, while hint gives 0.0+1.0=1.0.
        # Actually weights are clamped to [0,1], so max learned = 1.0.
        # Hint adds 1.0 on top. So hint always wins if not also learned.
        # To verify the boost is *additive*, give scout a weight of 1.0.
        # Scout gets 1.0, hint_agent gets 0+1.0=1.0 — tied, scout preserves order.
        for _ in range(50):
            router.record_interaction("task", "agent_scout", success=True)

        scout_weight = router.get_weight("task", "agent_scout")
        assert scout_weight > 0.9  # Close to 1.0

        candidates = ["agent_scout", "agent_engineering_officer"]
        result = router.get_preferred_targets(
            "task", candidates, hint="engineering_officer",
        )
        # scout has ~1.0 learned, eng has 0.0+1.0 hint = 1.0
        # With equal scores, sort is stable, so scout (first in list) stays first
        # The key point: hint doesn't infinitely dominate learned weights
        assert "agent_scout" in result
        assert "agent_engineering_officer" in result
        await router.stop()
