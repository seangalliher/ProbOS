"""AD-988 (#932): Retrieval-reason transparency — surface *why* an episodic
fragment was retrieved.

The episodic tier computes a full ``RecallScore`` breakdown and the Oracle
collapses it to one scalar (``composite_score``). This wave projects the
*dominant* recall signal back out as ``OracleResult.match_reason`` and surfaces
it in ``query_formatted`` — gated default-OFF so the Oracle is byte-identical to
pre-AD-988 when the flag is off (the Counselor's 2026-06-13 "I can tell it's
reaching but not why" gap).

BF-287 discipline: real ``RecallScore`` / ``OracleResult`` / ``MemoryConfig`` /
``OracleService`` / ``Episode`` throughout; no MagicMock at these boundaries.
The only stubs are minimal episodic / records doubles returning real objects.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import probos.cognitive.oracle_service as oracle_mod
from probos.cognitive.oracle_service import OracleResult, OracleService
from probos.config import MemoryConfig
from probos.types import Episode, RecallScore, dominant_match_reason

FIXED_NOW = 1_000_000.0


# ---------------------------------------------------------------------------
# Helpers / real-object doubles
# ---------------------------------------------------------------------------


def _rs(**over) -> RecallScore:
    """Build a RecallScore with every signal explicitly zeroed unless
    overridden (RecallScore's own defaults set trust/hebbian to 0.5, which
    would otherwise dominate the all-zero / single-signal cases)."""
    base = dict(
        episode=Episode(id="ep", user_input="x"),
        semantic_similarity=0.0,
        keyword_hits=0,
        trust_weight=0.0,
        hebbian_weight=0.0,
        recency_weight=0.0,
        anchor_confidence=0.0,
        tcm_similarity=0.0,
        composite_score=0.0,
    )
    base.update(over)
    return RecallScore(**base)  # type: ignore[arg-type]


@dataclass
class _FakeWeightedMemory:
    """Episodic-memory double exposing recall_weighted (the scored path)."""

    scored: list[RecallScore]

    async def recall_weighted(
        self,
        agent_id,
        query_text,
        *,
        trust_network=None,
        hebbian_router=None,
        intent_type="",
        k=5,
        context_budget=0,
    ) -> list[RecallScore]:
        return list(self.scored)


@dataclass
class _FakeUnscoredMemory:
    """Episodic-memory double exposing only recall (no RecallScore breakdown —
    mirrors the elif site that has score=0.5 and no RecallScore)."""

    episodes: list[Episode]

    async def recall(self, query_text, *, k=5) -> list[Episode]:
        return list(self.episodes)


@dataclass
class _FakeRecordsStore:
    """Records-tier double exposing search (non-episodic; never carries a
    match_reason)."""

    rows: list[dict]

    async def search(self, query_text, scope="ship") -> list[dict]:
        return list(self.rows)


# ---------------------------------------------------------------------------
# 1. dominant_match_reason — pure heuristic
# ---------------------------------------------------------------------------


def test_dominant_match_reason_keyword_plural():
    assert dominant_match_reason(_rs(keyword_hits=2)) == "keyword match (2 hits)"


def test_dominant_match_reason_keyword_singular():
    assert dominant_match_reason(_rs(keyword_hits=1)) == "keyword match (1 hit)"


def test_dominant_match_reason_keyword_wins_over_larger_graded_signal():
    # Lexical/FTS5 is the strongest *explicit* signal: it wins even when a
    # graded signal is numerically larger.
    rs = _rs(keyword_hits=1, semantic_similarity=0.99)
    assert dominant_match_reason(rs) == "keyword match (1 hit)"


def test_dominant_match_reason_semantic_dominant():
    rs = _rs(semantic_similarity=0.83, hebbian_weight=0.2, anchor_confidence=0.1)
    assert dominant_match_reason(rs) == "semantic similarity (0.83)"


def test_dominant_match_reason_hebbian_dominant():
    rs = _rs(hebbian_weight=0.7, semantic_similarity=0.3, anchor_confidence=0.1)
    assert dominant_match_reason(rs) == "Hebbian co-activation (0.70)"


def test_dominant_match_reason_anchor_dominant():
    rs = _rs(anchor_confidence=0.6, semantic_similarity=0.1, hebbian_weight=0.2)
    assert dominant_match_reason(rs) == "anchored context (0.60)"


def test_dominant_match_reason_recency_dominant():
    rs = _rs(recency_weight=0.55)
    assert dominant_match_reason(rs) == "recency (0.55)"


def test_dominant_match_reason_tcm_dominant():
    rs = _rs(tcm_similarity=0.45)
    assert dominant_match_reason(rs) == "temporal context (0.45)"


def test_dominant_match_reason_all_zero_is_weak():
    # Degenerate "it's reaching" case the Counselor flagged.
    assert dominant_match_reason(_rs()) == "weak/ambiguous match"


def test_dominant_match_reason_trust_weight_excluded():
    # trust_weight is a weighting, not a match reason: a high trust with no
    # match signal must still read as weak/ambiguous.
    rs = _rs(trust_weight=0.99)
    assert dominant_match_reason(rs) == "weak/ambiguous match"


def test_dominant_match_reason_tie_is_stable_first_signal_wins():
    # Equal semantic and hebbian: the first in the priority order wins.
    rs = _rs(semantic_similarity=0.5, hebbian_weight=0.5)
    assert dominant_match_reason(rs) == "semantic similarity (0.50)"


# ---------------------------------------------------------------------------
# 2. Episodic OracleResult carries the reason ON / "" OFF
# ---------------------------------------------------------------------------


def _episodic_results(*, enabled: bool, scored: list[RecallScore]) -> list[OracleResult]:
    svc = OracleService(
        episodic_memory=_FakeWeightedMemory(scored=scored),
        match_reason_enabled=enabled,
    )
    return asyncio.run(
        svc.query("anything", agent_id="alice", tiers=["episodic"])
    )


def test_episodic_result_carries_reason_when_enabled():
    scored = [_rs(episode=Episode(id="ep-1", user_input="hi"), keyword_hits=2,
                  composite_score=0.42)]
    results = _episodic_results(enabled=True, scored=scored)
    assert len(results) == 1
    assert results[0].source_tier == "episodic"
    assert results[0].match_reason == "keyword match (2 hits)"


def test_episodic_result_no_reason_when_disabled():
    scored = [_rs(episode=Episode(id="ep-1", user_input="hi"), keyword_hits=2,
                  composite_score=0.42)]
    results = _episodic_results(enabled=False, scored=scored)
    assert len(results) == 1
    assert results[0].match_reason == ""


def test_episodic_result_semantic_reason_when_enabled():
    scored = [_rs(episode=Episode(id="ep-2", user_input="hi"),
                  semantic_similarity=0.71, hebbian_weight=0.2,
                  composite_score=0.6)]
    results = _episodic_results(enabled=True, scored=scored)
    assert results[0].match_reason == "semantic similarity (0.71)"


def test_episodic_unscored_fallback_has_no_reason_even_when_enabled():
    # The recall() fallback site has no RecallScore; match_reason stays "".
    svc = OracleService(
        episodic_memory=_FakeUnscoredMemory(episodes=[Episode(id="e", user_input="hi")]),
        match_reason_enabled=True,
    )
    results = asyncio.run(svc.query("q", agent_id="alice", tiers=["episodic"]))
    assert len(results) == 1
    assert results[0].match_reason == ""


# ---------------------------------------------------------------------------
# 3. query_formatted — byte-identical OFF, surfaces reason ON
# ---------------------------------------------------------------------------


def _formatted(*, enabled: bool, monkeypatch) -> str:
    monkeypatch.setattr(oracle_mod.time, "time", lambda: FIXED_NOW)
    scored = [
        _rs(
            episode=Episode(
                id="ep-1",
                user_input="Yeo visual style",
                timestamp=FIXED_NOW - 120.0,  # -> "2m ago"
                agent_ids=["alice"],
                source="chat",
            ),
            keyword_hits=2,
            composite_score=0.42,
        )
    ]
    svc = OracleService(
        episodic_memory=_FakeWeightedMemory(scored=scored),
        match_reason_enabled=enabled,
    )
    return asyncio.run(
        svc.query_formatted("Yeo", agent_id="alice", tiers=["episodic"])
    )


def test_query_formatted_byte_identical_when_disabled(monkeypatch):
    out = _formatted(enabled=False, monkeypatch=monkeypatch)
    expected = (
        "=== ORACLE QUERY RESULTS ===\n"
        "[episodic memory] (score: 0.42, 2m ago) Yeo visual style\n"
        "=== END ORACLE RESULTS ==="
    )
    assert out == expected
    assert "why:" not in out


def test_query_formatted_surfaces_reason_when_enabled(monkeypatch):
    out = _formatted(enabled=True, monkeypatch=monkeypatch)
    expected = (
        "=== ORACLE QUERY RESULTS ===\n"
        "[episodic memory] (score: 0.42, 2m ago, why: keyword match (2 hits)) "
        "Yeo visual style\n"
        "=== END ORACLE RESULTS ==="
    )
    assert out == expected


def test_query_formatted_on_equals_off_plus_why_clause(monkeypatch):
    # Cross-check: removing the why-clause from the ON output yields the
    # byte-identical OFF output.
    off = _formatted(enabled=False, monkeypatch=monkeypatch)
    on = _formatted(enabled=True, monkeypatch=monkeypatch)
    assert on.replace(", why: keyword match (2 hits)", "") == off


# ---------------------------------------------------------------------------
# 4. Non-episodic tiers never carry a match_reason (no regression)
# ---------------------------------------------------------------------------


def test_non_episodic_records_result_has_empty_reason_even_when_enabled():
    svc = OracleService(
        episodic_memory=_FakeWeightedMemory(
            scored=[_rs(episode=Episode(id="ep-1", user_input="hi"),
                        keyword_hits=3, composite_score=0.9)]
        ),
        records_store=_FakeRecordsStore(
            rows=[{"score": 8, "snippet": "record snippet", "path": "ship/log.md"}]
        ),
        match_reason_enabled=True,
    )
    results = asyncio.run(
        svc.query("q", agent_id="alice", tiers=["episodic", "records"])
    )
    by_tier = {r.source_tier: r for r in results}
    assert by_tier["episodic"].match_reason == "keyword match (3 hits)"
    assert by_tier["records"].match_reason == ""


def test_oracle_result_match_reason_defaults_empty():
    r = OracleResult(
        source_tier="records",
        content="x",
        score=0.5,
        metadata={},
        provenance="[ship's records]",
    )
    assert r.match_reason == ""


# ---------------------------------------------------------------------------
# 5. Config default is OFF
# ---------------------------------------------------------------------------


def test_memory_config_default_is_off():
    assert MemoryConfig().oracle_match_reason_enabled is False
