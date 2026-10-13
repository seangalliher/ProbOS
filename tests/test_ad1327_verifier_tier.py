"""AD-1327 Milestone 1: the ``verifier`` LLM tier.

The tier is a peer of the other optional tiers in ``_LLM_TIERS`` (per-tier state,
its own endpoint, probes) but outside ``_TIER_ORDER``: no agent tier choice, no
stakes floor, and the router never serves it with a crew tier's model. Unset, a
verifier request is sent down the standard chain exactly as before.

Drives the real ``OpenAICompatibleClient`` and ``_wire_model_routing`` over an
in-process ``httpx.MockTransport`` (the AD-1324 pattern).

Tests 42-45 (review round 1) are the client seams: pool identity by credential,
the provider's model id, and the answering tier. 42 and 43 need the pool's real
Authorization header, so the ``seam`` fixture patches ``httpx.AsyncClient`` and lets
the REAL ``_build_client`` run; the ``endpoints`` fixture replaces ``_build_client``,
which drops that header.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx
import pytest

from probos import provider_setup
from probos.cognitive import model_router
from probos.cognitive import tier_policy
from probos.cognitive.llm_client import (
    _LLM_TIERS, _TIER_ORDER, TEXT_TIERS, VERIFIER_TIER, OpenAICompatibleClient, _pool_base,
)
from probos.cognitive.model_registry import ModelRegistry
from probos.cognitive.model_router import ModelRouter, ceiling_denials, routed_tiers
from probos.config import CognitiveConfig, LLMRateConfig, ModelRoutingConfig, SystemConfig
from probos.config_models.agentic import TierChoiceConfig
from probos.provider_setup import optional_tier_endpoints, tiers_using_shared_url
from probos.settings.section_registry import get_section
from probos.startup.finalize import _wire_model_routing
from probos.types import LLMRequest, LLMResponse
from tests.test_ad1324_router_floor import _Runtime

_SHARED = "https://shared.invalid/v1"
_NAMES = {"fast": "claude-sonnet-4-6-fast", "standard": "claude-sonnet-4-6", "deep": "claude-opus-4-6"}
_HOSTS = {"fast": "fast.invalid", "standard": "standard.invalid", "deep": "deep.invalid"}
_SHARED_HOST = "shared.invalid"
_SHARED_KEY = "shared-k"
_JUDGE_URL = "https://judge.invalid/v1"
_JUDGE_KEY = "judge-k"
# The real class, captured at import: the ``seam`` fixture replaces ``httpx.AsyncClient`` itself.
_RealAsyncClient = httpx.AsyncClient


class _FakeEndpoints:
    """Records ``(host, model)`` per request and answers 200; a host in ``down`` fails after recording."""

    def __init__(self, down: set[str] | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self.bodies: list[dict[str, Any]] = []
        self.down: set[str] = set(down or ())

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.calls.append((request.url.host, body["model"]))
        self.bodies.append(body)
        if request.url.host in self.down:
            raise httpx.ConnectError("down", request=request)
        # An honest provider echoes the model id it was sent (AD-1327 D9: ``answered_model``).
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "pong"}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 2, "prompt_tokens": 1},
            "model": body["model"],
        })

    @property
    def hosts(self) -> list[str]:
        return [host for host, _model in self.calls]

    @property
    def models(self) -> list[str]:
        return [model for _host, model in self.calls]

    def first_appearances(self) -> list[str]:
        seen: list[str] = []
        for host in self.hosts:
            if host not in seen:
                seen.append(host)
        return seen


@pytest.fixture
def endpoints(monkeypatch: pytest.MonkeyPatch) -> _FakeEndpoints:
    monkeypatch.delenv("PROBOS_LLM_URL", raising=False)
    fake = _FakeEndpoints()

    def build(client: OpenAICompatibleClient, tier: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=client._tier_configs[tier]["base_url"],
            transport=httpx.MockTransport(fake.handle),
        )

    monkeypatch.setattr(OpenAICompatibleClient, "_build_client", build)
    return fake


class _SeamEndpoints(_FakeEndpoints):
    """``_FakeEndpoints`` that also records each request's Authorization header, in step with ``calls``."""

    def __init__(self, down: set[str] | None = None) -> None:
        super().__init__(down)
        self.auths: list[str | None] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.auths.append(request.headers.get("authorization"))
        return super().handle(request)

    @property
    def sent(self) -> list[tuple[str, str, str | None]]:
        """``(host, model, Authorization)`` of every request that reached the transport, oldest first."""
        return list(zip(self.hosts, self.models, self.auths))


