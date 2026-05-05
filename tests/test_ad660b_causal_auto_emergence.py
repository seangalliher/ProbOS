"""AD-660b: Causal Reasoning Auto-Invocation + Emergence Integration — focused tests."""

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
    _jaccard,
    _rank_hypotheses,
    _recommended_actions_from,
    _tokenize_for_novelty,
)
from probos.cognitive.journal import CognitiveJournal


def _llm_response(payload: dict) -> SimpleNamespace:
    return SimpleNamespace(content=json.dumps(payload))


def _make_runtime(*, llm_payload: dict | None = None, journal: CognitiveJournal | None = None):
    response = _llm_response(llm_payload or {
        "what_changed": ["x"],
        "confounded_variables": [],
        "testable_hypotheses": ["latency caused regression"],
        "diagnostic_actions": ["roll back prompt"],
        "confidence": 0.5,
    })
    return SimpleNamespace(
        llm_client=SimpleNamespace(complete=AsyncMock(return_value=response)),
        cognitive_journal=journal,
    )


# ----- Test 1: template field shape & defaults --------------------------------

def test_template_has_ranked_hypotheses_and_recommended_actions_fields() -> None:
    t = CausalReasoningTemplate(
        template_id="t1",
        agent_id="a1",
        triggered_at=datetime.now(timezone.utc),
        trigger_summary="x",
        what_changed=[],
        confounded_variables=[],
        testable_hypotheses=[],
        diagnostic_actions=[],
        confidence=0.0,
    )
    assert t.ranked_hypotheses == []
    assert t.recommended_actions == []
    d = t.to_dict()
    assert d["ranked_hypotheses"] == []
    assert d["recommended_actions"] == []


# ----- Test 2: analyze() populates ranked_hypotheses + recommended_actions ----

@pytest.mark.asyncio
async def test_analyze_populates_ranking_and_recommendations() -> None:
    runtime = _make_runtime(llm_payload={
        "what_changed": ["new prompt"],
        "confounded_variables": [],
        "testable_hypotheses": [
            "fast tier insufficient",
            "prompt regression broke evaluate",
        ],
        "diagnostic_actions": ["pin tier=standard", "roll back prompt"],
        "confidence": 0.8,
    })
    reasoner = CausalReasoner(runtime)
    template = await reasoner.analyze(trigger="t", agent_id="a1")
    assert len(template.ranked_hypotheses) == 2
    ranks = [r["rank"] for r in template.ranked_hypotheses]
    assert ranks == [1, 2]
    scores = [r["score"] for r in template.ranked_hypotheses]
    assert scores[0] >= scores[1]
    assert template.ranked_hypotheses[0]["novelty"] == 1.0
    actions = template.recommended_actions
    assert len(actions) == 2
    assert all(a["status"] == "recommended" and a["needs_sandbox"] is True for a in actions)
    assert {a["action"] for a in actions} == {"pin tier=standard", "roll back prompt"}


# ----- Test 3: novelty scoring — identical hypothesis to prior --------------

def test_novelty_zero_when_hypothesis_matches_prior_token_set() -> None:
    prior = [_tokenize_for_novelty("fast tier insufficient for evaluate")]
    ranked = _rank_hypotheses(
        ["fast tier insufficient for evaluate"], 0.9, prior,
    )
    assert ranked[0]["novelty"] == 0.0
    assert ranked[0]["score"] == 0.0


# ----- Test 4: novelty scoring — fully novel hypothesis ----------------------

def test_novelty_one_when_no_token_overlap() -> None:
    prior = [_tokenize_for_novelty("alpha beta gamma")]
    ranked = _rank_hypotheses(
        ["delta epsilon zeta"], 0.6, prior,
    )
    assert ranked[0]["novelty"] == 1.0
    assert ranked[0]["score"] == pytest.approx(0.6, abs=1e-4)


# ----- Test 5: empty journal => novelty 1.0 for every hypothesis -----------

def test_novelty_one_when_no_prior_history() -> None:
    ranked = _rank_hypotheses(["any new hypothesis"], 0.4, [])
    assert ranked[0]["novelty"] == 1.0
    assert ranked[0]["score"] == pytest.approx(0.4, abs=1e-4)


# ----- Test 6: rate limiter — under threshold passes ------------------------

@pytest.mark.asyncio
async def test_rate_limit_allows_up_to_threshold() -> None:
    fixed = [1000.0]
    runtime = _make_runtime()
    reasoner = CausalReasoner(
        runtime, max_invocations_per_hour=3, clock=lambda: fixed[0],
    )
    for _ in range(3):
        t = await reasoner.analyze(trigger="t", agent_id="a1")
        assert t.trigger_summary != "<rate-limited>"
    assert runtime.llm_client.complete.await_count == 3


# ----- Test 7: rate limiter — at threshold rejects --------------------------

@pytest.mark.asyncio
async def test_rate_limit_rejects_above_threshold() -> None:
    fixed = [1000.0]
    runtime = _make_runtime()
    reasoner = CausalReasoner(
        runtime, max_invocations_per_hour=2, clock=lambda: fixed[0],
    )
    await reasoner.analyze(trigger="t", agent_id="a1")
    await reasoner.analyze(trigger="t", agent_id="a1")
    rejected = await reasoner.analyze(trigger="t", agent_id="a1")
    assert rejected.trigger_summary == "<rate-limited>"
    assert runtime.llm_client.complete.await_count == 2


