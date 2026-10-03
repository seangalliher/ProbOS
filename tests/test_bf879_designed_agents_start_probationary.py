"""BF-879: a self-designed agent starts at the probationary trust prior, and so
does every member its pool spawns later.

Two stacked defects kept every designed agent at the crew prior (#1440):

1. ``SelfModManager.set_probationary_trust`` read ``.id`` off the ids that
   ``ResourcePool.healthy_agents`` returns, and raised. The pipeline swallowed
   the error as a "trust boundary risk".
2. Even with that repaired, it ran too late. AD-640's ``initialize_trust`` had
   already created each record at the crew prior while wiring the agent, and
   ``create_with_prior`` never overwrites a record.

The designed pool now passes the probationary prior to
``ProbOSRuntime.create_pool``. That writes the prior for each member before
AD-640 runs, both for the members the pool is born with and for any it spawns
later on a refill or a surge.

The seam tests design a real agent through the runtime's own self-mod pipeline,
driven by the mock LLM, with no stubbed setter. The stubbed setter in
``test_ad600_transactive_memory.py`` is what hid both defects.

The vitals monitor reads that prior. An agent still at the prior it was born
with has no evidence against it, so it is not a trust outlier. Review of the
first candidate measured a ``medical_alert`` on every heartbeat once four
designed agents existed.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.agents.medical.vitals_monitor import VitalsMonitorAgent
from probos.bridge_alerts import BridgeAlertService
from probos.cognitive.llm_client import MockLLMClient
from probos.config import SystemConfig
from probos.consensus.trust import TrustNetwork
from probos.dream_adapter import DreamAdapter
from probos.runtime import ProbOSRuntime
from probos.self_mod_manager import SelfModManager
from probos.substrate.identity import generate_pool_ids
from probos.types import AgentState

_INTENT = "count_words"
_POOL = f"designed_{_INTENT}"


def _config() -> SystemConfig:
    config = SystemConfig()
    config.self_mod.enabled = True
    config.qa.enabled = False
    return config


async def _boot(data_dir: Path, config: SystemConfig | None = None) -> ProbOSRuntime:
    runtime = ProbOSRuntime(config=config or _config(), data_dir=data_dir, llm_client=MockLLMClient())
    await runtime.start()
    return runtime


@pytest.fixture
async def runtime(tmp_path: Path) -> AsyncIterator[ProbOSRuntime]:
    booted = await _boot(tmp_path / "data")
    try:
        yield booted
    finally:
        await booted.stop()


def _probationary(runtime: ProbOSRuntime) -> tuple[float, float]:
    return (runtime.config.self_mod.probationary_alpha, runtime.config.self_mod.probationary_beta)


def _crew(runtime: ProbOSRuntime) -> tuple[float, float]:
    return (runtime.config.consensus.trust_prior_alpha, runtime.config.consensus.trust_prior_beta)


def _raw(trust: TrustNetwork, agent_id: str) -> tuple[float, float] | None:
    record = trust.get_record(agent_id)
    return None if record is None else (record.alpha, record.beta)


async def _design(runtime: ProbOSRuntime) -> list[str]:
    assert _probationary(runtime) != _crew(runtime), "premise: the two priors differ"
    # BF-877: a booted runtime without a console wires no approval callback, and the
    # gate now refuses an unapproved design; every production path that designs passes
    # the Captain's approval this way.
    record = await runtime.self_mod_pipeline.handle_unhandled_intent(
        _INTENT, "Count the number of words in a text", {"text": "input text"},
        pre_approved=True,
    )
    assert getattr(record, "status", None) == "active", f"premise: a working agent was designed ({record})"
    pool = runtime.pools.get(_POOL)
    assert pool is not None and pool.healthy_agents, "premise: the design created its pool"
    return list(pool.healthy_agents)


async def test_a_designed_agent_starts_at_the_probationary_prior(runtime, caplog):
    caplog.set_level(logging.WARNING, logger="probos.cognitive.self_mod")

    (agent_id,) = await _design(runtime)

    alpha, beta = _probationary(runtime)
    assert _raw(runtime.trust_network, agent_id) == (alpha, beta)
    assert runtime.trust_network.get_score(agent_id) == pytest.approx(alpha / (alpha + beta))
    assert not [r for r in caplog.records if "trust boundary risk" in r.getMessage()]


async def test_members_the_designed_pool_spawns_later_start_probationary(runtime):
    (first,) = await _design(runtime)
    pool = runtime.pools[_POOL]

    surged = await pool.add_agent()  # the call PoolScaler.request_surge makes
    assert surged is not None and surged != first, "premise: the pool grew"
    pool.target_size = pool.current_size  # as the scaler does after growing a pool
    runtime.registry.get(first).state = AgentState.RECYCLING
    await pool.check_health()  # removes the member and refills the pool
    refilled = [aid for aid in pool.healthy_agents if aid not in (first, surged)]
    assert len(refilled) == 1, f"premise: the health pass refilled the pool ({pool.healthy_agents})"

    assert _raw(runtime.trust_network, surged) == _probationary(runtime)
    assert _raw(runtime.trust_network, refilled[0]) == _probationary(runtime)


async def test_a_pool_created_without_a_prior_keeps_the_crew_prior(runtime):
    pool = await runtime.create_pool("bf879_plain", "file_reader", target_size=1)
    (born,) = pool.healthy_agents
    grown = await pool.add_agent()
    assert grown is not None, "premise: the pool grew"

    assert _raw(runtime.trust_network, born) == _crew(runtime)
    assert _raw(runtime.trust_network, grown) == _crew(runtime)


async def test_a_designed_agent_that_already_has_a_record_keeps_it(runtime, caplog):
    (agent_id,) = generate_pool_ids(_INTENT, _POOL, 1)
    runtime.trust_network.create_with_prior(agent_id, 5.0, 2.0)
    caplog.set_level(logging.INFO, logger="probos.runtime")

    assert await _design(runtime) == [agent_id], "premise: the design reuses the deterministic id"

    assert _raw(runtime.trust_network, agent_id) == (5.0, 2.0)
    assert not [r for r in caplog.records if "BF-879" in r.getMessage() and agent_id in r.getMessage()]


async def test_the_probationary_prior_survives_a_restart(tmp_path):
    runtime = await _boot(tmp_path / "data")
    try:
        (agent_id,) = await _design(runtime)
        db_path = runtime.trust_network.db_path
        expected = _probationary(runtime)
    finally:
        await runtime.stop()
    assert db_path, "premise: trust is persisted to a database"

    reopened = TrustNetwork(db_path=db_path)
    await reopened.start()
    try:
        assert _raw(reopened, agent_id) == expected
    finally:
        await reopened.stop()


async def test_set_probationary_trust_seeds_member_ids_and_keeps_existing_records():
    trust = TrustNetwork()
    trust.create_with_prior("earned", 5.0, 2.0)
    manager = SelfModManager.__new__(SelfModManager)
    manager._config = SystemConfig()
    manager._trust_network = trust
    manager._pools = {_POOL: SimpleNamespace(healthy_agents=["fresh", "earned"])}

    await manager.set_probationary_trust(_POOL)
    await manager.set_probationary_trust("no_such_pool")

    config = manager._config.self_mod
    assert _raw(trust, "fresh") == (config.probationary_alpha, config.probationary_beta)
    assert _raw(trust, "earned") == (5.0, 2.0)


# ---------------------------------------------------------------------------
# The vitals monitor: an unproven agent is not a degraded one
# ---------------------------------------------------------------------------

_DESIGNED = [f"designed-{i}" for i in range(4)]
_CREW = [f"crew-{i}" for i in range(6)]


class _RecordingBus:
    def __init__(self) -> None:
        self.intents: list[Any] = []

    async def broadcast(self, intent: Any, *args: Any, **kwargs: Any) -> list[Any]:
        self.intents.append(intent)
        return []


def _trust_alerts(intents: list[Any]) -> list[Any]:
    return [
        i for i in intents
        if i.intent == "medical_alert" and i.params.get("metric") == "trust_outlier"
    ]


def _vitals_rig(config: SystemConfig) -> tuple[TrustNetwork, VitalsMonitorAgent, _RecordingBus]:
    trust = TrustNetwork(dampening_config=config.trust_dampening)
    for agent_id in _CREW:
        trust.create_with_prior(agent_id, *_crew_prior(config))
    for agent_id in _DESIGNED:
        trust.create_with_prior(agent_id, *_designed_prior(config))
    bus = _RecordingBus()
    runtime = SimpleNamespace(
        pools={}, trust_network=trust, dream_scheduler=None, attention=None,
        registry=SimpleNamespace(all=lambda: []), intent_bus=bus,
    )
    vitals = VitalsMonitorAgent(
        pool="medical_vitals", runtime=runtime,
        trust_floor=config.medical.trust_floor,
        max_trust_outliers=config.medical.max_trust_outliers,
    )
    floor = config.medical.trust_floor
    assert all(trust.get_score(a) < floor for a in _DESIGNED), "premise: designed agents start below the floor"
    assert len(_DESIGNED) > config.medical.max_trust_outliers, "premise: enough of them to breach the limit"
    assert all(trust.get_score(a) >= floor for a in _CREW), "premise: the crew prior is above the floor"
    return trust, vitals, bus


def _crew_prior(config: SystemConfig) -> tuple[float, float]:
    return (config.consensus.trust_prior_alpha, config.consensus.trust_prior_beta)


def _designed_prior(config: SystemConfig) -> tuple[float, float]:
    return (config.self_mod.probationary_alpha, config.self_mod.probationary_beta)


def _absorbing(config: SystemConfig) -> SystemConfig:
    alpha, beta = _designed_prior(config)
    config.trust_dampening.hard_trust_floor = alpha / (alpha + beta)
    return config


def _absorbed(trust: TrustNetwork, agent_id: str, prior: tuple[float, float]) -> bool:
    events = trust.get_events_for_agent(agent_id)
    return _raw(trust, agent_id) == prior and bool(events) and events[-1].floor_hit


def _degrade(trust: TrustNetwork, agent_id: str, floor: float) -> None:
    for _ in range(100):
        if trust.get_score(agent_id) < floor:
            return
        trust.record_outcome(agent_id, success=False)
    pytest.fail(f"premise: failures took {agent_id} below the floor ({trust.get_record(agent_id)})")


async def test_unproven_designed_agents_raise_no_trust_alert():
    config = SystemConfig()
    _, vitals, bus = _vitals_rig(config)

    ticks = [await vitals.collect_metrics() for _ in range(2)]

    assert [tick["trust_outliers"] for tick in ticks] == [[], []]
    assert _trust_alerts(bus.intents) == []
    alpha, beta = _designed_prior(config)
    assert ticks[-1]["trust_min"] == pytest.approx(alpha / (alpha + beta))  # still visible


async def test_designed_agents_that_fail_are_reported():
    config = SystemConfig()
    trust, vitals, bus = _vitals_rig(config)
    for agent_id in _DESIGNED:
        trust.record_outcome(agent_id, success=False)

    metrics = await vitals.collect_metrics()

    assert sorted(metrics["trust_outliers"]) == _DESIGNED
    (alert,) = _trust_alerts(bus.intents)
    assert sorted(alert.params["affected"]) == _DESIGNED


async def test_crew_degraded_by_evidence_still_alert_on_every_tick():
    config = SystemConfig()
    trust, vitals, bus = _vitals_rig(config)
    degraded = _CREW[:4]
    for agent_id in degraded:
        _degrade(trust, agent_id, config.medical.trust_floor)

    for _ in range(2):
        await vitals.collect_metrics()

    assert [sorted(a.params["affected"]) for a in _trust_alerts(bus.intents)] == [degraded, degraded]


async def test_unproven_agents_do_not_tip_a_degraded_count_over_the_limit():
    config = SystemConfig()
    trust, vitals, bus = _vitals_rig(config)
    degraded = _CREW[: config.medical.max_trust_outliers]
    for agent_id in degraded:
        _degrade(trust, agent_id, config.medical.trust_floor)

    metrics = await vitals.collect_metrics()

    assert sorted(metrics["trust_outliers"]) == degraded
    assert _trust_alerts(bus.intents) == []


async def test_scan_now_reports_the_same_outliers_as_the_heartbeat():
    config = SystemConfig()
    trust, vitals, _ = _vitals_rig(config)

    before = ((await vitals.scan_now())["trust_outliers"], (await vitals.collect_metrics())["trust_outliers"])
    trust.record_outcome(_DESIGNED[0], success=False)
    after = ((await vitals.scan_now())["trust_outliers"], (await vitals.collect_metrics())["trust_outliers"])

    assert before == ([], [])
    assert after == ([_DESIGNED[0]], [_DESIGNED[0]])


async def test_the_bridge_advisory_ignores_unproven_agents():
    config = SystemConfig()
    trust, vitals, _ = _vitals_rig(config)
    delivered: list[Any] = []

    async def deliver(alert: Any) -> None:
        delivered.append(alert.alert_type)

    adapter = DreamAdapter(
        dream_scheduler=None, emergent_detector=SimpleNamespace(analyze=lambda **_: []),
        episodic_memory=None, knowledge_store=None, hebbian_router=None,
        trust_network=trust, event_emitter=lambda *_: None, self_mod_pipeline=None,
        bridge_alerts=BridgeAlertService(), ward_room=None,
        registry=SimpleNamespace(get_by_pool=lambda name: [vitals] if name == "medical_vitals" else []),
        event_log=None, config=config, pools={}, deliver_bridge_alert_fn=deliver,
    )

    async def dream() -> list[str]:
        await vitals.collect_metrics()
        adapter.on_post_dream(None)
        await asyncio.sleep(0)  # let the adapter's delivery tasks run
        return [t for t in delivered if t == "trust_outliers"]

    assert await dream() == []
    for agent_id in _DESIGNED:
        trust.record_outcome(agent_id, success=False)
    assert await dream() == ["trust_outliers"], "premise: the harness reaches the bridge advisory"


async def test_designed_agents_whose_failures_the_hard_floor_absorbs_are_reported():
    config = _absorbing(SystemConfig())
    trust, vitals, bus = _vitals_rig(config)
    for agent_id in _DESIGNED:
        trust.record_outcome(agent_id, success=False)
    assert all(_absorbed(trust, a, _designed_prior(config)) for a in _DESIGNED), "premise: the floor absorbed each failure"

    metrics = await vitals.collect_metrics()

    assert sorted(metrics["trust_outliers"]) == _DESIGNED
    (alert,) = _trust_alerts(bus.intents)
    assert sorted(alert.params["affected"]) == _DESIGNED


async def test_at_the_hard_floor_the_report_does_not_rest_on_the_trust_event_log():
    config = _absorbing(SystemConfig())
    trust, vitals, _ = _vitals_rig(config)
    for agent_id in _DESIGNED:
        trust.record_outcome(agent_id, success=False)
    for _ in range(10_000):
        if not any(trust.get_events_for_agent(a) for a in _DESIGNED):
            break
        trust.record_outcome(_CREW[-1], success=True)
    else:
        pytest.fail("premise: later events evicted the absorbed failures from the log")

    assert sorted((await vitals.collect_metrics())["trust_outliers"]) == _DESIGNED


async def test_a_ship_whose_hard_floor_absorbs_designed_failures_reports_them(tmp_path, monkeypatch):
    runtime = await _boot(tmp_path / "data", _absorbing(_config()))
    try:
        alpha, beta = _probationary(runtime)
        assert runtime.trust_network.absorbs_failure_at(alpha / (alpha + beta)), "premise: the configured floor reaches the ship's network"
        await _design(runtime)
        pool = runtime.pools[_POOL]
        for _ in range(3):
            assert await pool.add_agent() is not None, "premise: the designed pool grew"
        pool.target_size = pool.current_size  # as the scaler does after growing a pool
        designed = sorted(pool.healthy_agents)
        for agent_id in designed:
            runtime.trust_network.record_outcome(agent_id, success=False)
        assert all(_absorbed(runtime.trust_network, a, (alpha, beta)) for a in designed), "premise: the floor absorbed each failure"
        (vitals,) = runtime.registry.get_by_pool("medical_vitals")
        alerts: list[Any] = []
        original = runtime.intent_bus.broadcast

        async def spy(intent: Any, *args: Any, **kwargs: Any) -> Any:
            if intent.intent == "medical_alert":
                alerts.append(intent)
                return []
            return await original(intent, *args, **kwargs)

        monkeypatch.setattr(runtime.intent_bus, "broadcast", spy)

        metrics = await vitals.collect_metrics()

        assert set(designed) <= set(metrics["trust_outliers"])
        assert any(set(designed) <= set(a.params["affected"]) for a in _trust_alerts(alerts))
    finally:
        await runtime.stop()


async def test_a_ship_with_four_new_designed_agents_raises_no_trust_alert(runtime, monkeypatch):
    await _design(runtime)
    pool = runtime.pools[_POOL]
    for _ in range(3):
        assert await pool.add_agent() is not None, "premise: the designed pool grew"
    pool.target_size = pool.current_size  # as the scaler does after growing a pool
    designed = list(pool.healthy_agents)
    floor = runtime.config.medical.trust_floor
    assert len(designed) > runtime.config.medical.max_trust_outliers, "premise: enough to breach the limit"
    assert all(runtime.trust_network.get_score(a) < floor for a in designed), "premise: each starts below the floor"
    (vitals,) = runtime.registry.get_by_pool("medical_vitals")
    alerts: list[Any] = []
    original = runtime.intent_bus.broadcast

    async def spy(intent: Any, *args: Any, **kwargs: Any) -> Any:
        if intent.intent == "medical_alert":
            alerts.append(intent)
            return []
        return await original(intent, *args, **kwargs)

    monkeypatch.setattr(runtime.intent_bus, "broadcast", spy)

    ticks = [await vitals.collect_metrics() for _ in range(2)]

    assert not set(designed) & {a for tick in ticks for a in tick["trust_outliers"]}
    assert _trust_alerts(alerts) == []
