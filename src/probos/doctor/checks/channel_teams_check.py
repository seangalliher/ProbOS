"""AD-805: Microsoft Teams adapter doctor check."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from probos.doctor.protocol import CheckOutcome, CheckResult, DoctorContext
from probos.doctor.registry import register_check


@dataclass(frozen=True)
class _ChannelTeamsCheck:
    name: str = "channel_teams"

    async def run(self, ctx: DoctorContext) -> CheckResult:
        cfg_path = Path(ctx.home_dir) / "channels" / "teams.yaml"
        if not cfg_path.exists():
            return CheckResult(
                outcome=CheckOutcome.OK,
                message="Channel teams: not configured (opt-in)",
            )
        try:
            raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        except (yaml.YAMLError, OSError) as exc:
            return CheckResult(
                outcome=CheckOutcome.FAIL,
                message=f"Channel teams: config parse error ({exc})",
                remediation=f"Fix YAML at {cfg_path}",
            )
        if not raw.get("enabled", False):
            return CheckResult(
                outcome=CheckOutcome.OK,
                message="Channel teams: disabled in config",
            )
        app_id = raw.get("app_id") or ""
        app_password = raw.get("app_password") or ""
        if not app_id or not app_password:
            return CheckResult(
                outcome=CheckOutcome.FAIL,
                message="Channel teams: enabled but app_id/app_password missing",
                remediation=(
                    "Register a Bot Service in Azure Portal, then set "
                    "app_id + app_password (or env var "
                    "PROBOS_TEAMS_APP_PASSWORD) in teams.yaml"
                ),
            )
        allowed_teams = raw.get("allowed_team_ids", []) or []
        allowed_users = raw.get("allowed_user_aads", []) or []
        return CheckResult(
            outcome=CheckOutcome.OK,
            message=(
                f"Channel teams: enabled (app_id present, "
                f"{len(allowed_teams)} team allow-list, "
                f"{len(allowed_users)} user allow-list)"
            ),
        )


register_check(_ChannelTeamsCheck())
