"""AD-764: Gmail adapter doctor check."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from probos.doctor.protocol import CheckOutcome, CheckResult, DoctorContext
from probos.doctor.registry import register_check


@dataclass(frozen=True)
class _ChannelGmailCheck:
    name: str = "channel_gmail"

    async def run(self, ctx: DoctorContext) -> CheckResult:
        cfg_path = Path(ctx.home_dir) / "channels" / "gmail.yaml"
        if not cfg_path.exists():
            return CheckResult(
                outcome=CheckOutcome.OK,
                message="Channel gmail: not configured (opt-in)",
            )
        try:
            raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        except (yaml.YAMLError, OSError) as exc:
            return CheckResult(
                outcome=CheckOutcome.FAIL,
                message=f"Channel gmail: config parse error ({exc})",
            )
        if not raw.get("enabled", False):
            return CheckResult(
                outcome=CheckOutcome.OK,
                message="Channel gmail: disabled in config",
            )
        address = raw.get("address", "")
        password = raw.get("app_password", "")
        if not address or not password:
            return CheckResult(
                outcome=CheckOutcome.FAIL,
                message="Channel gmail: enabled but address/app_password missing",
                remediation=(
                    "Generate an app password at "
                    "https://myaccount.google.com/apppasswords and set "
                    "address + app_password in gmail.yaml. Note: requires "
                    "2FA enabled on the Google account. Full OAuth flow is AD-764a."
                ),
            )
        senders = raw.get("allowed_senders", []) or []
        return CheckResult(
            outcome=CheckOutcome.OK,
            message=(
                f"Channel gmail: enabled (address={address}, "
                f"{len(senders)} sender allow-list)"
            ),
        )


register_check(_ChannelGmailCheck())
