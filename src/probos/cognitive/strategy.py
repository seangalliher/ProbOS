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
    # Minimum domain similarity for cognitive agent skill targeting (AD-200)
    _DOMAIN_MATCH_THRESHOLD = 0.3
    # Weight for domain match score in add_skill confidence (AD-200)
    _DOMAIN_MATCH_WEIGHT = 0.2

    def __init__(
        self,
        intent_descriptors: list[IntentDescriptor],
        llm_equipped_types: set[str],
        agent_classes: dict[str, type] | None = None,
    ) -> None:
        self._descriptors = intent_descriptors
        self._llm_equipped_types = llm_equipped_types
        self._agent_classes = agent_classes or {}

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

        # Compute maximum semantic similarity with any LLM-equipped agent's descriptors
        max_overlap = 0.0
        for desc in self._descriptors:
            overlap = self._compute_overlap(intent_name, intent_description, desc)
            if overlap > max_overlap:
                max_overlap = overlap

        # Domain-aware skill targeting (AD-200): find best cognitive agent
        target_type, domain_score = self._find_best_skill_target(
            intent_name, intent_description,
        )

        # If we have LLM-equipped types and there's some overlap, propose add_skill
        if self._llm_equipped_types and max_overlap > 0.0:
            skill_confidence = min(
                max_overlap + self._REVERSIBILITY_BONUS + (domain_score * self._DOMAIN_MATCH_WEIGHT),
                1.0,
            )
            if target_type != "skill_agent":
                label = f"Add skill to {target_type} agent"
                reason = (
                    f"The intent is semantically close to the {target_type} agent's domain "
                    f"(match: {domain_score:.2f}). Adding a skill is more reversible than "
                    f"creating a new agent."
                )
            else:
                label = "Add skill to existing agent"
                reason = (
                    "The intent has semantic similarity with existing capabilities. "
                    "Adding a skill is more reversible than creating a new agent."
                )
            options.append(StrategyOption(
                strategy="add_skill",
                label=label,
                reason=reason,
                confidence=round(skill_confidence, 2),
                target_agent_type=target_type,
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

    def _find_best_skill_target(
        self,
        intent_name: str,
        intent_description: str,
    ) -> tuple[str, float]:
        """Find the best cognitive agent to attach a skill to.

        Returns (target_agent_type, domain_match_score).
        Falls back to ("skill_agent", 0.0) if no cognitive match.
        """
        if not self._agent_classes:
            return "skill_agent", 0.0

        best_type = "skill_agent"
        best_score = 0.0

        intent_text = f"{intent_name} {intent_description}".replace("_", " ")

        for agent_type, agent_cls in self._agent_classes.items():
            instructions = getattr(agent_cls, "instructions", None)
            if not instructions:
                continue
            # Score intent description against agent's domain instructions
            score = self._compute_text_similarity(intent_text, instructions)
            if score > best_score and score >= self._DOMAIN_MATCH_THRESHOLD:
                best_score = score
                best_type = agent_type

        return best_type, best_score

    def _compute_text_similarity(self, text_a: str, text_b: str) -> float:
        """Compute similarity between two text strings.

        Uses embedding-based similarity when available, falls back to Jaccard.
        """
        try:
            from probos.knowledge.embeddings import compute_similarity
            sim = compute_similarity(text_a, text_b)
            if sim > 0.0:
                return sim
        except Exception:
            pass  # Keyword fallback — embedding unavailable

        # Fallback: keyword overlap (Jaccard)
        tokens_a = self._tokenize(text_a)
        tokens_b = self._tokenize(text_b)
        if not tokens_a or not tokens_b:
            return 0.0
        overlap = tokens_a & tokens_b
        union = tokens_a | tokens_b
        return len(overlap) / len(union) if union else 0.0

    def _compute_overlap(
        self,
        intent_name: str,
        intent_description: str,
        descriptor: IntentDescriptor,
    ) -> float:
        """Compute similarity between intent name/description and an existing
        descriptor's name/description.

        Uses semantic similarity via embeddings when available, falls back
        to keyword overlap (Jaccard tokenization).
        """
        intent_text = f"{intent_name} {intent_description}".replace("_", " ")
        desc_text = f"{descriptor.name} {descriptor.description}".replace("_", " ")
        return self._compute_text_similarity(intent_text, desc_text)

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
