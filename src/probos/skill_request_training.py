"""ProbOS — Skill-request holodeck-training completion wiring (AD-907).

Completion-side half of the AD-906 skill-request training loop. Listens for
``EventType.TEAM_SIMULATION_COMPLETED`` and advances the in-training skill
request linked to that simulation to ``completed``, recording the simulation's
outcome score as the request's ``post_metric``.

Scope note (FLAG-907): only the completion side is wired here. Auto-starting a
team simulation on approval is deferred — there is no single-agent drill
scenario primitive yet, and the §6.3 auto-approve threshold is unconfirmed.
The Captain links an approved request to a simulation explicitly via the
AD-908 ``begin-training`` endpoint until that primitive exists.

Honest-degrade (Tier-2): a missing store, a malformed event, or a failing
store call logs and returns without raising so a missing/disabled training
substrate never blocks simulation completion.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def on_team_simulation_completed(runtime: Any, event: Any) -> None:
    """Advance the skill request linked to a finished team simulation (AD-907).

    The runtime delivers events as plain dicts shaped
    ``{"type": ..., "data": {...}, "timestamp": ...}`` (matches
    ``CapabilityGapDriver.on_capability_event``); the TEAM_SIMULATION_COMPLETED
    payload carries ``simulation_id`` and ``outcome_score``. Resolves the
    in-training request via ``complete_for_simulation`` — a no-op when nothing
    is linked.
    """
    store = getattr(runtime, "skill_request_store", None)
    if store is None:
        # Cluster disabled or store absent — nothing to advance.
        return
    data = event.get("data", {}) if isinstance(event, dict) else {}
    simulation_id = data.get("simulation_id")
    if not simulation_id:
        logger.warning(
            "AD-907: team-simulation-completed event carries no simulation_id; "
            "skill-request completion skipped"
        )
        return
    score = data.get("outcome_score")
    try:
        await store.complete_for_simulation(simulation_id, score=score)
    except Exception:
        logger.warning(
            "AD-907: complete_for_simulation failed for %s; degrading",
            str(simulation_id)[:12], exc_info=True,
        )
