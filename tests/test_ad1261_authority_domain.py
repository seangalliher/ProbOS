"""AD-1261: authority matches actual execution identity and effective permissions."""

from __future__ import annotations

import asyncio
import gc
import weakref
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import pytest

from probos.cognitive import self_telemetry_domains as domain_module
from probos.cognitive.agentic_dispatch import (
    AgenticIdentityUnresolved, WorkItemAgenticExecutor, resolve_agentic_identity,
)
from probos.cognitive.decomposer import is_capability_gap
from probos.cognitive.swe_harness import agentic_loop as loop_module
from probos.cognitive.swe_harness.tool_call import (
    ToolCallRequest, ToolCallResult, ToolUseBlock, render_tool_output,
)
from probos.config import format_trust
from probos.ontology.models import Post
from probos.tools.executor import ToolExecutor
from probos.tools.protocol import ToolPermission, ToolResult, ToolResultPresentation
from probos.tools.self_query_tool import SELF_QUERY_OPTIONAL_DOMAINS, SelfQueryTool
from tests.test_ad1260_wellness_domain import (
    _FakeCatalogTool, _FakeRuntime, _NoLiveLLM, _SUBJECT, _OTHER, _PRIVATE, _PEER,
    _OMISSION_NOTICE,
    candidate_origins, domain_runtime,
)


def _execution_identity(runtime: _FakeRuntime, agent_id: str = _SUBJECT) -> Any:
    return resolve_agentic_identity(
        agent_id=agent_id, agent_registry=runtime.registry,
        ontology=runtime.ontology, trust_network=runtime.trust_network,
    )


