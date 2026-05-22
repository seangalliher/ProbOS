"""AD-801: disk-space free check on the data dir."""

from __future__ import annotations

import shutil
from dataclasses import dataclass

from probos.doctor.protocol import CheckOutcome, CheckResult, DoctorContext
from probos.doctor.registry import register_check

# Thresholds chosen so a healthy laptop reports OK, a half-full SSD
# reports WARN, and a nearly-full disk reports FAIL well before the
# runtime starts hitting "no space left" errors.
_WARN_BYTES = 1 * 1024 * 1024 * 1024  # 1 GB
_FAIL_BYTES = 100 * 1024 * 1024       # 100 MB


def _format_gb(n: int) -> str:
    return f"{n / 1024 / 1024 / 1024:.1f} GB"


@dataclass(frozen=True)
class _DiskCheck:
    name: str = "disk"

    async def run(self, ctx: DoctorContext) -> CheckResult:
        try:
            usage = shutil.disk_usage(ctx.data_dir)
        except OSError as exc:
            return CheckResult(
                outcome=CheckOutcome.WARN,
                message=f"Disk usage probe failed: {type(exc).__name__}",
                remediation="Disk probably exists; the runtime can still boot. Check permissions if this persists.",
            )

        free = usage.free
        if free < _FAIL_BYTES:
            return CheckResult(
                outcome=CheckOutcome.FAIL,
                message=f"Data dir free space critically low: {_format_gb(free)}",
                remediation="Free at least a few hundred MB on the volume hosting the data dir.",
            )
        if free < _WARN_BYTES:
            return CheckResult(
                outcome=CheckOutcome.WARN,
                message=f"Data dir free space low: {_format_gb(free)}",
                remediation="Consider freeing space; large episodic stores and attachment caches can grow quickly.",
            )
        return CheckResult(
            outcome=CheckOutcome.OK,
            message=f"Data dir free space: {_format_gb(free)}",
        )


register_check(_DiskCheck())
