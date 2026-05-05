"""AD-647b v1 — ProcessChainRegistry + process_chain_id base-class hook tests."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.process_chains import (
    ProcessChainDefinition,
    ProcessChainRegistry,
    ProcessChainStep,
    ProcessChainStepKind,
)
from probos.cognitive.scout import (
    SCOUT_REPORT_CHAIN,
    ScoutAgent,
    ScoutFinding,
    _scout_step_enrich_and_filter,
)


# ----------------------------------------------------------------------
# Test fixtures / helpers
# ----------------------------------------------------------------------

async def _noop(ctx: dict[str, Any]) -> dict[str, Any]:
    return {}


def _make_def(name: str = "x") -> ProcessChainDefinition:
    return ProcessChainDefinition(
        name=name,
        description="test",
        steps=(ProcessChainStep(kind=ProcessChainStepKind.TRANSFORM, name="s", handler=_noop),),
    )


# ----------------------------------------------------------------------
# Section 1: ProcessChainRegistry semantics
# ----------------------------------------------------------------------

def test_registry_register_get_list():
    registry = ProcessChainRegistry()
    definition = _make_def("scout_report")
    registry.register_chain(definition)
    assert registry.get_chain("scout_report") is definition
    assert registry.list_chains() == ["scout_report"]


def test_registry_get_unknown_returns_none():
    registry = ProcessChainRegistry()
    assert registry.get_chain("nope") is None


def test_registry_unregister_returns_true_when_present():
    registry = ProcessChainRegistry()
    registry.register_chain(_make_def("x"))
    assert registry.unregister_chain("x") is True
    assert registry.get_chain("x") is None


def test_registry_unregister_unknown_returns_false():
    registry = ProcessChainRegistry()
    assert registry.unregister_chain("nope") is False


def test_registry_duplicate_registration_replaces_with_warning(caplog):
    registry = ProcessChainRegistry()
    a = _make_def("x")
    b = _make_def("x")
    registry.register_chain(a)
    with caplog.at_level(logging.WARNING, logger="probos.cognitive.process_chains"):
        registry.register_chain(b)
    assert any("replacing existing process chain" in r.message for r in caplog.records)
    assert registry.get_chain("x") is b


# ----------------------------------------------------------------------
# Section 2: process_chain_id base-class hook
# ----------------------------------------------------------------------

class _FakeExecutor:
    enabled = True


def _bare_agent(process_chain_id: str | None = None) -> CognitiveAgent:
    """Bypass spawner ctor; wire only the attributes _should_activate_chain reads."""
    agent = CognitiveAgent.__new__(CognitiveAgent)
    agent._sub_task_executor = _FakeExecutor()
    if process_chain_id is not None:
        # type: ignore[misc] — instance-level override of class attribute
        agent.process_chain_id = process_chain_id
    return agent


def test_should_activate_chain_returns_false_when_process_chain_id_matches_duty():
    agent = _bare_agent(process_chain_id="scout_report")
    observation = {
        "intent": "proactive_think",
        "params": {"duty": {"duty_id": "scout_report"}},
    }
    assert agent._should_activate_chain(observation) is False


def test_should_activate_chain_falls_through_when_process_chain_id_is_none():
    agent = _bare_agent(process_chain_id=None)
    observation = {
        "intent": "proactive_think",
        "params": {"duty": {"duty_id": "scout_report"}},
    }
    # No process_chain_id set → gates 1+2 evaluate; executor enabled,
    # proactive_think is in _CHAIN_ELIGIBLE_INTENTS → True.
    assert agent._should_activate_chain(observation) is True


def test_should_activate_chain_falls_through_when_duty_id_mismatches():
    agent = _bare_agent(process_chain_id="scout_report")
    observation = {
        "intent": "proactive_think",
        "params": {"duty": {"duty_id": "other"}},
    }
    # duty_id mismatch → bypass not triggered; falls through to gates 1+2 → True.
    assert agent._should_activate_chain(observation) is True


# ----------------------------------------------------------------------
# Section 3: Scout migration (class attr + override removal)
# ----------------------------------------------------------------------

def test_scout_agent_class_attribute_is_scout_report():
    assert ScoutAgent.process_chain_id == "scout_report"


def test_scout_no_longer_overrides_should_activate_chain():
    # Method lookup on ScoutAgent must resolve to the base implementation.
    assert ScoutAgent._should_activate_chain is CognitiveAgent._should_activate_chain


# ----------------------------------------------------------------------
# Module-level handler reads agent from context
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_module_level_handler_reads_agent_from_context():
    agent_stub = SimpleNamespace(_repo_metadata={}, _last_findings=[])
    findings = [
        ScoutFinding(
            repo_full_name="o/a", stars=10, url="u",
            classification="absorb", relevance=4,
            credibility=4, reliability=4,
            summary="s", insight="i",
        ),
        ScoutFinding(
            repo_full_name="o/b", stars=5, url="u2",
            classification="skip", relevance=1,
            credibility=1, reliability=1,
            summary="s", insight="i",
        ),
    ]
    out = await _scout_step_enrich_and_filter({"_agent": agent_stub, "findings": findings})
    assert out["total_classified"] == 2
    # min_relevance=3 in filter_findings → only first survives.
    assert len(out["filtered"]) == 1
    assert out["filtered"][0].repo_full_name == "o/a"
    assert agent_stub._last_findings == out["filtered"]


# ----------------------------------------------------------------------
# Section 5: Finalize wirer
# ----------------------------------------------------------------------

def test_wirer_registers_scout_report_chain():
    from probos.config import SystemConfig
    from probos.startup.finalize import _wire_process_chain_registry

    runtime = SimpleNamespace()
    config = SystemConfig()
    result = _wire_process_chain_registry(runtime=runtime, config=config)
    assert result is True
    assert runtime.process_chain_registry.list_chains() == ["scout_report"]
    chain = runtime.process_chain_registry.get_chain("scout_report")
    assert chain is SCOUT_REPORT_CHAIN
    assert chain.steps[0].name == "parse_and_mark_seen"
