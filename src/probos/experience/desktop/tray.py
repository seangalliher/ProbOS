"""AD-751 Section 1: Tray Icon & System Integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from probos.config import DesktopConfig

logger = logging.getLogger(__name__)


class TrayManager:
    """Initialize system tray with status indicators.
    
    Platform-specific:
    - Windows: pystray + pywin32 for DPAPI integration
    - macOS: rumps (py-applescript wrapper)
    - Linux: pystray + dbus for notifications
    """

    def __init__(self, config: DesktopConfig) -> None:
        """Initialize TrayManager with config.
        
        Args:
            config: DesktopConfig instance containing tray settings.
        """
        self._config = config
        self._status = "idle"
        logger.info("TrayManager initialized; tray_autostart=%s, hotkey=%s",
                    config.tray_autostart, config.hotkey)

    def set_status(self, status: str) -> None:
        """Update tray icon: 'idle' | 'running' | 'urgent'.
        
        Visual: amber icon (idle), pulsing (running), red (urgent).
        
        Args:
            status: One of 'idle', 'running', 'urgent'.
        """
        valid = {"idle", "running", "urgent"}
        if status not in valid:
            logger.warning("Invalid tray status %r; must be one of %s", status, valid)
            return
        
        self._status = status
        logger.debug("Tray status updated to %r", status)

    def show_notification(self, title: str, message: str, urgency: str = "normal") -> None:
        """Toast notification (win10toast / pyobjc / plyer platform-specific).
        
        Args:
            title: Notification title.
            message: Notification message.
            urgency: One of 'normal' or 'critical'.
        """
        if not self._config.enabled:
            logger.debug("Desktop tray disabled; notification suppressed: %s / %s", title, message)
            return
        
        # Check quiet hours
        if urgency == "normal" and self._should_suppress_by_quiet_hours():
            logger.debug("Notification suppressed by quiet hours: %s", title)
            return
        
        logger.info("Toast notification: [%s] %s", title, message)

    def _should_suppress_by_quiet_hours(self) -> bool:
        """Check if current time is within quiet hours.
        
        Returns:
            True if notifications should be suppressed.
        """
        from datetime import datetime, time
        
        now = datetime.now().time()
        start = time(*self._config.quiet_hours_start_tuple)
        end = time(*self._config.quiet_hours_end_tuple)
        
        if start <= end:
            return start <= now < end
        else:  # quiet hours wrap midnight
            return now >= start or now < end
