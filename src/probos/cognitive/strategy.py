"""StrategyRecommender — proposes strategies for handling unhandled intents."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from probos.types import IntentDescriptor


@dataclass
class StrategyOption:
    """A proposed strategy for handling an unhandled intent."""

    strategy: str  # "new_agent" or "add_skill"
    label: str  # Human-readable label, e.g., "Create new TranslateTextAgent"
    reason: str  # Why this strategy is recommended
    confidence: float  # 0.0-1.0 — how confident the recommender is
    target_agent_type: str | None = None  # For add_skill: which agent to extend
    is_recommended: bool = False  # Whether this is the top recommendation


@dataclass
class StrategyProposal:
    """A set of strategy options for handling an unhandled intent."""

    intent_name: str
    intent_description: str
    options: list[StrategyOption] = field(default_factory=list)

    @property
    def recommended(self) -> StrategyOption | None:
        """Return the recommended option, or None."""
        return next((o for o in self.options if o.is_recommended), None)


class StrategyRecommender:
    """Analyzes an unhandled intent and proposes strategies.

    Two strategies are available:

    1. **add_skill** — If an existing agent type in llm_equipped_types
       could plausibly handle the new intent (based on keyword overlap
       between the intent and the agent's existing descriptors), suggest
       adding a skill. Scored higher than new_agent when both are viable
       (reversibility preference — a skill can be removed without
       destroying an agent pool).

    2. **new_agent** — Always available as a fallback. Confidence is higher
       when the intent has no overlap with existing capabilities.

    The recommender returns ALL viable options sorted by confidence.
    The user chooses. The system does NOT auto-select.
    """

    # Reversibility bonus for add_skill over new_agent (AD-127)
    _REVERSIBILITY_BONUS = 0.1

    def __init__(
        self,
        intent_descriptors: list[IntentDescriptor],
        llm_equipped_types: set[str],
    ) -> None:
        self._descriptors = intent_descriptors
        self._llm_equipped_types = llm_equipped_types

    def propose(
        self,
        intent_name: str,
        intent_description: str,
        parameters: dict[str, str],
    ) -> StrategyProposal:
        """Analyze the intent and return a StrategyProposal with options.

        Must always return at least one option (new_agent is always viable).
        Options sorted by confidence descending.
        The highest-confidence option has is_recommended=True.
        """
        options: list[StrategyOption] = []

        # Compute maximum keyword overlap with any LLM-equipped agent's descriptors
        max_overlap = 0.0
        best_agent_type: str | None = None
        for desc in self._descriptors:
            # Only consider descriptors from LLM-equipped agent types
            # We check via agent_type inference: descriptors don't carry agent_type,
            # so we check if any llm_equipped_type exists (skill_agent, introspection)
            overlap = self._keyword_overlap(intent_name, intent_description, desc)
            if overlap > max_overlap:
                max_overlap = overlap
                best_agent_type = None  # will assign below

        # If we have LLM-equipped types and there's some overlap, propose add_skill
        if self._llm_equipped_types and max_overlap > 0.0:
            # Pick first LLM-equipped type as target (prefer skill_agent)
            target = "skill_agent" if "skill_agent" in self._llm_equipped_types else next(iter(self._llm_equipped_types))
            skill_confidence = min(max_overlap + self._REVERSIBILITY_BONUS, 1.0)
            class_name = self._build_class_name(intent_name)
            options.append(StrategyOption(
                strategy="add_skill",
                label=f"Add skill to existing agent",
                reason=(
                    f"The intent has keyword overlap with existing capabilities. "
                    f"Adding a skill is more reversible than creating a new agent."
                ),
                confidence=round(skill_confidence, 2),
                target_agent_type=target,
            ))

        # new_agent is always available
        # Confidence is higher when no overlap exists
        new_agent_confidence = max(0.3, 1.0 - max_overlap) if max_overlap > 0 else 0.6
        class_name = self._build_class_name(intent_name)
        options.append(StrategyOption(
            strategy="new_agent",
            label=f"Create new {class_name}",
            reason=(
                f"Dedicated agent for {intent_name.replace('_', ' ')} tasks. "
                f"Will be created with probationary trust (0.25)."
            ),
            confidence=round(new_agent_confidence, 2),
        ))

        # Sort by confidence descending
        options.sort(key=lambda o: o.confidence, reverse=True)

        # Mark the highest-confidence option as recommended
        if options:
            options[0].is_recommended = True

        return StrategyProposal(
            intent_name=intent_name,
            intent_description=intent_description,
            options=options,
        )

    def _keyword_overlap(
        self,
        intent_name: str,
        intent_description: str,
        descriptor: IntentDescriptor,
    ) -> float:
        """Compute keyword overlap between intent name/description tokens
        and an existing descriptor's name/description tokens.

        Uses the same tokenization as attention relevance (AD-55):
        split on underscores and spaces, filter tokens < 3 chars,
        compute overlap ratio.
        """
        intent_tokens = self._tokenize(f"{intent_name} {intent_description}")
        desc_tokens = self._tokenize(f"{descriptor.name} {descriptor.description}")

        if not intent_tokens or not desc_tokens:
            return 0.0

        overlap = intent_tokens & desc_tokens
        # Jaccard-style: overlap / union
        union = intent_tokens | desc_tokens
        return len(overlap) / len(union) if union else 0.0

    def _tokenize(self, text: str) -> set[str]:
        """Tokenize text by splitting on underscores and spaces, filtering short tokens."""
        tokens = set()
        for word in text.replace("_", " ").lower().split():
            if len(word) >= 3:
                tokens.add(word)
        return tokens

    def _build_class_name(self, intent_name: str) -> str:
        """Convert intent_name like 'translate_text' to 'TranslateTextAgent'."""
        parts = intent_name.split("_")
        return "".join(p.capitalize() for p in parts) + "Agent"
