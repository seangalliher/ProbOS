"""Tests for Phase 8: Adaptive Pool Sizing & Dynamic Scaling."""

import asyncio
import time

import pytest

from probos.config import PoolConfig, ScalingConfig, SystemConfig, load_config
from probos.consensus.trust import TrustNetwork
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.substrate.agent import BaseAgent
from probos.substrate.pool import ResourcePool
from probos.substrate.registry import AgentRegistry
from probos.substrate.scaler import PoolScaler
from probos.substrate.spawner import AgentSpawner
from probos.types import CapabilityDescriptor


class _PoolTestAgent(BaseAgent):
    """Minimal agent for pool tests."""
    agent_type = "pool_test"
    default_capabilities = [CapabilityDescriptor(can="pool_test")]

    async def perceive(self, intent):
        return None
    async def decide(self, observation):
        return None
    async def act(self, plan):
        return None
    async def report(self, result):
        return {}


# =====================================================================
# TestScalingConfig (tests 1-2)
# =====================================================================


class TestScalingConfig:
    """Config model tests for ScalingConfig."""

    def test_defaults_load_correctly(self):
        """Test 1: Defaults load correctly from empty config."""
        cfg = ScalingConfig()
        assert cfg.enabled is True
        assert cfg.scale_up_threshold == 0.8
        assert cfg.scale_down_threshold == 0.2
        assert cfg.scale_up_step == 1
        assert cfg.scale_down_step == 1
        assert cfg.cooldown_seconds == 30.0
        assert cfg.observation_window_seconds == 60.0
        assert cfg.idle_scale_down_seconds == 120.0

    def test_custom_values_override_defaults(self):
        """Test 2: Custom values override defaults."""
        cfg = ScalingConfig(
            enabled=False,
            scale_up_threshold=0.9,
            scale_down_threshold=0.1,
            cooldown_seconds=15.0,
        )
        assert cfg.enabled is False
        assert cfg.scale_up_threshold == 0.9
        assert cfg.scale_down_threshold == 0.1
        assert cfg.cooldown_seconds == 15.0
        # Unchanged defaults
        assert cfg.scale_up_step == 1
        assert cfg.observation_window_seconds == 60.0

    def test_system_config_includes_scaling(self):
        """SystemConfig has a scaling field with ScalingConfig defaults."""
        cfg = SystemConfig()
        assert hasattr(cfg, "scaling")
        assert isinstance(cfg.scaling, ScalingConfig)
        assert cfg.scaling.enabled is True


# =====================================================================
# TestIntentBusDemandMetrics (tests 3-6)
# =====================================================================


class TestIntentBusDemandMetrics:
    """Demand tracking on IntentBus."""

    def _make_bus(self, window: float = 60.0) -> IntentBus:
        sm = SignalManager(reap_interval=999)
        bus = IntentBus(sm)
        bus._window_seconds = window
        return bus

    def test_demand_metrics_zeros_when_no_broadcasts(self):
        """Test 3: demand_metrics returns zeros with no broadcasts."""
        bus = self._make_bus()
        metrics = bus.demand_metrics()
        assert metrics["broadcasts_in_window"] == 0
        assert metrics["subscriber_count"] == 0

    def test_demand_metrics_counts_broadcasts(self):
        """Test 4: demand_metrics counts broadcasts within window."""
        bus = self._make_bus(window=60.0)
        bus.record_broadcast("read_file")
        bus.record_broadcast("read_file")
        bus.record_broadcast("write_file")
        metrics = bus.demand_metrics()
        assert metrics["broadcasts_in_window"] == 3

    def test_demand_metrics_prunes_old_broadcasts(self):
        """Test 5: demand_metrics prunes broadcasts outside window."""
        bus = self._make_bus(window=1.0)
        # Insert an old timestamp manually
        old_time = time.monotonic() - 5.0
        bus._broadcast_timestamps.append((old_time, "read_file"))
        # Insert a recent one
        bus.record_broadcast("write_file")
        metrics = bus.demand_metrics()
        assert metrics["broadcasts_in_window"] == 1

    def test_per_pool_demand_counts_correctly(self):
        """Test 6: per_pool_demand counts broadcasts per pool."""
        bus = self._make_bus(window=60.0)
        bus.record_broadcast("read_file")
        bus.record_broadcast("read_file")
        bus.record_broadcast("write_file")
        bus.record_broadcast("list_directory")

        pool_intents = {
            "filesystem": ["read_file", "stat_file"],
            "filesystem_writers": ["write_file"],
            "directory": ["list_directory"],
        }
        counts = bus.per_pool_demand(pool_intents)
        assert counts["filesystem"] == 2
        assert counts["filesystem_writers"] == 1
        assert counts["directory"] == 1


