"""AD-618e: Cognitive JIT Bridge — Bill step completion → T3 skill acquisition.

Listens to BILL_STEP_COMPLETED events and feeds SkillBridge to auto-acquire
skills, record exercises, and build agent proficiency from operational
experience. Pure side-effect listener — does not modify BillRuntime behavior.

Navy model: automated PQS sign-off from demonstrated watchstanding competence.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from probos.skill_framework import ProficiencyLevel

if TYPE_CHECKING:
    from probos.cognitive.skill_bridge import SkillBridge
    from probos.cognitive.skill_catalog import CognitiveSkillCatalog, CognitiveSkillEntry
    from probos.skill_framework import AgentSkillService
    from probos.sop.runtime import BillRuntime

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StepSkillMapping:
    """Maps a bill step action type to a T3 skill_id.

    The mapping can be scoped to a specific bill_id + step_id (exact match)
    or to an action type (broad match). Exact matches take priority.
    """

    skill_id: str                 # T3 skill to exercise/acquire
    action: str = ""              # StepAction value (e.g., "cognitive_skill", "tool")
    bill_id: str = ""             # Specific bill (empty = all bills)
    step_id: str = ""             # Specific step (empty = all steps with matching action)
    min_proficiency_to_acquire: ProficiencyLevel = ProficiencyLevel.FOLLOW


DEFAULT_STEP_SKILL_MAPPINGS: list[StepSkillMapping] = [
    # Cognitive skill steps → "duty_execution" (general operational competence)
    StepSkillMapping(skill_id="duty_execution", action="cognitive_skill"),
    # Tool usage steps → "tool_operation" (general tool proficiency)
    StepSkillMapping(skill_id="tool_operation", action="tool"),
    # Communication steps → "communication" (Ward Room proficiency)
    StepSkillMapping(skill_id="communication", action="post_to_channel"),
    StepSkillMapping(skill_id="communication", action="send_dm"),
    # Sub-bill orchestration → "coordination" (multi-agent coordination)
    StepSkillMapping(skill_id="coordination", action="sub_bill"),
]


class BillJITBridge:
    """Bridges Bill step completions to T3 skill proficiency tracking.

    Subscribes to BILL_STEP_COMPLETED events. For each completed step:
    1. Resolve the step's action type to a T3 skill_id via StepSkillMapping
    2. Look up matching CognitiveSkillEntry in the catalog (if any)
    3. Call SkillBridge.record_skill_exercise() to update proficiency

    Pure listener — never modifies BillRuntime, step outcomes, or agent state
    beyond skill proficiency records. Log-and-degrade on all errors.

    Parameters
    ----------
    skill_bridge : SkillBridge
        The T2↔T3 bridge for skill exercise recording.
    catalog : CognitiveSkillCatalog
        The T2 cognitive skill catalog for entry lookup.
    skill_service : AgentSkillService
        The T3 skill service for direct exercise recording (when no
        catalog entry exists). Passed explicitly to avoid reaching
        into SkillBridge's private ``_service`` attribute.
    mappings : list[StepSkillMapping], optional
        Custom step→skill mappings. Defaults to DEFAULT_STEP_SKILL_MAPPINGS.
    """

    def __init__(
        self,
        skill_bridge: SkillBridge,
        catalog: CognitiveSkillCatalog,
        skill_service: AgentSkillService,
        mappings: list[StepSkillMapping] | None = None,
    ) -> None:
        self._bridge = skill_bridge
        self._catalog = catalog
        self._skill_service = skill_service
        self._mappings = mappings or list(DEFAULT_STEP_SKILL_MAPPINGS)
        self._exercise_count: int = 0

    @property
    def exercise_count(self) -> int:
        """Total skill exercises recorded since initialization."""
        return self._exercise_count

    def add_mapping(self, mapping: StepSkillMapping) -> None:
        """Add a custom step→skill mapping at runtime."""
        self._mappings.append(mapping)

    def resolve_mapping(
        self,
        bill_id: str,
        step_id: str,
        action: str,
    ) -> StepSkillMapping | None:
        """Resolve the best StepSkillMapping for a completed step.

        Priority order:
        1. Exact match (bill_id + step_id)
        2. Bill-scoped action match (bill_id + action)
        3. Global action match (action only)

        Returns None if no mapping matches.
        """
        exact: StepSkillMapping | None = None
        bill_action: StepSkillMapping | None = None
        global_action: StepSkillMapping | None = None

        for m in self._mappings:
            # Exact match
            if m.bill_id and m.step_id and m.bill_id == bill_id and m.step_id == step_id:
                exact = m
                break  # Highest priority — stop searching
            # Bill-scoped action match
            if m.bill_id and not m.step_id and m.bill_id == bill_id and m.action == action:
                if not bill_action:
                    bill_action = m
            # Global action match
            if not m.bill_id and not m.step_id and m.action == action:
                if not global_action:
                    global_action = m

        return exact or bill_action or global_action

    async def on_step_completed(self, event: dict[str, Any]) -> None:
        """Handle a BILL_STEP_COMPLETED event envelope.

        Receives the full event envelope from runtime event emission or
        NATS callback — both deliver the same shape:
        ``{"type": "bill_step_completed", "data": {...}, "timestamp": ...}``

        The AD-618b payload fields (instance_id, bill_id, step_id, action,
        agent_id, agent_type, duration_s) live under event["data"].

        Log-and-degrade: never raises. A failure here must not affect
        bill execution or agent operations.
        """
        try:
            event_data = event.get("data", {}) if isinstance(event, dict) else {}

            bill_id = event_data.get("bill_id", "")
            step_id = event_data.get("step_id", "")
            action = event_data.get("action", "")
            agent_id = event_data.get("agent_id", "")

            if not agent_id:
                logger.debug(
                    "AD-618e: BILL_STEP_COMPLETED without agent_id — skipping JIT",
                )
                return

            # 1. Resolve mapping
            mapping = self.resolve_mapping(bill_id, step_id, action)
            if not mapping:
                logger.debug(
                    "AD-618e: No skill mapping for step %s/%s (action=%s)",
                    bill_id, step_id, action,
                )
                return

            # 2. Find CognitiveSkillEntry in catalog (if exists)
            entry = self._find_catalog_entry(mapping.skill_id)

            # 3. Record exercise via SkillBridge
            if entry:
                await self._bridge.record_skill_exercise(agent_id, entry)
            else:
                # No catalog entry — record directly via SkillBridge's
                # underlying service (auto-acquire at mapping's proficiency)
                await self._record_direct_exercise(agent_id, mapping)

            self._exercise_count += 1
            logger.debug(
                "AD-618e: Recorded skill exercise for %s — skill=%s (bill=%s, step=%s)",
                agent_id, mapping.skill_id, bill_id, step_id,
            )

        except Exception:
            # Log-and-degrade — JIT bridge must never crash
            logger.debug(
                "AD-618e: JIT bridge error on step completion",
                exc_info=True,
            )

    def _find_catalog_entry(self, skill_id: str) -> Any:
        """Look up CognitiveSkillEntry by skill_id in the catalog.

        Returns None if not found. The catalog may not have an entry for
        every T3 skill — that's fine, we fall back to direct recording.
        """
        for entry in self._catalog.list_entries():
            if entry.skill_id == skill_id:
                return entry
        return None

    async def _record_direct_exercise(
        self,
        agent_id: str,
        mapping: StepSkillMapping,
    ) -> None:
        """Record exercise directly via AgentSkillService when no catalog entry exists.

        Direct path mirrors SkillBridge.record_skill_exercise auto-acquire logic;
        required because SkillBridge.record_skill_exercise needs a CognitiveSkillEntry,
        not a bare skill_id.

        Uses the injected skill service to record_exercise().
        If the agent doesn't have the skill, auto-acquires at the mapping's
        proficiency level.
        """
        try:
            record = await self._skill_service.record_exercise(agent_id, mapping.skill_id)
            if record is None:
                # Auto-acquire at mapping's proficiency level
                await self._skill_service.acquire_skill(
                    agent_id,
                    mapping.skill_id,
                    source="bill_step_completion",
                    proficiency=mapping.min_proficiency_to_acquire,
                )
                await self._skill_service.record_exercise(agent_id, mapping.skill_id)
                logger.info(
                    "AD-618e: Auto-acquired skill '%s' for %s via bill step completion",
                    mapping.skill_id, agent_id,
                )
        except ValueError as e:
            # acquire_skill raises ValueError when prerequisites not met
            logger.info(
                "AD-618e: Cannot auto-acquire '%s' for %s — prerequisite not met: %s",
                mapping.skill_id, agent_id, e,
            )
        except Exception:
            logger.debug(
                "AD-618e: Direct exercise recording failed for %s / %s",
                agent_id, mapping.skill_id, exc_info=True,
            )

    def get_stats(self) -> dict[str, Any]:
        """Return diagnostic stats for the JIT bridge."""
        return {
            "exercise_count": self._exercise_count,
            "mapping_count": len(self._mappings),
            "custom_mappings": sum(
                1 for m in self._mappings if m.bill_id or m.step_id
            ),
        }
