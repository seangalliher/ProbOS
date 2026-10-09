"""AD-1324 amendment 2 (finding 3): a router fault under a floor or exact request fails closed.

Real client and endpoint spy. An unarmed request keeps the legacy degrade-to-configured-model.
"""

from __future__ import annotations

from typing import Any

import pytest

from probos.types import LLMRequest
from tests.test_ad1324_router_floor import _wired, endpoint  # noqa: F401  (fixture)


class _Boom:
    def choose(self, **_kwargs: Any) -> Any:
        raise RuntimeError("router down")


@pytest.mark.asyncio
async def test_unarmed_request_degrades_to_configured_model(endpoint: Any) -> None:  # noqa: F811
    _runtime, client = _wired()
    client.model_router = _Boom()
    try:
        response = await client.complete(LLMRequest(prompt="plain", tier="standard"))
    finally:
        await client.close()
    assert response.error is None and len(endpoint.bodies) == 1, "premise: legacy path still sends"


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [{"min_tier": "deep"}, {"min_tier": "fast"}])
async def test_floor_request_with_router_fault_sends_nothing(endpoint: Any, kwargs: dict) -> None:  # noqa: F811
    _runtime, client = _wired()
    client.model_router = _Boom()
    try:
        response = await client.complete(LLMRequest(prompt="stakes", tier="deep", **kwargs))
    finally:
        await client.close()
    assert endpoint.bodies == []
    assert response.error_kind == "tier_route_unverifiable"
    assert response.refusal_cause == "route_unverifiable"
    assert response.content in ("", None)


@pytest.mark.asyncio
async def test_exact_request_with_router_fault_sends_nothing(endpoint: Any) -> None:  # noqa: F811
    _runtime, client = _wired()
    client.model_router = _Boom()
    try:
        response = await client.complete(LLMRequest(prompt="x", tier="standard", exact_tier=True))
    finally:
        await client.close()
    assert endpoint.bodies == [] and response.error_kind == "tier_route_unverifiable"