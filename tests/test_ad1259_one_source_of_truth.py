"""AD-1259: Captain and first-person telemetry must share agent facts."""

from __future__ import annotations

import asyncio
import logging
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from probos.agents import introspect as introspect_module
from probos.cognitive import introspective_telemetry as telemetry_module
from probos.substrate.agent import BaseAgent
from probos.substrate.pool_group import PoolGroup, PoolGroupRegistry
from probos.tools import self_query_tool as self_query_module
from probos.types import AgentState, IntentMessage


_PRIVATE_FAILURE = "private-captain-telemetry-payload"


class _LifecycleSignal(BaseException):
    pass


@dataclass
class _FakeAgent:
    id: str
    agent_type: str = "test_agent"
    info_calls: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    state: AgentState = AgentState.ACTIVE
    confidence: float = 0.8

    def info(self) -> dict[str, Any]:
        self.info_calls += 1
        return {"id": self.id, "type": self.agent_type, **self.metadata}


@dataclass
class _FakeRegistry:
    agent: _FakeAgent | BaseAgent | None
    subjects: list[str] = field(default_factory=list)

    def get(self, agent_id: str) -> _FakeAgent | BaseAgent | None:
        self.subjects.append(agent_id)
        return self.agent if self.agent is not None and agent_id == self.agent.id else None

    def all(self) -> list[_FakeAgent | BaseAgent]:
        return [] if self.agent is None else [self.agent]

    @property
    def count(self) -> int:
        return len(self.all())


@dataclass(frozen=True)
class _FakeTrustRecord:
    observations: int = 7
    uncertainty: float = 0.123456


@dataclass
class _FakeTrustNetwork:
    scores: dict[str, float]
    score_subjects: list[str] = field(default_factory=list)

    def get_score(self, agent_id: str) -> float:
        self.score_subjects.append(agent_id)
        return self.scores[agent_id]

    def all_scores(self) -> dict[str, float]:
        return dict(self.scores)

    def get_record(self, agent_id: str) -> _FakeTrustRecord | None:
        return _FakeTrustRecord() if agent_id in self.scores else None

    def get_events_for_agent(self, agent_id: str, n: int = 5) -> list[object]:
        return []


@dataclass
class _FakeHebbianRouter:
    weights: dict[tuple[str, str, str], float]
    calls: int = 0

    def all_weights_typed(self) -> dict[tuple[str, str, str], float]:
        self.calls += 1
        return dict(self.weights)

    @property
    def weight_count(self) -> int:
        return len(self.weights)


@dataclass
class _FakeTelemetry:
    trust: dict[str, Any] = field(default_factory=lambda: {"score": 0.9375})
    social: dict[str, Any] = field(default_factory=lambda: {
        "routing_affinities": [{"intent": "narrow-routing", "weight": 0.99}],
        "incoming_affinities": [{"intent": "service-incoming", "weight": -0.1234}],
        "outbound_affinities": [{"intent": "service-outgoing", "weight": 0.2345}],
        "total_connections": 7,
        "interaction_breadth": 9,
    })
    failures: dict[str, BaseException] = field(default_factory=dict)
    calls: list[tuple[str, str]] = field(default_factory=list)

    async def get_trust_state(self, agent_id: str) -> dict[str, Any]:
        self.calls.append(("trust", agent_id))
        if "trust" in self.failures:
            raise self.failures["trust"]
        return deepcopy(self.trust)

    async def get_social_state(self, agent_id: str) -> dict[str, Any]:
        self.calls.append(("social", agent_id))
        if "social" in self.failures:
            raise self.failures["social"]
        return deepcopy(self.social)


@dataclass
class _FakePool:
    healthy_agents: list[str]
    target_size: int = 1

    def info(self) -> dict[str, Any]:
        return {
            "current_size": len(self.healthy_agents),
            "target_size": self.target_size,
            "agent_type": "test_agent",
        }


@dataclass
class _FakeCallsignRegistry:
    calls: list[str] = field(default_factory=list)

    def resolve(self, name: str) -> dict[str, str] | None:
        self.calls.append(name)
        return {"agent_type": "test_agent"} if name.lower() == "wesley" else None


@dataclass
class _FakeRuntime:
    registry: _FakeRegistry | None
    trust_network: _FakeTrustNetwork | None
    hebbian_router: _FakeHebbianRouter | None
    introspective_telemetry: telemetry_module.IntrospectiveTelemetryService | _FakeTelemetry | None = None
    pools: dict[str, _FakePool] = field(default_factory=dict)
    pool_groups: PoolGroupRegistry = field(default_factory=PoolGroupRegistry)
    callsign_registry: _FakeCallsignRegistry | None = None
    episodic_memory: None = None
    attention: None = None
    workflow_cache: None = None
    dream_scheduler: None = None
    _previous_execution: None = None
    _knowledge_store: None = None


@dataclass(frozen=True)
class _FakeSocialEvent:
    intent_type: str


@pytest.fixture
def social_runtime() -> _FakeRuntime:
    target = _FakeAgent(id="target-agent")
    runtime = _FakeRuntime(
        registry=_FakeRegistry(agent=target),
        trust_network=_FakeTrustNetwork(scores={target.id: 0.512375}),
        hebbian_router=_FakeHebbianRouter(weights={}),
        pools={"science_pool": _FakePool(healthy_agents=[target.id])},
    )
    runtime.pool_groups.register(PoolGroup(
        name="science", display_name="Science Team", pool_names={"science_pool"},
    ))
    return runtime


def _captain_plan(action: str) -> dict[str, Any]:
    return {
        "action": action,
        "params": {"agent_id": "target-agent"} if action == "agent_info" else {"team": "science"},
    }