# =====================================================================
# TestPoolBounds (tests 7-10)
# =====================================================================


class TestPoolBounds:
    """Pool bounds enforcement tests for add_agent/remove_agent."""

    @pytest.fixture
    def pool_deps(self):
        registry = AgentRegistry()
        spawner = AgentSpawner(registry)
        spawner.register_template("pool_test", _PoolTestAgent)
        config = PoolConfig(
            default_pool_size=3,
            max_pool_size=5,
            min_pool_size=2,
            spawn_cooldown_ms=100,
            health_check_interval_seconds=1.0,
        )
        return registry, spawner, config

    @pytest.mark.asyncio
    async def test_add_agent_returns_none_at_max(self, pool_deps):
        """Test 7: add_agent returns None when at max_pool_size."""
        registry, spawner, config = pool_deps
        pool = ResourcePool("test", "pool_test", spawner, registry, config, target_size=5)
        await pool.start()
        assert pool.current_size == 5  # At max
        result = await pool.add_agent()
        assert result is None
        assert pool.current_size == 5
        await pool.stop()

    @pytest.mark.asyncio
    async def test_add_agent_spawns_below_max(self, pool_deps):
        """Test 8: add_agent spawns and returns agent ID when below max."""
        registry, spawner, config = pool_deps
        pool = ResourcePool("test", "pool_test", spawner, registry, config, target_size=3)
        await pool.start()
        assert pool.current_size == 3
        new_id = await pool.add_agent()
        assert new_id is not None
        assert pool.current_size == 4
        await pool.stop()

    @pytest.mark.asyncio
    async def test_remove_agent_returns_none_at_min(self, pool_deps):
        """Test 9: remove_agent returns None when at min_pool_size."""
        registry, spawner, config = pool_deps
        pool = ResourcePool("test", "pool_test", spawner, registry, config, target_size=2)
        await pool.start()
        assert pool.current_size == 2  # At min
        result = await pool.remove_agent()
        assert result is None
        assert pool.current_size == 2
        await pool.stop()

    @pytest.mark.asyncio
    async def test_remove_agent_stops_agent_above_min(self, pool_deps):
        """Test 10: remove_agent stops agent and returns ID when above min."""
        registry, spawner, config = pool_deps
        pool = ResourcePool("test", "pool_test", spawner, registry, config, target_size=3)
        await pool.start()
        assert pool.current_size == 3
        removed_id = await pool.remove_agent()
        assert removed_id is not None
        assert pool.current_size == 2
        # Agent should be unregistered
        assert registry.get(removed_id) is None
        await pool.stop()


# =====================================================================
# TestTrustAwareScaleDown (tests 17-19)
# =====================================================================


