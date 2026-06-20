"""AD-1037 (#986): affect-salience capture at encoding.

Covers the pure ``score_affect`` lexicon scorer, the default-OFF /
byte-identical-when-OFF capture hook in ``EpisodicMemory.store()``, the
metadata round-trip, and the dormant AD-979f rerank term that consumes the
slot. Deterministic — no embedding model, no LLM, no network (real
``_FakeCollection`` stub, not MagicMock; BF-287).
"""

from __future__ import annotations

import time

import pytest

from probos.config import MemoryConfig
from probos.types import Episode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_episode(
    *,
    user_input: str = "",
    reflection: str | None = None,
    affect_salience: float = 0.0,
    importance: int = 5,
    agent_ids: list[str] | None = None,
    outcomes: list[dict] | None = None,
) -> Episode:
    return Episode(
        id="ep-001",
        user_input=user_input,
        reflection=reflection,
        timestamp=time.time(),
        agent_ids=agent_ids if agent_ids is not None else ["agent-001"],
        source="direct",
        outcomes=outcomes
        if outcomes is not None
        else [{"intent": "test", "success": True, "response": "done"}],
        importance=importance,
        affect_salience=affect_salience,
    )


class _FakeCollection:
    """Minimal real ChromaDB-collection stub for store() (no embedding model)."""

    def __init__(self) -> None:
        self.added: list[dict] = []

    def get(self, **kwargs):  # write-once guard + rate/dedup queries -> empty
        return {"ids": []}

    def add(self, *, ids, documents, metadatas) -> None:
        self.added.append({"ids": ids, "documents": documents, "metadatas": metadatas})

    def count(self) -> int:
        return 0


def _make_memory(*, affect_capture_enabled: bool):
    """EpisodicMemory wired with just the attributes store() touches.

    Mirrors test_ad598 Test 9's ``__new__`` approach so no embedding model /
    ChromaDB client is needed; sets the AD-1037 capture flag the real
    ``__init__`` would set from its kwarg.
    """
    from probos.cognitive.episodic import EpisodicMemory

    em = EpisodicMemory.__new__(EpisodicMemory)
    em._activation_tracker = None
    em._query_reformulation_enabled = False
    em.max_episodes = 1000
    em._collection = _FakeCollection()
    em._fts_db = None
    em._participant_index = None
    em._eviction_audit = None
    em._affect_capture_enabled = affect_capture_enabled  # AD-1037
    return em


# ---------------------------------------------------------------------------
# A. score_affect purity — Tests 1-9
# ---------------------------------------------------------------------------

class TestScoreAffect:
    """Pure lexicon scorer: deterministic, [0,1], magnitude-not-valence."""

    def test_empty_episode_zero(self):
        """Test 1: empty episode -> exactly 0.0."""
        from probos.cognitive.affect_scorer import score_affect

        assert score_affect(_make_episode(user_input="")) == 0.0

    def test_neutral_text_zero(self):
        """Test 2: neutral text (no arousal words) -> 0.0."""
        from probos.cognitive.affect_scorer import score_affect

        ep = _make_episode(user_input="system status report nominal")
        assert score_affect(ep) == 0.0

    def test_one_high_word(self):
        """Test 3: one high-arousal word -> 1 - exp(-1/2) ~= 0.3935."""
        from probos.cognitive.affect_scorer import score_affect

        assert score_affect(_make_episode(user_input="thrilled")) == pytest.approx(
            0.3935, abs=1e-3
        )

    def test_two_high_words(self):
        """Test 4: two high-arousal words -> 1 - exp(-2/2) ~= 0.6321."""
        from probos.cognitive.affect_scorer import score_affect

        ep = _make_episode(user_input="thrilled ecstatic")
        assert score_affect(ep) == pytest.approx(0.6321, abs=1e-3)

    def test_one_moderate_word(self):
        """Test 5: one moderate-arousal word -> 1 - exp(-0.5/2) ~= 0.2212."""
        from probos.cognitive.affect_scorer import score_affect

        assert score_affect(_make_episode(user_input="worried")) == pytest.approx(
            0.2212, abs=1e-3
        )

    def test_magnitude_not_valence(self):
        """Test 6 (DD-3): negative and positive high words both > 0 and equal."""
        from probos.cognitive.affect_scorer import score_affect

        neg = score_affect(_make_episode(user_input="devastated"))
        pos = score_affect(_make_episode(user_input="thrilled"))
        assert neg > 0.0
        assert pos > 0.0
        assert neg == pytest.approx(pos, abs=1e-9)

    def test_exclamation_intensity(self):
        """Test 7: high word + '!!!' strictly higher than without; <= 1.0."""
        from probos.cognitive.affect_scorer import score_affect

        with_bang = score_affect(_make_episode(user_input="thrilled!!!"))
        without = score_affect(_make_episode(user_input="thrilled"))
        assert with_bang > without
        assert with_bang <= 1.0

    def test_monotonic_increasing(self):
        """Test 8: more affect words -> strictly higher; all in [0,1]."""
        from probos.cognitive.affect_scorer import score_affect

        one = score_affect(_make_episode(user_input="thrilled"))
        two = score_affect(_make_episode(user_input="thrilled ecstatic"))
        three = score_affect(_make_episode(user_input="thrilled ecstatic elated"))
        assert one < two < three
        for v in (one, two, three):
            assert 0.0 <= v <= 1.0

    def test_orthogonal_to_importance(self):
        """Test 9 (DD-2): importance-vocabulary but no affect words -> 0.0."""
        from probos.cognitive.affect_scorer import score_affect

        ep = _make_episode(
            user_input="[1:1 with Captain]: routine status check on crew rotation, nominal",
        )
        assert score_affect(ep) == 0.0


