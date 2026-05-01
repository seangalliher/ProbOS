"""AD-455: Red team lead - health-monitor coordinator over RedTeamAgent pool.

Periodically inventories the red team pool and reports availability.
Does NOT synthesize new probes - that is AD-455b's scope. v1 surfaces
operator visibility into red team readiness without polluting the
trust network.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from probos.events import EventType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CampaignReport:
    """One health-monitor cycle outcome."""

    started_at: float
    completed_at: float
    agents_total: int
    agents_alive: int
    consecutive_failures: int
    summary: str


class RedTeamLead:
    """Coordinates existing RedTeamAgents - health monitor only.

    `runtime.red_team_agents` is the public list populated by
    agent_fleet.spawn_red_team_fn (verified at agent_fleet.py:232).
    """

    MAX_CONSECUTIVE_FAILURES = 5

    def __init__(
        self,
        *,
        runtime: Any,
        emit_event: Any | None = None,
        campaign_interval_seconds: float = 3600.0,
    ) -> None:
        self._runtime = runtime
        self._emit_event = emit_event
        self._interval = campaign_interval_seconds
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()
        self._last_report: CampaignReport | None = None
        self._consecutive_failures = 0

    async def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._loop(), name="ad455-red-team-lead")

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                logger.debug("AD-455: red team lead task cancelled cleanly")
            self._task = None

    @property
    def last_report(self) -> CampaignReport | None:
        return self._last_report

    async def run_campaign_now(self) -> CampaignReport:
        return await self._run_campaign()

    async def _loop(self) -> None:
        try:
            while not self._stopping.is_set():
                try:
                    await self._run_campaign()
                    self._consecutive_failures = 0
                except Exception:
                    self._consecutive_failures += 1
                    logger.exception(
                        "AD-455: campaign run failed (%d/%d)",
                        self._consecutive_failures, self.MAX_CONSECUTIVE_FAILURES,
                    )
                    if self._consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
                        logger.error(
                            "AD-455: campaign disabled after %d consecutive failures; "
                            "operator must restart to resume",
                            self.MAX_CONSECUTIVE_FAILURES,
                        )
                        return
                try:
                    await asyncio.wait_for(self._stopping.wait(), timeout=self._interval)
                except asyncio.TimeoutError:
                    pass
        except asyncio.CancelledError:
            raise

    async def _run_campaign(self) -> CampaignReport:
        started = time.time()
        agents = list(getattr(self._runtime, "red_team_agents", []) or [])
        total = len(agents)
        alive = sum(1 for a in agents if getattr(a, "is_alive", True))
        completed = time.time()
        report = CampaignReport(
            started_at=started, completed_at=completed,
            agents_total=total, agents_alive=alive,
            consecutive_failures=self._consecutive_failures,
            summary=f"red_team_pool: {alive}/{total} alive",
        )
        self._last_report = report
        if self._emit_event:
            try:
                self._emit_event(
                    EventType.RED_TEAM_CAMPAIGN_COMPLETE,
                    {
                        "agents_total": total,
                        "agents_alive": alive,
                        "duration_seconds": completed - started,
                    },
                )
            except Exception:
                logger.warning("AD-455: campaign emit failed", exc_info=True)
        return report
