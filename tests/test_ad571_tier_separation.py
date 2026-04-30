"""AD-571: Agent tier trust separation tests."""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from probos.cognitive.emergence_metrics import EmergenceMetricsEngine
from probos.config import AgentTierConfig, EmergenceMetricsConfig, SystemConfig, TrustDampeningConfig
from probos.consensus.trust import TrustNetwork
from probos.mesh.routing import HebbianRouter
from probos.startup.finalize import _populate_agent_tiers
from probos.substrate.agent_tier import AgentTier, AgentTierRegistry


class _FakeRegistry:
    def __init__(self, agents: list[SimpleNamespace]) -> None:
        self._agents = agents

    def all(self) -> list[SimpleNamespace]:
        return list(self._agents)


class _FakeTierAwareService:
    def __init__(self) -> None:
        self.registry: AgentTierRegistry | None = None

    def set_tier_registry(self, registry: AgentTierRegistry) -> None:
        self.registry = registry


def _registry_with(**tiers: AgentTier) -> AgentTierRegistry:
    registry = AgentTierRegistry()
    for agent_id, tier in tiers.items():
        registry.register(agent_id, tier)
    return registry


def _thread(thread_id: str, posts: list[dict[str, str]]) -> dict[str, object]:
    return {"id": thread_id, "posts": posts}


def _post(author_id: str, body: str) -> dict[str, object]:
    return {
        "id": f"{author_id}_{abs(hash(body)) % 10000}",
        "author_id": author_id,
        "body": body,
        "created_at": time.time(),
    }


class _FakeWardRoom:
    def __init__(self, threads: list[dict[str, object]]) -> None:
        self._threads = threads
        self._by_id = {str(thread["id"]): thread for thread in threads}

    async def browse_threads(
        self,
        agent_id: str,
        channels: object,
        limit: int,
        since: float,
    ) -> list[SimpleNamespace]:
        return [SimpleNamespace(id=thread["id"]) for thread in self._threads]

    async def get_thread(self, thread_id: str) -> dict[str, object] | None:
        return self._by_id.get(thread_id)


def test_register_and_get_tier() -> None:
    registry = AgentTierRegistry()

    registry.register("agent-a", AgentTier.CREW)

    assert registry.get_tier("agent-a") == AgentTier.CREW


def test_default_tier_utility() -> None:
    registry = AgentTierRegistry()

    assert registry.get_tier("unknown-agent") == AgentTier.UTILITY


def test_is_crew() -> None:
    registry = _registry_with(agent_a=AgentTier.CREW, agent_b=AgentTier.UTILITY)

    assert registry.is_crew("agent_a") is True
    assert registry.is_crew("agent_b") is False


def test_crew_agents_list() -> None:
    registry = _registry_with(
        zeta=AgentTier.CREW,
        alpha=AgentTier.CREW,
        utility=AgentTier.UTILITY,
        core=AgentTier.CORE_INFRASTRUCTURE,
    )

    assert registry.crew_agents() == ["alpha", "zeta"]


def test_trust_crew_only_scores() -> None:
    registry = _registry_with(crew=AgentTier.CREW, utility=AgentTier.UTILITY)
    trust = TrustNetwork()
    trust.set_tier_registry(registry)
    trust.record_outcome("crew", success=True)
    trust.record_outcome("utility", success=True)

    assert set(trust.all_scores(crew_only=True)) == {"crew"}


def test_trust_skip_core_recording() -> None:
    registry = _registry_with(core=AgentTier.CORE_INFRASTRUCTURE)
    trust = TrustNetwork()
    trust.create_with_prior("core", alpha=3.0, beta=1.0)
    trust.set_tier_registry(registry)
    before = trust.get_record("core")
    assert before is not None

    score = trust.record_outcome("core", success=False, weight=10.0)
    after = trust.get_record("core")

    assert score == pytest.approx(0.75)
    assert after is before
    assert after.alpha == pytest.approx(3.0)
    assert after.beta == pytest.approx(1.0)
    assert trust.get_events_for_agent("core") == []


def test_cascade_excludes_utility() -> None:
    config = TrustDampeningConfig(
        cascade_agent_threshold=2,
        cascade_department_threshold=1,
        cascade_delta_threshold=0.05,
    )
    registry = _registry_with(
        crew_a=AgentTier.CREW,
        crew_b=AgentTier.CREW,
        utility=AgentTier.UTILITY,
    )
    events: list[tuple[str, object]] = []
    trust = TrustNetwork(dampening_config=config)
    trust.set_tier_registry(registry)
    trust.set_event_callback(lambda event_type, data: events.append((event_type, data)))
    trust.set_department_lookup(lambda agent_id: "ops")

    trust.record_outcome("crew_a", success=True, weight=2.0)
    trust.record_outcome("utility", success=True, weight=2.0)

    assert [event_type for event_type, _ in events].count("trust_cascade_warning") == 0

    trust.record_outcome("crew_b", success=True, weight=2.0)

    assert [event_type for event_type, _ in events].count("trust_cascade_warning") == 1


