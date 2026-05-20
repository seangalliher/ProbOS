"""AD-751 Section 2: Global Hotkey & Mini-Mode."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from probos.config import DesktopConfig

logger = logging.getLogger(__name__)


class HotkeyListener:
    """Listen globally for hotkey press. Trigger mini-mode on activation."""

    def __init__(self, config: DesktopConfig | None = None) -> None:
        """Initialize HotkeyListener.
        
        Args:
            config: DesktopConfig instance (optional for testing).
        """
        self._config = config
        self._listening = False
        self._listener_task: asyncio.Task | None = None
        logger.info("HotkeyListener initialized")

    async def start_listening(self, hotkey: str = "ctrl+shift+space") -> None:
        """Listen globally for hotkey press. Trigger mini-mode on activation.
        
        Args:
            hotkey: Hotkey string (e.g., "ctrl+shift+space").
        """
        if self._listening:
            logger.debug("Hotkey listener already active")
            return
        
        self._listening = True
        logger.info("Starting hotkey listener for: %s", hotkey)
        
        # Store reference to the listener task
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("No running event loop; hotkey listening unavailable")
            self._listening = False
            return
        
        self._listener_task = loop.create_task(self._listen_loop(hotkey))

    async def on_hotkey_pressed(self) -> None:
        """Bring up mini-mode window or activate if already open."""
        logger.info("Hotkey pressed; would activate mini-mode window")

    async def _listen_loop(self, hotkey: str) -> None:
        """Internal listening loop."""
        try:
            while self._listening:
                # Placeholder: in real implementation, use pynput/keyboard library
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            logger.debug("Hotkey listener cancelled")
        finally:
            self._listener_task = None

    async def stop_listening(self) -> None:
        """Stop listening for hotkey."""
        if not self._listening:
            return
        
        self._listening = False
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
        logger.info("Hotkey listener stopped")
