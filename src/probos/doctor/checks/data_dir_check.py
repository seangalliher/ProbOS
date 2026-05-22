"""AD-801: data_dir write probe (preserves AD-484 behavior)."""

from __future__ import annotations

from dataclasses import dataclass

from probos.doctor.protocol import CheckOutcome, CheckResult, DoctorContext
from probos.doctor.registry import register_check


@dataclass(frozen=True)
class _DataDirCheck:
    name: str = "data_dir"

    async def run(self, ctx: DoctorContext) -> CheckResult:
        try:
            ctx.data_dir.mkdir(parents=True, exist_ok=True)
            probe = ctx.data_dir / ".probos_doctor_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except Exception as exc:
            return CheckResult(
                outcome=CheckOutcome.FAIL,
                message=f"Data dir not writable: {ctx.data_dir}",
                remediation=f"Fix permissions or move data dir. ({type(exc).__name__}: {exc})",
            )
        return CheckResult(
            outcome=CheckOutcome.OK,
            message=f"Data dir writable: {ctx.data_dir}",
        )


register_check(_DataDirCheck())
