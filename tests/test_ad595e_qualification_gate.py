"""AD-595e: Qualification Gate Enforcement — 16 tests.

Tests qualification gates at three pipeline points:
- BillRuntime step start (6 tests)
- ProactiveCognitiveLoop duty dispatch (4 tests)
- CognitiveAgent context injection (3 tests)
- Event emission (3 tests)
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.events import EventType
from probos.sop.runtime import BillRuntime
from probos.sop.schema import BillDefinition, BillRole, BillStep
from probos.sop.instance import StepStatus


# ── Helpers ──────────────────────────────────────────────────────────


def _make_bill() -> BillDefinition:
    """Minimal BillDefinition for gate tests."""
    return BillDefinition(
        bill="gate-test",
        title="Gate Test",
        roles={"lead": BillRole(id="lead", department="engineering")},
        steps=[BillStep(id="step-1", name="Test step", role="lead", action="cognitive_skill")],
    )


def _make_qual_config(*, enabled=False, log_only=True):
    """Create a mock QualificationConfig with enforcement fields."""
    cfg = MagicMock()
    cfg.enforcement_enabled = enabled
    cfg.enforcement_log_only = log_only
    return cfg


def _make_billet_registry(*, qualified=True, missing=None):
    """Create a mock BilletRegistry with full activation support + qualification gate."""
    reg = MagicMock()

    # Qualification standing (AD-595e gate)
    standing = {
        "qualified": qualified,
        "standing": "qualified" if qualified else "deficient",
        "missing": missing or [],
        "pass_rate": 1.0 if qualified else 0.5,
    }
    reg.get_qualification_standing = AsyncMock(return_value=standing)
    reg.check_role_qualifications = AsyncMock(return_value=(qualified, missing or []))

    # Activation support (WQSB role assignment needs roster)
    holders = [
        _make_billet_holder("eng-1", "Engineer", "engineering", "agent-forge", "engineering_officer", "Forge"),
        _make_billet_holder("sci-1", "Scientist", "science", "agent-atlas", "science_officer", "Atlas"),
    ]
    reg.get_roster.return_value = holders
    reg.get_department_roster.side_effect = lambda dept: [
        h for h in holders if h.department == dept
    ]
    reg.check_qualifications = AsyncMock(return_value=(True, []))

    return reg


def _make_billet_holder(billet_id, title, department, agent_id, agent_type, callsign):
    """Create a mock BilletHolder."""
    bh = MagicMock()
    bh.billet_id = billet_id
    bh.title = title
    bh.department = department
    bh.holder_agent_id = agent_id
    bh.holder_agent_type = agent_type
    bh.holder_callsign = callsign
    return bh


def _make_runtime(*, qual_config=None, billet_registry=None):
    """Create BillRuntime with optional qualification config."""
    events: list[tuple] = []
    rt = BillRuntime(
        billet_registry=billet_registry,
        emit_event_fn=lambda et, d: events.append((et, d)),
    )
    if qual_config:
        rt.set_qualification_config(qual_config)
    return rt, events


# ===========================================================================
# 1. BillRuntime gate (6 tests)
# ===========================================================================


class TestBillRuntimeGate:
    """Tests for qualification gate at bill step start."""

    @pytest.mark.asyncio
    async def test_gate_disabled_allows_step(self):
        """When enforcement_enabled=False, step starts normally."""
        reg = _make_billet_registry(qualified=True)
        rt, events = _make_runtime(billet_registry=reg)
        bill = _make_bill()
        inst = await rt.activate(bill)

        result = await rt.start_step(inst.id, "step-1", "agent-forge")
        assert result is True
        assert inst.step_states["step-1"].status == StepStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_gate_no_quals_allows_step(self):
        """When agent is qualified, step starts normally."""
        reg = _make_billet_registry(qualified=True)
        cfg = _make_qual_config(enabled=True, log_only=False)
        rt, events = _make_runtime(qual_config=cfg, billet_registry=reg)
        bill = _make_bill()
        inst = await rt.activate(bill)

        result = await rt.start_step(inst.id, "step-1", "agent-forge")
        assert result is True

    @pytest.mark.asyncio
    async def test_gate_blocked_rejects_step(self):
        """When agent is NOT qualified and enforcement is active, step is blocked."""
        reg = _make_billet_registry(qualified=False, missing=["nav_proficiency"])
        cfg = _make_qual_config(enabled=True, log_only=False)
        rt, events = _make_runtime(qual_config=cfg, billet_registry=reg)
        bill = _make_bill()
        inst = await rt.activate(bill)

        result = await rt.start_step(inst.id, "step-1", "agent-forge")
        assert result is False
        assert inst.step_states["step-1"].status == StepStatus.PENDING

    @pytest.mark.asyncio
    async def test_gate_shadow_logs_but_allows(self):
        """Shadow mode (log_only=True): logs gate event but allows step."""
        reg = _make_billet_registry(qualified=False, missing=["nav_proficiency"])
        cfg = _make_qual_config(enabled=True, log_only=True)
        rt, events = _make_runtime(qual_config=cfg, billet_registry=reg)
        bill = _make_bill()
        inst = await rt.activate(bill)

        result = await rt.start_step(inst.id, "step-1", "agent-forge")
        assert result is True  # Shadow — allowed
        assert inst.step_states["step-1"].status == StepStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_gate_no_store_allows(self):
        """When enforcement is enabled but billet_registry has no qualification store,
        gate degrades to ALLOW."""
        reg = _make_billet_registry(qualified=True)
        # Override get_qualification_standing to return "unknown" standing
        reg.get_qualification_standing = AsyncMock(return_value={
            "qualified": True, "standing": "unknown", "missing": [], "pass_rate": 1.0,
        })
        cfg = _make_qual_config(enabled=True, log_only=False)
        rt, events = _make_runtime(qual_config=cfg, billet_registry=reg)
        bill = _make_bill()
        inst = await rt.activate(bill)

        result = await rt.start_step(inst.id, "step-1", "agent-forge")
        assert result is True

    @pytest.mark.asyncio
    async def test_gate_exception_allows(self):
        """When qualification check raises, gate degrades to ALLOW."""
        reg = _make_billet_registry(qualified=True)
        # Override to raise on gate check but not on activation
        reg.get_qualification_standing = AsyncMock(side_effect=RuntimeError("db error"))
        cfg = _make_qual_config(enabled=True, log_only=False)
        rt, events = _make_runtime(qual_config=cfg, billet_registry=reg)
        bill = _make_bill()
        inst = await rt.activate(bill)

        result = await rt.start_step(inst.id, "step-1", "agent-forge")
        assert result is True  # Graceful degradation


# ===========================================================================
# 2. ProactiveCognitiveLoop gate (4 tests)
# ===========================================================================


class TestProactiveDutyGate:
    """Tests for qualification gate at proactive duty dispatch."""

    def _make_loop(self, *, qual_config=None, billet_registry=None):
        from probos.proactive import ProactiveCognitiveLoop
        loop = ProactiveCognitiveLoop(interval=999, cooldown=999)
        if qual_config:
            loop.set_qualification_config(qual_config)
        if billet_registry:
            loop.set_billet_registry(billet_registry)
        return loop

    @pytest.mark.asyncio
    async def test_gate_disabled_allows_duty(self):
        """When enforcement_enabled=False, duty dispatch proceeds."""
        loop = self._make_loop()
        agent = MagicMock()
        agent.id = "test-agent"
        agent.agent_type = "wesley"
        duty = MagicMock()
        duty.duty_id = "duty-1"

        result = await loop._check_duty_qualification(agent, duty)
        assert result is True  # True = allowed

    @pytest.mark.asyncio
    async def test_gate_blocked_rejects_duty(self):
        """When agent is NOT qualified and enforcement active, returns False."""
        reg = _make_billet_registry(qualified=False, missing=["systems_analysis"])
        cfg = _make_qual_config(enabled=True, log_only=False)
        loop = self._make_loop(qual_config=cfg, billet_registry=reg)
        loop._on_event = MagicMock()

        agent = MagicMock()
        agent.id = "test-agent"
        agent.agent_type = "science_officer"
        duty = MagicMock()
        duty.duty_id = "duty-1"

        result = await loop._check_duty_qualification(agent, duty)
        assert result is False  # Blocked

    @pytest.mark.asyncio
    async def test_gate_shadow_allows_duty(self):
        """Shadow mode: logs but allows duty dispatch."""
        reg = _make_billet_registry(qualified=False, missing=["systems_analysis"])
        cfg = _make_qual_config(enabled=True, log_only=True)
        loop = self._make_loop(qual_config=cfg, billet_registry=reg)
        loop._on_event = MagicMock()

        agent = MagicMock()
        agent.id = "test-agent"
        agent.agent_type = "science_officer"
        duty = MagicMock()
        duty.duty_id = "duty-1"

        result = await loop._check_duty_qualification(agent, duty)
        assert result is True  # Shadow — allowed

    @pytest.mark.asyncio
    async def test_gate_no_registry_allows(self):
        """When no billet_registry, gate degrades to ALLOW."""
        cfg = _make_qual_config(enabled=True, log_only=False)
        loop = self._make_loop(qual_config=cfg, billet_registry=None)

        agent = MagicMock()
        agent.id = "test-agent"
        agent.agent_type = "science_officer"
        duty = MagicMock()
        duty.duty_id = "duty-1"

        result = await loop._check_duty_qualification(agent, duty)
        assert result is True  # No registry — allow


# ===========================================================================
# 3. CognitiveAgent context injection (3 tests)
# ===========================================================================


class TestCognitiveAgentContext:
    """Tests for qualification standing injection in decide()."""

    def test_standing_fields_initialized(self):
        """CognitiveAgent has qualification standing cache fields."""
        from probos.cognitive.cognitive_agent import CognitiveAgent
        agent = CognitiveAgent(
            agent_type="test_agent",
            instructions="Test.",
        )
        assert agent._qualification_standing is None
        assert agent._qualification_standing_ts == 0.0
        assert agent._qualification_standing_ttl == 300.0

    @pytest.mark.asyncio
    async def test_standing_injected_into_observation(self):
        """When standing is available, it's injected into observation."""
        from probos.cognitive.cognitive_agent import CognitiveAgent

        agent = CognitiveAgent(
            agent_type="test_agent",
            instructions="Test.",
        )
        agent.id = "test-agent-id"
        agent._qualification_standing = {
            "qualified": True,
            "standing": "qualified",
            "missing": [],
            "pass_rate": 1.0,
        }
        agent._qualification_standing_ts = time.monotonic()

        # Mock the LLM client with AsyncMock for complete()
        llm = MagicMock()
        llm.complete = AsyncMock(return_value='{"action": "none"}')
        agent._llm_client = llm

        # Mock refresh to avoid real lookups
        agent._refresh_qualification_standing = AsyncMock()

        obs = {"intent": "proactive_think", "params": {}}
        try:
            await agent.decide(obs)
        except Exception:
            pass  # May fail on response parsing — we only care about injection

        # Verify standing was injected into observation
        assert "qualification_standing" in obs

    @pytest.mark.asyncio
    async def test_standing_not_injected_when_none(self):
        """When no standing cached, observation is not modified."""
        from probos.cognitive.cognitive_agent import CognitiveAgent

        agent = CognitiveAgent(
            agent_type="test_agent",
            instructions="Test.",
        )
        agent.id = "test-agent-id"
        agent._qualification_standing = None

        llm = MagicMock()
        llm.complete = AsyncMock(return_value='{"action": "none"}')
        agent._llm_client = llm
        agent._refresh_qualification_standing = AsyncMock()

        obs = {"intent": "proactive_think", "params": {}}
        try:
            await agent.decide(obs)
        except Exception:
            pass

        assert "qualification_standing" not in obs


