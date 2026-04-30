# AD-566f: Qualification → Skill Bridge

**Status:** Ready for builder
**Dependencies:** None
**Estimated tests:** ~7

---

## Problem

The `QualificationStore` (`cognitive/qualification.py`) tracks test
results (scores, pass/fail) for agents. The `SkillFramework`
(`skill_framework.py`) tracks skill proficiency levels (FOLLOW through
SHAPE (7-level Dreyfus scale)). These two systems don't talk to each other — passing a
qualification test doesn't automatically update skill proficiency.

An agent can pass all qualification tests for a skill but still show
FOLLOW-level proficiency because nothing bridges the qualification
outcome to a proficiency update.

## Fix

### Section 1: Create `QualificationSkillBridge`

**File:** `src/probos/cognitive/qual_skill_bridge.py` (new file)

```python
"""Qualification → Skill Bridge (AD-566f).

Bridges QualificationStore test results to SkillFramework
proficiency updates. When an agent passes qualification tests
at a sufficient score, their skill proficiency is advanced.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SkillAdvancement:
    """Record of a qualification-triggered skill advancement (AD-566f)."""

    agent_id: str
    skill_id: str
    from_level: int  # ProficiencyLevel value
    to_level: int
    qualification_test: str
    qualification_score: float
    reason: str = ""


# Score thresholds for proficiency advancement
# Keys are target ProficiencyLevel values (the level being advanced TO)
# ProficiencyLevel: FOLLOW(1), ASSIST(2), APPLY(3), ENABLE(4), ADVISE(5), LEAD(6), SHAPE(7)
DEFAULT_SCORE_THRESHOLDS: dict[int, float] = {
    2: 0.50,  # FOLLOW(1) → ASSIST(2) requires 50%
    3: 0.60,  # ASSIST(2) → APPLY(3) requires 60%
    4: 0.70,  # APPLY(3) → ENABLE(4) requires 70%
    5: 0.80,  # ENABLE(4) → ADVISE(5) requires 80%
    6: 0.90,  # ADVISE(5) → LEAD(6) requires 90%
    7: 0.95,  # LEAD(6) → SHAPE(7) requires 95%
}


class QualificationSkillBridge:
    """Maps qualification test results to skill proficiency updates (AD-566f).

    Usage:
        bridge = QualificationSkillBridge(
            skill_service=skill_service,
            qualification_store=qualification_store,
        )
        advancements = await bridge.process_qualification(
            agent_id="agent-1",
            test_name="threat_analysis_t1",
            score=0.85,
            passed=True,
        )
    """

    def __init__(
        self,
        *,
        skill_service: Any = None,
        qualification_store: Any = None,
        score_thresholds: dict[int, float] | None = None,
    ) -> None:
        self._skill_service = skill_service
        self._qualification_store = qualification_store
        self._score_thresholds = score_thresholds or dict(DEFAULT_SCORE_THRESHOLDS)
        # test_name → skill_id mapping
        self._test_skill_map: dict[str, str] = {}
        self._advancement_history: list[SkillAdvancement] = []

    def register_mapping(self, test_name: str, skill_id: str) -> None:
        """Map a qualification test to a skill."""
        self._test_skill_map[test_name] = skill_id

    def register_mappings(self, mappings: dict[str, str]) -> None:
        """Register multiple test → skill mappings."""
        self._test_skill_map.update(mappings)

    async def process_qualification(
        self,
        agent_id: str,
        test_name: str,
        score: float,
        passed: bool,
    ) -> SkillAdvancement | None:
        """Process a qualification result and potentially advance skill.

        Returns a SkillAdvancement if proficiency was updated, None otherwise.
        """
        if not passed:
            return None

        skill_id = self._test_skill_map.get(test_name)
        if not skill_id:
            logger.debug(
                "AD-566f: No skill mapping for test '%s'", test_name,
            )
            return None

        if not self._skill_service:
            return None

        # Get current proficiency
        profile = await self._skill_service.get_profile(agent_id)
        current_record = None
        for skill in profile.all_skills:
            if skill.skill_id == skill_id:
                current_record = skill
                break

        if not current_record:
            logger.debug(
                "AD-566f: Agent %s has no record for skill %s",
                agent_id[:12], skill_id,
            )
            return None

        current_level = current_record.proficiency.value
        target_level = current_level + 1

        # Check if score meets threshold for next level
        threshold = self._score_thresholds.get(target_level)
        if threshold is None:
            # Already at max level
            return None

        if score < threshold:
            logger.debug(
                "AD-566f: Score %.2f below threshold %.2f for level %d",
                score, threshold, target_level,
            )
            return None

        # Advance proficiency
        from probos.skill_framework import ProficiencyLevel
        new_level = ProficiencyLevel(target_level)

        await self._skill_service.update_proficiency(
            agent_id=agent_id,
            skill_id=skill_id,
            new_level=new_level,
            source="qualification",
            notes=f"Qualification test '{test_name}' score={score:.2f}",
        )

        advancement = SkillAdvancement(
            agent_id=agent_id,
            skill_id=skill_id,
            from_level=current_level,
            to_level=target_level,
            qualification_test=test_name,
            qualification_score=score,
            reason=f"Score {score:.2f} >= threshold {threshold:.2f}",
        )
        self._advancement_history.append(advancement)

        logger.info(
            "AD-566f: Advanced %s skill %s from level %d → %d (score %.2f)",
            agent_id[:12], skill_id, current_level, target_level, score,
        )

        return advancement

    def get_advancement_history(
        self, *, agent_id: str = "", limit: int = 50,
    ) -> list[SkillAdvancement]:
        """Query advancement history."""
        results = self._advancement_history
        if agent_id:
            results = [r for r in results if r.agent_id == agent_id]
        return results[-limit:]

    def get_mappings(self) -> dict[str, str]:
        """Return all test → skill mappings."""
        return dict(self._test_skill_map)
```