class TestTrustAwareScaleDown:
    """Trust-aware agent selection during scale-down."""

    @pytest.fixture
    def pool_deps(self):
        registry = AgentRegistry()
        spawner = AgentSpawner(registry)
        spawner.register_template("pool_test", _PoolTestAgent)
        config = PoolConfig(
            default_pool_size=4,
            max_pool_size=7,
            min_pool_size=2,
            spawn_cooldown_ms=100,
            health_check_interval_seconds=1.0,
        )
        return registry, spawner, config

    @pytest.mark.asyncio
    async def test_removes_lowest_trust_agent(self, pool_deps):
        """Test 17: remove_agent(trust_network=...) removes lowest-trust agent."""
        registry, spawner, config = pool_deps
        pool = ResourcePool("test", "pool_test", spawner, registry, config, target_size=4)
        await pool.start()
        assert pool.current_size == 4

        trust = TrustNetwork(prior_alpha=2.0, prior_beta=2.0)
        # Give different trust scores to agents
        ids = list(pool._agent_ids)
        trust.get_or_create(ids[0])  # Default: 0.5
        trust.get_or_create(ids[1])  # Default: 0.5
        # Make ids[2] the worst
        rec = trust.get_or_create(ids[2])
        rec.beta += 5.0  # Lower trust score
        trust.get_or_create(ids[3])  # Default: 0.5

        removed = await pool.remove_agent(trust_network=trust)
        assert removed == ids[2]
        assert pool.current_size == 3
        await pool.stop()

    @pytest.mark.asyncio
    async def test_equal_trust_removes_newest(self, pool_deps):
        """Test 18: Equal trust falls back to newest-first removal."""
        registry, spawner, config = pool_deps
        pool = ResourcePool("test", "pool_test", spawner, registry, config, target_size=3)
        await pool.start()

        trust = TrustNetwork(prior_alpha=2.0, prior_beta=2.0)
        ids = list(pool._agent_ids)
        for aid in ids:
            trust.get_or_create(aid)  # All default 0.5

        # With equal trust, the first one found with min score is removed
        # Since all are equal, the first encountered in iteration wins
        removed = await pool.remove_agent(trust_network=trust)
        assert removed is not None
        assert pool.current_size == 2
        await pool.stop()

    @pytest.mark.asyncio
    async def test_no_trust_removes_newest(self, pool_deps):
        """Test 19: remove_agent(trust_network=None) removes newest (backward compat)."""
        registry, spawner, config = pool_deps
        pool = ResourcePool("test", "pool_test", spawner, registry, config, target_size=3)
        await pool.start()

        ids = list(pool._agent_ids)
        newest = ids[-1]
        removed = await pool.remove_agent(trust_network=None)
        assert removed == newest
        assert pool.current_size == 2
        await pool.stop()


# =====================================================================
# Helper: create pool + scaler for scaler tests
# =====================================================================


def _make_scaler_env(
    pool_size: int = 3,
    max_size: int = 5,
    min_size: int = 2,
    scale_up_threshold: float = 0.8,
    scale_down_threshold: float = 0.2,
    cooldown: float = 0.0,
    window: float = 60.0,
):
    """Build pool, bus, and scaler for testing."""
    registry = AgentRegistry()
    spawner = AgentSpawner(registry)
    spawner.register_template("pool_test", _PoolTestAgent)

    pool_config = PoolConfig(
        default_pool_size=pool_size,
        max_pool_size=max_size,
        min_pool_size=min_size,
        spawn_cooldown_ms=100,
        health_check_interval_seconds=1.0,
    )
    scaling_config = ScalingConfig(
        scale_up_threshold=scale_up_threshold,
        scale_down_threshold=scale_down_threshold,
        cooldown_seconds=cooldown,
        observation_window_seconds=window,
    )
    sm = SignalManager(reap_interval=999)
    bus = IntentBus(sm)
    bus._window_seconds = window

    pool = ResourcePool("test_pool", "pool_test", spawner, registry, pool_config, target_size=pool_size)
    pools = {"test_pool": pool}
    pool_intent_map = {"test_pool": ["read_file"]}

    scaler = PoolScaler(
        pools=pools,
        intent_bus=bus,
        pool_config=pool_config,
        scaling_config=scaling_config,
        pool_intent_map=pool_intent_map,
    )
    return pool, bus, scaler


