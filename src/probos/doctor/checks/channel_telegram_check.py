"""AD-803a: Telegram channel-adapter health check.

OK when the operator hasn't configured Telegram (file absent — opt-in).
OK with bot username when token validates via `getMe`.
FAIL when config exists but the token is invalid or the API is unreachable.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from probos.channels.telegram_client import TelegramAPIError, TelegramClient
from probos.doctor.protocol import CheckOutcome, CheckResult, DoctorContext
from probos.doctor.registry import register_check


def _config_path(home_dir: Path) -> Path:
    return home_dir / "channels" / "telegram.yaml"


@dataclass(frozen=True)
class _ChannelTelegramCheck:
    name: str = "channel_telegram"

    async def run(self, ctx: DoctorContext) -> CheckResult:
        cfg_path = _config_path(ctx.home_dir)
        if not cfg_path.exists():
            return CheckResult(
                outcome=CheckOutcome.OK,
                message="Channel telegram: not configured (opt-in)",
            )

        try:
            raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            return CheckResult(
                outcome=CheckOutcome.FAIL,
                message=f"Channel telegram: config unparseable ({type(exc).__name__})",
                remediation=f"Fix {cfg_path} or re-run `probos channel telegram setup`.",
            )

        if not raw.get("enabled", True):
            return CheckResult(
                outcome=CheckOutcome.OK,
                message="Channel telegram: disabled in config",
            )

        token = raw.get("token", "")
        if not token:
            return CheckResult(
                outcome=CheckOutcome.FAIL,
                message="Channel telegram: config exists but token is empty",
                remediation="Run `probos channel telegram setup` to populate the token.",
            )

        # Verify via getMe with a short timeout — operators run doctor
        # under `probos doctor`, not a serve loop, so we don't want a
        # 30s hang on a flaky network.
        client = TelegramClient(
            token=token,
            timeout=5.0,
            base=raw.get("api_base", "https://api.telegram.org"),
        )
        try:
            me = await client.get_me()
        except TelegramAPIError as exc:
            return CheckResult(
                outcome=CheckOutcome.FAIL,
                message=f"Channel telegram: getMe failed ({exc})",
                remediation="Token may be invalid, revoked, or the API unreachable. Re-run setup.",
            )
        finally:
            await client.close()

        username = me.get("username") if isinstance(me, dict) else None
        return CheckResult(
            outcome=CheckOutcome.OK,
            message=f"Channel telegram: connected as @{username or '<unknown>'}",
        )


register_check(_ChannelTelegramCheck())
