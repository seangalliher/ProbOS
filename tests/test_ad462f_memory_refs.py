"""AD-462f: Memory Architecture — Optimized Memory Representation.

Tests cover the retrieval-as-pointers projection layer:
  - MemoryRef dataclass shape + hashability
  - OracleService.query_refs() projection + LRU population
  - OracleService.resolve_ref() cache hit/miss
  - OracleService.format_refs() rendering caps
  - _query_oracle_refs QUERY op (gate, success, failure modes)
  - _derive_ref_id stable-key derivation per tier

Wave 73 / GH #58. 14 tests target +14 (window [+11, +15] → 11458–11462).
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.oracle_service import (
    _MEMORY_REF_CACHE_SIZE,
    _derive_ref_id,
    OracleResult,
    OracleService,
)
from probos.cognitive.sub_tasks.query import _query_oracle_refs
from probos.earned_agency import RecallTier
from probos.events import EventType
from probos.types import MemoryRef


def _make_result(tier: str, content: str, score: float, **md: Any) -> OracleResult:
    return OracleResult(
        source_tier=tier, content=content, score=score,
        metadata=dict(md), provenance=f"[{tier}]",
    )


def _make_oracle_with_results(results: list[OracleResult]) -> OracleService:
    """Build an OracleService whose query() returns a fixed list."""
    svc = OracleService()
    svc.query = AsyncMock(return_value=results)  # type: ignore[method-assign]
    return svc


# --- 1. MemoryRef dataclass shape + hashability ---

def test_memory_ref_is_frozen_and_hashable():
    ref = MemoryRef(
        ref_id="episodic:abc", tier="episodic", score=0.9,
        snippet="hello", provenance="[episodic]",
    )
    with pytest.raises(Exception):
        ref.score = 0.5  # type: ignore[misc]
    # Hashable
    assert {ref} == {ref}
    # Eq by ref_id (full-tuple eq, but ref_id drives identity in practice)
    other = MemoryRef(
        ref_id="episodic:abc", tier="episodic", score=0.9,
        snippet="hello", provenance="[episodic]",
    )
    assert ref == other


# --- 2. _derive_ref_id per tier ---

def test_derive_ref_id_episodic_uses_episode_id():
    r = _make_result("episodic", "x", 0.5, episode_id="ep_42")
    assert _derive_ref_id(r, 0) == "episodic:ep_42"


def test_derive_ref_id_records_uses_path():
    r = _make_result("records", "x", 0.5, path="ship_records/foo.md")
    assert _derive_ref_id(r, 0) == "records:ship_records/foo.md"


def test_derive_ref_id_graph_uses_edge_id():
    r = _make_result("graph", "x", 0.5, edge_id="e_99")
    assert _derive_ref_id(r, 0) == "graph:e_99"


def test_derive_ref_id_falls_back_to_idx_when_metadata_empty():
    r = _make_result("episodic", "x", 0.5)
    assert _derive_ref_id(r, 7) == "episodic:idx7"


# --- 3. query_refs projection + LRU population ---

@pytest.mark.asyncio
async def test_query_refs_projects_results_to_memory_refs():
    results = [
        _make_result("episodic", "alpha content", 0.9, episode_id="ep_1", timestamp=100.0),
        _make_result("graph", "beta content", 0.7, edge_id="e_5"),
    ]
    svc = _make_oracle_with_results(results)
    refs = await svc.query_refs("test query")
    assert len(refs) == 2
    assert refs[0].ref_id == "episodic:ep_1"
    assert refs[0].snippet == "alpha content"
    assert refs[0].timestamp == 100.0
    assert refs[1].tier == "graph"
    # LRU populated
    assert "episodic:ep_1" in svc._ref_cache
    assert "graph:e_5" in svc._ref_cache


@pytest.mark.asyncio
async def test_query_refs_empty_query_returns_empty_list_no_query_call():
    svc = _make_oracle_with_results([])
    refs = await svc.query_refs("")
    assert refs == []
    svc.query.assert_not_called()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_query_refs_truncates_snippet_to_200_chars():
    long = "x" * 500
    svc = _make_oracle_with_results([_make_result("episodic", long, 0.5, episode_id="e1")])
    refs = await svc.query_refs("q")
    assert len(refs[0].snippet) == 200


# --- 4. resolve_ref cache hit/miss ---

@pytest.mark.asyncio
async def test_resolve_ref_returns_full_result_on_hit():
    full = _make_result("episodic", "full body", 0.9, episode_id="ep_1")
    svc = _make_oracle_with_results([full])
    refs = await svc.query_refs("q")
    resolved = svc.resolve_ref(refs[0].ref_id)
    assert resolved is full
    assert resolved.content == "full body"


def test_resolve_ref_returns_none_on_miss():
    svc = OracleService()
    assert svc.resolve_ref("episodic:nope") is None
    assert svc.resolve_ref("") is None


@pytest.mark.asyncio
async def test_query_refs_lru_evicts_oldest_at_cap():
    # Pack the cache to exactly _MEMORY_REF_CACHE_SIZE + 5 entries; oldest 5 should evict.
    cap = _MEMORY_REF_CACHE_SIZE
    overflow = 5
    results = [
        _make_result("episodic", f"c{i}", 0.5, episode_id=f"ep_{i}")
        for i in range(cap + overflow)
    ]
    svc = _make_oracle_with_results(results)
    await svc.query_refs("q")
    assert len(svc._ref_cache) == cap
    # Oldest 5 (ep_0..ep_4) should be gone
    assert "episodic:ep_0" not in svc._ref_cache
    assert "episodic:ep_4" not in svc._ref_cache
    assert "episodic:ep_5" in svc._ref_cache
    assert f"episodic:ep_{cap + overflow - 1}" in svc._ref_cache


# --- 5. format_refs rendering ---

def test_format_refs_empty_returns_empty_string():
    assert OracleService.format_refs([]) == ""


def test_format_refs_caps_at_max_lines():
    refs = [
        MemoryRef(
            ref_id=f"episodic:e{i}", tier="episodic", score=0.5,
            snippet=f"snippet {i}", provenance="[episodic]",
        )
        for i in range(20)
    ]
    out = OracleService.format_refs(refs, max_lines=5)
    # Header + 5 refs + footer = 7 lines
    assert out.count("\n") == 6
    assert "=== MEMORY REFS ===" in out
    assert "=== END MEMORY REFS ===" in out
    assert "episodic:e0" in out
    assert "episodic:e6" not in out


# --- 6. _query_oracle_refs QUERY op ---

@pytest.mark.asyncio
async def test_query_oracle_refs_denies_below_enhanced_tier():
    runtime = MagicMock()
    runtime.oracle = MagicMock()
    spec = MagicMock()
    context = {
        "oracle_query_text": "alpha incident",
        "_recall_tier": RecallTier.BASIC,  # below ENHANCED
    }
    out = await _query_oracle_refs(runtime, spec, context)
    assert out == {"oracle_refs": ""}
    runtime.oracle.query_refs.assert_not_called()


@pytest.mark.asyncio
async def test_query_oracle_refs_emits_event_on_success():
    runtime = MagicMock()
    refs = [MemoryRef(
        ref_id="episodic:e1", tier="episodic", score=0.8,
        snippet="hello", provenance="[episodic]",
    )]
    runtime.oracle = MagicMock()
    runtime.oracle.query_refs = AsyncMock(return_value=refs)
    runtime.oracle.format_refs = MagicMock(return_value="=== MEMORY REFS ===\n[episodic] episodic:e1 (score: 0.80) hello\n=== END MEMORY REFS ===")
    emit_fn = MagicMock()
    spec = MagicMock()
    context = {
        "oracle_query_text": "alpha incident",
        "_recall_tier": RecallTier.ENHANCED,
        "_agent_id": "test_agent",
        "_emit_event_fn": emit_fn,
    }
    out = await _query_oracle_refs(runtime, spec, context)
    assert "episodic:e1" in out["oracle_refs"]
    emit_fn.assert_called_once()
    args = emit_fn.call_args[0]
    assert args[0] == EventType.MEMORY_REFS_DISPATCHED
    payload = args[1]
    assert payload["ref_count"] == 1
    assert payload["agent_id"] == "test_agent"


@pytest.mark.asyncio
async def test_query_oracle_refs_returns_empty_when_runtime_oracle_missing():
    runtime = MagicMock(spec=[])  # no `oracle` attr
    spec = MagicMock()
    context = {
        "oracle_query_text": "q",
        "_recall_tier": RecallTier.ENHANCED,
    }
    out = await _query_oracle_refs(runtime, spec, context)
    assert out == {"oracle_refs": ""}
