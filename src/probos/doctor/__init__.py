"""AD-801: pluggable health-check registry for `probos doctor`.

The original `_cmd_doctor` (AD-484) was an inline function with six hard-coded
checks. AD-801 refactors that into a registry pattern so future ADs
(AD-798 ContainerSandbox, AD-803..807 channel adapters, AD-808 migration)
can plug their own checks in without editing `__main__.py`.

Public surface:
    - `CheckOutcome`, `CheckResult`, `DoctorCheck`, `DoctorContext` (protocol.py)
    - `register_check`, `iter_checks` (registry.py)
    - `run_doctor(args, console) -> int` (runner.py)
"""

from probos.doctor.protocol import (
    CheckOutcome,
    CheckResult,
    DoctorCheck,
    DoctorContext,
)
from probos.doctor.registry import iter_checks, register_check
from probos.doctor.runner import run_doctor

# Importing the built-in checks runs their `register_check` side effects.
from probos.doctor import checks as _builtin_checks  # noqa: F401

__all__ = [
    "CheckOutcome",
    "CheckResult",
    "DoctorCheck",
    "DoctorContext",
    "iter_checks",
    "register_check",
    "run_doctor",
]
