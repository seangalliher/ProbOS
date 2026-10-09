"""AD-463: ModelRegistry -- in-memory catalog of available LLM models.

v1: read-only public catalog seeded from defaults. Future ADs (AD-463b/c/d/e/f)
will extend with provider abstraction, MAD scoring, hot-swap, edit-format
selection.

BF-886: the runtime's routing registry is seeded from the operator's
configured tier models (``ModelRegistry.from_tier_models``). The built-in
descriptors are a price and capability catalog for the names they list; they
are routing candidates only in a bare ``ModelRegistry()``.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import InitVar, dataclass, field, replace
from enum import Enum

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


# Built-in catalog: price, provider, capability and context-window metadata
# for the names it lists. BF-886: the runtime never routes to these names
# instead of the configured ones -- ``ModelRegistry.from_tier_models`` copies
# an entry's metadata onto a configured model whose name matches it exactly.
# A bare ``ModelRegistry()`` still seeds them as candidates.
_DEFAULT_DESCRIPTORS: tuple[ModelDescriptor, ...] = (
    ModelDescriptor(
        name="claude-sonnet-4-6-fast",
        provider="anthropic",
        tier="fast",
        capabilities=frozenset({ModelCapability.GENERAL, ModelCapability.FAST}),
        cost_per_million_input_tokens=3.0,
        cost_per_million_output_tokens=15.0,
        context_window_tokens=200_000,
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
        name="claude-opus-4-6",
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


_CATALOG_BY_NAME: dict[str, ModelDescriptor] = {d.name: d for d in _DEFAULT_DESCRIPTORS}


def catalog() -> tuple[ModelDescriptor, ...]:
    """BF-886: the built-in price catalog, in declaration order.

    A configured model is priced only when its name matches one of these
    exactly; the model router names them in its remedy for a tier the cost
    ceiling leaves without an admissible model.
    """
    return _DEFAULT_DESCRIPTORS


@dataclass
class ModelRegistry:
    """In-memory catalog. Seeded from defaults; operators extend at startup.

    Entries are keyed by ``(tier, name)``, so one model can serve several
    tiers: the shipped config names one model for both ``fast`` and
    ``standard`` (BF-886).

    Public API:
      - ``from_tier_models(tier_models)`` -- BF-886: a registry holding exactly
        the configured model of each tier, priced from the built-in catalog.
      - ``register(descriptor)`` -- add, or overwrite the entry with the same tier and name.
      - ``get(name) -> ModelDescriptor | None`` -- the first entry with that name.
      - ``by_tier(tier) -> list[ModelDescriptor]`` -- all available models in tier.
      - ``all() -> list[ModelDescriptor]`` -- every entry; a model in two tiers appears twice.
      - ``mark_unavailable(name)`` / ``mark_available(name)`` -- transient state changes
        for a future AD-463b health probe, applied to every tier the model serves;
        v1 sets but does not persist.
    """

    _descriptors: dict[tuple[str, str], ModelDescriptor] = field(default_factory=dict)
    seed_defaults: InitVar[bool] = True

    def __post_init__(self, seed_defaults: bool) -> None:
        if seed_defaults:
            for d in _DEFAULT_DESCRIPTORS:
                self.register(d)

    @classmethod
    def from_tier_models(cls, tier_models: Mapping[str, str]) -> ModelRegistry:
        """BF-886: a registry whose candidates are exactly the configured tier models.

        ``tier_models`` maps each tier to the model name the operator
        configured for it, and each tier gets one entry under that name. A
        name the built-in catalog lists exactly keeps the catalog's price,
        provider, capabilities and context window, re-tiered; any other name
        is registered with price 0.0 -- the descriptor's "unknown"
        convention, which no cost ceiling admits -- rather than replaced by a
        known model. A tier with no model name gets no entry. Catalog entries
        are never candidates here.
        """
        registry = cls(seed_defaults=False)
        for tier, name in tier_models.items():
            if not name:
                continue
            known = _CATALOG_BY_NAME.get(name)
            if known is None:
                registry.register(ModelDescriptor(name=name, provider="unknown", tier=tier))
            else:
                registry.register(replace(known, tier=tier))
        return registry

    def register(self, descriptor: ModelDescriptor) -> None:
        self._descriptors[(descriptor.tier, descriptor.name)] = descriptor

    def get(self, name: str) -> ModelDescriptor | None:
        for d in self._descriptors.values():
            if d.name == name:
                return d
        return None

    def by_tier(self, tier: str) -> list[ModelDescriptor]:
        return [d for d in self._descriptors.values() if d.tier == tier and d.available]

    def all(self) -> list[ModelDescriptor]:
        return list(self._descriptors.values())

    def mark_unavailable(self, name: str) -> bool:
        return self._set_available(name, False)

    def mark_available(self, name: str) -> bool:
        return self._set_available(name, True)

    def _set_available(self, name: str, available: bool) -> bool:
        changed = False
        for key, d in list(self._descriptors.items()):
            if d.name == name and d.available is not available:
                self._descriptors[key] = replace(d, available=available)
                changed = True
        return changed
