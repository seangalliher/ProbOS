"""Tests for ServiceProfile + ServiceProfileStore (AD-382)."""

import unittest

from probos.service_profile import (
    LatencyStats, ServiceProfile, ServiceProfileStore,
    DEFAULT_INTERVAL, _SEED_INTERVALS,
)


class TestLatencyStats(unittest.TestCase):
    def test_record_latencies(self) -> None:
        stats = LatencyStats()
        # Simulate realistic traffic: many low-latency requests with occasional spikes
        for _ in range(50):
            stats.record(100.0)  # typical latency
        for _ in range(5):
            stats.record(500.0)  # spikes
        assert stats.sample_count == 55
        assert stats.p50_ms > 0
        assert stats.p95_ms >= stats.p50_ms
        assert stats.p99_ms >= stats.p95_ms

    def test_roundtrip_dict(self) -> None:
        stats = LatencyStats()
        stats.record(50.0)
        stats.record(200.0)
        d = stats.to_dict()
        restored = LatencyStats.from_dict(d)
        assert restored.sample_count == 2
        assert restored.p50_ms == stats.p50_ms
        assert restored.p95_ms == stats.p95_ms
        assert restored.p99_ms == stats.p99_ms


class TestServiceProfile(unittest.TestCase):
    def test_defaults(self) -> None:
        p = ServiceProfile(domain="example.com")
        assert p.error_rate == 0.0
        assert p.reliability == 1.0
        assert p.total_requests == 0

    def test_record_request_success(self) -> None:
        p = ServiceProfile(domain="example.com")
        p.record_request(100.0, 200)
        assert p.total_requests == 1
        assert p.total_errors == 0
        assert p.total_rate_limits == 0
        assert p.last_request_at > 0

    def test_record_request_429(self) -> None:
        p = ServiceProfile(domain="example.com", learned_min_interval=2.0)
        p.record_request(100.0, 429)
        assert p.total_rate_limits == 1
        assert p.learned_min_interval == 3.0  # 2.0 * 1.5
        assert p.last_rate_limit_at > 0

    def test_record_request_429_cap(self) -> None:
        p = ServiceProfile(domain="example.com", learned_min_interval=50.0)
        p.record_request(100.0, 429)  # 50 * 1.5 = 75, capped at 60
        assert p.learned_min_interval == 60.0

    def test_record_request_recovery(self) -> None:
        p = ServiceProfile(domain="example.com", learned_min_interval=2.0)
        p.record_request(100.0, 429)  # → 3.0
        assert p.learned_min_interval == 3.0
        p.record_request(100.0, 200)  # → 3.0 * 0.9 = 2.7
        assert p.learned_min_interval == pytest.approx(2.7, abs=0.01)

    def test_record_request_recovery_floor(self) -> None:
        """Recovery doesn't go below the seed interval."""
        p = ServiceProfile(domain="api.coingecko.com", learned_min_interval=3.0)
        p.record_request(100.0, 429)  # → 4.5
        # Multiple successes should decay back toward 3.0 but not below
        for _ in range(20):
            p.record_request(100.0, 200)
        assert p.learned_min_interval >= 3.0

    def test_record_request_5xx(self) -> None:
        p = ServiceProfile(domain="example.com")
        p.record_request(100.0, 500)
        assert p.total_errors == 1
        assert p.total_rate_limits == 0

    def test_error_rate_calculation(self) -> None:
        p = ServiceProfile(domain="example.com")
        for _ in range(8):
            p.record_request(100.0, 200)
        p.record_request(100.0, 500)
        p.record_request(100.0, 429)
        assert p.error_rate == pytest.approx(0.2)
        assert p.reliability == pytest.approx(0.8)

    def test_roundtrip_dict(self) -> None:
        p = ServiceProfile(domain="example.com", learned_min_interval=5.0)
        p.record_request(100.0, 200)
        d = p.to_dict()
        restored = ServiceProfile.from_dict(d)
        assert restored.domain == "example.com"
        assert restored.learned_min_interval == 5.0
        assert restored.total_requests == 1


class TestServiceProfileStore(unittest.TestCase):
    def test_get_or_create_seed(self) -> None:
        store = ServiceProfileStore(db_path=":memory:")
        p = store.get_or_create("unknown-domain.com")
        assert p.domain == "unknown-domain.com"
        assert p.learned_min_interval == DEFAULT_INTERVAL

    def test_get_or_create_known(self) -> None:
        store = ServiceProfileStore(db_path=":memory:")
        p = store.get_or_create("api.coingecko.com")
        assert p.learned_min_interval == 3.0

    def test_save_and_reload(self) -> None:
        import tempfile, os
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            store1 = ServiceProfileStore(db_path=path)
            p = store1.get_or_create("example.com")
            p.record_request(150.0, 200)
            store1.save(p)
            store1.close()

            # New store from same db
            store2 = ServiceProfileStore(db_path=path)
            p2 = store2.get_or_create("example.com")
            assert p2.total_requests == 1
            assert p2.latency.sample_count == 1
            store2.close()
        finally:
            os.unlink(path)

    def test_all_profiles_ordered(self) -> None:
        store = ServiceProfileStore(db_path=":memory:")
        pa = store.get_or_create("a.com")
        pa.total_requests = 10
        store.save(pa)
        pb = store.get_or_create("b.com")
        pb.total_requests = 50
        store.save(pb)
        pc = store.get_or_create("c.com")
        pc.total_requests = 5
        store.save(pc)

        profiles = store.all_profiles()
        assert len(profiles) == 3
        assert profiles[0].total_requests >= profiles[1].total_requests >= profiles[2].total_requests

    def test_get_interval_no_profile(self) -> None:
        store = ServiceProfileStore(db_path=":memory:")
        # Known seed domain — no profile created
        interval = store.get_interval("api.coingecko.com")
        assert interval == 3.0
        # Unknown domain
        interval2 = store.get_interval("unknown.com")
        assert interval2 == DEFAULT_INTERVAL
        # Should NOT have created profiles
        assert store.all_profiles() == []

    def test_get_interval_with_profile(self) -> None:
        store = ServiceProfileStore(db_path=":memory:")
        p = store.get_or_create("test.com")
        p.learned_min_interval = 5.0
        store.save(p)
        assert store.get_interval("test.com") == 5.0


# pytest.approx support
import pytest


if __name__ == "__main__":
    unittest.main()