@pytest.fixture
def seam(monkeypatch: pytest.MonkeyPatch) -> _SeamEndpoints:
    """Seam double (b): every pool is built by the REAL ``_build_client``, over a MockTransport.

    The ``endpoints`` fixture replaces ``_build_client``, so its pools carry no Authorization header;
    here the header a pool bakes (the key of the tier that built it) is the one the handler sees.
    ``llm_client.httpx`` is the ``httpx`` module, so this replaces ``httpx.AsyncClient`` for the whole
    test: build any other client from ``_RealAsyncClient``.
    """
    monkeypatch.delenv("PROBOS_LLM_URL", raising=False)
    fake = _SeamEndpoints()

    class _Seamed(_RealAsyncClient):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(transport=httpx.MockTransport(fake.handle), **kwargs)

    monkeypatch.setattr("probos.cognitive.llm_client.httpx.AsyncClient", _Seamed)
    return fake


def _cognitive(**overrides: Any) -> CognitiveConfig:
    """Crew tiers on their own hosts; the shared URL is a fifth host nobody should reach."""
    fields: dict[str, Any] = {"llm_base_url": _SHARED}
    for tier in ("fast", "standard", "deep"):
        fields[f"llm_base_url_{tier}"] = f"https://{_HOSTS[tier]}/v1"
        fields[f"llm_model_{tier}"] = _NAMES[tier]
    fields.update(overrides)
    return CognitiveConfig(**fields)


def _wired(cognitive: CognitiveConfig, ceiling: float | None = None) -> tuple[_Runtime, OpenAICompatibleClient]:
    config = SystemConfig(
        cognitive=cognitive,
        model_routing=ModelRoutingConfig(enabled=True, cost_ceiling_per_million_output_tokens=ceiling),
    )
    client = OpenAICompatibleClient(config=cognitive)
    runtime = _Runtime(client)
    _wire_model_routing(runtime=runtime, config=config)
    return runtime, client


async def _complete(cognitive: CognitiveConfig, tier: str, prompt: str = "ping"):
    client = OpenAICompatibleClient(config=cognitive)
    try:
        return await client.complete(LLMRequest(prompt=prompt, tier=tier))
    finally:
        await client.close()


@contextlib.asynccontextmanager
async def _client_of(cognitive: CognitiveConfig, **kwargs: Any) -> AsyncIterator[OpenAICompatibleClient]:
    """A client for several calls (``_complete`` builds one per call), closed on exit."""
    client = OpenAICompatibleClient(config=cognitive, **kwargs)
    try:
        yield client
    finally:
        await client.close()


def _one_url(**overrides: Any) -> CognitiveConfig:
    """Every tier on the one shared URL and key; the verifier judges with ``gpt-5.1`` and its own key."""
    fields: dict[str, Any] = {
        "llm_base_url": _SHARED,
        "llm_api_key": _SHARED_KEY,
        "llm_model_verifier": "gpt-5.1",
        "llm_api_key_verifier": _JUDGE_KEY,
    }
    for tier in ("fast", "standard", "deep"):
        fields[f"llm_model_{tier}"] = _NAMES[tier]
    fields.update(overrides)
    return CognitiveConfig(**fields)


_AUTH_SCHEME = "Bearer"  # the scheme ``_build_client`` bakes into a pool's Authorization header


def _bearer(key: str) -> str:
    """The Authorization header ``_build_client`` bakes for ``key``."""
    return f"{_AUTH_SCHEME} {key}"


def _todays_pools(client: OpenAICompatibleClient) -> set[str]:
    """The pools the client had before AD-1327: one ``_pool_base`` per distinct tier endpoint."""
    return {_pool_base(tc) for tc in client._tier_configs.values()}


_ABSENT = object()  # a provider reply that names no model at all


def _openai_reply() -> dict[str, Any]:
    return {
        "choices": [{"message": {"content": "pong"}, "finish_reason": "stop"}],
        "usage": {"total_tokens": 2, "prompt_tokens": 1},
    }


def _ollama_reply() -> dict[str, Any]:
    return {"message": {"content": "pong"}, "prompt_eval_count": 1, "eval_count": 1}


async def _through_transport(
    call: Callable[..., Awaitable[LLMResponse]], base_url: str, reply: dict[str, Any],
) -> tuple[LLMResponse, list[httpx.Request]]:
    """Run a transport method (``_call_openai`` / ``_call_ollama_native``) over a MockTransport answering ``reply``."""
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        # Bytes encoded here (ASCII escapes, as a provider's ``\ud800`` escape arrives): ``json=`` may encode
        # a lone surrogate strictly and raise before the client ever sees the reply.
        return httpx.Response(
            200, content=json.dumps(reply).encode(), headers={"content-type": "application/json"},
        )

    http = httpx.AsyncClient(base_url=base_url, transport=httpx.MockTransport(handle))
    try:
        response = await call(LLMRequest(prompt="ping", tier="verifier"), "gpt-5.1", http, timeout=5.0)
    finally:
        await http.aclose()
    return response, seen


