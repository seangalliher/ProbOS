"""AD-1324 amendment 2 (finding 1): the served tier is request-local, never client state.

Real ``OpenAICompatibleClient`` + ``ModelRouter`` wired through ``_wire_model_routing``; two
overlapping requests are served by different tiers while the first is still in flight.
"""

from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from probos.cognitive import llm_client as llm_mod
from probos.cognitive.llm_client import OpenAICompatibleClient, RouteResult
from probos.types import LLMRequest
from tests.test_ad1324_router_floor import _NAMES, _wired


class _SlowEndpoint:
    def __init__(self) -> None:
        self.bodies: list[dict[str, Any]] = []
        self.release = asyncio.Event()

    async def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.bodies.append(body)
        if body["model"] == _NAMES["fast"]:
            await self.release.wait()  # the fast-tier request stays in flight until released
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "pong"}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 2, "prompt_tokens": 1},
        })


@pytest.fixture
def slow(monkeypatch: pytest.MonkeyPatch) -> _SlowEndpoint:
    monkeypatch.delenv("PROBOS_LLM_URL", raising=False)
    fake = _SlowEndpoint()

    def build(client: OpenAICompatibleClient, tier: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=client._tier_configs[tier]["base_url"], transport=httpx.MockTransport(fake.handle),
        )

    monkeypatch.setattr(OpenAICompatibleClient, "_build_client", build)
    return fake


@pytest.mark.asyncio
async def test_overlapping_requests_each_cache_with_their_own_served_tier(slow: _SlowEndpoint) -> None:
    _runtime, client = _wired()
    try:
        first = asyncio.create_task(client.complete(LLMRequest(prompt="slow", tier="fast", min_tier="fast")))
        for _ in range(200):
            if slow.bodies:
                break
            await asyncio.sleep(0.005)
        assert [b["model"] for b in slow.bodies] == [_NAMES["fast"]], "premise: the fast request is in flight"
        second = await client.complete(LLMRequest(prompt="quick", tier="deep", min_tier="deep"))
        assert second.error is None and not first.done(), "premise: deep finished while fast is in flight"
        slow.release.set()
        assert (await first).error is None
    finally:
        slow.release.set()
        await client.close()
    by_prompt = {key: tier for key, tier in client._cache_provenance.items()}
    assert sorted(by_prompt.values()) == ["deep", "fast"], by_prompt
    assert next(k for k, v in by_prompt.items() if v == "fast") != next(k for k, v in by_prompt.items() if v == "deep")


def test_client_has_no_route_served_attribute() -> None:
    client = OpenAICompatibleClient.__new__(OpenAICompatibleClient)
    assert not hasattr(client, "_route_served")
    tree = ast.parse(Path(llm_mod.__file__).read_text(encoding="utf-8"))
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    names |= {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "_route_served" not in names


def test_resolve_route_returns_a_request_local_route_result() -> None:
    _runtime, client = _wired()
    route = client._resolve_route_for_tier("deep", min_tier="deep")
    assert isinstance(route, RouteResult) and route.served_tier == "deep" and route.model == _NAMES["deep"]
    assert client._resolve_model_for_tier("deep") == _NAMES["deep"]


@pytest.mark.asyncio
async def test_unarmed_resolution_passes_no_new_kwargs(slow: _SlowEndpoint, monkeypatch: pytest.MonkeyPatch) -> None:
    slow.release.set()
    _runtime, client = _wired()
    seen: list[tuple[tuple, dict]] = []
    original = client._resolve_model_for_tier

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(client, "_resolve_model_for_tier", spy)
    try:
        response = await client.complete(LLMRequest(prompt="plain", tier="standard"))
    finally:
        await client.close()
    assert response.error is None
    assert seen == [(("standard",), {})], "premise: the unarmed path called the resolver, with no new kwargs"
    assert client._cache_provenance == {}