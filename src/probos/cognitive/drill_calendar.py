"""AD-628d: Drill calendar — qualification-test scheduling queue.

Layered on top of AD-477 QualificationHarness. In-memory ring; durable
persistence is forcing-function letter AD-628i.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from probos.cognitive.qualification import QualificationHarness, TestResult


DrillStatus = Literal["scheduled", "executed", "missed"]


@dataclass(frozen=True)
class DrillEntry:
    """AD-628d: a scheduled qualification drill."""

    drill_id: str
    agent_id: str
    qualification_test: str
    scheduled_at: float
    status: DrillStatus = "scheduled"
    result: "TestResult | None" = None


class DrillCalendar:
    """AD-628d: in-memory drill scheduling layered on QualificationHarness."""

    def __init__(
        self,
        qualification_harness: "QualificationHarness",
        *,
        runtime: Any | None = None,
    ) -> None:
        self._harness = qualification_harness
        self._runtime = runtime
        self._drills: dict[str, DrillEntry] = {}
        self._next_id = 0

    def _registered_test_names(self) -> set[str]:
        # AD-477 QualificationHarness.registered_tests is a property returning
        # dict[str, QualificationTest].
        try:
            return set(self._harness.registered_tests.keys())
        except Exception:
            return set()

    def schedule_drill(
        self,
        agent_id: str,
        qualification_test: str,
        scheduled_at: float,
    ) -> str:
        """Schedule a drill. Returns drill_id.

        Raises KeyError if qualification_test is not registered with the
        QualificationHarness (W93-3 hard-stop).
        """
        registered = self._registered_test_names()
        if qualification_test not in registered:
            raise KeyError(
                f"AD-628d: qualification_test {qualification_test!r} not registered "
                f"with QualificationHarness; cannot schedule drill"
            )
        self._next_id += 1
        drill_id = f"drill-{self._next_id}"
        entry = DrillEntry(
            drill_id=drill_id,
            agent_id=agent_id,
            qualification_test=qualification_test,
            scheduled_at=scheduled_at,
            status="scheduled",
            result=None,
        )
        self._drills[drill_id] = entry
        return drill_id

    def list_due_drills(self, *, before: float) -> list[DrillEntry]:
        """List SCHEDULED drills with scheduled_at <= before."""
        return [
            e for e in self._drills.values()
            if e.status == "scheduled" and e.scheduled_at <= before
        ]

    async def execute_drill(self, drill_id: str) -> DrillEntry:
        """Execute the drill via QualificationHarness.run_test.

        AD-477 signature: run_test(agent_id, test_name, runtime). The
        qual_skill_bridge → SKILL_EXERCISED chain fires automatically.
        """
        entry = self._drills.get(drill_id)
        if entry is None:
            raise KeyError(f"AD-628d: unknown drill_id {drill_id!r}")
        result = await self._harness.run_test(
            entry.agent_id, entry.qualification_test, self._runtime,
        )
        updated = replace(entry, status="executed", result=result)
        self._drills[drill_id] = updated
        return updated

    def mark_missed(self, drill_id: str) -> DrillEntry:
        """Mark a drill as missed."""
        entry = self._drills.get(drill_id)
        if entry is None:
            raise KeyError(f"AD-628d: unknown drill_id {drill_id!r}")
        updated = replace(entry, status="missed")
        self._drills[drill_id] = updated
        return updated

    def get_drill(self, drill_id: str) -> DrillEntry | None:
        return self._drills.get(drill_id)

    def list_drills_for_agent(self, agent_id: str) -> list[DrillEntry]:
        return [e for e in self._drills.values() if e.agent_id == agent_id]
