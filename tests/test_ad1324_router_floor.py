"""AD-1324: the router/client tier floor (``min_tier``) and additive correlation events.

Drives the real ``_wire_model_routing`` wiring, the real ``OpenAICompatibleClient`` and an
in-process ``httpx.MockTransport`` (the BF-886 pattern). The floor only ever REMOVES
candidates; it never reorders them, never routes special tiers, and unarmed calls are
byte-identical to before.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from probos.cognitive import llm_client as llm_mod
from probos.cognitive.llm_client import OpenAICompatibleClient
from probos.cognitive.model_registry import ModelRegistry
from probos.cognitive.model_router import ModelRouter
from probos.config import CognitiveConfig, ModelRoutingConfig, SystemConfig
from probos.events import EventType
from probos.startup.finalize import _wire_model_routing
from probos.types import LLMRequest

_NAMES = {"fast": "claude-sonnet-4-6-fast", "standard": "claude-sonnet-4-6", "deep": "claude-opus-4-6"}


class _Endpoint:
    def __init__(self) -> None:
        self.bodies: list[dict[str, Any]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        assert request.url.host == "offline.invalid"
        self.bodies.append(json.loads(request.content))
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "pong"}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 2, "prompt_tokens": 1},
        })

    @property
    def models(self) -> list[str]:
        return [b.get("model") for b in self.bodies]


@pytest.fixture
def endpoint(monkeypatch: pytest.MonkeyPatch) -> _Endpoint:
    monkeypatch.delenv("PROBOS_LLM_URL", raising=False)
    fake = _Endpoint()

    def build(client: OpenAICompatibleClient, tier: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=client._tier_configs[tier]["base_url"],
            transport=httpx.MockTransport(fake.handle),
        )

    monkeypatch.setattr(OpenAICompatibleClient, "_build_client", build)
    return fake


class _Runtime:
    def __init__(self, llm_client: Any) -> None:
        self.llm_client = llm_client
        self.model_registry: Any = "unset"
        self.model_router: Any = "unset"
        self.events: list[tuple[Any, dict[str, Any]]] = []

    def emit_event(self, event_type: Any, data: dict[str, Any]) -> None:
        self.events.append((event_type, data))

    def of(self, event_type: EventType) -> list[dict[str, Any]]:
        return [d for et, d in self.events if et == event_type]


def _wired(ceiling: float | None = None) -> tuple[_Runtime, OpenAICompatibleClient]:
    config = SystemConfig(
        cognitive=CognitiveConfig(
            llm_base_url="https://offline.invalid/v1/",
            llm_model_fast=_NAMES["fast"], llm_model_standard=_NAMES["standard"],
            llm_model_deep=_NAMES["deep"],
        ),
        model_routing=ModelRoutingConfig(enabled=True, cost_ceiling_per_million_output_tokens=ceiling),
    )
    client = OpenAICompatibleClient(config=config.cognitive)
    runtime = _Runtime(client)
    _wire_model_routing(runtime=runtime, config=config)
    return runtime, client


def _router(ceiling: float | None = None) -> ModelRouter:
    return ModelRouter(registry=ModelRegistry(), cost_ceiling=ceiling)


def test_tier_tuples_are_unchanged() -> None:
    assert llm_mod.TEXT_TIERS == ("fast", "standard", "deep")
    assert llm_mod._TIER_ORDER == ("fast", "standard", "deep")
    assert llm_mod._LLM_TIERS == (
        "fast", "standard", "deep", "vision", "vision_fast", "compute_use", "image_gen",
    )


def test_choose_without_floor_matches_the_golden_decision() -> None:
    plain = _router().choose(tier="standard")
    floored_none = _router().choose(tier="standard", min_tier=None)
    assert plain == floored_none
    assert plain.excluded_by_floor is False


def test_choose_below_floor_is_excluded_not_rerouted() -> None:
    decision = _router().choose(tier="fast", min_tier="deep")
    assert decision.excluded_by_floor is True
    assert not decision.chosen_model


def test_choose_at_or_above_floor_is_unchanged() -> None:
    assert _router().choose(tier="deep", min_tier="standard").chosen_tier == "deep"
    assert _router().choose(tier="deep", min_tier="deep").excluded_by_floor is False


def test_cost_ceiling_and_floor_together_leave_no_candidate() -> None:
    decision = _router(ceiling=20.0).choose(tier="deep", min_tier="deep")
    assert not decision.chosen_model
    assert decision.excluded_by_floor is True or decision.excluded_by_cost_ceiling is True


def test_any_tier_fallback_never_picks_below_the_floor() -> None:
    router = _router(ceiling=20.0)
    decision = router.choose(tier="deep", min_tier="deep")
    assert decision.chosen_tier in ("", "deep")


@pytest.mark.asyncio
async def test_unarmed_routed_payload_is_exactly_the_old_three_keys(endpoint: _Endpoint) -> None:
    runtime, client = _wired()
    try:
        await client.complete(LLMRequest(prompt="ping", tier="deep"))
    finally:
        await client.close()
    routed = runtime.of(EventType.MODEL_ROUTED)
    assert [set(e) for e in routed] == [{"chosen_model", "tier", "reason"}]


@pytest.mark.asyncio
async def test_armed_routed_payload_adds_correlation_keys_only(endpoint: _Endpoint) -> None:
    runtime, client = _wired()
    try:
        await client.complete(LLMRequest(
            prompt="ping", tier="deep", agent_id="a1", work_item_id="w1",
            min_tier="standard", tier_choice_reason="floor_raise",
        ))
    finally:
        await client.close()
    event = runtime.of(EventType.MODEL_ROUTED)[0]
    assert {"chosen_model", "tier", "reason"} <= set(event)
    assert event["agent_id"] == "a1" and event["work_item_id"] == "w1"
    assert endpoint.models == [_NAMES["deep"]]


@pytest.mark.asyncio
async def test_floor_filters_the_fallback_chain_and_sends_nothing_below(endpoint: _Endpoint) -> None:
    runtime, client = _wired(ceiling=20.0)  # deep (75) is excluded
    try:
        response = await client.complete(LLMRequest(prompt="ping", tier="deep", min_tier="deep"))
    finally:
        await client.close()
    assert response.error_kind == "tier_floor_unmet"
    assert response.content == ""
    assert endpoint.bodies == []  # zero lower-tier endpoint calls


@pytest.mark.asyncio
async def test_same_request_without_floor_still_falls_back(endpoint: _Endpoint) -> None:
    _runtime, client = _wired(ceiling=20.0)
    try:
        response = await client.complete(LLMRequest(prompt="ping", tier="deep"))
    finally:
        await client.close()
    assert response.error is None and response.error_kind is None
    assert endpoint.models == [_NAMES["fast"]]


@pytest.mark.asyncio
async def test_floor_met_sends_at_the_floor_model(endpoint: _Endpoint) -> None:
    _runtime, client = _wired()
    try:
        response = await client.complete(LLMRequest(prompt="ping", tier="standard", min_tier="standard"))
    finally:
        await client.close()
    assert response.error is None
    assert endpoint.models == [_NAMES["standard"]]


@pytest.mark.asyncio
async def test_cache_fallback_below_floor_is_not_served(endpoint: _Endpoint) -> None:
    _runtime, client = _wired(ceiling=20.0)
    try:
        # Cached under the requested tier's key, but answered by a lower tier's model.
        first = await client.complete(LLMRequest(prompt="same", tier="deep"))
        assert first.error is None and endpoint.models == [_NAMES["fast"]]

        endpoint.bodies.clear()
        response = await client.complete(LLMRequest(prompt="same", tier="deep", min_tier="deep"))
    finally:
        await client.close()
    assert response.error_kind == "tier_floor_unmet"
    assert endpoint.bodies == []


def test_special_tier_with_floor_is_not_floored() -> None:
    assert LLMRequest(prompt="x", tier="vision", min_tier="deep").min_tier == "deep"
    assert "vision" not in llm_mod.TEXT_TIERS


@pytest.mark.asyncio
async def test_legacy_router_fakes_without_new_kwargs_still_work(endpoint: _Endpoint) -> None:
    seen: list[str] = []

    class _Fake:
        def choose(self, *, tier: str) -> Any:
            seen.append(tier)
            return _router().choose(tier=tier)

    _runtime, client = _wired()
    client.model_router = _Fake()
    try:
        response = await client.complete(LLMRequest(prompt="ping", tier="standard"))
    finally:
        await client.close()
    assert response.error is None
    assert seen == ["standard"]


def test_registry_without_a_floor_tier_model_never_substitutes_a_lower_one() -> None:
    registry = ModelRegistry.from_tier_models({"fast": "claude-sonnet-4-6-fast", "standard": "claude-sonnet-4-6"})
    decision = ModelRouter(registry=registry).choose(tier="deep", min_tier="deep")
    assert decision.chosen_model == "" and decision.excluded_by_floor is True
    unfloored = ModelRouter(registry=registry).choose(tier="deep")
    assert unfloored.chosen_model and unfloored.fallback is True


@pytest.mark.asyncio
async def test_client_filters_the_chain_even_when_the_router_ignores_the_floor(endpoint: _Endpoint) -> None:
    class _FloorBlind:
        def choose(self, *, tier: str, min_tier: str | None = None, correlation: Any = None) -> Any:
            return _router(ceiling=20.0).choose(tier=tier)

    _runtime, client = _wired()
    client.model_router = _FloorBlind()
    try:
        response = await client.complete(LLMRequest(prompt="ping", tier="deep", min_tier="deep"))
    finally:
        await client.close()
    assert response.error_kind == "tier_floor_unmet"
    assert endpoint.bodies == []


# -- Amendment 1: cache provenance records the tier that SERVED, not the one attempted ----------
from collections import OrderedDict  # noqa: E402

from probos.types import LLMResponse  # noqa: E402


def _no_deep_router() -> ModelRouter:
    return ModelRouter(registry=ModelRegistry.from_tier_models(
        {"fast": _NAMES["fast"], "standard": _NAMES["standard"]},
    ))


@pytest.mark.asyncio
async def test_cache_entry_served_by_fast_on_deep_attempt_does_not_satisfy_deep_floor(endpoint: _Endpoint) -> None:
    _runtime, client = _wired()
    client.model_router = _no_deep_router()  # deep has no model: the router's any-tier fallback answers
    try:
        # Amendment 2: only a floor-armed request records provenance (an unarmed one caches as unknown).
        first = await client.complete(LLMRequest(prompt="same", tier="deep", min_tier="fast"))
        assert first.error is None
        assert endpoint.models and endpoint.models[0] != _NAMES["deep"], "premise: a lower tier's model served it"
        served = set(client._cache_provenance.values())
        assert served and served <= {"fast", "standard"}, "premise: provenance is the served tier, not 'deep'"

        endpoint.bodies.clear()
        response = await client.complete(LLMRequest(prompt="same", tier="deep", min_tier="deep"))
    finally:
        await client.close()
    assert response.cached is not True
    assert response.error_kind == "tier_floor_unmet"
    assert endpoint.bodies == []


def _failing_endpoint(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []

    def build(client: OpenAICompatibleClient, tier: str) -> httpx.AsyncClient:
        def handle(request: httpx.Request) -> httpx.Response:
            seen.append(json.loads(request.content).get("model"))
            return httpx.Response(503, json={"error": "down"})

        return httpx.AsyncClient(
            base_url=client._tier_configs[tier]["base_url"], transport=httpx.MockTransport(handle),
        )

    monkeypatch.setattr(OpenAICompatibleClient, "_build_client", build)
    return seen


@pytest.mark.asyncio
async def test_cache_legacy_entry_without_provenance_serves_unarmed_but_misses_armed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PROBOS_LLM_URL", raising=False)
    _failing_endpoint(monkeypatch)
    _runtime, client = _wired()
    key = client._cache_key("standard", "p", None)
    client._cache[key] = LLMResponse(content="old", model="m", tier="standard", tokens_used=1)
    client._cache_provenance = {}
    try:
        unarmed = await client.complete(LLMRequest(prompt="p", tier="standard"))
        armed = await client.complete(LLMRequest(
            prompt="p", tier="standard", min_tier="standard", exact_tier=True, agent_id="a",
        ))
    finally:
        await client.close()
    assert unarmed.cached is True and unarmed.content == "old"
    assert armed.cached is not True and armed.content == ""


@pytest.mark.asyncio
async def test_cache_eviction_pops_provenance(endpoint: _Endpoint) -> None:
    _runtime, client = _wired()
    client._cache_max_entries = 1
    try:
        await client.complete(LLMRequest(prompt="one", tier="standard", min_tier="standard"))
        await client.complete(LLMRequest(prompt="two", tier="standard", min_tier="standard"))
    finally:
        await client.close()
    assert len(client._cache) == 1
    assert set(client._cache_provenance) == set(client._cache)


def test_cache_helpers_work_on_new_built_client() -> None:
    client = OpenAICompatibleClient.__new__(OpenAICompatibleClient)  # no __init__: no provenance attribute
    client._cache = OrderedDict()
    response = LLMResponse(content="x", model="m", tier="fast", tokens_used=1)
    llm_mod._cache_put(client, "k", response, "fast")
    assert llm_mod._cache_get(client, "k", floor=None, exact=None) is response
    assert llm_mod._cache_get(client, "k", floor="fast", exact=None) is response
    assert llm_mod._cache_get(client, "k", floor="standard", exact=None) is None
    assert llm_mod._cache_get(client, "missing", floor=None, exact=None) is None


def test_exact_tier_cache_hit_requires_equal_provenance() -> None:
    client = OpenAICompatibleClient.__new__(OpenAICompatibleClient)
    client._cache = OrderedDict()
    response = LLMResponse(content="x", model="m", tier="standard", tokens_used=1)
    llm_mod._cache_put(client, "k", response, "standard")
    assert llm_mod._cache_get(client, "k", floor=None, exact="standard") is response
    assert llm_mod._cache_get(client, "k", floor=None, exact="deep") is None
    assert llm_mod._cache_get(client, "k", floor=None, exact="fast") is None