# 1
def test_verifier_tier_is_in_llm_tiers_and_outside_the_text_chain() -> None:
    assert VERIFIER_TIER == "verifier"
    assert VERIFIER_TIER in _LLM_TIERS
    assert VERIFIER_TIER not in _TIER_ORDER
    assert TEXT_TIERS is _TIER_ORDER
    assert provider_setup.OPTIONAL_TIERS[-1] == "verifier"
    assert list(provider_setup.TIER_CONFIGURED_CHECKS) == list(provider_setup.OPTIONAL_TIERS)


# 2
def test_tier_config_verifier_unset_has_no_model_and_the_shared_endpoint() -> None:
    cfg = CognitiveConfig(
        llm_base_url=_SHARED, llm_api_key="shared-key",
        llm_base_url_standard="https://standard.invalid/v1", llm_model_standard="m-std",
    )
    assert cfg.tier_config("standard")["base_url"] != _SHARED  # premise: standard's URL differs
    resolved = cfg.tier_config("verifier")
    assert resolved["model"] is None
    assert resolved["base_url"] == _SHARED
    assert resolved["api_key"] == "shared-key"


# 3
def test_tier_config_verifier_set_uses_its_own_fields_then_the_shared_ones() -> None:
    own = CognitiveConfig(
        llm_base_url=_SHARED, llm_api_key="shared-key",
        llm_model_verifier="judge-m", llm_base_url_verifier="https://judge.invalid/v1",
        llm_api_key_verifier="judge-key", llm_timeout_verifier=7.5, llm_api_format_verifier="ollama",
    )
    resolved = own.tier_config("verifier")
    assert resolved["model"] == "judge-m"
    assert resolved["base_url"] == "https://judge.invalid/v1"
    assert resolved["api_key"] == "judge-key"
    assert resolved["timeout"] == 7.5
    assert resolved["api_format"] == "ollama"

    only_model = CognitiveConfig(
        llm_base_url=_SHARED, llm_api_key="shared-key", llm_timeout_seconds=33.0,
        llm_model_verifier="judge-m",
    )
    resolved = only_model.tier_config("verifier")
    assert resolved["model"] == "judge-m"
    assert resolved["base_url"] == _SHARED
    assert resolved["api_key"] == "shared-key"
    assert resolved["timeout"] == 33.0
    assert resolved["api_format"] == "openai"


# 4
def test_blank_verifier_model_is_unset() -> None:
    assert CognitiveConfig(llm_model_verifier="").llm_model_verifier is None
    assert CognitiveConfig(llm_model_verifier="   ").llm_model_verifier is None
    assert CognitiveConfig(llm_model_verifier="m").llm_model_verifier == "m"


# 5
def test_client_state_covers_every_tier_including_verifier() -> None:
    client = OpenAICompatibleClient(config=_cognitive(llm_model_verifier="judge-m"))
    expected = set(_LLM_TIERS)
    assert "verifier" in expected
    assert set(client._tier_configs) == expected
    assert set(client._consecutive_failures) == expected
    assert set(client._consecutive_successes) == expected
    assert set(client._request_timestamps) == expected
    assert set(client._consecutive_429s) == expected
    assert set(client.models) == expected
    assert set(client.tier_info()) == expected
    assert set(client.get_health_status()["tiers"]) == expected


# 6
def test_unset_verifier_tier_is_not_probed() -> None:
    def run(cfg: CognitiveConfig) -> tuple[dict[str, bool], list[str]]:
        client = OpenAICompatibleClient(config=cfg)
        probed: list[str] = []

        async def _fake_check_endpoint(tier: str, **_kw: Any) -> bool:
            probed.append(tier)
            return True

        client._check_endpoint = _fake_check_endpoint  # type: ignore[method-assign]
        return asyncio.run(client.check_connectivity()), probed

    results, probed = run(_cognitive())
    assert probed, "premise: the probe did call _check_endpoint for the configured tiers"
    assert results["verifier"] is False
    assert "verifier" not in probed

    # Negative control: a model and its OWN base URL make it probed (a tier on an
    # already-checked endpoint reuses that result without a call).
    results, probed = run(_cognitive(
        llm_model_verifier="judge-m", llm_base_url_verifier="https://judge.invalid/v1",
    ))
    assert "verifier" in probed
    assert results["verifier"] is True


