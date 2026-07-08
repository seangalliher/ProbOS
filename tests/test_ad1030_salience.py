"""AD-1030: tests for adaptive salience scoring (relevance × recency × importance).

Layout:
- ``test_compute_salience_*`` / ``test_recency_*`` / ``test_importance_*`` /
  ``test_cosine_*`` — pure unit tests for the ``salience`` module (no agent, no
  I/O). The rank-flip acceptance lives here.
- ``test_attention_config_*`` — config defaults (salience scoring OFF).
- ``test_salience_rank_memories_*`` / ``test_build_user_message_*`` /
  ``test_*_wm_*`` — integration on a real ``CognitiveAgent`` with REAL
  ``embed_text`` embeddings for the relevance path (BF-287: no MagicMock at the
  embedding boundary; kept to 2 memories/entries so it stays fast).

Default-OFF is the paramount constraint: ``attention.salience_scoring=False``
(the default) ⇒ the AD-1029 fixed-priority bid path is byte-identical. That
byte-identity is additionally proven by the unchanged AD-1028 golden and
AD-1029 suites run alongside this file in the gate.
"""
from __future__ import annotations

import math
import re
import time

import pytest

from probos.cognitive.agent_working_memory import AgentWorkingMemory
from probos.cognitive.salience import (
    SalienceWeights,
    compute_salience,
    cosine_similarity,
    importance_norm,
    recency_decay,
)
from probos.config import AttentionConfig, SystemConfig
from probos.knowledge.embeddings import embed_text, get_embedding_function
from tests.fixtures.ad1028_golden._capture_golden import make_dm_agent


# ---------------------------------------------------------------------------
# Real-object fixtures (BF-287)
# ---------------------------------------------------------------------------


class _Rt:
    """Minimal real runtime stand-in exposing a real ``SystemConfig``."""

    def __init__(self, config: SystemConfig) -> None:
        self.config = config


def _salience_on_config(
    *, w_rel: float = 1.0, w_rec: float = 0.5, w_imp: float = 0.5,
    half_life: float = 86400.0,
) -> SystemConfig:
    """A real SystemConfig with AD-1030 salience scoring enabled."""
    cfg = SystemConfig()
    cfg.memory.attention.salience_scoring = True
    cfg.memory.attention.w_rel = w_rel
    cfg.memory.attention.w_rec = w_rec
    cfg.memory.attention.w_imp = w_imp
    cfg.memory.attention.recency_half_life_seconds = half_life
    return cfg


_IRRELEVANT = "Replicator dessert menu was updated."
_RELEVANT = "The warp core alignment is nominal."
_GOAL = "warp core alignment status"


# ---------------------------------------------------------------------------
# Pure scorer — the rank-flip acceptance + term behaviors
# ---------------------------------------------------------------------------


def test_compute_salience_high_relevance_low_recency_outranks_low_relevance_recent_default_weights() -> None:
    weights = SalienceWeights()  # 1.0, 0.5, 0.5
    relevant_old = compute_salience(relevance=0.9, recency=0.0, importance=5, weights=weights)
    recent_irrelevant = compute_salience(relevance=0.1, recency=1.0, importance=5, weights=weights)
    assert relevant_old > recent_irrelevant


def test_compute_salience_ranking_flips_with_recency_heavy_weights() -> None:
    # Same two memories; weights now emphasize recency → the recent one wins.
    weights = SalienceWeights(w_rel=0.1, w_rec=2.0, w_imp=0.5)
    relevant_old = compute_salience(relevance=0.9, recency=0.0, importance=5, weights=weights)
    recent_irrelevant = compute_salience(relevance=0.1, recency=1.0, importance=5, weights=weights)
    assert recent_irrelevant > relevant_old


def test_compute_salience_in_unit_interval() -> None:
    s = compute_salience(relevance=0.7, recency=0.3, importance=8, weights=SalienceWeights())
    assert 0.0 <= s <= 1.0


def test_compute_salience_weights_scale_invariant() -> None:
    a = compute_salience(relevance=0.7, recency=0.3, importance=8, weights=SalienceWeights(2.0, 1.0, 1.0))
    b = compute_salience(relevance=0.7, recency=0.3, importance=8, weights=SalienceWeights(4.0, 2.0, 2.0))
    assert abs(a - b) < 1e-12


