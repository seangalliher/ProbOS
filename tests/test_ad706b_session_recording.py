"""AD-706b (Wave 166) - Browser session video recording + retention reaper tests."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.config import BrowserToolConfig
from probos.events import EventType
from probos.tools.browser.recording_reaper import RecordingReaper
from probos.tools.browser.session import BrowserSession


# ---------------------------------------------------------------------------
# Section 2: BrowserSession recording lifecycle
# ---------------------------------------------------------------------------


class _FakeContext:
    def __init__(self, raise_on_close: bool = False) -> None:
        self.closed = False
        self._raise = raise_on_close

    async def new_page(self) -> Any:
        page = MagicMock()
        page.set_default_timeout = MagicMock()
        return page

    async def close(self) -> None:
        self.closed = True
        if self._raise:
            raise RuntimeError("ad706b-test: simulated finalize error")


class _FakeBrowser:
    def __init__(self, raise_on_close: bool = False) -> None:
        self.new_context_kwargs: dict[str, Any] | None = None
        self._raise = raise_on_close

    async def new_context(self, **kwargs: Any) -> _FakeContext:
        self.new_context_kwargs = kwargs
        return _FakeContext(raise_on_close=self._raise)

    async def close(self) -> None:
        pass


class _FakeChromium:
    def __init__(self, browser: _FakeBrowser) -> None:
        self._browser = browser

    async def launch(self, **kwargs: Any) -> _FakeBrowser:
        return self._browser


class _FakePlaywright:
    def __init__(self, browser: _FakeBrowser) -> None:
        self.chromium = _FakeChromium(browser)

    async def stop(self) -> None:
        pass


class _FakePlaywrightFactory:
    def __init__(self, browser: _FakeBrowser) -> None:
        self._pw = _FakePlaywright(browser)

    async def start(self) -> _FakePlaywright:
        return self._pw


def _install_fake_playwright(
    monkeypatch: pytest.MonkeyPatch, browser: _FakeBrowser
) -> None:
    """Patch the lazy ``from playwright.async_api import async_playwright`` import."""
    import sys
    import types

    fake_mod = types.ModuleType("playwright.async_api")
    fake_mod.async_playwright = lambda: _FakePlaywrightFactory(browser)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.async_api", fake_mod)


@pytest.mark.asyncio
async def test_recording_disabled_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfg = BrowserToolConfig(enabled=True, recording_dir=str(tmp_path))
    assert cfg.recording_enabled is False
    browser = _FakeBrowser()
    _install_fake_playwright(monkeypatch, browser)
    sess = BrowserSession(session_id="s1", agent_id="a1", config=cfg)
    await sess.start()
    assert browser.new_context_kwargs == {}
    await sess.stop()


@pytest.mark.asyncio
async def test_recording_enabled_passes_record_video_dir_to_context(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfg = BrowserToolConfig(
        enabled=True, recording_enabled=True, recording_dir=str(tmp_path)
    )
    browser = _FakeBrowser()
    _install_fake_playwright(monkeypatch, browser)
    sess = BrowserSession(session_id="s1", agent_id="a1", config=cfg)
    await sess.start()
    assert browser.new_context_kwargs is not None
    assert browser.new_context_kwargs.get("record_video_dir") == str(tmp_path / "s1")
    assert (tmp_path / "s1").is_dir()
    await sess.stop()


@pytest.mark.asyncio
async def test_recording_emits_started_and_stopped_events(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    events: list[tuple[Any, dict]] = []
    cfg = BrowserToolConfig(
        enabled=True, recording_enabled=True, recording_dir=str(tmp_path)
    )
    browser = _FakeBrowser()
    _install_fake_playwright(monkeypatch, browser)
    sess = BrowserSession(
        session_id="s1",
        agent_id="a1",
        config=cfg,
        emit_event=lambda et, p: events.append((et, p)),
    )
    await sess.start()
    await sess.stop()
    event_types = [et for et, _ in events]
    assert EventType.BROWSER_RECORDING_STARTED in event_types
    assert EventType.BROWSER_RECORDING_STOPPED in event_types


@pytest.mark.asyncio
async def test_session_stop_emits_failed_event_when_close_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    events: list[tuple[Any, dict]] = []
    cfg = BrowserToolConfig(
        enabled=True, recording_enabled=True, recording_dir=str(tmp_path)
    )
    browser = _FakeBrowser(raise_on_close=True)
    _install_fake_playwright(monkeypatch, browser)
    sess = BrowserSession(
        session_id="s1",
        agent_id="a1",
        config=cfg,
        emit_event=lambda et, p: events.append((et, p)),
    )
    await sess.start()
    # Should NOT raise - Tier-2 log-and-degrade.
    await sess.stop()
    event_types = [et for et, _ in events]
    assert EventType.BROWSER_RECORDING_FAILED in event_types


# ---------------------------------------------------------------------------
# Section 3: RecordingReaper
# ---------------------------------------------------------------------------


def _make_recording(root: Path, session_id: str, name: str, mtime_ago_seconds: float) -> Path:
    subdir = root / session_id
    subdir.mkdir(parents=True, exist_ok=True)
    f = subdir / name
    f.write_bytes(b"x" * 1024)
    past = time.time() - mtime_ago_seconds
    os.utime(f, (past, past))
    return f


@pytest.mark.asyncio
async def test_reaper_deletes_files_older_than_retention(tmp_path: Path) -> None:
    cfg = BrowserToolConfig(
        enabled=True,
        recording_enabled=True,
        recording_dir=str(tmp_path),
        recording_retention_days=1,
    )
    f = _make_recording(tmp_path, "s1", "old.webm", mtime_ago_seconds=2 * 86400)
    reaper = RecordingReaper(cfg=cfg)
    deleted = await reaper.reap_once()
    assert deleted == 1
    assert not f.exists()


@pytest.mark.asyncio
async def test_reaper_preserves_files_within_retention(tmp_path: Path) -> None:
    cfg = BrowserToolConfig(
        enabled=True,
        recording_enabled=True,
        recording_dir=str(tmp_path),
        recording_retention_days=7,
    )
    f = _make_recording(tmp_path, "s1", "fresh.webm", mtime_ago_seconds=60)
    reaper = RecordingReaper(cfg=cfg)
    deleted = await reaper.reap_once()
    assert deleted == 0
    assert f.exists()


@pytest.mark.asyncio
async def test_reaper_enforces_per_session_size_cap(tmp_path: Path) -> None:
    cfg = BrowserToolConfig(
        enabled=True,
        recording_enabled=True,
        recording_dir=str(tmp_path),
        recording_retention_days=365,
        recording_max_size_mb_per_session=10,
    )
    # Three 4-MB files (12 MB total) in the same session - oldest must be reaped.
    subdir = tmp_path / "s1"
    subdir.mkdir(parents=True)
    sizes: list[Path] = []
    for i, age in enumerate([300, 200, 100]):
        f = subdir / f"r{i}.webm"
        f.write_bytes(b"y" * 4 * 1024 * 1024)
        past = time.time() - age
        os.utime(f, (past, past))
        sizes.append(f)
    reaper = RecordingReaper(cfg=cfg)
    deleted = await reaper.reap_once()
    assert deleted >= 1
    # Oldest (r0) must have been deleted first.
    assert not sizes[0].exists()
    # Newest must survive.
    assert sizes[2].exists()


@pytest.mark.asyncio
async def test_reaper_removes_empty_session_directory_after_cleanup(
    tmp_path: Path,
) -> None:
    cfg = BrowserToolConfig(
        enabled=True,
        recording_enabled=True,
        recording_dir=str(tmp_path),
        recording_retention_days=1,
    )
    _make_recording(tmp_path, "s1", "old.webm", mtime_ago_seconds=2 * 86400)
    reaper = RecordingReaper(cfg=cfg)
    await reaper.reap_once()
    assert not (tmp_path / "s1").exists()


# ---------------------------------------------------------------------------
# Section 4: runtime.stop() integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recording_reaper_stops_cleanly(tmp_path: Path) -> None:
    cfg = BrowserToolConfig(
        enabled=True,
        recording_enabled=True,
        recording_dir=str(tmp_path),
        recording_reaper_interval_seconds=60,
    )
    reaper = RecordingReaper(cfg=cfg)
    await reaper.start()
    assert reaper._task is not None  # noqa: SLF001
    await reaper.stop()
    # Repeat stop is idempotent (no raise).
    await reaper.stop()