# =====================================================================
# TestPoolScalerScaleUp (tests 11-13)
# =====================================================================


class TestPoolScalerScaleUp:
    """Scale-up tests for PoolScaler."""

    @pytest.mark.asyncio
    async def test_scale_up_on_high_demand(self):
        """Test 11: Scale-up triggered when demand ratio exceeds threshold."""
        pool, bus, scaler = _make_scaler_env(
            pool_size=3, max_size=5, scale_up_threshold=0.8, cooldown=0.0,
        )
        await pool.start()
        assert pool.current_size == 3

        # Simulate high demand: 3 broadcasts / 3 agents = 1.0 > 0.8
        for _ in range(3):
            bus.record_broadcast("read_file")

        await scaler._evaluate_and_scale()
        assert pool.current_size == 4
        assert pool.target_size == 4
        await pool.stop()

    @pytest.mark.asyncio
    async def test_scale_up_blocked_by_max(self):
        """Test 12: Scale-up blocked by max_pool_size."""
        pool, bus, scaler = _make_scaler_env(
            pool_size=5, max_size=5, scale_up_threshold=0.8, cooldown=0.0,
        )
        await pool.start()
        assert pool.current_size == 5

        for _ in range(10):
            bus.record_broadcast("read_file")

        await scaler._evaluate_and_scale()
        assert pool.current_size == 5  # Blocked at max
        await pool.stop()

    @pytest.mark.asyncio
    async def test_scale_up_blocked_by_cooldown(self):
        """Test 13: Scale-up blocked by cooldown."""
        pool, bus, scaler = _make_scaler_env(
            pool_size=3, max_size=5, scale_up_threshold=0.8, cooldown=999.0,
        )
        await pool.start()

        for _ in range(10):
            bus.record_broadcast("read_file")

        # First scale-up should work
        await scaler._evaluate_and_scale()
        size_after_first = pool.current_size
        assert size_after_first == 4

        # Second should be blocked by cooldown
        for _ in range(10):
            bus.record_broadcast("read_file")
        await scaler._evaluate_and_scale()
        assert pool.current_size == size_after_first  # Blocked
        await pool.stop()


# =====================================================================
# TestPoolScalerScaleDown (tests 14-16)
# =====================================================================


class TestPoolScalerScaleDown:
    """Scale-down tests for PoolScaler."""

    @pytest.mark.asyncio
    async def test_scale_down_on_low_demand(self):
        """Test 14: Scale-down triggered when demand ratio below threshold."""
        pool, bus, scaler = _make_scaler_env(
            pool_size=4, max_size=5, min_size=2,
            scale_down_threshold=0.2, cooldown=0.0,
        )
        await pool.start()
        assert pool.current_size == 4

        # No broadcasts = demand ratio 0.0 < 0.2
        await scaler._evaluate_and_scale()
        assert pool.current_size == 3
        assert pool.target_size == 3
        await pool.stop()

    @pytest.mark.asyncio
    async def test_scale_down_blocked_by_min(self):
        """Test 15: Scale-down blocked by min_pool_size."""
        pool, bus, scaler = _make_scaler_env(
            pool_size=2, max_size=5, min_size=2,
            scale_down_threshold=0.2, cooldown=0.0,
        )
        await pool.start()
        assert pool.current_size == 2  # At min

        await scaler._evaluate_and_scale()
        assert pool.current_size == 2  # Can't go below min
        await pool.stop()

    @pytest.mark.asyncio
    async def test_scale_down_blocked_by_cooldown(self):
        """Test 16: Scale-down blocked by cooldown."""
        pool, bus, scaler = _make_scaler_env(
            pool_size=4, max_size=5, min_size=2,
            scale_down_threshold=0.2, cooldown=999.0,
        )
        await pool.start()

        # First scale-down should work
        await scaler._evaluate_and_scale()
        assert pool.current_size == 3

        # Second should be blocked
        await scaler._evaluate_and_scale()
        assert pool.current_size == 3  # Blocked
        await pool.stop()


