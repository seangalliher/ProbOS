"""AD-763: ProactiveScanConfig Pydantic defaults + validation tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from probos.config import (
    ProactiveScanCalendarConfig,
    ProactiveScanConfig,
    ProactiveScanInboxConfig,
    SystemConfig,
)


class TestDefaults:
    def test_inbox_defaults(self) -> None:
        cfg = ProactiveScanInboxConfig()
        assert cfg.folders == ["Inbox"]
        assert cfg.lookback_hours == 24
        assert cfg.importance_filter == "any"
        assert cfg.unread_only is False
        assert cfg.sender_allowlist == []
        assert cfg.sender_denylist == []

    def test_calendar_defaults(self) -> None:
        cfg = ProactiveScanCalendarConfig()
        assert cfg.calendar_ids == ["primary"]
        assert cfg.lookahead_hours == 24
        assert cfg.include_declined is False

    def test_root_defaults(self) -> None:
        cfg = ProactiveScanConfig()
        assert cfg.inbox.folders == ["Inbox"]
        assert cfg.calendar.calendar_ids == ["primary"]

    def test_system_config_includes_proactive_scan(self) -> None:
        sc = SystemConfig()
        assert isinstance(sc.proactive_scan, ProactiveScanConfig)
        assert sc.proactive_scan.inbox.importance_filter == "any"


class TestValidation:
    def test_importance_filter_rejects_unknown(self) -> None:
        with pytest.raises(ValidationError):
            ProactiveScanInboxConfig(importance_filter="medium")  # type: ignore[arg-type]

    def test_lookback_hours_rejects_zero(self) -> None:
        with pytest.raises(ValidationError):
            ProactiveScanInboxConfig(lookback_hours=0)

    def test_lookback_hours_rejects_too_large(self) -> None:
        with pytest.raises(ValidationError):
            ProactiveScanInboxConfig(lookback_hours=10_000)

    def test_lookahead_hours_rejects_zero(self) -> None:
        with pytest.raises(ValidationError):
            ProactiveScanCalendarConfig(lookahead_hours=0)

    def test_unread_only_rejects_non_bool(self) -> None:
        with pytest.raises(ValidationError):
            ProactiveScanInboxConfig(unread_only="yes please")  # type: ignore[arg-type]


class TestRoundTrip:
    def test_model_dump_round_trip(self) -> None:
        original = ProactiveScanConfig(
            inbox=ProactiveScanInboxConfig(
                folders=["Inbox", "Archive"],
                lookback_hours=12,
                importance_filter="high",
                unread_only=True,
                sender_allowlist=["@acme.com"],
                sender_denylist=["noise@spam.com"],
            ),
            calendar=ProactiveScanCalendarConfig(
                calendar_ids=["primary", "team"],
                lookahead_hours=48,
                include_declined=True,
            ),
        )
        dumped = original.model_dump()
        revived = ProactiveScanConfig(
            inbox=ProactiveScanInboxConfig(**dumped["inbox"]),
            calendar=ProactiveScanCalendarConfig(**dumped["calendar"]),
        )
        assert revived == original

    def test_empty_folders_allowed_for_defer_mode(self) -> None:
        """Empty folder list is valid — connector falls back to ['Inbox'] at call time."""
        cfg = ProactiveScanInboxConfig(folders=[])
        assert cfg.folders == []
