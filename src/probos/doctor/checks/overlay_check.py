"""AD-801: overlay extension status report (AD-697)."""

from __future__ import annotations

from dataclasses import dataclass

from probos.doctor.protocol import CheckOutcome, CheckResult, DoctorContext
from probos.doctor.registry import register_check


@dataclass(frozen=True)
class _OverlayCheck:
    name: str = "overlay"

    async def run(self, ctx: DoctorContext) -> CheckResult:
        # Discovery is idempotent — calling it here from `probos doctor`
        # has the same effect as the runtime boot path.
        try:
            from probos.extensions.overlay import (
                discover_extensions,
                is_commercial_loaded,
                loaded_providers,
            )
            discover_extensions()
            providers = list(loaded_providers())
            commercial = is_commercial_loaded()
        except Exception as exc:
            return CheckResult(
                outcome=CheckOutcome.WARN,
                message=f"Overlay discovery failed: {type(exc).__name__}",
                remediation=f"{exc}",
            )

        if not providers:
            return CheckResult(
                outcome=CheckOutcome.OK,
                message="Overlay: OSS-only mode (no extension packages loaded)",
            )

        flag = " (commercial)" if commercial else ""
        return CheckResult(
            outcome=CheckOutcome.OK,
            message=f"Overlay providers loaded: {', '.join(providers)}{flag}",
        )


register_check(_OverlayCheck())
