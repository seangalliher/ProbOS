"""BF-886 (#1474): model routing honours the configured tier models and cost ceiling.

AD-463 wired a ``ModelRouter`` whose registry held only built-in model names,
so with routing on -- the default -- every ``fast``, ``standard`` and ``deep``
call went out under the registry's name instead of the operator's, and the
configured cost ceiling was never read. The seam tests drive the real startup
wiring (``_wire_model_routing``), the real ``OpenAICompatibleClient`` and an
in-process ``httpx.MockTransport``, and read the model name from the body of
the request the client sends.

Unknown prices (A-1): a configured model the built-in catalog does not price is
registered at 0.0, and with a ceiling configured an unknown price fails it, as
#1474 requires; wiring logs an ERROR naming each tier left without an
admissible model, the ceiling and the remedy. A probe, a warm-up and a doctor
check are generation requests too, so none is sent for such a tier, and its
exclusion is never reported as an outage or allowed to select the mock client.
"""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from io import StringIO
from typing import Any

import httpx
import pytest
from rich.console import Console

from probos import __main__ as main_mod
from probos.cognitive.llm_client import MockLLMClient, OpenAICompatibleClient
from probos.cognitive.model_registry import ModelDescriptor, ModelRegistry
from probos.cognitive.model_router import ModelRouter, RoutingDecision
from probos.config import CognitiveConfig, ModelRoutingConfig, SystemConfig
from probos.events import EventType
from probos.startup.finalize import _wire_model_routing
from probos.types import LLMRequest

_TEXT_TIERS = ("fast", "standard", "deep")
_NAMES = {
    "fast": "bf886-fast-model",
    "standard": "bf886-standard-model",
    "deep": "bf886-deep-model",
}
_PRICED_MODELS = {
    "fast": "claude-sonnet-4-6-fast",
    "standard": "claude-sonnet-4-6",
    "deep": "claude-opus-4-6",
}
_ROUTER_LOGGER = "probos.cognitive.model_router"


class _Endpoint:
    """In-process OpenAI-compatible endpoint that records each request body."""

    def __init__(self) -> None:
        self.bodies: list[dict[str, Any]] = []
        self.paths: list[str] = []
        self.down = False

    def handle(self, request: httpx.Request) -> httpx.Response:
        assert request.url.host == "offline.invalid", "a test reached an unowned endpoint"
        self.paths.append(request.url.path)
        self.bodies.append(json.loads(request.content) if request.content else {})
        if self.down:
            raise httpx.ConnectError("endpoint down", request=request)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "pong"}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 2, "prompt_tokens": 1},
        })

    @property
    def models(self) -> list[str]:
        return [body.get("model") for body in self.bodies]


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
    """What ``_wire_model_routing`` reads from the runtime, and what it writes."""

    def __init__(self, llm_client: Any) -> None:
        self.llm_client = llm_client
        self.model_registry: Any = "unset"
        self.model_router: Any = "unset"
        self.events: list[tuple[Any, dict[str, Any]]] = []

    def emit_event(self, event_type: Any, data: dict[str, Any]) -> None:
        self.events.append((event_type, data))

    def of(self, event_type: EventType) -> list[dict[str, Any]]:
        return [data for et, data in self.events if et == event_type]


def _config(
    *, enabled: bool = True, ceiling: float | None = None, **models: str,
) -> SystemConfig:
    return SystemConfig(
        cognitive=CognitiveConfig(llm_base_url="https://offline.invalid/v1/", **models),
        model_routing=ModelRoutingConfig(
            enabled=enabled, cost_ceiling_per_million_output_tokens=ceiling,
        ),
    )


def _named(**overrides: str) -> dict[str, str]:
    names = {**_NAMES, **overrides}
    return {f"llm_model_{tier}": name for tier, name in names.items()}


def _priced(**overrides: str) -> dict[str, str]:
    names = {**_PRICED_MODELS, **overrides}
    return {f"llm_model_{tier}": name for tier, name in names.items()}


def _wired(config: SystemConfig) -> tuple[_Runtime, OpenAICompatibleClient]:
    client = OpenAICompatibleClient(config=config.cognitive)
    runtime = _Runtime(client)
    _wire_model_routing(runtime=runtime, config=config)
    return runtime, client


def _catalog_price(name: str) -> float:
    descriptor = ModelRegistry().get(name)
    assert descriptor is not None, f"premise: {name} is in the built-in catalog"
    return descriptor.cost_per_million_output_tokens


# ----- The seam: SystemConfig -> startup wiring -> LLM client -> request -----