class TestAuthorityContract:
    async def test_get_authority_state_effective_levels_and_enabled_population(
        self, domain_runtime: _FakeRuntime,
    ) -> None:
        registry = domain_runtime.tool_registry
        identity = _execution_identity(domain_runtime)
        for tool_id, level in (
            ("read_tool", "read"), ("observe_tool", "observe"),
            ("write_tool", "write"), ("restricted_tool", "none"),
        ):
            registry.register(
                _FakeCatalogTool(tool_id), default_permissions={identity.rank: level},
            )
        registry.register(_FakeCatalogTool("disabled_tool"), enabled=False)
        registry.register(_FakeCatalogTool("type_only"), restricted_to=["counselor"])
        await domain_runtime.tool_permission_store.issue_grant(
            _SUBJECT, "read_tool", ToolPermission.FULL,
        )
        await domain_runtime.tool_permission_store.issue_grant(
            _SUBJECT, "write_tool", ToolPermission.OBSERVE, is_restriction=True,
        )
        result = await domain_runtime.introspective_telemetry.get_authority_state(_SUBJECT)
        assert result["held"] == [
            {"tool_id": "observe_tool", "permission": "observe"},
            {"tool_id": "read_tool", "permission": "full"},
            {"tool_id": "write_tool", "permission": "observe"},
        ]
        assert result["withheld"] == ["restricted_tool", "type_only"]
        assert result["coverage"] == {
            "population": "registered_enabled_tools", "catalog_total": 5,
            "resolved_total": 5, "unresolved_total": 0, "held_total": 3,
            "withheld_total": 2, "held_omitted": 0, "withheld_omitted": 0,
            "complete": True,
        }
        assert result["escalation_route"] == "Science Chief"
        for entry in result["held"]:
            assert entry["permission"] == registry.resolve_permission(
                _SUBJECT, entry["tool_id"], agent_department=identity.department,
                agent_rank=identity.rank,
            ).value
        rendered = domain_runtime.introspective_telemetry.render_telemetry_context(
            {"authority": result},
        )
        assert "Withheld: restricted_tool, type_only\nEscalation route: Science Chief" in rendered
        assert "permissions unchanged" in rendered
        assert not is_capability_gap(rendered)

    @pytest.mark.parametrize("subject", [_SUBJECT, _OTHER])
    async def test_get_authority_state_identity_equals_public_execution_resolver(
        self, domain_runtime: _FakeRuntime, subject: str,
    ) -> None:
        expected = _execution_identity(domain_runtime, subject)
        domain_runtime.trust_network.subjects.clear()
        result = await domain_runtime.introspective_telemetry.get_authority_state(subject)
        assert (result["department"], result["rank"]) == (expected.department, expected.rank)
        assert result["trust_score"] == format_trust(domain_runtime.trust_network.scores[subject])
        assert domain_runtime.trust_network.subjects == [subject]
        assert _execution_identity(domain_runtime, _SUBJECT).rank != (
            _execution_identity(domain_runtime, _OTHER).rank
        )

    async def test_get_authority_state_displays_the_resolver_sample_not_a_second_read(
        self, domain_runtime: _FakeRuntime, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        samples = iter([0.2, 0.95])
        seen: list[str] = []
        def changing_score(agent_id: str) -> float:
            seen.append(agent_id)
            return next(samples)
        domain_runtime.trust_network.scores[_SUBJECT] = 0.2
        expected = _execution_identity(domain_runtime)
        monkeypatch.setattr(domain_runtime.trust_network, "get_score", changing_score)
        result = await domain_runtime.introspective_telemetry.get_authority_state(_SUBJECT)
        assert seen == [_SUBJECT]
        assert result["trust_score"] == 0.2 and result["rank"] == expected.rank
        assert next(samples) == 0.95

    @pytest.mark.parametrize("department", [None, ""])
    async def test_get_authority_state_present_ontology_empty_department_uses_resolver_fallback(
        self, domain_runtime: _FakeRuntime, monkeypatch: pytest.MonkeyPatch,
        department: str | None,
    ) -> None:
        monkeypatch.setattr(domain_runtime.ontology, "get_agent_department", lambda _: department)
        expected = _execution_identity(domain_runtime)
        result = await domain_runtime.introspective_telemetry.get_authority_state(_SUBJECT)
        assert result["department"] == expected.department
        assert result["rank"] == expected.rank

    @pytest.mark.parametrize(
        "case", ["ontology", "registry", "trust_network", "tool_registry", "mismatch",
                 "catalog", "all-permissions", "empty-id", "none-id", "nan-trust"],
    )
    async def test_get_authority_state_failed_resolution_is_unknown_not_empty_withholding(
        self, domain_runtime: _FakeRuntime, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture, case: str,
    ) -> None:
        domain_runtime.tool_registry.register(_FakeCatalogTool("tool"))
        subject = _SUBJECT
        def fail(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError(_PRIVATE)
        if case in ("ontology", "registry", "trust_network", "tool_registry"):
            setattr(domain_runtime, case, None)
        elif case == "mismatch":
            other = domain_runtime.registry.get(_OTHER)
            monkeypatch.setattr(
                domain_runtime.registry, "get", lambda _: other,
            )
        elif case == "catalog":
            monkeypatch.setattr(domain_runtime.tool_registry, "list_tools", fail)
        elif case == "all-permissions":
            monkeypatch.setattr(domain_runtime.tool_registry, "resolve_permission", fail)
        elif case == "nan-trust":
            domain_runtime.trust_network.scores[_SUBJECT] = float("nan")
        else:
            subject = "" if case == "empty-id" else None
        result = await domain_runtime.introspective_telemetry.get_authority_state(subject)
        assert result == {} and "withheld" not in result
        assert caplog.records and caplog.records[-1].levelname == "WARNING"
        assert _PRIVATE not in caplog.text
        if case in ("ontology", "registry", "trust_network", "mismatch", "empty-id", "none-id"):
            with pytest.raises(AgenticIdentityUnresolved):
                _execution_identity(domain_runtime, subject)

    async def test_get_authority_state_partial_resolution_counts_whole_catalog(
        self, domain_runtime: _FakeRuntime, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        registry = domain_runtime.tool_registry
        for tool_id in ("held", "unresolved", "withheld"):
            registry.register(
                _FakeCatalogTool(tool_id),
                restricted_to=[_OTHER] if tool_id == "withheld" else None,
            )
        resolve = registry.resolve_permission
        def partial(agent_id: str, tool_id: str, **kwargs: Any) -> ToolPermission:
            if tool_id == "unresolved":
                raise RuntimeError(_PRIVATE)
            return resolve(agent_id, tool_id, **kwargs)
        monkeypatch.setattr(registry, "resolve_permission", partial)
        result = await domain_runtime.introspective_telemetry.get_authority_state(_SUBJECT)
        assert result["coverage"] == {
            "population": "registered_enabled_tools", "catalog_total": 3,
            "resolved_total": 2, "unresolved_total": 1, "held_total": 1,
            "withheld_total": 1, "held_omitted": 0, "withheld_omitted": 0,
            "complete": False,
        }
        rendered = domain_runtime.introspective_telemetry.render_telemetry_context(
            {"authority": result},
        )
        assert "unresolved=1" in rendered and not is_capability_gap(rendered)

    async def test_get_authority_state_caps_and_oversized_ids_have_truthful_omissions(
        self, domain_runtime: _FakeRuntime,
    ) -> None:
        registry = domain_runtime.tool_registry
        for partition in ("held", "withheld"):
            for index in range(30):
                registry.register(
                    _FakeCatalogTool(f"{partition}_{index:02d}"),
                    restricted_to=[_OTHER] if partition == "withheld" else None,
                )
            registry.register(
                _FakeCatalogTool(partition + "_" * 257),
                restricted_to=[_OTHER] if partition == "withheld" else None,
            )
        result = await domain_runtime.introspective_telemetry.get_authority_state(_SUBJECT)
        assert len(result["held"]) == len(result["withheld"]) == 25
        assert result["coverage"] == {
            "population": "registered_enabled_tools", "catalog_total": 62,
            "resolved_total": 62, "unresolved_total": 0, "held_total": 31,
            "withheld_total": 31, "held_omitted": 6, "withheld_omitted": 6,
            "complete": False,
        }
        for entry in result["held"]:
            assert registry.get(entry["tool_id"]) is not None
        assert all(registry.get(tool_id) is not None for tool_id in result["withheld"])
        assert not is_capability_gap(
            domain_runtime.introspective_telemetry.render_telemetry_context({"authority": result})
        )

    @pytest.mark.parametrize("case", ["normal", "ancestor", "undeclared", "other-dept", "long", "missing", "error"])
    async def test_get_authority_state_route_is_nearest_declared_superior_or_captain(
        self, domain_runtime: _FakeRuntime, monkeypatch: pytest.MonkeyPatch, case: str,
    ) -> None:
        posts = domain_runtime.posts
        if case == "ancestor":
            posts["counselor-post"].reports_to = "intermediate"
            posts["intermediate"] = Post(
                "intermediate", "Intermediate", "science", "science-chief",
            )
            posts["science-chief"].authority_over = ["intermediate"]
        elif case == "undeclared":
            posts["science-chief"].authority_over = []
        elif case == "other-dept":
            posts["science-chief"].department_id = "engineering"
        elif case == "long":
            posts["science-chief"].title = "x" * 257
        elif case == "missing":
            monkeypatch.setattr(domain_runtime.ontology, "get_post_for_agent", lambda _: None)
        elif case == "error":
            def fail(_: str) -> Any:
                raise RuntimeError(_PRIVATE)
            monkeypatch.setattr(domain_runtime.ontology, "get_chain_of_command", fail)
        result = await domain_runtime.introspective_telemetry.get_authority_state(_SUBJECT)
        assert result["escalation_route"] == (
            "Science Chief" if case in ("normal", "ancestor") else "Captain"
        )

    async def test_get_authority_state_empty_catalog_is_successful_and_complete(
        self, domain_runtime: _FakeRuntime,
    ) -> None:
        result = await domain_runtime.introspective_telemetry.get_authority_state(_SUBJECT)
        assert result["held"] == result["withheld"] == []
        assert result["coverage"]["catalog_total"] == 0
        assert result["coverage"]["complete"] is True
        rendered = domain_runtime.introspective_telemetry.render_telemetry_context(
            {"authority": result},
        )
        # R1 replaces "(empty)": zero shown must remain distinct from omitted entries.
        assert "Withheld: 0 shown; 0 omitted\nEscalation route:" in rendered
        assert not is_capability_gap(rendered)
        assert not is_capability_gap(SelfQueryTool(telemetry=None).description)

    @pytest.mark.parametrize("domain", ["wellness", "authority"])
    async def test_self_query_explicit_selection_has_exact_domain_and_safe_render(
        self, domain_runtime: _FakeRuntime, domain: str,
    ) -> None:
        result = await SelfQueryTool(telemetry=domain_runtime.introspective_telemetry).invoke(
            {"domains": [domain, domain]}, {"agent_id": _SUBJECT},
        )
        assert result.success and list(result.output["domains"]) == [domain]
        assert f"{domain.title()}:" in result.output["rendered"]
        assert not is_capability_gap(result.output["rendered"])

    @pytest.mark.parametrize("owner", ["trust_network", "tool_registry"])
    async def test_get_authority_state_cancellation_propagates(
        self, domain_runtime: _FakeRuntime, monkeypatch: pytest.MonkeyPatch, owner: str,
    ) -> None:
        domain_runtime.tool_registry.register(_FakeCatalogTool("tool"))
        def cancel(*args: Any, **kwargs: Any) -> Any:
            raise asyncio.CancelledError()
        monkeypatch.setattr(
            getattr(domain_runtime, owner),
            "get_score" if owner == "trust_network" else "resolve_permission", cancel,
        )
        with pytest.raises(asyncio.CancelledError):
            await domain_runtime.introspective_telemetry.get_authority_state(_SUBJECT)


def _populate_delivery_catalog(runtime: _FakeRuntime) -> None:
    identity = _execution_identity(runtime)
    for partition in ("held", "withheld"):
        for index in range(31):
            tool_id = f"{partition}_{index:02d}_" + "escaped'\\\r\n" * 15
            runtime.tool_registry.register(
                _FakeCatalogTool(tool_id),
                default_permissions={
                    identity.rank: "observe" if partition == "held" else "none",
                },
            )
    runtime.profile.latest_assessment().concerns = ["Stored 'quote'\\\r\n" * 40] * 5


async def _run_delivery(
    runtime: _FakeRuntime, monkeypatch: pytest.MonkeyPatch, *,
    structured: bool, cap: int, domains: list[str],
) -> tuple[ToolResult, list[tuple[dict[str, Any], str]], Any]:
    from tests import test_ad1258_self_knowledge as fixture_module

    root = Path(__file__).resolve().parents[1]
    assert Path(fixture_module.__file__).resolve() == (
        root / "tests" / "test_ad1258_self_knowledge.py"
    )
    runtime.config.agentic_loop.structured_tool_messages = structured
    runtime.config.agentic_loop.tool_result_max_chars = cap
    call = ToolCallRequest(name="self_query", arguments={"domains": domains}, id="domain-read")
    results: list[ToolResult] = []
    contexts: list[dict[str, Any]] = []
    accepted: list[tuple[dict[str, Any], str]] = []
    reads: list[tuple[str, str]] = []
    source_profile = deepcopy(runtime.profile.to_dict())
    invoke = SelfQueryTool.invoke
    presentation_type = ToolResultPresentation

    async def record_invoke(
        tool: SelfQueryTool, params: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> ToolResult:
        assert context is not None
        contexts.append(context)
        result = await invoke(tool, params, context)
        results.append(result)
        return result

    def record_presentation(*, render_complete: Any) -> ToolResultPresentation:
        def render(value: Any) -> str | None:
            plain = render_complete(value)
            if plain is not None:
                accepted.append((deepcopy(value), plain))
            return plain
        return presentation_type(render_complete=render)

    monkeypatch.setattr(SelfQueryTool, "invoke", record_invoke)
    monkeypatch.setattr(loop_module, "ToolResultPresentation", record_presentation)
    for domain in ("wellness", "authority"):
        getter = getattr(runtime.introspective_telemetry, f"get_{domain}_state")
        async def record_read(
            agent_id: str, selected: str = domain, original: Any = getter,
        ) -> dict[str, Any]:
            reads.append((selected, agent_id))
            return await original(agent_id)
        monkeypatch.setattr(runtime.introspective_telemetry, f"get_{domain}_state", record_read)

    client = fixture_module._ScriptedSelfQueryLLM(call=call)
    forged = {
        "agent_id": _OTHER, "department": "engineering", "rank": "senior_officer",
        "thread_id": "forged-thread",
    }
    original_forged = dict(forged)
    outcome = await WorkItemAgenticExecutor(llm_client=client).run(
        agent_id=_SUBJECT, instructions="Controlled local telemetry read.",
        task_text="Read the explicitly selected self domains.", runtime=runtime,
        department="engineering", rank="senior_officer", thread_id="owned-thread",
        max_iterations=2, extra_context=forged,
    )
    assert outcome.stopped_reason == "complete" and outcome.denied_tools == []
    assert len(client.requests) == 2 and len(results) == 1
    result = results[0]
    expected = ToolCallResult(
        id=call.id,
        output=render_tool_output(result.output, max_chars=0) if result.success else result.error,
        is_error=not result.success,
    )
    # This checks the real next request against the complete producer envelope,
    # before checking the admission witness. Bypassing admission must break it.
    fixture_module._assert_model_visible_result(
        client.requests[1], call, expected, structured=structured,
    )
    assert reads == [(domain, _SUBJECT) for domain in ("wellness", "authority") if domain in domains]
    assert contexts[0]["agent_id"] == _SUBJECT
    assert contexts[0]["agent_department"] == "science"
    assert contexts[0]["thread_id"] == "owned-thread"
    assert type(contexts[0]["_tool_result_presentation"]) is ToolResultPresentation
    assert forged == original_forged
    assert runtime.profile.to_dict() == source_profile
    model_text = str(client.requests[1].messages) + client.requests[1].prompt
    assert _PRIVATE not in model_text and _PEER not in model_text
    if result.success:
        assert accepted and accepted[-1] == (result.output, expected.output)
        assert not is_capability_gap(expected.output)
        assert len(expected.output) <= 6000
        assert cap == 0 or len(expected.output) <= cap
        assert result.output["rendered"] == (
            runtime.introspective_telemetry.render_telemetry_context(result.output["domains"])
        )
    else:
        assert result.output is None and not accepted
        assert not is_capability_gap(result.error)
    return result, accepted, outcome


@pytest.mark.parametrize("structured", [True, False], ids=["structured", "legacy"])
@pytest.mark.parametrize("cap", [0, 6000, 3200, 180])
@pytest.mark.parametrize(
    "domains", [["wellness"], ["authority"], ["wellness", "authority"]],
    ids=["wellness", "authority", "combined"],
)
async def test_loop_delivers_accepted_complete_optional_envelope(
    domain_runtime: _FakeRuntime, monkeypatch: pytest.MonkeyPatch,
    structured: bool, cap: int, domains: list[str],
) -> None:
    _populate_delivery_catalog(domain_runtime)
    result, _, _ = await _run_delivery(
        domain_runtime, monkeypatch, structured=structured, cap=cap, domains=domains,
    )
    assert result.success is (cap != 180)
    if not result.success:
        assert result.error == "self_query: result exceeds the presentation budget."
        return
    assert result.output["agent_id"] == _SUBJECT
    projected = result.output["domains"]
    if "wellness" in domains:
        wellness = projected["wellness"]
        assert wellness["wellness_score"] == 0.8123
        assert "assessment age: 48.0001h" in result.output["rendered"]
        coverage = wellness["coverage"]
        assert coverage["concerns_total"] == 5
        assert coverage["concerns_omitted"] == 5 - len(wellness["concerns"])
        assert coverage["concern_characters_omitted"] == (
            sum(map(len, domain_runtime.profile.latest_assessment().concerns))
            - sum(map(len, wellness["concerns"]))
        )
        assert coverage["complete"] is False
    if "authority" in domains:
        authority = projected["authority"]
        coverage = authority["coverage"]
        catalog = domain_runtime.tool_registry.list_tools(enabled_only=True)
        identity = _execution_identity(domain_runtime)
        held = {
            registration.tool_id: domain_runtime.tool_registry.resolve_permission(
                _SUBJECT, registration.tool_id, agent_department=identity.department,
                agent_rank=identity.rank,
            ).value for registration in catalog
        }
        assert coverage["catalog_total"] == coverage["resolved_total"] == len(catalog)
        assert coverage["unresolved_total"] == 0
        assert coverage["held_total"] == sum(level != "none" for level in held.values())
        assert coverage["withheld_total"] == 31
        assert coverage["held_omitted"] == coverage["held_total"] - len(authority["held"])
        assert coverage["withheld_omitted"] == 31 - len(authority["withheld"])
        assert coverage["complete"] is False
        for entry in authority["held"]:
            assert entry["permission"] == held[entry["tool_id"]]
        assert all(held[tool_id] == "none" for tool_id in authority["withheld"])
        assert authority["escalation_route"] == "Science Chief"
        assert "\nEscalation route: Science Chief" in result.output["rendered"]
        assert not is_capability_gap(result.output["rendered"])


async def test_delivery_admission_control(
    domain_runtime: _FakeRuntime, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _populate_delivery_catalog(domain_runtime)
    result, _, _ = await _run_delivery(
        domain_runtime, monkeypatch, structured=True, cap=3200,
        domains=["wellness", "authority"],
    )
    assert result.success
    assert result.output["domains"]["authority"]["coverage"]["complete"] is False


@pytest.mark.parametrize("structured", [True, False], ids=["structured", "legacy"])
async def test_loop_small_catalog_delivers_effective_permission_withheld_id_and_real_route(
    domain_runtime: _FakeRuntime, monkeypatch: pytest.MonkeyPatch, structured: bool,
) -> None:
    identity = _execution_identity(domain_runtime)
    domain_runtime.tool_registry.register(
        _FakeCatalogTool("monitor_signal"), default_permissions={identity.rank: "observe"},
    )
    domain_runtime.tool_registry.register(
        _FakeCatalogTool("restricted_instrument"), restricted_to=[_OTHER],
    )
    result, _, _ = await _run_delivery(
        domain_runtime, monkeypatch, structured=structured, cap=6000,
        domains=["wellness", "authority"],
    )
    assert result.success
    authority = result.output["domains"]["authority"]
    assert {"tool_id": "monitor_signal", "permission": "observe"} in authority["held"]
    assert "restricted_instrument" in authority["withheld"]
    assert authority["coverage"]["complete"] is True
    assert "Withheld: restricted_instrument\nEscalation route: Science Chief" in result.output["rendered"]


@pytest.mark.parametrize("case", ["absent", "invalid-type", "noncallable", "changed", "raises", "rejects"])
async def test_self_query_presentation_boundary_uses_whole_dictionary_or_neutral_error(
    domain_runtime: _FakeRuntime, case: str,
) -> None:
    context: dict[str, Any] = {"agent_id": _SUBJECT}
    if case == "invalid-type":
        context["_tool_result_presentation"] = None
    elif case == "noncallable":
        context["_tool_result_presentation"] = ToolResultPresentation(None)
    elif case == "changed":
        context["_tool_result_presentation"] = ToolResultPresentation(lambda _: "changed")
    elif case == "raises":
        def fail(_: Any) -> str:
            raise RuntimeError(_PRIVATE)
        context["_tool_result_presentation"] = ToolResultPresentation(fail)
    elif case == "rejects":
        context["_tool_result_presentation"] = ToolResultPresentation(lambda _: None)
    result = await SelfQueryTool(telemetry=domain_runtime.introspective_telemetry).invoke(
        {"domains": ["wellness", "authority"]}, context,
    )
    assert result.success is (case == "absent")
    if result.success:
        assert type(result.output) is dict
        assert len(render_tool_output(result.output, max_chars=0)) <= 6000
    else:
        assert result.output is None
        assert not is_capability_gap(result.error) and _PRIVATE not in result.error


@pytest.mark.parametrize("extra_length", [0, 9000])
async def test_self_query_fitting_preserves_old_domains_and_never_recollects(
    domain_runtime: _FakeRuntime, monkeypatch: pytest.MonkeyPatch, extra_length: int,
) -> None:
    _populate_delivery_catalog(domain_runtime)
    service = domain_runtime.introspective_telemetry
    original = await service.get_trust_state(_SUBJECT)
    original["legacy_fact"] = "L" * extra_length
    saved = deepcopy(original)
    reads: list[str] = []
    async def old_trust(agent_id: str) -> dict[str, Any]:
        reads.append(agent_id)
        return original
    monkeypatch.setattr(service, "get_trust_state", old_trust)
    profile = deepcopy(domain_runtime.profile.to_dict())
    result = await SelfQueryTool(telemetry=service).invoke(
        {"domains": ["trust", "wellness", "authority"]}, {"agent_id": _SUBJECT},
    )
    assert reads == [_SUBJECT] and original == saved
    assert domain_runtime.profile.to_dict() == profile
    if extra_length:
        assert result.output is None and not result.success
        assert result.error == "self_query: result exceeds the presentation budget."
    else:
        assert result.success and result.output["domains"]["trust"] == saved
        assert result.output["domains"]["trust"] is original


@pytest.mark.parametrize("case", ["empty", "partial", "failure", "truncated"])
async def test_authority_status_variants_use_actual_gap_classifier(
    domain_runtime: _FakeRuntime, monkeypatch: pytest.MonkeyPatch, case: str,
) -> None:
    registry = domain_runtime.tool_registry
    if case in ("partial", "failure"):
        registry.register(_FakeCatalogTool("readable"))
        registry.register(_FakeCatalogTool("unresolved"))
        resolve = registry.resolve_permission
        def broken(agent_id: str, tool_id: str, **kwargs: Any) -> ToolPermission:
            if case == "failure" or tool_id == "unresolved":
                raise RuntimeError(_PRIVATE)
            return resolve(agent_id, tool_id, **kwargs)
        monkeypatch.setattr(registry, "resolve_permission", broken)
    elif case == "truncated":
        _populate_delivery_catalog(domain_runtime)
    result = await SelfQueryTool(telemetry=domain_runtime.introspective_telemetry).invoke(
        {"domains": ["authority"]}, {"agent_id": _SUBJECT},
    )
    assert result.success
    assert not is_capability_gap(result.output["rendered"])
    assert not is_capability_gap(str(result.output))
    if case == "failure":
        assert result.output["domains"]["authority"] == {}


@pytest.mark.parametrize("length", [255, 256, 257])
async def test_authority_identifier_boundary_preserves_or_omits_whole_ids(
    domain_runtime: _FakeRuntime, length: int,
) -> None:
    held_id = "held_" + "x" * (length - 5)
    withheld_id = "withheld_" + "x" * (length - 9)
    domain_runtime.tool_registry.register(_FakeCatalogTool(held_id))
    domain_runtime.tool_registry.register(
        _FakeCatalogTool(withheld_id), restricted_to=[_OTHER],
    )
    result = await domain_runtime.introspective_telemetry.get_authority_state(_SUBJECT)
    assert result["coverage"]["resolved_total"] == 2
    if length <= 256:
        assert result["held"] == [{"tool_id": held_id, "permission": "read"}]
        assert result["withheld"] == [withheld_id]
        assert result["coverage"]["complete"] is True
    else:
        assert result["held"] == result["withheld"] == []
        assert result["coverage"]["held_total"] == result["coverage"]["withheld_total"] == 1
        assert result["coverage"]["held_omitted"] == result["coverage"]["withheld_omitted"] == 1
        assert result["coverage"]["complete"] is False


@pytest.mark.parametrize("case", ["catalog", "permission"])
async def test_authority_malformed_service_data_degrades_to_unknown(
    domain_runtime: _FakeRuntime, monkeypatch: pytest.MonkeyPatch, case: str,
) -> None:
    registry = domain_runtime.tool_registry
    registry.register(_FakeCatalogTool("entry"))
    if case == "catalog":
        monkeypatch.setattr(registry, "list_tools", lambda **_: None)
    else:
        monkeypatch.setattr(registry, "resolve_permission", lambda *_, **__: "read")
    assert await domain_runtime.introspective_telemetry.get_authority_state(_SUBJECT) == {}


async def test_self_query_presentation_cancellation_propagates(
    domain_runtime: _FakeRuntime,
) -> None:
    def cancel(value: Any) -> str:
        raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await SelfQueryTool(telemetry=domain_runtime.introspective_telemetry).invoke(
            {"domains": ["wellness", "authority"]},
            {"agent_id": _SUBJECT, "_tool_result_presentation": ToolResultPresentation(cancel)},
        )


def test_self_query_optional_domain_descriptions_are_gap_safe() -> None:
    tool = SelfQueryTool(telemetry=None)
    assert not is_capability_gap(tool.description)
    assert not is_capability_gap(tool.input_schema["properties"]["domains"]["description"])


@pytest.mark.parametrize("partition", ["held", "withheld"])
@pytest.mark.parametrize("extra_entries", [0, 27], ids=["zero-shown", "prior-cap-omissions"])
async def test_authority_shared_filter_preserves_registered_ids_counts_and_permissions(
    domain_runtime: _FakeRuntime, partition: str, extra_entries: int,
) -> None:
    registry = domain_runtime.tool_registry
    identity = _execution_identity(domain_runtime)
    level = "read" if partition == "held" else "none"
    registry.register(_FakeCatalogTool("no tool"), default_permissions={identity.rank: level})
    for index in range(extra_entries):
        registry.register(
            _FakeCatalogTool(f"significant_blackboard_{index:02d}"),
            default_permissions={identity.rank: level},
        )
    control_id = "significant_blackboard'\\\r\ncontrol"
    registry.register(
        _FakeCatalogTool(control_id),
        default_permissions={identity.rank: "none" if partition == "held" else "observe"},
    )
    catalog = deepcopy([entry.to_dict() for entry in registry.list_tools(enabled_only=False)])
    permissions = {
        entry.tool_id: registry.resolve_permission(
            _SUBJECT, entry.tool_id, agent_department=identity.department, agent_rank=identity.rank,
        ) for entry in registry.list_tools()
    }
    assert is_capability_gap("no tool") and not is_capability_gap(control_id)
    service = domain_runtime.introspective_telemetry

    collected = await service.get_authority_state(_SUBJECT)

    coverage = collected["coverage"]
    assert coverage["catalog_total"] == coverage["resolved_total"] == extra_entries + 2
    assert coverage["unresolved_total"] == 0 and coverage["complete"] is False
    for key in ("held", "withheld"):
        total = sum((value is ToolPermission.NONE) == (key == "withheld") for value in permissions.values())
        assert coverage[f"{key}_total"] == total
        assert coverage[f"{key}_omitted"] == total - len(collected[key])
    if partition == "held":
        assert collected["withheld"] == [control_id]
    else:
        assert collected["held"] == [{"tool_id": control_id, "permission": "observe"}]
    for entry in collected["held"]:
        assert entry["permission"] == permissions[entry["tool_id"]].value
    assert all(permissions[tool_id] is ToolPermission.NONE for tool_id in collected["withheld"])
    raw = deepcopy(collected)
    raw[partition].insert(
        0, {"tool_id": "no tool", "permission": "read"} if partition == "held" else "no tool",
    )
    raw["coverage"][f"{partition}_omitted"] -= 1
    raw["coverage"]["complete"] = extra_entries == 0
    snapshot = {"authority": raw}
    before = deepcopy(snapshot)
    assert is_capability_gap(str(snapshot))

    projected = domain_module.filter_optional_domains(snapshot)
    rendered = service.render_telemetry_context(snapshot)

    assert projected == {"authority": collected}
    assert domain_module.filter_optional_domains(projected) == projected
    assert rendered == service.render_telemetry_context(projected)
    assert control_id in rendered and not is_capability_gap(rendered)
    # R1 pinned only the first sentence, leaving the retrieval disclaimer untested.
    assert rendered.splitlines().count(_OMISSION_NOTICE) == 1
    assert not is_capability_gap(_OMISSION_NOTICE)
    if extra_entries == 0:
        assert f"{partition.title()}: 0 shown; 1 omitted" in rendered
    assert "\nEscalation route: Science Chief" in rendered
    assert snapshot == before
    assert [entry.to_dict() for entry in registry.list_tools(enabled_only=False)] == catalog
    assert registry.get("no tool") is not None
    assert registry.resolve_permission(
        _SUBJECT, "no tool", agent_department=identity.department, agent_rank=identity.rank,
    ) is permissions["no tool"]


@pytest.mark.parametrize("field", ["department", "escalation_route", "coverage", "extra_metadata"])
async def test_authority_direct_render_residual_unsafe_value_explicitly_refuses(
    domain_runtime: _FakeRuntime, field: str,
) -> None:
    state = await domain_runtime.introspective_telemetry.get_authority_state(_SUBJECT)
    if field == "coverage":
        state["coverage"]["population"] = "no tool"
    else:
        state[field] = "no tool"
    snapshot = {"authority": state}
    before = deepcopy(snapshot)

    with pytest.raises(ValueError, match="Optional telemetry presentation check failed"):
        domain_module.render_optional_domains(snapshot)

    assert snapshot == before


@pytest.mark.parametrize("structured", [True, False], ids=["structured", "legacy"])
@pytest.mark.parametrize("combined", [False, True], ids=["single-domain", "combined"])
@pytest.mark.parametrize("source", ["concern", "held-id", "withheld-id"])
async def test_loop_real_matching_producer_value_is_omitted_before_next_request(
    domain_runtime: _FakeRuntime, monkeypatch: pytest.MonkeyPatch,
    structured: bool, combined: bool, source: str,
) -> None:
    registry = domain_runtime.tool_registry
    identity = _execution_identity(domain_runtime)
    control_id = "significant_blackboard'\\\r\ninstrument"
    registry.register(
        _FakeCatalogTool(control_id), default_permissions={identity.rank: "observe"},
    )
    if source == "concern":
        offending = "Unable to maintain focus"
        domain_runtime.profile.latest_assessment().concerns = [
            offending, "Significant focus on blackboard",
        ]
        domain = "wellness"
    else:
        offending = "no tool"
        registry.register(
            _FakeCatalogTool(offending),
            default_permissions={identity.rank: "read" if source == "held-id" else "none"},
        )
        domain = "authority"
    assert is_capability_gap(offending)

    result, accepted, _ = await _run_delivery(
        domain_runtime, monkeypatch, structured=structured, cap=6000,
        domains=["wellness", "authority"] if combined else [domain],
    )

    assert result.success
    plain = accepted[-1][1]
    assert not is_capability_gap(plain) and offending not in plain
    # R1 pinned only the first sentence, not the complete model-visible notice.
    assert result.output["rendered"].splitlines().count(_OMISSION_NOTICE) == 1
    assert _OMISSION_NOTICE in plain and not is_capability_gap(_OMISSION_NOTICE)
    if source == "concern":
        state = result.output["domains"]["wellness"]
        assert state["concerns"] == ["Significant focus on blackboard"]
        assert state["coverage"] == {
            "concerns_total": 2, "concerns_omitted": 1,
            "concern_characters_omitted": len(offending), "complete": False,
        }
    else:
        state = result.output["domains"]["authority"]
        partition = "held" if source == "held-id" else "withheld"
        assert state["coverage"][f"{partition}_omitted"] == 1
        assert state["coverage"]["complete"] is False
        assert state["coverage"]["catalog_total"] == state["coverage"]["resolved_total"]
        assert state["coverage"]["unresolved_total"] == 0
        assert {"tool_id": control_id, "permission": "observe"} in state["held"]
        assert registry.get(offending) is not None
        assert registry.resolve_permission(
            _SUBJECT, offending, agent_department=identity.department, agent_rank=identity.rank,
        ).value == ("read" if source == "held-id" else "none")


@pytest.mark.parametrize(
    "case", ["agent-id", "unknown-domain", "old-data", "optional-identity",
             "optional-route", "optional-metadata", "rendered-envelope"],
)
async def test_self_query_nonprunable_gap_refuses_without_pruning_other_facts(
    domain_runtime: _FakeRuntime, monkeypatch: pytest.MonkeyPatch, case: str,
) -> None:
    service = domain_runtime.introspective_telemetry
    domains = ["wellness", "authority"]
    context: dict[str, Any] = {"agent_id": _SUBJECT}
    backing: dict[str, Any] = {}
    if case == "agent-id":
        context["agent_id"] = "no tool"
        domains = ["wellness"]
    elif case == "unknown-domain":
        domains.append("no tool")
    elif case == "old-data":
        _populate_delivery_catalog(domain_runtime)
        backing = {"score": 0.7235, "legacy_fact": "no tool"}
        async def old_trust(agent_id: str) -> dict[str, Any]:
            return backing
        monkeypatch.setattr(service, "get_trust_state", old_trust)
        domains.append("trust")
    elif case == "optional-route":
        domain_runtime.posts["science-chief"].title = "no tool"
    elif case.startswith("optional-"):
        backing = await service.get_authority_state(_SUBJECT)
        if case == "optional-identity":
            backing["department"] = "no tool"
        else:
            backing["coverage"]["source"] = "no tool"
        async def authority(agent_id: str) -> dict[str, Any]:
            return backing
        monkeypatch.setattr(service, "get_authority_state", authority)
    else:
        monkeypatch.setattr(service, "render_telemetry_context", lambda _: "no tool")
    before = deepcopy(backing)
    profile = deepcopy(domain_runtime.profile.to_dict())
    pruned: list[dict[str, Any]] = []
    prune = domain_module.prune_optional_entry
    def record_prune(snapshot: dict[str, Any]) -> bool:
        pruned.append(deepcopy(snapshot))
        return prune(snapshot)
    monkeypatch.setattr(domain_module, "prune_optional_entry", record_prune)
    admissions: list[dict[str, Any]] = []
    def admit(value: dict[str, Any]) -> str:
        admissions.append(deepcopy(value))
        return render_tool_output(value, max_chars=0)
    context["_tool_result_presentation"] = ToolResultPresentation(admit)

    result = await SelfQueryTool(telemetry=service).invoke({"domains": domains}, context)

    assert not result.success and result.output is None
    assert result.error == "self_query: presentation check failed."
    assert not is_capability_gap(result.error)
    assert pruned == admissions == []
    assert backing == before and domain_runtime.profile.to_dict() == profile


async def test_self_query_checks_actual_plain_envelope_again_after_budget_fitting(
    domain_runtime: _FakeRuntime, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = domain_runtime.introspective_telemetry
    original_render = service.render_telemetry_context
    rendered: list[dict[str, Any]] = []
    def render(snapshot: dict[str, Any]) -> str:
        rendered.append(deepcopy(snapshot))
        text = original_render(snapshot)
        if snapshot["wellness"]["concerns"]:
            return text
        # A repr-escaped newline would join its "n" to "no" and defeat this premise.
        text += " no tool"
        assert is_capability_gap(render_tool_output({"rendered": text}, max_chars=0))
        return text
    monkeypatch.setattr(service, "render_telemetry_context", render)
    presentations: list[dict[str, Any]] = []
    def admit(value: dict[str, Any]) -> str | None:
        presentations.append(deepcopy(value))
        return None if value["domains"]["wellness"]["concerns"] else render_tool_output(value)

    result = await SelfQueryTool(telemetry=service).invoke(
        {"domains": ["wellness"]},
        {"agent_id": _SUBJECT, "_tool_result_presentation": ToolResultPresentation(admit)},
    )

    assert not result.success and result.output is None
    assert result.error == "self_query: presentation check failed."
    assert len(rendered) == 2 and len(presentations) == 1
    assert rendered[0]["wellness"]["concerns"] == ["Stored self concern"]
    assert rendered[1]["wellness"]["concerns"] == []
    assert rendered[1]["wellness"]["coverage"]["complete"] is False
    assert domain_runtime.profile.latest_assessment().concerns == ["Stored self concern"]


@pytest.mark.parametrize("structured", [True, False], ids=["structured", "legacy"])
@pytest.mark.parametrize("source", ["route", "old-data"])
async def test_loop_nonprunable_source_delivers_neutral_error_in_next_request(
    domain_runtime: _FakeRuntime, monkeypatch: pytest.MonkeyPatch,
    structured: bool, source: str,
) -> None:
    domains = ["wellness", "authority"]
    if source == "route":
        domain_runtime.posts["science-chief"].title = "no tool"
    else:
        async def old_trust(agent_id: str) -> dict[str, Any]:
            return {"score": 0.7235, "legacy_fact": "no tool"}
        monkeypatch.setattr(domain_runtime.introspective_telemetry, "get_trust_state", old_trust)
        domains.append("trust")

    result, accepted, _ = await _run_delivery(
        domain_runtime, monkeypatch, structured=structured, cap=6000, domains=domains,
    )

    assert result.error == "self_query: presentation check failed."
    assert result.output is None and accepted == []


class _ThirdRepresentationString(str):
    def __init__(self, value: str) -> None:
        self.representations = 0

    def __repr__(self) -> str:
        self.representations += 1
        return super().__repr__() if self.representations <= 2 else repr("no tool")


class _RetentionEnvelope(dict[str, Any]):
    def __init__(self, value: dict[str, Any], *, broken: bool = False) -> None:
        super().__init__(value)
        self.representations = 0
        self.broken = broken

    def __repr__(self) -> str:
        self.representations += 1
        if self.broken:
            raise ValueError(_PRIVATE)
        return super().__repr__()


@dataclass(frozen=True)
class _ExtendedSelfQueryResult(ToolResult):
    witness: object = field(kw_only=True)


class _RetentionExecutor:
    def __init__(self, action: Callable[[ToolResultPresentation], ToolResult]) -> None:
        self.action = action
        self.raw: ToolResult | None = None

    async def invoke(self, *, context: dict[str, Any], **kwargs: Any) -> ToolResult:
        self.raw = self.action(context["_tool_result_presentation"])
        return self.raw


class _RawResultCapture:
    def __init__(self) -> None:
        self.results: list[ToolResult] = []
        self.failed = False

    def record(self, call_id: str, tool_id: str, result: ToolResult) -> None:
        self.results.append(result)

    def fail(self) -> None:
        self.failed = True


async def _execute_retention(
    executor: Any, *, domains: list[str] | None = None,
    tool_id: str = "self_query", cap: int = 6000,
) -> ToolCallResult:
    loop = loop_module.AgenticLoop(
        llm_client=_NoLiveLLM(), tool_executor=executor, tool_result_max_chars=cap,
    )
    return await loop._execute_one_tool(
        ToolUseBlock(ToolCallRequest(
            name=tool_id, arguments={"domains": domains} if domains is not None else {},
            id="retention-read",
        )),
        agent_id=_SUBJECT, iteration=1, context={"agent_id": _SUBJECT},
    )


@pytest.mark.parametrize("structured", [True, False], ids=["structured", "legacy"])
async def test_loop_r2_retained_text_reaches_next_request_without_third_representation(
    domain_runtime: _FakeRuntime, monkeypatch: pytest.MonkeyPatch, structured: bool,
) -> None:
    from tests import test_ad1258_self_knowledge as fixture_module

    root = Path(__file__).resolve().parents[1]
    assert Path(fixture_module.__file__).resolve() == root / "tests" / "test_ad1258_self_knowledge.py"
    changing = _ThirdRepresentationString("Stored unchanged fact")
    assert is_capability_gap("no tool")
    trust = {"score": 0.7235, "legacy_fact": changing}
    service = domain_runtime.introspective_telemetry

    async def get_trust(agent_id: str) -> dict[str, Any]:
        assert agent_id == _SUBJECT
        return trust

    monkeypatch.setattr(service, "get_trust_state", get_trust)
    raw_results: list[ToolResult] = []
    metadata = {"hook_observations": []}
    witness = object()
    original_invoke = SelfQueryTool.invoke

    async def invoke(
        tool: SelfQueryTool, params: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> ToolResult:
        result = await original_invoke(tool, params, context)
        extended = _ExtendedSelfQueryResult(
            output=result.output, error=result.error, duration_ms=37.5,
            metadata=metadata, witness=witness,
        )
        raw_results.append(extended)
        return extended

    monkeypatch.setattr(SelfQueryTool, "invoke", invoke)
    accepted: list[tuple[Any, str]] = []

    def presentation(*, render_complete: Any) -> ToolResultPresentation:
        def admit(value: Any) -> str | None:
            text = render_complete(value)
            if text is not None:
                accepted.append((value, text))
            return text
        return ToolResultPresentation(admit)

    monkeypatch.setattr(loop_module, "ToolResultPresentation", presentation)
    converted: list[tuple[ToolResult, float, int]] = []
    converter = ToolCallResult.from_tool_result

    def convert(
        cls: type[ToolCallResult], request_id: str, result: ToolResult,
        duration_ms: float, *, max_chars: int = 0,
    ) -> ToolCallResult:
        converted.append((result, duration_ms, max_chars))
        return converter(request_id, result, duration_ms, max_chars=max_chars)

    monkeypatch.setattr(ToolCallResult, "from_tool_result", classmethod(convert))
    identity = _execution_identity(domain_runtime)
    domain_runtime.tool_registry.register(
        SelfQueryTool(telemetry=service), default_permissions={identity.rank: "read"},
    )
    executor = ToolExecutor(registry=domain_runtime.tool_registry)
    hook_results: list[ToolResult] = []

    def observe(context: dict[str, Any], result: ToolResult) -> None:
        hook_results.append(result)
        result.metadata["hook_observations"].append(context["agent_id"])

    executor.add_post_hook(observe)
    capture = _RawResultCapture()
    call = ToolCallRequest(
        name="self_query", arguments={"domains": ["trust", "wellness", "authority"]},
        id="retained-domain-read",
    )
    client = fixture_module._ScriptedSelfQueryLLM(call=call)
    outcome = await loop_module.AgenticLoop(
        llm_client=client, tool_executor=executor, structured_tool_messages=structured,
        tool_result_max_chars=6000, max_iterations=2,
    ).run(
        system_prompt="SYS", user_message="Read explicit self domains.", tools=[],
        context={"agent_id": _SUBJECT, "department": identity.department, "rank": identity.rank},
        fault_capture=capture,
    )

    assert len(client.requests) == 2 and outcome.stopped_reason == "complete"
    assert len(raw_results) == len(accepted) == len(converted) == 1
    raw = raw_results[0]
    admitted_object, text = accepted[0]
    replacement, elapsed, cap = converted[0]
    # The oracle is the admitted string, never another serialization of the raw dictionary.
    fixture_module._assert_model_visible_result(
        client.requests[1], call, ToolCallResult(id=call.id, output=text), structured=structured,
    )
    assert type(raw.output) is dict and raw.output is admitted_object
    assert set(raw.output) == {"agent_id", "domains", "rendered", "unknown_domains"}
    assert raw.output["domains"]["trust"] is trust
    assert hook_results[0] is capture.results[0] is raw and not capture.failed
    assert type(replacement) is type(raw) is _ExtendedSelfQueryResult
    assert replacement is not raw and replacement.output is text
    assert replacement.metadata is raw.metadata is metadata
    assert replacement.witness is raw.witness is witness
    assert replacement.duration_ms == raw.duration_ms == 37.5
    assert metadata == {"hook_observations": [_SUBJECT]}
    assert changing.representations == 2
    assert 0 < len(text) <= cap == 6000 and not is_capability_gap(text)
    result = outcome.tool_results[0]
    assert result.output == text and not result.is_error
    assert result.duration_ms == elapsed and result.source_chars is None


@pytest.mark.parametrize("domain", SELF_QUERY_OPTIONAL_DOMAINS)
@pytest.mark.parametrize("case", [
    "missing", "rejected", "stale-rejected", "stale-raise", "mismatch",
    "stale-other", "gap", "over-ceiling", "empty", "subclass-text",
])
async def test_loop_r2_invalid_retention_returns_neutral_error_without_raw_conversion(
    monkeypatch: pytest.MonkeyPatch, domain: str, case: str,
) -> None:
    initial = _RetentionEnvelope({"fact": "stored"})
    at_return: list[tuple[_RetentionEnvelope, int]] = []
    conversions: list[ToolResult] = []
    converter = ToolCallResult.from_tool_result

    def convert(
        cls: type[ToolCallResult], request_id: str, result: ToolResult,
        duration_ms: float, *, max_chars: int = 0,
    ) -> ToolCallResult:
        conversions.append(result)
        return converter(request_id, result, duration_ms, max_chars=max_chars)

    monkeypatch.setattr(ToolCallResult, "from_tool_result", classmethod(convert))
    if case == "subclass-text":
        monkeypatch.setattr(
            loop_module, "render_tool_output",
            lambda value, **kwargs: _ThirdRepresentationString("stored"),
        )

    def act(carrier: ToolResultPresentation) -> ToolResult:
        output: Any = initial
        if case in ("rejected", "over-ceiling"):
            output = _RetentionEnvelope({"fact": "x" * 6100})
            text = carrier.render_complete(output)
            assert (text is None) is (case == "rejected")
        elif case == "gap":
            output = _RetentionEnvelope({"fact": "no tool"})
            assert is_capability_gap(carrier.render_complete(output))
        elif case == "empty":
            output = ""
            assert carrier.render_complete(output) == ""
        elif case != "missing":
            assert carrier.render_complete(initial) is not None
            if case == "stale-rejected":
                assert carrier.render_complete({"fact": "x" * 6100}) is None
            elif case == "stale-raise":
                with pytest.raises(ValueError, match="work_pull_presentation_render_failed"):
                    carrier.render_complete(_RetentionEnvelope({}, broken=True))
            elif case == "mismatch":
                output = _RetentionEnvelope(initial)
                assert output == initial and output is not initial
            elif case == "stale-other":
                assert carrier.render_complete({"different": "stored"}) is not None
        if isinstance(output, _RetentionEnvelope):
            at_return.append((output, output.representations))
        return ToolResult(output=output)

    executor = _RetentionExecutor(act)
    result = await _execute_retention(
        executor, domains=[domain], cap=0 if case == "over-ceiling" else 6000,
    )

    assert result.is_error and result.output == "self_query: presentation check failed."
    assert not is_capability_gap(result.output) and _PRIVATE not in result.output
    assert conversions == []
    assert all(value.representations == count for value, count in at_return)


@pytest.mark.parametrize("stage", ["replacement", "conversion"])
async def test_loop_r2_presentation_failure_never_retries_with_raw(
    monkeypatch: pytest.MonkeyPatch, stage: str,
) -> None:
    output = _RetentionEnvelope({"fact": "stored"})
    seen: list[ToolResult] = []

    def act(carrier: ToolResultPresentation) -> ToolResult:
        assert carrier.render_complete(output) is not None
        return ToolResult(output=output)

    if stage == "replacement":
        def fail_replace(raw: ToolResult, **kwargs: Any) -> ToolResult:
            seen.append(raw)
            raise ValueError(_PRIVATE)
        monkeypatch.setattr(loop_module, "replace", fail_replace)
    else:
        def fail_convert(
            cls: type[ToolCallResult], request_id: str, raw: ToolResult,
            duration_ms: float, *, max_chars: int = 0,
        ) -> ToolCallResult:
            seen.append(raw)
            raise ValueError(_PRIVATE)
        monkeypatch.setattr(ToolCallResult, "from_tool_result", classmethod(fail_convert))
    executor = _RetentionExecutor(act)

    result = await _execute_retention(executor, domains=["wellness", "authority"])

    assert result.is_error and result.output == "self_query: presentation check failed."
    assert not is_capability_gap(result.output) and _PRIVATE not in result.output
    assert len(seen) == 1 and output.representations == 1
    if stage == "conversion":
        assert seen[0] is not executor.raw and type(seen[0].output) is str
    else:
        assert seen[0] is executor.raw


@pytest.mark.parametrize("invalidate", [False, True], ids=["retained", "cleared"])
async def test_loop_r2_retention_holds_strong_reference_until_next_attempt(
    invalidate: bool,
) -> None:
    def act(carrier: ToolResultPresentation) -> ToolResult:
        output = _RetentionEnvelope({"fact": "stored"})
        reference = weakref.ref(output)
        assert carrier.render_complete(output) is not None
        del output
        gc.collect()
        assert reference() is not None
        if invalidate:
            assert carrier.render_complete({"fact": "x" * 6100}) is None
            gc.collect()
            assert reference() is None
        return ToolResult(output=reference())

    result = await _execute_retention(_RetentionExecutor(act), domains=["wellness"])

    assert result.is_error is invalidate
    assert result.output == (
        "self_query: presentation check failed." if invalidate else "{'fact': 'stored'}"
    )


@pytest.mark.parametrize("error", ["", "no tool", "Stored service refusal."])
async def test_loop_r2_genuine_error_never_uses_retained_success(
    monkeypatch: pytest.MonkeyPatch, error: str,
) -> None:
    output = _RetentionEnvelope({"fact": "stored"})
    observed: list[ToolResult] = []
    converter = ToolCallResult.from_tool_result

    def convert(
        cls: type[ToolCallResult], request_id: str, raw: ToolResult,
        duration_ms: float, *, max_chars: int = 0,
    ) -> ToolCallResult:
        observed.append(raw)
        return converter(request_id, raw, duration_ms, max_chars=max_chars)

    monkeypatch.setattr(ToolCallResult, "from_tool_result", classmethod(convert))

    def act(carrier: ToolResultPresentation) -> ToolResult:
        assert carrier.render_complete(output) is not None
        return ToolResult(output=output, error=error)

    executor = _RetentionExecutor(act)
    result = await _execute_retention(executor, domains=["authority"])

    assert result.is_error and result.output == error
    assert len(observed) == 1 and observed[0] is executor.raw
    assert executor.raw.output is output and output.representations == 1


@pytest.mark.parametrize("tool_id,domains", [
    ("self_query", None), ("self_query", ["trust"]),
    ("ordinary_tool", ["wellness", "authority"]),
    ("claim_work_item", ["wellness"]),
])
async def test_loop_r2_old_only_and_other_tools_keep_original_conversion(
    monkeypatch: pytest.MonkeyPatch, tool_id: str, domains: list[str] | None,
) -> None:
    output = _RetentionEnvelope({"fact": "no tool"})
    raw = ToolResult(output=output)
    converted: list[ToolResult] = []
    converter = ToolCallResult.from_tool_result

    def convert(
        cls: type[ToolCallResult], request_id: str, value: ToolResult,
        duration_ms: float, *, max_chars: int = 0,
    ) -> ToolCallResult:
        converted.append(value)
        return converter(request_id, value, duration_ms, max_chars=max_chars)

    monkeypatch.setattr(ToolCallResult, "from_tool_result", classmethod(convert))

    class _UnchangedExecutor:
        async def invoke(self, **kwargs: Any) -> ToolResult:
            return raw

    result = await _execute_retention(_UnchangedExecutor(), tool_id=tool_id, domains=domains)

    assert not result.is_error and result.output == "{'fact': 'no tool'}"
    assert is_capability_gap(result.output)
    assert len(converted) == 1 and converted[0] is raw
    assert output.representations == 1


async def test_loop_r2_concurrent_calls_have_separate_retained_pairs() -> None:
    first_admitted = asyncio.Event()
    second_admitted = asyncio.Event()
    outputs: dict[str, _RetentionEnvelope] = {}
    texts: dict[str, str] = {}
    carriers: dict[str, ToolResultPresentation] = {}

    class _ConcurrentExecutor:
        async def invoke(
            self, *, agent_id: str, context: dict[str, Any], **kwargs: Any,
        ) -> ToolResult:
            if agent_id == _OTHER:
                await first_admitted.wait()
            carrier = context["_tool_result_presentation"]
            carriers[agent_id] = carrier
            output = _RetentionEnvelope({"subject": agent_id})
            outputs[agent_id] = output
            text = carrier.render_complete(output)
            assert type(text) is str
            texts[agent_id] = text
            if agent_id == _SUBJECT:
                first_admitted.set()
                await second_admitted.wait()
            else:
                second_admitted.set()
            return ToolResult(output=output)

    loop = loop_module.AgenticLoop(
        llm_client=_NoLiveLLM(), tool_executor=_ConcurrentExecutor(),
        tool_result_max_chars=6000,
    )
    tasks = [
        asyncio.create_task(loop._execute_one_tool(
            ToolUseBlock(ToolCallRequest(
                name="self_query", arguments={"domains": [domain]}, id=subject,
            )),
            agent_id=subject, iteration=1, context={"agent_id": subject},
        ))
        for subject, domain in zip((_SUBJECT, _OTHER), SELF_QUERY_OPTIONAL_DOMAINS)
    ]
    try:
        async with asyncio.timeout(5):
            results = await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    assert carriers[_SUBJECT] is not carriers[_OTHER]
    for result in results:
        assert not result.is_error and result.output == texts[result.id]
        assert outputs[result.id].representations == 1


@pytest.mark.parametrize("structured", [True, False], ids=["structured", "legacy"])
async def test_loop_r2_pre_hook_refusal_without_retention_reaches_next_request_unchanged(
    domain_runtime: _FakeRuntime, monkeypatch: pytest.MonkeyPatch, structured: bool,
) -> None:
    from tests import test_ad1258_self_knowledge as fixture_module

    async def unexpected(
        tool: SelfQueryTool, params: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> ToolResult:
        pytest.fail("Refused self_query must not collect or admit a presentation")

    monkeypatch.setattr(SelfQueryTool, "invoke", unexpected)
    domain_runtime.tool_registry.register(
        SelfQueryTool(telemetry=domain_runtime.introspective_telemetry),
    )
    executor = ToolExecutor(registry=domain_runtime.tool_registry)
    executor.add_pre_hook(lambda _: False)
    refusals: list[ToolResult] = []
    executor.add_terminal_hook(lambda context, result: refusals.append(result))
    capture = _RawResultCapture()
    call = ToolCallRequest(name="self_query", arguments={"domains": ["wellness"]}, id="refused")
    client = fixture_module._ScriptedSelfQueryLLM(call=call)

    outcome = await loop_module.AgenticLoop(
        llm_client=client, tool_executor=executor, structured_tool_messages=structured,
        tool_result_max_chars=6000, max_iterations=2,
    ).run(
        system_prompt="SYS", user_message="Read explicit self domains.", tools=[],
        context={"agent_id": _SUBJECT}, fault_capture=capture,
    )

    assert len(client.requests) == 2 and len(refusals) == len(capture.results) == 1
    assert refusals[0] is capture.results[0] and not capture.failed
    result = outcome.tool_results[0]
    assert result.is_error and result.output == refusals[0].error
    assert result.output == "Pre-hook aborted invocation of self_query"
    fixture_module._assert_model_visible_result(
        client.requests[1], call, result, structured=structured,
    )
