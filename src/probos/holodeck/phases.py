"""AD-486: Holodeck Birth Chamber phase enum + ordering."""

from __future__ import annotations

from enum import Enum


class HolodeckPhase(str, Enum):
    """Five birth-chamber phases plus GRADUATED sentinel.

    Distinct from AD-509 ``BootCampPhase`` (orientation/core_knowledge/
    a_school/calibration/integration). AD-486 phases mirror the spec at
    docs/development/roadmap.md:4130: orientation -> calibration ->
    self_discovery -> ship_records -> ward_room_integration -> graduated.
    """

    ORIENTATION = "orientation"
    CALIBRATION = "calibration"
    SELF_DISCOVERY = "self_discovery"
    SHIP_RECORDS = "ship_records"
    WARD_ROOM_INTEGRATION = "ward_room_integration"
    GRADUATED = "graduated"


PHASE_ORDER: tuple[HolodeckPhase, ...] = (
    HolodeckPhase.ORIENTATION,
    HolodeckPhase.CALIBRATION,
    HolodeckPhase.SELF_DISCOVERY,
    HolodeckPhase.SHIP_RECORDS,
    HolodeckPhase.WARD_ROOM_INTEGRATION,
    HolodeckPhase.GRADUATED,
)


def next_phase(current: HolodeckPhase) -> HolodeckPhase:
    """Return the phase after ``current``, or ``GRADUATED`` if at end."""
    try:
        idx = PHASE_ORDER.index(current)
    except ValueError:
        return current
    if idx >= len(PHASE_ORDER) - 1:
        return HolodeckPhase.GRADUATED
    return PHASE_ORDER[idx + 1]