@pytest.mark.asyncio
@pytest.mark.parametrize("tier", _TEXT_TIERS)
async def test_routed_call_sends_the_configured_tier_model(
    endpoint: _Endpoint, tier: str,
) -> None:
    assert ModelRegistry().get(_NAMES[tier]) is None  # premise: no built-in entry
    runtime, client = _wired(_config(**_named()))
    try:
        assert runtime.model_router is not None
        assert client.model_router is runtime.model_router  # premise: routing is on
        response = await client.complete(LLMRequest(prompt="ping", tier=tier))
    finally:
        await client.close()
    assert response.error is None
    assert endpoint.models == [_NAMES[tier]]
    assert [e["chosen_model"] for e in runtime.of(EventType.MODEL_ROUTED)] == [_NAMES[tier]]


@pytest.mark.asyncio
async def test_fast_and_standard_sharing_one_name_each_send_it(endpoint: _Endpoint) -> None:
    shared = "bf886-shared-model"
    runtime, client = _wired(_config(**_named(fast=shared, standard=shared)))
    try:
        for tier in ("fast", "standard"):
            response = await client.complete(LLMRequest(prompt="ping", tier=tier))
            assert response.error is None
    finally:
        await client.close()
    assert endpoint.models == [shared, shared]
    assert [d.name for d in runtime.model_registry.by_tier("fast")] == [shared]
    assert [d.name for d in runtime.model_registry.by_tier("standard")] == [shared]


@pytest.mark.asyncio
async def test_default_config_fast_tier_sends_its_configured_name(endpoint: _Endpoint) -> None:
    config = _config()
    configured = config.cognitive.llm_model_fast
    # premise: the catalog's own fast entry is a different name
    assert [d.name for d in ModelRegistry().by_tier("fast")] != [configured]
    runtime, client = _wired(config)
    try:
        response = await client.complete(LLMRequest(prompt="ping", tier="fast"))
    finally:
        await client.close()
    assert response.error is None
    assert endpoint.models == [configured]


@pytest.mark.asyncio
async def test_routing_disabled_sends_the_configured_model_unrouted(endpoint: _Endpoint) -> None:
    config = _config(enabled=False, **_named())
    client = OpenAICompatibleClient(config=config.cognitive)
    runtime = _Runtime(client)
    try:
        assert _wire_model_routing(runtime=runtime, config=config) is False
        assert runtime.model_registry is None
        assert runtime.model_router is None
        assert client.model_router is None
        response = await client.complete(LLMRequest(prompt="ping", tier="deep"))
    finally:
        await client.close()
    assert response.error is None
    assert endpoint.models == [_NAMES["deep"]]
    assert runtime.events == []


@pytest.mark.asyncio
async def test_ceiling_below_a_known_price_skips_the_tier_and_the_chain_continues(
    endpoint: _Endpoint,
) -> None:
    config = _config(ceiling=20.0, **_priced())
    deep = config.cognitive.llm_model_deep
    fast = config.cognitive.llm_model_fast
    assert _catalog_price(deep) > 20.0 >= _catalog_price(fast)  # premise
    runtime, client = _wired(config)
    try:
        response = await client.complete(LLMRequest(prompt="ping", tier="deep"))
    finally:
        await client.close()
    assert response.error is None
    assert endpoint.models == [fast]
    fallbacks = runtime.of(EventType.MODEL_FALLBACK)
    assert [(e["tier"], e["chosen_model"]) for e in fallbacks] == [("deep", "")]
    assert "cost ceiling 20.00" in fallbacks[0]["reason"]


@pytest.mark.asyncio
async def test_when_no_tier_qualifies_nothing_is_sent_and_the_error_names_the_ceiling(
    endpoint: _Endpoint,
) -> None:
    config = _config(ceiling=1.0, **_priced())
    for tier in _TEXT_TIERS:  # premise: every configured model is priced above it
        assert _catalog_price(config.cognitive.tier_config(tier)["model"]) > 1.0
    runtime, client = _wired(config)
    try:
        response = await client.complete(LLMRequest(prompt="ping", tier="fast"))
    finally:
        await client.close()
    assert endpoint.bodies == []
    assert response.error is not None
    assert response.error.startswith("All LLM tiers unavailable")
    assert "cost ceiling 1.00" in response.error
    assert sorted(e["tier"] for e in runtime.of(EventType.MODEL_FALLBACK)) == sorted(_TEXT_TIERS)


