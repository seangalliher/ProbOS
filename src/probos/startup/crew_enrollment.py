"""BF-906 (#1594): the Phase 7 crew enrollment pass and the startup crew invariant check."""

from __future__ import annotations

import logging
from typing import Any

from probos.crew_enrollment import (
    CrewEnrollmentService,
    CrewInvariantReport,
    check_crew_invariant,
    log_crew_invariant_failure,
)

logger = logging.getLogger(__name__)


async def enroll_boot_crew(*, runtime: Any, boot_started_at: float) -> CrewEnrollmentService | None:
    """Enroll every agent wired so far, then route every later wiring through the enroller."""
    if runtime.acm is None:
        logger.error(
            "BF-906: ACM is unavailable; no crew member is onboarded or commissioned "
            "this boot, and the crew invariant check reports them",
        )
        return None
    service = CrewEnrollmentService(
        acm=runtime.acm,
        ontology=runtime.ontology,
        skill_service=runtime.skill_service,
        identity_registry=runtime.identity_registry,
        event_log=runtime.event_log,
        commission_context=runtime,
        boot_started_at=boot_started_at,
    )
    try:
        await service.enroll_wired_crew(runtime.registry.all())
    except Exception:
        logger.error("BF-906: the crew enrollment pass failed; the invariant check reports who is missing", exc_info=True)
    runtime.onboarding.set_crew_enroller(service.enroll_joining)
    return service


async def report_crew_invariant(*, runtime: Any) -> CrewInvariantReport | None:
    """Report any crew agent without a lifecycle row or a commissioning, never silently."""
    try:
        report = await check_crew_invariant(
            acm=runtime.acm, skill_service=runtime.skill_service,
            ontology=runtime.ontology, agents=runtime.registry.all(),
        )
    except Exception:
        logger.error("BF-906: the crew invariant could not be evaluated", exc_info=True)
        return None
    if report.ok:
        logger.info("BF-906: crew invariant holds for %d crew agents", report.checked)
        return report
    logger.error(
        "BF-906: crew invariant FAILED (%d crew checked): no ACM lifecycle record: %s; "
        "never commissioned: %s",
        report.checked,
        ", ".join(report.missing_lifecycle) or "none",
        ", ".join(report.never_commissioned) or "none",
    )
    await log_crew_invariant_failure(runtime.event_log, report)
    return report
