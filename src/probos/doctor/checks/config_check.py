"""AD-801: config file presence + parseability check (preserves AD-484 behavior).

AD-1137: the file checked is the one ``probos`` and ``probos serve`` would load
(``--config``, else ``~/.probos/config.yaml``, else the checkout's
``config/system.yaml``); a missing file is named, and a file that does not load
says which setting or line is at fault.
"""

from __future__ import annotations

from dataclasses import dataclass

from probos.doctor.protocol import CheckOutcome, CheckResult, DoctorContext
from probos.doctor.registry import register_check


@dataclass(frozen=True)
class _ConfigCheck:
    name: str = "config"

    async def run(self, ctx: DoctorContext) -> CheckResult:
        if ctx.config_path is None:
            target = ctx.config_target
            where = str(target) if target is not None else "config.yaml"
            return CheckResult(
                outcome=CheckOutcome.FAIL,
                message=f"No config file at {where}: probos would start on built-in defaults",
                remediation="Run `probos setup` to configure a model provider, or pass --config PATH.",
            )
        if ctx.config is None:
            reason = ctx.config_error or "it did not load"
            return CheckResult(
                outcome=CheckOutcome.FAIL,
                message=f"Config {ctx.config_path} does not load: {reason}",
                remediation="Correct the setting or line named above, or restore the file from a backup.",
            )
        return CheckResult(
            outcome=CheckOutcome.OK,
            message=f"Config: {ctx.config_path}",
        )


register_check(_ConfigCheck())
