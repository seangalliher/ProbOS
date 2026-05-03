"""Naval Organization Protocols (AD-477).

v1 ships two daily-document services:

- ``CaptainsLogService`` — synthesizes daily narrative from episodic memory,
  Ward Room activity, and active work item summary.
- ``PlanOfDayService`` — auto-generates a morning operations summary from
  active work items, Ward Room thread queue, and current alert conditions.

Both services are read-only consumers of existing runtime surfaces; they emit
``CAPTAINS_LOG_GENERATED`` / ``PLAN_OF_DAY_GENERATED`` events when documents
are written to disk.

Deferred to grandchildren:

- AD-477b: Qualification Programs (extends AD-566 Crew Qualification Battery).
- AD-477c: 3M System (planned preventive maintenance).
- AD-477d: Damage Control Organization (5-phase protocol).
- AD-477e: SORM (Ship's Organization and Regulations Manual).
- AD-477f: Plan of the Day scheduled-duty integration (forcing function:
  public ``runtime.duty_schedule_tracker`` accessor or AD-500a-1's
  ``WorkItem(work_type="duty")`` query path ships).
- AD-477g: Captain's Log dream-consolidation source (forcing function:
  public ``runtime.dreaming_engine`` accessor or
  ``DreamScheduler.recent_consolidation_summaries(...)`` ships).
"""

from probos.naval.captains_log import CaptainsLogService
from probos.naval.plan_of_day import PlanOfDayService

__all__ = ["CaptainsLogService", "PlanOfDayService"]
