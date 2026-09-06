"""AD-1258: Renderer regressions for first-person self-knowledge."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from probos.cognitive import introspective_telemetry as telemetry_module
from probos.cognitive.agentic_dispatch import (
    WorkItemAgenticExecutor,
    WorkItemAgenticOutcome,
)
from probos.cognitive.decomposer import is_capability_gap
from probos.cognitive.introspective_telemetry import IntrospectiveTelemetryService
from probos.cognitive.swe_harness.tool_call import (
    ToolCallRequest,
    ToolCallResult,
    ToolUseBlock,
)
from probos.config import AgenticToolsConfig, SystemConfig, load_config
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import Tool, ToolPermission, ToolRegistration, ToolResult, ToolType
from probos.tools.registry import ToolRegistry
from probos.tools.self_query_tool import (
    SELF_QUERY_DOMAINS,
    SelfQueryTelemetry,
    SelfQueryTool,
)
from probos.types import LLMRequest


_LEGACY_FULL_RENDERING = (
    "--- Your Telemetry (ground self-referential claims in these metrics) ---\n"
    "Memory: 47 episodes (cosine similarity retrieval, no offline processing)\n"
    "Trust: 0.72 (23 observations, uncertainty \u00b10.08, trend: stable)\n"
    "Cognitive zone: GREEN\n"
    "Uptime: 2.3h | Age: 2.3h | Last action: 4.1m ago\n"
    "\n"
    "When discussing yourself, cite these numbers. You may express warmth and\n"
    "personality \u2014 do not generate claims about architecture not reflected here.\n"
    "---"
)


@dataclass
class _FakeHebbianRouter:
    weights: dict[tuple[str, str, str], float]
    calls: dict[str, int]

    def all_weights_typed(self) -> dict[tuple[str, str, str], float]:
        self.calls["hebbian"] += 1
        return dict(self.weights)


@dataclass(frozen=True)
class _FakeTrustEvent:
    agent_id: str
    intent_type: str
    new_score: float


@dataclass
class _FakeTrustNetwork:
    scores: dict[str, float]
    events: list[_FakeTrustEvent]
    calls: dict[str, int]
    score_subjects: list[str] = field(default_factory=list)
    record_subjects: list[str] = field(default_factory=list)
    event_queries: list[tuple[str, int]] = field(default_factory=list)

    def get_score(self, agent_id: str) -> float:
        self.score_subjects.append(agent_id)
        return self.scores[agent_id]

    def get_record(self, agent_id: str) -> None:
        self.record_subjects.append(agent_id)
        return None

    def get_events_for_agent(
        self, agent_id: str, n: int = 5,
    ) -> list[_FakeTrustEvent]:
        self.calls["trust_events"] += 1
        self.event_queries.append((agent_id, n))
        return [event for event in self.events if event.agent_id == agent_id][-n:]


@pytest.fixture
def full_snapshot() -> dict[str, Any]:
    return {
        "memory": {
            "episode_count": 47,
            "retrieval": "cosine_similarity",
            "offline_processing": False,
        },
        "trust": {
            "score": 0.72,
            "observations": 23,
            "uncertainty": 0.08,
            "trend": "stable",
        },
        "cognitive": {"zone": "green"},
        "temporal": {
            "system_uptime_hours": 2.3,
            "agent_age_hours": 2.3,
            "last_action_minutes": 4.1,
        },
        "social": {},
    }


@pytest.mark.parametrize(
    "social",
    [{}, None, {"routing_affinities": []}, {"routing_affinities": None}],
    ids=["empty", "none", "empty-affinities", "none-affinities"],
)
def test_render_full_snapshot_empty_social_is_byte_identical(
    full_snapshot: dict[str, Any], social: dict[str, Any] | None,
) -> None:
    full_snapshot["social"] = social

    rendered = IntrospectiveTelemetryService.render_telemetry_context(full_snapshot)

    assert rendered.encode("utf-8") == _LEGACY_FULL_RENDERING.encode("utf-8")
    assert "Collaboration:" not in rendered


def test_render_full_snapshot_absent_social_is_byte_identical(
    full_snapshot: dict[str, Any],
) -> None:
    del full_snapshot["social"]

    rendered = IntrospectiveTelemetryService.render_telemetry_context(full_snapshot)

    assert rendered.encode("utf-8") == _LEGACY_FULL_RENDERING.encode("utf-8")
    assert "Collaboration:" not in rendered


def test_render_populated_social_preserves_order_and_input(
    full_snapshot: dict[str, Any],
) -> None:
    full_snapshot["social"] = {
        "routing_affinities": [
            {"intent": "canary_social_probe", "weight": 0.88},
            {"intent": "review_code", "weight": 0.61},
        ],
        "interaction_breadth": 2,
    }
    original = deepcopy(full_snapshot)
    social_line = (
        "Collaboration: routing affinities: canary_social_probe (0.88), "
        "review_code (0.61) | interaction breadth: 2"
    )

    rendered = IntrospectiveTelemetryService.render_telemetry_context(full_snapshot)

    assert rendered == _LEGACY_FULL_RENDERING.replace(
        "\n\n", f"\n{social_line}\n\n", 1,
    )
    assert full_snapshot == original


@pytest.mark.parametrize("breadth", [0, 3])
def test_render_social_breadth_without_affinities_preserves_value(
    breadth: int,
) -> None:
    snapshot = {"social": {"interaction_breadth": breadth}}

    rendered = IntrospectiveTelemetryService.render_telemetry_context(snapshot)

    assert rendered.splitlines()[1] == f"Collaboration: interaction breadth: {breadth}"
    assert "routing affinities:" not in rendered


@pytest.mark.parametrize(
    ("affinity", "expected"),
    [
        ({}, "? (?)"),
        ({"intent": "canary_social_probe"}, "canary_social_probe (?)"),
        ({"weight": 0.88}, "? (0.88)"),
    ],
    ids=["both-missing", "weight-missing", "intent-missing"],
)
def test_render_social_missing_affinity_fields_uses_placeholders(
    affinity: dict[str, Any], expected: str,
) -> None:
    snapshot = {"social": {"routing_affinities": [affinity]}}
    original = deepcopy(snapshot)

    rendered = IntrospectiveTelemetryService.render_telemetry_context(snapshot)

    assert rendered.splitlines()[1] == f"Collaboration: routing affinities: {expected}"
    assert "interaction breadth:" not in rendered
    assert snapshot == original


@pytest.mark.parametrize(
    ("snapshot", "domain_lines"),
    [
        (
            {"memory": {"episode_count": 5}},
            ["Memory: 5 episodes (cosine similarity retrieval, no offline processing)"],
        ),
        ({"trust": {"score": 0.512}}, ["Trust: 0.512"]),
        ({"cognitive": {"zone": "amber"}}, ["Cognitive zone: AMBER"]),
        ({"temporal": {"system_uptime_hours": 2.3}}, ["Uptime: 2.3h"]),
        (
            {"social": {"interaction_breadth": 0}},
            ["Collaboration: interaction breadth: 0"],
        ),
        (
            {"memory": {}},
            ["Memory: unknown episodes (cosine similarity retrieval, no offline processing)"],
        ),
        ({"trust": {}}, ["Trust: no record yet"]),
        ({"cognitive": {}}, ["Cognitive zone: UNKNOWN"]),
        ({"temporal": {}}, []),
        ({"social": {}}, []),
    ],
    ids=[
        "memory", "trust", "cognitive", "temporal", "social",
        "empty-memory", "empty-trust", "empty-cognitive", "empty-temporal",
        "empty-social",
    ],
)
def test_render_partial_snapshot_reports_only_present_domains(
    snapshot: dict[str, Any], domain_lines: list[str],
) -> None:
    original = deepcopy(snapshot)
    expected_lines = [
        "--- Your Telemetry (ground self-referential claims in these metrics) ---",
        *domain_lines,
        "",
        "When discussing yourself, cite these numbers. You may express warmth and",
        "personality \u2014 do not generate claims about architecture not reflected here.",
        "---",
    ]

    rendered = IntrospectiveTelemetryService.render_telemetry_context(snapshot)

    assert rendered == "\n".join(expected_lines)
    assert snapshot == original


def test_render_populated_and_empty_contexts_are_not_capability_gaps(
    full_snapshot: dict[str, Any],
) -> None:
    full_snapshot["social"] = {
        "routing_affinities": [
            {"intent": "canary_social_probe", "weight": 0.88},
            {},
        ],
        "interaction_breadth": 0,
    }
    assert is_capability_gap("I cannot complete this action.")

    for snapshot in ({}, {"social": {}}, full_snapshot):
        rendered = IntrospectiveTelemetryService.render_telemetry_context(snapshot)
        assert not is_capability_gap(rendered)


@pytest.mark.asyncio
async def test_collection_to_render_preserves_social() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    expected_origin = (
        repository_root / "src" / "probos" / "cognitive" / "introspective_telemetry.py"
    )
    assert telemetry_module.__file__ is not None
    assert Path(telemetry_module.__file__).resolve() == expected_origin.resolve()

    subject = "subject-agent"
    other_subject = "other-agent"
    marker = "canary_social_probe"
    other_marker = "other_subject_probe"
    calls = {"hebbian": 0, "trust_events": 0}
    weights = {
        (marker, subject, "routing"): 0.876543,
        (other_marker, other_subject, "routing"): 0.99,
        ("zero_weight_probe", subject, "routing"): 0.0,
        ("negative_weight_probe", subject, "routing"): -0.5,
    }
    events = [
        _FakeTrustEvent(subject, marker, 0.5124),
        _FakeTrustEvent(other_subject, other_marker, 0.91),
    ]
    router = _FakeHebbianRouter(weights=weights, calls=calls)
    trust = _FakeTrustNetwork(
        scores={subject: 0.512375, other_subject: 0.91},
        events=events,
        calls=calls,
    )
    service = IntrospectiveTelemetryService(
        runtime=SimpleNamespace(hebbian_router=router, trust_network=trust),
    )
    assert weights[(other_marker, other_subject, "routing")] > weights[
        (marker, subject, "routing")
    ] > 0
    assert {event.agent_id for event in events} == {subject, other_subject}
    assert len({event.intent_type for event in events}) == 2
    assert calls == {"hebbian": 0, "trust_events": 0}

    snapshot = await service.get_full_snapshot(subject)

    assert list(snapshot) == ["memory", "trust", "cognitive", "temporal", "social"]
    assert calls == {"hebbian": 1, "trust_events": 2}
    assert trust.score_subjects == [subject]
    assert trust.record_subjects == [subject]
    assert trust.event_queries == [(subject, 5), (subject, 20)]
    assert snapshot["trust"]["score"] == 0.5124
    # AD-1259 adds the Captain projection without widening first-person routing.
    assert snapshot["social"] == {
        "routing_affinities": [{"intent": marker, "weight": 0.8765}],
        "incoming_affinities": [
            {"intent": marker, "weight": 0.8765},
            {"intent": "zero_weight_probe", "weight": 0.0},
            {"intent": "negative_weight_probe", "weight": -0.5},
        ],
        "total_connections": 3,
        "interaction_breadth": 1,
    }
    original = deepcopy(snapshot)

    rendered = service.render_telemetry_context(snapshot)

    assert snapshot == original
    assert calls == {"hebbian": 1, "trust_events": 2}
    assert "Trust: 0.5124\n" in rendered
    assert other_marker not in rendered
    assert "zero_weight_probe" not in rendered
    assert "negative_weight_probe" not in rendered
    assert marker in rendered, "Collected social marker was lost during rendering"
    assert "0.8765" in rendered
    assert "interaction breadth: 1" in rendered
    assert not is_capability_gap(rendered)


_BASELINE_OFFER_NAMES = (
    "web_search", "read_page", "http_fetch", "run_python",
    "search_capabilities", "delegate_task",
)
_BASELINE_OFFER_SHA256 = (
    "71ae15e69d52f20ae548c221376b08a7c2be531a559ee094ad694b3d2756f949"
)
_PRIVATE_FAILURE = "private-telemetry-exception-payload"


class _StringSubclass(str):
    pass


class _DictSubclass(dict[str, Any]):
    pass


class _LifecycleSignal(BaseException):
    pass


@dataclass
class _FakeSelfQueryTelemetry:
    snapshots: dict[str, dict[str, Any]]
    calls: list[tuple[str, str]] = field(default_factory=list)
    failure: tuple[str, BaseException] | None = None

    def _read(self, domain: str, agent_id: str) -> dict[str, Any]:
        self.calls.append((domain, agent_id))
        if self.failure is not None and self.failure[0] == domain:
            raise self.failure[1]
        snapshot = self.snapshots[agent_id]
        return snapshot if domain == "full" else snapshot[domain]

    async def get_memory_state(self, agent_id: str) -> dict[str, Any]:
        return self._read("memory", agent_id)

    async def get_trust_state(self, agent_id: str) -> dict[str, Any]:
        return self._read("trust", agent_id)

    async def get_cognitive_state(self, agent_id: str) -> dict[str, Any]:
        return self._read("cognitive", agent_id)

    async def get_temporal_state(self, agent_id: str) -> dict[str, Any]:
        return self._read("temporal", agent_id)

    async def get_social_state(self, agent_id: str) -> dict[str, Any]:
        return self._read("social", agent_id)

    async def get_full_snapshot(self, agent_id: str) -> dict[str, Any]:
        return self._read("full", agent_id)

    @staticmethod
    def render_telemetry_context(snapshot: dict[str, Any]) -> str:
        return IntrospectiveTelemetryService.render_telemetry_context(snapshot)


@pytest.fixture
def self_query_telemetry(full_snapshot: dict[str, Any]) -> _FakeSelfQueryTelemetry:
    snapshots = {}
    for subject in ("baseline-agent", "other-agent"):
        snapshot = deepcopy(full_snapshot)
        snapshot["social"] = {
            "routing_affinities": [
                {"intent": f"{subject}_unique_social_probe", "weight": 0.88},
            ],
            "interaction_breadth": 2,
        }
        snapshots[subject] = snapshot
    return _FakeSelfQueryTelemetry(snapshots=snapshots)


@pytest.fixture
def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def shipped_config(
    repository_root: Path, monkeypatch: pytest.MonkeyPatch,
) -> SystemConfig:
    for name in tuple(os.environ):
        if name.startswith("PROBOS_"):
            monkeypatch.delenv(name)
    config_path = repository_root / "config" / "system.yaml"
    assert config_path.is_file()
    return load_config(config_path)


def _query_output(
    service: _FakeSelfQueryTelemetry,
    domains: list[str],
    *,
    agent_id: str = "baseline-agent",
    unknown_domains: list[str] | None = None,
) -> dict[str, Any]:
    snapshot = {
        domain: deepcopy(service.snapshots[agent_id][domain]) for domain in domains
    }
    return {
        "agent_id": agent_id,
        "domains": snapshot,
        "rendered": IntrospectiveTelemetryService.render_telemetry_context(snapshot),
        "unknown_domains": unknown_domains or [],
    }


def test_self_query_protocol_schema_and_description(
    self_query_telemetry: _FakeSelfQueryTelemetry,
) -> None:
    dependency: SelfQueryTelemetry = self_query_telemetry
    tool: Tool = SelfQueryTool(telemetry=dependency)

    assert isinstance(tool, Tool)
    assert tool.tool_id == "self_query"
    assert tool.name == "Self Query"
    assert tool.tool_type is ToolType.UTILITY_AGENT
    assert type(SELF_QUERY_DOMAINS) is tuple
    assert SELF_QUERY_DOMAINS == ("memory", "trust", "cognitive", "temporal", "social")
    schema = json.loads(json.dumps(tool.input_schema))
    assert schema["type"] == "object"
    assert list(schema["properties"]) == ["domains"]
    assert schema.get("required", []) == []
    assert schema["additionalProperties"] is False
    assert schema["properties"]["domains"]["type"] == "array"
    assert schema["properties"]["domains"]["items"] == {
        "type": "string", "enum": list(SELF_QUERY_DOMAINS),
    }
    schema["properties"]["domains"]["items"]["enum"].append("peer")
    assert tool.input_schema["properties"]["domains"]["items"]["enum"] == list(
        SELF_QUERY_DOMAINS,
    )
    output_schema = json.loads(json.dumps(tool.output_schema))
    assert output_schema["type"] == "object"
    assert output_schema["required"] == [
        "agent_id", "domains", "rendered", "unknown_domains",
    ]
    assert set(output_schema["properties"]) == set(output_schema["required"])
    assert "your own" in tool.description
    assert "before describing yourself" in tool.description
    assert not is_capability_gap(tool.description)
    assert self_query_telemetry.calls == []


def test_runtime_telemetry_property_is_read_only_and_preserves_service_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from probos.runtime import ProbOSRuntime

    runtime = object.__new__(ProbOSRuntime)
    assert runtime.introspective_telemetry is None
    service: SelfQueryTelemetry = IntrospectiveTelemetryService(runtime=SimpleNamespace())
    monkeypatch.setattr(runtime, "_introspective_telemetry", service, raising=False)
    assert runtime.introspective_telemetry is service
    with pytest.raises(AttributeError):
        setattr(runtime, "introspective_telemetry", None)
    assert runtime.introspective_telemetry is service
    monkeypatch.setattr(runtime, "_introspective_telemetry", None)
    assert runtime.introspective_telemetry is None


@pytest.mark.asyncio
@pytest.mark.parametrize("domain", SELF_QUERY_DOMAINS)
async def test_self_query_singleton_calls_only_selected_getter(
    domain: str, self_query_telemetry: _FakeSelfQueryTelemetry,
) -> None:
    tool = SelfQueryTool(telemetry=self_query_telemetry)

    result = await tool.invoke({"domains": [domain]}, {"agent_id": "baseline-agent"})

    assert result.success
    assert result.output == _query_output(self_query_telemetry, [domain])
    assert list(result.output["domains"]) == [domain]
    assert self_query_telemetry.calls == [(domain, "baseline-agent")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("requested", "selected", "unknown"),
    [
        (["social", "trust", "memory", "social"], ["memory", "trust", "social"], []),
        (["social", "future", "trust", "future"], ["trust", "social"], ["future"]),
        (["TRUST", "trust", " trust "], ["trust"], ["TRUST", " trust "]),
    ],
)
async def test_self_query_subsets_are_canonical_without_widening(
    requested: list[str], selected: list[str], unknown: list[str],
    self_query_telemetry: _FakeSelfQueryTelemetry,
) -> None:
    params = {"domains": requested}
    original = deepcopy(params)
    tool = SelfQueryTool(telemetry=self_query_telemetry)

    result = await tool.invoke(params, {"agent_id": "baseline-agent"})

    assert result.success
    assert result.output == _query_output(
        self_query_telemetry, selected, unknown_domains=unknown,
    )
    assert list(result.output["domains"]) == selected
    assert self_query_telemetry.calls == [
        (domain, "baseline-agent") for domain in selected
    ]
    assert params == original


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {},
        {"domains": ["social", "temporal", "cognitive", "trust", "memory", "trust"]},
        {"domains": ["future", "memory", "trust", "cognitive", "temporal", "social"]},
    ],
    ids=["omitted", "explicit-all-deduplicated", "all-with-unknown"],
)
async def test_self_query_full_selection_calls_snapshot_once(
    params: dict[str, Any], self_query_telemetry: _FakeSelfQueryTelemetry,
) -> None:
    tool = SelfQueryTool(telemetry=self_query_telemetry)

    result = await tool.invoke(params, {"agent_id": "baseline-agent"})

    assert result.success
    assert result.output == _query_output(
        self_query_telemetry,
        list(SELF_QUERY_DOMAINS),
        unknown_domains=["future"] if "future" in params.get("domains", []) else [],
    )
    assert list(result.output["domains"]) == list(SELF_QUERY_DOMAINS)
    assert self_query_telemetry.calls == [("full", "baseline-agent")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("selection", "social_fields", "projected_social_fields", "render_error"),
    [
        pytest.param(
            None,
            {"social": {
                "total_connections": 3,
                "interaction_breadth": None,
                "incoming_affinities": [{"intent": "captain-only", "weight": 0.8765}],
                "routing_affinities": [
                    {"intent": "second", "weight": 0.5},
                    {"intent": "first", "weight": 0.8765},
                ],
                "outbound_affinities": [{"intent": "peer", "weight": 0.42}],
            }},
            {"social": {
                "interaction_breadth": None,
                "routing_affinities": [
                    {"intent": "second", "weight": 0.5},
                    {"intent": "first", "weight": 0.8765},
                ],
            }},
            False, id="full-ordered-values",
        ),
        pytest.param(
            ["trust", "social"],
            {"social": {
                "interaction_breadth": 0, "total_connections": 0, "routing_affinities": [],
            }},
            {"social": {"interaction_breadth": 0, "routing_affinities": []}},
            False, id="selected-zero-and-empty",
        ),
        pytest.param(
            ["social"],
            {"social": {"routing_affinities": None, "incoming_affinities": []}},
            {"social": {"routing_affinities": None}},
            False, id="selected-partial-routing-none",
        ),
        pytest.param(
            None,
            {"social": {"interaction_breadth": 2, "outbound_affinities": []}},
            {"social": {"interaction_breadth": 2}},
            False, id="full-partial-breadth",
        ),
        pytest.param(
            ["social"],
            {"social": {
                "total_connections": 0, "incoming_affinities": [], "outbound_affinities": [],
            }},
            {"social": {}}, False, id="selected-captain-only",
        ),
        pytest.param(None, {"social": {}}, {"social": {}}, False, id="full-empty"),
        pytest.param(None, {}, {}, False, id="full-absent"),
        pytest.param(None, {"social": None}, {"social": None}, False, id="full-nondict-none"),
        pytest.param(
            ["trust", "social"], {"social": []}, {"social": []},
            False, id="selected-nondict-empty",
        ),
        pytest.param(
            ["social"], {"social": ["legacy"]}, {"social": ["legacy"]},
            True, id="selected-nondict-render-error",
        ),
        pytest.param(
            ["memory", "trust", "cognitive", "temporal"],
            {"social": {
                "total_connections": 3,
                "routing_affinities": [{"intent": "unqueried", "weight": 0.5}],
            }},
            {}, False, id="social-excluded",
        ),
    ],
)
async def test_self_query_projection_preserves_backing_objects_and_legacy_output(
    selection: list[str] | None,
    social_fields: dict[str, Any],
    projected_social_fields: dict[str, Any],
    render_error: bool,
    full_snapshot: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = full_snapshot
    del snapshot["social"]
    snapshot.update(deepcopy(social_fields))
    original = deepcopy(snapshot)
    domain_refs = dict(snapshot)
    telemetry = _FakeSelfQueryTelemetry(snapshots={"baseline-agent": snapshot})
    rendered_snapshots: list[dict[str, Any]] = []

    def render_snapshot(outward: dict[str, Any]) -> str:
        rendered_snapshots.append(outward)
        return IntrospectiveTelemetryService.render_telemetry_context(outward)

    monkeypatch.setattr(telemetry, "render_telemetry_context", render_snapshot)
    selected = list(snapshot) if selection is None else selection
    expected_snapshot = {domain: original[domain] for domain in selected}
    expected_rendered = ""
    if render_error:
        with pytest.raises(AttributeError):
            IntrospectiveTelemetryService.render_telemetry_context(expected_snapshot)
    else:
        expected_rendered = IntrospectiveTelemetryService.render_telemetry_context(
            expected_snapshot,
        )
    if "social" in expected_snapshot:
        expected_snapshot["social"] = deepcopy(projected_social_fields["social"])
    params = {} if selection is None else {"domains": selection}
    assert telemetry.snapshots["baseline-agent"] is snapshot
    assert telemetry.calls == []

    result = await SelfQueryTool(telemetry=telemetry).invoke(
        params, {"agent_id": "baseline-agent"},
    )

    assert result.success is (not render_error)
    assert result.error == ("self_query: telemetry query failed." if render_error else None)
    assert result.output == {
        "agent_id": "baseline-agent",
        "domains": {} if render_error else expected_snapshot,
        "rendered": expected_rendered,
        "unknown_domains": [],
    }
    assert telemetry.calls == (
        [("full", "baseline-agent")] if selection is None
        else [(domain, "baseline-agent") for domain in selected]
    )
    assert len(rendered_snapshots) == 1
    outward = rendered_snapshots[0]
    assert outward == expected_snapshot
    assert list(outward) == list(expected_snapshot)
    assert outward is not snapshot
    if not render_error:
        assert result.output["domains"] is outward
    assert telemetry.snapshots["baseline-agent"] is snapshot
    assert snapshot == original
    assert list(snapshot) == list(original)
    for domain, original_domain in domain_refs.items():
        assert snapshot[domain] is original_domain
        if isinstance(original_domain, dict):
            assert list(original_domain) == list(original[domain])
        if domain not in outward:
            continue
        if domain == "social" and isinstance(original_domain, dict):
            assert outward[domain] is not original_domain
            assert list(outward[domain]) == list(expected_snapshot[domain])
            for key, value in outward[domain].items():
                assert value is original_domain[key]
        else:
            assert outward[domain] is original_domain


@pytest.mark.asyncio
@pytest.mark.parametrize("selection", [[], ["future", "unknown"]])
async def test_self_query_empty_or_unknown_selection_refuses_without_reads(
    selection: list[str], self_query_telemetry: _FakeSelfQueryTelemetry,
) -> None:
    result = await SelfQueryTool(telemetry=self_query_telemetry).invoke(
        {"domains": selection}, {"agent_id": "baseline-agent"},
    )

    assert not result.success
    assert result.error
    assert result.output == {
        "agent_id": "baseline-agent", "domains": {}, "rendered": "",
        "unknown_domains": selection,
    }
    assert self_query_telemetry.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "domains",
    [None, "trust", {}, ("trust",), [None], [42], [[]], [_StringSubclass("trust")]],
)
async def test_self_query_malformed_domains_refuse_without_reads(
    domains: Any, self_query_telemetry: _FakeSelfQueryTelemetry,
) -> None:
    result = await SelfQueryTool(telemetry=self_query_telemetry).invoke(
        {"domains": domains}, {"agent_id": "baseline-agent"},
    )

    assert not result.success
    assert result.error == "self_query: domains must be an array of strings."
    assert self_query_telemetry.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("params", [None, [], "social", True, _DictSubclass()])
async def test_self_query_malformed_params_refuse_without_reads(
    params: Any, self_query_telemetry: _FakeSelfQueryTelemetry,
) -> None:
    result = await SelfQueryTool(telemetry=self_query_telemetry).invoke(
        params, {"agent_id": "baseline-agent"},
    )

    assert not result.success
    assert result.error == "self_query: params must be an object."
    assert self_query_telemetry.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "context",
    [
        None, [], "baseline-agent", {}, _DictSubclass(agent_id="baseline-agent"),
        {"agent_id": None}, {"agent_id": ""}, {"agent_id": " \t\n"},
        {"agent_id": True}, {"agent_id": 17}, {"agent_id": []},
        {"agent_id": _StringSubclass("baseline-agent")},
        {"callsign": "baseline-agent"},
    ],
)
async def test_self_query_malformed_context_refuses_without_identity_fallback(
    context: Any, self_query_telemetry: _FakeSelfQueryTelemetry,
) -> None:
    result = await SelfQueryTool(telemetry=self_query_telemetry).invoke({}, context)

    assert not result.success
    assert result.error is not None and "context" in result.error
    assert self_query_telemetry.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "key", ["agent_id", "agent_type", "callsign", "subject", "target", "unexpected"],
)
async def test_self_query_undeclared_parameter_precedes_selection_and_context(
    key: str, self_query_telemetry: _FakeSelfQueryTelemetry,
) -> None:
    result = await SelfQueryTool(telemetry=self_query_telemetry).invoke(
        {key: "other-agent", "domains": []},
    )

    assert not result.success
    assert result.error == f"self_query: unknown parameter(s) {key}. Accepted: domains."
    assert "other-agent" not in result.error
    assert self_query_telemetry.calls == []


@pytest.mark.asyncio
async def test_self_query_preserves_exact_identity_and_retains_no_caller(
    self_query_telemetry: _FakeSelfQueryTelemetry,
) -> None:
    exact_subject = " baseline-agent "
    self_query_telemetry.snapshots[exact_subject] = deepcopy(
        self_query_telemetry.snapshots["baseline-agent"],
    )
    tool = SelfQueryTool(telemetry=self_query_telemetry)

    first = await tool.invoke(
        {"domains": ["social"]}, {"agent_id": exact_subject, "callsign": "other-agent"},
    )
    second = await tool.invoke({"domains": ["social"]}, {"agent_id": "other-agent"})
    missing = await tool.invoke({})

    assert first.success and second.success
    assert first.output == _query_output(
        self_query_telemetry, ["social"], agent_id=exact_subject,
    )
    assert second.output == _query_output(
        self_query_telemetry, ["social"], agent_id="other-agent",
    )
    assert "baseline-agent_unique_social_probe" not in second.output["rendered"]
    assert not missing.success
    assert self_query_telemetry.calls == [
        ("social", exact_subject), ("social", "other-agent"),
    ]
    assert list(vars(tool).values()) == [self_query_telemetry]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_site", [*SELF_QUERY_DOMAINS, "full", "render"])
async def test_self_query_ordinary_failures_are_error_shaped_and_content_safe(
    failure_site: str, self_query_telemetry: _FakeSelfQueryTelemetry,
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    if failure_site == "render":
        def fail_render(snapshot: dict[str, Any]) -> str:
            assert snapshot["social"]["routing_affinities"]
            raise RuntimeError(_PRIVATE_FAILURE)

        monkeypatch.setattr(self_query_telemetry, "render_telemetry_context", fail_render)
        params = {"domains": ["social"]}
    else:
        self_query_telemetry.failure = (failure_site, RuntimeError(_PRIVATE_FAILURE))
        params = {} if failure_site == "full" else {"domains": [failure_site]}

    result = await SelfQueryTool(telemetry=self_query_telemetry).invoke(
        params, {"agent_id": "baseline-agent"},
    )

    assert not result.success
    assert result.error == "self_query: telemetry query failed."
    assert result.output == {
        "agent_id": "baseline-agent", "domains": {}, "rendered": "",
        "unknown_domains": [],
    }
    assert self_query_telemetry.calls == [
        ("social" if failure_site == "render" else failure_site, "baseline-agent"),
    ]
    assert "returning an error" in caplog.text
    assert _PRIVATE_FAILURE not in result.error + repr(result.output) + caplog.text
    assert "baseline-agent_unique_social_probe" not in repr(result.output) + caplog.text


@pytest.mark.asyncio
async def test_self_query_unavailable_service_returns_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    result = await SelfQueryTool(telemetry=None).invoke(
        {"domains": ["social"]}, {"agent_id": "baseline-agent"},
    )

    assert not result.success
    assert result.error == "self_query: telemetry service unavailable."
    assert result.output == {
        "agent_id": "baseline-agent", "domains": {}, "rendered": "",
        "unknown_domains": [],
    }
    assert "returning an error" in caplog.text


@pytest.mark.asyncio
async def test_self_query_preserves_real_full_snapshot_best_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = IntrospectiveTelemetryService(runtime=SimpleNamespace())
    subjects: list[str] = []

    async def fail_memory(agent_id: str) -> dict[str, Any]:
        subjects.append(agent_id)
        raise RuntimeError("memory read failed")

    monkeypatch.setattr(service, "get_memory_state", fail_memory)

    result = await SelfQueryTool(telemetry=service).invoke(
        {}, {"agent_id": "baseline-agent"},
    )

    assert result.success
    assert subjects == ["baseline-agent"]
    assert list(result.output["domains"]) == list(SELF_QUERY_DOMAINS)
    assert result.output["domains"]["memory"] == {}
    assert result.output["domains"]["cognitive"]["zone"] == "green"
    assert result.output["rendered"] == service.render_telemetry_context(
        result.output["domains"],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [asyncio.CancelledError, _LifecycleSignal])
@pytest.mark.parametrize("selection", ["full", "social"])
async def test_self_query_lifecycle_exceptions_propagate(
    error_type: type[BaseException], selection: str,
    self_query_telemetry: _FakeSelfQueryTelemetry,
) -> None:
    error = error_type("lifecycle signal")
    self_query_telemetry.failure = (selection, error)
    params = {} if selection == "full" else {"domains": [selection]}

    with pytest.raises(error_type) as caught:
        await SelfQueryTool(telemetry=self_query_telemetry).invoke(
            params, {"agent_id": "baseline-agent"},
        )

    assert caught.value is error
    assert self_query_telemetry.calls == [(selection, "baseline-agent")]


def test_self_query_config_default_and_facade_identity() -> None:
    from probos.config_models.agentic import AgenticToolsConfig as OwnedAgenticToolsConfig

    assert AgenticToolsConfig is OwnedAgenticToolsConfig
    assert AgenticToolsConfig().self_query_enabled is False
    assert SystemConfig().agentic_tools.self_query_enabled is False
    assert list(AgenticToolsConfig.model_fields)[-1] == "self_query_enabled"


@pytest.mark.parametrize(
    ("value", "expected"), [(True, True), (False, False), ("true", True), ("false", False)],
)
def test_self_query_config_parses_boolean_values(value: Any, expected: bool) -> None:
    config = AgenticToolsConfig.model_validate({"self_query_enabled": value})
    assert config.self_query_enabled is expected


@pytest.mark.parametrize("value", [None, "invalid", 2, [], {}])
def test_self_query_config_rejects_invalid_boolean_values(value: Any) -> None:
    with pytest.raises(ValidationError) as caught:
        AgenticToolsConfig.model_validate({"self_query_enabled": value})
    assert caught.value.errors()[0]["loc"] == ("self_query_enabled",)


def test_self_query_shipped_yaml_enables_only_the_opt_in_default(
    shipped_config: SystemConfig,
) -> None:
    assert type(shipped_config.agentic_tools) is AgenticToolsConfig
    assert shipped_config.agentic_tools.self_query_enabled is True
    assert AgenticToolsConfig().self_query_enabled is False


class _FakeSelfQueryRuntime(SimpleNamespace):
    def __init__(
        self, *, config: SystemConfig, telemetry: SelfQueryTelemetry | None,
    ) -> None:
        registry = ToolRegistry()
        store = ToolPermissionStore()
        registry.set_permission_store(store)
        super().__init__(
            config=config,
            tool_registry=registry,
            tool_permission_store=store,
            intent_bus=object(),
            intent_grant_store=None,
            mcp_workbench=None,
            attachment_store=None,
            artifact_store=None,
            cognitive_skill_catalog=None,
            emit_event=None,
            telemetry=telemetry,
            telemetry_accesses=0,
            refuse_telemetry_access=False,
        )

    @property
    def introspective_telemetry(self) -> SelfQueryTelemetry | None:
        self.telemetry_accesses += 1
        if self.refuse_telemetry_access:
            raise RuntimeError(_PRIVATE_FAILURE)
        return self.telemetry


class _ScriptedSelfQueryLLM:
    def __init__(
        self,
        *,
        call: ToolCallRequest | None = None,
        inspect_result: Callable[[LLMRequest], None] | None = None,
    ) -> None:
        self.call = call
        self.inspect_result = inspect_result
        self.requests: list[LLMRequest] = []
        self.inspected = False

    async def complete(self, request: LLMRequest, **kwargs: Any) -> SimpleNamespace:
        self.requests.append(deepcopy(request))
        if self.call is not None and len(self.requests) == 1:
            return SimpleNamespace(
                content_blocks=[ToolUseBlock(tool_call=self.call)],
                content="", tokens_used=1,
            )
        assert len(self.requests) == (2 if self.call is not None else 1)
        if self.inspect_result is not None:
            self.inspect_result(request)
            self.inspected = True
        return SimpleNamespace(
            content_blocks=[], content="baseline-complete", tokens_used=1,
        )


async def _run_self_query_fixture(
    runtime: _FakeSelfQueryRuntime,
    llm: _ScriptedSelfQueryLLM,
    *,
    extra_context: dict[str, Any] | None = None,
) -> WorkItemAgenticOutcome:
    return await WorkItemAgenticExecutor(llm_client=llm).run(
        agent_id="baseline-agent",
        instructions="Offline offer capture.",
        task_text=(
            "Return baseline-complete without tools." if llm.call is None
            else "Read your own telemetry before describing yourself."
        ),
        runtime=runtime,
        department="science",
        rank="lieutenant",
        thread_id="baseline-thread",
        max_iterations=2,
        extra_context=extra_context,
    )


def _assert_baseline_offer(definitions: list[dict[str, Any]]) -> None:
    """Worker pre-registration capture, not a fingerprint derived from this assembly."""
    names = [definition["function"]["name"] for definition in definitions]
    assert {"web_search", "read_page", "http_fetch"}.issubset(names)
    assert "run_python" in names
    assert {"search_capabilities", "delegate_task"}.issubset(names)
    assert names == list(_BASELINE_OFFER_NAMES)
    serialized = json.dumps(
        definitions, ensure_ascii=True, separators=(",", ":"),
    ).encode("utf-8")
    assert hashlib.sha256(serialized).hexdigest() == _BASELINE_OFFER_SHA256


def _assert_model_visible_result(
    request: LLMRequest,
    call: ToolCallRequest,
    expected: ToolCallResult,
    *,
    structured: bool,
) -> None:
    assert expected.id == call.id and expected.id
    assert expected.output
    if structured:
        assert request.prompt == ""
        assert request.messages is not None
        assistants = [
            message for message in request.messages if message.get("tool_calls")
        ]
        assert len(assistants) == 1
        assert assistants[0]["role"] == "assistant"
        assert assistants[0]["tool_calls"] == [{
            "id": call.id,
            "type": "function",
            "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
        }]
        tool_messages = [
            message for message in request.messages if message["role"] == "tool"
        ]
        assert tool_messages == [{
            "role": "tool", "tool_call_id": expected.id, "content": expected.output,
        }]
    else:
        assert not request.messages
        marker = f"[tool_result:{expected.id} error={expected.is_error}]\n"
        assert request.prompt.count(marker) == 1
        assert request.prompt.endswith(marker + expected.output)


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_self_query_offer_preserves_independent_baseline_and_appends_last(
    enabled: bool, shipped_config: SystemConfig,
    self_query_telemetry: _FakeSelfQueryTelemetry, repository_root: Path,
) -> None:
    from probos.cognitive import agentic_dispatch as dispatch_module
    from probos.tools import self_query_tool as tool_module

    for module, relative in (
        (dispatch_module, "cognitive/agentic_dispatch.py"),
        (tool_module, "tools/self_query_tool.py"),
    ):
        assert module.__file__ is not None
        assert Path(module.__file__).resolve() == (
            repository_root / "src" / "probos" / relative
        ).resolve()
    before = shipped_config.model_dump()
    shipped_config.agentic_tools.self_query_enabled = enabled
    before["agentic_tools"]["self_query_enabled"] = enabled
    assert shipped_config.model_dump() == before
    runtime = _FakeSelfQueryRuntime(config=shipped_config, telemetry=self_query_telemetry)
    runtime.refuse_telemetry_access = not enabled
    llm = _ScriptedSelfQueryLLM()

    outcome = await _run_self_query_fixture(runtime, llm)

    assert outcome.final_text == "baseline-complete"
    assert outcome.stopped_reason == "complete"
    assert len(llm.requests) == 1
    definitions = llm.requests[0].tools
    assert definitions is not None
    _assert_baseline_offer(definitions[:-1] if enabled else definitions)
    assert self_query_telemetry.calls == []
    assert runtime.telemetry_accesses == int(enabled)
    registration = runtime.tool_registry.get("self_query")
    if enabled:
        assert len(definitions) == len(_BASELINE_OFFER_NAMES) + 1
        assert definitions[-1]["function"]["name"] == "self_query"
        assert registration is not None
        assert isinstance(registration.tool, SelfQueryTool)
        assert definitions[-1]["function"]["parameters"] == registration.tool.input_schema
        assert definitions[-1]["function"]["parameters"]["properties"]["domains"]["items"][
            "enum"
        ] == list(SELF_QUERY_DOMAINS)
        assert registration.provider == "AD-1258"
        assert registration.tags == ["self_query", "introspection"]
        assert registration.default_permissions == {}
    else:
        assert registration is None


@pytest.mark.asyncio
async def test_self_query_registration_is_idempotent_and_off_skips_service_access(
    shipped_config: SystemConfig, self_query_telemetry: _FakeSelfQueryTelemetry,
) -> None:
    runtime = _FakeSelfQueryRuntime(config=shipped_config, telemetry=self_query_telemetry)
    first = _ScriptedSelfQueryLLM()
    assert (await _run_self_query_fixture(runtime, first)).stopped_reason == "complete"
    registration = runtime.tool_registry.get("self_query")
    assert registration is not None
    assert runtime.tool_registry.list_ids()[-2:] == ["delegate_task", "self_query"]
    assert runtime.telemetry_accesses == 1
    runtime.refuse_telemetry_access = True
    second = _ScriptedSelfQueryLLM()

    assert (await _run_self_query_fixture(runtime, second)).stopped_reason == "complete"

    assert runtime.tool_registry.get("self_query") is registration
    assert runtime.telemetry_accesses == 1
    assert second.requests[0].tools == first.requests[0].tools
    runtime.config.agentic_tools.self_query_enabled = False
    disabled = _ScriptedSelfQueryLLM()
    assert (await _run_self_query_fixture(runtime, disabled)).stopped_reason == "complete"
    assert disabled.requests[0].tools is not None
    _assert_baseline_offer(disabled.requests[0].tools)
    assert runtime.telemetry_accesses == 1
    assert self_query_telemetry.calls == []


@pytest.mark.asyncio
async def test_self_query_missing_registry_does_not_resolve_service(
    shipped_config: SystemConfig, self_query_telemetry: _FakeSelfQueryTelemetry,
) -> None:
    runtime = _FakeSelfQueryRuntime(config=shipped_config, telemetry=self_query_telemetry)
    runtime.tool_registry = None
    runtime.refuse_telemetry_access = True
    llm = _ScriptedSelfQueryLLM()

    outcome = await _run_self_query_fixture(runtime, llm)

    assert outcome.stopped_reason == "complete"
    assert len(llm.requests) == 1
    assert llm.requests[0].tools == []
    assert runtime.telemetry_accesses == 0
    assert self_query_telemetry.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_site", ["registration", "service-resolution"])
async def test_self_query_registration_failure_preserves_other_offers(
    failure_site: str, shipped_config: SystemConfig,
    self_query_telemetry: _FakeSelfQueryTelemetry,
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    runtime = _FakeSelfQueryRuntime(config=shipped_config, telemetry=self_query_telemetry)
    registry = runtime.tool_registry
    original_register = registry.register
    registration_attempts: list[str] = []

    def register(tool: Tool, **kwargs: Any) -> ToolRegistration:
        if tool.tool_id == "self_query":
            registration_attempts.append(tool.tool_id)
            raise RuntimeError(_PRIVATE_FAILURE)
        return original_register(tool, **kwargs)

    if failure_site == "registration":
        monkeypatch.setattr(registry, "register", register)
    else:
        runtime.refuse_telemetry_access = True
    llm = _ScriptedSelfQueryLLM()

    outcome = await _run_self_query_fixture(runtime, llm)

    assert outcome.stopped_reason == "complete"
    assert llm.requests[0].tools is not None
    _assert_baseline_offer(llm.requests[0].tools)
    assert registry.get("self_query") is None
    assert runtime.telemetry_accesses == 1
    assert registration_attempts == (["self_query"] if failure_site == "registration" else [])
    assert self_query_telemetry.calls == []
    assert "continuing with the other tools without self_query" in caplog.text
    assert _PRIVATE_FAILURE not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [True, False], ids=["structured", "legacy"])
async def test_loop_self_query_returns_context_identity_to_model(
    structured: bool, shipped_config: SystemConfig,
    self_query_telemetry: _FakeSelfQueryTelemetry,
) -> None:
    shipped_config.agentic_loop.structured_tool_messages = structured
    runtime = _FakeSelfQueryRuntime(config=shipped_config, telemetry=self_query_telemetry)
    hostile = {
        "agent_id": "other-agent", "department": "security",
        "rank": "senior_officer", "thread_id": "hostile-thread",
    }
    original_hostile = dict(hostile)
    assert self_query_telemetry.snapshots["baseline-agent"]["social"] != (
        self_query_telemetry.snapshots["other-agent"]["social"]
    )
    call = ToolCallRequest(
        name="self_query", arguments={"domains": ["social"]}, id="self-query-subject",
    )
    expected = ToolCallResult(
        id=call.id, output=str(_query_output(self_query_telemetry, ["social"])),
    )

    def inspect_result(request: LLMRequest) -> None:
        assert self_query_telemetry.calls == [("social", "baseline-agent")]
        _assert_model_visible_result(request, call, expected, structured=structured)
        assert "baseline-agent_unique_social_probe" in expected.output
        assert "other-agent_unique_social_probe" not in expected.output

    llm = _ScriptedSelfQueryLLM(call=call, inspect_result=inspect_result)

    outcome = await _run_self_query_fixture(runtime, llm, extra_context=hostile)

    assert outcome.final_text == "baseline-complete"
    assert outcome.stopped_reason == "complete"
    assert outcome.denied_tools == []
    assert llm.inspected and len(llm.requests) == 2
    assert llm.requests[0].tools is not None
    assert llm.requests[0].tools[-1]["function"]["name"] == "self_query"
    assert hostile == original_hostile
    assert self_query_telemetry.calls == [("social", "baseline-agent")]


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [True, False], ids=["structured", "legacy"])
@pytest.mark.parametrize("reason", ["subject-parameter", "captain-restriction", "unavailable"])
async def test_loop_self_query_errors_reach_model_without_telemetry_reads(
    structured: bool, reason: str, shipped_config: SystemConfig,
    self_query_telemetry: _FakeSelfQueryTelemetry,
) -> None:
    shipped_config.agentic_loop.structured_tool_messages = structured
    runtime = _FakeSelfQueryRuntime(
        config=shipped_config,
        telemetry=None if reason == "unavailable" else self_query_telemetry,
    )
    params: dict[str, Any] = {"domains": ["social"]}
    if reason == "subject-parameter":
        params["subject"] = "other-agent"
        error = "self_query: unknown parameter(s) subject. Accepted: domains."
    elif reason == "captain-restriction":
        grant = await runtime.tool_permission_store.issue_grant(
            "baseline-agent", "self_query", ToolPermission.NONE, is_restriction=True,
        )
        assert grant.is_restriction and grant.issued_by == "captain"
        assert runtime.tool_permission_store.get_active_grants_sync(
            "baseline-agent", "self_query",
        ) == [grant]
        error = (
            "Tool self_query failed: Agent baseline-agent has none on self_query, "
            "needs read"
        )
    else:
        error = "self_query: telemetry service unavailable."
    call = ToolCallRequest(name="self_query", arguments=params, id="self-query-error")
    expected = ToolCallResult(id=call.id, output=error, is_error=True)

    def inspect_result(request: LLMRequest) -> None:
        assert self_query_telemetry.calls == []
        _assert_model_visible_result(request, call, expected, structured=structured)

    llm = _ScriptedSelfQueryLLM(call=call, inspect_result=inspect_result)

    outcome = await _run_self_query_fixture(runtime, llm)

    assert outcome.stopped_reason == "complete"
    assert outcome.final_text == "baseline-complete"
    assert llm.inspected and len(llm.requests) == 2
    assert self_query_telemetry.calls == []
    assert runtime.tool_registry.get("self_query") is not None
    assert llm.requests[0].tools is not None
    offered = [definition["function"]["name"] for definition in llm.requests[0].tools]
    if reason == "captain-restriction":
        assert "self_query" not in offered
        assert outcome.denied_tools == ["self_query"]
        assert runtime.tool_registry.resolve_permission(
            "baseline-agent", "self_query", agent_department="science",
            agent_rank="lieutenant",
        ) is ToolPermission.NONE
    else:
        assert offered[-1] == "self_query"
        assert outcome.denied_tools == []


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [True, False], ids=["structured", "legacy"])
async def test_loop_self_query_cancellation_propagates_before_next_model_request(
    structured: bool, shipped_config: SystemConfig,
    self_query_telemetry: _FakeSelfQueryTelemetry,
) -> None:
    shipped_config.agentic_loop.structured_tool_messages = structured
    runtime = _FakeSelfQueryRuntime(config=shipped_config, telemetry=self_query_telemetry)
    error = asyncio.CancelledError("stop this run")
    self_query_telemetry.failure = ("social", error)
    call = ToolCallRequest(
        name="self_query", arguments={"domains": ["social"]}, id="self-query-cancel",
    )
    llm = _ScriptedSelfQueryLLM(call=call)

    with pytest.raises(asyncio.CancelledError) as caught:
        await _run_self_query_fixture(runtime, llm)

    assert caught.value is error
    assert self_query_telemetry.calls == [("social", "baseline-agent")]
    assert len(llm.requests) == 1
    assert not llm.inspected


def _consumer_telemetry_runtime(
    subject: str,
) -> tuple[SimpleNamespace, dict[str, int], _FakeTrustNetwork]:
    calls = {"hebbian": 0, "trust_events": 0}
    trust = _FakeTrustNetwork(
        scores={subject: 0.512375},
        events=[_FakeTrustEvent(subject, "consumer_social_marker", 0.5124)],
        calls=calls,
    )
    runtime = SimpleNamespace(
        config=SystemConfig(),
        registry=None,
        episodic_memory=None,
        trust_network=trust,
        hebbian_router=_FakeHebbianRouter(
            weights={
                ("consumer_social_marker", subject, "routing"): 0.876543,
                ("another_subject_marker", "another-agent", "routing"): 0.99,
            },
            calls=calls,
        ),
        is_cold_start=False,
    )
    runtime._introspective_telemetry = IntrospectiveTelemetryService(runtime=runtime)
    return runtime, calls, trust


@pytest.mark.asyncio
@pytest.mark.parametrize("intent", ["direct_message", "ward_room_notification"])
async def test_collected_social_reaches_conversational_prompt(intent: str) -> None:
    from tests.test_ad588_telemetry_introspection import _make_cognitive_agent

    subject = "consumer-agent"
    runtime, calls, trust = _consumer_telemetry_runtime(subject)
    agent = _make_cognitive_agent(agent_id=subject, runtime=runtime)
    text = "How is your trust score?"
    assert agent._is_introspective_query(text)
    observation = {
        "intent": intent,
        "params": {
            "text": text,
            "title": "Self report",
            "channel_name": "bridge",
            "author_callsign": "Captain",
        },
        "context": "",
    }
    assert calls == {"hebbian": 0, "trust_events": 0}

    prompt = await agent._build_user_message(observation)

    assert calls == {"hebbian": 1, "trust_events": 2}
    assert trust.score_subjects == [subject]
    assert trust.record_subjects == [subject]
    assert trust.event_queries == [(subject, 5), (subject, 20)]
    assert "Trust: 0.5124\n" in prompt
    assert "consumer_social_marker (0.8765)" in prompt
    assert "interaction breadth: 1" in prompt
    assert "another_subject_marker" not in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("consumer", ["analyze", "compose"])
async def test_query_collected_social_reaches_prompt(consumer: str) -> None:
    from probos.cognitive.sub_task import SubTaskSpec, SubTaskType
    from probos.cognitive.sub_tasks.analyze import _build_thread_analysis_prompt
    from probos.cognitive.sub_tasks.compose import _build_user_prompt
    from probos.cognitive.sub_tasks.query import QueryHandler

    subject = "query-consumer-agent"
    runtime, calls, trust = _consumer_telemetry_runtime(subject)
    context = {
        "params": {"title": "How is your trust score?", "text": ""},
        "_agent_id": "transient-agent",
        "sovereign_id": subject,
        "context": "Thread content",
        "_agent_type": "agent",
        "_agent_rank": None,
        "_skill_profile": None,
        "_formatted_memories": "",
    }
    spec = SubTaskSpec(
        sub_task_type=SubTaskType.QUERY,
        name="query-introspective-telemetry",
        context_keys=("introspective_telemetry",),
    )
    assert calls == {"hebbian": 0, "trust_events": 0}

    result = await QueryHandler(runtime)(spec, context, [])
    if consumer == "analyze":
        _, prompt = _build_thread_analysis_prompt(context, [result], "Analyst", "Science")
    else:
        prompt = _build_user_prompt(context, [result])

    assert result.success and result.sub_task_type is SubTaskType.QUERY
    assert result.tokens_used == 0
    assert calls == {"hebbian": 1, "trust_events": 2}
    assert trust.score_subjects == [subject]
    assert trust.record_subjects == [subject]
    assert trust.event_queries == [(subject, 5), (subject, 20)]
    assert "consumer_social_marker (0.8765)" in result.result["introspective_telemetry"]
    assert "Trust: 0.5124\n" in prompt
    assert "consumer_social_marker (0.8765)" in prompt
    assert "interaction breadth: 1" in prompt
    assert "another_subject_marker" not in prompt


@pytest.mark.asyncio
async def test_proactive_collected_social_reaches_think_prompt() -> None:
    from probos.proactive import ProactiveCognitiveLoop
    from tests.test_ad588_telemetry_introspection import _make_cognitive_agent

    subject = "proactive-consumer-agent"
    runtime, calls, trust = _consumer_telemetry_runtime(subject)
    agent = _make_cognitive_agent(agent_id=subject, runtime=runtime)
    loop = ProactiveCognitiveLoop()
    loop.set_runtime(runtime)
    assert calls == {"hebbian": 0, "trust_events": 0}

    context_parts = await loop._gather_context(agent, 0.5124)
    prompt = await agent._build_user_message({
        "intent": "proactive_think",
        "params": {"context_parts": context_parts},
    })

    assert calls == {"hebbian": 1, "trust_events": 2}
    # Self-monitoring and telemetry each read this agent's trust.
    assert trust.score_subjects == [subject, subject]
    assert trust.record_subjects == [subject]
    assert trust.event_queries == [(subject, 5), (subject, 20)]
    assert "consumer_social_marker (0.8765)" in context_parts["introspective_telemetry"]
    assert "Trust: 0.5124\n" in prompt
    assert "consumer_social_marker (0.8765)" in prompt
    assert "interaction breadth: 1" in prompt
    assert "another_subject_marker" not in prompt