@pytest.mark.asyncio
async def test_an_unpriced_configured_model_fails_the_ceiling(
    endpoint: _Endpoint, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=_ROUTER_LOGGER)
    unpriced = "bf886-unpriced-model"
    assert ModelRegistry().get(unpriced) is None  # premise: no known price
    config = _config(ceiling=100.0, **_priced(fast=unpriced))
    standard = config.cognitive.llm_model_standard
    assert _catalog_price(standard) <= 100.0  # premise: the next tier in the chain is admissible
    runtime, client = _wired(config)
    try:
        response = await client.complete(LLMRequest(prompt="ping", tier="fast"))
    finally:
        await client.close()
    assert response.error is None
    assert endpoint.models == [standard]  # A-1: the unpriced model is never sent
    fallbacks = runtime.of(EventType.MODEL_FALLBACK)
    assert [(e["tier"], e["chosen_model"]) for e in fallbacks] == [("fast", "")]
    assert f"({unpriced} with no known price)" in fallbacks[0]["reason"]
    errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert f"tier fast with no admissible model ({unpriced} with no known price)" in errors[0]
    assert "100.00 USD per million output tokens" in errors[0]
    assert "model_routing.cost_ceiling_per_million_output_tokens" in errors[0]


def test_wiring_logs_an_error_naming_each_tier_the_ceiling_excludes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    config = _config(ceiling=20.0, **_priced())
    assert _catalog_price(config.cognitive.llm_model_deep) > 20.0  # premise
    runtime = _Runtime(llm_client=None)
    assert _wire_model_routing(runtime=runtime, config=config) is True
    errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "20.00 USD per million output tokens" in errors[0]
    assert "tier deep with no admissible model (claude-opus-4-6 at 75.00)" in errors[0]
    # A-1: the remedy names the catalog models that fit the ceiling.
    assert "(claude-sonnet-4-6-fast at 15.00, claude-sonnet-4-6 at 15.00)" in errors[0]


