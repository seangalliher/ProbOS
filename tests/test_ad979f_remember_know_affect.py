"""AD-979f (Oracle recall epic, #908): Remember/Know recall typing (A) +
affective-salience rerank slot/axis (B3).

A — a PURE classifier (Tulving 1985 remember/know) on
``RecallConfidence.recall_type``, gated ``remember_know_typing_enabled``
(default False -> ``recall_type`` stays ``""`` -> byte-identical).

B3 — an ``Episode.affect_salience`` storage slot [0,1] + an affect term in the
AD-873 composite reranker, gated by ``recall_rerank_weights["affect"]`` (default
0.0 -> term skipped -> byte-identical). This ships the AXIS + SLOT only; what
POPULATES ``affect_salience`` is a deferred capture AD — there is NO capture
pipeline here, so the mechanism is exercised with hand-built real Episodes.

BF-287 discipline: real ``Episode``, real ``RecallConfidence``, real
``MemoryConfig``, real ``EpisodicMemory`` on ``tmp_path`` with real ONNX MiniLM
embeddings (NO MagicMock). Integration band assertions assert membership rather
than a hard-coded embedding-fragile band.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from probos.cognitive.episodic import (
    EpisodicMemory,
    RecallConfidence,
    classify_remember_know,
    remember_know_phrase,
)
from probos.config import MemoryConfig
from probos.types import AnchorFrame, Episode


# ===================== B3: affect rerank term (pure) =====================


def test_affect_term_raises_high_salience_episode():
    """A high affect_salience episode outscores a low one at equal similarity."""
    now = time.time()
    ep_hi = Episode(timestamp=now, user_input="x", affect_salience=0.9)
    ep_lo = Episode(timestamp=now, user_input="x", affect_salience=0.1)
    weights = {"affect": 1.0}
    s_hi = EpisodicMemory._composite_recall_score(0.8, ep_hi, weights, now)
    s_lo = EpisodicMemory._composite_recall_score(0.8, ep_lo, weights, now)
    assert s_hi > s_lo


def test_affect_absent_is_byte_identical():
    """No 'affect' key -> term never reads affect_salience -> today's score.

    The affect FIELD is set high (0.9) but a weights dict WITHOUT an 'affect'
    key must not perturb the composite — proving the slot cannot leak into the
    score unless the operator opts in.
    """
    now = time.time()
    ep = Episode(timestamp=now, user_input="x", affect_salience=0.9)
    s_strength_only = EpisodicMemory._composite_recall_score(
        0.8, ep, {"strength": 1.0}, now
    )
    s_with_zero_affect = EpisodicMemory._composite_recall_score(
        0.8, ep, {"strength": 1.0, "affect": 0.0}, now
    )
    assert s_with_zero_affect == s_strength_only


def test_affect_weight_zero_equals_no_affect():
    """affect weight 0.0 skips the term (x**0 == 1 idiom) -> equals no-affect."""
    now = time.time()
    ep_hi = Episode(timestamp=now, user_input="x", affect_salience=0.9)
    ep_lo = Episode(timestamp=now, user_input="x", affect_salience=0.1)
    s_hi = EpisodicMemory._composite_recall_score(0.8, ep_hi, {"affect": 0.0}, now)
    s_lo = EpisodicMemory._composite_recall_score(0.8, ep_lo, {"affect": 0.0}, now)
    assert s_hi == s_lo == pytest.approx(0.8)


def test_empty_weights_reproduce_similarity_with_affect_field_set():
    """Neutral (empty) weights -> composite == similarity even with affect set."""
    now = time.time()
    ep = Episode(timestamp=now, user_input="x", affect_salience=0.9)
    assert EpisodicMemory._composite_recall_score(0.75, ep, {}, now) == pytest.approx(
        0.75
    )


# ===================== B3: affect_salience metadata round-trip =====================


def test_metadata_round_trip_preserves_affect_salience():
    ep = Episode(user_input="An emotionally salient memory.", affect_salience=0.73)
    meta = EpisodicMemory._episode_to_metadata(ep)
    assert meta["affect_salience"] == pytest.approx(0.73)
    restored = EpisodicMemory._metadata_to_episode(ep.id, "", meta)
    assert restored.affect_salience == pytest.approx(0.73)


def test_metadata_missing_affect_key_degrades_to_zero():
    """Pre-AD-979f episodes (no affect_salience key) -> 0.0 honest-degrade."""
    meta = EpisodicMemory._episode_to_metadata(Episode(user_input="legacy"))
    del meta["affect_salience"]  # simulate the pre-979f stored shape
    restored = EpisodicMemory._metadata_to_episode("legacy-id", "", meta)
    assert restored.affect_salience == 0.0


def test_metadata_bad_affect_value_degrades_to_zero():
    """A non-numeric affect_salience value -> 0.0 (TypeError/ValueError guard)."""
    meta = EpisodicMemory._episode_to_metadata(Episode(user_input="x"))
    meta["affect_salience"] = "not-a-number"
    restored = EpisodicMemory._metadata_to_episode("x-id", "", meta)
    assert restored.affect_salience == 0.0


# ===================== A: remember/know classifier (pure) =====================


def _grounded_anchors() -> AnchorFrame:
    return AnchorFrame(channel="dm", trigger_agent="captain")


def test_classify_strong_grounded_is_remember():
    ep = Episode(user_input="x", anchors=_grounded_anchors(), source="direct")
    assert classify_remember_know("strong", ep) == "remember"


def test_classify_strong_reflection_is_know():
    # Strong + grounded, but a reflection (dream synthesis) is familiarity, not
    # episodic re-experiencing.
    ep = Episode(user_input="x", anchors=_grounded_anchors(), source="reflection")
    assert classify_remember_know("strong", ep) == "know"


def test_classify_strong_no_anchors_is_know():
    ep = Episode(user_input="x", anchors=None, source="direct")
    assert classify_remember_know("strong", ep) == "know"


def test_classify_strong_empty_anchors_is_know():
    # Anchors present but no grounding fields -> not episodically grounded.
    ep = Episode(user_input="x", anchors=AnchorFrame(), source="direct")
    assert classify_remember_know("strong", ep) == "know"


def test_classify_weak_band_is_know():
    ep = Episode(user_input="x", anchors=_grounded_anchors(), source="direct")
    assert classify_remember_know("weak", ep) == "know"


def test_classify_none_band_is_none():
    ep = Episode(user_input="x", anchors=_grounded_anchors())
    assert classify_remember_know("none", ep) == "none"


def test_classify_none_episode_is_none():
    assert classify_remember_know("strong", None) == "none"
    assert classify_remember_know("none", None) == "none"


def test_classify_each_grounding_field_alone_grounds():
    # Any ONE of the four grounding fields is sufficient for episodic grounding.
    for anchors in (
        AnchorFrame(channel="dm"),
        AnchorFrame(participants=["captain"]),
        AnchorFrame(trigger_agent="captain"),
        AnchorFrame(source_timestamp=123.0),
    ):
        ep = Episode(user_input="x", anchors=anchors, source="direct")
        assert classify_remember_know("strong", ep) == "remember"


# ===================== A: phrase formatter (pure) =====================


def test_remember_know_phrase_all_types():
    assert remember_know_phrase("remember") == "I recall the specifics"
    assert remember_know_phrase("know") == (
        "this feels familiar but I can't place the specifics"
    )
    assert remember_know_phrase("none") == "I have no memory of this"
    assert remember_know_phrase("") == ""
    assert remember_know_phrase("garbage") == ""


# ===================== A+B3: config defaults (off / byte-identical) =====================


def test_config_defaults_are_off_and_byte_identical():
    cfg = MemoryConfig()
    assert cfg.remember_know_typing_enabled is False
    assert cfg.recall_rerank_weights["affect"] == 0.0


# ===================== A: integration on real EpisodicMemory =====================


@pytest.fixture
async def memory_off(tmp_path: Path):
    em = EpisodicMemory(db_path=str(tmp_path / "ad979f_off.db"))
    await em.start()
    yield em
    try:
        await em.stop()
    except Exception:
        pass


@pytest.fixture
async def memory_on(tmp_path: Path):
    em = EpisodicMemory(
        db_path=str(tmp_path / "ad979f_on.db"),
        remember_know_typing_enabled=True,
    )
    await em.start()
    yield em
    try:
        await em.stop()
    except Exception:
        pass


@pytest.mark.asyncio
async def test_recall_with_confidence_typing_off_is_empty(memory_off):
    # Flag OFF -> recall_type "" (byte-identical to AD-979a behavior).
    text = "The Captain approved the database migration on Tuesday."
    await memory_off.store(
        Episode(
            user_input=text,
            anchors=AnchorFrame(channel="dm", trigger_agent="captain"),
        )
    )
    _episodes, conf = await memory_off.recall_with_confidence(text, k=5)
    assert isinstance(conf, RecallConfidence)
    assert conf.recall_type == ""


@pytest.mark.asyncio
async def test_recall_with_confidence_typing_on_classifies(memory_on):
    text = "The Captain approved the database migration on Tuesday afternoon."
    await memory_on.store(
        Episode(
            user_input=text,
            anchors=AnchorFrame(channel="dm", trigger_agent="captain"),
        )
    )
    _episodes, conf = await memory_on.recall_with_confidence(text, k=5)
    # Self-query -> strong band; grounded anchors -> "remember". Assert
    # membership (robust to embedding drift).
    assert conf.recall_type in {"remember", "know"}


@pytest.mark.asyncio
async def test_recall_with_confidence_typing_on_empty_store_unchanged(memory_on):
    # The empty-store fast-absence path returns early (the count==0 guard, before
    # the typing hook), so recall_type stays "" even with typing ON — the
    # early-return paths are byte-identical; the classifier runs only on the main
    # recall path.
    _episodes, conf = await memory_on.recall_with_confidence("nothing stored yet", k=5)
    assert conf.band == "none"
    assert conf.recall_type == ""


@pytest.mark.asyncio
async def test_recall_with_confidence_typing_on_unrelated_query(memory_on):
    # A populated store + an unrelated query goes through the MAIN path; the
    # classifier maps band none->"none" (slow-gap) and weak->"know". Either is a
    # valid typed signal (robust to embedding drift) — never "remember" without a
    # strong grounded top.
    await memory_on.store(Episode(user_input="The shuttle bay doors are sealed."))
    _episodes, conf = await memory_on.recall_with_confidence(
        "medieval tapestry weaving techniques", k=3
    )
    assert conf.recall_type in {"none", "know"}


@pytest.mark.asyncio
async def test_recall_for_agent_typing_off_is_empty(memory_off):
    # Sovereign path, flag OFF -> recall_type "" (byte-identical to AD-981a).
    text = "Engineering logged a coolant flush in section seven."
    await memory_off.store(
        Episode(
            user_input=text,
            agent_ids=["zeus"],
            anchors=AnchorFrame(channel="dm", trigger_agent="captain"),
        )
    )
    _episodes, conf = await memory_off.recall_for_agent_with_confidence(
        "zeus", text, k=5
    )
    assert conf.recall_type == ""


@pytest.mark.asyncio
async def test_recall_for_agent_typing_on_classifies(memory_on):
    text = "Engineering logged a coolant flush in section seven."
    await memory_on.store(
        Episode(
            user_input=text,
            agent_ids=["zeus"],
            anchors=AnchorFrame(channel="dm", trigger_agent="captain"),
        )
    )
    _episodes, conf = await memory_on.recall_for_agent_with_confidence(
        "zeus", text, k=5
    )
    assert conf.recall_type in {"remember", "know"}
