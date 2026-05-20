"""AD-753 destructive-operation safeguards."""

from __future__ import annotations

import logging


logger = logging.getLogger(__name__)

DESTRUCTIVE_INTENTS: set[str] = {
    "write_file",
    "delete_file",
    "shell_command",
    "modify_config",
    "agent_self_modify",
}


class DestructiveOpsGuard:
    """Classifies destructive intents and emits audit-safe warnings."""

    async def check_and_log(self, intent: str) -> bool:
        """Return true when intent is destructive and requires explicit quorum."""
        if intent not in DESTRUCTIVE_INTENTS:
            return False

        logger.warning(
            "AD-753: destructive intent requested intent=%s; forcing explicit quorum path",
            intent,
        )
        return True