def test_compute_salience_all_zero_weights_returns_zero() -> None:
    s = compute_salience(relevance=0.9, recency=0.9, importance=9, weights=SalienceWeights(0.0, 0.0, 0.0))
    assert s == 0.0


def test_compute_salience_clamps_out_of_range_terms() -> None:
    # relevance > 1 clamps to 1.0; isolate the relevance term with w_rec=w_imp=0.
    s = compute_salience(
        relevance=1.5, recency=-0.5, importance=10,
        weights=SalienceWeights(w_rel=1.0, w_rec=0.0, w_imp=0.0),
    )
    assert s == 1.0


def test_compute_salience_omits_importance_when_w_imp_zero() -> None:
    # WM case: importance has no effect when its weight is zero.
    weights = SalienceWeights(w_rel=1.0, w_rec=1.0, w_imp=0.0)
    low = compute_salience(relevance=0.5, recency=0.5, importance=1, weights=weights)
    high = compute_salience(relevance=0.5, recency=0.5, importance=10, weights=weights)
    assert low == high


def test_compute_salience_isolated_importance_term() -> None:
    # w_rel=w_rec=0, w_imp=1 ⇒ salience == importance_norm(importance).
    weights = SalienceWeights(w_rel=0.0, w_rec=0.0, w_imp=1.0)
    assert compute_salience(relevance=0.0, recency=0.0, importance=1, weights=weights) == 0.0
    assert compute_salience(relevance=0.0, recency=0.0, importance=10, weights=weights) == 1.0
    assert abs(compute_salience(relevance=0.0, recency=0.0, importance=5, weights=weights) - (4.0 / 9.0)) < 1e-12


def test_recency_decay_endpoints_and_monotonic() -> None:
    half_life = 86400.0
    assert recency_decay(0.0, half_life) == 1.0
    assert abs(recency_decay(half_life, half_life) - math.exp(-1.0)) < 1e-12
    # Strictly decreasing in age.
    assert recency_decay(10.0, half_life) > recency_decay(1000.0, half_life)
    assert recency_decay(1000.0, half_life) > recency_decay(100000.0, half_life)


def test_recency_decay_negative_age_clamps_to_one() -> None:
    assert recency_decay(-5.0, 86400.0) == 1.0


def test_recency_decay_nonpositive_half_life_degrades_to_one() -> None:
    assert recency_decay(100.0, 0.0) == 1.0
    assert recency_decay(100.0, -5.0) == 1.0


def test_importance_norm_endpoints_and_clamp() -> None:
    assert importance_norm(1) == 0.0
    assert importance_norm(10) == 1.0
    assert abs(importance_norm(5) - (4.0 / 9.0)) < 1e-12
    assert importance_norm(0) == 0.0     # clamp low
    assert importance_norm(11) == 1.0    # clamp high


def test_cosine_similarity_identical_orthogonal_empty_mismatch() -> None:
    assert cosine_similarity([1.0, 0.0, 0.0], [1.0, 0.0, 0.0]) == 1.0
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert cosine_similarity([], []) == 0.0
    assert cosine_similarity([1.0, 2.0], [1.0]) == 0.0      # length mismatch
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0  # zero magnitude


# ---------------------------------------------------------------------------
# Config defaults — salience scoring OFF out of the box
# ---------------------------------------------------------------------------


def test_attention_config_salience_defaults_off() -> None:
    cfg = AttentionConfig()
    assert cfg.salience_scoring is False
    assert cfg.w_rel == 1.0
    assert cfg.w_rec == 0.5
    assert cfg.w_imp == 0.5
    assert cfg.recency_half_life_seconds == 86400.0


# ---------------------------------------------------------------------------
# Gate helper — default-OFF
# ---------------------------------------------------------------------------


