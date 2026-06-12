"""AD-984d: Captain-local timezone in the crew's temporal context.

The crew only had UTC and inferred local time, getting it wrong ("3am" when it
was 9pm Mountain). A configured ``captain_timezone`` surfaces the Captain's
CURRENT local time as a FACT, removing the confabulation source. Unset =
unchanged (UTC only); a bad zone name honest-degrades.

BF-287: real ``SystemConfig`` + the real ``_build_temporal_context`` method
bound to a minimal namespace (the unrelated crew-complement helper is stubbed —
a separate concern; birth/uptime/meta/posts branches skip on absent attrs).
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from probos.config import SystemConfig
from probos.cognitive.cognitive_agent import CognitiveAgent


def _temporal_context(captain_timezone: str = "", *, enabled: bool = True) -> str:
    cfg = SystemConfig()
    cfg.temporal.enabled = enabled
    cfg.temporal.captain_timezone = captain_timezone
    fake = SimpleNamespace(
        _runtime=SimpleNamespace(config=cfg),
        # Separate concern (AD-513); not under test here.
        _build_crew_complement=lambda: "",
    )
    return CognitiveAgent._build_temporal_context(fake)


def test_unset_timezone_shows_utc_only():
    out = _temporal_context("")
    assert "Current time:" in out and "UTC" in out
    assert "Captain's local time" not in out


def test_configured_timezone_adds_captain_local_line():
    out = _temporal_context("America/Denver")
    assert "Current time:" in out and "UTC" in out  # UTC line preserved
    assert "Captain's local time:" in out
    assert "America/Denver" in out


def test_configured_timezone_actually_converts():
    # The rendered local time must match an independent conversion (proves the
    # branch converts rather than echoing UTC). Compare the date+hour, which is
    # stable within the sub-second call window.
    out = _temporal_context("America/Denver")
    local = datetime.now(timezone.utc).astimezone(ZoneInfo("America/Denver"))
    assert f"Captain's local time: {local.strftime('%Y-%m-%d %H:%M')}" in out


def test_bad_timezone_honest_degrades_to_utc_only():
    # An unknown zone name must not raise and must leave the UTC line untouched.
    out = _temporal_context("Not/ARealZone")
    assert "Current time:" in out and "UTC" in out
    assert "Captain's local time" not in out


def test_temporal_disabled_returns_empty_even_with_timezone():
    assert _temporal_context("America/Denver", enabled=False) == ""


def test_config_default_is_empty():
    # Default behavior unchanged: no timezone configured out of the box.
    assert SystemConfig().temporal.captain_timezone == ""