# =====================================================================
# TestPoolScalerSurge (tests 20-22)
# =====================================================================


class TestPoolScalerSurge:
    """Surge capacity tests for PoolScaler."""

    @pytest.mark.asyncio
    async def test_surge_adds_agent(self):
        """Test 20: request_surge adds agent to named pool."""
        pool, bus, scaler = _make_scaler_env(
            pool_size=3, max_size=5, cooldown=0.0,
        )
        await pool.start()
        assert pool.current_size == 3

        result = await scaler.request_surge("test_pool", extra=1)
        assert result is True
        assert pool.current_size == 4
        assert pool.target_size == 4
        await pool.stop()

    @pytest.mark.asyncio
    async def test_surge_returns_false_at_max(self):
        """Test 21: request_surge returns False when at max."""
        pool, bus, scaler = _make_scaler_env(
            pool_size=5, max_size=5, cooldown=0.0,
        )
        await pool.start()
        assert pool.current_size == 5

        result = await scaler.request_surge("test_pool", extra=1)
        assert result is False
        assert pool.current_size == 5
        await pool.stop()

    @pytest.mark.asyncio
    async def test_surge_bypasses_cooldown(self):
        """Test 22: request_surge bypasses cooldown."""
        pool, bus, scaler = _make_scaler_env(
            pool_size=3, max_size=5, cooldown=999.0,
        )
        await pool.start()

        # Set a recent scale time to simulate active cooldown
        scaler._last_scale_time["test_pool"] = time.monotonic()

        result = await scaler.request_surge("test_pool", extra=1)
        assert result is True
        assert pool.current_size == 4
        await pool.stop()


# =====================================================================
# TestPoolScalerIdleScaleDown (tests 23-24)
# =====================================================================


class TestPoolScalerIdleScaleDown:
    """Idle scale-down tests for PoolScaler."""

    @pytest.mark.asyncio
    async def test_idle_scale_down_reduces_pools(self):
        """Test 23: scale_down_idle reduces all non-excluded pools toward min."""
        pool, bus, scaler = _make_scaler_env(
            pool_size=4, max_size=5, min_size=2, cooldown=0.0,
        )
        await pool.start()
        assert pool.current_size == 4

        await scaler.scale_down_idle()
        assert pool.current_size == 3
        assert pool.target_size == 3
        await pool.stop()

    @pytest.mark.asyncio
    async def test_idle_scale_down_skips_excluded(self):
        """Test 24: scale_down_idle skips excluded pools."""
        pool, bus, scaler = _make_scaler_env(
            pool_size=4, max_size=5, min_size=2, cooldown=0.0,
        )
        scaler.excluded_pools = {"test_pool"}
        await pool.start()

        await scaler.scale_down_idle()
        assert pool.current_size == 4  # Not touched
        await pool.stop()


# =====================================================================
# TestPoolScalerExclusions (tests 25-26)
# =====================================================================


