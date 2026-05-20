"""Tests for AD-751: Desktop UX Surface."""

import pytest
from pathlib import Path
import tempfile

from probos.config import DesktopConfig
from probos.experience.desktop.tray import TrayManager
from probos.experience.desktop.hotkey import HotkeyListener
from probos.experience.desktop.lifecycle import DesktopLifecycle
from probos.experience.desktop.notifications import NotificationCenter


class TestTrayManager:
    """Test TrayManager (Section 1)."""

    def test_tray_manager_init(self) -> None:
        """Test TrayManager initialization."""
        config = DesktopConfig(enabled=True)
        manager = TrayManager(config)
        assert manager._status == "idle"
        assert manager._config == config

    def test_tray_manager_set_status(self) -> None:
        """Test TrayManager status updates."""
        config = DesktopConfig(enabled=True)
        manager = TrayManager(config)
        
        manager.set_status("running")
        assert manager._status == "running"
        
        manager.set_status("urgent")
        assert manager._status == "urgent"
        
        # Invalid status should not change current status
        manager.set_status("invalid")
        assert manager._status == "urgent"


class TestHotkeyListener:
    """Test HotkeyListener (Section 2)."""

    @pytest.mark.asyncio
    async def test_hotkey_listener_init(self) -> None:
        """Test HotkeyListener initialization."""
        listener = HotkeyListener()
        assert listener._listening is False
        assert listener._listener_task is None

    @pytest.mark.asyncio
    async def test_hotkey_listener_start_stop(self) -> None:
        """Test hotkey listener start/stop lifecycle."""
        listener = HotkeyListener()
        
        await listener.start_listening("ctrl+shift+space")
        assert listener._listening is True
        assert listener._listener_task is not None
        
        await listener.stop_listening()
        assert listener._listening is False


class TestDesktopLifecycle:
    """Test DesktopLifecycle (Section 3)."""

    @pytest.mark.asyncio
    async def test_lifecycle_lock_acquire_release(self) -> None:
        """Test single-instance lock acquisition and release."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = DesktopConfig(lock_file=str(Path(tmpdir) / "test.lock"))
            lifecycle = DesktopLifecycle(config)
            
            # Acquire lock
            acquired = await lifecycle.acquire_lock()
            assert acquired is True
            assert lifecycle.lock_file.exists()
            
            # Release lock
            await lifecycle.release_lock()
            assert not lifecycle.lock_file.exists()

    @pytest.mark.asyncio
    async def test_lifecycle_lock_duplicate_instance(self) -> None:
        """Test that lock prevents duplicate instance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = DesktopConfig(lock_file=str(Path(tmpdir) / "test.lock"))
            lifecycle1 = DesktopLifecycle(config)
            lifecycle2 = DesktopLifecycle(config)
            
            # First instance acquires lock
            acquired1 = await lifecycle1.acquire_lock()
            assert acquired1 is True
            
            # Second instance cannot acquire same lock
            acquired2 = await lifecycle2.acquire_lock()
            assert acquired2 is False
            
            # Cleanup
            await lifecycle1.release_lock()

    @pytest.mark.asyncio
    async def test_lifecycle_register_unregister_autostart(self) -> None:
        """Test autostart registration (platform-specific, graceful degrade)."""
        config = DesktopConfig(autostart_enabled=True)
        lifecycle = DesktopLifecycle(config)
        
        # Should not raise even if platform is unsupported
        await lifecycle.register_autostart()
        await lifecycle.unregister_autostart()


class TestNotificationCenter:
    """Test NotificationCenter (Section 4)."""

    @pytest.mark.asyncio
    async def test_notification_center_init(self) -> None:
        """Test NotificationCenter initialization."""
        center = NotificationCenter()
        assert center._config is None

    @pytest.mark.asyncio
    async def test_notification_with_action(self) -> None:
        """Test actionable notifications."""
        center = NotificationCenter()
        
        actions = [
            {"label": "Approve", "intent": "approve_build"},
            {"label": "Reject", "intent": "reject_build"},
        ]
        
        result = await center.notify_with_action(
            title="Build Ready",
            message="A new build is ready for approval",
            actions=actions,
        )
        
        # Result should be the first action label (placeholder implementation)
        assert result == "Approve"
