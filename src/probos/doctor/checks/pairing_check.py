"""AD-802: pairing-store presence check.

Reports the number of active paired users so the Captain can see at a
glance whether the pairing substrate is wired and used.
"""

from __future__ import annotations

from dataclasses import dataclass

from probos.doctor.protocol import CheckOutcome, CheckResult, DoctorContext
from probos.doctor.registry import register_check


@dataclass(frozen=True)
class _PairingCheck:
    name: str = "pairing"

    async def run(self, ctx: DoctorContext) -> CheckResult:
        db_path = ctx.data_dir / "pairings.db"
        if not db_path.exists():
            return CheckResult(
                outcome=CheckOutcome.OK,
                message="Pairing: store not yet initialized (no channel adapters wired)",
            )
        try:
            from probos.security.pairing import PairingRegistry
            registry = PairingRegistry(db_path)
            active = registry.all_active_paired()
            pending = registry.list_pending()
        except Exception as exc:
            return CheckResult(
                outcome=CheckOutcome.WARN,
                message=f"Pairing store probe failed: {type(exc).__name__}",
                remediation=f"{exc}",
            )

        if not active and not pending:
            return CheckResult(
                outcome=CheckOutcome.OK,
                message="Pairing: 0 active, 0 pending",
            )
        return CheckResult(
            outcome=CheckOutcome.OK,
            message=f"Pairing: {len(active)} active, {len(pending)} pending",
        )


register_check(_PairingCheck())
