"""AD-807: Discord channel-adapter health check.

OK when the operator hasn't configured Discord (no token).
OK with token-present indication when config is set up (no live API
call — discord.py opens a websocket on start that's too heavy for
``probos doctor``; we just verify config sanity).
"""

from __future__ import annotations

from dataclasses import dataclass

from probos.doctor.protocol import CheckOutcome, CheckResult, DoctorContext
from probos.doctor.registry import register_check


@dataclass(frozen=True)
class _ChannelDiscordCheck:
    name: str = "channel_discord"

    async def run(self, ctx: DoctorContext) -> CheckResult:
        if ctx.config is None:
            return CheckResult(
                outcome=CheckOutcome.OK,
                message="Channel discord: skipped (config unavailable)",
            )
        channels_cfg = getattr(ctx.config, "channels", None)
        discord_cfg = getattr(channels_cfg, "discord", None) if channels_cfg else None
        if discord_cfg is None:
            return CheckResult(
                outcome=CheckOutcome.OK,
                message="Channel discord: not configured (opt-in)",
            )

        if not getattr(discord_cfg, "enabled", False):
            return CheckResult(
                outcome=CheckOutcome.OK,
                message="Channel discord: disabled in config",
            )

        token = getattr(discord_cfg, "token", "")
        if not token:
            return CheckResult(
                outcome=CheckOutcome.FAIL,
                message="Channel discord: enabled but token is empty",
                remediation="Set channels.discord.token (or PROBOS_DISCORD_TOKEN env var).",
            )

        # Don't open a Discord websocket from doctor — too heavy for a
        # synchronous health check. Just report token presence + filters.
        allowed_channels = getattr(discord_cfg, "allowed_channel_ids", []) or []
        allowed_users = getattr(discord_cfg, "allowed_user_ids", []) or []
        return CheckResult(
            outcome=CheckOutcome.OK,
            message=(
                f"Channel discord: enabled (token present, "
                f"{len(allowed_channels)} channel allow-list, "
                f"{len(allowed_users)} user allow-list)"
            ),
        )


register_check(_ChannelDiscordCheck())
