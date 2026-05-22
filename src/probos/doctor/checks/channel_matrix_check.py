"""AD-806: Matrix channel-adapter health check.

OK when not configured (opt-in).
OK with bot user_id when access_token validates via /account/whoami.
FAIL when token is set but whoami rejects it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from probos.channels.matrix_client import MatrixAPIError, MatrixClient
from probos.doctor.protocol import CheckOutcome, CheckResult, DoctorContext
from probos.doctor.registry import register_check


def _config_path(home_dir: Path) -> Path:
    return home_dir / "channels" / "matrix.yaml"


@dataclass(frozen=True)
class _ChannelMatrixCheck:
    name: str = "channel_matrix"

    async def run(self, ctx: DoctorContext) -> CheckResult:
        cfg_path = _config_path(ctx.home_dir)
        if not cfg_path.exists():
            return CheckResult(
                outcome=CheckOutcome.OK,
                message="Channel matrix: not configured (opt-in)",
            )

        try:
            raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            return CheckResult(
                outcome=CheckOutcome.FAIL,
                message=f"Channel matrix: config unparseable ({type(exc).__name__})",
                remediation=f"Fix {cfg_path} or re-run `probos channel matrix setup`.",
            )

        if not raw.get("enabled", True):
            return CheckResult(
                outcome=CheckOutcome.OK,
                message="Channel matrix: disabled in config",
            )

        token = raw.get("access_token", "")
        homeserver = raw.get("homeserver", "")
        if not token or not homeserver:
            return CheckResult(
                outcome=CheckOutcome.FAIL,
                message="Channel matrix: config exists but access_token or homeserver is empty",
                remediation="Run `probos channel matrix setup` to populate credentials.",
            )

        client = MatrixClient(
            homeserver=homeserver,
            access_token=token,
            timeout=5.0,
        )
        try:
            user_id = await client.whoami()
        except MatrixAPIError as exc:
            return CheckResult(
                outcome=CheckOutcome.FAIL,
                message=f"Channel matrix: whoami failed ({exc})",
                remediation="Access token may be revoked or homeserver unreachable. Re-run setup.",
            )
        finally:
            await client.close()

        return CheckResult(
            outcome=CheckOutcome.OK,
            message=f"Channel matrix: connected as {user_id} on {homeserver}",
        )


register_check(_ChannelMatrixCheck())
