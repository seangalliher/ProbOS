"""BF-684: the records semantic index reached 20% of the corpus, permanently.

Measured on the reference vessel: 2,455 records, 500 indexed, 1,955
unreachable. Three defects compounded, and each hid the next.

**1. The backfill never ran twice.** ``runtime._wire_records_semantic_index``
short-circuited on a non-empty collection ("skipping backfill"), so after the
first bounded pass indexed its 500-record budget, every later boot skipped
entirely. Index-on-write does not close the gap — it only covers records
written *again*. The warning ("the remainder index on next write") read like a
deferral; it was permanent.

**2. The pass re-walked the same prefix.** ``entries[:limit]`` over a
deterministically sorted ``list_entries()`` took the same first 500 every time,
so even without defect 1 the pass could never advance.

**3. The keyword index became dead code.** ``_query_records`` treated keyword
as a *fallback* entered only when semantic returned nothing. The three seeded
``ship`` manuals match essentially any query, so semantic was never empty, so
keyword never ran. Enabling AD-1138 therefore *reduced* reachable recall from
the whole repository to the indexed subset — a retrieval feature that made
retrieval worse.

Defect 3 is why no test caught 1 and 2: every fixture in the suite is far
smaller than the 500 budget, so the bounded path was never exercised.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from probos.cognitive.oracle_service import OracleResult, _fuse_record_results
from probos.config import RecordsConfig
from probos.knowledge.records_store import RecordsStore
from probos.knowledge.semantic import SemanticKnowledgeLayer


@pytest.fixture
async def records(tmp_path: Path) -> RecordsStore:
    store = RecordsStore(
        RecordsConfig(repo_path=str(tmp_path / "ship-records"), auto_commit=False)
    )
    await store.initialize()
    return store


@pytest.fixture
async def layer(tmp_path: Path):
    sk = SemanticKnowledgeLayer(db_path=tmp_path / "semantic", episodic_memory=None)
    await sk.start()
    try:
        yield sk
    finally:
        await sk.stop()


async def _seed(store: RecordsStore, n: int, *, prefix: str = "note") -> list[str]:
    """A corpus deliberately larger than a single backfill budget."""
    paths = []
    for i in range(n):
        paths.append(await store.write_entry(
            author="scout",
            path=f"reports/{prefix}-{i:04d}.md",
            content=f"reactor telemetry sample {i}",
            message="seed",
            classification="ship",
        ))
    return paths


# ---------------------------------------------------------------------------
# The backfill resumes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_successive_passes_cover_a_corpus_larger_than_the_budget(
    records: RecordsStore, layer: Any,
) -> None:
    """The defect, stated directly. No existing fixture exceeded the budget,
    which is exactly why this went unnoticed."""
    await _seed(records, 12)

    first = await layer.reindex_records(records, limit=5)
    second = await layer.reindex_records(records, limit=5)
    third = await layer.reindex_records(records, limit=5)

    assert (first, second, third) == (5, 5, 2)
    assert layer.stats()["records"] == 12


@pytest.mark.asyncio
async def test_a_second_pass_reindexes_nothing_when_current(
    records: RecordsStore, layer: Any,
) -> None:
    """A pass with nothing to do must be cheap and report zero, so the caller
    can run it unconditionally on every boot."""
    await _seed(records, 6)

    assert await layer.reindex_records(records) == 6
    assert await layer.reindex_records(records) == 0
    assert layer.stats()["records"] == 6


@pytest.mark.asyncio
async def test_the_budget_is_spent_on_unindexed_records(
    records: RecordsStore, layer: Any,
) -> None:
    """Not on re-walking the prefix. With 6 already indexed and a budget of 5,
    a pass must reach 5 *new* records, not re-do the first 5."""
    await _seed(records, 6, prefix="old")
    await layer.reindex_records(records)
    await _seed(records, 5, prefix="new")

    assert await layer.reindex_records(records, limit=5) == 5
    assert layer.stats()["records"] == 11


@pytest.mark.asyncio
async def test_every_record_is_eventually_reachable(
    records: RecordsStore, layer: Any,
) -> None:
    """The property that actually matters: run to convergence and the last
    record is retrievable, not just counted."""
    await _seed(records, 9)
    while await layer.reindex_records(records, limit=4):
        pass

    rows = await layer.search(
        "reactor telemetry", types=["records"], limit=50, records_scope="ship",
    )
    found = {r.get("metadata", {}).get("path", "") for r in rows}
    assert "reports/note-0008.md" in found


@pytest.mark.asyncio
async def test_an_unreadable_id_lookup_reindexes_rather_than_strands(
    records: RecordsStore, layer: Any,
) -> None:
    """Fail-safe direction. Being wrong about what is indexed costs a wasted
    upsert (idempotent); being wrong the other way strands records silently."""
    await _seed(records, 3)

    class _NoGet:
        def __init__(self, inner: Any) -> None:
            self._inner = inner

        def get(self, **_kw: Any) -> Any:
            raise RuntimeError("id lookup unavailable")

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

    layer._collections["records"] = _NoGet(layer._collections["records"])
    assert await layer.reindex_records(records) == 3


@pytest.mark.asyncio
async def test_the_runtime_no_longer_skips_a_non_empty_collection() -> None:
    """Defect 1. The early-out made every later boot a no-op, so resumability
    alone would not have helped."""
    import inspect

    from probos.runtime import ProbOSRuntime

    source = inspect.getsource(ProbOSRuntime._wire_records_semantic_index)
    assert "skipping backfill" not in source
    assert "reindex_records" in source


# ---------------------------------------------------------------------------
# Both retrieval axes run
# ---------------------------------------------------------------------------

def _r(path: str, score: float) -> OracleResult:
    return OracleResult(
        source_tier="records", content=f"body {path}", score=score,
        metadata={"path": path}, provenance="[ship's records]",
    )


def test_a_keyword_only_hit_survives_a_non_empty_semantic_result() -> None:
    """Defect 3, stated directly. Under the old short-circuit a non-empty
    semantic result discarded the keyword axis wholesale, and the seeded ship
    manuals made it non-empty for essentially every query — so an exact-match
    record the keyword index found was unreachable."""
    fused = _fuse_record_results([_r("manual.md", 0.4)], [_r("exact-hit.md", 0.9)], k=10)
    assert {r.metadata["path"] for r in fused} == {"manual.md", "exact-hit.md"}


def test_agreement_between_axes_ranks_first() -> None:
    fused = _fuse_record_results(
        [_r("a.md", 0.30), _r("b.md", 0.90)],
        [_r("c.md", 0.80), _r("a.md", 0.10)],
        k=10,
    )
    assert fused[0].metadata["path"] == "a.md"


def test_a_record_on_both_axes_appears_once() -> None:
    fused = _fuse_record_results([_r("a.md", 0.5)], [_r("a.md", 0.7)], k=10)
    assert len(fused) == 1


def test_the_emitted_score_is_the_source_score_not_the_rrf_score() -> None:
    """Load-bearing. AD-1141's Sigma-context floor defaults to 0.35 and a
    rank-1-in-both RRF score is ~0.033, so emitting fused scores would filter
    out every record while appearing to work."""
    fused = _fuse_record_results([_r("a.md", 0.92)], [_r("a.md", 0.44)], k=10)
    assert fused[0].score == 0.92
    assert fused[0].score > 0.35


def test_a_single_axis_passes_through_in_its_own_order() -> None:
    """The common case on a fresh vessel: semantic disabled, empty, or failed.
    Order must be byte-identical to the old behaviour."""
    kw = [_r("a.md", 0.9), _r("b.md", 0.8), _r("c.md", 0.7)]
    assert [r.metadata["path"] for r in _fuse_record_results([], kw, k=10)] == [
        "a.md", "b.md", "c.md",
    ]
    sem = [_r("x.md", 0.1), _r("y.md", 0.2)]
    assert [r.metadata["path"] for r in _fuse_record_results(sem, [], k=10)] == [
        "x.md", "y.md",
    ]


def test_both_axes_empty_returns_empty() -> None:
    assert _fuse_record_results([], [], k=10) == []


def test_the_result_limit_is_honoured() -> None:
    fused = _fuse_record_results(
        [_r("a.md", 0.9), _r("b.md", 0.8)],
        [_r("c.md", 0.7), _r("d.md", 0.6)],
        k=2,
    )
    assert len(fused) == 2


def test_a_result_without_a_path_is_dropped_not_crashed() -> None:
    """``path`` is the records identity; a result lacking one cannot be fused
    or deduplicated, and must not take down the query."""
    nameless = OracleResult(
        source_tier="records", content="?", score=0.5, metadata={},
        provenance="[ship's records]",
    )
    fused = _fuse_record_results([nameless, _r("a.md", 0.4)], [_r("b.md", 0.3)], k=10)
    assert {r.metadata["path"] for r in fused} == {"a.md", "b.md"}


def test_the_semantic_payload_wins_for_a_record_on_both_axes() -> None:
    """The semantic axis carries the frontmatter sidecar; the keyword axis
    carries a plain snippet. Keeping the richer payload preserves provenance
    for BF-689's attribution requirements."""
    rich = OracleResult(
        source_tier="records", content="full", score=0.5,
        metadata={"path": "a.md", "frontmatter": {"author": "Ezri"}},
        provenance="[ship's records]",
    )
    plain = OracleResult(
        source_tier="records", content="snip", score=0.9,
        metadata={"path": "a.md"}, provenance="[ship's records]",
    )
    fused = _fuse_record_results([rich], [plain], k=10)
    assert fused[0].metadata.get("frontmatter", {}).get("author") == "Ezri"
    assert fused[0].score == 0.9  # score still the max across axes