@pytest.mark.asyncio
async def test_agent_info_and_telemetry_snapshot_share_facts() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    for module in (introspect_module, telemetry_module, self_query_module):
        assert module.__file__ is not None
        assert Path(module.__file__).resolve().is_relative_to(repository_root / "src")

    target = _FakeAgent(id="target-agent")
    registry = _FakeRegistry(agent=target)
    trust = _FakeTrustNetwork(scores={target.id: 0.512375})
    router = _FakeHebbianRouter(weights={
        ("source-intent", target.id, "routing"): 0.876543,
        (target.id, "peer-agent", "routing"): 0.654321,
    })
    runtime = _FakeRuntime(
        registry=registry, trust_network=trust, hebbian_router=router,
    )
    service = telemetry_module.IntrospectiveTelemetryService(runtime=runtime)
    runtime.introspective_telemetry = service
    captain_agent = introspect_module.IntrospectionAgent(runtime=runtime)
    self_query = self_query_module.SelfQueryTool(telemetry=service)

    assert runtime.introspective_telemetry is service
    assert not registry.subjects
    assert not trust.score_subjects
    assert router.calls == 0
    assert target.info_calls == 0

    result = await captain_agent.act({
        "action": "agent_info", "params": {"agent_id": target.id},
    })

    assert result["success"] is True
    assert result["data"]["agents"]
    assert len(result["data"]["agents"]) == 1
    captain = result["data"]["agents"][0]
    assert captain["id"] == target.id
    assert captain["type"] == target.agent_type
    assert target.info_calls > 0
    assert registry.subjects and set(registry.subjects) == {target.id}
    assert trust.score_subjects and set(trust.score_subjects) == {target.id}
    assert router.calls > 0
    captain_score_reads = len(trust.score_subjects)
    captain_router_reads = router.calls
    captain_registry_reads = len(registry.subjects)
    assert captain_score_reads == 1
    assert captain_router_reads == 1

    snapshot = await service.get_full_snapshot(target.id)

    assert snapshot and snapshot["trust"]
    assert trust.score_subjects[captain_score_reads:] == [target.id]
    assert set(trust.score_subjects) == {target.id}
    assert router.calls - captain_router_reads == 1
    assert registry.subjects[captain_registry_reads:]
    assert set(registry.subjects) == {target.id}
    assert isinstance(captain["trust_score"], float)
    assert isinstance(snapshot["trust"]["score"], float)

    assert captain["trust_score"] == snapshot["trust"]["score"]

    social = snapshot["social"]
    hebbian = captain["hebbian"]
    assert hebbian["incoming_top3"] == [
        {"source": affinity["intent"], "weight": affinity["weight"]}
        for affinity in social["incoming_affinities"]
    ]
    assert hebbian["outgoing_top3"] == [
        {"target": affinity["intent"], "weight": affinity["weight"]}
        for affinity in social["outbound_affinities"]
    ]
    assert hebbian["total_connections"] == social["total_connections"]
    assert snapshot["trust"]["score"] == 0.5124
    assert snapshot["trust"]["uncertainty"] == 0.1235
    assert hebbian["incoming_top3"] == [
        {"source": "source-intent", "weight": 0.8765},
    ]
    assert hebbian["outgoing_top3"] == [
        {"target": "peer-agent", "weight": 0.6543},
    ]
    assert hebbian["total_connections"] == 2
    assert set(result) == {"success", "data"}
    assert set(result["data"]) == {"agents"}
    assert set(captain) == {"id", "type", "trust_score", "hebbian"}
    assert set(hebbian) == {"incoming_top3", "outgoing_top3", "total_connections"}

    snapshot_score_reads = len(trust.score_subjects)
    snapshot_router_reads = router.calls
    snapshot_registry_reads = len(registry.subjects)

    tool_result = await self_query.invoke({}, context={"agent_id": target.id})

    assert tool_result.error is None
    assert isinstance(tool_result.output, dict)
    assert set(tool_result.output) == {"agent_id", "domains", "rendered", "unknown_domains"}
    assert tool_result.output["agent_id"] == target.id
    assert tool_result.output["unknown_domains"] == []
    assert trust.score_subjects[snapshot_score_reads:] == [target.id]
    assert set(trust.score_subjects) == {target.id}
    assert router.calls - snapshot_router_reads == 1
    assert registry.subjects[snapshot_registry_reads:]
    assert set(registry.subjects) == {target.id}
    assert tool_result.output["domains"]["trust"] == snapshot["trust"]
    assert tool_result.output["domains"]["social"] == {
        "routing_affinities": social["routing_affinities"],
        "interaction_breadth": social["interaction_breadth"],
    }
    assert tool_result.output["rendered"] == service.render_telemetry_context(
        tool_result.output["domains"],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {},
        {"domains": list(self_query_module.SELF_QUERY_DOMAINS)},
        {"domains": ["social"]},
    ],
    ids=["omitted-domains", "explicit-all", "selected-social"],
)
async def test_self_query_social_payload_excludes_captain_projection(
    params: dict[str, Any],
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    for module in (telemetry_module, self_query_module):
        assert module.__file__ is not None
        assert Path(module.__file__).resolve().is_relative_to(repository_root / "src")

    subject = _FakeAgent(id="subject-agent")
    registry = _FakeRegistry(agent=subject)
    trust = _FakeTrustNetwork(scores={subject.id: 0.512375})
    router = _FakeHebbianRouter(weights={
        ("peer-agent", subject.id, "agent"): 0.876543,
        ("peer-agent", subject.id, "social"): 0.5,
        (subject.id, "peer-agent", "social"): 0.42,
    })
    runtime = _FakeRuntime(
        registry=registry, trust_network=trust, hebbian_router=router,
    )
    service = telemetry_module.IntrospectiveTelemetryService(runtime=runtime)
    runtime.introspective_telemetry = service
    self_query = self_query_module.SelfQueryTool(telemetry=service)

    assert runtime.introspective_telemetry is service
    assert router.weight_count == 3
    assert router.calls == 0

    snapshot = await service.get_full_snapshot(subject.id)

    assert router.calls == 1
    assert registry.subjects and set(registry.subjects) == {"subject-agent"}
    assert trust.score_subjects == ["subject-agent"]
    social = snapshot["social"]
    assert social["incoming_affinities"] == [
        {"intent": "peer-agent", "weight": 0.8765},
        {"intent": "peer-agent", "weight": 0.5},
    ]
    assert social["outbound_affinities"] == [
        {"intent": "peer-agent", "weight": 0.42},
    ]
    assert social["total_connections"] == 3
    assert social["routing_affinities"] == [{"intent": "peer-agent", "weight": 0.5}]
    assert social["interaction_breadth"] == 0
    selected_domains = params.get("domains", self_query_module.SELF_QUERY_DOMAINS)
    selected_snapshot = {domain: snapshot[domain] for domain in selected_domains}
    expected_social = {
        "routing_affinities": [{"intent": "peer-agent", "weight": 0.5}],
        "interaction_breadth": social["interaction_breadth"],
    }
    graph_calls_before = router.calls

    tool_result = await self_query.invoke(params, context={"agent_id": subject.id})

    assert router.calls - graph_calls_before == 1
    assert tool_result.error is None
    assert isinstance(tool_result.output, dict)
    assert set(tool_result.output) == {"agent_id", "domains", "rendered", "unknown_domains"}
    assert tool_result.output["agent_id"] == "subject-agent"
    assert tool_result.output["unknown_domains"] == []
    assert set(tool_result.output["domains"]) == set(selected_snapshot)
    assert registry.subjects and set(registry.subjects) == {"subject-agent"}
    assert trust.score_subjects and set(trust.score_subjects) == {"subject-agent"}
    assert tool_result.output["rendered"] == service.render_telemetry_context(selected_snapshot)
    assert tool_result.output["domains"]["social"] == expected_social


@pytest.mark.asyncio
async def test_get_social_state_preserves_typed_edges_and_legacy_routing(
    social_runtime: _FakeRuntime,
) -> None:
    router = social_runtime.hebbian_router
    assert router is not None
    router.weights = {
        ("shared-source", "target-agent", "routing"): 0.876543,
        ("shared-source", "target-agent", "collaboration"): 0.654321,
        ("shared-source", "target-agent", "inhibition"): -0.125678,
        ("zero-source", "target-agent", "routing"): 0.0,
        ("target-agent", "out-peer", "routing"): 0.654321,
        ("target-agent", "out-peer", "collaboration"): 0.512375,
        ("target-agent", "out-peer", "inhibition"): -0.234567,
        ("target-agent", "target-agent", "self"): -0.345678,
        ("foreign-source", "foreign-target", "routing"): 1.0,
    }
    service = telemetry_module.IntrospectiveTelemetryService(runtime=social_runtime)

    social = await service.get_social_state("target-agent")

    assert router.calls == 1
    assert social == {
        "routing_affinities": [{"intent": "shared-source", "weight": 0.6543}],
        "incoming_affinities": [
            {"intent": "shared-source", "weight": 0.8765},
            {"intent": "shared-source", "weight": 0.6543},
            {"intent": "zero-source", "weight": 0.0},
        ],
        "outbound_affinities": [
            {"intent": "out-peer", "weight": 0.6543},
            {"intent": "out-peer", "weight": 0.5124},
            {"intent": "out-peer", "weight": -0.2346},
        ],
        "total_connections": 8,
        "interaction_breadth": 0,
    }


@pytest.mark.asyncio
async def test_get_social_state_sorts_raw_weights_with_stable_ties(
    social_runtime: _FakeRuntime,
) -> None:
    router = social_runtime.hebbian_router
    assert router is not None
    endpoint_weights = [
        ("lower-first", 0.654311),
        ("zeta-tie-first", 0.654349),
        ("alpha-tie-second", 0.654349),
        ("middle", 0.654321),
    ]
    router.weights = {
        edge: weight
        for endpoint, weight in endpoint_weights
        for edge in (
            (endpoint, "target-agent", "routing"),
            ("target-agent", endpoint, "routing"),
        )
    }
    service = telemetry_module.IntrospectiveTelemetryService(runtime=social_runtime)

    social = await service.get_social_state("target-agent")

    expected = [
        {"intent": "zeta-tie-first", "weight": 0.6543},
        {"intent": "alpha-tie-second", "weight": 0.6543},
        {"intent": "middle", "weight": 0.6543},
    ]
    assert router.calls == 1
    assert social == {
        "routing_affinities": expected,
        "incoming_affinities": expected,
        "outbound_affinities": expected,
        "total_connections": 8,
        "interaction_breadth": 0,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("weights", "expected"),
    [
        ({}, {"total_connections": 0, "interaction_breadth": 0}),
        (
            {("target-agent", "target-agent", "self"): 0.0},
            {
                "incoming_affinities": [{"intent": "target-agent", "weight": 0.0}],
                "outbound_affinities": [{"intent": "target-agent", "weight": 0.0}],
                "total_connections": 1,
                "interaction_breadth": 0,
            },
        ),
    ],
    ids=["empty-graph", "zero-self-loop"],
)
async def test_get_social_state_counts_empty_graph_and_self_loop(
    social_runtime: _FakeRuntime,
    weights: dict[tuple[str, str, str], float],
    expected: dict[str, Any],
) -> None:
    router = social_runtime.hebbian_router
    assert router is not None
    router.weights = weights
    service = telemetry_module.IntrospectiveTelemetryService(runtime=social_runtime)

    social = await service.get_social_state("target-agent")

    assert router.calls == 1
    assert social == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["unavailable", "collection", "projection"])
