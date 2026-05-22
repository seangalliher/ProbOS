"""AD-801: config file presence + parseability check (preserves AD-484 behavior)."""

from __future__ import annotations

from dataclasses import dataclass

from probos.doctor.protocol import CheckOutcome, CheckResult, DoctorContext
from probos.doctor.registry import register_check


@dataclass(frozen=True)
class _ConfigCheck:
    name: str = "config"

    async def run(self, ctx: DoctorContext) -> CheckResult:
        if ctx.config_path is None:
            return CheckResult(
                outcome=CheckOutcome.FAIL,
                message="config.yaml not found",
                remediation="Run `probos init` to create one.",
            )
        if ctx.config is None:
            return CheckResult(
                outcome=CheckOutcome.FAIL,
                message=f"config.yaml at {ctx.config_path} failed to parse",
                remediation="Check the file for schema errors; restore from backup if needed.",
            )
        return CheckResult(
            outcome=CheckOutcome.OK,
            message=f"Config: {ctx.config_path}",
        )


register_check(_ConfigCheck())
