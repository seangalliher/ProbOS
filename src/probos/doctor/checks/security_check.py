"""AD-801: AD-711 security profile sanity (preserves AD-484 behavior)."""

from __future__ import annotations

from dataclasses import dataclass

from probos.doctor.protocol import CheckOutcome, CheckResult, DoctorContext
from probos.doctor.registry import register_check


@dataclass(frozen=True)
class _SecurityCheck:
    name: str = "security"

    async def run(self, ctx: DoctorContext) -> CheckResult:
        if ctx.config is None:
            return CheckResult(
                outcome=CheckOutcome.WARN,
                message="security: skipped (config unavailable)",
            )

        sec = getattr(ctx.config, "security", None)
        if sec is None:
            return CheckResult(
                outcome=CheckOutcome.FAIL,
                message="security: section missing from config.yaml",
                remediation="Re-run `probos init --force --security-profile strict` to regenerate.",
            )

        profile = getattr(sec, "profile", "")
        perms = getattr(sec, "permissions", None)
        deny = list(getattr(perms, "deny", []) or [])

        if not deny:
            return CheckResult(
                outcome=CheckOutcome.FAIL,
                message="security.permissions.deny is empty",
                remediation="At minimum deny `shell:rm -rf` and `fs:write:.env` per AD-711 defaults.",
            )
        if profile != "strict":
            return CheckResult(
                outcome=CheckOutcome.WARN,
                message=f"security.profile is '{profile}' (not 'strict')",
                remediation="Review your security profile if running multi-user or remote-reachable.",
            )
        return CheckResult(
            outcome=CheckOutcome.OK,
            message=f"Security profile: {profile} ({len(deny)} deny rules)",
        )


register_check(_SecurityCheck())
