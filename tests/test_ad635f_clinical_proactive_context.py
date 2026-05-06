"""AD-635f tests: clinical telemetry proactive context injection.

Mirrors test_ad630_leadership_feedback.py fixture pattern (loop + MagicMock
runtime). 15 tests across 5 test classes:

- TestClinicalRoleGate (4)
- TestPerDomainErrorIsolation (3)
- TestStateBuilder (3)
- TestPromptRender (4)
- TestIntegration (1)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------


def _make_loop_and_rt(*, clinical_service=None):
    """Build a ProactiveCognitiveLoop with a MagicMock runtime.

    Mirrors test_ad630_leadership_feedback.py:_make_loop_and_rt (line 470).
    Sets `_build_self_monitoring_context = AsyncMock(return_value=None)` to
    silence the AD-504 path so we test only the AD-635f branch.
    """
    from probos.proactive import ProactiveCognitiveLoop

    loop = ProactiveCognitiveLoop(interval=120.0, cooldown=300.0)

    rt = MagicMock()
    rt.ontology = MagicMock()
    rt.ontology.get_subordinate_agent_types = MagicMock(return_value=[])
    rt.ontology.get_crew_context = MagicMock(return_value=None)
    rt.ward_room_service = AsyncMock()
    rt.agent_pool = {}
    rt._start_time_wall = 1000.0
    rt.trust_network = AsyncMock()
    rt.trust_network.get_score = AsyncMock(return_value=0.5)
    rt.skill_service = None
    rt._introspective_telemetry = None
    rt.conn_manager = None
    rt.cognitive_skill_catalog = None
    rt.callsign_registry = MagicMock()
    rt.callsign_registry.get_callsign = MagicMock(return_value="")
    rt.clinical_telemetry = clinical_service

    loop.set_runtime(rt)
    loop._build_self_monitoring_context = AsyncMock(return_value=None)

    return loop, rt


def _make_clinical_service(*, dreams=None, traces=None, breakers=None,
                           dream_exc=None, trace_exc=None, breaker_exc=None):
    """Build a MagicMock ClinicalTelemetryService stub."""
    svc = MagicMock()
    if dream_exc is not None:
        svc.query_dream_history = AsyncMock(side_effect=dream_exc)
    else:
        svc.query_dream_history = AsyncMock(return_value=dreams or [])
    if trace_exc is not None:
        svc.query_agent_chain_traces = AsyncMock(side_effect=trace_exc)
    else:
        svc.query_agent_chain_traces = AsyncMock(return_value=traces or [])
    if breaker_exc is not None:
        svc.query_circuit_breaker_history = AsyncMock(side_effect=breaker_exc)
    else:
        svc.query_circuit_breaker_history = AsyncMock(return_value=breakers or [])
    return svc


def _make_agent(*, agent_type, agent_id="chapel-id", callsign="Chapel"):
    agent = MagicMock()
    agent.agent_type = agent_type
    agent.id = agent_id
    agent.sovereign_id = f"{agent_id}-sov"
    agent.callsign = callsign
    return agent


# ---------------------------------------------------------------------------
# TestClinicalRoleGate (4)
# ---------------------------------------------------------------------------


class TestClinicalRoleGate:

    @pytest.mark.asyncio
    async def test_diagnostician_gets_clinical_telemetry(self):
        svc = _make_clinical_service(
            dreams=[{"ts": 100}, {"ts": 90}, {"ts": 80}],
            traces=[{"ts": 200, "outcome": "ok"}, {"ts": 190, "outcome": "ok"}],
            breakers=[
                {"agent_id": "alpha", "from_zone": "GREEN", "to_zone": "AMBER", "ts": 300},
            ],
        )
        loop, rt = _make_loop_and_rt(clinical_service=svc)
        agent = _make_agent(agent_type="diagnostician")

        context = await loop._gather_context(agent, 0.5)

        assert "clinical_telemetry" in context
        clin = context["clinical_telemetry"]
        assert "dreams" in clin and clin["dreams"]["count"] == 3
        assert "chain_traces" in clin and clin["chain_traces"]["count"] == 2
        assert clin["chain_traces"]["latest_outcome"] == "ok"
        assert "breakers" in clin and clin["breakers"]["count"] == 1
        assert clin["breakers"]["recent_transitions"][0]["agent"] == "alpha"

    @pytest.mark.asyncio
    async def test_counselor_gets_clinical_telemetry(self):
        svc = _make_clinical_service(
            dreams=[{"ts": 100}],
            traces=[{"ts": 200, "outcome": "completed"}],
            breakers=[{"agent_id": "beta", "from_zone": "AMBER", "to_zone": "RED", "ts": 300}],
        )
        loop, rt = _make_loop_and_rt(clinical_service=svc)
        agent = _make_agent(agent_type="counselor", agent_id="echo-id", callsign="Echo")

        context = await loop._gather_context(agent, 0.5)

        assert "clinical_telemetry" in context
        clin = context["clinical_telemetry"]
        assert clin["dreams"]["count"] == 1
        assert clin["chain_traces"]["count"] == 1
        assert clin["breakers"]["count"] == 1

    @pytest.mark.asyncio
    async def test_non_clinical_agent_no_injection(self):
        svc = _make_clinical_service(
            dreams=[{"ts": 100}],
            traces=[{"ts": 200, "outcome": "ok"}],
            breakers=[{"agent_id": "x", "from_zone": "G", "to_zone": "A", "ts": 300}],
        )
        loop, rt = _make_loop_and_rt(clinical_service=svc)
        agent = _make_agent(agent_type="engineering_officer", agent_id="eng-id")

        context = await loop._gather_context(agent, 0.5)

        assert "clinical_telemetry" not in context
        svc.query_dream_history.assert_not_called()
        svc.query_agent_chain_traces.assert_not_called()
        svc.query_circuit_breaker_history.assert_not_called()

    @pytest.mark.asyncio
    async def test_service_unavailable_no_injection(self):
        loop, rt = _make_loop_and_rt(clinical_service=None)
        agent = _make_agent(agent_type="diagnostician")

        context = await loop._gather_context(agent, 0.5)

        assert "clinical_telemetry" not in context


# ---------------------------------------------------------------------------
# TestPerDomainErrorIsolation (3)
# ---------------------------------------------------------------------------


class TestPerDomainErrorIsolation:

    @pytest.mark.asyncio
    async def test_dream_query_failure_logs_and_skips_dreams(self):
        svc = _make_clinical_service(
            dream_exc=RuntimeError("dream service down"),
            traces=[{"ts": 200, "outcome": "ok"}],
            breakers=[{"agent_id": "x", "from_zone": "G", "to_zone": "A", "ts": 300}],
        )
        loop, rt = _make_loop_and_rt(clinical_service=svc)
        agent = _make_agent(agent_type="diagnostician")

        context = await loop._gather_context(agent, 0.5)

        assert "clinical_telemetry" in context
        clin = context["clinical_telemetry"]
        assert "dreams" not in clin
        assert "chain_traces" in clin
        assert "breakers" in clin

    @pytest.mark.asyncio
    async def test_all_three_queries_fail_no_key_injected(self):
        svc = _make_clinical_service(
            dream_exc=RuntimeError("d"),
            trace_exc=RuntimeError("t"),
            breaker_exc=RuntimeError("b"),
        )
        loop, rt = _make_loop_and_rt(clinical_service=svc)
        agent = _make_agent(agent_type="diagnostician")

        context = await loop._gather_context(agent, 0.5)

        assert "clinical_telemetry" not in context

    @pytest.mark.asyncio
    async def test_captain_override_never_set_to_true(self):
        svc = _make_clinical_service(
            dreams=[{"ts": 100}],
            traces=[{"ts": 200, "outcome": "ok"}],
            breakers=[{"agent_id": "x", "from_zone": "G", "to_zone": "A", "ts": 300}],
        )
        loop, rt = _make_loop_and_rt(clinical_service=svc)
        agent = _make_agent(agent_type="diagnostician")

        await loop._gather_context(agent, 0.5)

        for mock_call in (
            svc.query_dream_history,
            svc.query_agent_chain_traces,
            svc.query_circuit_breaker_history,
        ):
            assert mock_call.call_count == 1
            kwargs = mock_call.call_args.kwargs
            assert kwargs.get("captain_override", False) is False


# ---------------------------------------------------------------------------
# TestStateBuilder (3)
# ---------------------------------------------------------------------------


class TestStateBuilder:
    """Direct call into CognitiveAgent._build_situation_awareness."""

    def _call_builder(self, context_parts: dict) -> dict:
        from probos.cognitive.cognitive_agent import CognitiveAgent
        # MagicMock self honoring the bound method signature.
        instance = MagicMock(spec=CognitiveAgent)
        return CognitiveAgent._build_situation_awareness(instance, context_parts)

    def test_clinical_telemetry_xml_tags(self):
        context_parts = {
            "clinical_telemetry": {
                "dreams": {"count": 3, "latest_ts": 100},
                "chain_traces": {"count": 2, "latest_ts": 200, "latest_outcome": "ok"},
                "breakers": {
                    "count": 1,
                    "recent_transitions": [
                        {"agent": "alpha", "from": "GREEN", "to": "AMBER", "ts": 300},
                    ],
                },
            }
        }
        state = self._call_builder(context_parts)

        assert "_clinical_telemetry" in state
        rendered = state["_clinical_telemetry"]
        assert rendered.startswith("<clinical_telemetry>")
        assert rendered.endswith("</clinical_telemetry>")
        assert "dreams: 3 recent" in rendered
        assert "chain_traces: 2 self" in rendered
        assert "latest_outcome=ok" in rendered
        assert "breakers: 1 transitions" in rendered
        assert "alpha: GREEN->AMBER" in rendered

    def test_clinical_telemetry_empty_no_state(self):
        state = self._call_builder({"clinical_telemetry": {}})
        assert "_clinical_telemetry" not in state

    def test_clinical_telemetry_partial_summary(self):
        context_parts = {
            "clinical_telemetry": {
                "dreams": {"count": 2, "latest_ts": 100},
            }
        }
        state = self._call_builder(context_parts)

        assert "_clinical_telemetry" in state
        rendered = state["_clinical_telemetry"]
        assert "dreams: 2 recent" in rendered
        assert "chain_traces" not in rendered
        assert "breakers" not in rendered


# ---------------------------------------------------------------------------
# TestPromptRender (4)
# ---------------------------------------------------------------------------


class TestPromptRender:

    def test_compose_includes_clinical_section(self):
        from probos.cognitive.sub_tasks.compose import _build_user_prompt
        body = "<clinical_telemetry>\n  dreams: 3 recent\n</clinical_telemetry>"
        rendered = _build_user_prompt(
            context={"context": "msg", "_clinical_telemetry": body},
            prior_results=[],
        )
        assert "## Clinical Telemetry" in rendered
        assert body in rendered

    def test_compose_skips_when_clinical_empty(self):
        from probos.cognitive.sub_tasks.compose import _build_user_prompt
        rendered = _build_user_prompt(
            context={"context": "msg"},
            prior_results=[],
        )
        assert "## Clinical Telemetry" not in rendered

    def test_analyze_includes_clinical_section(self):
        from probos.cognitive.sub_tasks.analyze import _build_situation_review_prompt
        body = "<clinical_telemetry>\n  dreams: 3 recent\n</clinical_telemetry>"
        _system, user = _build_situation_review_prompt(
            context={"context": "", "_clinical_telemetry": body},
            prior_results=[],
            callsign="Chapel",
            department="medical",
        )
        assert body in user

    def test_analyze_skips_when_clinical_empty(self):
        from probos.cognitive.sub_tasks.analyze import _build_situation_review_prompt
        _system, user = _build_situation_review_prompt(
            context={"context": ""},
            prior_results=[],
            callsign="Chapel",
            department="medical",
        )
        assert "<clinical_telemetry>" not in user


# ---------------------------------------------------------------------------
# TestIntegration (1)
# ---------------------------------------------------------------------------


class TestIntegration:

    @pytest.mark.asyncio
    async def test_chapel_end_to_end_proactive_cycle_renders_section(self):
        from probos.cognitive.cognitive_agent import CognitiveAgent
        from probos.cognitive.sub_tasks.compose import _build_user_prompt

        svc = _make_clinical_service(
            dreams=[{"ts": 100}, {"ts": 90}],
            traces=[{"ts": 200, "outcome": "ok"}],
            breakers=[
                {"agent_id": "alpha", "from_zone": "GREEN", "to_zone": "AMBER", "ts": 300},
            ],
        )
        loop, rt = _make_loop_and_rt(clinical_service=svc)
        agent = _make_agent(agent_type="diagnostician", callsign="Chapel")

        # Producer side
        context = await loop._gather_context(agent, 0.5)
        assert "clinical_telemetry" in context

        # State-builder side
        instance = MagicMock(spec=CognitiveAgent)
        state = CognitiveAgent._build_situation_awareness(instance, context)
        assert "_clinical_telemetry" in state
        assert state["_clinical_telemetry"].startswith("<clinical_telemetry>")

        # Prompt-render side
        rendered = _build_user_prompt(
            context={"context": "msg", "_clinical_telemetry": state["_clinical_telemetry"]},
            prior_results=[],
        )
        assert "## Clinical Telemetry" in rendered
        assert "<clinical_telemetry>" in rendered
        assert "dreams: 2 recent" in rendered
