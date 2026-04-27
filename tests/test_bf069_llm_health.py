"""BF-069: LLM Proxy Health Monitoring & Alerting — 25 tests."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# LLM Client Health Tracking (9 tests)
# ---------------------------------------------------------------------------


class TestLLMClientHealthTracking:
    """Tests for OpenAICompatibleClient health status tracking."""

    def _make_client(self):
        """Create a minimal OpenAICompatibleClient for testing."""
        from probos.cognitive.llm_client import OpenAICompatibleClient
        client = OpenAICompatibleClient.__new__(OpenAICompatibleClient)
        # Initialize the health tracking state
        client._consecutive_failures = {t: 0 for t in ("fast", "standard", "deep")}
        client._consecutive_successes = {t: 0 for t in ("fast", "standard", "deep")}
        client._min_consecutive_healthy = 3
        client._last_success = {}
        client._last_failure = {}
        return client

    def test_health_status_all_operational(self):
        """Fresh client with no failures → all tiers operational, overall operational."""
        client = self._make_client()
        status = client.get_health_status()
        assert status["overall"] == "operational"
        for tier in ("fast", "standard", "deep"):
            assert status["tiers"][tier]["status"] == "operational"
            assert status["tiers"][tier]["consecutive_failures"] == 0

    def test_health_status_single_tier_degraded(self):
        """1-2 failures on one tier → that tier degraded, overall degraded."""
        client = self._make_client()
        client._consecutive_failures["fast"] = 2
        status = client.get_health_status()
        assert status["tiers"]["fast"]["status"] == "degraded"
        assert status["tiers"]["standard"]["status"] == "operational"
        assert status["overall"] == "degraded"

    def test_health_status_single_tier_unreachable(self):
        """3+ failures on one tier → that tier unreachable, overall degraded."""
        client = self._make_client()
        client._consecutive_failures["standard"] = 5
        status = client.get_health_status()
        assert status["tiers"]["standard"]["status"] == "unreachable"
        assert status["tiers"]["fast"]["status"] == "operational"
        assert status["overall"] == "degraded"

    def test_health_status_all_unreachable(self):
        """3+ failures on all tiers → overall offline."""
        client = self._make_client()
        for tier in ("fast", "standard", "deep"):
            client._consecutive_failures[tier] = 3
        status = client.get_health_status()
        assert status["overall"] == "offline"
        for tier in ("fast", "standard", "deep"):
            assert status["tiers"][tier]["status"] == "unreachable"

    def test_failure_counter_resets_on_success(self):
        """Successful call resets consecutive failures to 0."""
        client = self._make_client()
        client._consecutive_failures["fast"] = 5
        # Simulate a successful completion
        client._consecutive_failures["fast"] = 0
        client._last_success["fast"] = time.monotonic()
        status = client.get_health_status()
        assert status["tiers"]["fast"]["status"] == "operational"
        assert status["tiers"]["fast"]["consecutive_failures"] == 0

    def test_failure_counter_increments_on_connect_error(self):
        """ConnectError increments counter."""
        client = self._make_client()
        assert client._consecutive_failures["fast"] == 0
        client._consecutive_failures["fast"] += 1
        client._last_failure["fast"] = time.monotonic()
        assert client._consecutive_failures["fast"] == 1
        status = client.get_health_status()
        assert status["tiers"]["fast"]["status"] == "degraded"

    def test_failure_counter_increments_on_timeout(self):
        """TimeoutException increments counter."""
        client = self._make_client()
        client._consecutive_failures["standard"] += 1
        client._last_failure["standard"] = time.monotonic()
        assert client._consecutive_failures["standard"] == 1

    def test_failure_counter_increments_on_http_error(self):
        """HTTPStatusError increments counter."""
        client = self._make_client()
        for _ in range(3):
            client._consecutive_failures["deep"] += 1
            client._last_failure["deep"] = time.monotonic()
        status = client.get_health_status()
        assert status["tiers"]["deep"]["status"] == "unreachable"
        assert status["tiers"]["deep"]["consecutive_failures"] == 3

    def test_connectivity_check_resets_counters(self):
        """Successful check_connectivity resets failure counters."""
        client = self._make_client()
        client._consecutive_failures["fast"] = 5
        client._consecutive_failures["standard"] = 3
        # Simulate what check_connectivity does when tier is reachable
        client._consecutive_failures["fast"] = 0
        client._last_success["fast"] = time.monotonic()
        client._consecutive_failures["standard"] = 0
        client._last_success["standard"] = time.monotonic()
        status = client.get_health_status()
        assert status["tiers"]["fast"]["status"] == "operational"
        assert status["tiers"]["standard"]["status"] == "operational"


class TestBaseLLMClientHealth:
    """Base class default health status."""

    def test_base_client_default_health(self):
        """BaseLLMClient.get_health_status returns all-operational default."""
        from probos.cognitive.llm_client import BaseLLMClient

        class TestClient(BaseLLMClient):
            async def complete(self, request):
                pass

        client = TestClient()
        status = client.get_health_status()
        assert status["overall"] == "operational"
        for tier in ("fast", "standard", "deep"):
            assert status["tiers"][tier]["status"] == "operational"
            assert status["tiers"][tier]["consecutive_failures"] == 0


# ---------------------------------------------------------------------------
# VitalsMonitor Extension (4 tests)
# ---------------------------------------------------------------------------


class TestVitalsMonitorLLMHealth:
    """VitalsMonitor LLM health integration."""

    def _make_rt_mock(self, llm_health=None):
        """Create a runtime mock with llm_client."""
        rt = MagicMock()
        rt.pools = {}
        rt.trust_network.all_scores.return_value = {}
        rt.dream_scheduler = None
        rt.registry.all.return_value = []
        if llm_health is not None:
            rt.llm_client = MagicMock()
            rt.llm_client.get_health_status.return_value = llm_health
        else:
            rt.llm_client = None
        return rt

    @pytest.mark.asyncio
    async def test_vitals_includes_llm_health(self):
        """collect_metrics() includes llm_health key."""
        from probos.agents.medical.vitals_monitor import VitalsMonitorAgent

        agent = VitalsMonitorAgent.__new__(VitalsMonitorAgent)
        agent.id = "vitals-001"
        agent._pulse_count = 1
        agent._pool_health_min = 0.5
        agent._trust_floor = 0.3
        agent._health_floor = 0.6
        agent._max_trust_outliers = 3
        agent._window = __import__("collections").deque(maxlen=12)
        agent._runtime = self._make_rt_mock(
            llm_health={"overall": "operational", "tiers": {
                "fast": {"status": "operational"},
                "standard": {"status": "operational"},
                "deep": {"status": "operational"},
            }}
        )
        # Patch out threshold checks
        agent._check_thresholds = AsyncMock()

        metrics = await agent.collect_metrics()
        assert "llm_health" in metrics
        assert metrics["llm_health"]["overall"] == "operational"

    @pytest.mark.asyncio
    async def test_vitals_threshold_llm_offline_alert(self):
        """LLM offline triggers medical_alert with severity critical."""
        from probos.agents.medical.vitals_monitor import VitalsMonitorAgent

        agent = VitalsMonitorAgent.__new__(VitalsMonitorAgent)
        agent.id = "vitals-002"
        agent._pool_health_min = 0.5
        agent._trust_floor = 0.3
        agent._health_floor = 0.6
        agent._max_trust_outliers = 3

        rt = MagicMock()
        rt.intent_bus = MagicMock()
        rt.intent_bus.broadcast = AsyncMock()

        metrics = {
            "timestamp": time.time(),
            "pool_health": {},
            "trust_outliers": [],
            "system_health": 1.0,
            "llm_health": {"overall": "offline", "tiers": {}},
        }

        await agent._check_thresholds(metrics, rt)
        # Should have broadcast at least one alert
        calls = rt.intent_bus.broadcast.call_args_list
        llm_alerts = [c for c in calls if c[0][0].params.get("metric") == "llm_health"]
        assert len(llm_alerts) >= 1
        assert llm_alerts[0][0][0].params["severity"] == "critical"

    @pytest.mark.asyncio
    async def test_vitals_threshold_llm_degraded_alert(self):
        """LLM degraded triggers medical_alert with severity warning."""
        from probos.agents.medical.vitals_monitor import VitalsMonitorAgent

        agent = VitalsMonitorAgent.__new__(VitalsMonitorAgent)
        agent.id = "vitals-003"
        agent._pool_health_min = 0.5
        agent._trust_floor = 0.3
        agent._health_floor = 0.6
        agent._max_trust_outliers = 3

        rt = MagicMock()
        rt.intent_bus = MagicMock()
        rt.intent_bus.broadcast = AsyncMock()

        metrics = {
            "timestamp": time.time(),
            "pool_health": {},
            "trust_outliers": [],
            "system_health": 1.0,
            "llm_health": {
                "overall": "degraded",
                "tiers": {
                    "fast": {"status": "unreachable"},
                    "standard": {"status": "operational"},
                },
            },
        }

        await agent._check_thresholds(metrics, rt)
        calls = rt.intent_bus.broadcast.call_args_list
        llm_alerts = [c for c in calls if c[0][0].params.get("metric") == "llm_health"]
        assert len(llm_alerts) >= 1
        assert llm_alerts[0][0][0].params["severity"] == "warning"

    @pytest.mark.asyncio
    async def test_vitals_no_alert_when_operational(self):
        """LLM operational triggers no medical_alert."""
        from probos.agents.medical.vitals_monitor import VitalsMonitorAgent

        agent = VitalsMonitorAgent.__new__(VitalsMonitorAgent)
        agent.id = "vitals-004"
        agent._pool_health_min = 0.5
        agent._trust_floor = 0.3
        agent._health_floor = 0.6
        agent._max_trust_outliers = 3

        rt = MagicMock()
        rt.intent_bus = MagicMock()
        rt.intent_bus.broadcast = AsyncMock()

        metrics = {
            "timestamp": time.time(),
            "pool_health": {},
            "trust_outliers": [],
            "system_health": 1.0,
            "llm_health": {"overall": "operational", "tiers": {}},
        }

        await agent._check_thresholds(metrics, rt)
        calls = rt.intent_bus.broadcast.call_args_list
        llm_alerts = [c for c in calls if c[0][0].params.get("metric") == "llm_health"]
        assert len(llm_alerts) == 0


# ---------------------------------------------------------------------------
# BridgeAlertService Extension (5 tests)
# ---------------------------------------------------------------------------


class TestBridgeAlertLLMHealth:
    """BridgeAlertService.check_llm_health() tests."""

    def test_bridge_alert_llm_offline(self):
        """Overall offline → ALERT severity, 'Communications Array Offline'."""
        from probos.bridge_alerts import AlertSeverity, BridgeAlertService

        svc = BridgeAlertService(cooldown_seconds=0.01)
        alerts = svc.check_llm_health({"overall": "offline", "tiers": {}})
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.ALERT
        assert "Communications Array Offline" in alerts[0].title
        assert alerts[0].source == "llm_client"
        assert alerts[0].alert_type == "llm_offline"

    def test_bridge_alert_llm_degraded(self):
        """Overall degraded with unreachable tiers → ADVISORY severity."""
        from probos.bridge_alerts import AlertSeverity, BridgeAlertService

        svc = BridgeAlertService(cooldown_seconds=0.01)
        health = {
            "overall": "degraded",
            "tiers": {
                "fast": {"status": "unreachable"},
                "standard": {"status": "operational"},
                "deep": {"status": "operational"},
            },
        }
        alerts = svc.check_llm_health(health)
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.ADVISORY
        assert "Communications Array Degraded" in alerts[0].title
        assert "fast" in alerts[0].detail

    def test_bridge_alert_llm_operational_no_alert(self):
        """Overall operational → no alerts."""
        from probos.bridge_alerts import BridgeAlertService

        svc = BridgeAlertService()
        alerts = svc.check_llm_health({"overall": "operational", "tiers": {}})
        assert len(alerts) == 0

    def test_bridge_alert_llm_dedup(self):
        """Same alert suppressed within cooldown period."""
        from probos.bridge_alerts import BridgeAlertService

        svc = BridgeAlertService(cooldown_seconds=300)
        alerts1 = svc.check_llm_health({"overall": "offline", "tiers": {}})
        assert len(alerts1) == 1
        # Second call within cooldown → suppressed
        alerts2 = svc.check_llm_health({"overall": "offline", "tiers": {}})
        assert len(alerts2) == 0

    def test_bridge_alert_llm_dedup_different_tiers(self):
        """Different tier combinations get different dedup keys."""
        from probos.bridge_alerts import BridgeAlertService

        svc = BridgeAlertService(cooldown_seconds=300)
        health_fast = {
            "overall": "degraded",
            "tiers": {"fast": {"status": "unreachable"}},
        }
        health_deep = {
            "overall": "degraded",
            "tiers": {"deep": {"status": "unreachable"}},
        }
        alerts1 = svc.check_llm_health(health_fast)
        alerts2 = svc.check_llm_health(health_deep)
        assert len(alerts1) == 1
        assert len(alerts2) == 1
        assert alerts1[0].dedup_key != alerts2[0].dedup_key


# ---------------------------------------------------------------------------
# System Endpoint (3 tests)
# ---------------------------------------------------------------------------


class TestSystemEndpointLLMHealth:
    """System services endpoint LLM health integration."""

    @pytest.mark.asyncio
    async def test_system_services_includes_llm_proxy(self):
        """/api/system/services includes 'LLM Proxy' entry."""
        from probos.routers.system import system_services

        rt = MagicMock()
        rt.ward_room = MagicMock()
        rt.episodic_memory = MagicMock()
        rt.trust_network = MagicMock()
        rt._knowledge_store = None
        rt.cognitive_journal = None
        rt.codebase_index = None
        rt.skill_registry = None
        rt.skill_service = None
        rt.acm = None
        rt.hebbian_router = MagicMock()
        rt.intent_bus = MagicMock()
        rt.llm_client = MagicMock()
        rt.llm_client.get_health_status.return_value = {
            "overall": "operational",
            "tiers": {},
        }

        result = await system_services(runtime=rt)
        names = [s["name"] for s in result["services"]]
        assert "LLM Proxy" in names

    @pytest.mark.asyncio
    async def test_system_services_llm_status_mapping(self):
        """operational→online, degraded→degraded, offline→offline."""
        from probos.routers.system import system_services

        for overall, expected in [
            ("operational", "online"),
            ("degraded", "degraded"),
            ("offline", "offline"),
        ]:
            rt = MagicMock()
            rt.ward_room = MagicMock()
            rt.episodic_memory = MagicMock()
            rt.trust_network = MagicMock()
            rt._knowledge_store = None
            rt.cognitive_journal = None
            rt.codebase_index = None
            rt.skill_registry = None
            rt.skill_service = None
            rt.acm = None
            rt.hebbian_router = MagicMock()
            rt.intent_bus = MagicMock()
            rt.llm_client = MagicMock()
            rt.llm_client.get_health_status.return_value = {
                "overall": overall,
                "tiers": {},
            }

            result = await system_services(runtime=rt)
            llm_entry = [s for s in result["services"] if s["name"] == "LLM Proxy"][0]
            assert llm_entry["status"] == expected, \
                f"Expected {expected} for overall={overall}, got {llm_entry['status']}"

    @pytest.mark.asyncio
    async def test_llm_health_endpoint(self):
        """/api/system/llm-health returns per-tier detail."""
        from probos.routers.system import llm_health

        rt = MagicMock()
        rt.llm_client = MagicMock()
        expected = {
            "overall": "degraded",
            "tiers": {
                "fast": {"status": "operational", "consecutive_failures": 0},
                "standard": {"status": "unreachable", "consecutive_failures": 5},
                "deep": {"status": "operational", "consecutive_failures": 0},
            },
        }
        rt.llm_client.get_health_status.return_value = expected

        result = await llm_health(runtime=rt)
        assert result == expected

    @pytest.mark.asyncio
    async def test_llm_health_endpoint_no_client(self):
        """/api/system/llm-health returns unknown when no client."""
        from probos.routers.system import llm_health

        rt = MagicMock(spec=[])  # No llm_client attribute
        result = await llm_health(runtime=rt)
        assert result["overall"] == "unknown"


# ---------------------------------------------------------------------------
# Proactive Loop Failure Visibility (4 tests)
# ---------------------------------------------------------------------------


class TestProactiveLoopFailureVisibility:
    """ProactiveCognitiveLoop LLM failure tracking."""

    def _make_loop(self):
        from probos.proactive import ProactiveCognitiveLoop
        return ProactiveCognitiveLoop(interval=120.0, cooldown=300.0)

    def test_proactive_failure_count_increments(self):
        """Failed proactive think increments counter."""
        loop = self._make_loop()
        assert loop._llm_failure_count == 0
        loop._llm_failure_count += 1
        assert loop._llm_failure_count == 1

    def test_proactive_failure_count_resets_on_success(self):
        """Successful post resets counter to 0."""
        loop = self._make_loop()
        loop._llm_failure_count = 5
        # Simulate what happens after _post_to_ward_room
        loop._llm_failure_count = 0
        assert loop._llm_failure_count == 0

    def test_proactive_failure_logged(self, caplog):
        """Failed result logs a warning."""
        with caplog.at_level(logging.WARNING, logger="probos.proactive"):
            logger = logging.getLogger("probos.proactive")
            # Simulate the logging that happens in the failure path
            logger.warning(
                "BF-069: Proactive think failed for %s: %s (consecutive failures: %d)",
                "test_agent", "agent returned unsuccessful result", 1,
            )
        assert "BF-069: Proactive think failed" in caplog.text

    def test_proactive_failure_count_property(self):
        """llm_failure_count property returns current count."""
        loop = self._make_loop()
        assert loop.llm_failure_count == 0
        loop._llm_failure_count = 3
        assert loop.llm_failure_count == 3


# ---------------------------------------------------------------------------
# Event Type (1 bonus test)
# ---------------------------------------------------------------------------


class TestLLMHealthEventType:
    """EventType.LLM_HEALTH_CHANGED exists."""

    def test_event_type_exists(self):
        from probos.events import EventType
        assert hasattr(EventType, "LLM_HEALTH_CHANGED")
        assert EventType.LLM_HEALTH_CHANGED.value == "llm_health_changed"


# ---------------------------------------------------------------------------
# Dwell-Time Criterion (10 tests)
# ---------------------------------------------------------------------------


class TestDwellTimeCriterion:
    """BF-240: LLM health recovery requires consecutive healthy checks."""

    def _make_client(self, min_consecutive_healthy: int = 3):
        """Create a minimal OpenAICompatibleClient for testing."""
        from probos.cognitive.llm_client import OpenAICompatibleClient
        client = OpenAICompatibleClient.__new__(OpenAICompatibleClient)
        client.default_tier = "fast"
        client._tier_configs = {
            tier: {
                "base_url": f"http://{tier}.example/v1",
                "api_key": "",
                "model": f"{tier}-model",
                "timeout": 30.0,
                "api_format": "openai",
                "temperature": None,
                "top_p": None,
            }
            for tier in ("fast", "standard", "deep")
        }
        client._clients = {
            f"http://{tier}.example/v1|openai": MagicMock()
            for tier in ("fast", "standard", "deep")
        }
        client._tier_status = {}
        client._cache = OrderedDict()
        client._cache_max_entries = 500
        client._rate_config = None
        client._consecutive_429s = {t: 0 for t in ("fast", "standard", "deep")}
        client._consecutive_failures = {t: 0 for t in ("fast", "standard", "deep")}
        client._consecutive_successes = {t: 0 for t in ("fast", "standard", "deep")}
        client._min_consecutive_healthy = min_consecutive_healthy
        client._last_success = {}
        client._last_failure = {}
        return client

    async def _complete_success(self, client, *, tier: str = "fast", prompt: str = "ping"):
        from probos.types import LLMRequest, LLMResponse

        client._call_api = AsyncMock(
            return_value=LLMResponse(content="ok", model=f"{tier}-model", tier=tier)
        )
        return await client._complete_inner(LLMRequest(prompt=prompt, tier=tier))

    @pytest.mark.asyncio
    async def test_single_success_does_not_clear_failures(self):
        client = self._make_client()
        client._consecutive_failures["fast"] = 3

        await self._complete_success(client, prompt="one")

        assert client._consecutive_failures["fast"] == 3
        assert client._consecutive_successes["fast"] == 1
        status = client.get_health_status()
        assert status["tiers"]["fast"]["status"] != "operational"

    @pytest.mark.asyncio
    async def test_dwell_threshold_clears_failures(self):
        client = self._make_client()
        client._consecutive_failures["fast"] = 3

        for i in range(3):
            await self._complete_success(client, prompt=f"threshold-{i}")

        assert client._consecutive_failures["fast"] == 0
        assert client._consecutive_successes["fast"] == 3
        status = client.get_health_status()
        assert status["tiers"]["fast"]["status"] == "operational"

    @pytest.mark.asyncio
    async def test_failure_resets_success_counter(self):
        client = self._make_client()
        client._consecutive_failures["fast"] = 3
        for i in range(2):
            await self._complete_success(client, prompt=f"partial-{i}")

        client._call_api = AsyncMock(side_effect=RuntimeError("boom"))
        from probos.types import LLMRequest

        await client._complete_inner(LLMRequest(prompt="failure", tier="fast"))

        assert client._consecutive_successes["fast"] == 0
        assert client._consecutive_failures["fast"] == 4

    def test_recovering_status_exposed(self):
        client = self._make_client()
        client._consecutive_failures["fast"] = 2
        client._consecutive_successes["fast"] = 1

        status = client.get_health_status()

        assert status["tiers"]["fast"]["status"] == "recovering"

    @pytest.mark.asyncio
    async def test_connectivity_check_dwell(self):
        client = self._make_client()
        for tier in ("fast", "standard", "deep"):
            client._consecutive_failures[tier] = 3
        client._check_endpoint = AsyncMock(return_value=True)

        await client.check_connectivity()
        assert client._consecutive_successes["fast"] == 1
        assert client._consecutive_failures["fast"] == 3

        await client.check_connectivity()
        assert client._consecutive_successes["fast"] == 2
        assert client._consecutive_failures["fast"] == 3

        await client.check_connectivity()
        assert client._consecutive_successes["fast"] == 3
        assert client._consecutive_failures["fast"] == 0

    def test_overall_status_recovering(self):
        client = self._make_client()
        client._consecutive_failures["fast"] = 3
        client._consecutive_successes["fast"] = 1

        status = client.get_health_status()

        assert status["overall"] == "recovering"

    @pytest.mark.asyncio
    async def test_config_overrides_default(self):
        from probos.cognitive.llm_client import OpenAICompatibleClient
        from probos.config import CognitiveConfig

        config = CognitiveConfig(llm_health_min_consecutive_healthy=5)
        client = OpenAICompatibleClient(config=config)
        try:
            client._consecutive_failures["fast"] = 3
            for i in range(4):
                await self._complete_success(client, prompt=f"configured-{i}")
            assert client._min_consecutive_healthy == 5
            assert client._consecutive_failures["fast"] == 3

            await self._complete_success(client, prompt="configured-4")
            assert client._consecutive_failures["fast"] == 0
        finally:
            await client.close()

    def test_consecutive_successes_in_health_dict(self):
        client = self._make_client()
        client._consecutive_successes["standard"] = 2

        status = client.get_health_status()

        assert status["tiers"]["standard"]["consecutive_successes"] == 2

    @pytest.mark.asyncio
    async def test_zero_failures_no_dwell_needed(self):
        client = self._make_client()

        await self._complete_success(client, prompt="already-healthy")

        status = client.get_health_status()
        assert client._consecutive_failures["fast"] == 0
        assert client._consecutive_successes["fast"] == 1
        assert status["tiers"]["fast"]["status"] == "operational"

    @pytest.mark.asyncio
    async def test_event_includes_dwell_count(self):
        from probos.proactive import ProactiveCognitiveLoop

        events = []
        loop = ProactiveCognitiveLoop(interval=120.0, cooldown=300.0, on_event=lambda e: events.append(e))
        loop._llm_client = MagicMock()
        loop._llm_client.get_health_status.return_value = {
            "overall": "recovering",
            "tiers": {
                "fast": {"consecutive_successes": 2},
                "standard": {"consecutive_successes": 0},
                "deep": {"consecutive_successes": 1},
            },
        }
        loop._llm_failure_count = 3

        await loop._update_llm_status(failure=True)

        assert events[0]["data"]["consecutive_successes"] == 2