def test_wiring_says_what_is_lost_when_the_client_refuses_the_router(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _ReadOnlyClient:
        def __setattr__(self, name: str, value: Any) -> None:
            raise AttributeError(f"{name} is read-only")

    caplog.set_level(logging.WARNING, logger="probos.startup.finalize")
    runtime = _Runtime(llm_client=_ReadOnlyClient())
    assert _wire_model_routing(runtime=runtime, config=_config()) is True
    assert runtime.model_router is not None
    warnings = [
        r.getMessage() for r in caplog.records
        if r.name == "probos.startup.finalize" and r.levelno == logging.WARNING
    ]
    assert len(warnings) == 1
    assert "without the configured cost ceiling" in warnings[0]


@pytest.mark.asyncio
async def test_without_a_ceiling_the_configured_model_is_sent_and_nothing_is_reported(
    endpoint: _Endpoint, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=_ROUTER_LOGGER)
    config = _config()
    deep = config.cognitive.llm_model_deep
    runtime, client = _wired(config)
    try:
        response = await client.complete(LLMRequest(prompt="ping", tier="deep"))
    finally:
        await client.close()
    assert response.error is None
    assert endpoint.models == [deep]
    assert runtime.of(EventType.MODEL_FALLBACK) == []
    assert [r for r in caplog.records if r.name == _ROUTER_LOGGER] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("tier", ["vision", "vision_fast", "compute_use"])
async def test_a_ceiling_never_reaches_the_router_bypassed_tiers(
    endpoint: _Endpoint, tier: str,
) -> None:
    runtime, client = _wired(_config(ceiling=1.0))
    try:
        assert client._resolve_model_for_tier(tier) is None
    finally:
        await client.close()
    assert runtime.events == []


# ----- ModelRegistry.from_tier_models -----


def test_from_tier_models_holds_only_the_configured_models() -> None:
    registry = ModelRegistry.from_tier_models(_NAMES)
    assert {t: [d.name for d in registry.by_tier(t)] for t in _TEXT_TIERS} == {
        t: [_NAMES[t]] for t in _TEXT_TIERS
    }
    assert sorted(d.name for d in registry.all()) == sorted(_NAMES.values())
    assert ModelRegistry(seed_defaults=False).all() == []


def test_from_tier_models_prices_a_catalog_name_and_retiers_it() -> None:
    (descriptor,) = ModelRegistry.from_tier_models({"fast": "claude-opus-4-6"}).by_tier("fast")
    catalog = ModelRegistry().get("claude-opus-4-6")
    assert catalog is not None and catalog.tier == "deep"
    assert descriptor == replace(catalog, tier="fast")


def test_from_tier_models_registers_an_unknown_name_at_price_zero() -> None:
    (descriptor,) = ModelRegistry.from_tier_models({"deep": "bf886-unknown"}).by_tier("deep")
    assert (
        descriptor.name,
        descriptor.provider,
        descriptor.tier,
        descriptor.cost_per_million_input_tokens,
        descriptor.cost_per_million_output_tokens,
    ) == ("bf886-unknown", "unknown", "deep", 0.0, 0.0)


def test_from_tier_models_leaves_a_tier_without_a_name_empty() -> None:
    registry = ModelRegistry.from_tier_models({"fast": "", "deep": "bf886-deep"})
    assert registry.by_tier("fast") == []
    assert [d.name for d in registry.all()] == ["bf886-deep"]


def test_a_model_in_two_tiers_keeps_both_entries_and_one_availability() -> None:
    registry = ModelRegistry.from_tier_models({"fast": "bf886-m", "standard": "bf886-m"})
    assert [(d.tier, d.name) for d in registry.all()] == [
        ("fast", "bf886-m"), ("standard", "bf886-m"),
    ]
    assert registry.mark_unavailable("bf886-m") is True
    assert registry.by_tier("fast") == [] and registry.by_tier("standard") == []
    assert registry.mark_unavailable("bf886-m") is False
    assert registry.mark_available("bf886-m") is True
    assert [d.name for d in registry.by_tier("fast")] == ["bf886-m"]
    assert [d.name for d in registry.by_tier("standard")] == ["bf886-m"]


# ----- ModelRouter and the cost ceiling -----


def test_router_applies_its_configured_ceiling_without_a_call_argument() -> None:
    events: list[tuple[Any, dict[str, Any]]] = []
    router = ModelRouter(
        registry=ModelRegistry.from_tier_models({"deep": "claude-opus-4-6"}),
        emit_event=lambda et, data: events.append((et, data)),
        cost_ceiling=20.0,
    )
    assert router.cost_ceiling == 20.0
    decision = router.choose(tier="deep")
    assert decision == RoutingDecision(
        chosen_model="",
        requested_tier="deep",
        reason=(
            "cost ceiling 20.00 USD per million output tokens excludes every "
            "available model in tier 'deep' (claude-opus-4-6 at 75.00)"
        ),
        fallback=True,
        excluded_by_cost_ceiling=True,
    )
    assert events == [(
        EventType.MODEL_FALLBACK,
        {"chosen_model": "", "tier": "deep", "reason": decision.reason},
    )]


def test_a_per_call_ceiling_tightens_but_never_lifts_the_configured_one() -> None:
    registry = ModelRegistry.from_tier_models(
        {"standard": "claude-sonnet-4-6", "deep": "claude-opus-4-6"},
    )
    router = ModelRouter(registry=registry, cost_ceiling=20.0)
    assert router.choose(tier="deep", cost_ceiling=100.0).excluded_by_cost_ceiling is True
    assert router.choose(tier="standard", cost_ceiling=10.0).excluded_by_cost_ceiling is True
    assert router.choose(tier="standard").chosen_model == "claude-sonnet-4-6"
    unset = ModelRouter(registry=registry)
    assert unset.choose(tier="deep", cost_ceiling=20.0).excluded_by_cost_ceiling is True
    assert unset.choose(tier="deep").chosen_model == "claude-opus-4-6"


@pytest.mark.parametrize("ceiling", [0.0, 1.0, 1000.0])
def test_router_refuses_an_unknown_price_under_any_ceiling(ceiling: float) -> None:
    # A-1 (#1474 acceptance): with a ceiling configured, an unknown price fails it.
    router = ModelRouter(
        registry=ModelRegistry.from_tier_models({"fast": "bf886-unknown"}),
        cost_ceiling=ceiling,
    )
    decision = router.choose(tier="fast")
    assert (decision.chosen_model, decision.fallback, decision.excluded_by_cost_ceiling) == (
        "", True, True,
    )
    assert decision.reason.endswith("(bf886-unknown with no known price)")


def test_router_admits_an_unknown_price_without_a_ceiling() -> None:
    router = ModelRouter(registry=ModelRegistry.from_tier_models({"fast": "bf886-unknown"}))
    decision = router.choose(tier="fast")
    assert (decision.chosen_model, decision.fallback, decision.excluded_by_cost_ceiling) == (
        "bf886-unknown", False, False,
    )


def test_cross_tier_fallback_never_picks_a_model_above_the_ceiling() -> None:
    registry = ModelRegistry()
    registry.mark_unavailable("claude-sonnet-4-6-fast")
    registry.mark_unavailable("claude-sonnet-4-6")
    # premise: the only model left in any tier is priced above the ceiling
    assert [(d.name, d.cost_per_million_output_tokens) for d in registry.all() if d.available] == [
        ("claude-opus-4-6", 75.0),
    ]
    events: list[tuple[Any, dict[str, Any]]] = []
    router = ModelRouter(registry=registry, emit_event=lambda et, data: events.append((et, data)))
    decision = router.choose(tier="standard", cost_ceiling=20.0)
    assert decision.chosen_model == ""
    assert decision.fallback is True
    assert decision.reason == "no available model within cost ceiling 20.00 in any tier"
    # A-1 (F-R1-3): under a ceiling, no admissible model anywhere is a denial.
    assert decision.excluded_by_cost_ceiling is True
    assert [et for et, _ in events] == [EventType.MODEL_FALLBACK]


def test_cross_tier_fallback_picks_the_first_model_within_the_ceiling() -> None:
    registry = ModelRegistry.from_tier_models(
        {"deep": "claude-opus-4-6", "fast": "claude-sonnet-4-6"},
    )
    router = ModelRouter(registry=registry, cost_ceiling=20.0)
    decision = router.choose(tier="standard")
    assert (decision.chosen_model, decision.fallback, decision.excluded_by_cost_ceiling) == (
        "claude-sonnet-4-6", True, False,
    )


def test_a_repeated_routing_deviation_is_reported_once_then_at_debug(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=_ROUTER_LOGGER)
    router = ModelRouter(
        registry=ModelRegistry.from_tier_models({"deep": "claude-opus-4-6"}),
        cost_ceiling=20.0,
    )
    router.choose(tier="deep")
    router.choose(tier="deep")
    reports = [r for r in caplog.records if "model routing for tier deep" in r.getMessage()]
    assert [r.levelno for r in reports] == [logging.WARNING, logging.DEBUG]
    assert "the tier attempt is skipped" in reports[0].getMessage()


def test_the_report_memory_is_bounded(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr("probos.cognitive.model_router._REPORTED_LIMIT", 1)
    caplog.set_level(logging.DEBUG, logger=_ROUTER_LOGGER)
    registry = ModelRegistry.from_tier_models(
        {"standard": "claude-sonnet-4-6", "deep": "claude-opus-4-6"},
    )
    router = ModelRouter(registry=registry, cost_ceiling=1.0)
    for tier in ("deep", "standard", "deep"):
        router.choose(tier=tier)
    reports = [r for r in caplog.records if "model routing for tier" in r.getMessage()]
    # A full memory resets before the next new report, so "deep" is reported afresh.
    assert [r.levelno for r in reports] == [logging.WARNING] * 3


def test_a_choice_among_several_registered_models_is_reported_at_info(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=_ROUTER_LOGGER)
    registry = ModelRegistry.from_tier_models({"fast": "claude-sonnet-4-6"})
    registry.register(ModelDescriptor(
        name="bf886-cheaper", provider="unknown", tier="fast",
        cost_per_million_output_tokens=1.0,
    ))
    decision = ModelRouter(registry=registry).choose(tier="fast")
    assert (decision.chosen_model, decision.reason) == ("bf886-cheaper", "cheapest-by-output-cost")
    reports = [r for r in caplog.records if "model routing for tier fast" in r.getMessage()]
    assert [r.levelno for r in reports] == [logging.INFO]
    assert "chosen among 2 registered candidates" in reports[0].getMessage()


def test_report_cost_ceiling_classifies_and_logs_each_tier(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=_ROUTER_LOGGER)
    registry = ModelRegistry.from_tier_models({
        "fast": "claude-sonnet-4-6",
        "standard": "bf886-unpriced",
        "deep": "claude-opus-4-6",
    })
    router = ModelRouter(registry=registry, cost_ceiling=20.0)
    assert router.report_cost_ceiling(("fast", "standard", "deep", "vision")) == {
        "fast": "within",
        "standard": "excluded",  # A-1: an unknown price fails the ceiling
        "deep": "excluded",
        "vision": "empty",
    }
    records = [(r.levelno, r.getMessage()) for r in caplog.records]
    assert [level for level, _ in records] == [logging.ERROR, logging.ERROR]
    assert "tier standard with no admissible model (bf886-unpriced with no known price)" in records[0][1]
    assert "tier deep with no admissible model (claude-opus-4-6 at 75.00)" in records[1][1]


def test_report_cost_ceiling_says_when_no_catalog_model_fits(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=_ROUTER_LOGGER)
    router = ModelRouter(
        registry=ModelRegistry.from_tier_models({"fast": "claude-sonnet-4-6"}), cost_ceiling=1.0,
    )
    assert router.report_cost_ceiling(("fast",)) == {"fast": "excluded"}
    (record,) = caplog.records
    assert "no model in the built-in catalog fits this ceiling: raise it until one does and configure that model, or unset it" in record.getMessage()
    assert "raise or unset" not in record.getMessage()


def test_report_cost_ceiling_without_a_ceiling_reports_and_logs_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=_ROUTER_LOGGER)
    router = ModelRouter(registry=ModelRegistry.from_tier_models({"deep": "claude-opus-4-6"}))
    assert router.report_cost_ceiling(_TEXT_TIERS) == {}
    assert caplog.records == []


# ----- LLM client: the exclusion is fail-safe -----


def test_resolve_model_for_tier_raises_when_the_ceiling_excludes_the_tier() -> None:
    # Imported here, not at module level, so the seam tests above still
    # collect, and fail on their own assertions, on a tree without it.
    from probos.cognitive.llm_client import CostCeilingExclusion

    router = ModelRouter(
        registry=ModelRegistry.from_tier_models({"deep": "claude-opus-4-6"}),
        cost_ceiling=20.0,
    )
    client = OpenAICompatibleClient(model_router=router)
    with pytest.raises(CostCeilingExclusion, match="cost ceiling 20.00"):
        client._resolve_model_for_tier("deep")


def test_a_router_decision_without_the_exclusion_flag_is_used_as_before() -> None:
    class _Decision:
        chosen_model = "bf886-chosen"

    class _Router:
        def choose(self, *, tier: str) -> _Decision:
            return _Decision()

    client = OpenAICompatibleClient(model_router=_Router())
    assert client._resolve_model_for_tier("fast") == "bf886-chosen"


# ----- A-1 (F-R1-1): probes, the boot factory, the warm-up and doctor obey the ceiling -----


def _text_tier_endpoints() -> dict[str, str]:
    """One endpoint per text tier, so each tier's probe is sent on its own."""
    return {f"llm_base_url_{tier}": f"https://offline.invalid/{tier}/v1/" for tier in _TEXT_TIERS}


@pytest.mark.asyncio
@pytest.mark.parametrize("respect_cooldown", [False, True], ids=["boot-or-diagnostic", "recovery-loop"])
async def test_a_connectivity_probe_never_sends_a_model_the_ceiling_denies(
    endpoint: _Endpoint, respect_cooldown: bool,
) -> None:
    config = _config(ceiling=20.0, **_text_tier_endpoints(), **_priced())
    deep = config.cognitive.llm_model_deep
    assert _catalog_price(deep) > 20.0  # premise: the ceiling denies the deep tier
    runtime, client = _wired(config)
    try:
        results = await client.check_connectivity(respect_cooldown=respect_cooldown)
        info = client.tier_info()
        health = client.get_health_status()
    finally:
        await client.close()
    assert deep not in endpoint.models
    assert not any(path.startswith("/deep/") for path in endpoint.paths)
    assert sorted(m for m in endpoint.models if m) == [
        "claude-sonnet-4-6", "claude-sonnet-4-6-fast",
    ]
    assert (results["fast"], results["standard"]) == (True, True)
    assert "deep" not in results  # an exclusion is neither reachable nor unreachable
    assert info["deep"]["reachable"] is None
    assert health["tiers"]["deep"]["consecutive_failures"] == 0


@pytest.mark.asyncio
async def test_the_boot_factory_applies_the_ceiling_before_its_first_probe(endpoint: _Endpoint) -> None:
    config = _config(ceiling=1.0, **_priced())
    for tier in _TEXT_TIERS:  # premise: the ceiling denies every text tier
        assert _catalog_price(config.cognitive.tier_config(tier)["model"]) > 1.0
    buffer = StringIO()
    client = await main_mod._create_llm_client(config, Console(file=buffer, width=300))
    try:
        assert endpoint.bodies == []  # no probe: each text tier is denied, and no tier probes in its place
        assert type(client) is OpenAICompatibleClient
        assert client.model_router is not None and client.model_router.cost_ceiling == 1.0
        response = await client.complete(LLMRequest(prompt="ping", tier="fast"))
    finally:
        await client.close()
    assert endpoint.bodies == []
    assert response.error is not None and "cost ceiling 1.00" in response.error
    out = buffer.getvalue()
    for tier in _TEXT_TIERS:
        assert f"LLM {tier}: not probed at " in out
        assert f"cost ceiling 1.00 USD per million output tokens excludes every available model in tier '{tier}'" in out
    assert "unreachable" not in out


@pytest.mark.asyncio
async def test_a_budget_exclusion_never_selects_the_mock_client(endpoint: _Endpoint) -> None:
    endpoint.down = True
    control = await main_mod._create_llm_client(_config(), Console(file=StringIO(), width=300))
    assert isinstance(control, MockLLMClient)  # premise: an unreachable endpoint does select the mock
    endpoint.bodies.clear()
    client = await main_mod._create_llm_client(_config(ceiling=1.0), Console(file=StringIO(), width=300))
    try:
        assert endpoint.bodies == []  # nothing was probed, so nothing failed
        assert type(client) is OpenAICompatibleClient
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_check_endpoint_sends_nothing_for_a_tier_the_ceiling_denies(endpoint: _Endpoint) -> None:
    runtime, client = _wired(_config(ceiling=20.0))
    try:
        assert await client._check_endpoint("deep") is False
        assert await client._check_endpoint("fast") is True  # premise: the probe path works
    finally:
        await client.close()
    assert endpoint.models == ["claude-sonnet-4-6"]


@pytest.mark.asyncio
async def test_a_probe_sends_the_model_the_router_would_choose(endpoint: _Endpoint) -> None:
    config = _config(llm_model_fast="claude-opus-4-6")
    registry = ModelRegistry.from_tier_models({"fast": "claude-opus-4-6"})
    registry.register(ModelDescriptor(
        name="claude-sonnet-4-6-fast", provider="anthropic", tier="fast",
        cost_per_million_output_tokens=15.0,
    ))
    client = OpenAICompatibleClient(
        config=config.cognitive, model_router=ModelRouter(registry=registry, cost_ceiling=20.0),
    )
    try:
        assert await client._check_endpoint("fast") is True
    finally:
        await client.close()
    # The configured claude-opus-4-6 is above the ceiling; the router's choice is not.
    assert endpoint.models == ["claude-sonnet-4-6-fast"]


@pytest.mark.asyncio
async def test_a_router_without_preview_keeps_the_configured_probe_model(endpoint: _Endpoint) -> None:
    class _ChooseOnly:
        def choose(self, *, tier: str) -> Any:
            raise AssertionError("a probe never routes through choose()")

    client = OpenAICompatibleClient(config=_config(**_named()).cognitive, model_router=_ChooseOnly())
    try:
        assert await client._check_endpoint("fast") is True
    finally:
        await client.close()
    assert endpoint.models == [_NAMES["fast"]]


@pytest.mark.asyncio
async def test_the_ollama_warm_up_skips_a_tier_the_ceiling_denies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROBOS_LLM_URL", raising=False)
    seen: list[tuple[str, str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "offline.invalid", "a test reached an unowned endpoint"
        body = json.loads(request.content) if request.content else {}
        seen.append((request.method, request.url.path, body.get("model")))
        if request.url.path.endswith("/api/version"):
            return httpx.Response(200, json={"version": "0.0.0"})
        return httpx.Response(200, json={"message": {"content": "pong"}})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda *args, **kwargs: real_client(*args, transport=httpx.MockTransport(handle), **kwargs),
    )
    ollama = {
        "llm_base_url_fast": "http://offline.invalid:11434",
        "llm_api_format_fast": "ollama",
        "llm_model_fast": "bf886-llama",
    }
    assert ModelRegistry().get("bf886-llama") is None  # premise: no known price
    await main_mod._ensure_ollama(_config(**ollama), Console(file=StringIO()))
    assert ("POST", "/api/chat", "bf886-llama") in seen  # premise: without a ceiling it is warmed up
    seen.clear()
    buffer = StringIO()
    await main_mod._ensure_ollama(_config(ceiling=100.0, **ollama), Console(file=buffer, width=200))
    assert seen == []
    assert "Not warming up the fast tier" in buffer.getvalue()


@pytest.mark.asyncio
async def test_doctor_does_not_probe_a_tier_the_ceiling_denies(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from probos.doctor.checks.llm_check import _LLMCheck
    from probos.doctor.protocol import CheckOutcome, DoctorContext

    monkeypatch.delenv("PROBOS_LLM_URL", raising=False)
    seen: list[tuple[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "offline.invalid", "a test reached an unowned endpoint"
        if request.method == "GET":
            seen.append(("GET", None))
            return httpx.Response(200, json={
                "object": "list",
                "data": [{"id": "claude-sonnet-4-6"}, {"id": "claude-opus-4-6"}],
            })
        seen.append(("POST", json.loads(request.content).get("model")))
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "pong"}, "finish_reason": "stop"}],
        })

    ctx = DoctorContext(
        config=_config(ceiling=20.0), home_dir=tmp_path, data_dir=tmp_path, config_path=None,
        provider_transport=httpx.MockTransport(handle),
    )
    result = await _LLMCheck().run(ctx)
    assert ("POST", "claude-sonnet-4-6") in seen  # premise: doctor probed what the ceiling admits
    assert ("POST", "claude-opus-4-6") not in seen
    assert result.outcome is CheckOutcome.WARN
    assert "not verified: deep" in result.message
    assert "cost ceiling 20.00" in result.remediation
    assert "raising the ceiling first if no catalog model fits" in result.remediation
    assert "or raise or unset" not in result.remediation