# 7
@pytest.mark.asyncio
async def test_unset_verifier_tier_request_is_sent_down_the_standard_chain(endpoints: _FakeEndpoints) -> None:
    cfg = _cognitive()
    verifier = await _complete(cfg, "verifier")
    assert verifier.error is None
    assert len(endpoints.calls) == 1
    assert endpoints.calls[0] == (_HOSTS["standard"], _NAMES["standard"])
    verifier_body = endpoints.bodies[0]

    standard = await _complete(cfg, "standard")
    assert standard.error is None
    assert len(endpoints.calls) == 2
    assert endpoints.calls[1] == (_HOSTS["standard"], _NAMES["standard"])
    assert endpoints.bodies[1] == verifier_body


# 8
@pytest.mark.asyncio
async def test_configured_verifier_request_goes_to_its_endpoint_with_its_model(endpoints: _FakeEndpoints) -> None:
    cfg = _cognitive(llm_model_verifier="gpt-5.1", llm_base_url_verifier="https://judge.invalid/v1")
    response = await _complete(cfg, "verifier")
    assert response.error is None
    assert endpoints.calls == [("judge.invalid", "gpt-5.1")]


# 9
@pytest.mark.asyncio
async def test_verifier_falls_back_to_standard_then_fast_then_deep(endpoints: _FakeEndpoints) -> None:
    endpoints.down = {"judge.invalid", _HOSTS["standard"]}
    cfg = _cognitive(llm_model_verifier="gpt-5.1", llm_base_url_verifier="https://judge.invalid/v1")
    response = await _complete(cfg, "verifier")
    # A failed endpoint may be retried once after a pool refresh (BF-665): compare first appearances.
    assert endpoints.first_appearances() == ["judge.invalid", _HOSTS["standard"], _HOSTS["fast"]]
    assert response.error is None
    assert response.model == _NAMES["fast"]
    assert endpoints.calls[-1] == (_HOSTS["fast"], _NAMES["fast"])
    assert _HOSTS["deep"] not in endpoints.hosts


# 10
def test_agent_tier_choice_and_stakes_floor_never_offer_verifier() -> None:
    assert "verifier" not in tier_policy.TIER_RANK
    assert TierChoiceConfig(stakes_floor={"high": "verifier"}).stakes_floor == {}
    assert model_router._tier_rank("verifier") == -1


# 11
def test_routed_tiers_add_the_verifier_only_when_configured() -> None:
    assert routed_tiers(CognitiveConfig()) is TEXT_TIERS
    assert routed_tiers(CognitiveConfig(llm_model_verifier="judge-m")) == (*TEXT_TIERS, "verifier")


# 12
def test_build_model_routing_registers_the_verifier_model_under_its_own_tier() -> None:
    def build(cognitive: CognitiveConfig) -> ModelRouter:
        router = model_router.build_model_routing(
            SystemConfig(cognitive=cognitive, model_routing=ModelRoutingConfig(enabled=True)),
        )
        assert router is not None
        return router

    configured = build(_cognitive(llm_model_verifier="gpt-5.1"))
    assert [d.name for d in configured.registry.by_tier("verifier")] == ["gpt-5.1"]

    unset = build(_cognitive())
    assert unset.registry.by_tier("verifier") == []
    assert {d.tier for d in unset.registry.all()} == set(TEXT_TIERS)
    for tier in TEXT_TIERS:
        assert [d.name for d in unset.registry.by_tier(tier)] == [_NAMES[tier]]


# 13
def test_verifier_model_never_substitutes_for_a_crew_tier() -> None:
    registry = ModelRegistry.from_tier_models({"verifier": "claude-opus-4-6", "standard": "claude-sonnet-4-6"})
    assert registry.all()[0].tier == "verifier"  # premise: the verifier entry comes first
    assert ModelRouter(registry=registry).choose(tier="fast").chosen_model == "claude-sonnet-4-6"

    only_verifier = ModelRegistry.from_tier_models({"verifier": "claude-opus-4-6"})
    assert only_verifier.all()[0].tier == "verifier"
    assert ModelRouter(registry=only_verifier).choose(tier="fast").chosen_model == ""


# 14
@pytest.mark.asyncio
async def test_router_never_serves_a_verifier_attempt_with_a_crew_model(endpoints: _FakeEndpoints) -> None:
    cfg = _cognitive(llm_model_verifier="gpt-5.1", llm_base_url_verifier="https://judge.invalid/v1")
    runtime, client = _wired(cfg)
    try:
        assert runtime.model_registry.mark_unavailable("gpt-5.1") is True  # premise
        response = await client.complete(LLMRequest(prompt="ping", tier="verifier"))
    finally:
        await client.close()
    assert response.error is None
    assert "judge.invalid" not in endpoints.hosts
    assert endpoints.calls == [(_HOSTS["standard"], _NAMES["standard"])]


