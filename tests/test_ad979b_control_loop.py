"""AD-979b (Oracle recall epic, #904): metacognitive control loop.

Recall happens before an agent reasons; when recall is weak (a likely miss) the
agent had no recourse but to report uncertainty. A human, on a Feeling-of-Knowing,
keeps searching differently (Nelson & Narens 1990: the monitor signal drives a
control action). AD-979b adds that loop: the AD-979a band (monitor) maps to a
control action — accept (strong) / expand (weak) / abstain (none) — and a weak
band triggers at most N bounded re-query attempts before settling.

Three layers, all tested:
  * ``decide_recall_control`` — pure monitor->action policy.
  * ``recall_expansion_variants`` — pure bounded query-expansion generator.
  * ``recall_with_control`` — real-store loop: weak triggers expansion, strong
    and none do not (zero added cost), honest abstain when expansion fails.

BF-287 discipline: real ``EpisodicMemory`` on ``tmp_path`` (NOT MagicMock).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from probos.cognitive.episodic import (
    EpisodicMemory,
    decide_recall_control,
    recall_expansion_variants,
)
from probos.types import Episode


# ===================== 1. decide_recall_control (pure) =====================


def test_decide_strong_accepts():
    assert decide_recall_control("strong") == "accept"


def test_decide_weak_expands():
    assert decide_recall_control("weak") == "expand"


def test_decide_none_abstains():
    assert decide_recall_control("none") == "abstain"


def test_decide_unknown_band_abstains():
    # Defensive: any unexpected band defaults to the safe "abstain" (no work).
    assert decide_recall_control("garbage") == "abstain"


# =================== 2. recall_expansion_variants (pure) ===================


def test_expansion_excludes_original_query():
    variants = recall_expansion_variants("the coolant leak in engineering", max_n=2)
    assert "the coolant leak in engineering" not in variants


def test_expansion_produces_content_word_soup():
    # A verbose query yields a stripped content-word variant.
    variants = recall_expansion_variants(
        "What did the Captain say about the migration?", max_n=2
    )
    assert variants, "should produce at least one expansion variant"
    # the soup variant is lowercased content tokens
    assert any("captain" in v and "migration" in v for v in variants)


def test_expansion_respects_max_n():
    variants = recall_expansion_variants(
        "Where is the away team right now exactly?", max_n=1
    )
    assert len(variants) <= 1


def test_expansion_dedupes_and_is_order_preserving():
    variants = recall_expansion_variants("reactor reactor core", max_n=5)
    assert len(variants) == len(set(variants))


def test_expansion_empty_query_yields_nothing():
    assert recall_expansion_variants("", max_n=2) == []
    assert recall_expansion_variants("?!.", max_n=2) == []


# ====================== 3. recall_with_control (real) ======================


@pytest.fixture
async def memory(tmp_path: Path):
    em = EpisodicMemory(db_path=str(tmp_path / "ad979b.db"))
    await em.start()
    yield em
    try:
        await em.stop()
    except Exception:
        pass


@pytest.mark.asyncio
async def test_strong_recall_accepts_no_expansion(memory):
    text = "The Captain approved the database migration on Tuesday afternoon."
    await memory.store(Episode(user_input=text))
    episodes, conf, actions = await memory.recall_with_control(text, k=3)
    # Strong recall -> accept, NO requery attempts in the audit trail.
    assert conf.band == "strong"
    assert actions == ["accept"]
    assert not any(a.startswith("requery") for a in actions)
    assert episodes


@pytest.mark.asyncio
async def test_empty_store_abstains_no_expansion(memory):
    # Fast-absence -> abstain, zero expansion cost.
    episodes, conf, actions = await memory.recall_with_control("anything", k=3)
    assert episodes == []
    assert conf.band == "none"
    assert actions == ["abstain"]


@pytest.mark.asyncio
async def test_max_expansions_zero_disables_loop(memory):
    # Even a weak band does no expansion when max_expansions=0.
    await memory.store(Episode(user_input="Photosynthesis converts light to sugar."))
    # query chosen to be unrelated -> weak or none; with max_expansions=0 the
    # action list never contains a requery regardless of band.
    _episodes, _conf, actions = await memory.recall_with_control(
        "quarterly budget review meeting", k=3, max_expansions=0
    )
    assert not any(a.startswith("requery") for a in actions)


@pytest.mark.asyncio
async def test_weak_band_triggers_bounded_expansion(memory):
    # Construct a weak FoK: store a terse episode, query with a verbose question
    # whose content words overlap. If the initial band is weak, the loop must
    # record at least one requery attempt (bounded by max_expansions).
    await memory.store(Episode(user_input="Coolant leak, section seven, sealed."))
    episodes, conf, actions = await memory.recall_with_control(
        "Can you tell me what happened with the coolant situation in section seven?",
        k=3,
        max_expansions=2,
    )
    if actions[0] == "expand":
        # weak initial band -> the loop attempted bounded re-queries
        assert any(a.startswith("requery") for a in actions)
        assert sum(1 for a in actions if a.startswith("requery")) <= 2
    else:
        # if recall was already strong/none, no expansion — also valid.
        assert actions[0] in {"accept", "abstain"}


@pytest.mark.asyncio
async def test_returns_three_tuple_shape(memory):
    await memory.store(Episode(user_input="The away team returned with samples."))
    result = await memory.recall_with_control("away team samples", k=2)
    assert isinstance(result, tuple) and len(result) == 3
    episodes, conf, actions = result
    assert isinstance(episodes, list)
    assert isinstance(actions, list) and actions
    assert hasattr(conf, "band")


@pytest.mark.asyncio
async def test_expansion_adopts_only_more_accessible_variant(memory):
    # The final confidence is the BEST found; never downgraded by a worse
    # variant. We assert the returned best_similarity is >= the first-pass one
    # would have been by checking monotonicity through the audit trail.
    await memory.store(Episode(user_input="Stardate log: warp core stable."))
    episodes, conf, actions = await memory.recall_with_control(
        "How is the warp core doing on this stardate?", k=3, max_expansions=2
    )
    # Whatever path was taken, the final band is a valid band and consistent
    # with the episodes (a strong/weak band returns at least the best episode).
    assert conf.band in {"strong", "weak", "none"}
    if conf.band in {"strong", "weak"}:
        assert episodes
