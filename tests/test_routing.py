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
