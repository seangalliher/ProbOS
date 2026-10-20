"""BF-908 (#1605): where the crew-scope token comes from, and whether a config file still holds it.

Names the file and the setting, never the value. WARN while ``auth.crew_scope_token``
is set in the config file (any process running as the Captain's user can read it);
FAIL when a secure OS keyring cannot be read and the file sets no token, because the
vessel would then refuse every caller on every route that needs the token.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from probos.doctor.protocol import CheckOutcome, CheckResult, DoctorContext
from probos.doctor.registry import register_check
from probos.security.crew_scope import (
    configured_crew_scope_token,
    crew_scope_posture,
    read_keyring_token_bounded,
)

_OUTCOMES = {"ok": CheckOutcome.OK, "warning": CheckOutcome.WARN, "error": CheckOutcome.FAIL}


@dataclass(frozen=True)
class _CrewScopeCheck:
    name: str = "crew_scope_token"
    backend: Any = None  # BF-908: tests inject an in-memory keyring; None reads the OS keyring

    async def run(self, ctx: DoctorContext) -> CheckResult:
        if ctx.config is None:
            return CheckResult(outcome=CheckOutcome.WARN, message="crew-scope token: skipped (config unavailable)")
        read = await read_keyring_token_bounded(self.backend)
        where = ctx.config_path if ctx.config_path is not None else ctx.config_target
        posture = crew_scope_posture(
            read, config_holds_token=bool(configured_crew_scope_token(ctx.config)),
            config_file=str(where) if where is not None else "the config file",
        )
        return CheckResult(outcome=_OUTCOMES[posture.severity], message=posture.message, remediation=posture.remediation)


register_check(_CrewScopeCheck())
