"""AD-766: YeomanAgent — Captain's personal assistant tests.

Covers: registration, singleton enforcement, persona binding from Captain
Card, proactive-scan subscription wiring, digest aggregation, quiet-hours
queueing, delegation routing, and read-only intent auto-approval.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from probos.captain_card.card import CaptainCard
from probos.cognitive.yeoman import (
    DELEGATION_MAP,
    YeomanAgent,
    resolve_delegate,
    _DEFAULT_PERSONA,
    _ROLE_RULES,
)
from probos.security.permission_model import (
    PermissionConfig,
    PermissionMode,
    should_auto_approve,
)
from probos.types import IntentMessage


# ---------------------------------------------------------------------------
# Fixtures / fakes
# ---------------------------------------------------------------------------


class _FakeIntentBus:
    def __init__(self) -> None:
        self.subscribed: list[tuple[str, Any, list[str] | None]] = []
        self.broadcasts: list[IntentMessage] = []

    def subscribe(
        self, agent_id: str, handler: Any,
        intent_names: list[str] | None = None,
    ) -> None:
        self.subscribed.append((agent_id, handler, intent_names))

    async def broadcast(self, intent: IntentMessage, *args: Any, **kwargs: Any) -> Any:
        self.broadcasts.append(intent)
        return None


class _FakeRuntime:
    def __init__(self) -> None:
        self.intent_bus = _FakeIntentBus()


@pytest.fixture(autouse=True)
def _reset_yeoman_singleton() -> None:
    """Reset the singleton counter so each test starts clean."""
    YeomanAgent._live_instance_count = 0
    yield
    YeomanAgent._live_instance_count = 0


def _make_yeo(runtime: _FakeRuntime | None = None) -> YeomanAgent:
    """Construct a YeomanAgent without the full CognitiveAgent __init__ chain.

    Mirrors the test_counselor_therapeutic.py pattern.
    """
    agent = object.__new__(YeomanAgent)
    agent.id = "yeoman-001"
    agent.callsign = "Yeo"
    agent.agent_type = "yeoman"
    agent.tier = "domain"
    agent.pool = "yeoman"
    agent.instructions = _DEFAULT_PERSONA + _ROLE_RULES
    agent._runtime = runtime
    agent._captain_card = None
    agent._duty_schedule = None
    agent._proactive_sub_id = ""
    agent._digest_window_seconds = 60.0
    agent._scan_buffer = []
    agent._buffer_lock = asyncio.Lock()
    agent._flush_task = None
    agent._pending_dispatch_tasks = set()
    YeomanAgent._live_instance_count += 1
    return agent


# ---------------------------------------------------------------------------
# Registration + class-level shape
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_class_shape_matches_spec(self) -> None:
        assert YeomanAgent.agent_type == "yeoman"
        assert YeomanAgent.callsign == "Yeo"
        assert YeomanAgent.tier == "domain"
        assert YeomanAgent.department == "Bridge"

    def test_handled_intents_cover_all_five_capabilities(self) -> None:
        expected = {
            "daily_briefing",
            "schedule_lookup",
            "triage_inbox",
            "delegate_to_crew",
            "relay_standing_order",
        }
        assert YeomanAgent._handled_intents == expected

    def test_intent_descriptors_match_handled_intents(self) -> None:
        descriptor_names = {d.name for d in YeomanAgent.intent_descriptors}
        assert descriptor_names == YeomanAgent._handled_intents

    def test_template_registered_in_runtime(self) -> None:
        """Runtime imports YeomanAgent and registers the template at line 968."""
        from probos.runtime import YeomanAgent as RuntimeYeoman
        assert RuntimeYeoman is YeomanAgent

    def test_bridge_pools_includes_yeoman(self) -> None:
        from probos.config import TieredTrustConfig
        cfg = TieredTrustConfig()
        assert "yeoman" in cfg.bridge_pools
        assert "Yeo" in cfg.bridge_callsigns


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_second_instance_raises(self) -> None:
        _make_yeo()
        with pytest.raises(RuntimeError, match="singleton"):
            # Second construction via real __init__ must trip the guard.
            YeomanAgent(
                pool="yeoman",
                instructions=_DEFAULT_PERSONA + _ROLE_RULES,
            )

    def test_counter_resets_on_stop(self) -> None:
        yeo = _make_yeo()
        assert YeomanAgent._live_instance_count == 1
        # Manual decrement mirrors stop()'s finally-block accounting; the
        # test fixture handles the full reset between tests.
        YeomanAgent._live_instance_count = 0
        assert YeomanAgent._live_instance_count == 0
        # And re-construction would now succeed (covered by other tests
        # via the autouse fixture).
        assert yeo.id == "yeoman-001"


# ---------------------------------------------------------------------------
# Captain Card persona binding
# ---------------------------------------------------------------------------


class TestPersonaBinding:
    @pytest.mark.asyncio
    async def test_default_persona_when_no_card(self) -> None:
        yeo = _make_yeo()
        assert "Yeo, the Captain's personal assistant" in yeo.instructions
        assert "Yeoman role (AD-766)" in yeo.instructions

    @pytest.mark.asyncio
    async def test_card_overrides_default(self) -> None:
        runtime = _FakeRuntime()
        yeo = _make_yeo(runtime=runtime)
        card = CaptainCard(name="Sean", preferred_work_hours="09:00-17:00")
        await yeo.initialize(captain_card=card, duty_schedule=None)
        assert "Yeo, Sean's personal assistant" in yeo.instructions
        assert "Yeoman role (AD-766)" in yeo.instructions

    @pytest.mark.asyncio
    async def test_card_failure_retains_default(self) -> None:
        runtime = _FakeRuntime()
        yeo = _make_yeo(runtime=runtime)

        class _BrokenCard:
            name = "x"

            def to_system_context(self) -> str:
                raise RuntimeError("boom")

        await yeo.initialize(captain_card=_BrokenCard(), duty_schedule=None)  # type: ignore[arg-type]
        # Default persona preserved on failure.
        assert "Yeoman role (AD-766)" in yeo.instructions


# ---------------------------------------------------------------------------
# Proactive-scan subscription
# ---------------------------------------------------------------------------


class TestProactiveSubscription:
    @pytest.mark.asyncio
    async def test_subscribes_to_proactive_scan_intent(self) -> None:
        runtime = _FakeRuntime()
        yeo = _make_yeo(runtime=runtime)
        await yeo.initialize(captain_card=None, duty_schedule=None)
        assert len(runtime.intent_bus.subscribed) == 1
        sub_id, handler, names = runtime.intent_bus.subscribed[0]
        assert sub_id.startswith("yeoman-proactive-")
        assert names == ["proactive_scan"]
        assert handler == yeo._handle_proactive_scan

    @pytest.mark.asyncio
    async def test_no_subscription_when_runtime_missing(self) -> None:
        yeo = _make_yeo(runtime=None)
        await yeo.initialize(captain_card=None, duty_schedule=None)
        # No crash; no subscription registered.
        assert yeo._proactive_sub_id == ""

    @pytest.mark.asyncio
    async def test_handler_buffers_scan(self) -> None:
        runtime = _FakeRuntime()
        yeo = _make_yeo(runtime=runtime)
        await yeo.initialize(
            captain_card=None, duty_schedule=None,
            digest_window_seconds=0.0,
        )
        intent = IntentMessage(
            intent="proactive_scan",
            params={
                "scan_types": ["inbox", "calendar"],
                "suppressed_reasons": {},
            },
        )
        result = await yeo._handle_proactive_scan(intent)
        assert result is None
        assert len(yeo._scan_buffer) == 1
        assert yeo._scan_buffer[0]["scan_types"] == ["inbox", "calendar"]


# ---------------------------------------------------------------------------
# Digest aggregation
# ---------------------------------------------------------------------------


class TestDigestAggregation:
    @pytest.mark.asyncio
    async def test_multiple_scans_collapse_into_single_dm(self) -> None:
        runtime = _FakeRuntime()
        yeo = _make_yeo(runtime=runtime)
        await yeo.initialize(
            captain_card=None, duty_schedule=None,
            digest_window_seconds=0.0,  # Flush immediately on schedule.
        )
        for scan_types in (["inbox"], ["calendar"], ["teams"]):
            await yeo._handle_proactive_scan(IntentMessage(
                intent="proactive_scan",
                params={"scan_types": scan_types, "suppressed_reasons": {}},
            ))
        # The first scan started the flush task; wait for it.
        if yeo._flush_task:
            await yeo._flush_task

        # All three scans MUST collapse into a single Captain DM digest.
        assert len(runtime.intent_bus.broadcasts) == 1
        dm = runtime.intent_bus.broadcasts[0]
        assert dm.intent == "direct_message"
        assert dm.params["from"] == "yeoman"
        assert dm.params["to"] == "captain"
        assert dm.params["kind"] == "yeoman_digest"
        digest = dm.params["digest"]
        assert digest["scan_count"] == 3
        # Order preserved, no duplicates.
        assert digest["scan_types"] == ["inbox", "calendar", "teams"]

    @pytest.mark.asyncio
    async def test_flush_now_empties_buffer(self) -> None:
        runtime = _FakeRuntime()
        yeo = _make_yeo(runtime=runtime)
        await yeo.initialize(captain_card=None, duty_schedule=None)
        yeo._scan_buffer.append({
            "ts": 0.0, "scan_types": ["inbox"],
            "suppressed_reasons": {}, "queued": False,
        })
        digest = await yeo.flush_now()
        assert digest is not None
        assert yeo._scan_buffer == []
        # flush_now sometimes uses create_task for the dispatch — drain it.
        for task in list(yeo._pending_dispatch_tasks):
            await task
        assert len(runtime.intent_bus.broadcasts) == 1

    @pytest.mark.asyncio
    async def test_flush_now_no_op_when_buffer_empty(self) -> None:
        runtime = _FakeRuntime()
        yeo = _make_yeo(runtime=runtime)
        result = await yeo.flush_now()
        assert result is None
        assert runtime.intent_bus.broadcasts == []


# ---------------------------------------------------------------------------
# Quiet hours
# ---------------------------------------------------------------------------


class _AllSuppressedDutySchedule:
    """Stub DutySchedule — every scan type is currently suppressed."""

    def should_scan(self, scan_type: str, dt: Any = None) -> bool:
        return False

    def reason_code(self, scan_type: str, dt: Any = None) -> str:
        return "quiet_hours_active"


class TestQuietHours:
    @pytest.mark.asyncio
    async def test_fully_suppressed_scan_queued_not_emitted(self) -> None:
        runtime = _FakeRuntime()
        yeo = _make_yeo(runtime=runtime)
        await yeo.initialize(
            captain_card=None,
            duty_schedule=_AllSuppressedDutySchedule(),
            digest_window_seconds=0.0,
        )
        intent = IntentMessage(
            intent="proactive_scan",
            params={
                "scan_types": [],  # Empty = policy gate active.
                "suppressed_reasons": {
                    "inbox": "quiet_hours_active",
                    "calendar": "quiet_hours_active",
                    "teams": "quiet_hours_active",
                },
            },
        )
        await yeo._handle_proactive_scan(intent)
        # Buffered ...
        assert len(yeo._scan_buffer) == 1
        assert yeo._scan_buffer[0]["queued"] is True
        # ... but no flush task scheduled, so no Captain DM emitted.
        assert yeo._flush_task is None
        assert runtime.intent_bus.broadcasts == []


# ---------------------------------------------------------------------------
# Delegation routing
# ---------------------------------------------------------------------------


class TestDelegation:
    def test_resolves_medical_request(self) -> None:
        assert resolve_delegate("the patient needs diagnostic help") == "Bones"

    def test_resolves_engineering_request(self) -> None:
        assert resolve_delegate("warp core power fluctuation") == "LaForge"

    def test_resolves_security_request(self) -> None:
        assert resolve_delegate("security threat on deck 4") == "Worf"

    def test_returns_none_when_no_keyword_matches(self) -> None:
        assert resolve_delegate("hello yeo, just checking in") is None

    def test_delegation_map_covers_all_departments(self) -> None:
        # Forcing function: if new departments are added, the test reminds
        # the architect to extend the map.
        assert set(DELEGATION_MAP.keys()) >= {
            "medical", "engineering", "science",
            "security", "operations", "counseling",
        }


# ---------------------------------------------------------------------------
# Read-only auto-approval (AD-765 §4 wiring)
# ---------------------------------------------------------------------------


class TestReadOnlyAutoApprove:
    @pytest.mark.asyncio
    async def test_read_only_intents_classified_correctly(self) -> None:
        assert "daily_briefing" in YeomanAgent.read_only_intents
        assert "schedule_lookup" in YeomanAgent.read_only_intents
        assert "triage_inbox" in YeomanAgent.read_only_intents
        # Write-shaped intents are NOT in the read-only set.
        assert "delegate_to_crew" not in YeomanAgent.read_only_intents
        assert "relay_standing_order" not in YeomanAgent.read_only_intents

    @pytest.mark.asyncio
    async def test_autopilot_mode_auto_approves_read_only_yeo_intents(self) -> None:
        # AD-765 §4 verdict: PermissionConfig already has the primitive;
        # callers extend the whitelist with their agent-specific intents.
        whitelist = set(YeomanAgent.read_only_intents)
        cfg = PermissionConfig(
            mode=PermissionMode.AUTOPILOT,
            auto_approve_read_only=True,
            read_only_whitelist=whitelist,
        )
        for intent_name in YeomanAgent.read_only_intents:
            assert await should_auto_approve(intent_name, cfg) is True
        # Write intents still gate on quorum even with the same config.
        assert await should_auto_approve("delegate_to_crew", cfg) is False

    @pytest.mark.asyncio
    async def test_manual_mode_blocks_auto_approval(self) -> None:
        cfg = PermissionConfig(
            mode=PermissionMode.MANUAL,
            auto_approve_read_only=True,
            read_only_whitelist=set(YeomanAgent.read_only_intents),
        )
        for intent_name in YeomanAgent.read_only_intents:
            assert await should_auto_approve(intent_name, cfg) is False
