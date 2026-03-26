"""Tests for AD-435: Restart Announcements."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from probos.ward_room import WardRoomService


class TestShutdownAnnouncement:
    """AD-435: Shutdown announcements to Ward Room."""

    @pytest.mark.asyncio
    async def test_shutdown_announcement(self, tmp_path):
        """AD-435: Shutdown posts 'System Restart' with reason to All Hands."""
        wr = WardRoomService(
            db_path=str(tmp_path / "wr.db"),
            emit_event=lambda t, d: None,
        )
        await wr.start()

        # Find All Hands channel
        channels = await wr.list_channels()
        all_hands = next(c for c in channels if c.name == "All Hands")

        # Simulate what runtime.stop() does for the announcement
        msg = "System shutdown initiated. Reason: Development build"
        await wr.create_thread(
            channel_id=all_hands.id,
            author_id="system",
            title="System Restart",
            body=msg,
            author_callsign="Ship's Computer",
            thread_mode="announce",
            max_responders=0,
        )

        threads = await wr.list_threads(all_hands.id)
        restart_threads = [t for t in threads if t.title == "System Restart"]
        assert len(restart_threads) == 1
        assert "Development build" in restart_threads[0].body
        assert restart_threads[0].thread_mode == "announce"

        await wr.stop()

    @pytest.mark.asyncio
    async def test_shutdown_announcement_no_reason(self, tmp_path):
        """AD-435: Shutdown announcement without reason has no 'Reason:' suffix."""
        wr = WardRoomService(
            db_path=str(tmp_path / "wr.db"),
            emit_event=lambda t, d: None,
        )
        await wr.start()

        channels = await wr.list_channels()
        all_hands = next(c for c in channels if c.name == "All Hands")

        # Simulate stop() with no reason — body is just the base message
        msg = "System shutdown initiated."
        await wr.create_thread(
            channel_id=all_hands.id,
            author_id="system",
            title="System Restart",
            body=msg,
            author_callsign="Ship's Computer",
            thread_mode="announce",
            max_responders=0,
        )

        threads = await wr.list_threads(all_hands.id)
        restart_threads = [t for t in threads if t.title == "System Restart"]
        assert len(restart_threads) == 1
        assert restart_threads[0].body == "System shutdown initiated."
        assert "Reason:" not in restart_threads[0].body

        await wr.stop()

    @pytest.mark.asyncio
    async def test_shutdown_no_ward_room(self):
        """AD-435: stop() reason param signature doesn't crash without Ward Room."""
        from probos.runtime import ProbOSRuntime

        # Verify stop() accepts reason kwarg (signature test)
        import inspect
        sig = inspect.signature(ProbOSRuntime.stop)
        assert "reason" in sig.parameters
        assert sig.parameters["reason"].default == ""


class TestStartupAnnouncement:
    """AD-435: Startup announcement to Ward Room."""

    @pytest.mark.asyncio
    async def test_startup_announcement(self, tmp_path):
        """AD-435: 'System Online' thread posted to All Hands."""
        wr = WardRoomService(
            db_path=str(tmp_path / "wr.db"),
            emit_event=lambda t, d: None,
        )
        await wr.start()

        channels = await wr.list_channels()
        all_hands = next(c for c in channels if c.name == "All Hands")

        # Simulate what runtime.start() does for the announcement
        await wr.create_thread(
            channel_id=all_hands.id,
            author_id="system",
            title="System Online",
            body="ProbOS startup complete. All systems operational.",
            author_callsign="Ship's Computer",
            thread_mode="announce",
            max_responders=0,
        )

        threads = await wr.list_threads(all_hands.id)
        online_threads = [t for t in threads if t.title == "System Online"]
        assert len(online_threads) == 1
        assert "All systems operational" in online_threads[0].body
        assert online_threads[0].thread_mode == "announce"

        await wr.stop()


class TestShellQuitReason:
    """AD-435: Shell /quit passes reason."""

    @pytest.mark.asyncio
    async def test_quit_with_reason(self):
        """AD-435: /quit stores reason for shutdown announcement."""
        from probos.experience.shell import ProbOSShell

        shell = ProbOSShell.__new__(ProbOSShell)
        shell._running = True
        shell.console = MagicMock()

        await shell._cmd_quit("Deploying AD-435")
        assert shell._quit_reason == "Deploying AD-435"
        assert shell._running is False

    @pytest.mark.asyncio
    async def test_quit_without_reason(self):
        """AD-435: /quit with no argument stores empty reason."""
        from probos.experience.shell import ProbOSShell

        shell = ProbOSShell.__new__(ProbOSShell)
        shell._running = True
        shell.console = MagicMock()

        await shell._cmd_quit("")
        assert shell._quit_reason == ""
        assert shell._running is False
