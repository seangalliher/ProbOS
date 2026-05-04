"""AD-660 v1: Agent Causal Reasoning Framework — focused unit tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from probos.cognitive.causal_reasoning import (
    CausalReasoner,
    CausalReasoningTemplate,
)
from probos.cognitive.journal import CognitiveJournal


# ----- Test 1: dataclass shape -------------------------------------------------

def test_template_is_frozen_and_round_trips_to_dict() -> None:
    t = CausalReasoningTemplate(
        template_id="abc123",
        agent_id="agent-1",
        triggered_at=datetime(2026, 5, 4, 12, 0, 0, tzinfo=timezone.utc),
        trigger_summary="Latency spiked",
        what_changed=["new prompt", "new tier"],
        confounded_variables=["both shipped same day"],
        testable_hypotheses=["prompt change caused regression"],
        diagnostic_actions=["roll back prompt only"],
        confidence=0.7,
        source_event_ref="self_monitoring_concern:agent-1",
    )
    with pytest.raises(Exception):  # FrozenInstanceError
        t.confidence = 0.9  # type: ignore[misc]
    d = t.to_dict()
    assert d["template_id"] == "abc123"
    assert d["confidence"] == 0.7
    assert d["what_changed"] == ["new prompt", "new tier"]
    assert d["triggered_at"] == "2026-05-04T12:00:00+00:00"
    assert d["source_event_ref"] == "self_monitoring_concern:agent-1"


# ----- Test 2: happy path — synthetic LLM JSON -------------------------------

@pytest.mark.asyncio
async def test_analyze_happy_path_with_synthetic_llm_output() -> None:
    fake_response = SimpleNamespace(content=json.dumps({
        "what_changed": ["modulation_v2 enabled", "tier=fast forced"],
        "confounded_variables": ["both rolled out same dream cycle"],
        "testable_hypotheses": ["fast tier insufficient for evaluate step"],
        "diagnostic_actions": ["pin tier=standard for evaluate; re-run"],
        "confidence": 0.6,
    }))
    fake_llm = SimpleNamespace(complete=AsyncMock(return_value=fake_response))
    runtime = SimpleNamespace(llm_client=fake_llm)
    reasoner = CausalReasoner(runtime)

    template = await reasoner.analyze(
        trigger="Evaluate latency p95 doubled",
        agent_id="science-1",
        context={"step": "evaluate", "tier": "fast"},
        source_event_ref="evt:abc",
    )

    assert template.agent_id == "science-1"
    assert template.confidence == 0.6
    assert "modulation_v2 enabled" in template.what_changed
    assert template.testable_hypotheses == [
        "fast tier insufficient for evaluate step"
    ]
    assert template.source_event_ref == "evt:abc"
    fake_llm.complete.assert_awaited_once()


# ----- Test 3: degraded path — JSON parse failure ----------------------------

@pytest.mark.asyncio
async def test_analyze_returns_degraded_template_on_parse_failure() -> None:
    fake_response = SimpleNamespace(content="<no JSON here, just prose>")
    fake_llm = SimpleNamespace(complete=AsyncMock(return_value=fake_response))
    runtime = SimpleNamespace(llm_client=fake_llm)
    reasoner = CausalReasoner(runtime)

    template = await reasoner.analyze(
        trigger="Unknown failure",
        agent_id="medical-1",
    )
    assert template.agent_id == "medical-1"
    assert template.what_changed == []
    assert template.confounded_variables == []
    assert template.testable_hypotheses == []
    assert template.diagnostic_actions == []
    assert template.confidence == 0.0


# ----- Test 4: journal round-trip --------------------------------------------

@pytest.mark.asyncio
async def test_journal_record_and_retrieve_round_trip(tmp_path: Path) -> None:
    journal = CognitiveJournal(db_path=str(tmp_path / "j.db"))
    await journal.start()
    try:
        t = CausalReasoningTemplate(
            template_id="rt-1",
            agent_id="ops-1",
            triggered_at=datetime.now(timezone.utc),
            trigger_summary="trip",
            what_changed=["a", "b"],
            confounded_variables=["c"],
            testable_hypotheses=["h1", "h2"],
            diagnostic_actions=["d1"],
            confidence=0.4,
            source_event_ref="evt:ops",
        )
        await journal.record_causal_template(t)
        rows = await journal.get_recent_causal_templates(limit=10)
        assert len(rows) == 1
        row = rows[0]
        assert row["template_id"] == "rt-1"
        assert row["agent_id"] == "ops-1"
        assert row["what_changed"] == ["a", "b"]
        assert row["testable_hypotheses"] == ["h1", "h2"]
        assert row["confidence"] == 0.4
        assert row["source_event_ref"] == "evt:ops"
    finally:
        await journal.stop()


# ----- Test 5: agent_id filter -----------------------------------------------

@pytest.mark.asyncio
async def test_journal_get_recent_filters_by_agent_id(tmp_path: Path) -> None:
    journal = CognitiveJournal(db_path=str(tmp_path / "j.db"))
    await journal.start()
    try:
        for i, aid in enumerate(["a1", "a2", "a1"]):
            t = CausalReasoningTemplate(
                template_id=f"f-{i}",
                agent_id=aid,
                triggered_at=datetime.now(timezone.utc),
                trigger_summary="trig",
                what_changed=[],
                confounded_variables=[],
                testable_hypotheses=[],
                diagnostic_actions=[],
                confidence=0.0,
            )
            await journal.record_causal_template(t)
        only_a1 = await journal.get_recent_causal_templates(limit=10, agent_id="a1")
        assert {r["agent_id"] for r in only_a1} == {"a1"}
        assert len(only_a1) == 2
    finally:
        await journal.stop()


# ----- Test 6: analyze_concern degrades on missing agent_id ------------------

@pytest.mark.asyncio
async def test_analyze_concern_returns_none_on_missing_agent_id() -> None:
    runtime = SimpleNamespace(llm_client=SimpleNamespace(complete=AsyncMock()))
    reasoner = CausalReasoner(runtime)
    result = await reasoner.analyze_concern({"zone": "amber"})
    assert result is None
    runtime.llm_client.complete.assert_not_awaited()


# ----- Test 7: integration point — disabled config = no-op -------------------

def test_wirer_skips_when_config_disabled() -> None:
    """AD-660: _wire_causal_reasoner returns False when config disabled."""
    from probos.config import SystemConfig
    from probos.startup.finalize import _wire_causal_reasoner

    sys_cfg = SystemConfig()
    assert sys_cfg.causal_reasoning.enabled is False  # default
    runtime = SimpleNamespace()
    wired = _wire_causal_reasoner(runtime=runtime, config=sys_cfg)
    assert wired is False
    assert not hasattr(runtime, "causal_reasoner")


# ----- Test 8: integration point — enabled config = wired + reasoner runs ----

@pytest.mark.asyncio
async def test_wirer_creates_runtime_attribute_when_enabled() -> None:
    """AD-660: _wire_causal_reasoner sets runtime.causal_reasoner when enabled."""
    from probos.config import CausalReasoningConfig, SystemConfig
    from probos.startup.finalize import _wire_causal_reasoner

    sys_cfg = SystemConfig()
    sys_cfg.causal_reasoning = CausalReasoningConfig(enabled=True)
    runtime = SimpleNamespace(llm_client=SimpleNamespace(
        complete=AsyncMock(return_value=SimpleNamespace(content="{}")),
    ))
    wired = _wire_causal_reasoner(runtime=runtime, config=sys_cfg)
    assert wired is True
    assert isinstance(runtime.causal_reasoner, CausalReasoner)
    # Smoke: analyze_concern with valid payload returns a (degraded but real) template.
    template = await runtime.causal_reasoner.analyze_concern(
        {"agent_id": "a1", "agent_callsign": "alpha", "zone": "amber",
         "similarity_ratio": 0.9, "velocity_ratio": 1.2}
    )
    assert template is not None
    assert template.agent_id == "a1"
    assert template.confidence == 0.0  # empty JSON `{}` → degraded