def test_salience_scoring_enabled_false_by_default() -> None:
    agent = make_dm_agent()  # _runtime = None ⇒ unwired
    assert agent._salience_scoring_enabled() is False
    agent._runtime = _Rt(SystemConfig())  # default config ⇒ flag off
    assert agent._salience_scoring_enabled() is False
    agent._runtime = _Rt(_salience_on_config())
    assert agent._salience_scoring_enabled() is True


# ---------------------------------------------------------------------------
# Episodic salience ranking — REAL embeddings (BF-287)
# ---------------------------------------------------------------------------


def test_salience_rank_memories_real_embeddings_orders_by_relevance() -> None:
    if get_embedding_function() is None:
        pytest.skip(
            "real-embedding relevance ordering; the BF-657 lexical local fallback "
            "(CI PROBOS_EMBEDDINGS=local) cannot rank by semantic relevance"
        )
    agent = make_dm_agent()
    agent._runtime = _Rt(_salience_on_config())
    now = time.time()
    # Equal recency + importance ⇒ real-embedding relevance is the only differentiator.
    mems = [
        {"input": _IRRELEVANT, "_embedding": embed_text(_IRRELEVANT), "_timestamp": now, "_importance": 5},
        {"input": _RELEVANT, "_embedding": embed_text(_RELEVANT), "_timestamp": now, "_importance": 5},
    ]
    goal_vec = embed_text(_GOAL)
    ordered, max_salience = agent._salience_rank_memories(mems, goal_vec)
    assert ordered[0]["input"] == _RELEVANT
    assert ordered[1]["input"] == _IRRELEVANT
    assert 0.0 <= max_salience <= 1.0


def test_salience_rank_memories_does_not_mutate_input() -> None:
    agent = make_dm_agent()
    agent._runtime = _Rt(_salience_on_config())
    now = time.time()
    mems = [
        {"input": _IRRELEVANT, "_embedding": embed_text(_IRRELEVANT), "_timestamp": now, "_importance": 5},
        {"input": _RELEVANT, "_embedding": embed_text(_RELEVANT), "_timestamp": now, "_importance": 5},
    ]
    original_order = [m["input"] for m in mems]
    agent._salience_rank_memories(mems, embed_text(_GOAL))
    assert [m["input"] for m in mems] == original_order  # caller's list untouched


def test_salience_rank_memories_missing_keys_degrade_to_tail() -> None:
    agent = make_dm_agent()
    agent._runtime = _Rt(_salience_on_config())
    now = time.time()
    mems = [
        {"input": "no internal salience keys"},  # missing _embedding/_timestamp ⇒ rel/rec 0
        {"input": _RELEVANT, "_embedding": embed_text(_RELEVANT), "_timestamp": now, "_importance": 5},
    ]
    ordered, _ = agent._salience_rank_memories(mems, embed_text(_GOAL))
    assert ordered[0]["input"] == _RELEVANT
    assert ordered[-1]["input"] == "no internal salience keys"


# ---------------------------------------------------------------------------
# End-to-end DM prompt — ON reorders, OFF preserves recall order (same obs)
# ---------------------------------------------------------------------------


def _enriched_dm_observation() -> dict:
    now = time.time()
    return {
        "intent": "direct_message",
        "params": {"text": _GOAL},
        "recent_memories": [
            {"source": "direct", "verified": True, "input": _IRRELEVANT,
             "_embedding": embed_text(_IRRELEVANT), "_timestamp": now, "_importance": 5},
            {"source": "direct", "verified": True, "input": _RELEVANT,
             "_embedding": embed_text(_RELEVANT), "_timestamp": now, "_importance": 5},
        ],
    }


async def test_build_user_message_salience_on_reorders_episodic_block() -> None:
    if get_embedding_function() is None:
        pytest.skip(
            "salience reorder needs real-embedding relevance; the BF-657 lexical "
            "local fallback (CI PROBOS_EMBEDDINGS=local) cannot reorder by relevance"
        )
    agent = make_dm_agent()
    agent._runtime = _Rt(_salience_on_config())
    msg = await agent._build_user_message(_enriched_dm_observation())
    # Relevant memory (recall index 1) is promoted ABOVE the irrelevant one.
    assert msg.index(_RELEVANT) < msg.index(_IRRELEVANT)
    # Internal salience keys never leak into the prompt.
    assert "_embedding" not in msg
    assert "_timestamp" not in msg


