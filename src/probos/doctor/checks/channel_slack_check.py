"""AD-804: Slack channel-adapter health check.

OK when the operator hasn't configured Slack (token empty — opt-in).
OK with bot user_id when token validates via ``auth.test``.
FAIL when token is set but ``auth.test`` rejects it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from probos.channels.slack_client import SlackAPIError, SlackClient
from probos.doctor.protocol import CheckOutcome, CheckResult, DoctorContext
from probos.doctor.registry import register_check


def _config_path(home_dir: Path) -> Path:
    return home_dir / "channels" / "slack.yaml"


@dataclass(frozen=True)
class _ChannelSlackCheck:
    name: str = "channel_slack"

    async def run(self, ctx: DoctorContext) -> CheckResult:
        cfg_path = _config_path(ctx.home_dir)
        if not cfg_path.exists():
            return CheckResult(
                outcome=CheckOutcome.OK,
                message="Channel slack: not configured (opt-in)",
            )

        try:
            raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            return CheckResult(
                outcome=CheckOutcome.FAIL,
                message=f"Channel slack: config unparseable ({type(exc).__name__})",
                remediation=f"Fix {cfg_path} or re-run `probos channel slack setup`.",
            )

        if not raw.get("enabled", True):
            return CheckResult(
                outcome=CheckOutcome.OK,
                message="Channel slack: disabled in config",
            )

        token = raw.get("bot_token", "")
        if not token:
            return CheckResult(
                outcome=CheckOutcome.FAIL,
                message="Channel slack: config exists but bot_token is empty",
                remediation="Run `probos channel slack setup` to populate the token.",
            )

        client = SlackClient(
            bot_token=token,
            timeout=5.0,
            base=raw.get("api_base", "https://slack.com/api"),
        )
        try:
            identity = await client.auth_test()
        except SlackAPIError as exc:
            return CheckResult(
                outcome=CheckOutcome.FAIL,
                message=f"Channel slack: auth.test failed ({exc})",
                remediation="Token may be invalid, revoked, or the API unreachable. Re-run setup.",
            )
        finally:
            await client.close()

        user_id = identity.get("user_id") if isinstance(identity, dict) else None
        team = identity.get("team") if isinstance(identity, dict) else None
        return CheckResult(
            outcome=CheckOutcome.OK,
            message=f"Channel slack: connected as user_id={user_id} team={team}",
        )


register_check(_ChannelSlackCheck())
