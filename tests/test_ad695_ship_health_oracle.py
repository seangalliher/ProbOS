"""AD-695: Tests for Ship Health Oracle Tier 7 + ThresholdAlertService."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from probos.bridge_alerts import AlertSeverity, BridgeAlert
from probos.cognitive.oracle_service import OracleService
from probos.cognitive.threshold_alerts import (
    ThresholdAlert,
    ThresholdAlertService,
)
from probos.config import ThresholdAlertConfig


# ---------- helpers ----------

def _make_runtime(
    *,
    pools: dict | None = None,
    queue_size: int = 0,
    stress_level: str = "normal",
    shed_services: list | None = None,
    ward_room_router: AsyncMock | None = None,
) -> SimpleNamespace:
    spawner = SimpleNamespace(pools=pools or {})
    attention = SimpleNamespace(queue_size=queue_size)
    status = SimpleNamespace(
        stress_level=SimpleNamespace(value=stress_level),
        shed_services=shed_services or [],
    )
    dm = SimpleNamespace(status=lambda: status)
    return SimpleNamespace(
        spawner=spawner,
        attention=attention,
        degradation_manager=dm,
        ward_room_router=ward_room_router,
    )


# ---------- Oracle Tier 7 tests ----------

@pytest.mark.asyncio
async def test_oracle_default_active_tiers_includes_health():
    """Default tier list must include 'health' as the 7th tier."""
    svc = OracleService()
    # Empty query short-circuits to [], but doesn't raise.
    result = await svc.query("", tiers=None)
    assert result == []
    # Verify the source-string contains "health" in the default list.
    import probos.cognitive.oracle_service as mod
    src = mod.__file__
    with open(src, encoding="utf-8") as f:
        text = f.read()
    assert '"graph", "health"' in text


@pytest.mark.asyncio
async def test_query_health_returns_empty_when_no_provider():
    svc = OracleService()
    out = await svc._query_health("vitals pool", k=10)
    assert out == []


@pytest.mark.asyncio
async def test_query_health_pool_stats_happy_path():
    pool = SimpleNamespace(current_size=2, target_size=4)
    provider = SimpleNamespace(
        spawner=SimpleNamespace(pools={"medical": pool}),
    )
    svc = OracleService()
    svc.attach_health_provider(provider)
    out = await svc._query_health("medical pool", k=10)
    assert len(out) == 1
    r = out[0]
    assert r.source_tier == "health"
    assert r.metadata["metric"] == "pool"
    assert r.metadata["current_size"] == 2
    assert r.metadata["target_size"] == 4
    assert r.provenance == "[health: pool]"


@pytest.mark.asyncio
async def test_query_health_attention_queue_metric():
    provider = SimpleNamespace(
        attention=SimpleNamespace(queue_size=7, get_queue_snapshot=lambda: []),
    )
    svc = OracleService(health_provider=provider)
    out = await svc._query_health("attention queue depth", k=10)
    assert len(out) == 1
    r = out[0]
    assert r.metadata["metric"] == "attention"
    assert r.metadata["queue_depth"] == 7


@pytest.mark.asyncio
async def test_query_health_degradation_metric():
    status = SimpleNamespace(
        stress_level=SimpleNamespace(value="degraded"),
        shed_services=["x", "y"],
    )
    provider = SimpleNamespace(
        degradation_manager=SimpleNamespace(status=lambda: status),
    )
    svc = OracleService(health_provider=provider)
    out = await svc._query_health("degradation stress_level", k=10)
    assert len(out) == 1
    r = out[0]
    assert r.metadata["metric"] == "degradation"
    assert r.metadata["stress_level"] == "degraded"
    assert r.metadata["shed_count"] == 2


@pytest.mark.asyncio
async def test_query_health_filters_by_query_keyword():
    pool = SimpleNamespace(current_size=2, target_size=4)
    status = SimpleNamespace(
        stress_level=SimpleNamespace(value="normal"),
        shed_services=[],
    )
    provider = SimpleNamespace(
        spawner=SimpleNamespace(pools={"medical": pool}),
        attention=SimpleNamespace(queue_size=3),
        degradation_manager=SimpleNamespace(status=lambda: status),
    )
    svc = OracleService(health_provider=provider)
    out = await svc._query_health("pool medical", k=10)
    # Pool result is at top with non-zero score; others may be 0 and filtered out.
    assert len(out) >= 1
    assert out[0].metadata["metric"] == "pool"
    # Only the pool tier matches "pool medical" tokens.
    metrics = {r.metadata["metric"] for r in out}
    assert "pool" in metrics


@pytest.mark.asyncio
async def test_query_health_truncates_to_k():
    pools = {
        f"p{i}": SimpleNamespace(current_size=1, target_size=2)
        for i in range(5)
    }
    status = SimpleNamespace(
        stress_level=SimpleNamespace(value="degraded"),
        shed_services=[],
    )
    provider = SimpleNamespace(
        spawner=SimpleNamespace(pools=pools),
        attention=SimpleNamespace(queue_size=10),
        degradation_manager=SimpleNamespace(status=lambda: status),
    )
    svc = OracleService(health_provider=provider)
    out = await svc._query_health("", k=2)
    # Empty query -> uniform 0.5 score; truncated to 2.
    assert len(out) == 2


# ---------- ThresholdAlertConfig defaults ----------

def test_threshold_alert_config_defaults():
    cfg = ThresholdAlertConfig()
    assert cfg.enabled is False
    assert cfg.pool_saturation_floor == 0.9
    assert cfg.attention_queue_depth == 20
    assert cfg.dedup_window_seconds == 300.0
    assert cfg.degradation_min_severity == "degraded"


# ---------- ThresholdAlertService tests ----------

@pytest.mark.asyncio
async def test_check_and_alert_pool_saturation_breach_fires():
    wrr = AsyncMock()
    pool = SimpleNamespace(current_size=9, target_size=10)
    rt = _make_runtime(pools={"medical": pool}, ward_room_router=wrr)
    svc = ThresholdAlertService(rt)
    fired = await svc.check_and_alert()
    assert len(fired) == 1
    a = fired[0]
    assert a.metric == "pool_saturation"
    assert a.value == pytest.approx(0.9)
    assert a.related_pool == "medical"
    assert a.threshold_id == "pool_saturation:medical"
    wrr.deliver_bridge_alert.assert_awaited_once()
    delivered = wrr.deliver_bridge_alert.call_args.args[0]
    assert isinstance(delivered, BridgeAlert)
    assert delivered.dedup_key == "pool_saturation:medical"
    assert delivered.severity == AlertSeverity.ADVISORY


@pytest.mark.asyncio
async def test_check_and_alert_degradation_escalation_fires():
    wrr = AsyncMock()
    rt = _make_runtime(stress_level="critical", ward_room_router=wrr)
    svc = ThresholdAlertService(rt)
    fired = await svc.check_and_alert()
    assert len(fired) == 1
    a = fired[0]
    assert a.severity == "alert"
    assert a.metric == "degradation_tier"
    assert a.value == 3.0
    wrr.deliver_bridge_alert.assert_awaited_once()
    delivered = wrr.deliver_bridge_alert.call_args.args[0]
    assert delivered.severity == AlertSeverity.ALERT


@pytest.mark.asyncio
async def test_check_and_alert_attention_queue_depth_fires():
    wrr = AsyncMock()
    rt = _make_runtime(queue_size=25, ward_room_router=wrr)
    svc = ThresholdAlertService(rt)
    fired = await svc.check_and_alert()
    # queue depth fires; healthy pools/normal degradation do not.
    metrics = {a.metric for a in fired}
    assert "attention_queue_depth" in metrics
    aq = next(a for a in fired if a.metric == "attention_queue_depth")
    assert aq.value == 25.0


@pytest.mark.asyncio
async def test_check_and_alert_dedup_prevents_repost(monkeypatch):
    wrr = AsyncMock()
    pool = SimpleNamespace(current_size=9, target_size=10)
    rt = _make_runtime(pools={"medical": pool}, ward_room_router=wrr)
    svc = ThresholdAlertService(rt, dedup_window_seconds=300.0)

    # Freeze time at t=1000.
    current = {"t": 1000.0}
    monkeypatch.setattr(
        "probos.cognitive.threshold_alerts.time.time",
        lambda: current["t"],
    )

    fired1 = await svc.check_and_alert()
    assert len(fired1) == 1
    assert wrr.deliver_bridge_alert.await_count == 1

    # Second call within dedup window -> no fire.
    current["t"] = 1100.0
    fired2 = await svc.check_and_alert()
    assert fired2 == []
    assert wrr.deliver_bridge_alert.await_count == 1

    # Advance past the window -> fires again.
    current["t"] = 1500.0
    fired3 = await svc.check_and_alert()
    assert len(fired3) == 1
    assert wrr.deliver_bridge_alert.await_count == 2


@pytest.mark.asyncio
async def test_check_and_alert_no_breach_returns_empty():
    wrr = AsyncMock()
    pool = SimpleNamespace(current_size=5, target_size=10)
    rt = _make_runtime(
        pools={"medical": pool},
        queue_size=0,
        stress_level="normal",
        ward_room_router=wrr,
    )
    svc = ThresholdAlertService(rt)
    fired = await svc.check_and_alert()
    assert fired == []
    wrr.deliver_bridge_alert.assert_not_awaited()