# ----- A-1 (F-R1-3): no admissible model anywhere, under a ceiling, is a denial -----


def test_an_empty_registry_under_a_ceiling_is_a_denial() -> None:
    bounded = ModelRouter(registry=ModelRegistry(seed_defaults=False), cost_ceiling=1.0).choose(tier="fast")
    assert (bounded.chosen_model, bounded.excluded_by_cost_ceiling) == ("", True)
    unbounded = ModelRouter(registry=ModelRegistry(seed_defaults=False)).choose(tier="fast")
    assert (unbounded.chosen_model, unbounded.excluded_by_cost_ceiling, unbounded.reason) == (
        "", False, "no available models in any tier",
    )


@pytest.mark.asyncio
async def test_a_completion_with_no_admissible_model_anywhere_sends_nothing(endpoint: _Endpoint) -> None:
    runtime, client = _wired(_config(ceiling=1.0))
    for descriptor in runtime.model_registry.all():
        runtime.model_registry.mark_unavailable(descriptor.name)
    assert not any(runtime.model_registry.by_tier(tier) for tier in _TEXT_TIERS)  # premise
    try:
        response = await client.complete(LLMRequest(prompt="ping", tier="fast"))
    finally:
        await client.close()
    assert endpoint.bodies == []
    assert response.error is not None
    assert "no available model within cost ceiling 1.00 in any tier" in response.error