### Section 2: Wire bridge in startup

**File:** `src/probos/runtime.py`

Add after `self.skill_service = comm.skill_service` (around line 1551),
where both `self.skill_service` and `self._qualification_store` are available:

```python
    # AD-566f: Qualification → Skill Bridge
    self._qual_skill_bridge = None
    if self.skill_service and getattr(self, '_qualification_store', None):
        from probos.cognitive.qual_skill_bridge import QualificationSkillBridge
        self._qual_skill_bridge = QualificationSkillBridge(
            skill_service=self.skill_service,
            qualification_store=self._qualification_store,
        )
        # Register default test → skill mappings
        self._qual_skill_bridge.register_mappings({
            "threat_analysis_t1": "threat_analysis",
            "ward_room_communication_t1": "ward_room_communication",
            "trust_assessment_t1": "trust_assessment",
        })
        logger.info("AD-566f: QualificationSkillBridge initialized with %d mappings",
                    len(self._qual_skill_bridge.get_mappings()))
```

**Note:** `self._qualification_store` is set at runtime.py line 1310.
`self.skill_service` is set at runtime.py line 1551 (from `comm.skill_service`).

## Tests

**File:** `tests/test_ad566f_qual_skill_bridge.py`

7 tests:

1. `test_skill_advancement_creation` — create `SkillAdvancement`, verify fields
2. `test_register_mapping` — register test→skill mapping, verify `get_mappings()`
3. `test_process_qualification_no_mapping` — process unknown test → returns None
4. `test_process_qualification_failed` — process with `passed=False` → returns None
5. `test_process_qualification_below_threshold` — mock skill service with
   FOLLOW(1) agent, score 0.3 (below 0.50 threshold for ASSIST) → returns None
6. `test_process_qualification_advances` — mock skill service with FOLLOW(1)
   agent, score 0.6 (above 0.50 threshold for ASSIST) → returns SkillAdvancement
   with `from_level=1, to_level=2`, verify `update_proficiency` called
7. `test_advancement_history` — process multiple qualifications, verify
   `get_advancement_history()` returns correct list

## What This Does NOT Change

- `QualificationStore` unchanged — still stores test results independently
- `SkillFramework` / `AgentSkillService` unchanged — bridge calls its public API
- Qualification test execution unchanged
- Proficiency decay unchanged
- Does NOT add automatic qualification test triggering
- Does NOT add persistence for advancement history (in-memory only)
- Does NOT modify ProficiencyLevel enum

## Tracking

- `PROGRESS.md`: Add AD-566f as COMPLETE
- `docs/development/roadmap.md`: Update AD-566f status

## Acceptance Criteria

- `QualificationSkillBridge` with `process_qualification()` exists
- Test → skill mappings are configurable
- Score thresholds are configurable per proficiency level
- Passing a qualification with sufficient score advances proficiency
- Below-threshold scores don't advance
- All 7 new tests pass
- Full test gate: `pytest tests/ -q -n auto` — no regressions
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`

## Verified Against Codebase (2026-04-29)

```
# QualificationStore
grep -n "class QualificationStore" src/probos/cognitive/qualification.py
  136: class QualificationStore — SQLite persistence for qualification results

# SkillFramework
grep -n "class AgentSkillService\|def update_proficiency\|def get_profile" src/probos/skill_framework.py
  435: class AgentSkillService — runtime skill service
  542: update_proficiency(agent_id, skill_id, new_level, source, notes)
  611: get_profile(agent_id) → SkillProfile

# ProficiencyLevel (7-level Dreyfus scale)
grep -n "class ProficiencyLevel" src/probos/skill_framework.py
  38: FOLLOW(1), ASSIST(2), APPLY(3), ENABLE(4), ADVISE(5), LEAD(6), SHAPE(7)

# AgentSkillService (not "SkillService")
grep -n "class AgentSkillService" src/probos/skill_framework.py
  435: class AgentSkillService

# Startup wiring
# runtime._qualification_store set at runtime.py:1310
# runtime.skill_service set at runtime.py:1551 (from comm.skill_service)

# No existing bridge
grep -rn "QualificationSkillBridge\|qual_skill_bridge" src/probos/ → no matches
```
