"""AD-751 Section 3: Autostart & Single-Instance Lock."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from probos.config import DesktopConfig

logger = logging.getLogger(__name__)


class DesktopLifecycle:
    """Manage desktop lifecycle: lock, autostart, shutdown."""

    def __init__(self, config: DesktopConfig) -> None:
        """Initialize DesktopLifecycle.
        
        Args:
            config: DesktopConfig instance.
        """
        self._config = config
        self.lock_file = Path(config.lock_file).expanduser()
        self._lock_file_handle: int | None = None
        logger.info("DesktopLifecycle initialized; lock_file=%s", self.lock_file)

    async def acquire_lock(self) -> bool:
        """Fail fast if already running (prevents duplicate instances).
        
        Returns:
            True if lock acquired, False if already locked.
        """
        # Ensure parent dir exists
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            # Attempt to create lock file exclusively (Windows/Unix portable)
            # Using os.open for cross-platform exclusive creation
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            self._lock_file_handle = os.open(str(self.lock_file), flags, 0o644)
            logger.info("Lock acquired: %s", self.lock_file)
            return True
        except FileExistsError:
            logger.warning("Lock file already exists; another instance may be running: %s", self.lock_file)
            return False
        except Exception as e:
            logger.error("Failed to acquire lock: %s", e)
            return False

    async def release_lock(self) -> None:
        """Release the lock file."""
        if self._lock_file_handle is not None:
            try:
                os.close(self._lock_file_handle)
                self._lock_file_handle = None
            except OSError as e:
                logger.error("Error closing lock file handle: %s", e)
        
        try:
            if self.lock_file.exists():
                self.lock_file.unlink()
                logger.info("Lock released: %s", self.lock_file)
        except OSError as e:
            logger.error("Failed to delete lock file: %s", e)

    async def register_autostart(self) -> None:
        """Platform-specific autostart registration:
        - Windows: Registry HKCU\\Run
        - macOS: LaunchAgent plist in ~/Library/LaunchAgents
        - Linux: .desktop file in ~/.config/autostart
        """
        import sys
        
        if not self._config.autostart_enabled:
            logger.debug("Autostart disabled in config")
            return
        
        if sys.platform == "win32":
            await self._register_autostart_windows()
        elif sys.platform == "darwin":
            await self._register_autostart_macos()
        elif sys.platform == "linux":
            await self._register_autostart_linux()
        else:
            logger.warning("Unsupported platform for autostart: %s", sys.platform)

    async def _register_autostart_windows(self) -> None:
        """Register autostart on Windows via registry."""
        try:
            import winreg
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, "ProbOS Yeo", 0, winreg.REG_SZ, "probos serve --interactive")
            logger.info("Autostart registered on Windows")
        except Exception as e:
            logger.error("Failed to register autostart on Windows: %s", e)

    async def _register_autostart_macos(self) -> None:
        """Register autostart on macOS via LaunchAgent."""
        agents_dir = Path.home() / "Library" / "LaunchAgents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        
        plist_path = agents_dir / "com.probos.yeo.plist"
        plist_content = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.probos.yeo</string>
    <key>ProgramArguments</key>
    <array>
        <string>probos</string>
        <string>serve</string>
        <string>--interactive</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
"""
        try:
            plist_path.write_text(plist_content)
            logger.info("Autostart plist registered on macOS: %s", plist_path)
        except Exception as e:
            logger.error("Failed to register autostart on macOS: %s", e)

    async def _register_autostart_linux(self) -> None:
        """Register autostart on Linux via .desktop file."""
        autostart_dir = Path.home() / ".config" / "autostart"
        autostart_dir.mkdir(parents=True, exist_ok=True)
        
        desktop_path = autostart_dir / "probos-yeo.desktop"
        desktop_content = """[Desktop Entry]
Type=Application
Name=ProbOS Yeo
Exec=probos serve --interactive
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
"""
        try:
            desktop_path.write_text(desktop_content)
            logger.info("Autostart .desktop file registered on Linux: %s", desktop_path)
        except Exception as e:
            logger.error("Failed to register autostart on Linux: %s", e)

    async def unregister_autostart(self) -> None:
        """Remove autostart registration."""
        import sys
        
        if sys.platform == "win32":
            await self._unregister_autostart_windows()
        elif sys.platform == "darwin":
            await self._unregister_autostart_macos()
        elif sys.platform == "linux":
            await self._unregister_autostart_linux()
        else:
            logger.warning("Unsupported platform for unregister_autostart: %s", sys.platform)

    async def _unregister_autostart_windows(self) -> None:
        """Unregister autostart on Windows."""
        try:
            import winreg
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, "ProbOS Yeo")
            logger.info("Autostart unregistered on Windows")
        except Exception as e:
            logger.error("Failed to unregister autostart on Windows: %s", e)

    async def _unregister_autostart_macos(self) -> None:
        """Unregister autostart on macOS."""
        plist_path = Path.home() / "Library" / "LaunchAgents" / "com.probos.yeo.plist"
        try:
            if plist_path.exists():
                plist_path.unlink()
            logger.info("Autostart plist removed on macOS")
        except Exception as e:
            logger.error("Failed to unregister autostart on macOS: %s", e)

    async def _unregister_autostart_linux(self) -> None:
        """Unregister autostart on Linux."""
        desktop_path = Path.home() / ".config" / "autostart" / "probos-yeo.desktop"
        try:
            if desktop_path.exists():
                desktop_path.unlink()
            logger.info("Autostart .desktop file removed on Linux")
        except Exception as e:
            logger.error("Failed to unregister autostart on Linux: %s", e)

    def _should_suppress_by_quiet_hours(self) -> bool:
        """Check if current time is within quiet hours.
        
        Returns:
            True if notifications should be suppressed.
        """
        from datetime import datetime
        now = datetime.now()
        # Placeholder implementation
        return False