# ----- A-1: a budget refusal is not logged as an outage -----


@pytest.mark.asyncio
async def test_a_call_the_ceiling_refuses_everywhere_is_not_logged_as_an_outage(
    endpoint: _Endpoint, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="probos.cognitive.llm_client")
    runtime, client = _wired(_config(ceiling=1.0))
    try:
        response = await client.complete(LLMRequest(prompt="ping", tier="fast"))
        health = client.get_health_status()
    finally:
        await client.close()
    assert endpoint.bodies == []
    assert response.error is not None and response.error.startswith("All LLM tiers unavailable")
    records = [r for r in caplog.records if r.name == "probos.cognitive.llm_client"]
    assert not [r for r in records if r.levelno >= logging.ERROR]
    assert any("refused by the model routing cost ceiling on every tier" in r.getMessage() for r in records)
    assert health["overall"] == "operational"


# ----- A-1: R-8 and the shared builder -----


def test_text_tiers_is_the_public_alias_of_the_fallback_chain() -> None:
    import ast
    import inspect

    from probos.cognitive import llm_client

    assert llm_client.TEXT_TIERS is llm_client._TIER_ORDER
    # Identity also holds for an equal literal (CPython shares equal constants in
    # a module), so the alias is read from the source: never a second copy.
    tree = ast.parse(inspect.getsource(llm_client))
    (value,) = [
        node.value for node in tree.body
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "TEXT_TIERS"
    ]
    assert isinstance(value, ast.Name) and value.id == "_TIER_ORDER"


