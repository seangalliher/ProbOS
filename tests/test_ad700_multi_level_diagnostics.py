"""AD-700: Multi-Level Diagnostics (L1-L5) — DiagnosticLevel enum + Diagnostician integration.

Tests cover:
- DiagnosticLevel enum invariants (depth_rank, llm_tier, expected_duration_label).
- parse_level() robustness across formats and fallback behavior.
- DiagnosticianAgent.perceive() correctly:
  * Defaults missing level to L3.
  * Stamps level / level_rank / level_llm_tier on the result.
  * Skips VitalsMonitor scan at L5 (shallowest).
  * Invokes VitalsMonitor scan at deeper levels (L4-L1).
  * Appends the level-specific scope hint to context.
  * Leaves non-diagnose intents untouched.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.agents.medical.diagnostic_levels import DiagnosticLevel, parse_level


# --- enum-level invariants ---------------------------------------------------

def test_depth_rank_inverts_level_number():
    """L5 is shallowest (rank 1), L1 is deepest (rank 5)."""
    assert DiagnosticLevel.L5.depth_rank == 1
    assert DiagnosticLevel.L4.depth_rank == 2
    assert DiagnosticLevel.L3.depth_rank == 3
    assert DiagnosticLevel.L2.depth_rank == 4
    assert DiagnosticLevel.L1.depth_rank == 5


def test_llm_tier_mapping_matches_spec():
    """Per roadmap: L4-L5 = no LLM, L2-L3 = fast, L1 = deep."""
    assert DiagnosticLevel.L5.llm_tier is None
    assert DiagnosticLevel.L4.llm_tier is None
    assert DiagnosticLevel.L3.llm_tier == "fast"
    assert DiagnosticLevel.L2.llm_tier == "fast"
    assert DiagnosticLevel.L1.llm_tier == "deep"


def test_expected_duration_label_present_for_every_level():
    for level in DiagnosticLevel:
        assert level.expected_duration_label
        assert isinstance(level.expected_duration_label, str)


# --- parse_level robustness --------------------------------------------------

@pytest.mark.parametrize("token,expected", [
    ("L5", DiagnosticLevel.L5),
    ("L1", DiagnosticLevel.L1),
    ("l3", DiagnosticLevel.L3),
    ("  L4 ", DiagnosticLevel.L4),
    ("3", DiagnosticLevel.L3),
    ("1", DiagnosticLevel.L1),
    (5, DiagnosticLevel.L5),
    (DiagnosticLevel.L2, DiagnosticLevel.L2),
])
def test_parse_level_accepts_supported_formats(token, expected):
    assert parse_level(token) == expected


@pytest.mark.parametrize("token", ["", None, "garbage", "L9", "0", "6", "L0"])
def test_parse_level_falls_back_to_default(token):
    assert parse_level(token) == DiagnosticLevel.L3
    assert parse_level(token, default=DiagnosticLevel.L1) == DiagnosticLevel.L1


# --- Diagnostician.perceive() integration -----------------------------------

@pytest.fixture
def stub_super_perceive(monkeypatch):
    """Stub CognitiveAgent.perceive (parent of DiagnosticianAgent) to a
    passthrough so we can exercise the real DiagnosticianAgent.perceive
    logic without needing a fully-constructed CognitiveAgent."""
    from probos.cognitive.cognitive_agent import CognitiveAgent

    async def _passthrough(self, intent):
        return dict(intent)

    monkeypatch.setattr(CognitiveAgent, "perceive", _passthrough)
    return _passthrough


def _make_diagnostician(vitals_metrics: dict | None = None):
    """Construct a DiagnosticianAgent without invoking the real constructor."""
    from probos.agents.medical.diagnostician import DiagnosticianAgent

    agent = DiagnosticianAgent.__new__(DiagnosticianAgent)
    runtime = MagicMock()
    if vitals_metrics is None:
        runtime.registry.all.return_value = []
    else:
        vitals = MagicMock()
        vitals.agent_type = "vitals_monitor"
        vitals.scan_now = AsyncMock(return_value=vitals_metrics)
        runtime.registry.all.return_value = [vitals]
        agent._vitals_stub = vitals
    agent._runtime = runtime
    return agent


@pytest.mark.asyncio
async def test_perceive_defaults_to_l3_when_level_missing(stub_super_perceive):
    agent = _make_diagnostician(vitals_metrics={"trust_mean": 0.5})
    out = await agent.perceive({"intent": "diagnose_system"})
    assert out["level"] == "L3"
    assert out["level_rank"] == 3
    assert out["level_llm_tier"] == "fast"
    assert "Diagnostic depth: L3" in out["context"]


@pytest.mark.asyncio
async def test_perceive_l5_skips_vitals_scan(stub_super_perceive):
    agent = _make_diagnostician(vitals_metrics={"trust_mean": 0.5})
    out = await agent.perceive({"intent": "diagnose_system", "level": "L5"})
    assert out["level"] == "L5"
    assert out["level_rank"] == 1
    assert out["level_llm_tier"] is None
    agent._vitals_stub.scan_now.assert_not_awaited()
    assert "Diagnostic depth: L5" in out["context"]


@pytest.mark.asyncio
async def test_perceive_l4_invokes_vitals_scan(stub_super_perceive):
    agent = _make_diagnostician(vitals_metrics={"trust_mean": 0.5})
    out = await agent.perceive({"intent": "diagnose_system", "level": "L4"})
    assert out["level"] == "L4"
    agent._vitals_stub.scan_now.assert_awaited_once()
    assert "LIVE SYSTEM METRICS" in out["context"]
    assert "Diagnostic depth: L4" in out["context"]


@pytest.mark.asyncio
async def test_perceive_l1_uses_deep_tier(stub_super_perceive):
    agent = _make_diagnostician(vitals_metrics={"trust_mean": 0.5})
    out = await agent.perceive({"intent": "diagnose_system", "level": 1})
    assert out["level"] == "L1"
    assert out["level_rank"] == 5
    assert out["level_llm_tier"] == "deep"
    assert "Diagnostic depth: L1" in out["context"]


@pytest.mark.asyncio
async def test_perceive_invalid_level_falls_back_to_l3(stub_super_perceive):
    agent = _make_diagnostician(vitals_metrics={"trust_mean": 0.5})
    out = await agent.perceive({"intent": "diagnose_system", "level": "L9"})
    assert out["level"] == "L3"


@pytest.mark.asyncio
async def test_perceive_no_runtime_still_emits_level_metadata(stub_super_perceive):
    from probos.agents.medical.diagnostician import DiagnosticianAgent

    agent = DiagnosticianAgent.__new__(DiagnosticianAgent)
    agent._runtime = None
    out = await agent.perceive({"intent": "diagnose_system", "level": "L3"})
    assert out["level"] == "L3"
    assert "LIVE SYSTEM METRICS" not in out.get("context", "")
    assert "Diagnostic depth: L3" in out["context"]


@pytest.mark.asyncio
async def test_perceive_non_diagnose_intent_unchanged(stub_super_perceive):
    agent = _make_diagnostician()
    out = await agent.perceive({"intent": "medical_alert", "severity": "warning"})
    assert "level" not in out
    assert "context" not in out
