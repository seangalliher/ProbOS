"""AD-486: Phase-completion gate predicates.

Each gate is async because some predicates (calibration episodic count)
require database round-trips. Gates return ``(passed: bool, reason: str)``;
the chamber emits HOLODECK_PHASE_GATE_PASSED or
HOLODECK_PHASE_GATE_BLOCKED accordingly.

Trait-adaptive calibration pacing (AD-494) lives here: high-conscientiousness
agents (Medical) need longer calibration than low-conscientiousness agents
(Security). The multiplier is read via the callsign registry's
``get_profile(agent_type)`` lookup.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from probos.holodeck.chamber import BirthChamberRecord

logger = logging.getLogger(__name__)


def conscientiousness_multiplier(profile: dict[str, Any] | None) -> float:
    """Map a crew_profile dict to a calibration-min-episodes multiplier.

    AD-494 sea-trial evidence: high-conscientiousness agents (Medical) need
    longer calibration; low-conscientiousness (Security) shorter.
    """
    if not profile:
        return 1.0
    personality = profile.get("personality") if isinstance(profile, dict) else None
    if isinstance(personality, dict):
        c = float(personality.get("conscientiousness", 0.5))
    else:
        c = float(getattr(personality, "conscientiousness", 0.5)) if personality else 0.5
    if c >= 0.7:
        return 2.0
    if c <= 0.3:
        return 0.5
    return 1.0


async def gate_orientation_complete(
    record: "BirthChamberRecord",
    services: dict[str, Any],
) -> tuple[bool, str]:
    flags = record.gates_passed
    required = ("identity_grounded", "code_of_conduct_acknowledged",
                "curriculum_orientation_delivered")
    missing = [f for f in required if not flags.get(f, False)]
    if missing:
        return False, f"awaiting: {', '.join(missing)}"
    return True, "orientation acknowledged"


async def gate_calibration_baseline(
    record: "BirthChamberRecord",
    services: dict[str, Any],
) -> tuple[bool, str]:
    base = int(services.get("calibration_min_episodes", 5))
    profile = None
    callsign_registry = services.get("callsign_registry")
    if callsign_registry is not None:
        try:
            profile = callsign_registry.get_profile(record.agent_type)
        except Exception:
            logger.debug(
                "AD-486: callsign_registry.get_profile failed for %s",
                record.agent_type, exc_info=True,
            )
    multiplier = conscientiousness_multiplier(profile)
    effective = max(1, round(base * multiplier))
    episodic_memory = services.get("episodic_memory")
    if episodic_memory is None:
        return True, "no episodic memory; auto-pass"
    try:
        count = await episodic_memory.count_for_agent(record.agent_id)
    except Exception:
        logger.warning(
            "AD-486: episodic_memory.count_for_agent failed for %s; auto-pass",
            record.agent_id, exc_info=True,
        )
        return True, "episodic count unavailable; auto-pass"
    if count >= effective:
        return True, f"baseline established ({count} >= {effective})"
    return False, f"awaiting baseline ({count} / {effective})"


async def gate_self_discovery(
    record: "BirthChamberRecord",
    services: dict[str, Any],
) -> tuple[bool, str]:
    if record.gates_passed.get("self_distillation_probe_succeeded", False):
        return True, "self-distillation probe completed"
    return False, "awaiting self-distillation probe"


async def gate_ship_records(
    record: "BirthChamberRecord",
    services: dict[str, Any],
) -> tuple[bool, str]:
    if not record.gates_passed.get("ship_records_acknowledged", False):
        return False, "awaiting ship records acknowledgment"
    cb = services.get("circuit_breaker")
    if cb is not None:
        try:
            if not cb.should_allow_think(record.agent_id):
                return False, "circuit breaker open; deferring"
        except Exception:
            logger.debug(
                "AD-486: circuit_breaker.should_allow_think failed; ignoring",
                exc_info=True,
            )
    return True, "ship records acknowledged"


async def gate_ward_room_integration(
    record: "BirthChamberRecord",
    services: dict[str, Any],
) -> tuple[bool, str]:
    if record.gates_passed.get("integration_ready", False):
        return True, "integration ready"
    return False, "awaiting integration ready"