def test_build_model_routing_follows_the_config() -> None:
    from probos.cognitive.model_router import build_model_routing

    assert build_model_routing(_config(enabled=False, ceiling=1.0)) is None
    router = build_model_routing(_config(ceiling=20.0, **_named()))
    assert router is not None and router.cost_ceiling == 20.0
    assert {t: [d.name for d in router.registry.by_tier(t)] for t in _TEXT_TIERS} == {
        t: [_NAMES[t]] for t in _TEXT_TIERS
    }


def test_preview_and_denials_neither_log_nor_emit(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger=_ROUTER_LOGGER)
    events: list[Any] = []
    router = ModelRouter(
        registry=ModelRegistry.from_tier_models({"fast": "claude-sonnet-4-6", "deep": "claude-opus-4-6"}),
        emit_event=lambda event_type, data: events.append(event_type),
        cost_ceiling=20.0,
    )
    assert router.preview(tier="fast").chosen_model == "claude-sonnet-4-6"
    assert router.preview(tier="deep").excluded_by_cost_ceiling is True
    assert router.denials(("fast", "deep")) == {"deep": router.preview(tier="deep").reason}
    assert events == []
    assert caplog.records == []


def test_ceiling_denials_reads_the_config() -> None:
    from probos.cognitive.model_router import ceiling_denials

    assert ceiling_denials(_config()) == {}
    assert ceiling_denials(_config(enabled=False, ceiling=1.0)) == {}
    assert list(ceiling_denials(_config(ceiling=20.0))) == ["deep"]


@pytest.mark.asyncio
async def test_a_probe_is_withheld_when_the_router_cannot_preview(
    endpoint: _Endpoint, caplog: pytest.LogCaptureFixture,
) -> None:
    class _BrokenPreview:
        def choose(self, *, tier: str) -> Any:
            raise AssertionError("a probe never routes through choose()")

        def preview(self, *, tier: str) -> Any:
            raise RuntimeError("bf886: preview unavailable")

    caplog.set_level(logging.WARNING, logger="probos.cognitive.llm_client")
    client = OpenAICompatibleClient(config=_config(**_named()).cognitive, model_router=_BrokenPreview())
    try:
        assert await client._check_endpoint("fast") is False
        results = await client.check_connectivity()
    finally:
        await client.close()
    assert not any(model in _NAMES.values() for model in endpoint.models)  # no text-tier probe went out
    assert not set(_TEXT_TIERS) & set(results)
    assert any("probe is withheld" in r.getMessage() for r in caplog.records)