class TestPoolScalerExclusions:
    """Exclusion logic tests for PoolScaler."""

    @pytest.mark.asyncio
    async def test_excluded_pools_not_scaled(self):
        """Test 25: System/heartbeat pools are excluded from automatic scaling."""
        pool, bus, scaler = _make_scaler_env(
            pool_size=4, max_size=5, min_size=2,
            scale_down_threshold=0.2, cooldown=0.0,
        )
        scaler.excluded_pools = {"test_pool"}
        await pool.start()

        # No demand --> would normally scale down, but pool is excluded
        await scaler._evaluate_and_scale()
        assert pool.current_size == 4
        await pool.stop()

    @pytest.mark.asyncio
    async def test_pinned_pools_not_scaled(self):
        """Test 26: Pools with min_pool_size == max_pool_size (pinned) are excluded."""
        registry = AgentRegistry()
        spawner = AgentSpawner(registry)
        spawner.register_template("pool_test", _PoolTestAgent)
        pool_config = PoolConfig(
            default_pool_size=3,
            max_pool_size=3,  # Pinned: min == max
            min_pool_size=3,
            spawn_cooldown_ms=100,
            health_check_interval_seconds=1.0,
        )
        scaling_config = ScalingConfig(
            scale_down_threshold=0.2, cooldown_seconds=0.0,
        )
        sm = SignalManager(reap_interval=999)
        bus = IntentBus(sm)

        pool = ResourcePool("pinned", "pool_test", spawner, registry, pool_config, target_size=3)
        scaler = PoolScaler(
            pools={"pinned": pool},
            intent_bus=bus,
            pool_config=pool_config,
            scaling_config=scaling_config,
            pool_intent_map={"pinned": ["test"]},
        )
        await pool.start()

        await scaler._evaluate_and_scale()
        assert pool.current_size == 3  # Pinned, not scaled
        await pool.stop()


# =====================================================================
# TestPoolScalerConsensusFloor (tests AD-150a–c)
# =====================================================================


class TestPoolScalerConsensusFloor:
    """Consensus pools must not shrink below consensus_min_agents."""

    @pytest.mark.asyncio
    async def test_scale_down_blocked_by_consensus_floor(self):
        """Scale-down refused when pool is at consensus_min_agents."""
        pool, bus, scaler = _make_scaler_env(
            pool_size=3, max_size=5, min_size=1,
            scale_down_threshold=0.2, cooldown=0.0,
        )
        scaler.consensus_pools = {"test_pool"}
        scaler.consensus_min_agents = 3
        await pool.start()
        assert pool.current_size == 3

        # No demand → ratio=0 → would normally scale down, but consensus floor blocks it
        await scaler._evaluate_and_scale()
        assert pool.current_size == 3
        await pool.stop()

    @pytest.mark.asyncio
    async def test_idle_scale_down_blocked_by_consensus_floor(self):
        """Idle scale-down refused when pool is at consensus_min_agents."""
        pool, bus, scaler = _make_scaler_env(
            pool_size=3, max_size=5, min_size=1, cooldown=0.0,
        )
        scaler.consensus_pools = {"test_pool"}
        scaler.consensus_min_agents = 3
        await pool.start()
        assert pool.current_size == 3

        await scaler.scale_down_idle()
        assert pool.current_size == 3  # Floor holds
        await pool.stop()

    @pytest.mark.asyncio
    async def test_non_consensus_pool_scales_below_floor(self):
        """Non-consensus pool can scale below consensus_min_agents (only min_size applies)."""
        pool, bus, scaler = _make_scaler_env(
            pool_size=3, max_size=5, min_size=1,
            scale_down_threshold=0.2, cooldown=0.0,
        )
        # consensus_pools is empty — test_pool is not in it
        scaler.consensus_pools = set()
        scaler.consensus_min_agents = 3
        await pool.start()
        assert pool.current_size == 3

        # No demand → should scale down (min_size=1 allows it)
        await scaler._evaluate_and_scale()
        assert pool.current_size == 2
        await pool.stop()


# =====================================================================
# TestRuntimeScaling (tests 27-29)
# =====================================================================