async def test_get_social_state_omits_incomplete_graph_and_logs_safe_fallback(
    social_runtime: _FakeRuntime,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    failure_stage: str,
) -> None:
    router = social_runtime.hebbian_router
    assert router is not None
    assert social_runtime.trust_network is not None
    router.weights = {
        ("source-intent", "target-agent", "routing"): 0.876543,
        ("target-agent", "peer-agent", "routing"): 0.654321,
    }
    private_payload = "private graph payload"
    formatted_weights: list[float] = []
    event_requests: list[tuple[str, int]] = []

    def get_events(agent_id: str, n: int = 5) -> list[_FakeSocialEvent]:
        event_requests.append((agent_id, n))
        return [
            _FakeSocialEvent("repeat"),
            _FakeSocialEvent("repeat"),
            _FakeSocialEvent("other"),
        ]

    monkeypatch.setattr(social_runtime.trust_network, "get_events_for_agent", get_events)
    if failure_stage == "unavailable":
        monkeypatch.setattr(social_runtime, "hebbian_router", None)
    elif failure_stage == "collection":
        def fail_collection() -> dict[tuple[str, str, str], float]:
            router.calls += 1
            raise RuntimeError(private_payload)

        monkeypatch.setattr(router, "all_weights_typed", fail_collection)
    else:
        original_format_trust = telemetry_module.format_trust

        def fail_outbound_format(value: float) -> float:
            formatted_weights.append(value)
            if value == 0.654321:
                raise RuntimeError(private_payload)
            return original_format_trust(value)

        monkeypatch.setattr(telemetry_module, "format_trust", fail_outbound_format)
    service = telemetry_module.IntrospectiveTelemetryService(runtime=social_runtime)

    with caplog.at_level(logging.WARNING, logger=telemetry_module.__name__):
        social = await service.get_social_state("target-agent")

    assert router.calls == (0 if failure_stage == "unavailable" else 1)
    if failure_stage == "projection":
        assert formatted_weights[-1] == 0.654321
        assert 0.876543 in formatted_weights[:-1]
    assert event_requests == [("target-agent", 20)]
    assert social == {"interaction_breadth": 2}
    records = [record for record in caplog.records if record.name == telemetry_module.__name__]
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert records[0].exc_info is None
    assert "without graph facts" in records[0].getMessage()
    assert private_payload not in caplog.text