# 15
@pytest.mark.asyncio
async def test_cost_ceiling_governs_verifier_calls_and_probe(endpoints: _FakeEndpoints) -> None:
    cfg = _cognitive(llm_model_verifier="claude-opus-4-6", llm_base_url_verifier="https://judge.invalid/v1")
    runtime, client = _wired(cfg, ceiling=20.0)
    try:
        response = await client.complete(LLMRequest(prompt="ping", tier="verifier"))
        assert response.error is None
        assert endpoints.calls == [(_HOSTS["standard"], _NAMES["standard"])]
        endpoints.calls.clear()
        results = await client.check_connectivity()
    finally:
        await client.close()
    assert "verifier" not in results
    assert "judge.invalid" not in endpoints.hosts
    assert endpoints.calls, "premise: the probe did reach the admitted tiers"

    config = SystemConfig(
        cognitive=cfg,
        model_routing=ModelRoutingConfig(enabled=True, cost_ceiling_per_million_output_tokens=20.0),
    )
    assert "verifier" in ceiling_denials(config)

    # Negative control: a ceiling that admits the model sends to the judge host.
    endpoints.calls.clear()
    _runtime, admitted = _wired(cfg, ceiling=100.0)
    try:
        response = await admitted.complete(LLMRequest(prompt="ping", tier="verifier"))
    finally:
        await admitted.close()
    assert response.error is None
    assert endpoints.calls == [("judge.invalid", "claude-opus-4-6")]


# 16
def test_provider_setup_keeps_the_shared_url_for_a_verifier_with_a_model() -> None:
    with_model = optional_tier_endpoints(
        "cognitive:\n  llm_base_url: https://s.invalid/v1\n  llm_model_verifier: judge-m\n",
    )
    assert with_model["verifier"].inherited is True  # premise: no own URL
    assert tiers_using_shared_url(with_model).get("verifier") == "judge-m"

    without_model = optional_tier_endpoints("cognitive:\n  llm_base_url: https://s.invalid/v1\n")
    assert without_model["verifier"].model is None
    assert "verifier" not in tiers_using_shared_url(without_model)


# 17
def test_settings_section_offers_the_verifier_fields() -> None:
    section = get_section("llm_tiers")
    assert section is not None
    field_ids = {field.field_id for field in section.fields}
    assert {
        "cognitive.llm_base_url_verifier", "cognitive.llm_model_verifier", "cognitive.llm_timeout_verifier",
    } <= field_ids


# 42
@pytest.mark.asyncio
async def test_verifier_with_its_own_key_on_a_shared_url_gets_its_own_pool(seam: _SeamEndpoints) -> None:
    async with _client_of(_one_url()) as client:
        verifier_key = client._client_key("verifier")
        standard_key = client._client_key("standard")
        assert verifier_key == standard_key + "|verifier"
        assert len(client._clients) == 2
        assert set(client._clients) == _todays_pools(client) | {verifier_key}
        for tier in _LLM_TIERS:
            if tier != "verifier":
                assert client._client_key(tier) == _pool_base(client._tier_configs[tier]), tier
        assert client._clients[verifier_key].headers["Authorization"] == _bearer(_JUDGE_KEY)
        assert client._clients[standard_key].headers["Authorization"] == _bearer(_SHARED_KEY)
        assert verifier_key in client._client_pool_states
        assert verifier_key in client._endpoint_failure_states
        assert verifier_key in client._endpoint_semaphores
        pool_names = [
            *client._clients, *client._client_pool_states, *client._endpoint_failure_states,
            *client._endpoint_semaphores,
        ]
        assert not [name for name in pool_names if _JUDGE_KEY in name or _SHARED_KEY in name]

        # Real requests: each tier's request carries the key of the pool it uses.
        verifier = await client.complete(LLMRequest(prompt="judge this", tier="verifier"))
        assert verifier.error is None
        assert seam.sent == [(_SHARED_HOST, "gpt-5.1", _bearer(_JUDGE_KEY))]  # premise: the handler saw it
        standard = await client.complete(LLMRequest(prompt="crew work", tier="standard"))
        assert standard.error is None
        assert seam.sent[1:] == [(_SHARED_HOST, _NAMES["standard"], _bearer(_SHARED_KEY))]

        # The probe of the verifier's pool is a gpt-5.1 request with the verifier's key.
        before = len(seam.sent)
        reachable = await client.check_connectivity()
        probes = seam.sent[before:]
        assert any(model == "gpt-5.1" for _host, model, _auth in probes), "premise: the handler saw the probe"
        assert (_SHARED_HOST, "gpt-5.1", _bearer(_JUDGE_KEY)) in probes
        assert (_SHARED_HOST, _NAMES["fast"], _bearer(_SHARED_KEY)) in probes
        assert reachable["verifier"] is True

    # Control: the same key as the shared pool's keeps today's one pool.
    async with _client_of(_one_url(llm_api_key_verifier=_SHARED_KEY)) as same_key:
        configs = same_key._tier_configs
        assert configs["verifier"]["model"] == "gpt-5.1"  # premise: configured ...
        assert configs["verifier"]["api_key"] == configs["standard"]["api_key"]  # ... with the shared pool's key
        assert same_key._client_key("verifier") == same_key._client_key("standard")
        assert set(same_key._clients) == _todays_pools(same_key) == {f"{_SHARED}|openai"}

    # Control: an unset verifier keeps today's pool, though its key differs from fast's, the first tier to build it.
    async with _client_of(
        _one_url(llm_model_verifier=None, llm_api_key_verifier=None, llm_api_key_fast="fast-k"),
    ) as unset:
        configs = unset._tier_configs
        assert not configs["verifier"]["model"]  # premise: unset ...
        assert configs["verifier"]["api_key"] != configs["fast"]["api_key"]  # ... and its key differs from fast's
        assert unset._client_key("verifier") == unset._client_key("fast")
        assert set(unset._clients) == _todays_pools(unset) == {f"{_SHARED}|openai"}

    # Control: its own URL and key is its own pool by URL, with no suffix.
    async with _client_of(_one_url(llm_base_url_verifier=_JUDGE_URL)) as own_url:
        configs = own_url._tier_configs
        assert configs["verifier"]["base_url"] != configs["standard"]["base_url"]  # premise: its own URL
        assert own_url._client_key("verifier") == f"{_JUDGE_URL}|openai"
        assert set(own_url._clients) == _todays_pools(own_url) == {f"{_SHARED}|openai", f"{_JUDGE_URL}|openai"}
        assert own_url._clients[own_url._client_key("verifier")].headers["Authorization"] == _bearer(_JUDGE_KEY)


