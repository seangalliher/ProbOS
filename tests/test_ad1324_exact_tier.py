"""AD-1324 amendment 1 (finding 3): an armed request is EXACT -- the chosen tier or nothing.

Armed steps never ride the generic ``_TIER_ORDER`` fallback chain or the router's any-tier
fallback: a tier that cannot serve is refused (``tier_unavailable`` / ``tier_floor_unmet``),
and no other tier's model is called. Unarmed requests are byte-identical to before.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from probos.cognitive.llm_client import OpenAICompatibleClient
from probos.cognitive.model_registry import ModelRegistry
from probos.cognitive.model_router import ModelRouter
from probos.types import LLMRequest
from tests.test_ad1324_router_floor import _NAMES, _wired


def _endpoint(monkeypatch: pytest.MonkeyPatch, down: set[str]) -> list[str]:
    monkeypatch.delenv("PROBOS_LLM_URL", raising=False)
    seen: list[str] = []

    def build(client: OpenAICompatibleClient, tier: str) -> httpx.AsyncClient:
        def handle(request: httpx.Request) -> httpx.Response:
            model = json.loads(request.content).get("model")
            seen.append(model)
            if model in down:
                return httpx.Response(503, json={"error": "down"})
            return httpx.Response(200, json={
                "choices": [{"message": {"content": "pong"}, "finish_reason": "stop"}],
                "usage": {"total_tokens": 2, "prompt_tokens": 1},
            })

        return httpx.AsyncClient(
            base_url=client._tier_configs[tier]["base_url"], transport=httpx.MockTransport(handle),
        )

    monkeypatch.setattr(OpenAICompatibleClient, "_build_client", build)
    return seen


@pytest.mark.asyncio
async def test_armed_503_on_chosen_deep_returns_tier_unavailable_and_no_fast_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _endpoint(monkeypatch, down={_NAMES["deep"]})
    _runtime, client = _wired()
    try:
        response = await client.complete(LLMRequest(
            prompt="ping", tier="deep", exact_tier=True, agent_id="a", work_item_id="w",
        ))
    finally:
        await client.close()
    assert response.error_kind == "tier_unavailable"
    assert seen and set(seen) == {_NAMES["deep"]}, "premise: deep was tried; nothing else was called"


@pytest.mark.asyncio
async def test_armed_no_deep_model_with_floor_returns_tier_floor_unmet(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _endpoint(monkeypatch, down=set())
    _runtime, client = _wired()
    client.model_router = ModelRouter(registry=ModelRegistry.from_tier_models(
        {"fast": _NAMES["fast"], "standard": _NAMES["standard"]},
    ))
    try:
        response = await client.complete(LLMRequest(
            prompt="ping", tier="deep", min_tier="deep", exact_tier=True, agent_id="a",
        ))
    finally:
        await client.close()
    assert response.error_kind == "tier_floor_unmet"
    assert seen == []


@pytest.mark.asyncio
async def test_armed_unregistered_deep_without_floor_is_tier_unavailable_and_nothing_is_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A router exclusion (not a 503, which stops the shared endpoint) is what discriminates a
    # surviving _TIER_ORDER tail: with the tail, the fast attempt would be served.
    seen = _endpoint(monkeypatch, down=set())
    _runtime, client = _wired()
    client.model_router = ModelRouter(registry=ModelRegistry.from_tier_models(
        {"fast": _NAMES["fast"], "standard": _NAMES["standard"]},
    ))
    try:
        response = await client.complete(LLMRequest(
            prompt="ping", tier="deep", exact_tier=True, agent_id="a", work_item_id="w",
        ))
    finally:
        await client.close()
    assert response.error_kind == "tier_unavailable"
    assert seen == [], "premise: the router refused deep; no other tier's model was called"


def test_router_exact_tier_skips_any_tier_fallback() -> None:
    registry = ModelRegistry.from_tier_models({"fast": _NAMES["fast"], "standard": _NAMES["standard"]})
    router = ModelRouter(registry=registry)
    loose = router.choose(tier="deep")
    assert loose.chosen_model and loose.fallback is True, "premise: the any-tier fallback exists"
    exact = router.choose(tier="deep", exact_tier=True)
    assert exact.chosen_model == "" and exact.excluded_exact is True
    assert router.preview(tier="deep", exact_tier=True).chosen_model == ""
    assert router.choose(tier="standard", exact_tier=True).chosen_model == _NAMES["standard"]


@pytest.mark.asyncio
async def test_unarmed_chain_and_router_kwargs_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _endpoint(monkeypatch, down={_NAMES["deep"]})
    _runtime, client = _wired()
    calls: list[dict[str, Any]] = []
    real = client.model_router

    class _Recorder:
        def choose(self, *, tier: str, **kw: Any) -> Any:
            calls.append({"tier": tier, **kw})
            return real.choose(tier=tier, **kw)

    client.model_router = _Recorder()
    try:
        response = await client.complete(LLMRequest(prompt="ping", tier="deep"))
    finally:
        await client.close()
    assert response.error is None, "the generic fallback chain still answers"
    assert seen[0] == _NAMES["deep"] and len(set(seen)) > 1
    assert all(set(c) == {"tier"} for c in calls), "no new kwargs reach the router when unarmed"


@pytest.mark.asyncio
async def test_exact_tier_not_set_when_unarmed() -> None:
    from tests.test_ad1324_loop_tier_choice import answer, run

    _r, client, _t = await run([answer()])
    assert [r.exact_tier for r in client.requests] == [False]
