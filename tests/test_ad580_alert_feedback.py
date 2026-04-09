"""Tests for AD-580: Alert resolution feedback loop.

Tests dismiss/resolve/mute suppression, detection tracking,
pattern matching, list_suppressed, and API endpoints.
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from probos.bridge_alerts import BridgeAlertService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_service(**kwargs) -> BridgeAlertService:
    """Create a BridgeAlertService with short defaults for testing."""
    defaults = {
        "cooldown_seconds": 1.0,
        "resolve_clean_period": 5.0,
        "default_dismiss_duration": 10.0,
    }
    defaults.update(kwargs)
    return BridgeAlertService(**defaults)


# ---------------------------------------------------------------------------
# TestAlertDismiss (4 tests)
# ---------------------------------------------------------------------------

class TestAlertDismiss:
    """Dismiss suppression: time-limited suppression."""

    def test_dismiss_suppresses_alert(self):
        """Dismissed dedup_key → _should_emit() returns False."""
        bas = _make_service()
        bas.dismiss_alert("test:key", 60.0)
        assert bas._should_emit("test:key") is False

    def test_dismiss_expires(self):
        """After duration passes, alert fires again."""
        bas = _make_service()
        bas.dismiss_alert("test:key", 0.01)  # 10ms
        time.sleep(0.02)
        # After expiry, should_emit should return True
        assert bas._should_emit("test:key") is True

    def test_dismiss_custom_duration(self):
        """Custom duration_seconds honored over default."""
        bas = _make_service(default_dismiss_duration=9999.0)
        bas.dismiss_alert("test:key", 0.01)
        time.sleep(0.02)
        assert bas._should_emit("test:key") is True

    def test_dismiss_unknown_key_noop(self):
        """Dismissing an unknown key succeeds without error (pre-emptive dismiss)."""
        bas = _make_service()
        # Should not raise — logs warning but no error
        bas.dismiss_alert("never:seen", 60.0)
        assert "never:seen" in bas._dismissed


# ---------------------------------------------------------------------------
# TestAlertResolve (5 tests)
# ---------------------------------------------------------------------------

class TestAlertResolve:
    """Resolve suppression: suppressed until clean detection period elapses."""

    def test_resolve_suppresses_alert(self):
        """Resolved alert suppressed immediately."""
        bas = _make_service()
        bas.resolve_alert("test:key")
        assert bas._should_emit("test:key") is False

    def test_resolve_refires_after_clean_period(self):
        """Pattern gone for clean period, then recurs → fires.

        After resolve, if no detection occurs for resolve_clean_period, the
        resolved state is cleared.  _should_emit always counts as a detection
        (updates _last_detected before checking suppression), so we verify
        via _is_suppressed that the clean gap elapses when there are no
        detections.
        """
        bas = _make_service(resolve_clean_period=0.02)
        bas.resolve_alert("test:key")
        # Immediately after resolve, suppressed
        assert bas._is_suppressed("test:key") is True
        # Wait for clean period with NO detection
        time.sleep(0.03)
        # Clean period elapsed → no longer suppressed
        assert bas._is_suppressed("test:key") is False

    def test_resolve_no_refire_during_clean_period(self):
        """Pattern recurs within clean period → still suppressed."""
        bas = _make_service(resolve_clean_period=5.0)
        bas.resolve_alert("test:key")
        # First check — suppressed but updates last_detected
        assert bas._should_emit("test:key") is False
        # Second check within clean period — still suppressed
        assert bas._should_emit("test:key") is False

    def test_resolve_tracks_last_detected(self):
        """Each detection updates _last_detected even when suppressed."""
        bas = _make_service(resolve_clean_period=5.0)
        bas.resolve_alert("test:key")
        t1 = bas._last_detected.get("test:key")
        time.sleep(0.01)
        bas._should_emit("test:key")
        t2 = bas._last_detected.get("test:key")
        assert t2 is not None
        # t1 might be None (set only after _should_emit runs) or earlier
        if t1 is not None:
            assert t2 >= t1

    def test_resolve_continuous_detection_stays_suppressed(self):
        """Pattern detected continuously without clean gap → stays suppressed indefinitely."""
        bas = _make_service(resolve_clean_period=0.05)
        bas.resolve_alert("test:key")
        # Keep detecting — clean period never elapses
        for _ in range(20):
            assert bas._should_emit("test:key") is False
            time.sleep(0.005)
        # Still suppressed because continuous detection resets the gap
        assert bas._should_emit("test:key") is False


# ---------------------------------------------------------------------------
# TestAlertMute (3 tests)
# ---------------------------------------------------------------------------

class TestAlertMute:
    """Mute suppression: indefinite suppression until unmuted."""

    def test_mute_suppresses_indefinitely(self):
        """Muted alert never fires."""
        bas = _make_service()
        bas.mute_alert("test:key")
        for _ in range(10):
            assert bas._should_emit("test:key") is False

    def test_unmute_allows_firing(self):
        """After unmute, alert fires normally."""
        bas = _make_service()
        bas.mute_alert("test:key")
        assert bas._should_emit("test:key") is False
        bas.unmute_alert("test:key")
        assert bas._should_emit("test:key") is True

    def test_mute_survives_many_cycles(self):
        """Muted alert stays muted across many detection cycles."""
        bas = _make_service(cooldown_seconds=0.001)
        bas.mute_alert("test:key")
        for _ in range(50):
            assert bas._should_emit("test:key") is False
        # Still muted
        assert "test:key" in bas._muted


# ---------------------------------------------------------------------------
# TestAlertListSuppressed (2 tests)
# ---------------------------------------------------------------------------

class TestAlertListSuppressed:
    """list_suppressed() returns metadata for all three suppression modes."""

    def test_list_shows_all_suppression_modes(self):
        """List returns dismissed, resolved, and muted entries with mode metadata."""
        bas = _make_service()
        bas.dismiss_alert("d:key", 100.0)
        bas.resolve_alert("r:key")
        bas.mute_alert("m:key")

        suppressed = bas.list_suppressed()
        modes = {e["dedup_key"]: e["mode"] for e in suppressed}
        assert modes["d:key"] == "dismissed"
        assert modes["r:key"] == "resolved"
        assert modes["m:key"] == "muted"

        # Dismissed has remaining_seconds
        dismissed = [e for e in suppressed if e["mode"] == "dismissed"][0]
        assert "remaining_seconds" in dismissed
        assert dismissed["remaining_seconds"] > 0

        # Resolved has clean_gap_seconds and clean_period_needed
        resolved = [e for e in suppressed if e["mode"] == "resolved"][0]
        assert "clean_gap_seconds" in resolved
        assert "clean_period_needed" in resolved

    def test_list_excludes_expired(self):
        """Expired dismissals not shown."""
        bas = _make_service()
        bas.dismiss_alert("expired:key", 0.01)
        time.sleep(0.02)
        # Trigger _is_suppressed to clean up expired entry
        bas._should_emit("expired:key")

        suppressed = bas.list_suppressed()
        keys = [e["dedup_key"] for e in suppressed]
        assert "expired:key" not in keys


# ---------------------------------------------------------------------------
# TestAlertDetectionTracking (2 tests)
# ---------------------------------------------------------------------------

class TestAlertDetectionTracking:
    """_last_detected tracking independent of emission."""

    def test_last_detected_updated_on_suppressed_emission(self):
        """_last_detected updates even when _should_emit() returns False."""
        bas = _make_service()
        bas.mute_alert("test:key")
        assert bas._should_emit("test:key") is False
        assert "test:key" in bas._last_detected

    def test_last_detected_not_set_for_unknown_keys(self):
        """No phantom entries for keys never passed through _should_emit()."""
        bas = _make_service()
        assert "phantom:key" not in bas._last_detected


# ---------------------------------------------------------------------------
# TestAlertAPI (3 tests)
# ---------------------------------------------------------------------------

class TestAlertAPI:
    """API endpoint tests for alert suppression."""

    @pytest.fixture
    def mock_runtime(self):
        from probos.runtime import ProbOSRuntime
        runtime = MagicMock(spec=ProbOSRuntime)
        runtime._started = True
        runtime.registry = MagicMock()
        runtime.registry.count = 0
        runtime.registry.all.return_value = []

        # Provide a real BridgeAlertService for suppression API tests
        runtime.bridge_alerts = _make_service()

        # Minimal services
        runtime.ward_room = MagicMock()
        runtime.episodic_memory = MagicMock()
        runtime.trust_network = MagicMock()
        runtime._knowledge_store = None
        runtime.cognitive_journal = None
        runtime.codebase_index = None
        runtime.skill_registry = None
        runtime.skill_service = None
        runtime.acm = None
        runtime.hebbian_router = None
        runtime.intent_bus = None
        runtime.llm_client = None
        runtime.notification_queue = MagicMock()
        return runtime

    @pytest.fixture
    def client(self, mock_runtime):
        from probos.api import create_app
        from fastapi.testclient import TestClient
        app = create_app(mock_runtime)
        return TestClient(app)

    def test_dismiss_endpoint(self, client, mock_runtime):
        """POST /api/alerts/dismiss works."""
        resp = client.post("/api/alerts/dismiss", json={
            "dedup_key": "test:key", "duration_seconds": 60.0,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "dismissed"
        assert data["dedup_key"] == "test:key"
        # Verify actually suppressed
        assert mock_runtime.bridge_alerts._should_emit("test:key") is False

    def test_suppressed_endpoint(self, client, mock_runtime):
        """GET /api/alerts/suppressed returns correct data."""
        mock_runtime.bridge_alerts.mute_alert("muted:key")
        mock_runtime.bridge_alerts.dismiss_alert("dismissed:key", 300.0)

        resp = client.get("/api/alerts/suppressed")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        keys = [e["dedup_key"] for e in data["suppressed"]]
        assert "muted:key" in keys
        assert "dismissed:key" in keys

    def test_mute_unmute_roundtrip(self, client, mock_runtime):
        """Mute then unmute via API."""
        resp = client.post("/api/alerts/mute", json={"dedup_key": "test:key"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "muted"
        assert mock_runtime.bridge_alerts._should_emit("test:key") is False

        resp = client.post("/api/alerts/unmute", json={"dedup_key": "test:key"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "unmuted"
        assert mock_runtime.bridge_alerts._should_emit("test:key") is True


# ---------------------------------------------------------------------------
# TestAlertPatternMatching (2 tests)
# ---------------------------------------------------------------------------

class TestAlertPatternMatching:
    """find_matching_keys() substring and exact-match logic."""

    def test_substring_match_finds_prefixed_key(self):
        """'cooperation_cluster' matches 'emergent:cooperation_cluster'."""
        bas = _make_service()
        # Seed a key into _recent (as if it had fired)
        bas._recent["emergent:cooperation_cluster"] = time.monotonic()

        matches = bas.find_matching_keys("cooperation_cluster")
        assert "emergent:cooperation_cluster" in matches

    def test_exact_key_preferred_over_substring(self):
        """When both exact and substring match exist, exact wins."""
        bas = _make_service()
        bas._recent["foo"] = time.monotonic()
        bas._recent["prefix:foo"] = time.monotonic()

        matches = bas.find_matching_keys("foo")
        # Exact match returns single element
        assert matches == ["foo"]