# 43
@pytest.mark.asyncio
async def test_refreshed_verifier_pool_keeps_the_verifier_key(seam: _SeamEndpoints) -> None:
    async with _client_of(_one_url()) as client:
        verifier_key = client._client_key("verifier")
        standard_key = client._client_key("standard")
        assert verifier_key != standard_key  # premise: the verifier has its own pool
        old_verifier_pool = client._clients[verifier_key]
        assert old_verifier_pool.headers["Authorization"] == _bearer(_JUDGE_KEY)  # premise: it starts on that key
        standard_pool = client._clients[standard_key]
        verifier_generation = client._client_pool_states[verifier_key].generation
        standard_generation = client._client_pool_states[standard_key].generation

        assert await client._refresh_client("verifier", observed_generation=verifier_generation) is True

        new_verifier_pool = client._clients[verifier_key]
        assert new_verifier_pool is not old_verifier_pool  # premise: it was rebuilt
        assert new_verifier_pool.headers["Authorization"] == _bearer(_JUDGE_KEY)
        assert client._client_pool_states[verifier_key].generation == verifier_generation + 1
        assert client._clients[standard_key] is standard_pool
        assert client._client_pool_states[standard_key].generation == standard_generation
        assert standard_pool.headers["Authorization"] == _bearer(_SHARED_KEY)

        # The rebuilt pool is the one the next verifier request goes through.
        response = await client.complete(LLMRequest(prompt="after the refresh", tier="verifier"))
        assert response.error is None
        assert seam.sent == [(_SHARED_HOST, "gpt-5.1", _bearer(_JUDGE_KEY))]


_FAST_KEY = "a-k"  # the shared key (fast's, deep's) and, in the F4 config, the verifier's
_STANDARD_KEY = "b-k"  # standard's own key: the one a standard-driven pool rebuild bakes


def _f4(**overrides: Any) -> CognitiveConfig:
    """Review round 2, F4: one URL; fast and the verifier share ``a-k``, standard has its own ``b-k``."""
    fields: dict[str, Any] = {
        "llm_api_key": _FAST_KEY, "llm_api_key_standard": _STANDARD_KEY, "llm_api_key_verifier": _FAST_KEY,
    }
    fields.update(overrides)
    return _one_url(**fields)


def _empty_first_reply_for(seam: _SeamEndpoints, monkeypatch: pytest.MonkeyPatch, model: str) -> None:
    """The seam answers the FIRST request for ``model`` with HTTP 200 and empty content (BF-612 recovery)."""
    answer = seam.handle
    state = {"emptied": False}

    def handle(request: httpx.Request) -> httpx.Response:
        response = answer(request)
        if seam.models[-1] == model and not state["emptied"]:
            state["emptied"] = True
            return httpx.Response(200, json={
                "choices": [{"message": {"content": ""}, "finish_reason": "stop"}],
                "usage": {"total_tokens": 2, "prompt_tokens": 1},
                "model": model,
            })
        return response

    monkeypatch.setattr(seam, "handle", handle)