@pytest.mark.asyncio
async def test_emergence_crew_only() -> None:
    config = EmergenceMetricsConfig(
        min_thread_contributors=2,
        min_thread_posts=3,
        pid_permutation_shuffles=1,
    )
    registry = _registry_with(crew_a=AgentTier.CREW, crew_b=AgentTier.CREW, utility=AgentTier.UTILITY)
    engine = EmergenceMetricsEngine(config)
    engine.set_tier_registry(registry)
    ward_room = _FakeWardRoom([
        _thread("t1", [
            _post("crew_a", "alpha diagnostic observation"),
            _post("crew_b", "beta clinical response"),
            _post("utility", "infrastructure bookkeeping"),
        ]),
        _thread("t2", [
            _post("crew_a", "alpha follow up observation"),
            _post("crew_b", "beta follow up response"),
            _post("utility", "more bookkeeping"),
        ]),
    ])

    with patch("probos.cognitive.emergence_metrics.embed_text", return_value=[0.5] * 10):
        snapshot = await engine.compute_emergence_metrics(ward_room, TrustNetwork())

    assert snapshot.threads_analyzed == 2
    assert snapshot.pairs_analyzed == 1
    assert snapshot.top_synergy_pairs[0][0:2] == ("crew_a", "crew_b")


def test_hebbian_crew_only_report() -> None:
    registry = _registry_with(crew=AgentTier.CREW, utility=AgentTier.UTILITY, core=AgentTier.CORE_INFRASTRUCTURE)
    router = HebbianRouter()
    router.set_tier_registry(registry)
    router.record_interaction("crew", "utility", success=True)
    router.record_interaction("utility", "crew", success=True)
    router.record_interaction("utility", "core", success=True)

    assert set(router.all_weights(crew_only=True)) == {("crew", "utility"), ("utility", "crew")}


def test_startup_population() -> None:
    trust = _FakeTierAwareService()
    router = _FakeTierAwareService()
    emergence = _FakeTierAwareService()
    runtime = SimpleNamespace(
        registry=_FakeRegistry([
            SimpleNamespace(id="core-1", agent_type="event_log"),
            SimpleNamespace(id="crew-1", agent_type="architect"),
            SimpleNamespace(id="utility-1", agent_type="unknown_tool"),
        ]),
        trust_network=trust,
        hebbian_router=router,
        # BF-252: AD-680 promoted emergence_metrics_engine to a public property on
        # ProbOSRuntime; finalize._populate_agent_tiers now reads the public name.
        # SimpleNamespace doesn't expose @property descriptors, so the public attr
        # must be set directly. Keep the private alias for any consumers that still
        # read it.
        emergence_metrics_engine=emergence,
        _emergence_metrics_engine=emergence,
    )

    count = _populate_agent_tiers(runtime=runtime, config=SystemConfig())

    assert count == 3
    assert runtime._tier_registry.get_tier("core-1") == AgentTier.CORE_INFRASTRUCTURE
    assert runtime._tier_registry.get_tier("crew-1") == AgentTier.CREW
    assert runtime._tier_registry.get_tier("utility-1") == AgentTier.UTILITY
    assert trust.registry is runtime._tier_registry
    assert router.registry is runtime._tier_registry
    assert emergence.registry is runtime._tier_registry


def test_tier_enum_values() -> None:
    assert [tier.value for tier in AgentTier] == ["core_infrastructure", "utility", "crew"]


def test_config_crew_types() -> None:
    config = AgentTierConfig()

    assert len(config.crew_types) == 14
    assert "architect" in config.crew_types
    assert set(config.core_types) == {"event_log", "vitals_monitor", "introspect"}


def test_mixed_tier_trust_scores() -> None:
    registry = _registry_with(crew=AgentTier.CREW, utility=AgentTier.UTILITY)
    trust = TrustNetwork()
    trust.set_tier_registry(registry)
    trust.record_outcome("crew", success=True)
    trust.record_outcome("utility", success=False)

    assert set(trust.all_scores(crew_only=False)) == {"crew", "utility"}
    assert set(trust.all_scores(crew_only=True)) == {"crew"}


def test_all_agents_classified() -> None:
    runtime = SimpleNamespace(
        registry=_FakeRegistry([
            SimpleNamespace(id="a", agent_type="event_log"),
            SimpleNamespace(id="b", agent_type="architect"),
            SimpleNamespace(id="c", agent_type="unknown"),
        ]),
        trust_network=None,
        hebbian_router=None,
        # BF-252: see test_startup_population for rationale.
        emergence_metrics_engine=None,
        _emergence_metrics_engine=None,
    )

    assert _populate_agent_tiers(runtime=runtime, config=SystemConfig()) == 3
    assert set(runtime._tier_registry.all_registered()) == {"a", "b", "c"}


def test_core_agents_excluded_from_trust() -> None:
    registry = _registry_with(core=AgentTier.CORE_INFRASTRUCTURE)
    trust = TrustNetwork()
    trust.set_tier_registry(registry)

    score = trust.record_outcome("core", success=True)

    assert score == pytest.approx(0.5)
    assert trust.get_record("core") is None
    assert trust.get_events_for_agent("core") == []
