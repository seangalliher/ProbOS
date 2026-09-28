"""AD-1137 (#1056): is this Python new enough for ProbOS?

pip already refuses to install ProbOS into an older interpreter
(``requires-python``); this check also names the interpreter doctor ran under,
which is the one ``probos`` runs under, so a wrong virtual environment is visible.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from probos.doctor.protocol import CheckOutcome, CheckResult, DoctorContext
from probos.doctor.registry import register_check

# pyproject.toml ``requires-python``; tests/test_ad1137_doctor.py pins the two together.
MINIMUM_PYTHON: tuple[int, int] = (3, 12)


def _running_version() -> tuple[int, ...]:
    return tuple(sys.version_info[:3])


@dataclass(frozen=True)
class _PythonCheck:
    name: str = "python"

    async def run(self, ctx: DoctorContext) -> CheckResult:
        version = _running_version()
        shown = ".".join(str(part) for part in version)
        minimum = ".".join(str(part) for part in MINIMUM_PYTHON)
        if version[:2] < MINIMUM_PYTHON:
            return CheckResult(
                outcome=CheckOutcome.FAIL,
                message=f"Python {shown} is older than ProbOS's minimum, {minimum}",
                remediation=(
                    f"Install Python {minimum} or newer, then reinstall ProbOS into a virtual "
                    "environment created with it."
                ),
            )
        return CheckResult(outcome=CheckOutcome.OK, message=f"Python {shown} ({sys.executable})")


register_check(_PythonCheck())