@pytest.mark.asyncio
async def test_get_social_state_keeps_graph_when_event_query_fails(
    social_runtime: _FakeRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router = social_runtime.hebbian_router
    assert router is not None
    assert social_runtime.trust_network is not None
    router.weights = {("source-intent", "target-agent", "routing"): 0.876543}
    event_requests: list[tuple[str, int]] = []

    def fail_events(agent_id: str, n: int = 5) -> list[object]:
        event_requests.append((agent_id, n))
        raise RuntimeError("private event payload")

    monkeypatch.setattr(social_runtime.trust_network, "get_events_for_agent", fail_events)
    service = telemetry_module.IntrospectiveTelemetryService(runtime=social_runtime)

    social = await service.get_social_state("target-agent")

    assert router.calls == 1
    assert event_requests == [("target-agent", 20)]
    assert social == {
        "routing_affinities": [{"intent": "source-intent", "weight": 0.8765}],
        "incoming_affinities": [{"intent": "source-intent", "weight": 0.8765}],
        "total_connections": 1,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["agent_info", "team_info"])
async def test_captain_handlers_use_injected_service_facts(
    social_runtime: _FakeRuntime, action: str,
) -> None:
    registry = social_runtime.registry
    trust = social_runtime.trust_network
    router = social_runtime.hebbian_router
    assert registry is not None and trust is not None and router is not None
    target = registry.agent
    assert isinstance(target, _FakeAgent)
    target.metadata = {
        "callsign": "Wesley", "pool": "original-pool", "state": "active",
        "confidence": 0.8, "capabilities": ["observe"], "operations": 3,
        "success_rate": 0.6667, "trust_score": -1.0,
    }
    metadata = deepcopy(target.metadata)
    router.weights = {("raw-source", target.id, "routing"): 0.876543}
    service = _FakeTelemetry()
    social_runtime.introspective_telemetry = service
    captain = introspect_module.IntrospectionAgent(runtime=social_runtime)
    assert trust.scores[target.id] != service.trust["score"]
    assert len(router.weights) != service.social["total_connections"]

    result = await captain.act(_captain_plan(action))

    assert result["success"] is True
    assert set(result) == {"success", "data"}
    assert len(result["data"]["agents"]) == 1
    row = result["data"]["agents"][0]
    expected = {"id": target.id, "type": target.agent_type, **metadata, "trust_score": 0.9375}
    if action == "agent_info":
        expected["hebbian"] = {
            "incoming_top3": [{"source": "service-incoming", "weight": -0.1234}],
            "outgoing_top3": [{"target": "service-outgoing", "weight": 0.2345}],
            "total_connections": 7,
        }
        assert set(result["data"]) == {"agents"}
        assert service.calls == [("trust", target.id), ("social", target.id)]
    else:
        expected["pool"] = "science_pool"
        assert set(result["data"]) == {"team", "health", "pools", "agents"}
        assert result["data"]["team"] == {
            "name": "science", "display_name": "Science Team", "exclude_from_scaler": False,
        }
        assert result["data"]["health"] == {
            "total_agents": 1, "healthy_agents": 1, "health_ratio": 1.0,
        }
        assert result["data"]["pools"] == {"science_pool": {
            "current_size": 1, "target_size": 1, "agent_type": "test_agent",
        }}
        assert service.calls == [("trust", target.id)]
    assert row == expected
    assert target.metadata == metadata
    assert target.info_calls == 1
    assert trust.score_subjects == []
    assert router.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["agent_info", "team_info"])
