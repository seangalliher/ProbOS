"""AD-463: ModelRegistry -- in-memory catalog of available LLM models.

v1: read-only public catalog seeded from defaults. Future ADs (AD-463b/c/d/e/f)
will extend with provider abstraction, MAD scoring, hot-swap, edit-format
selection.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
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
      - ``register(descriptor)`` -- add or overwrite by name.
      - ``get(name) -> ModelDescriptor | None``.
      - ``by_tier(tier) -> list[ModelDescriptor]`` -- all available models in tier.
      - ``all() -> list[ModelDescriptor]``.
      - ``mark_unavailable(name)`` / ``mark_available(name)`` -- transient state changes
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
