"""AD-1260/1261: explicit subject-bound telemetry, using stored local services."""

from __future__ import annotations

import asyncio
import inspect
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive import introspective_telemetry as telemetry_module
from probos.cognitive import self_telemetry_domains as domain_module
from probos.cognitive.counselor import CounselorAgent, CounselorAssessment
from probos.cognitive.decomposer import is_capability_gap
from probos.config import SystemConfig, format_trust
from probos.ontology.departments import DepartmentService
from probos.ontology.models import Assignment, Department, Post
from probos.substrate.registry import AgentRegistry
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolResult, ToolResultPresentation, ToolType
from probos.tools.registry import ToolRegistry
from probos.tools.self_query_tool import SELF_QUERY_DOMAINS, SelfQueryTool

_NOW = 1_800_000_000.125
_SUBJECT = "self-subject"
_OTHER = "other-subject"
_PRIVATE = "CAPTAIN-CLINICAL-SENTINEL"
_PEER = "OTHER-CLINICAL-SENTINEL"
_OMISSION_NOTICE = (
    "Presentation omissions: valid source information is absent from this "
    "projection; counts do not restore it. "
    "No alternative retrieval mechanism is promised."
)


class _NoLiveLLM:
    async def complete(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("This fixture must only read stored assessments")


class _FakeTrust:
    def __init__(self) -> None:
        self.scores = {_SUBJECT: 0.723456, _OTHER: 0.95}
        self.subjects: list[str] = []

    def get_score(self, agent_id: str) -> float:
        self.subjects.append(agent_id)
        return self.scores[agent_id]

    def get_record(self, agent_id: str) -> None:
        return None

    def get_events_for_agent(self, agent_id: str, n: int = 5) -> list[Any]:
        return []

    def all_scores(self) -> dict[str, float]:
        return dict(self.scores)


class _FakeRouter:
    def all_weights_typed(self) -> dict[tuple[str, str, str], float]:
        return {}


class _FakeCatalogTool:
    name = "Local fixture"
    tool_type = ToolType.DETERMINISTIC_FUNCTION
    description = "Controlled catalog entry."

    def __init__(self, tool_id: str) -> None:
        self.tool_id = tool_id
        self.input_schema = {"type": "object"}
        self.output_schema = {"type": "object"}

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> ToolResult:
        raise AssertionError("Catalog entries must not execute")


class _FakeRuntime(SimpleNamespace):
    def get_uptime_seconds(self) -> float:
        return 7200.0

    @property
    def _introspective_telemetry(self) -> Any:
        return self.introspective_telemetry


def _assert_candidate_origins() -> None:
    from probos.cognitive import agentic_dispatch, counselor, decomposer
    from probos.cognitive.swe_harness import agentic_loop, tool_call
    from probos.tools import registry, self_query_tool

    root = Path(__file__).resolve().parents[1]
    for module in (
        telemetry_module, domain_module, agentic_dispatch, counselor, decomposer,
        agentic_loop, tool_call, registry, self_query_tool,
    ):
        assert module.__file__ is not None
        assert Path(module.__file__).resolve().is_relative_to(root / "src" / "probos")
    assert Path(inspect.getfile(_make_runtime)).resolve() == (
        root / "tests" / "test_ad1260_wellness_domain.py"
    )


@pytest.fixture(autouse=True)
def candidate_origins() -> None:
    _assert_candidate_origins()


async def _make_runtime() -> _FakeRuntime:
    counselor = CounselorAgent(
        agent_id=_SUBJECT, pool="counselor", llm_client=_NoLiveLLM(),
    )
    other = CounselorAgent(agent_id=_OTHER, pool="crew", llm_client=_NoLiveLLM())
    registry = AgentRegistry()
    await registry.register(counselor)
    await registry.register(other)
    profile = counselor.get_or_create_profile(_SUBJECT, counselor.agent_type)
    profile.confabulation_rate = 0.012345
    profile.memory_integrity_score = 0.987654
    profile.add_assessment(CounselorAssessment(
        agent_id=_SUBJECT, timestamp=_NOW - 172800.5,
        wellness_score=0.812345, trust_drift=-0.012345,
        confidence_drift=0.023456, hebbian_drift=-0.034567,
        concerns=["Stored self concern"], recommendations=[_PRIVATE], notes=_PRIVATE,
        fit_for_duty=False, fit_for_promotion=True, personality_drift=0.6,
    ))
    counselor.get_or_create_profile(_OTHER).add_assessment(CounselorAssessment(
        agent_id=_OTHER, timestamp=_NOW, wellness_score=0.2,
        concerns=[_PEER], recommendations=[_PRIVATE], notes=_PRIVATE,
    ))
    posts = {
        "counselor-post": Post("counselor-post", "Counselor", "science", "science-chief"),
        "science-chief": Post(
            "science-chief", "Science Chief", "science", "captain",
            authority_over=["counselor-post"],
        ),
        "captain": Post("captain", "Captain", "command", None, ["science-chief"]),
    }
    ontology = DepartmentService(
        {"science": Department("science", "Science", "Local fixture")},
        posts, {"counselor": Assignment("counselor", "counselor-post", "Counselor")},
    )
    tools = ToolRegistry()
    permissions = ToolPermissionStore()
    tools.set_permission_store(permissions)
    runtime = _FakeRuntime(
        config=SystemConfig(), registry=registry, counselor=counselor, profile=profile,
        ontology=ontology, posts=posts, trust_network=_FakeTrust(),
        hebbian_router=_FakeRouter(), tool_registry=tools,
        tool_permission_store=permissions, episodic_memory=None,
        intent_bus=object(), intent_grant_store=None, mcp_workbench=None,
        attachment_store=None, artifact_store=None, cognitive_skill_catalog=None,
        emit_event=None, pools={}, is_cold_start=False, work_item_store=None,
    )
    runtime.config.agentic_tools.self_query_enabled = True
    runtime.introspective_telemetry = telemetry_module.IntrospectiveTelemetryService(
        runtime=runtime,
    )
    return runtime


@pytest.fixture
async def domain_runtime(monkeypatch: pytest.MonkeyPatch) -> _FakeRuntime:
    monkeypatch.setattr(domain_module.time, "time", lambda: _NOW)
    return await _make_runtime()


class TestWellnessContract:
    async def test_get_wellness_state_stored_whitelist_and_stale_age(
        self, domain_runtime: _FakeRuntime,
    ) -> None:
        result = await domain_runtime.introspective_telemetry.get_wellness_state(_SUBJECT)
        assert set(result) == {
            "wellness_score", "fit_for_duty", "concerns", "trust_drift",
            "confidence_drift", "hebbian_drift", "assessed_at", "alert_level",
            "confabulation_rate", "memory_integrity_score", "trust_drift_trend", "coverage",
        }
        assert result["wellness_score"] == format_trust(0.812345)
        assert result["trust_drift_trend"] == format_trust(-0.012345)
        assert result["assessed_at"] == _NOW - 172800.5
        assert result["fit_for_duty"] is False
        assert result["alert_level"] == "red"
        rendered = telemetry_module.IntrospectiveTelemetryService.render_telemetry_context(
            {"wellness": result},
        )
        assert "assessment age: 48.0001h" in rendered
        assert str(result["wellness_score"]) in rendered
        assert _PRIVATE not in str(result) + rendered
        assert _PEER not in str(result) + rendered
        assert not is_capability_gap(rendered)

    @pytest.mark.parametrize("concerns", [[], ["x" * 300] * 5])
    async def test_get_wellness_state_concern_caps_count_all_omissions(
        self, domain_runtime: _FakeRuntime, concerns: list[str],
    ) -> None:
        domain_runtime.profile.latest_assessment().concerns = concerns
        result = await domain_runtime.introspective_telemetry.get_wellness_state(_SUBJECT)
        assert result["concerns"] == [text[:256] for text in concerns[:3]]
        # R1 replaces coverage without completeness: omitted text is partial data.
        assert result["coverage"] == {
            "concerns_total": len(concerns),
            "concerns_omitted": max(0, len(concerns) - 3),
            "concern_characters_omitted": sum(map(len, concerns))
            - sum(map(len, result["concerns"])),
            "complete": len(concerns) <= 3 and all(len(text) <= 256 for text in concerns),
        }
        assert domain_runtime.profile.latest_assessment().concerns == concerns

    async def test_get_wellness_state_no_assessment_has_profile_fields_only(
        self, domain_runtime: _FakeRuntime,
    ) -> None:
        domain_runtime.profile.assessments.clear()
        result = await domain_runtime.introspective_telemetry.get_wellness_state(_SUBJECT)
        assert result == {
            "alert_level": "red", "confabulation_rate": 0.0123,
            "memory_integrity_score": 0.9877,
        }
        rendered = domain_runtime.introspective_telemetry.render_telemetry_context(
            {"wellness": result},
        )
        assert "assessment age: unknown" in rendered
        assert not is_capability_gap(rendered)

    @pytest.mark.parametrize("timestamp", [None, float("nan"), float("inf"), 0, _NOW + 1])
    async def test_get_wellness_state_invalid_age_never_implies_freshness(
        self, domain_runtime: _FakeRuntime, timestamp: Any,
    ) -> None:
        domain_runtime.profile.latest_assessment().timestamp = timestamp
        result = await domain_runtime.introspective_telemetry.get_wellness_state(_SUBJECT)
        rendered = domain_runtime.introspective_telemetry.render_telemetry_context(
            {"wellness": result},
        )
        assert "assessment age: unknown" in rendered
        if timestamp is None or timestamp in (float("inf"),) or timestamp != timestamp:
            assert "assessed_at" not in result
        else:
            assert result["assessed_at"] == timestamp

    @pytest.mark.parametrize("case", ["missing", "empty", "method", "profile", "read", "id"])
    async def test_get_wellness_state_absence_or_failure_has_no_clinical_leak(
        self, domain_runtime: _FakeRuntime, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture, case: str,
    ) -> None:
        subject = _SUBJECT
        if case == "missing":
            domain_runtime.registry = None
        elif case == "empty":
            await domain_runtime.registry.unregister(_SUBJECT)
        elif case == "method":
            monkeypatch.setattr(domain_runtime.counselor, "get_profile", None)
        elif case == "profile":
            subject = "not-profiled"
        elif case == "id":
            subject = None
        else:
            def fail(agent_id: str) -> None:
                raise RuntimeError(_PRIVATE)
            monkeypatch.setattr(domain_runtime.counselor, "get_profile", fail)
        assert await domain_runtime.introspective_telemetry.get_wellness_state(subject) == {}
        assert _PRIVATE not in caplog.text
        if case == "read":
            assert "assessment is unknown" in caplog.text

    @pytest.mark.parametrize("domains", [None, list(SELF_QUERY_DOMAINS), ["trust"]])
    async def test_self_query_original_domains_never_access_optional_getters(
        self, domains: list[str] | None,
    ) -> None:
        class OldTelemetry:
            def __getattr__(self, name: str) -> Any:
                raise AssertionError(f"Unexpected getter access: {name}")

            async def get_full_snapshot(self, agent_id: str) -> dict[str, Any]:
                return {domain: {} for domain in SELF_QUERY_DOMAINS}

            async def get_trust_state(self, agent_id: str) -> dict[str, Any]:
                return {}

            @staticmethod
            def render_telemetry_context(snapshot: dict[str, Any]) -> str:
                return "old-only"

        result = await SelfQueryTool(telemetry=OldTelemetry()).invoke(
            {} if domains is None else {"domains": domains}, {"agent_id": _SUBJECT},
        )
        assert result.success
        assert result.output["rendered"] == "old-only"
        assert list(result.output["domains"]) == (domains or list(SELF_QUERY_DOMAINS))

    @pytest.mark.parametrize("extra", [(), ("wellness",), ("wellness", "authority")])
    async def test_get_full_snapshot_extras_are_explicit_and_independent(
        self, domain_runtime: _FakeRuntime, extra: tuple[str, ...],
    ) -> None:
        snapshot = await domain_runtime.introspective_telemetry.get_full_snapshot(
            _SUBJECT, extra_domains=extra,
        )
        assert list(snapshot) == [*SELF_QUERY_DOMAINS, *extra]
        for domain in extra:
            assert snapshot[domain]

    @pytest.mark.parametrize("failure", [RuntimeError(_PRIVATE), asyncio.CancelledError()])
    async def test_get_full_snapshot_optional_failure_preserves_other_domains_or_cancellation(
        self, domain_runtime: _FakeRuntime, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture, failure: BaseException,
    ) -> None:
        async def fail(agent_id: str) -> dict[str, Any]:
            raise failure
        service = domain_runtime.introspective_telemetry
        monkeypatch.setattr(service, "get_wellness_state", fail)
        if isinstance(failure, asyncio.CancelledError):
            with pytest.raises(asyncio.CancelledError):
                await service.get_full_snapshot(_SUBJECT, extra_domains=("wellness",))
        else:
            result = await service.get_full_snapshot(
                _SUBJECT, extra_domains=("wellness", "authority"),
            )
            assert list(result) == [*SELF_QUERY_DOMAINS, "wellness", "authority"]
            assert result["wellness"] == {} and result["authority"]
        assert _PRIVATE not in caplog.text

    @pytest.mark.parametrize("extra", [None, [], ("wellness", None)])
    async def test_get_full_snapshot_malformed_extras_rejected(
        self, domain_runtime: _FakeRuntime, extra: Any,
    ) -> None:
        with pytest.raises(ValueError, match="tuple of strings"):
            await domain_runtime.introspective_telemetry.get_full_snapshot(
                _SUBJECT, extra_domains=extra,
            )

    @pytest.mark.parametrize("parameter", ["agent_id", "subject", "agent_type"])
    async def test_self_query_subject_parameters_rejected_before_collection(
        self, domain_runtime: _FakeRuntime, monkeypatch: pytest.MonkeyPatch,
        parameter: str,
    ) -> None:
        def unexpected(agent_id: str) -> None:
            pytest.fail("Rejected subject reached the Counselor")
        monkeypatch.setattr(domain_runtime.counselor, "get_profile", unexpected)
        result = await SelfQueryTool(telemetry=domain_runtime.introspective_telemetry).invoke(
            {"domains": ["wellness", "authority"], parameter: _OTHER},
            {"agent_id": _SUBJECT},
        )
        assert result.error == (
            f"self_query: unknown parameter(s) {parameter}. Accepted: domains."
        )
        assert domain_runtime.trust_network.subjects == []

    async def test_self_query_exact_subject_crosses_stored_profile_to_rendering(
        self, domain_runtime: _FakeRuntime,
    ) -> None:
        before = deepcopy(domain_runtime.profile.to_dict())
        result = await SelfQueryTool(telemetry=domain_runtime.introspective_telemetry).invoke(
            {"domains": ["wellness"]},
            {"agent_id": _SUBJECT, "subject": _OTHER, "agent_type": "other"},
        )
        assert result.success and result.output["agent_id"] == _SUBJECT
        assert list(result.output["domains"]) == ["wellness"]
        assert "0.8123" in result.output["rendered"]
        assert _PEER not in str(result.output) and _PRIVATE not in str(result.output)
        assert domain_runtime.profile.to_dict() == before
        exact = await SelfQueryTool(telemetry=domain_runtime.introspective_telemetry).invoke(
            {"domains": ["wellness"]}, {"agent_id": f" {_SUBJECT} "},
        )
        assert exact.output["agent_id"] == f" {_SUBJECT} "
        assert exact.output["domains"] == {"wellness": {}}

    async def test_get_wellness_state_cancellation_propagates(
        self, domain_runtime: _FakeRuntime, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def cancel(agent_id: str) -> None:
            raise asyncio.CancelledError()
        monkeypatch.setattr(domain_runtime.counselor, "get_profile", cancel)
        with pytest.raises(asyncio.CancelledError):
            await domain_runtime.introspective_telemetry.get_wellness_state(_SUBJECT)

    async def test_agent_info_populated_optional_domains_preserve_third_person_keys(
        self, domain_runtime: _FakeRuntime, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from probos.agents.introspect import IntrospectionAgent

        service = domain_runtime.introspective_telemetry
        populated = await service.get_full_snapshot(
            _SUBJECT, extra_domains=("wellness", "authority"),
        )
        assert populated["wellness"] and populated["authority"]
        base_keys = set(domain_runtime.counselor.info())
        async def unexpected(agent_id: str) -> dict[str, Any]:
            pytest.fail("Third-person query read an optional domain")
        monkeypatch.setattr(service, "get_wellness_state", unexpected)
        monkeypatch.setattr(service, "get_authority_state", unexpected)

        result = await IntrospectionAgent(runtime=domain_runtime).act({
            "action": "agent_info", "params": {"agent_id": _SUBJECT},
        })

        assert result["success"] is True
        assert set(result) == {"success", "data"}
        assert set(result["data"]) == {"agents"}
        assert len(result["data"]["agents"]) == 1
        info = result["data"]["agents"][0]
        assert set(info) == base_keys | {"trust_score", "hebbian"}
        assert set(info["hebbian"]) == {"incoming_top3", "outgoing_top3", "total_connections"}
        assert "wellness" not in info and "authority" not in info
        assert _PRIVATE not in str(result) and _PEER not in str(result)
        default = await service.get_full_snapshot(_SUBJECT)
        assert list(default) == list(SELF_QUERY_DOMAINS)


class _OriginalFiveTelemetry:
    """Independent old collector contract; no optional keys are collected or filtered."""

    def __init__(self, service: telemetry_module.IntrospectiveTelemetryService) -> None:
        self.service = service

    async def get_full_snapshot(self, agent_id: str) -> dict[str, Any]:
        return {
            "memory": await self.service.get_memory_state(agent_id),
            "trust": await self.service.get_trust_state(agent_id),
            "cognitive": await self.service.get_cognitive_state(agent_id),
            "temporal": await self.service.get_temporal_state(agent_id),
            "social": await self.service.get_social_state(agent_id),
        }

    @staticmethod
    def render_telemetry_context(snapshot: dict[str, Any]) -> str:
        assert list(snapshot) == ["memory", "trust", "cognitive", "temporal", "social"]
        return telemetry_module.IntrospectiveTelemetryService.render_telemetry_context(snapshot)


class _FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz: Any = None) -> datetime:
        value = datetime.fromtimestamp(_NOW, tz=timezone.utc)
        return value if tz is not None else value.replace(tzinfo=None)


async def _passive_output(runtime: _FakeRuntime, site: str) -> Any:
    from tests import test_ad588_telemetry_introspection as fixture_module

    assert Path(fixture_module.__file__).resolve() == (
        Path(__file__).resolve().parent / "test_ad588_telemetry_introspection.py"
    )
    agent = fixture_module._make_cognitive_agent(agent_id=_SUBJECT, runtime=runtime)
    if site in ("direct_message", "ward_room_notification"):
        return await agent._build_user_message({
            "intent": site,
            "params": {
                "text": "How is your trust score?", "title": "Self report",
                "channel_name": "bridge", "author_callsign": "Captain",
            },
            "context": "",
        })
    if site == "proactive":
        from probos.proactive import ProactiveCognitiveLoop
        loop = ProactiveCognitiveLoop()
        loop.set_runtime(runtime)
        parts = await loop._gather_context(agent, 0.7235)
        return parts, await agent._build_user_message({
            "intent": "proactive_think", "params": {"context_parts": parts},
        })
    from probos.cognitive.sub_task import SubTaskSpec, SubTaskType
    from probos.cognitive.sub_tasks.analyze import _build_thread_analysis_prompt
    from probos.cognitive.sub_tasks.compose import _build_user_prompt
    from probos.cognitive.sub_tasks.query import QueryHandler
    context = {
        "params": {"title": "How is your trust score?", "text": ""},
        "_agent_id": "transient-slot", "sovereign_id": _SUBJECT,
        "context": "Thread content", "_agent_type": "counselor",
        "_agent_rank": None, "_skill_profile": None, "_formatted_memories": "",
    }
    spec = SubTaskSpec(
        sub_task_type=SubTaskType.QUERY, name="query-introspective-telemetry",
        context_keys=("introspective_telemetry",),
    )
    result = await QueryHandler(runtime)(spec, context, [])
    assert result.success
    if site == "query-analyze":
        _, prompt = _build_thread_analysis_prompt(context, [result], "Counselor", "Science")
    else:
        prompt = _build_user_prompt(context, [result])
    return result.result, prompt


@pytest.mark.parametrize(
    "site", ["direct_message", "ward_room_notification", "proactive", "query-analyze", "query-compose"],
)
async def test_passive_consumers_populated_extras_preserve_complete_original_output(
    domain_runtime: _FakeRuntime, monkeypatch: pytest.MonkeyPatch, site: str,
) -> None:
    monkeypatch.setattr(telemetry_module, "datetime", _FrozenDateTime)
    service = domain_runtime.introspective_telemetry
    explicit = await service.get_full_snapshot(_SUBJECT, extra_domains=("wellness", "authority"))
    assert explicit["wellness"] and explicit["authority"]
    reads: list[str] = []
    async def unexpected(agent_id: str) -> dict[str, Any]:
        reads.append(agent_id)
        pytest.fail("Passive consumer collected an explicit-only domain")
    monkeypatch.setattr(service, "get_wellness_state", unexpected)
    monkeypatch.setattr(service, "get_authority_state", unexpected)
    domain_runtime.introspective_telemetry = _OriginalFiveTelemetry(service)
    baseline = await _passive_output(domain_runtime, site)
    domain_runtime.introspective_telemetry = service

    current = await _passive_output(domain_runtime, site)

    assert current == baseline
    assert "Trust: 0.7235" in str(current)
    assert "Your Telemetry" in str(current)
    assert "Wellness:" not in str(current) and "Authority:" not in str(current)
    assert _PRIVATE not in str(current) and _PEER not in str(current)
    assert reads == []


class _FakeEmptyMemory:
    is_available = True

    async def count_for_agent(self, agent_id: str) -> int:
        return 0

    async def recent_for_agent(self, agent_id: str, k: int) -> list[Any]:
        return []

    async def recall_by_anchor(self, **kwargs: Any) -> list[Any]:
        return []


async def test_profile_and_memory_graph_keep_exact_third_person_projections(
    domain_runtime: _FakeRuntime, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from probos import crew_profile
    from probos.routers import agents, memory_graph

    monkeypatch.setattr(telemetry_module, "datetime", _FrozenDateTime)
    monkeypatch.setattr(memory_graph, "datetime", _FrozenDateTime)
    async def no_seed(agent_type: str) -> None:
        return None
    monkeypatch.setattr(crew_profile, "load_seed_profile_async", no_seed)
    domain_runtime.config = SimpleNamespace(avatars=None)
    domain_runtime.episodic_memory = _FakeEmptyMemory()
    service = domain_runtime.introspective_telemetry
    explicit = await service.get_full_snapshot(_SUBJECT, extra_domains=("wellness", "authority"))
    assert explicit["wellness"] and explicit["authority"]
    async def unexpected(agent_id: str) -> dict[str, Any]:
        pytest.fail("Third-person projection read an optional domain")
    monkeypatch.setattr(service, "get_wellness_state", unexpected)
    monkeypatch.setattr(service, "get_authority_state", unexpected)

    profile = await agents.agent_profile(_SUBJECT, runtime=domain_runtime)
    graph = await memory_graph.get_memory_graph(
        _SUBJECT, runtime=domain_runtime, max_nodes=20, ship_wide=False,
        semantic_k=5, time_range_hours=None,
    )

    assert set(profile) == {
        "id", "sovereignId", "did", "agentType", "callsign", "displayName", "rank",
        "agencyLevel", "department", "personality", "specialization", "trust",
        "trustHistory", "confidence", "state", "tier", "pool", "hebbianConnections",
        "memoryCount", "uptime", "memoryCountMetadata", "uptimeMetadata",
        "voiceProfile", "appearance", "isCrew", "proactiveCooldown", "visionCapable",
    }
    assert profile["memoryCount"] == 0 and profile["uptime"] == 7200.0
    assert set(graph) == {"nodes", "edges", "meta"}
    assert set(graph["meta"]) == {
        "agent_id", "total_episodes", "nodes_shown", "ship_wide",
        "total_measurement", "selection",
    }
    assert graph["nodes"] == graph["edges"] == []
    assert graph["meta"]["total_episodes"] == 0
    assert _PRIVATE not in str(profile) + str(graph)
    assert _PEER not in str(profile) + str(graph)


async def test_explicit_whitelist_does_not_expand_mesh_or_full_clinical_access(
    domain_runtime: _FakeRuntime,
) -> None:
    from probos.cognitive.clinical_access import resolve_clinical_access
    from probos.cognitive.dm.reply_pipeline import _MESH_READ_INTENT_POOLS

    assert _MESH_READ_INTENT_POOLS == {
        "list_directory": "directory", "read_file": "filesystem", "stat_file": "filesystem",
        "search_files": "search", "search_content": "code_search",
        "web_search": "web_search", "read_page": "page_reader",
    }
    result = await SelfQueryTool(telemetry=domain_runtime.introspective_telemetry).invoke(
        {"domains": ["wellness", "authority"]}, {"agent_id": _SUBJECT},
    )
    assert result.success and _PRIVATE not in str(result.output)
    subject = resolve_clinical_access(
        caller_agent_id=_SUBJECT, caller_agent_type="counselor",
        target_agent_id=_SUBJECT, is_captain=False,
    )
    assert subject.allowed is False and subject.source == "subject_denied"
    captain = resolve_clinical_access(
        caller_agent_id="", caller_agent_type="", target_agent_id=_SUBJECT, is_captain=True,
    )
    assert captain.allowed is True and captain.source == "captain"


@pytest.mark.parametrize(
    "concern", ["Unable to maintain focus", "x" * 256 + " Unable to maintain focus"],
    ids=["stored-concern", "match-beyond-character-cap"],
)
async def test_wellness_filter_whole_stored_concern_preserves_totals_and_source(
    domain_runtime: _FakeRuntime, concern: str,
) -> None:
    assert is_capability_gap(concern)
    control = "Significant focus on blackboard 'quotes'\\\n"
    long_control = "Stable attention " + "x" * 270
    concerns = [concern, long_control, control, "Additional stored concern"]
    domain_runtime.profile.latest_assessment().concerns = concerns
    source = deepcopy(domain_runtime.profile.to_dict())

    state = await domain_runtime.introspective_telemetry.get_wellness_state(_SUBJECT)

    assert state["concerns"] == [long_control[:256], control]
    assert state["coverage"] == {
        "concerns_total": 4, "concerns_omitted": 2,
        "concern_characters_omitted": sum(map(len, concerns))
        - sum(map(len, state["concerns"])),
        "complete": False,
    }
    assert not is_capability_gap(str(state))
    once = domain_module.filter_optional_domains({"wellness": state})
    assert once == domain_module.filter_optional_domains(once) == {"wellness": state}
    assert await domain_runtime.introspective_telemetry.get_wellness_state(_SUBJECT) == state
    assert domain_runtime.profile.to_dict() == source


@pytest.mark.parametrize("with_control", [False, True])
async def test_wellness_direct_render_shares_filter_without_mutating_input(
    domain_runtime: _FakeRuntime, with_control: bool,
) -> None:
    concerns = ["Unable to maintain focus"]
    if with_control:
        concerns.append("Significant focus on blackboard 'quotes'\\\n")
    domain_runtime.profile.latest_assessment().concerns = concerns
    source = deepcopy(domain_runtime.profile.to_dict())
    service = domain_runtime.introspective_telemetry
    collected = await service.get_wellness_state(_SUBJECT)
    raw = deepcopy(collected)
    raw["concerns"] = list(concerns)
    raw["coverage"] = {
        "concerns_total": len(concerns), "concerns_omitted": 0,
        "concern_characters_omitted": 0, "complete": True,
    }
    snapshot = {"wellness": raw}
    before = deepcopy(snapshot)
    assert is_capability_gap(str(snapshot))

    projected = domain_module.filter_optional_domains(snapshot)
    rendered = service.render_telemetry_context(snapshot)

    assert projected == {"wellness": collected}
    assert domain_module.filter_optional_domains(projected) == projected
    assert rendered == service.render_telemetry_context(projected)
    assert not is_capability_gap(rendered)
    # R1 pinned only the first sentence, leaving the retrieval disclaimer untested.
    assert rendered.splitlines().count(_OMISSION_NOTICE) == 1
    assert not is_capability_gap(_OMISSION_NOTICE)
    if with_control:
        assert collected["concerns"] == concerns[1:]
    else:
        assert "Concerns: 0 shown; 1 omitted" in rendered
    assert snapshot == before
    assert domain_runtime.profile.to_dict() == source


@pytest.mark.parametrize("case", ["alert-level", "metadata", "rendered-age"])
async def test_wellness_direct_render_residual_unsafe_value_explicitly_refuses(
    domain_runtime: _FakeRuntime, monkeypatch: pytest.MonkeyPatch, case: str,
) -> None:
    state = await domain_runtime.introspective_telemetry.get_wellness_state(_SUBJECT)
    if case == "alert-level":
        state["alert_level"] = "Unable to maintain focus"
    elif case == "metadata":
        state["coverage"]["source"] = "no tool"
    else:
        assert not is_capability_gap(str(state))
        # The age suffix must not turn the fixture into the non-matching word "toolh".
        assert is_capability_gap("no tool h")
        monkeypatch.setattr(domain_module, "format_trust", lambda _: "no tool ")
    snapshot = {"wellness": state}
    before = deepcopy(snapshot)

    with pytest.raises(ValueError, match="Optional telemetry presentation check failed"):
        domain_module.render_optional_domains(snapshot)

    assert snapshot == before
    assert state["concerns"] == ["Stored self concern"]


@pytest.mark.parametrize("case", ["old-only", "wellness-empty", "wellness-none", "authority-empty", "authority-none"])
def test_filter_optional_domains_empty_and_old_values_are_unchanged(case: str) -> None:
    snapshot: dict[str, Any] = {"trust": {"legacy_fact": "no tool"}}
    if case != "old-only":
        domain, value = case.split("-")
        snapshot[domain] = {} if value == "empty" else None
    before = deepcopy(snapshot)

    projected = domain_module.filter_optional_domains(snapshot)

    assert projected == before == snapshot
    assert projected is not snapshot
    assert projected["trust"] is snapshot["trust"]
    assert domain_module.filter_optional_domains(projected) == projected
    assert domain_module.render_optional_domains(snapshot) == []


async def test_prune_optional_entry_wellness_records_complete_and_exact_characters(
    domain_runtime: _FakeRuntime,
) -> None:
    state = await domain_runtime.introspective_telemetry.get_wellness_state(_SUBJECT)
    before = deepcopy(state)
    assert state["coverage"]["complete"] is True
    snapshot = domain_module.filter_optional_domains({"wellness": state})

    assert domain_module.prune_optional_entry(snapshot) is True

    assert snapshot["wellness"]["concerns"] == []
    assert snapshot["wellness"]["coverage"] == {
        "concerns_total": 1, "concerns_omitted": 1,
        "concern_characters_omitted": len("Stored self concern"), "complete": False,
    }
    after = deepcopy(snapshot)
    assert domain_module.prune_optional_entry(snapshot) is False
    assert domain_module.filter_optional_domains(snapshot) == after == snapshot
    assert state == before


@pytest.mark.parametrize("selection", [None, list(SELF_QUERY_DOMAINS), ["trust"]])
async def test_self_query_old_only_gap_values_keep_exact_envelope_bytes(
    domain_runtime: _FakeRuntime, monkeypatch: pytest.MonkeyPatch,
    selection: list[str] | None,
) -> None:
    from probos.cognitive.swe_harness.tool_call import render_tool_output

    monkeypatch.setattr(telemetry_module, "datetime", _FrozenDateTime)
    service = domain_runtime.introspective_telemetry
    trust = {"score": 0.7235, "legacy_fact": "no tool"}
    async def old_trust(agent_id: str) -> dict[str, Any]:
        assert agent_id == _SUBJECT
        return trust
    monkeypatch.setattr(service, "get_trust_state", old_trust)
    snapshot = (
        {"trust": trust} if selection == ["trust"] else await service.get_full_snapshot(_SUBJECT)
    )
    if "social" in snapshot:
        # The original tool already excludes the Captain-only graph count.
        assert snapshot["social"] == {"total_connections": 0, "interaction_breadth": 0}
        snapshot["social"] = {"interaction_breadth": 0}
    expected = {
        "agent_id": _SUBJECT, "domains": snapshot,
        "rendered": service.render_telemetry_context(snapshot), "unknown_domains": [],
    }
    expected_plain = render_tool_output(expected, max_chars=0)
    assert is_capability_gap(expected_plain)

    result = await SelfQueryTool(telemetry=service).invoke(
        {} if selection is None else {"domains": selection}, {"agent_id": _SUBJECT},
    )

    assert result.success
    assert render_tool_output(result.output, max_chars=0) == expected_plain
    assert result.output["domains"]["trust"] is trust


@pytest.mark.parametrize("budget_delta", [0, -1], ids=["exact-fit", "one-short"])
async def test_self_query_r2_complete_omission_notice_counts_toward_envelope_budget(
    domain_runtime: _FakeRuntime, budget_delta: int,
) -> None:
    from probos.cognitive.swe_harness.tool_call import render_tool_output

    domain_runtime.profile.latest_assessment().concerns = ["Unable to maintain focus"]
    tool = SelfQueryTool(telemetry=domain_runtime.introspective_telemetry)
    params = {"domains": ["wellness"]}
    baseline = await tool.invoke(params, {"agent_id": _SUBJECT})
    assert baseline.success
    assert baseline.output["rendered"].splitlines().count(_OMISSION_NOTICE) == 1
    assert len(_OMISSION_NOTICE) == 154
    assert not is_capability_gap(_OMISSION_NOTICE)
    plain = render_tool_output(baseline.output, max_chars=0)
    assert _OMISSION_NOTICE in plain and not is_capability_gap(plain)
    presentations: list[str] = []

    def admit(value: Any) -> str | None:
        text = render_tool_output(value, max_chars=0)
        presentations.append(text)
        return text if len(text) <= len(plain) + budget_delta else None

    result = await tool.invoke(
        params,
        {"agent_id": _SUBJECT, "_tool_result_presentation": ToolResultPresentation(admit)},
    )

    assert presentations == [plain]
    if budget_delta == 0:
        assert result.success and result.output == baseline.output
    else:
        assert result.output is None
        assert result.error == "self_query: result exceeds the presentation budget."
        assert not is_capability_gap(result.error)


@pytest.mark.parametrize("returned", ["no tool", "x" * 6001, "changed-safe", 123])
async def test_self_query_r2_checks_returned_presentation_text_before_admission(
    domain_runtime: _FakeRuntime, monkeypatch: pytest.MonkeyPatch, returned: Any,
) -> None:
    from probos.cognitive import decomposer

    checked: list[str] = []
    presented: list[dict[str, Any]] = []
    classifier = decomposer.is_capability_gap

    def classify(text: str) -> bool:
        checked.append(text)
        return classifier(text)

    def admit(value: dict[str, Any]) -> Any:
        presented.append(value)
        return returned

    monkeypatch.setattr(decomposer, "is_capability_gap", classify)
    result = await SelfQueryTool(telemetry=domain_runtime.introspective_telemetry).invoke(
        {"domains": ["wellness"]},
        {"agent_id": _SUBJECT, "_tool_result_presentation": ToolResultPresentation(admit)},
    )

    assert len(presented) == 1
    assert result.output is None and result.error == "self_query: presentation check failed."
    assert not classifier(result.error)
    if type(returned) is str and len(returned) <= 6000:
        assert returned in checked
    else:
        assert returned not in checked