# ----- Test 8: rate limiter — window expiry resets counter ------------------

@pytest.mark.asyncio
async def test_rate_limit_resets_after_window_expiry() -> None:
    fixed = [1000.0]
    runtime = _make_runtime()
    reasoner = CausalReasoner(
        runtime, max_invocations_per_hour=1, clock=lambda: fixed[0],
    )
    t1 = await reasoner.analyze(trigger="t", agent_id="a1")
    assert t1.trigger_summary != "<rate-limited>"
    rejected = await reasoner.analyze(trigger="t", agent_id="a1")
    assert rejected.trigger_summary == "<rate-limited>"
    fixed[0] = 1000.0 + 3601.0
    t3 = await reasoner.analyze(trigger="t", agent_id="a1")
    assert t3.trigger_summary != "<rate-limited>"
    assert runtime.llm_client.complete.await_count == 2


# ----- Test 9: analyze_groupthink builds trigger and uses emergence bucket --

@pytest.mark.asyncio
async def test_analyze_groupthink_builds_trigger_and_uses_emergence_bucket() -> None:
    runtime = _make_runtime()
    reasoner = CausalReasoner(runtime, max_invocations_per_hour=1)
    await reasoner.analyze(trigger="x", agent_id="a1")
    template = await reasoner.analyze_groupthink({"redundancy_ratio": 0.85})
    assert template.trigger_summary != "<rate-limited>"
    assert template.agent_id == "_ship_emergence"
    assert template.source_event_ref == "groupthink_warning"
    call_args = runtime.llm_client.complete.await_args_list[-1]
    sent = call_args.args[0]
    assert "0.850" in sent.prompt


# ----- Test 10: analyze_fragmentation builds trigger ------------------------

@pytest.mark.asyncio
async def test_analyze_fragmentation_builds_trigger() -> None:
    runtime = _make_runtime()
    reasoner = CausalReasoner(runtime)
    template = await reasoner.analyze_fragmentation({
        "synergy_ratio": 0.05,
        "pairs_analyzed": 12,
    })
    assert template.agent_id == "_ship_emergence"
    assert template.source_event_ref == "fragmentation_warning"
    call_args = runtime.llm_client.complete.await_args_list[-1]
    sent = call_args.args[0]
    assert "synergy_ratio=0.050" in sent.prompt
    assert "12 pairs" in sent.prompt


# ----- Test 11: counselor groupthink hook fires reasoner + journal ----------

@pytest.mark.asyncio
async def test_counselor_groupthink_handler_invokes_causal_reasoner() -> None:
    """Smoke: _on_groupthink_warning awaits reasoner.analyze_groupthink + journal.record."""
    from probos.cognitive.counselor import CounselorAgent

    reasoner = SimpleNamespace(analyze_groupthink=AsyncMock(
        return_value=SimpleNamespace(template_id="g1"),
    ))
    journal = SimpleNamespace(record_causal_template=AsyncMock())
    runtime = SimpleNamespace(causal_reasoner=reasoner, cognitive_journal=journal)

    counselor = CounselorAgent.__new__(CounselorAgent)
    counselor.id = "counselor-1"
    counselor._runtime = runtime
    counselor.__dict__["_cognitive_journal"] = journal

    await counselor._on_groupthink_warning({"redundancy_ratio": 0.7})

    reasoner.analyze_groupthink.assert_awaited_once()
    journal.record_causal_template.assert_awaited_once()


# ----- Test 12: default-on config + journal round-trip with new fields -----

@pytest.mark.asyncio
async def test_default_enabled_and_journal_roundtrip_with_new_fields(tmp_path: Path) -> None:
    from probos.config import SystemConfig

    sys_cfg = SystemConfig()
    assert sys_cfg.causal_reasoning.enabled is True
    assert sys_cfg.causal_reasoning.max_invocations_per_hour == 5

    journal = CognitiveJournal(db_path=str(tmp_path / "j.db"))
    await journal.start()
    try:
        t = CausalReasoningTemplate(
            template_id="rt-b1",
            agent_id="ops-1",
            triggered_at=datetime.now(timezone.utc),
            trigger_summary="trip",
            what_changed=[],
            confounded_variables=[],
            testable_hypotheses=["h"],
            diagnostic_actions=["do x"],
            confidence=0.5,
            source_event_ref="evt:b1",
            ranked_hypotheses=[{"hypothesis": "h", "score": 0.5, "rank": 1, "novelty": 1.0}],
            recommended_actions=[{"action": "do x", "status": "recommended", "needs_sandbox": True}],
        )
        await journal.record_causal_template(t)
        rows = await journal.get_recent_causal_templates(limit=10)
        assert len(rows) == 1
        row = rows[0]
        assert row["ranked_hypotheses"] == [
            {"hypothesis": "h", "score": 0.5, "rank": 1, "novelty": 1.0},
        ]
        assert row["recommended_actions"] == [
            {"action": "do x", "status": "recommended", "needs_sandbox": True},
        ]
    finally:
        await journal.stop()
