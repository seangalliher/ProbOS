"""AD-596c: Skill-Registry Bridge.

Stateless coordinator connecting CognitiveSkillCatalog (T2 instruction-defined skills)
and SkillRegistry/AgentSkillService (T3 proficiency-tracked skills).

No database. No lifecycle. Constructed once at startup with references to both systems.
Dependency Inversion: depends on public APIs of both services, not their internals.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from probos.cognitive.skill_catalog import CognitiveSkillCatalog, CognitiveSkillEntry
    from probos.skill_framework import AgentSkillService, SkillProfile, SkillRegistry

logger = logging.getLogger(__name__)


class SkillBridge:
    """Bridges CognitiveSkillCatalog (T2) and SkillRegistry/AgentSkillService (T3).

    Stateless coordinator — no database, no lifecycle. Constructed once at startup
    with references to both systems.
    """

    def __init__(
        self,
        catalog: CognitiveSkillCatalog,
        skill_registry: SkillRegistry,
        skill_service: AgentSkillService,
    ) -> None:
        self._catalog = catalog
        self._registry = skill_registry
        self._service = skill_service

    # ── Startup Sync ──────────────────────────────────────────────────

    async def validate_and_sync(self) -> dict[str, Any]:
        """Validate skill_id mappings between T2 catalog and T3 registry at startup.

        For each CognitiveSkillEntry with a non-empty skill_id:
        1. Verify the skill_id exists in SkillRegistry
        2. Log warnings for unmatched skill_ids
        3. Return summary: matched, unmatched, no_skill_id
        """
        matched: list[str] = []
        unmatched: list[str] = []
        no_skill_id: list[str] = []

        registered_ids = {s.skill_id for s in self._registry.list_skills()}

        for entry in self._catalog.list_entries():
            if not entry.skill_id:
                no_skill_id.append(entry.name)
                continue
            if entry.skill_id in registered_ids:
                matched.append(entry.name)
            else:
                unmatched.append(entry.name)
                logger.warning(
                    "AD-596c: Cognitive skill '%s' references skill_id '%s' "
                    "not found in SkillRegistry — proficiency gating will be inactive",
                    entry.name,
                    entry.skill_id,
                )

        result = {
            "matched": len(matched),
            "unmatched": len(unmatched),
            "no_skill_id": len(no_skill_id),
            "unmatched_names": unmatched,
        }
        logger.info(
            "AD-596c: Skill bridge sync — %d matched, %d unmatched, %d ungoverned",
            len(matched), len(unmatched), len(no_skill_id),
        )
        return result

    # ── Proficiency Gating ────────────────────────────────────────────

    def check_proficiency_gate(
        self,
        agent_id: str,
        entry: CognitiveSkillEntry,
        agent_profile: SkillProfile | None,
    ) -> bool:
        """Check if agent meets the proficiency requirement for a cognitive skill.

        If entry.skill_id is empty or entry.min_proficiency <= 1: always True (ungoverned).
        Otherwise: lookup agent's AgentSkillRecord for that skill_id,
        return record.proficiency >= entry.min_proficiency.
        """
        # Ungoverned skills (no skill_id or min_proficiency not set) — always pass
        if not entry.skill_id or entry.min_proficiency <= 1:
            return True

        # No profile available — fail closed (agent hasn't been profiled yet)
        if not agent_profile:
            logger.debug(
                "AD-596c: Proficiency gate FAIL for %s on '%s' — no profile",
                agent_id, entry.name,
            )
            return False

        # Search for matching skill record across all skill categories
        for record in agent_profile.all_skills:
            if record.skill_id == entry.skill_id:
                passes = record.proficiency >= entry.min_proficiency
                if not passes:
                    logger.debug(
                        "AD-596c: Proficiency gate FAIL for %s on '%s' — "
                        "has %d, needs %d",
                        agent_id, entry.name,
                        record.proficiency, entry.min_proficiency,
                    )
                return passes

        # Agent has no record for this skill — fail
        logger.debug(
            "AD-596c: Proficiency gate FAIL for %s on '%s' — "
            "skill_id '%s' not in profile",
            agent_id, entry.name, entry.skill_id,
        )
        return False

    # ── Exercise Recording ────────────────────────────────────────────

    async def record_skill_exercise(
        self,
        agent_id: str,
        entry: CognitiveSkillEntry,
    ) -> None:
        """Record that an agent activated a cognitive skill.

        If entry.skill_id is empty: no-op (ungoverned skill, no proficiency tracking).
        If agent has no record for skill_id: auto-acquire at FOLLOW (1).
        Then call record_exercise() to update last_exercised and exercise_count.
        Log-and-degrade on any failure — skill activation must not be blocked by tracking errors.
        """
        if not entry.skill_id:
            return  # Ungoverned — no tracking

        try:
            # Check if agent has this skill; auto-acquire if not
            record = await self._service.record_exercise(agent_id, entry.skill_id)
            if record is None:
                # Agent doesn't have this skill yet — auto-acquire at FOLLOW
                from probos.skill_framework import ProficiencyLevel
                await self._service.acquire_skill(
                    agent_id,
                    entry.skill_id,
                    source="cognitive_skill_activation",
                    proficiency=ProficiencyLevel.FOLLOW,
                )
                await self._service.record_exercise(agent_id, entry.skill_id)
                logger.info(
                    "AD-596c: Auto-acquired skill '%s' for %s via cognitive activation",
                    entry.skill_id, agent_id,
                )
        except Exception:
            # Log-and-degrade — never block skill activation for tracking errors
            logger.debug(
                "AD-596c: Exercise recording failed for %s / %s",
                agent_id, entry.skill_id, exc_info=True,
            )

    # ── Gap Predictor Bridge ──────────────────────────────────────────

    def resolve_skill_for_gap(
        self,
        intent_types: list[str],
    ) -> str:
        """Enhanced intent-to-skill mapping that consults CognitiveSkillCatalog.

        1. Check CognitiveSkillCatalog.find_by_intent() for T2 skill matches
        2. If found and entry.skill_id is set, return that skill_id
        3. Fall back to SkillRegistry exact-match (existing behavior)
        4. Final fallback: "duty_execution" PCC
        """
        # T2 catalog match — richer intent→skill mapping
        for intent in intent_types:
            entries = self._catalog.find_by_intent(intent)
            if entries:
                entry = entries[0]
                if entry.skill_id:
                    return entry.skill_id

        # T3 registry exact-match fallback (replaces old _intent_to_skill_id behavior)
        registered_ids = {s.skill_id for s in self._registry.list_skills()}
        for intent in intent_types:
            if intent in registered_ids:
                return intent

        return "duty_execution"
