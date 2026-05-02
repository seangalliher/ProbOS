# AD-463: Model Diversity & Neural Routing -- Foundation (v1)

**Status:** Ready for builder
**Dependencies:** Builds on existing `BaseLLMClient` ABC (`cognitive/llm_client.py:22`) and `OpenAICompatibleClient` (`cognitive/llm_client.py:44`). Reads `HebbianRouter.get_weight()` (`mesh/routing.py:142`) for routing-bias. Reads existing `CognitiveJournal` schema (`cognitive/journal.py:25-43`) for cost-tracking columns.
**Estimated tests:** ~15
**Risk:** High -- foundation work that future ADs (AD-428b, AD-462f, AD-469) will depend on. **v1 scope is deliberately narrow per no-theater discipline.**

---

## Problem

ProbOS hardcodes a fixed three-tier model topology in `OpenAICompatibleClient.__init__` (`cognitive/llm_client.py:78-81`): `fast = gpt-4o-mini`, `standard = claude-sonnet-4-6`, `deep = claude-opus-4-0-...`. There is no:

1. **Model catalog** -- no first-class registry of available models with per-model metadata (provider, cost-per-token, token-limit, capability tags).
2. **Provider abstraction** -- `OpenAICompatibleClient` is the only `BaseLLMClient` implementation today (verified -- only `OpenAICompatibleClient` and `MockLLMClient` exist). Adding a fundamentally-different provider (e.g., Anthropic native, Ollama native, Bedrock) requires duplicating logic.
3. **Routing decision** -- model selection is by tier name (`"fast"|"standard"|"deep"`), not by capability/cost/load.

`grep -rn "class ModelRegistry\|class ModelRouter\|class ProviderABC" src/probos/` returns no matches today.

