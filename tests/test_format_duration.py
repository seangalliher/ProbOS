"""Tests for BF-074: Shared format_duration utility."""

from probos.utils import format_duration


class TestFormatDuration:

    def test_sub_minute(self):
        assert format_duration(45) == "45s"

    def test_minutes_and_seconds(self):
        assert format_duration(195) == "3m 15s"

    def test_hours_and_minutes(self):
        assert format_duration(7500) == "2h 5m"

    def test_days_and_hours(self):
        assert format_duration(90000) == "1d 1h"

    def test_zero(self):
        assert format_duration(0) == "0s"

    def test_negative_clamped(self):
        assert format_duration(-5) == "0s"

    def test_exact_minute_boundary(self):
        assert format_duration(60) == "1m 0s"

    def test_exact_hour_boundary(self):
        assert format_duration(3600) == "1h 0m"

    def test_import_works(self):
        """Verify the import path resolves correctly."""
        from probos.utils import format_duration as fd
        assert callable(fd)