async def test_build_user_message_salience_off_preserves_recall_order() -> None:
    agent = make_dm_agent()
    agent._runtime = _Rt(SystemConfig())  # salience scoring OFF (default)
    msg = await agent._build_user_message(_enriched_dm_observation())
    # OFF ⇒ recall order is preserved (irrelevant at index 0 stays first) and the
    # internal _embedding keys are ignored (not rendered).
    assert msg.index(_IRRELEVANT) < msg.index(_RELEVANT)
    assert "_embedding" not in msg


# ---------------------------------------------------------------------------
# Render safety — internal salience keys are never rendered
# ---------------------------------------------------------------------------


def test_format_memory_section_never_renders_internal_salience_keys() -> None:
    agent = make_dm_agent()
    mem = {
        "input": "visible memory content",
        "source": "direct",
        "verified": True,
        "_embedding": [0.123456, 0.654321, 0.111111],
        "_timestamp": 1234567890.0,
        "_importance": 9,
    }
    rendered = "\n".join(agent._format_memory_section([mem]))
    assert "visible memory content" in rendered
    assert "0.123456" not in rendered
    assert "1234567890" not in rendered
    assert "_embedding" not in rendered
    assert "_timestamp" not in rendered
    assert "_importance" not in rendered


# ---------------------------------------------------------------------------
# Working memory — bid-salience only (no internal reorder; HARD-STOP guard c)
# ---------------------------------------------------------------------------


def test_iter_salience_entries_collects_buffer_entries() -> None:
    wm = AgentWorkingMemory()
    wm.record_action("warp core status nominal", source="dm")
    wm.record_observation("coolant pressure steady", source="dm")
    contents = [e.content for e in wm.iter_salience_entries()]
    assert "warp core status nominal" in contents
    assert "coolant pressure steady" in contents


def test_iter_salience_entries_empty_when_no_activity() -> None:
    assert AgentWorkingMemory().iter_salience_entries() == []


def test_salience_score_wm_bid_none_when_no_working_memory() -> None:
    agent = make_dm_agent()  # _working_memory = None
    agent._runtime = _Rt(_salience_on_config())
    assert agent._salience_score_wm_bid(embed_text(_GOAL)) is None


def test_salience_score_wm_bid_none_when_empty() -> None:
    agent = make_dm_agent()
    agent._runtime = _Rt(_salience_on_config())
    agent._working_memory = AgentWorkingMemory()  # no entries
    assert agent._salience_score_wm_bid(embed_text(_GOAL)) is None


def test_salience_score_wm_bid_float_with_entries() -> None:
    agent = make_dm_agent()
    agent._runtime = _Rt(_salience_on_config())
    wm = AgentWorkingMemory()
    wm.record_action("warp core alignment nominal", source="dm")
    agent._working_memory = wm
    salience = agent._salience_score_wm_bid(embed_text(_GOAL))
    assert salience is not None
    assert 0.0 <= salience <= 1.0


def test_salience_score_wm_bid_does_not_reorder_render_context() -> None:
    # WM ships bid-salience-only: scoring must be read-only over render_context.
    agent = make_dm_agent()
    agent._runtime = _Rt(_salience_on_config())
    wm = AgentWorkingMemory()
    wm.record_action("warp core alignment nominal", source="dm")
    wm.record_observation("replicator menu changed", source="dm")
    agent._working_memory = wm
    # AD-1030: render_context embeds an incidental relative "(Ns ago)" token
    # (AgentWorkingMemory._format_age over time.time()). The real embed_text +
    # per-entry scoring between the two renders advances the wall clock,
    # drifting that token (e.g. "0s" -> "5s") even though the bid ORDER is
    # unchanged (the property under test). Neutralize the age token so the
    # assertion isolates reordering, not timing.
    _age_token = re.compile(r"\(\d+(?:\.\d+)?[smh] ago")
    before = _age_token.sub("(<age> ago", wm.render_context())
    agent._salience_score_wm_bid(embed_text(_GOAL))
    after = _age_token.sub("(<age> ago", wm.render_context())
    assert before == after