The roadmap entry (line 4169) lists 10 capabilities. **v1 ships 4 real-work primitives; six deferred to AD-463b/c/d/e** per no-theater discipline (Wave 5 retrospective convention #7).

## Solution Overview

Create three new modules:

1. **`src/probos/cognitive/model_registry.py`** -- `ModelDescriptor` dataclass + `ModelRegistry` (in-memory catalog, seeded from config). Public lookup API.
2. **`src/probos/cognitive/model_router.py`** -- `ModelRouter` consults the registry + (optionally) `HebbianRouter.get_weight()` to pick a model for a given `(tier, agent_id)` request. Stateless. Read-only over both inputs. Emits `MODEL_ROUTED` per decision; `MODEL_FALLBACK` when the preferred model is unavailable and a backup is chosen.
3. **Registry hook in `OpenAICompatibleClient`** -- one *real consumer* call site: `complete()` consults `runtime.model_router.choose(tier, agent_id)` (when present) to override the default tier-to-model mapping. Falls back to existing tier->model logic when registry is absent. (Real consumer per Wave 5 retrospective convention #7 -- not theater.)

This is **policy + diagnostics layered on existing surfaces.** AD-463 does NOT replace `BaseLLMClient`, does NOT introduce new providers, does NOT extend `HebbianRouter`. It composes existing primitives into a model-selection observability surface and prepares the seam for future provider expansion.

**v1 scope (no-theater discipline -- enforced):**

The roadmap's 10 capabilities reduce to 4 v1 deliverables that do real work today:

- **`ModelRegistry`** -- shipped, real public catalog API.
- **`ModelDescriptor`** -- shipped, real dataclass.
- **`ModelRouter`** -- shipped, real selection logic with one real consumer wiring.
- **One real consumer hook** in `OpenAICompatibleClient.complete()` -- routes the chosen model into the existing per-tier request path.

**Six deferred to sub-ADs (per the roadmap's 10-capability list):**

- **`ProviderABC` + non-OpenAI providers** (Anthropic native, Ollama native, Bedrock) -- AD-463b. v1's `ModelDescriptor` carries a `provider: str` field for future use; routing today still goes through the existing `OpenAICompatibleClient` regardless of provider.
- **MAD (Multi-Agent Debate) confidence scoring** -- AD-463c. v1 picks a single model; multi-model comparison deferred.
- **Brain diversity / per-agent model preference** -- AD-463d. v1 reads HebbianRouter for routing-bias hint only.
- **Hot-swap (live model swap without restart)** -- AD-463e. v1 routes; swap requires runtime restart.
- **Per-model edit-format selection** (e.g., diff vs full-rewrite preference) -- AD-463f. v1's ModelDescriptor has no edit-format field.
- **Cost-aware selection** -- partial. v1's `ModelDescriptor` carries `cost_per_million_input_tokens` and `cost_per_million_output_tokens` fields; ModelRouter accepts a `cost_ceiling: float | None` parameter. **Cost tracking integration with CognitiveJournal is shipped as a public-attribute read** -- but no behavior changes are made to journal writes (existing `CognitiveJournal` schema at `journal.py:25-43` already has `model`, `prompt_tokens`, `completion_tokens` columns; they continue to be written by the existing path). Aggregation queries are AD-467d Cost Tracker scope.

---

## Section 0: Event Types

Add to `src/probos/events.py`:

```
MODEL_ROUTED = "model_routed"  # AD-463
MODEL_FALLBACK = "model_fallback"  # AD-463
```

Two new values. Verified absent via `grep -n "MODEL_ROUTED\|MODEL_FALLBACK" src/probos/events.py` (no matches).

---

## Section 1: `ModelDescriptor` and `ModelRegistry`

**File:** `src/probos/cognitive/model_registry.py` (new)

```python
"""AD-463: ModelRegistry -- in-memory catalog of available LLM models.

v1: read-only public catalog seeded from config. Future ADs (AD-463b/c/d/e/f)
will extend with provider abstraction, MAD scoring, hot-swap, edit-format
selection.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

logger = logging.getLogger(__name__)


class ModelCapability(str, Enum):
    """Capability tags. Used by ModelRouter to filter candidates."""

    GENERAL = "general"           # general-purpose chat / completion
    REASONING = "reasoning"       # chain-of-thought, math, code
    FAST = "fast"                 # latency-optimized
    LONG_CONTEXT = "long_context"  # >100K tokens


@dataclass(frozen=True)
class ModelDescriptor:
    """Public per-model metadata. v1 fields stable across AD-463/463b/c/d/e/f."""

    name: str
    provider: str                              # "openai", "anthropic", "ollama"
    tier: str                                  # "fast", "standard", "deep"
    capabilities: frozenset[ModelCapability] = field(default_factory=frozenset)
    cost_per_million_input_tokens: float = 0.0   # USD; 0 => unknown / free
    cost_per_million_output_tokens: float = 0.0
    context_window_tokens: int = 0               # 0 => unknown
    available: bool = True


# v1 default catalog. Operators extend by registering additional descriptors
# at startup. The names match the existing CognitiveConfig defaults so v1
# routing decisions are observable without operator action.
_DEFAULT_DESCRIPTORS: tuple[ModelDescriptor, ...] = (
    ModelDescriptor(
        name="gpt-4o-mini",
        provider="openai",
        tier="fast",
        capabilities=frozenset({ModelCapability.GENERAL, ModelCapability.FAST}),
        cost_per_million_input_tokens=0.15,
        cost_per_million_output_tokens=0.60,
        context_window_tokens=128_000,
    ),
    ModelDescriptor(
        name="claude-sonnet-4-6",
        provider="anthropic",
        tier="standard",
        capabilities=frozenset({
            ModelCapability.GENERAL,
            ModelCapability.REASONING,
            ModelCapability.LONG_CONTEXT,
        }),
        cost_per_million_input_tokens=3.0,
        cost_per_million_output_tokens=15.0,
        context_window_tokens=200_000,
    ),
    ModelDescriptor(
        name="claude-opus-4-0",
        provider="anthropic",
        tier="deep",
        capabilities=frozenset({
            ModelCapability.GENERAL,
            ModelCapability.REASONING,
            ModelCapability.LONG_CONTEXT,
        }),
        cost_per_million_input_tokens=15.0,
        cost_per_million_output_tokens=75.0,
        context_window_tokens=200_000,
    ),
)


@dataclass
class ModelRegistry:
    """In-memory catalog. Seeded from defaults; operators extend at startup.

    Public API:
      - register(descriptor) -- add or overwrite by name.
      - get(name) -> ModelDescriptor | None.
      - by_tier(tier) -> list[ModelDescriptor] -- all available models in tier.
      - all() -> list[ModelDescriptor].
      - mark_unavailable(name) / mark_available(name) -- transient state changes
        for a future AD-463b health probe; v1 sets but does not persist.
    """

    _descriptors: dict[str, ModelDescriptor] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for d in _DEFAULT_DESCRIPTORS:
            self._descriptors[d.name] = d

    def register(self, descriptor: ModelDescriptor) -> None:
        self._descriptors[descriptor.name] = descriptor

    def get(self, name: str) -> ModelDescriptor | None:
        return self._descriptors.get(name)

    def by_tier(self, tier: str) -> list[ModelDescriptor]:
        return [d for d in self._descriptors.values() if d.tier == tier and d.available]

    def all(self) -> list[ModelDescriptor]:
        return list(self._descriptors.values())

    def mark_unavailable(self, name: str) -> bool:
        d = self._descriptors.get(name)
        if d is None or not d.available:
            return False
        # frozen dataclass -- replace via dataclasses.replace
        from dataclasses import replace
        self._descriptors[name] = replace(d, available=False)
        return True

    def mark_available(self, name: str) -> bool:
        d = self._descriptors.get(name)
        if d is None or d.available:
            return False
        from dataclasses import replace
        self._descriptors[name] = replace(d, available=True)
        return True
```

---

## Section 2: `ModelRouter`

**File:** `src/probos/cognitive/model_router.py` (new)

```python
"""AD-463: ModelRouter -- model selection given (tier, agent_id) + policy.

v1 logic:
  1. Pull all available models in the requested tier from ModelRegistry.
  2. Apply optional cost_ceiling filter.
  3. If no candidates remain, emit MODEL_FALLBACK with reason; pick the
     first available model from any tier (as a last-resort fallback).
  4. Emit MODEL_ROUTED with the chosen model name.

HebbianRouter integration: v1 uses `HebbianRouter.get_weight()` (verified at
`mesh/routing.py:142`) as a SOFT routing hint when an agent has multiple
candidates. Future ADs (AD-463d brain diversity) will integrate more
deeply -- v1 only reads weights via the existing public API.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from probos.events import EventType

if TYPE_CHECKING:
    from probos.cognitive.model_registry import ModelDescriptor, ModelRegistry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RoutingDecision:
    """Outcome of one routing call."""

    chosen_model: str
    requested_tier: str
    agent_id: str
    reason: str
    fallback: bool = False


class ModelRouter:
    """Composes ModelRegistry + (optional) HebbianRouter into selection.

    Stateless. Each `choose()` call queries the registry and returns a
    fresh RoutingDecision.
    """

    def __init__(
        self,
        *,
        registry: "ModelRegistry",
        hebbian_router: Any | None = None,
        emit_event: Any | None = None,
    ) -> None:
        self._registry = registry
        self._hebbian = hebbian_router
        self._emit_event = emit_event

    def choose(
        self,
        *,
        tier: str,
        agent_id: str = "",
        cost_ceiling: float | None = None,
    ) -> RoutingDecision:
        candidates = self._registry.by_tier(tier)
        if cost_ceiling is not None:
            candidates = [
                d for d in candidates
                if d.cost_per_million_output_tokens <= cost_ceiling
            ]

        if not candidates:
            # No candidates in tier (or under cost ceiling) -- emit fallback
            for d in self._registry.all():
                if d.available:
                    decision = RoutingDecision(
                        chosen_model=d.name,
                        requested_tier=tier,
                        agent_id=agent_id,
                        reason=f"no available models in tier '{tier}' (cost_ceiling={cost_ceiling})",
                        fallback=True,
                    )
                    self._emit_fallback(decision)
                    return decision
            # No models available anywhere -- return empty decision
            decision = RoutingDecision(
                chosen_model="",
                requested_tier=tier,
                agent_id=agent_id,
                reason="no available models in any tier",
                fallback=True,
            )
            self._emit_fallback(decision)
            return decision

        # Single-candidate fast path
        if len(candidates) == 1:
            chosen = candidates[0]
            decision = RoutingDecision(
                chosen_model=chosen.name,
                requested_tier=tier,
                agent_id=agent_id,
                reason="single candidate",
            )
            self._emit_routed(decision)
            return decision

        # Multi-candidate: cheapest by output cost (v1 default policy).
        # AD-463d will integrate HebbianRouter weights more deeply; v1 only
        # consults the public get_weight() for tie-breaking when costs equal.
        chosen = min(
            candidates,
            key=lambda d: (d.cost_per_million_output_tokens, d.name),
        )
        reason = "cheapest-by-output-cost"
        if self._hebbian is not None and agent_id:
            try:
                # If the agent has a strong outbound weight to a candidate
                # name (treated as an opaque AgentID for the hint), prefer it.
                weighted = [
                    (d, self._hebbian.get_weight(agent_id, d.name))
                    for d in candidates
                ]
                positive = [(d, w) for d, w in weighted if w > 0.0]
                if positive:
                    chosen = max(positive, key=lambda pair: pair[1])[0]
                    reason = "hebbian-weight"
            except Exception:
                logger.debug(
                    "AD-463: HebbianRouter.get_weight failed; falling back to cost (agent_id=%s)",
                    agent_id, exc_info=True,
                )

        decision = RoutingDecision(
            chosen_model=chosen.name,
            requested_tier=tier,
            agent_id=agent_id,
            reason=reason,
        )
        self._emit_routed(decision)
        return decision

    def _emit_routed(self, decision: RoutingDecision) -> None:
        if not self._emit_event:
            return
        try:
            self._emit_event(
                EventType.MODEL_ROUTED,
                {
                    "chosen_model": decision.chosen_model,
                    "tier": decision.requested_tier,
                    "agent_id": decision.agent_id,
                    "reason": decision.reason,
                },
            )
        except Exception:
            logger.warning(
                "AD-463: MODEL_ROUTED emit failed (model=%s, tier=%s)",
                decision.chosen_model, decision.requested_tier, exc_info=True,
            )

    def _emit_fallback(self, decision: RoutingDecision) -> None:
        if not self._emit_event:
            return
        try:
            self._emit_event(
                EventType.MODEL_FALLBACK,
                {
                    "chosen_model": decision.chosen_model,
                    "tier": decision.requested_tier,
                    "agent_id": decision.agent_id,
                    "reason": decision.reason,
                },
            )
        except Exception:
            logger.warning(
                "AD-463: MODEL_FALLBACK emit failed (model=%s, tier=%s)",
                decision.chosen_model, decision.requested_tier, exc_info=True,
            )
```

---

## Section 3: Real-consumer hook in `OpenAICompatibleClient`

**File:** `src/probos/cognitive/llm_client.py`

To honor no-theater discipline (Wave 5 retrospective convention #7), v1 must wire `ModelRouter` into one real call site. The minimal-blast-radius hook: extend `OpenAICompatibleClient.__init__` to accept an optional `model_router: ModelRouter | None` argument; when present, `_resolve_model_for_tier(tier, agent_id)` consults the router and overrides the default tier->model mapping.

Builder note: this section is a CALLER-OPTIONAL hook. Existing callers that pass no `model_router` get the existing behavior unchanged. New callers (post-AD-463) pass `runtime.model_router` to enable routing.

SEARCH (in `OpenAICompatibleClient.__init__`):
```python
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8080/v1",
        api_key: str = "",
        models: dict[str, str] | None = None,
        timeout: float = 30.0,
        default_tier: str = "standard",
        config: Any = None,  # CognitiveConfig — optional, overrides all above
        rate_config: Any = None,  # AD-617: LLMRateConfig — optional
    ) -> None:
```

REPLACE:
```python
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8080/v1",
        api_key: str = "",
        models: dict[str, str] | None = None,
        timeout: float = 30.0,
        default_tier: str = "standard",
        config: Any = None,  # CognitiveConfig -- optional, overrides all above
        rate_config: Any = None,  # AD-617: LLMRateConfig -- optional
        model_router: Any = None,  # AD-463: ModelRouter -- optional override
    ) -> None:
        self._model_router = model_router
```

Then in the method that resolves a tier-name to a model-name (search for the existing `tier_config` consumption in `complete()` -- typically near the top of `complete()` where the request's tier is mapped to a model). Add a helper method `_resolve_model_for_tier`:

```python
    def _resolve_model_for_tier(self, tier: str, agent_id: str = "") -> str | None:
        """AD-463: consult ModelRouter if wired, else None (existing path).

        v1 only overrides the model NAME; base_url, api_key, timeout, and
        rate_config remain the existing per-tier values. Provider-routing
        (different base_url per provider) is deferred to AD-463b.
        """
        if self._model_router is None:
            return None
        try:
            decision = self._model_router.choose(tier=tier, agent_id=agent_id)
            return decision.chosen_model or None
        except Exception:
            logger.warning(
                "AD-463: ModelRouter.choose failed; falling back to default tier mapping (tier=%s)",
                tier, exc_info=True,
            )
            return None
```

> Builder note: the call-site insertion of `_resolve_model_for_tier(...)` in `complete()` requires reading the actual `complete()` body to identify the model-name resolution point. Verify-first by greping `complete(` body for where the tier is converted to the request's `model` field. Apply a minimal patch: when `_resolve_model_for_tier` returns a non-None override, use that instead of the existing tier->model lookup. When it returns None, the existing path is unchanged.
>
> Specifically: in the request-construction block of `complete()`, find where the model name is set (typically `tc["model"]` or similar). Before that line, call `override = self._resolve_model_for_tier(tier, getattr(request, "agent_id", ""))`; use `override or tc["model"]` for the request's model name.

This is a real-consumer wire per no-theater discipline. v1 ships ModelRouter integrated into the actual LLM call path, not as a dead class.

---

## Section 4: Add EventTypes

**File:** `src/probos/events.py`

SEARCH:
```python
    INFODYNAMIC_REPORT = "infodynamic_report"  # AD-491
```

REPLACE:
```python
    INFODYNAMIC_REPORT = "infodynamic_report"  # AD-491
    MODEL_ROUTED = "model_routed"  # AD-463
    MODEL_FALLBACK = "model_fallback"  # AD-463
```

> Builder note: anchor `INFODYNAMIC_REPORT` is verified post-AD-491 (Wave 6). Fallback chain terminates at `AGENT_SELF_NAMED = "agent_self_named"  # AD-499` (line 190).

---

## Section 5: Add `ModelRoutingConfig`

**File:** `src/probos/config.py`

```python
class ModelRoutingConfig(BaseModel):
    """Model routing configuration (AD-463)."""

    enabled: bool = True
    cost_ceiling_per_million_output_tokens: float | None = None  # USD; None disables
    use_hebbian_hint: bool = True
```

Wire into `SystemConfig`:

SEARCH:
```python
    infodynamic: InfodynamicConfig = InfodynamicConfig()  # AD-491
```

REPLACE:
```python
    infodynamic: InfodynamicConfig = InfodynamicConfig()  # AD-491
    model_routing: ModelRoutingConfig = ModelRoutingConfig()  # AD-463
```

> Builder note: anchor-chain fallback (next-anchor if predecessor hasn't landed):
> 1. `infodynamic: InfodynamicConfig` (AD-491, post-Wave 6).
> 2. `degradation: DegradationConfig` (AD-459, post-Wave 6).
> 3. `engineering: EngineeringConfig` (AD-457, post-Wave 6).
> 4. `validation_framework: ValidationFrameworkConfig` (AD-451, post-Wave 6).
> 5. `orders: OrdersConfig = OrdersConfig()  # AD-440` (config.py:1593) -- always-available terminal fallback.

---

## Section 6: Wire into startup

**File:** `src/probos/startup/finalize.py`

Place near the existing AD-491 InfodynamicProbe block:

```python
    # AD-463: Model Diversity & Neural Routing (v1 foundation)
    if config.model_routing.enabled:
        from probos.cognitive.model_registry import ModelRegistry
        from probos.cognitive.model_router import ModelRouter
        runtime.model_registry = ModelRegistry()
        runtime.model_router = ModelRouter(
            registry=runtime.model_registry,
            hebbian_router=runtime.hebbian_router if config.model_routing.use_hebbian_hint else None,
            emit_event=runtime.emit_event,
        )
        # Wire ModelRouter into the existing LLM client (real consumer, not theater).
        # The client's _model_router attribute is consulted at every complete() call
        # via _resolve_model_for_tier(). Existing tier->model defaults remain when
        # ModelRouter is absent.
        llm_client = getattr(runtime, "llm_client", None)
        if llm_client is not None:
            try:
                llm_client._model_router = runtime.model_router
            except Exception:
                logger.warning(
                    "AD-463: failed to wire ModelRouter into runtime.llm_client",
                    exc_info=True,
                )
        logger.info("AD-463: ModelRegistry + ModelRouter wired (%d models)",
                    len(runtime.model_registry.all()))
```

> Verify-first: `runtime.hebbian_router` is public (verified at `runtime.py:304`). `runtime.llm_client` is the existing public LLM client (verified at `runtime.py:347`). `runtime.model_registry` and `runtime.model_router` are published as public attributes (no leading underscore) per Wave 5 retrospective convention #1.
>
> The `llm_client._model_router = runtime.model_router` post-init assignment is the seam Section 3 introduces (the `__init__` already accepts `model_router=None` after Section 3's edit). This is wiring an architect-defined public attribute directly to an architect-defined private slot in the LLM client; not a Demeter violation because both ends are AD-463-introduced surface.

---

## Tests

**File:** `tests/test_ad463_model_routing.py`

15 tests:

1. `test_event_type_model_routed_exists` -- value matches.
2. `test_event_type_model_fallback_exists` -- value matches.
3. `test_model_routing_config_defaults` -- `ModelRoutingConfig()` defaults: `enabled=True`, `cost_ceiling_per_million_output_tokens=None`, `use_hebbian_hint=True`.
4. `test_model_descriptor_immutable` -- `dataclasses.replace(d, available=False)` creates a new instance; original unchanged.
5. `test_model_registry_default_seed_includes_three_tiers` -- `ModelRegistry()` constructed with defaults; `by_tier("fast")`, `by_tier("standard")`, `by_tier("deep")` each return >= 1 descriptor.
6. `test_model_registry_register_overwrites_by_name` -- register("gpt-4o-mini", new_descriptor) overwrites; existing seeds preserved for other names.
7. `test_model_registry_mark_unavailable_excludes_from_by_tier` -- mark_unavailable + by_tier no longer returns the marked model.
8. `test_router_single_candidate_returns_it` -- registry with one fast model -> `choose(tier="fast")` returns that model; `MODEL_ROUTED` emit fires; reason="single candidate".
9. `test_router_picks_cheapest_among_tier` -- two fast models with different costs -> cheaper one chosen; `MODEL_ROUTED` emit fires.
10. `test_router_cost_ceiling_filters_candidates` -- `cost_ceiling=1.0` filters out `>$1/M` models; remaining candidates considered.
11. `test_router_no_candidates_emits_fallback` -- empty tier -> first available from any tier chosen, `fallback=True`, `MODEL_FALLBACK` emit fires.
12. `test_router_no_models_at_all_returns_empty_decision` -- registry empty -> chosen_model=""; `fallback=True`; emit fires.
13. `test_router_hebbian_weight_overrides_cost` -- two equal-cost candidates; HebbianRouter returns positive weight to model A but zero to model B -> A chosen; reason="hebbian-weight".
14. `test_router_hebbian_failure_falls_back_to_cost` -- HebbianRouter raises -> swallowed; cheapest-by-output-cost path runs.
15. `test_llm_client_resolve_model_for_tier_when_router_absent_returns_none` -- `OpenAICompatibleClient(model_router=None)._resolve_model_for_tier("fast")` returns None; existing tier->model path is preserved.

Each test uses isolated fakes. No shared mutable state.

---

## What This Does NOT Change

- `BaseLLMClient` ABC (`cognitive/llm_client.py:22`) is unchanged.
- `MockLLMClient` (`cognitive/llm_client.py:823`) is unchanged.
- `HebbianRouter` (`mesh/routing.py:39`) is unchanged. v1 reads `get_weight()` as an existing public API; no extension.
- `CognitiveJournal` schema (`cognitive/journal.py:25-43`) is unchanged. The existing `model`, `prompt_tokens`, `completion_tokens` columns continue to be written by the existing path.
- No new LLM provider implementations. v1's `ModelDescriptor` carries a `provider: str` field for future use; routing today still goes through the existing `OpenAICompatibleClient`.
- **`ProviderABC` + non-OpenAI providers deferred to AD-463b.**
- **MAD (Multi-Agent Debate) confidence scoring deferred to AD-463c.**
- **Brain diversity / per-agent model preference deferred to AD-463d.**
- **Hot-swap (live model swap without restart) deferred to AD-463e.**
- **Per-model edit-format selection deferred to AD-463f.**
- **Cost aggregation queries** -- v1 emits MODEL_ROUTED with chosen model + tier; aggregation is AD-467d Cost Tracker scope (sibling Wave 7).
- AD-463 introduces NO destructive intents -- `requires_consensus=True` rule does not apply.

---

## Tracking

- `PROGRESS.md`: add `AD-463 CLOSED. Model Diversity & Neural Routing (v1 foundation; 6 capabilities deferred to AD-463b/c/d/e/f and AD-467d) -- ...`
- `docs/development/roadmap.md`: flip AD-463 status from `*(planned)*` to `*(partial -- v1 foundation; provider/MAD/diversity/hot-swap/edit-format/cost-aggregation deferred)*` near line 4169.
- `DECISIONS.md`: optional entry recording the v1-4-primitives + 6-deferred-sub-AD scope decision; this is the canonical no-theater example for foundation work.

---

## Pre-Commit Sanity Check (HARD RULE)

```pwsh
git diff --cached --stat
```

If any tracker file shows >200 deletions, STOP.

Expected delta:
- `src/probos/cognitive/model_registry.py`: ~155 lines (new).
- `src/probos/cognitive/model_router.py`: ~190 lines (new).
- `src/probos/cognitive/llm_client.py`: ~20 lines added (Section 3 hook).
- `src/probos/events.py`: 2 lines added.
- `src/probos/config.py`: ~7 lines added.
- `src/probos/startup/finalize.py`: ~25 lines added.
- `tests/test_ad463_model_routing.py`: ~290 lines (new).
- `PROGRESS.md`, `roadmap.md`: ~3 lines changed.

---

## Acceptance Criteria

- All 15 tests pass under `pytest tests/test_ad463_model_routing.py -v -n 0`.
- Full parallel gate non-decreasing.
- 2 new EventTypes appear exactly once in `events.py`.
- `runtime.model_registry` and `runtime.model_router` are public attributes (no leading underscore).
- `OpenAICompatibleClient.__init__` accepts optional `model_router=None`; when absent, all existing call sites continue to work unchanged.
- `_resolve_model_for_tier` is wired into `complete()` such that an active ModelRouter overrides the default tier->model mapping; when ModelRouter is absent, the existing default applies.
- v1 ships only ModelRegistry, ModelDescriptor, ModelRouter, and one real consumer hook. ProviderABC, MAD, brain diversity, hot-swap, edit-format selection, and cost aggregation explicitly deferred to AD-463b/c/d/e/f and AD-467d.
- `BaseLLMClient`, `MockLLMClient`, `HebbianRouter`, `CognitiveJournal` are unchanged.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-01)

```
grep -n "class BaseLLMClient\|class OpenAICompatibleClient\|class MockLLMClient" src/probos/cognitive/llm_client.py
  22: class BaseLLMClient(ABC):
  44: class OpenAICompatibleClient(BaseLLMClient):
  823: class MockLLMClient(BaseLLMClient):

grep -n "async def complete" src/probos/cognitive/llm_client.py
  26: async def complete(self, request: LLMRequest, *, priority: Priority = Priority.NORMAL) -> LLMResponse:
  385: async def complete(self, request: LLMRequest, *, priority: Priority = Priority.NORMAL) -> LLMResponse:
  1023: async def complete(self, request: LLMRequest, *, priority: Priority = Priority.NORMAL) -> LLMResponse:

grep -n "class HebbianRouter\|def get_weight" src/probos/mesh/routing.py
  39: class HebbianRouter:
  142: def get_weight(

grep -n "class CognitiveJournal\|model\|prompt_tokens\|completion_tokens" src/probos/cognitive/journal.py | head -10
  27: model       TEXT NOT NULL DEFAULT '',
  28: prompt_tokens    INTEGER NOT NULL DEFAULT 0,
  29: completion_tokens INTEGER NOT NULL DEFAULT 0,
  56: class CognitiveJournal:
  (existing schema; AD-463 reads these columns indirectly via journal writes from the existing path; no schema change)

grep -rn "class ModelRegistry\|class ModelRouter\|class ProviderABC\|class ModelDescriptor" src/probos/
  (no matches -- AD-463 introduces these names)

grep -n "MODEL_ROUTED\|MODEL_FALLBACK" src/probos/events.py
  (no matches -- names are free)

grep -n "AGENT_SELF_NAMED\|INFODYNAMIC_REPORT" src/probos/events.py
  190: AGENT_SELF_NAMED = "agent_self_named"  # AD-499
  (terminal fallback)

grep -n "self\.hebbian_router\|self\.llm_client" src/probos/runtime.py | head -3
  304: self.hebbian_router = HebbianRouter(...)
  347: self.llm_client: BaseLLMClient = llm_client or MockLLMClient()
  (both public; AD-463 reads via runtime.X)

grep -n "orders: OrdersConfig" src/probos/config.py
  1593: orders: OrdersConfig = OrdersConfig()  # AD-440
  (always-available terminal fallback)

grep -n "def emit_event" src/probos/runtime.py
  775: def emit_event(self, event: BaseEvent | str | EventType, ...
```