# ---------------------------------------------------------------------------
# B. capture-in-store() — Tests 10-12
# ---------------------------------------------------------------------------

class TestCaptureInStore:
    """The default-OFF capture hook inside EpisodicMemory.store()."""

    @pytest.mark.asyncio
    async def test_flag_on_captures_affect(self):
        """Test 10: flag True + high-affect episode -> metadata affect_salience > 0."""
        em = _make_memory(affect_capture_enabled=True)
        ep = _make_episode(
            user_input="I am absolutely thrilled and ecstatic about this breakthrough!",
        )
        await em.store(ep)

        meta = em._collection.added[0]["metadatas"][0]
        assert meta["affect_salience"] > 0.0

    @pytest.mark.asyncio
    async def test_flag_off_byte_identical(self):
        """Test 11: flag False + same high-affect episode -> 0.0 (scorer never invoked)."""
        em = _make_memory(affect_capture_enabled=False)
        ep = _make_episode(
            user_input="I am absolutely thrilled and ecstatic about this breakthrough!",
        )
        await em.store(ep)

        meta = em._collection.added[0]["metadatas"][0]
        assert meta["affect_salience"] == 0.0

    @pytest.mark.asyncio
    async def test_caller_set_value_respected(self):
        """Test 12: flag True but caller already set affect_salience=0.5 -> stays 0.5."""
        em = _make_memory(affect_capture_enabled=True)
        ep = _make_episode(
            user_input="thrilled ecstatic devastated furious",  # would score high
            affect_salience=0.5,
        )
        await em.store(ep)

        meta = em._collection.added[0]["metadatas"][0]
        assert meta["affect_salience"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# C. metadata round-trip — Test 13
# ---------------------------------------------------------------------------

class TestMetadataRoundTrip:
    """affect_salience survives _episode_to_metadata -> _metadata_to_episode."""

    def test_affect_salience_roundtrip(self):
        """Test 13: affect_salience=0.7 survives the metadata round-trip."""
        from probos.cognitive.episodic import EpisodicMemory

        ep = _make_episode(affect_salience=0.7)
        metadata = EpisodicMemory._episode_to_metadata(ep)
        doc = EpisodicMemory._prepare_document(ep)
        restored = EpisodicMemory._metadata_to_episode(ep.id, doc, metadata)
        assert restored.affect_salience == pytest.approx(0.7)


# ---------------------------------------------------------------------------
# D. ranking e2e (pure _composite_recall_score staticmethod) — Tests 14-15
# ---------------------------------------------------------------------------

class TestRankingE2E:
    """The AD-979f affect rerank term: only when its weight is > 0."""

    def test_affect_weight_boosts_high(self):
        """Test 14: weight affect=1.0 -> high-affect episode ranks above neutral."""
        from probos.cognitive.episodic import EpisodicMemory

        now = time.time()
        ep_hi = _make_episode(affect_salience=0.8)
        ep_neutral = _make_episode(affect_salience=0.0)
        weights = {"affect": 1.0}
        s_hi = EpisodicMemory._composite_recall_score(0.6, ep_hi, weights, now)
        s_neutral = EpisodicMemory._composite_recall_score(0.6, ep_neutral, weights, now)
        assert s_hi > s_neutral

    def test_affect_weight_zero_byte_identical(self):
        """Test 15: weight affect=0.0 -> scores equal (byte-identical OFF at ranking)."""
        from probos.cognitive.episodic import EpisodicMemory

        now = time.time()
        ep_hi = _make_episode(affect_salience=0.8)
        ep_neutral = _make_episode(affect_salience=0.0)
        weights = {"affect": 0.0}
        s_hi = EpisodicMemory._composite_recall_score(0.6, ep_hi, weights, now)
        s_neutral = EpisodicMemory._composite_recall_score(0.6, ep_neutral, weights, now)
        assert s_hi == s_neutral


# ---------------------------------------------------------------------------
# E. default-OFF structural — Test 16
# ---------------------------------------------------------------------------

class TestDefaultOff:
    """The capture gate is off by default."""

    def test_config_default_false(self):
        """Test 16: MemoryConfig().affect_capture_enabled is False."""
        assert MemoryConfig().affect_capture_enabled is False
