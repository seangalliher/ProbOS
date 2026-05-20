"""AD-751 Section 4: Actionable Notifications."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from probos.config import DesktopConfig

logger = logging.getLogger(__name__)


class NotificationCenter:
    """Display notifications with clickable action buttons."""

    def __init__(self, config: DesktopConfig | None = None) -> None:
        """Initialize NotificationCenter.
        
        Args:
            config: DesktopConfig instance (optional for testing).
        """
        self._config = config
        logger.info("NotificationCenter initialized")

    async def notify_with_action(
        self,
        title: str,
        message: str,
        actions: list[dict[str, str]] | None = None,
    ) -> str | None:
        """Show notification with clickable action buttons.
        
        Args:
            title: Notification title.
            message: Notification message.
            actions: List of action dicts with 'label' and 'intent' keys.
                     Example: [{"label": "Approve", "intent": "approve_build"}]
        
        Returns:
            The label of the action clicked, or None if dismissed.
        """
        if actions is None:
            actions = []
        
        action_str = ", ".join([f"{a.get('label', '?')}/{a.get('intent', '?')}" for a in actions])
        logger.info("Actionable notification: [%s] %s | Actions: %s", title, message, action_str or "(none)")
        
        # Placeholder: return first action for now
        return actions[0]["label"] if actions else None