# 49
@pytest.mark.asyncio
async def test_verifier_never_shares_a_pool_a_sibling_rebuilds_with_another_key(
    seam: _SeamEndpoints, monkeypatch: pytest.MonkeyPatch,
) -> None:
    standard_model = _NAMES["standard"]
    _empty_first_reply_for(seam, monkeypatch, standard_model)
    async with _client_of(_f4()) as client:
        standard_key = client._client_key("standard")
        verifier_key = client._client_key("verifier")
        assert client._client_key("fast") == standard_key  # premise: one shared pool ...
        assert client._clients[standard_key].headers["Authorization"] == _bearer(_FAST_KEY)  # ... fast built it
        assert client._tier_configs["verifier"]["api_key"] == _FAST_KEY  # premise: the verifier's key is fast's
        assert verifier_key == standard_key + "|verifier"  # a sibling (standard) differs, so it is isolated
        assert client._clients[verifier_key].headers["Authorization"] == _bearer(_FAST_KEY)

        # The real recovery: standard's empty reply rebuilds the shared pool with standard's key.
        recovered = await client.complete(LLMRequest(prompt="crew work", tier="standard"))
        assert recovered.error is None and recovered.content
        assert seam.models.count(standard_model) == 2  # premise: the handler saw the empty one, then the retry
        assert client._client_pool_states[standard_key].generation == 1  # premise: the pool was rebuilt
        assert client._clients[standard_key].headers["Authorization"] == _bearer(_STANDARD_KEY)
        assert seam.sent[-1] == (_SHARED_HOST, standard_model, _bearer(_STANDARD_KEY))

        before = len(seam.sent)
        verdict_reply = await client.complete(LLMRequest(prompt="judge this", tier="verifier"))
        assert verdict_reply.error is None
        assert seam.sent[before:] == [(_SHARED_HOST, "gpt-5.1", _bearer(_FAST_KEY))]
        assert client._clients[verifier_key].headers["Authorization"] == _bearer(_FAST_KEY)

    # Control (i): all keys equal is one shared pool (one probe, one breaker), as before AD-1327.
    _empty_first_reply_for(seam, monkeypatch, standard_model)  # re-arm before the pools are built: the same recovery
    async with _client_of(_f4(llm_api_key_standard=None, llm_api_key_verifier=None)) as same:
        configs = same._tier_configs
        assert configs["verifier"]["model"] == "gpt-5.1"  # premise: configured ...
        assert {configs[tier]["api_key"] for tier in _LLM_TIERS} == {_FAST_KEY}  # ... and every key is the same
        assert same._client_key("verifier") == same._client_key("standard")
        async with _client_of(_f4(llm_api_key_standard=None, llm_api_key_verifier=None, llm_model_verifier=None)) as unset:
            assert set(same._clients) == set(unset._clients) == _todays_pools(same)
        before = len(seam.sent)
        recovered = await same.complete(LLMRequest(prompt="more crew work", tier="standard"))
        assert recovered.error is None and recovered.content
        standard_pool = same._client_key("standard")
        assert same._client_pool_states[standard_pool].generation == 1  # premise: the pool was rebuilt
        assert same._clients[standard_pool].headers["Authorization"] == _bearer(_FAST_KEY)
        verdict_reply = await same.complete(LLMRequest(prompt="judge this", tier="verifier"))
        assert verdict_reply.error is None
        assert seam.sent[-1] == (_SHARED_HOST, "gpt-5.1", _bearer(_FAST_KEY))
        assert len(seam.sent) == before + 3  # premise: the empty reply, its retry and the judge reached the handler

    # Control (ii): an unset verifier keeps the shared pool whatever standard's key is.
    async with _client_of(_f4(llm_model_verifier=None, llm_api_key_verifier=None)) as unset_verifier:
        configs = unset_verifier._tier_configs
        assert not configs["verifier"]["model"]  # premise: unset ...
        assert configs["standard"]["api_key"] == _STANDARD_KEY  # ... while standard has its own key
        assert unset_verifier._client_key("verifier") == _pool_base(configs["verifier"])  # the base key, no suffix
        async with _client_of(_f4(llm_api_key_standard=None, llm_model_verifier=None, llm_api_key_verifier=None)) as one_key:
            assert set(unset_verifier._clients) == set(one_key._clients) == _todays_pools(unset_verifier)