# ===========================================================================
# 4. Event emission (3 tests)
# ===========================================================================


class TestEventEmission:
    """Tests for QUALIFICATION_GATE_BLOCKED event emission."""

    @pytest.mark.asyncio
    async def test_bill_gate_emits_event(self):
        """Blocked bill step emits QUALIFICATION_GATE_BLOCKED."""
        reg = _make_billet_registry(qualified=False, missing=["nav_proficiency"])
        cfg = _make_qual_config(enabled=True, log_only=True)  # shadow mode
        rt, events = _make_runtime(qual_config=cfg, billet_registry=reg)
        bill = _make_bill()
        inst = await rt.activate(bill)

        await rt.start_step(inst.id, "step-1", "agent-forge", agent_type="nav_officer")

        gate_events = [e for e in events if e[0] == EventType.QUALIFICATION_GATE_BLOCKED]
        assert len(gate_events) == 1
        assert gate_events[0][1]["gate"] == "bill_step"
        assert gate_events[0][1]["missing"] == ["nav_proficiency"]

    @pytest.mark.asyncio
    async def test_event_log_only_true(self):
        """Event payload includes log_only=True in shadow mode."""
        reg = _make_billet_registry(qualified=False, missing=["nav_proficiency"])
        cfg = _make_qual_config(enabled=True, log_only=True)
        rt, events = _make_runtime(qual_config=cfg, billet_registry=reg)
        bill = _make_bill()
        inst = await rt.activate(bill)

        await rt.start_step(inst.id, "step-1", "agent-forge")

        gate_events = [e for e in events if e[0] == EventType.QUALIFICATION_GATE_BLOCKED]
        assert gate_events[0][1]["log_only"] is True

    @pytest.mark.asyncio
    async def test_event_log_only_false(self):
        """Event payload includes log_only=False in active enforcement."""
        reg = _make_billet_registry(qualified=False, missing=["nav_proficiency"])
        cfg = _make_qual_config(enabled=True, log_only=False)
        rt, events = _make_runtime(qual_config=cfg, billet_registry=reg)
        bill = _make_bill()
        inst = await rt.activate(bill)

        await rt.start_step(inst.id, "step-1", "agent-forge")

        gate_events = [e for e in events if e[0] == EventType.QUALIFICATION_GATE_BLOCKED]
        assert gate_events[0][1]["log_only"] is False