async def test_captain_handlers_preserve_service_zero_values(
    social_runtime: _FakeRuntime, action: str,
) -> None:
    trust = social_runtime.trust_network
    router = social_runtime.hebbian_router
    assert trust is not None and router is not None
    router.weights = {("raw-source", "target-agent", "routing"): 0.876543}
    service = _FakeTelemetry(trust={"score": 0.0}, social={"total_connections": 0})
    social_runtime.introspective_telemetry = service

    result = await introspect_module.IntrospectionAgent(runtime=social_runtime).act(
        _captain_plan(action),
    )

    assert result["success"] is True
    row = result["data"]["agents"][0]
    assert row["trust_score"] == 0.0
    if action == "agent_info":
        assert row["hebbian"] == {
            "incoming_top3": [], "outgoing_top3": [], "total_connections": 0,
        }
        assert service.calls == [("trust", "target-agent"), ("social", "target-agent")]
    else:
        assert set(row) == {"id", "type", "trust_score", "pool"}
        assert service.calls == [("trust", "target-agent")]
    assert trust.score_subjects == []
    assert router.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["agent_info", "team_info"])
@pytest.mark.parametrize("availability", ["none", "absent", "accessor-error"])
async def test_captain_handlers_fall_back_when_service_unavailable(
    social_runtime: _FakeRuntime, action: str, availability: str,
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    trust = social_runtime.trust_network
    router = social_runtime.hebbian_router
    assert trust is not None and router is not None
    router.weights = {("raw-source", "target-agent", "routing"): 0.876543}
    accesses: list[str] = []
    if availability != "none":
        def unavailable(runtime: _FakeRuntime) -> None:
            assert runtime is social_runtime
            accesses.append(availability)
            if availability == "absent":
                raise AttributeError("introspective_telemetry")
            raise RuntimeError(_PRIVATE_FAILURE)

        monkeypatch.setattr(_FakeRuntime, "introspective_telemetry", property(unavailable))

    with caplog.at_level(logging.WARNING, logger=introspect_module.__name__):
        result = await introspect_module.IntrospectionAgent(runtime=social_runtime).act(
            _captain_plan(action),
        )

    assert result["success"] is True
    row = result["data"]["agents"][0]
    assert row["trust_score"] == 0.5124
    assert trust.score_subjects == ["target-agent"]
    assert accesses == ([] if availability == "none" else [availability])
    if action == "agent_info":
        assert row["hebbian"] == {
            "incoming_top3": [{"source": "raw-source", "weight": 0.8765}],
            "outgoing_top3": [], "total_connections": 1,
        }
        assert router.calls == 1
    else:
        assert set(row) == {"id", "type", "trust_score", "pool"}
        assert router.calls == 0
    if availability == "accessor-error":
        assert "falling back to raw agent facts" in caplog.text
    assert _PRIVATE_FAILURE not in repr(result) + caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "domain"),
    [("agent_info", "trust"), ("agent_info", "social"), ("team_info", "trust")],
)
@pytest.mark.parametrize("failure", ["exception", "missing", "none"])
async def test_captain_domain_fallback_preserves_healthy_service_domain(
    social_runtime: _FakeRuntime, action: str, domain: str, failure: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    trust = social_runtime.trust_network
    router = social_runtime.hebbian_router
    assert trust is not None and router is not None
    router.weights = {("raw-source", "target-agent", "routing"): 0.876543}
    service = _FakeTelemetry()
    if failure == "exception":
        service.failures[domain] = RuntimeError(_PRIVATE_FAILURE)
    elif domain == "trust":
        service.trust = {} if failure == "missing" else {"score": None}
    else:
        service.social = {
            "interaction_breadth": 9,
            "routing_affinities": [{"intent": "narrow-routing", "weight": 0.99}],
        }
        if failure == "none":
            service.social["total_connections"] = None
    social_runtime.introspective_telemetry = service

    with caplog.at_level(logging.WARNING, logger=introspect_module.__name__):
        result = await introspect_module.IntrospectionAgent(runtime=social_runtime).act(
            _captain_plan(action),
        )

    assert result["success"] is True
    row = result["data"]["agents"][0]
    assert row["trust_score"] == (0.5124 if domain == "trust" else 0.9375)
    assert trust.score_subjects == (["target-agent"] if domain == "trust" else [])
    assert router.calls == (1 if domain == "social" else 0)
    if action == "team_info":
        assert set(row) == {"id", "type", "trust_score", "pool"}
        assert service.calls == [("trust", "target-agent")]
    else:
        assert service.calls == [("trust", "target-agent"), ("social", "target-agent")]
        assert row["hebbian"] == ({
            "incoming_top3": [{"source": "raw-source", "weight": 0.8765}],
            "outgoing_top3": [], "total_connections": 1,
        } if domain == "social" else {
            "incoming_top3": [{"source": "service-incoming", "weight": -0.1234}],
            "outgoing_top3": [{"target": "service-outgoing", "weight": 0.2345}],
            "total_connections": 7,
        })
    assert "falling back to raw" in caplog.text
    assert _PRIVATE_FAILURE not in repr(result) + caplog.text
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.asyncio
async def test_agent_info_real_failed_graph_falls_back_once(
    social_runtime: _FakeRuntime, monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    trust = social_runtime.trust_network
    router = social_runtime.hebbian_router
    assert trust is not None and router is not None
    router.weights = {("raw-source", "target-agent", "routing"): 0.876543}

    def collect_after_failure() -> dict[tuple[str, str, str], float]:
        router.calls += 1
        if router.calls == 1:
            raise RuntimeError(_PRIVATE_FAILURE)
        assert router.calls == 2
        return dict(router.weights)

    monkeypatch.setattr(router, "all_weights_typed", collect_after_failure)
    social_runtime.introspective_telemetry = telemetry_module.IntrospectiveTelemetryService(
        runtime=social_runtime,
    )

    with caplog.at_level(logging.WARNING):
        result = await introspect_module.IntrospectionAgent(runtime=social_runtime).act(
            _captain_plan("agent_info"),
        )

    assert result["success"] is True
    assert result["data"]["agents"][0]["trust_score"] == 0.5124
    assert result["data"]["agents"][0]["hebbian"] == {
        "incoming_top3": [{"source": "raw-source", "weight": 0.8765}],
        "outgoing_top3": [], "total_connections": 1,
    }
    assert trust.score_subjects == ["target-agent"]
    assert router.calls == 2
    assert "without graph facts" in caplog.text
    assert "falling back to raw Hebbian graph facts" in caplog.text
    assert _PRIVATE_FAILURE not in repr(result) + caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("service_available", [False, True])
async def test_agent_info_preserves_typed_raw_ranking_and_incident_count(
    social_runtime: _FakeRuntime, service_available: bool,
) -> None:
    router = social_runtime.hebbian_router
    assert router is not None
    router.weights = {
        ("shared-source", "target-agent", "routing"): 0.654311,
        ("shared-source", "target-agent", "collaboration"): 0.654349,
        ("other-source", "target-agent", "routing"): 0.654349,
        ("zero-source", "target-agent", "routing"): 0.0,
        ("target-agent", "out-zero", "routing"): 0.0,
        ("target-agent", "out-negative", "routing"): -0.125678,
        ("target-agent", "target-agent", "self"): -0.345678,
        ("foreign-source", "foreign-target", "routing"): 1.0,
    }
    original = dict(router.weights)
    if service_available:
        social_runtime.introspective_telemetry = telemetry_module.IntrospectiveTelemetryService(
            runtime=social_runtime,
        )

    result = await introspect_module.IntrospectionAgent(runtime=social_runtime).act(
        _captain_plan("agent_info"),
    )

    assert result["success"] is True
    assert router.calls == 1
    assert router.weights == original
    assert result["data"]["agents"][0]["hebbian"] == {
        "incoming_top3": [
            {"source": "shared-source", "weight": 0.6543},
            {"source": "other-source", "weight": 0.6543},
            {"source": "shared-source", "weight": 0.6543},
        ],
        "outgoing_top3": [
            {"target": "out-zero", "weight": 0.0},
            {"target": "out-negative", "weight": -0.1257},
            {"target": "target-agent", "weight": -0.3457},
        ],
        "total_connections": 7,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["agent_info", "team_info"])
@pytest.mark.parametrize("metadata", ["no-record", "record-error", "events-error"])
async def test_captain_handlers_keep_score_after_trust_metadata_failure(
    social_runtime: _FakeRuntime, action: str, metadata: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trust = social_runtime.trust_network
    router = social_runtime.hebbian_router
    assert trust is not None and router is not None
    metadata_reads: list[str] = []
    if metadata == "events-error":
        def fail_events(agent_id: str, n: int = 5) -> list[object]:
            metadata_reads.append(agent_id)
            raise RuntimeError(_PRIVATE_FAILURE)

        monkeypatch.setattr(trust, "get_events_for_agent", fail_events)
    else:
        def get_record(agent_id: str) -> None:
            metadata_reads.append(agent_id)
            if metadata == "record-error":
                raise RuntimeError(_PRIVATE_FAILURE)
            return None

        monkeypatch.setattr(trust, "get_record", get_record)
    social_runtime.introspective_telemetry = telemetry_module.IntrospectiveTelemetryService(
        runtime=social_runtime,
    )

    result = await introspect_module.IntrospectionAgent(runtime=social_runtime).act(
        _captain_plan(action),
    )

    assert result["success"] is True
    assert result["data"]["agents"][0]["trust_score"] == 0.5124
    assert trust.score_subjects == ["target-agent"]
    assert metadata_reads == ["target-agent"] * (
        2 if metadata == "events-error" and action == "agent_info" else 1
    )
    assert router.calls == (1 if action == "agent_info" else 0)
    assert _PRIVATE_FAILURE not in repr(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "component"),
    [
        ("agent_info", "registry"), ("agent_info", "trust_network"),
        ("agent_info", "hebbian_router"), ("team_info", "registry"),
        ("team_info", "trust_network"),
    ],
)
@pytest.mark.parametrize("absence", ["none", "missing"])
async def test_captain_handlers_missing_components_return_honest_error(
    social_runtime: _FakeRuntime, action: str, component: str, absence: str,
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    assert getattr(social_runtime, component) is not None
    if absence == "none":
        monkeypatch.setattr(social_runtime, component, None)
    else:
        monkeypatch.delattr(social_runtime, component)

    with caplog.at_level(logging.WARNING, logger=introspect_module.__name__):
        result = await introspect_module.IntrospectionAgent(runtime=social_runtime).act(
            _captain_plan(action),
        )

    assert result == {
        "success": False,
        "error": "Agent information unavailable" if action == "agent_info" else "Team information unavailable",
    }
    assert "returning an error" in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["agent_info", "team_info"])
async def test_captain_handlers_use_service_with_absent_raw_domains(
    social_runtime: _FakeRuntime, action: str,
) -> None:
    service = _FakeTelemetry()
    social_runtime.introspective_telemetry = service
    social_runtime.trust_network = None
    social_runtime.hebbian_router = None

    result = await introspect_module.IntrospectionAgent(runtime=social_runtime).act(
        _captain_plan(action),
    )

    assert result["success"] is True
    row = result["data"]["agents"][0]
    assert row["trust_score"] == 0.9375
    if action == "agent_info":
        assert row["hebbian"]["total_connections"] == 7
        assert service.calls == [("trust", "target-agent"), ("social", "target-agent")]
    else:
        assert set(row) == {"id", "type", "trust_score", "pool"}
        assert service.calls == [("trust", "target-agent")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "failure_site"),
    [
        ("agent_info", "registry"), ("agent_info", "trust"),
        ("agent_info", "graph"), ("team_info", "registry"), ("team_info", "trust"),
    ],
)
async def test_captain_raw_failures_return_sanitized_error(
    social_runtime: _FakeRuntime, action: str, failure_site: str,
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    registry = social_runtime.registry
    trust = social_runtime.trust_network
    router = social_runtime.hebbian_router
    assert registry is not None and trust is not None and router is not None
    failures: list[str] = []

    def fail_lookup(agent_id: str) -> None:
        failures.append(agent_id)
        raise RuntimeError(_PRIVATE_FAILURE)

    def fail_trust(agent_id: str) -> float:
        failures.append(agent_id)
        raise RuntimeError(_PRIVATE_FAILURE)

    def fail_graph() -> dict[tuple[str, str, str], float]:
        failures.append("graph")
        raise RuntimeError(_PRIVATE_FAILURE)

    if failure_site == "registry":
        monkeypatch.setattr(registry, "get", fail_lookup)
    elif failure_site == "trust":
        monkeypatch.setattr(trust, "get_score", fail_trust)
    else:
        monkeypatch.setattr(router, "all_weights_typed", fail_graph)

    with caplog.at_level(logging.WARNING, logger=introspect_module.__name__):
        result = await introspect_module.IntrospectionAgent(runtime=social_runtime).act(
            _captain_plan(action),
        )

    assert result["success"] is False
    assert set(result) == {"success", "error"}
    assert failures == (["graph"] if failure_site == "graph" else ["target-agent"])
    assert "returning an error" in caplog.text
    assert _PRIVATE_FAILURE not in repr(result) + caplog.text
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["agent_info", "team_info"])
async def test_captain_handlers_preserve_base_info_and_live_trust_read(
    social_runtime: _FakeRuntime, action: str,
) -> None:
    registry = social_runtime.registry
    trust = social_runtime.trust_network
    assert registry is not None and trust is not None
    target = introspect_module.IntrospectionAgent(
        agent_id="target-agent", pool="science_pool", runtime=social_runtime,
    )
    registry.agent = target
    service = _FakeTelemetry()
    social_runtime.introspective_telemetry = service
    expected = target.info()
    assert expected["trust_score"] == 0.5124
    assert trust.score_subjects == [target.id]
    trust.score_subjects.clear()

    result = await introspect_module.IntrospectionAgent(runtime=social_runtime).act(
        _captain_plan(action),
    )

    assert result["success"] is True
    expected["trust_score"] = 0.9375
    if action == "agent_info":
        expected["hebbian"] = {
            "incoming_top3": [{"source": "service-incoming", "weight": -0.1234}],
            "outgoing_top3": [{"target": "service-outgoing", "weight": 0.2345}],
            "total_connections": 7,
        }
    assert result["data"]["agents"] == [expected]
    assert trust.score_subjects == [target.id]


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["agent_info", "team_info"])
@pytest.mark.parametrize("implementation", ["stub", "base-agent"])
async def test_captain_handlers_contain_info_failure(
    social_runtime: _FakeRuntime, action: str, implementation: str,
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    registry = social_runtime.registry
    trust = social_runtime.trust_network
    assert registry is not None and trust is not None
    failures: list[str] = []
    if implementation == "base-agent":
        registry.agent = introspect_module.IntrospectionAgent(
            agent_id="target-agent", runtime=social_runtime,
        )

        def fail_live_trust(agent_id: str) -> float:
            failures.append(agent_id)
            raise RuntimeError(_PRIVATE_FAILURE)

        monkeypatch.setattr(trust, "get_score", fail_live_trust)
    else:
        assert isinstance(registry.agent, _FakeAgent)

        def fail_info() -> dict[str, Any]:
            failures.append("target-agent")
            raise RuntimeError(_PRIVATE_FAILURE)

        monkeypatch.setattr(registry.agent, "info", fail_info)
    service = _FakeTelemetry()
    social_runtime.introspective_telemetry = service

    with caplog.at_level(logging.WARNING, logger=introspect_module.__name__):
        result = await introspect_module.IntrospectionAgent(runtime=social_runtime).act(
            _captain_plan(action),
        )

    assert result["success"] is False
    assert set(result) == {"success", "error"}
    assert failures == ["target-agent"]
    assert service.calls == []
    assert "returning an error" in caplog.text
    assert _PRIVATE_FAILURE not in repr(result) + caplog.text
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {}, {"agent_type": None, "agent_id": None}, {"agent_id": "target-agent"},
        {"agent_type": "test_agent"}, {"agent_type": "TEST_"},
        {"agent_type": "est_ag"}, {"agent_type": "science"}, {"agent_type": "WESLEY"},
    ],
    ids=["all", "none", "id", "type", "prefix", "substring", "pool", "callsign"],
)
async def test_agent_info_preserves_lookup_fallbacks(
    social_runtime: _FakeRuntime, params: dict[str, Any],
) -> None:
    callsigns = _FakeCallsignRegistry()
    social_runtime.callsign_registry = callsigns
    service = _FakeTelemetry()
    social_runtime.introspective_telemetry = service

    result = await introspect_module.IntrospectionAgent(runtime=social_runtime).act({
        "action": "agent_info", "params": params,
    })

    assert result["success"] is True
    assert [row["id"] for row in result["data"]["agents"]] == ["target-agent"]
    assert service.calls == [("trust", "target-agent"), ("social", "target-agent")]
    assert callsigns.calls == (["WESLEY"] if params.get("agent_type") == "WESLEY" else [])