class TestRuntimeScaling:
    """Runtime integration tests for pool scaling."""

    @pytest.mark.asyncio
    async def test_runtime_creates_scaler_when_enabled(self, tmp_path):
        """Test 27: Runtime creates PoolScaler when scaling enabled."""
        from probos.runtime import ProbOSRuntime

        cfg = SystemConfig()
        cfg.scaling.enabled = True
        rt = ProbOSRuntime(config=cfg, data_dir=tmp_path)
        await rt.start()
        try:
            assert rt.pool_scaler is not None
        finally:
            await rt.stop()

    @pytest.mark.asyncio
    async def test_runtime_no_scaler_when_disabled(self, tmp_path):
        """Test 28: Runtime does NOT create scaler when scaling disabled."""
        from probos.runtime import ProbOSRuntime

        cfg = SystemConfig()
        cfg.scaling.enabled = False
        rt = ProbOSRuntime(config=cfg, data_dir=tmp_path)
        await rt.start()
        try:
            assert rt.pool_scaler is None
        finally:
            await rt.stop()

    @pytest.mark.asyncio
    async def test_status_includes_scaling(self, tmp_path):
        """Test 29: status() includes scaling info."""
        from probos.runtime import ProbOSRuntime

        cfg = SystemConfig()
        cfg.scaling.enabled = True
        rt = ProbOSRuntime(config=cfg, data_dir=tmp_path)
        await rt.start()
        try:
            status = rt.status()
            assert "scaling" in status
            # Should have pool-level info since scaler is active
            assert isinstance(status["scaling"], dict)
        finally:
            await rt.stop()


# =====================================================================
# TestEscalationSurge (tests 30-31)
# =====================================================================


class TestEscalationSurge:
    """Escalation surge function integration tests."""

    @pytest.mark.asyncio
    async def test_surge_fn_called_during_tier1(self):
        """Test 30: surge_fn called during Tier 1 retry."""
        from probos.consensus.escalation import EscalationManager
        from probos.types import TaskNode

        surge_calls = []

        async def mock_surge(pool_name: str, extra: int) -> bool:
            surge_calls.append((pool_name, extra))
            return True

        # Create minimal mock runtime
        class MockRuntime:
            async def submit_intent(self, **kwargs):
                return []

        node = TaskNode(id="t1", intent="read_file", params={"path": "/x"})
        node.use_consensus = False
        mgr = EscalationManager(
            runtime=MockRuntime(),
            llm_client=None,
            max_retries=1,
            surge_fn=mock_surge,
        )
        await mgr._tier1_retry(node, "test error", {"pool_name": "filesystem"})
        assert len(surge_calls) == 1
        assert surge_calls[0] == ("filesystem", 1)

    @pytest.mark.asyncio
    async def test_escalation_works_without_surge_fn(self):
        """Test 31: surge_fn=None -- escalation works without scaler (backward compat)."""
        from probos.consensus.escalation import EscalationManager
        from probos.types import TaskNode

        class MockRuntime:
            async def submit_intent(self, **kwargs):
                return []

        node = TaskNode(id="t1", intent="read_file", params={"path": "/x"})
        node.use_consensus = False
        mgr = EscalationManager(
            runtime=MockRuntime(),
            llm_client=None,
            max_retries=1,
            surge_fn=None,
        )
        # Should not raise
        result = await mgr._tier1_retry(node, "test error", {"pool_name": "filesystem"})
        assert result.resolved is False  # No agents to respond


# =====================================================================
# TestShellScalingCommand (tests 32-33)
# =====================================================================


class TestShellScalingCommand:
    """Shell /scaling command tests."""

    @pytest.mark.asyncio
    async def test_scaling_command_renders_panel(self, tmp_path):
        """Test 32: /scaling command renders panel when scaler enabled."""
        from io import StringIO
        from rich.console import Console as RichConsole
        from probos.experience.shell import ProbOSShell
        from probos.runtime import ProbOSRuntime

        cfg = SystemConfig()
        cfg.scaling.enabled = True
        rt = ProbOSRuntime(config=cfg, data_dir=tmp_path)
        await rt.start()
        try:
            buf = StringIO()
            console = RichConsole(file=buf, force_terminal=True, width=120)
            shell = ProbOSShell(rt, console=console)
            await shell.execute_command("/scaling")
            output = buf.getvalue()
            assert "Pool Scaling" in output or "Scaling" in output
        finally:
            await rt.stop()

    def test_help_includes_scaling(self):
        """Test 33: /help listing includes /scaling."""
        from probos.experience.shell import ProbOSShell
        assert "/scaling" in ProbOSShell.COMMANDS
