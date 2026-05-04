"""Creative skills inventory (AD-525 v1).

Stateless catalog of creative skills with per-skill Big Five trait affinity.
Read-only surface. Default catalog is seeded from the AD-525 roadmap entry;
extensible at runtime via :meth:`CreativeSkillsRegistry.register_skill`
(no persistence in v1 — runtime-only).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from probos.events import EventType

logger = logging.getLogger(__name__)


_BIG_FIVE: tuple[str, ...] = (
    "openness",
    "conscientiousness",
    "extraversion",
    "agreeableness",
    "neuroticism",
)


@dataclass(frozen=True)
class CreativeSkill:
    """A creative skill agents can adopt. AD-525 v1.

    Big Five affinity values are 0.0-1.0. Omitted traits default to 0.5
    (neutral). Lower neuroticism indicates a better fit for skills where
    emotional steadiness helps (e.g. Music Composition).
    """

    skill_id: str
    name: str
    medium: tuple[str, ...]
    openness: float = 0.5
    conscientiousness: float = 0.5
    extraversion: float = 0.5
    agreeableness: float = 0.5
    neuroticism: float = 0.5


class CreativeSkillsRegistry:
    """Catalog of creative skills with per-skill personality affinity.

    Read-only surface. AD-525 v1. Default catalog seeded from the roadmap
    table (8 skills); extensible via :meth:`register_skill` (no persistence
    in v1 — runtime-only).
    """

    DEFAULT_SKILLS: tuple[CreativeSkill, ...] = (
        CreativeSkill(
            "creative_writing",
            "Creative Writing",
            ("prose", "poetry", "journal"),
            openness=0.85,
        ),
        CreativeSkill(
            "technical_writing",
            "Technical Writing",
            ("documentation", "tutorial", "guide"),
            conscientiousness=0.85,
        ),
        CreativeSkill(
            "code_as_art",
            "Code as Art",
            ("generative", "visualization"),
            openness=0.80,
        ),
        CreativeSkill(
            "visual_design",
            "Visual Design",
            ("svg", "diagram", "schematic"),
            openness=0.80,
        ),
        CreativeSkill(
            "music_composition",
            "Music Composition",
            ("algorithmic", "procedural"),
            openness=0.80,
            neuroticism=0.30,
        ),
        CreativeSkill(
            "philosophy",
            "Philosophy",
            ("essay", "analysis"),
            openness=0.85,
            conscientiousness=0.80,
        ),
        CreativeSkill(
            "historiography",
            "Historiography",
            ("history", "chronicle"),
            conscientiousness=0.85,
        ),
        CreativeSkill(
            "comedy_satire",
            "Comedy/Satire",
            ("humor", "observational"),
            openness=0.75,
            extraversion=0.80,
        ),
    )

    def __init__(self) -> None:
        self._skills: dict[str, CreativeSkill] = {
            s.skill_id: s for s in self.DEFAULT_SKILLS
        }
        # Late-bind setter (Wave 5 convention #5).
        self._emit_event_fn: Callable[..., None] | None = None

    def list_skills(self) -> tuple[CreativeSkill, ...]:
        """Return all registered skills."""
        return tuple(self._skills.values())

    def get_skill(self, skill_id: str) -> CreativeSkill | None:
        """Return skill by id; ``None`` if absent."""
        return self._skills.get(skill_id)

    def affinity_score(self, skill_id: str, traits: dict[str, float]) -> float:
        """Compute affinity score for an agent's Big Five traits against a skill.

        Args:
            skill_id: The creative skill to score.
            traits: Agent's Big Five trait values, keyed by trait name
                (openness, conscientiousness, extraversion, agreeableness,
                neuroticism), values 0.0-1.0. Callers typically project a
                ``CrewProfile`` via ``profile.personality.to_dict()``.

        Returns:
            Affinity score 0.0-1.0. Higher = better fit. Computed as
            ``1.0 - mean(|trait - skill_affinity|)`` across all 5 Big Five
            dimensions. Returns 0.0 if ``skill_id`` is absent or ``traits``
            is empty.

        Emits ``CREATIVE_SKILL_AFFINITY_QUERIED`` with
        ``{agent_traits, skill_id, score}``.
        """
        skill = self._skills.get(skill_id)
        if skill is None or not traits:
            return 0.0

        diffs: list[float] = []
        for trait in _BIG_FIVE:
            agent_val = traits.get(trait, 0.5)
            skill_val = getattr(skill, trait)
            diffs.append(abs(agent_val - skill_val))
        score = 1.0 - (sum(diffs) / len(diffs))
        # Clamp into [0.0, 1.0] in case of out-of-range trait inputs.
        if score < 0.0:
            score = 0.0
        elif score > 1.0:
            score = 1.0

        if self._emit_event_fn is not None:
            try:
                self._emit_event_fn(
                    EventType.CREATIVE_SKILL_AFFINITY_QUERIED,
                    {
                        "agent_traits": dict(traits),
                        "skill_id": skill_id,
                        "score": score,
                    },
                )
            except Exception:
                logger.debug(
                    "AD-525: failed to emit CREATIVE_SKILL_AFFINITY_QUERIED",
                    exc_info=True,
                )
        return score

    def top_skills_for(
        self, traits: dict[str, float], k: int = 3
    ) -> list[tuple[CreativeSkill, float]]:
        """Return top ``k`` skills by affinity score, descending.

        Returns an empty list if ``traits`` is empty or ``k <= 0``.
        """
        if not traits or k <= 0:
            return []
        scored: list[tuple[CreativeSkill, float]] = []
        for skill in self._skills.values():
            scored.append((skill, self.affinity_score(skill.skill_id, traits)))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:k]

    def register_skill(self, skill: CreativeSkill) -> None:
        """Add a skill to the registry.

        Last-write-wins on ``skill_id`` collision.
        """
        self._skills[skill.skill_id] = skill