@pytest.mark.asyncio
@pytest.mark.parametrize("selection", ["unknown-id", "unknown-type", "empty-registry"])
async def test_agent_info_empty_selection_does_not_collect_facts(
    social_runtime: _FakeRuntime, selection: str,
) -> None:
    registry = social_runtime.registry
    trust = social_runtime.trust_network
    router = social_runtime.hebbian_router
    assert registry is not None and trust is not None and router is not None
    service = _FakeTelemetry()
    social_runtime.introspective_telemetry = service
    if selection == "empty-registry":
        registry.agent = None
        params: dict[str, Any] = {}
        qualifier = "all"
    else:
        params = {"agent_id" if selection == "unknown-id" else "agent_type": "unknown"}
        qualifier = "unknown"

    result = await introspect_module.IntrospectionAgent(runtime=social_runtime).act({
        "action": "agent_info", "params": params,
    })

    assert result == {
        "success": True,
        "data": {"agents": [], "message": f"No agents found matching: {qualifier}"},
    }
    assert service.calls == []
    assert trust.score_subjects == []
    assert router.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "selection", ["summary", "no-groups", "unknown", "fuzzy", "missing-pool", "unknown-member"],
)
async def test_team_info_preserves_summaries_matching_and_sparse_roster(
    social_runtime: _FakeRuntime, selection: str,
) -> None:
    service = _FakeTelemetry()
    social_runtime.introspective_telemetry = service
    params: dict[str, Any] = {"team": "science"}
    if selection in {"summary", "no-groups"}:
        params = {}
        if selection == "no-groups":
            social_runtime.pool_groups = PoolGroupRegistry()
    elif selection == "unknown":
        params = {"team": "unknown"}
    elif selection == "fuzzy":
        params = {"team": " SCI "}
    elif selection == "missing-pool":
        group = social_runtime.pool_groups.get_group("science")
        assert group is not None
        group.pool_names.add("missing_pool")
    else:
        social_runtime.pools["science_pool"].healthy_agents.append("unknown-agent")

    result = await introspect_module.IntrospectionAgent(runtime=social_runtime).act({
        "action": "team_info", "params": params,
    })

    assert result["success"] is True
    data = result["data"]
    if selection == "summary":
        assert data == {"teams": [{
            "name": "science", "display_name": "Science Team", "total_agents": 1,
            "healthy_agents": 1, "health_ratio": 1.0, "pool_count": 1,
        }], "count": 1}
    elif selection == "no-groups":
        assert data == {"message": "No crew teams registered."}
    elif selection == "unknown":
        assert data == {
            "message": "No crew team found matching 'unknown'.", "available_teams": ["science"],
        }
    else:
        assert data["team"]["name"] == "science"
        assert data["agents"] == [{
            "id": "target-agent", "type": "test_agent", "trust_score": 0.9375,
            "pool": "science_pool",
        }]
        assert set(data["pools"]) == {"science_pool"}
        assert service.calls == [("trust", "target-agent")]
    if selection in {"summary", "no-groups", "unknown"}:
        assert service.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "domain"),
    [("agent_info", "trust"), ("agent_info", "social"), ("team_info", "trust")],
)
@pytest.mark.parametrize("error_type", [asyncio.CancelledError, _LifecycleSignal])
async def test_captain_service_lifecycle_signals_propagate(
    social_runtime: _FakeRuntime, action: str, domain: str,
    error_type: type[BaseException],
) -> None:
    trust = social_runtime.trust_network
    router = social_runtime.hebbian_router
    assert trust is not None and router is not None
    error = error_type("stop this query")
    service = _FakeTelemetry(failures={domain: error})
    social_runtime.introspective_telemetry = service

    with pytest.raises(error_type) as caught:
        await introspect_module.IntrospectionAgent(runtime=social_runtime).act(
            _captain_plan(action),
        )

    assert caught.value is error
    assert service.calls == (
        [("trust", "target-agent"), ("social", "target-agent")]
        if domain == "social" else [("trust", "target-agent")]
    )
    assert trust.score_subjects == []
    assert router.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "expected_key"),
    [
        ("explain_last", "explanation"), ("agent_info", "agents"),
        ("team_info", "team"), ("system_health", "overall_health"),
        ("why", "matching_episodes"), ("introspect_memory", "enabled"),
        ("introspect_system", "agents_by_tier"), ("system_anomalies", "message"),
        ("emergent_patterns", "message"), ("search_knowledge", "query"),
        ("introspect_design", "message"),
    ],
)
async def test_all_introspection_dispatches_return_real_reports(
    social_runtime: _FakeRuntime, action: str, expected_key: str,
) -> None:
    service = _FakeTelemetry()
    social_runtime.introspective_telemetry = service
    captain = introspect_module.IntrospectionAgent(runtime=social_runtime)
    assert {descriptor.name for descriptor in captain.intent_descriptors} == {
        "explain_last", "agent_info", "team_info", "system_health", "why",
        "introspect_memory", "introspect_system", "system_anomalies",
        "emergent_patterns", "search_knowledge", "introspect_design",
    }
    message = IntentMessage(intent=action, params={
        "agent_id": "target-agent", "team": "science", "query": "agent facts",
        "question": "What happened?",
    })

    result = await captain.handle_intent(message)

    assert result is not None
    assert result.success is True
    assert result.intent_id == message.id
    assert result.agent_id == captain.id
    assert result.error is None
    assert isinstance(result.result, dict)
    assert expected_key in result.result
    if action == "agent_info":
        assert service.calls == [("trust", "target-agent"), ("social", "target-agent")]
    elif action == "team_info":
        assert service.calls == [("trust", "target-agent")]
    else:
        assert service.calls == []