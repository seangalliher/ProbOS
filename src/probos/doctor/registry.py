"""AD-801: module-level check registry.

Idempotent registration so test setups can re-import safely. Duplicate
names raise — checks own their identifier and a name collision is a
real bug.
"""

from __future__ import annotations

import logging
from typing import Iterator

from probos.doctor.protocol import DoctorCheck

logger = logging.getLogger(__name__)

_CHECKS: list[DoctorCheck] = []
_NAMES: set[str] = set()


def register_check(check: DoctorCheck) -> None:
    """Append `check` to the registry. Raises if `check.name` is already
    registered — name collisions indicate a real bug, not a re-import.
    """
    name = check.name
    if name in _NAMES:
        raise ValueError(
            f"AD-801: doctor check '{name}' already registered; "
            "duplicate names are not allowed",
        )
    _CHECKS.append(check)
    _NAMES.add(name)
    logger.debug("AD-801: registered doctor check '%s'", name)


def iter_checks() -> Iterator[DoctorCheck]:
    """Yield registered checks in registration order."""
    yield from _CHECKS


def _reset_for_tests() -> None:
    """Test-only: clear the registry. Public API does NOT use this.

    Called from pytest fixtures that want to assert against a fresh
    registry; never call from production code.
    """
    _CHECKS.clear()
    _NAMES.clear()