# 44
@pytest.mark.asyncio
async def test_transports_carry_the_providers_model_id() -> None:
    replies = [
        ("gpt-5.1-2025-11-13", "gpt-5.1-2025-11-13"),
        (_ABSENT, ""),
        (None, ""),
        (7, ""),
        ("x\x00y", "x\x00y"),  # verbatim: the policy that persists it bounds it (test 23)
        ("gpt-\ud800-5", "gpt-\ud800-5"),  # a lone surrogate (review round 2): verbatim too, bounded by the policy
    ]
    async with _client_of(_cognitive()) as client:
        transports = [
            ("openai", client._call_openai, "https://judge.invalid/v1/", "/v1/chat/completions", _openai_reply),
            ("ollama", client._call_ollama_native, "https://judge.invalid/", "/api/chat", _ollama_reply),
        ]
        for name, call, base_url, path, build_reply in transports:
            for named, expected in replies:
                reply = build_reply()
                if named is not _ABSENT:
                    reply["model"] = named
                response, seen = await _through_transport(call, base_url, reply)
                case = f"{name} transport, reply model {named!r}"
                assert [(r.url.path, json.loads(r.content)["model"]) for r in seen] == [(path, "gpt-5.1")], case
                assert response.answered_model == expected, case
                assert response.model == "gpt-5.1", case
                assert response.answered_tier is None, case


# 45
@pytest.mark.asyncio
async def test_attempt_loop_records_the_answering_tier_and_replays_keep_it(endpoints: _FakeEndpoints) -> None:
    default = LLMResponse(content="x")
    assert default.answered_tier is None and default.answered_model is None  # the default pin

    judge = "judge.invalid"
    cfg = _cognitive(llm_model_verifier="gpt-5.1", llm_base_url_verifier=_JUDGE_URL)
    async with _client_of(cfg) as client:
        # The verifier's own attempt answers.
        first = await client.complete(LLMRequest(prompt="judge this", tier="verifier"))
        assert endpoints.calls == [(judge, "gpt-5.1")]  # premise: the judge host served it
        assert first.error is None
        assert (first.answered_tier, first.answered_model) == ("verifier", "gpt-5.1")
        assert (first.tier, first.model) == ("verifier", "gpt-5.1")

        # The judge host is down: the standard attempt answers, and ``tier`` stays the requested one.
        endpoints.down = {judge}
        mark = len(endpoints.calls)
        fallback = await client.complete(LLMRequest(prompt="judge that", tier="verifier"))
        attempted = endpoints.calls[mark:]
        assert attempted[0] == (judge, "gpt-5.1")  # premise: the verifier attempt was made, and failed
        assert attempted[-1] == (_HOSTS["standard"], _NAMES["standard"])
        assert fallback.error is None
        assert (fallback.answered_tier, fallback.answered_model) == ("standard", _NAMES["standard"])
        assert fallback.tier == "verifier"

        # Every host down: the final cache replay still says who answered each cached response.
        endpoints.down = {judge, *_HOSTS.values()}
        mark = len(endpoints.calls)
        replay = await client.complete(LLMRequest(prompt="judge this", tier="verifier"))
        assert {host for host, _model in endpoints.calls[mark:]} == endpoints.down  # premise: the whole chain failed
        assert replay.cached is True
        assert (replay.answered_tier, replay.answered_model) == (first.answered_tier, first.answered_model)
        assert replay.tier == "verifier"
        replay_fallback = await client.complete(LLMRequest(prompt="judge that", tier="verifier"))
        assert replay_fallback.cached is True
        assert (replay_fallback.answered_tier, replay_fallback.answered_model) == ("standard", _NAMES["standard"])

    # The rate-limit replay keeps both fields too: one standard request a minute, the second is over budget.
    endpoints.down = set()
    limits = LLMRateConfig(rpm_standard=1, max_wait_seconds=0.0)
    async with _client_of(_cognitive(), rate_config=limits) as limited:
        mark = len(endpoints.calls)
        filled = await limited.complete(LLMRequest(prompt="within the window", tier="standard"))
        replayed = await limited.complete(LLMRequest(prompt="within the window", tier="standard"))
        assert len(endpoints.calls) == mark + 1  # premise: only the first reached a host
        assert replayed.cached is True  # premise: the second was budget-exhausted and replayed
        assert (filled.answered_tier, filled.answered_model) == ("standard", _NAMES["standard"])
        assert (replayed.answered_tier, replayed.answered_model) == (filled.answered_tier, filled.answered_model)

    renamed = dataclasses.replace(first, content="y")
    assert (renamed.content, renamed.answered_tier, renamed.answered_model) == ("y", "verifier", "gpt-5.1")
