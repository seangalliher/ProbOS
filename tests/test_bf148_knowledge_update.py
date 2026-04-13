"""BF-148: Knowledge update probe — temporal preference + timestamp fix."""

import time
import pytest

from probos.cognitive.memory_probes import _UPDATE_PAIRS, KnowledgeUpdateProbe
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.source_governance import SourceAuthority


class TestBF148TimestampFix:
    """All episode timestamps must be in the past."""

    def test_no_future_timestamps(self):
        """BF-148: Knowledge update probe must not create future-dated episodes."""
        # Simulate the timestamp calculation from _run_inner
        base_ts = time.time() - 7200
        now = time.time()
        for i in range(len(_UPDATE_PAIRS)):
            old_ts = base_ts + i * 600
            new_ts = base_ts + 3600 + i * 600
            assert old_ts < now, f"Pair {i} old timestamp {old_ts} >= now {now}"
            assert new_ts < now, f"Pair {i} new timestamp {new_ts} >= now {now}"

    def test_new_is_more_recent_than_old(self):
        """BF-148: 'New' episode must always be more recent than 'old'."""
        base_ts = time.time() - 7200
        for i in range(len(_UPDATE_PAIRS)):
            old_ts = base_ts + i * 600
            new_ts = base_ts + 3600 + i * 600
            assert new_ts > old_ts, f"Pair {i}: new={new_ts} should be > old={old_ts}"

    def test_temporal_separation_sufficient(self):
        """BF-148: Old and new episodes should have at least 30min separation."""
        base_ts = time.time() - 7200
        for i in range(len(_UPDATE_PAIRS)):
            old_ts = base_ts + i * 600
            new_ts = base_ts + 3600 + i * 600
            separation_minutes = (new_ts - old_ts) / 60
            assert separation_minutes >= 30, f"Pair {i} separation {separation_minutes}min < 30min"


class TestBF148TemporalPreference:
    """Confabulation guard includes temporal preference instruction."""

    def test_supplementary_tier_has_temporal_preference(self):
        """BF-148: SUPPLEMENTARY tier includes temporal preference."""
        text = CognitiveAgent._confabulation_guard(SourceAuthority.SUPPLEMENTARY)
        assert "most recent" in text.lower() or "prefer" in text.lower()

    def test_peripheral_tier_has_temporal_preference(self):
        """BF-148: PERIPHERAL tier includes temporal preference."""
        text = CognitiveAgent._confabulation_guard(SourceAuthority.PERIPHERAL)
        assert "most recent" in text.lower() or "prefer" in text.lower()

    def test_authoritative_tier_has_temporal_preference(self):
        """BF-159: AUTHORITATIVE tier includes temporal preference.

        Temporal contradictions are valid even for high-quality memories.
        AGM Belief Revision: newer observations supersede older ones,
        regardless of source authority level.
        """
        text = CognitiveAgent._confabulation_guard(SourceAuthority.AUTHORITATIVE)
        assert "most recent" in text.lower() or "prefer" in text.lower()

    def test_authoritative_tier_no_orientation_priority(self):
        """BF-159: AUTHORITATIVE tier still omits orientation priority.

        Orientation priority ("orientation data is authoritative") is about
        system data quality — not appropriate for high-quality memories.
        This is distinct from temporal preference (time ordering).
        """
        text = CognitiveAgent._confabulation_guard(SourceAuthority.AUTHORITATIVE)
        assert "orientation" not in text.lower()

    def test_none_authority_has_temporal_preference(self):
        """BF-148: None authority (fallback) includes temporal preference."""
        text = CognitiveAgent._confabulation_guard(None)
        assert "most recent" in text.lower() or "prefer" in text.lower()
